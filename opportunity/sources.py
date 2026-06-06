"""Extensible event-source adapters for Opportunity Scout."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, time, timedelta
from typing import Protocol

from openai import OpenAI

from config.env import get_env
from .models import ExternalEvent
from .source_registry import load_source_registry, source_research_guidance

logger = logging.getLogger(__name__)


class EventSource(Protocol):
    name: str

    def search_events(self, start: datetime, end: datetime) -> list[ExternalEvent]:
        """Return validated activities occurring in the requested range."""


def _response_text(response) -> str:
    for item in response.output:
        if item.type == "message":
            for content in item.content:
                if content.type == "output_text":
                    return content.text.strip()
    return ""


def _json_array(text: str) -> list[dict]:
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        return []
    data = json.loads(match.group(0))
    return data if isinstance(data, list) else []


class ConfiguredWebLeadSource:
    """Web-search adapter for configured public editorial and official lead sources."""

    name = "Configured public Ottawa sources"

    def search_events(self, start: datetime, end: datetime) -> list[ExternalEvent]:
        guidance = source_research_guidance()
        prompt = f"""Find real Ottawa-area family activities occurring between {start.isoformat()} and {end.isoformat()}.

Search these configured public sources as discovery leads:
{guidance}

Rules:
- Do not access private/login-gated content, scrape Facebook groups, or bypass access controls.
- Editorial sources such as Ottawa Is Not Boring are leads. Verify dates, price, registration, and availability against an official event page whenever possible.
- Return only events with a specific start and end time in the requested date range.
- Return a JSON array only, with at most 8 objects.
- Each object must contain: id, title, description, source, source_url, venue, address, start, end, categories, min_age, max_age, indoor_outdoor, registration_required, registration_deadline, availability_status, admission_cost, parking_cost, incidental_cost, travel_minutes, relevant_members, weather_sensitive, confidence, last_verified_at.
- Use ISO 8601 timestamps with an Ottawa timezone offset.
- Use HTTPS source URLs found in search. Do not invent facts or URLs.
- Use confidence no higher than 0.7 for editorial leads or incomplete data."""
        response = OpenAI(api_key=get_env("OPENAI_API_KEY")).responses.create(
            model=get_env("OPENAI_RESEARCH_MODEL", "gpt-4o"),
            tools=[{"type": "web_search_preview"}],
            input=prompt,
        )
        events: list[ExternalEvent] = []
        for raw in _json_array(_response_text(response)):
            try:
                event = ExternalEvent.from_dict(raw)
            except (TypeError, ValueError, KeyError) as exc:
                logger.warning("Discarded invalid configured-source event: %s", exc)
                continue
            if start <= event.start < end:
                events.append(event)
        return events


class MockOttawaEventSource:
    """Deterministic Phase 1 source shaped like future permitted provider adapters."""

    name = "Opportunity Scout Mock Ottawa"
    discovery_leads = load_source_registry()

    def search_events(self, start: datetime, end: datetime) -> list[ExternalEvent]:
        templates = [
            {
                "slug": "library-crafts",
                "title": "Barrhaven Library Creative Workshop",
                "description": "A guided crafts and drawing session for children and families.",
                "venue": "Ruth E. Dickinson Library",
                "address": "100 Malvern Dr, Ottawa, ON",
                "weekday": 5,
                "start_time": time(10, 30),
                "duration": 90,
                "categories": ["crafts", "drawing", "library", "creative workshop"],
                "min_age": 6,
                "max_age": 14,
                "indoor_outdoor": "indoor",
                "admission_cost": 0,
                "parking_cost": 0,
                "incidental_cost": 8,
                "travel_minutes": 12,
                "relevant_members": ["younger_child", "family"],
                "source_url": "https://biblioottawalibrary.ca/en/program",
            },
            {
                "slug": "museum-family",
                "title": "Family Discovery Afternoon",
                "description": "Hands-on exhibits and educational activities for the whole family.",
                "venue": "Canada Science and Technology Museum",
                "address": "1867 St Laurent Blvd, Ottawa, ON",
                "weekday": 5,
                "start_time": time(13, 0),
                "duration": 150,
                "categories": ["museum", "educational", "science"],
                "min_age": 5,
                "max_age": 99,
                "indoor_outdoor": "indoor",
                "admission_cost": 45,
                "parking_cost": 12,
                "incidental_cost": 18,
                "travel_minutes": 28,
                "relevant_members": ["family"],
                "source_url": "https://ingeniumcanada.org/scitech",
            },
            {
                "slug": "debate-clinic",
                "title": "Youth Debate and Leadership Clinic",
                "description": "A practical public-speaking and debate session for teens.",
                "venue": "Nepean Creative Arts Centre",
                "address": "35 Stafford Rd, Ottawa, ON",
                "weekday": 6,
                "start_time": time(14, 0),
                "duration": 120,
                "categories": ["debate", "leadership", "public speaking"],
                "min_age": 12,
                "max_age": 17,
                "indoor_outdoor": "indoor",
                "registration_required": True,
                "availability_status": "available",
                "admission_cost": 20,
                "parking_cost": 0,
                "incidental_cost": 5,
                "travel_minutes": 20,
                "relevant_members": ["older_child"],
                "source_url": "https://ottawa.ca/en/recreation-and-parks",
            },
            {
                "slug": "greenbelt-walk",
                "title": "Greenbelt Family Nature Walk",
                "description": "A relaxed outdoor walk with room for photography and exploration.",
                "venue": "NCC Greenbelt",
                "address": "Ottawa Greenbelt, Ottawa, ON",
                "weekday": 6,
                "start_time": time(10, 0),
                "duration": 120,
                "categories": ["outdoor walk", "photography", "fitness"],
                "min_age": 6,
                "max_age": 99,
                "indoor_outdoor": "outdoor",
                "admission_cost": 0,
                "parking_cost": 0,
                "incidental_cost": 10,
                "travel_minutes": 18,
                "relevant_members": ["family", "older_child"],
                "weather_sensitive": True,
                "source_url": "https://ncc-ccn.gc.ca/places/greenbelt",
            },
        ]

        events: list[ExternalEvent] = []
        day = start.date()
        while day <= end.date():
            for template in templates:
                if day.weekday() != template["weekday"]:
                    continue
                event_start = datetime.combine(day, template["start_time"], tzinfo=start.tzinfo)
                event_end = event_start + timedelta(minutes=template["duration"])
                if event_end < start or event_start >= end:
                    continue
                raw = {
                    **template,
                    "id": f"mock-{template['slug']}-{day.isoformat()}",
                    "source": self.name,
                    "start": event_start,
                    "end": event_end,
                    "registration_deadline": event_start - timedelta(days=2)
                    if template.get("registration_required")
                    else None,
                    "confidence": 0.65,
                    "discovered_at": start,
                    "last_verified_at": start,
                }
                events.append(ExternalEvent.from_dict(raw))
            day += timedelta(days=1)
        return events


def search_sources(
    sources: list[EventSource],
    start: datetime,
    end: datetime,
) -> tuple[list[ExternalEvent], list[str]]:
    activities: list[ExternalEvent] = []
    warnings: list[str] = []
    for source in sources:
        try:
            activities.extend(source.search_events(start, end))
        except Exception as exc:
            logger.error("Opportunity source %s failed: %s", source.name, exc, exc_info=True)
            warnings.append(f"{source.name} is temporarily unavailable.")
    return activities, warnings
