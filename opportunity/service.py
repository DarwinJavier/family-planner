"""Opportunity Scout free-time detection, filtering, scoring, and feedback."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from config.env import get_env
from gcal.client import get_events, get_overlapping_events
from .models import ExternalEvent, FreeWindow, Recommendation
from .preferences import load_preferences, load_state, record_feedback, save_state
from .sources import ConfiguredWebLeadSource, EventSource, MockOttawaEventSource, search_sources

CONFIG_FILE = Path(__file__).parent.parent / "config" / "opportunity_scout.yaml"
POSITIVE_FEEDBACK = {"accepted", "saved", "more_like_this"}
NEGATIVE_FEEDBACK = {
    "dismissed", "not_relevant", "too_expensive", "too_far", "wrong_age",
    "wrong_time", "already_attended", "hide_category",
}


def _config() -> dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def _parse_clock(value: str) -> time:
    return time.fromisoformat(value)


def _event_bounds(event: dict, tz: ZoneInfo) -> tuple[datetime, datetime] | None:
    start_raw = event.get("start", {}).get("dateTime")
    end_raw = event.get("end", {}).get("dateTime")
    if not start_raw or not end_raw:
        return None
    try:
        return (
            datetime.fromisoformat(start_raw).astimezone(tz),
            datetime.fromisoformat(end_raw).astimezone(tz),
        )
    except ValueError:
        return None


def _event_members(event: dict) -> set[str]:
    raw = event.get("extendedProperties", {}).get("private", {}).get("family_members", "")
    members = {member.strip() for member in raw.split(",") if member.strip()}
    return members or {"family", "older_child", "younger_child", "parents"}


def _merge_busy_periods(periods: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[list[datetime]] = []
    for start, end in sorted(periods):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def detect_free_windows(
    events: list[dict],
    start: datetime,
    end: datetime,
    config: dict | None = None,
    required_members: tuple[str, ...] = ("family",),
) -> list[FreeWindow]:
    """Return conservative full-family windows after events and protected time."""
    config = config or _config()
    availability = config["availability"]
    minimum = int(availability["minimum_useful_minutes"])
    travel = int(availability["default_travel_minutes"])
    max_commitments = int(availability["maximum_commitments_per_day"])
    tz = start.tzinfo
    if tz is None:
        raise ValueError("start must include a timezone")

    required = set(required_members)
    event_periods = [
        (*bounds, _event_members(event))
        for event in events
        if (bounds := _event_bounds(event, tz))
        and (required.intersection(_event_members(event)) or "family" in required)
    ]
    windows: list[FreeWindow] = []
    day = start.date()
    while day <= end.date():
        day_start = datetime.combine(day, _parse_clock(availability["day_start"]), tzinfo=tz)
        day_end = datetime.combine(day, _parse_clock(availability["day_end"]), tzinfo=tz)
        range_start = max(day_start, start)
        range_end = min(day_end, end)
        if range_end <= range_start:
            day += timedelta(days=1)
            continue

        day_events = [(s, e) for s, e, _members in event_periods if s.date() == day or e.date() == day]
        if len(day_events) >= max_commitments:
            day += timedelta(days=1)
            continue

        busy = [(s - timedelta(minutes=travel), e + timedelta(minutes=travel)) for s, e in day_events]
        for protected in availability.get("protected_periods", []):
            if day.weekday() in protected.get("weekdays", []):
                busy.append((
                    datetime.combine(day, _parse_clock(protected["start"]), tzinfo=tz),
                    datetime.combine(day, _parse_clock(protected["end"]), tzinfo=tz),
                ))

        cursor = range_start
        for busy_start, busy_end in _merge_busy_periods(busy):
            busy_start = max(busy_start, range_start)
            busy_end = min(busy_end, range_end)
            if busy_start > cursor and (busy_start - cursor).total_seconds() >= minimum * 60:
                windows.append(FreeWindow(cursor, busy_start, available_members=required_members, kind="full_family" if "family" in required else "individual"))
            cursor = max(cursor, busy_end)
        if range_end > cursor and (range_end - cursor).total_seconds() >= minimum * 60:
            windows.append(FreeWindow(cursor, range_end, available_members=required_members, kind="full_family" if "family" in required else "individual"))
        day += timedelta(days=1)

    return windows


def _matching_window(activity: ExternalEvent, windows: list[FreeWindow], preparation_minutes: int) -> FreeWindow | None:
    occupied_start = activity.start - timedelta(minutes=activity.travel_minutes + preparation_minutes)
    occupied_end = activity.end + timedelta(minutes=activity.travel_minutes)
    return next(
        (window for window in windows if occupied_start >= window.start and occupied_end <= window.end),
        None,
    )


def _age_fit(activity: ExternalEvent, preferences: dict) -> bool:
    member_names = set(activity.relevant_members)
    if "family" in member_names:
        member_names.update({"older_child", "younger_child"})
    ages = [
        preferences[name].get("age")
        for name in member_names
        if name in preferences and preferences[name].get("age") is not None
    ]
    if not ages:
        return True
    return all(
        (activity.min_age is None or age >= activity.min_age)
        and (activity.max_age is None or age <= activity.max_age)
        for age in ages
    )


def _feedback_adjustment(activity: ExternalEvent, state: dict) -> tuple[float, bool]:
    feedback = state.get("feedback", {})
    direct = feedback.get(activity.id, {}).get("value")
    if direct in NEGATIVE_FEEDBACK:
        return -100, True
    if direct in POSITIVE_FEEDBACK:
        return 8, False

    adjustment = 0.0
    categories = set(activity.categories)
    for item in feedback.values():
        overlap = categories.intersection(item.get("categories", []))
        if not overlap:
            continue
        if item.get("value") in POSITIVE_FEEDBACK:
            adjustment += min(4, len(overlap))
        elif item.get("value") in NEGATIVE_FEEDBACK:
            adjustment -= min(6, len(overlap) * 2)
    return adjustment, False


def score_activity(
    activity: ExternalEvent,
    window: FreeWindow,
    preferences: dict,
    state: dict,
    config: dict | None = None,
    now: datetime | None = None,
) -> Recommendation | None:
    config = config or _config()
    now = now or datetime.now(activity.start.tzinfo)
    weights = config["scoring"]
    family = preferences["family"]
    categories = set(activity.categories)
    disliked = set(family.get("disliked_categories", []))
    for profile in preferences.values():
        disliked.update(profile.get("disliked_categories", []))
    if categories.intersection(disliked) or not _age_fit(activity, preferences):
        return None
    if family.get("free_only") and activity.total_cost > 0:
        return None
    if activity.total_cost > float(family.get("max_cost_per_activity", 999999)):
        return None
    if activity.travel_minutes > int(family.get("max_travel_minutes", 999)):
        return None
    if activity.availability_status in {"cancelled", "full", "sold_out", "unavailable"}:
        return None
    if activity.registration_required and activity.registration_deadline and activity.registration_deadline < now:
        return None

    feedback_score, blocked = _feedback_adjustment(activity, state)
    if blocked:
        return None

    interests = set(family.get("interests", []))
    for member in activity.relevant_members:
        interests.update(preferences.get(member, {}).get("interests", []))
    matches = categories.intersection(interests)

    occupied_minutes = (
        int((activity.end - activity.start).total_seconds() // 60)
        + activity.travel_minutes * 2
        + int(config["availability"]["preparation_minutes"])
    )
    fit_ratio = min(1, occupied_minutes / max(1, window.duration_minutes))
    score = weights["calendar_fit"] * (0.7 + 0.3 * fit_ratio)
    score += weights["interest_match"] * min(1, len(matches) / 2)
    score += weights["age_suitability"]
    score += weights["travel"] * max(0, 1 - activity.travel_minutes / max(1, family["max_travel_minutes"]))
    score += weights["cost"] * max(0, 1 - activity.total_cost / max(1, family["max_cost_per_activity"]))
    score += weights["confidence"] * activity.confidence
    score += weights["novelty"] + feedback_score

    window_label = "family" if window.kind == "full_family" else "/".join(window.available_members)
    reasons = [
        f"fits an open {window.duration_minutes // 60}-hour {window_label} window",
        f"is about {activity.travel_minutes} minutes away",
    ]
    if matches:
        reasons.append(f"matches {', '.join(sorted(matches)[:3])}")
    if activity.total_cost == 0:
        reasons.append("is free")
    else:
        reasons.append(f"has an estimated total family cost of ${activity.total_cost:.0f}")

    warnings: list[str] = []
    if activity.confidence < 0.75:
        warnings.append("Details come from the Phase 1 mock source and must be verified.")
    if activity.availability_status == "unknown":
        warnings.append("Registration or availability status is unknown.")
    if activity.weather_sensitive:
        warnings.append("Outdoor activity; weather may affect the plan.")

    return Recommendation(
        activity=activity,
        window=window,
        score=round(score, 1),
        explanation="Strong match because it " + ", ".join(reasons) + ".",
        warnings=tuple(warnings),
    )


def _recommendation_from_dict(raw: dict) -> Recommendation:
    return Recommendation(
        activity=ExternalEvent.from_dict(raw["activity"]),
        window=FreeWindow(
            start=datetime.fromisoformat(raw["window"]["start"]),
            end=datetime.fromisoformat(raw["window"]["end"]),
            available_members=tuple(raw["window"].get("available_members", ["family"])),
            kind=raw["window"].get("kind", "full_family"),
        ),
        score=float(raw["score"]),
        explanation=raw["explanation"],
        warnings=tuple(raw.get("warnings", [])),
    )


def discover_recommendations(
    now: datetime | None = None,
    calendar_events: list[dict] | None = None,
    sources: list[EventSource] | None = None,
    limit: int | None = None,
) -> tuple[list[Recommendation], list[str]]:
    config = _config()
    tz = ZoneInfo(get_env("TIMEZONE", "America/Toronto"))
    now = now or datetime.now(tz)
    end = now + timedelta(days=int(config["availability"]["planning_days"]))
    events = calendar_events if calendar_events is not None else get_events(now, end)
    windows_by_members: dict[tuple[str, ...], list[FreeWindow]] = {
        ("family",): detect_free_windows(events, now, end, config),
        ("older_child",): detect_free_windows(events, now, end, config, required_members=("older_child",)),
        ("younger_child",): detect_free_windows(events, now, end, config, required_members=("younger_child",)),
    }
    if not any(windows_by_members.values()):
        return [], ["No meaningful free family windows were found."]

    activities, warnings = search_sources(
        sources or [ConfiguredWebLeadSource(), MockOttawaEventSource()],
        now,
        end,
    )
    preferences = load_preferences()
    state = load_state()
    existing_titles = {event.get("summary", "").strip().lower() for event in events}
    recommendations: list[Recommendation] = []
    prep = int(config["availability"]["preparation_minutes"])
    for activity in activities:
        if activity.title.lower() in existing_titles:
            continue
        member_key = ("family",) if "family" in activity.relevant_members else tuple(
            member for member in activity.relevant_members if member in {"older_child", "younger_child"}
        )
        if not member_key:
            member_key = ("family",)
        windows = windows_by_members.get(member_key)
        if windows is None:
            windows = detect_free_windows(events, now, end, config, required_members=member_key)
            windows_by_members[member_key] = windows
        window = _matching_window(activity, windows, prep)
        if not window:
            continue
        recommendation = score_activity(activity, window, preferences, state, config, now=now)
        if recommendation:
            recommendations.append(recommendation)

    recommendations.sort(key=lambda recommendation: recommendation.score, reverse=True)
    result = recommendations[: limit or int(config["recommendations"]["default_limit"])]
    state["recommendations"] = {item.activity.id: item.to_dict() for item in result}
    save_state(state)
    if not result:
        warnings.append("No activities fit the available windows and current preferences.")
    return result, warnings


def get_recommendation(activity_id: str) -> Recommendation | None:
    raw = load_state().get("recommendations", {}).get(activity_id)
    return _recommendation_from_dict(raw) if raw else None


def save_recommendation(activity_id: str) -> Recommendation | None:
    recommendation = get_recommendation(activity_id)
    if recommendation:
        record_feedback(activity_id, "saved", recommendation.activity.categories, recommendation.activity.start.tzinfo)
    return recommendation


def recommend_more_like(activity_id: str) -> Recommendation | None:
    recommendation = get_recommendation(activity_id)
    if recommendation:
        record_feedback(activity_id, "more_like_this", recommendation.activity.categories, recommendation.activity.start.tzinfo)
    return recommendation


def dismiss_recommendation(activity_id: str, reason: str = "dismissed") -> Recommendation | None:
    recommendation = get_recommendation(activity_id)
    if recommendation:
        value = reason if reason in NEGATIVE_FEEDBACK else "dismissed"
        record_feedback(activity_id, value, recommendation.activity.categories, recommendation.activity.start.tzinfo)
    return recommendation


def accept_recommendation(activity_id: str) -> Recommendation | None:
    recommendation = get_recommendation(activity_id)
    if recommendation:
        record_feedback(activity_id, "accepted", recommendation.activity.categories, recommendation.activity.start.tzinfo)
    return recommendation


def format_recommendations(recommendations: list[Recommendation], warnings: list[str] | None = None) -> str:
    if not recommendations:
        detail = f" {' '.join(warnings or [])}".strip()
        return f"No strong Opportunity Scout matches right now.{detail}".strip()

    lines = ["Opportunity Scout found these realistic matches:"]
    for item in recommendations:
        activity = item.activity
        lines.extend([
            "",
            f"{activity.title} [{activity.id}]",
            f"{activity.start.strftime('%a %b %d, %I:%M %p').lstrip('0')} at {activity.venue}",
            f"Why it fits: {item.explanation}",
            f"Relevant family members: {', '.join(activity.relevant_members)}",
            f"Travel: ~{activity.travel_minutes} min | Estimated family cost: ${activity.total_cost:.0f} | Score: {item.score}",
            f"Source: {activity.source_url}",
        ])
        if item.warnings:
            lines.append(f"Check first: {' '.join(item.warnings)}")
    lines.append("\nUse /scout_add ID, /scout_save ID, or /scout_dismiss ID.")
    return "\n".join(lines)


def build_calendar_proposal(activity_id: str) -> tuple[dict, list[str]] | None:
    recommendation = get_recommendation(activity_id)
    if not recommendation:
        return None
    activity = recommendation.activity
    prep = int(_config()["availability"]["preparation_minutes"])
    start = activity.start - timedelta(minutes=activity.travel_minutes + prep)
    end = activity.end + timedelta(minutes=activity.travel_minutes)
    description = (
        f"{activity.description}\n\n"
        f"Official source: {activity.source_url}\n"
        f"Activity time: {activity.start.isoformat()} to {activity.end.isoformat()}\n"
        f"Includes {prep} min preparation and {activity.travel_minutes} min travel each way.\n"
        f"Estimated total family cost: ${activity.total_cost:.2f}\n"
        f"Relevant family members: {', '.join(activity.relevant_members)}\n\n"
        "[agent]\n"
        "type: opportunity_scout\n"
        f"opportunity_id: {activity.id}\n"
        f"source: {activity.source}\n"
        "[/agent]"
    )
    proposal = {
        "title": activity.title,
        "start_datetime": start.isoformat(),
        "end_datetime": end.isoformat(),
        "description": description,
    }
    overlaps = get_overlapping_events(start, end)
    conflicts = [event.get("summary", "(no title)") for event in overlaps]
    return proposal, conflicts
