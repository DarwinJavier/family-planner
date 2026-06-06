"""Editable Opportunity Scout preferences and persisted feedback."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PREFERENCES_FILE = Path("data/opportunity_preferences.json")
STATE_FILE = Path("data/opportunity_state.json")

DEFAULT_PREFERENCES = {
    "family": {
        "interests": ["museum", "outdoor walk", "festival", "bookstore", "pool", "educational"],
        "disliked_categories": [],
        "max_travel_minutes": 35,
        "max_cost_per_activity": 100,
        "free_only": False,
        "weekly_activity_budget": 150,
        "monthly_activity_budget": 400,
        "preferred_indoor_outdoor": "either",
    },
    "older_child": {
        "age": 13,
        "interests": [
            "law", "debate", "leadership", "public speaking", "basketball",
            "business", "photography", "fitness", "swimming", "volunteering",
        ],
        "disliked_categories": [],
    },
    "younger_child": {
        "age": 8,
        "interests": ["crafts", "drawing", "music", "dance", "reading", "library", "creative workshop"],
        "disliked_categories": [],
    },
}


def _read_json(path: Path, fallback: dict) -> dict:
    if not path.exists():
        return deepcopy(fallback)
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else deepcopy(fallback)
    except (OSError, json.JSONDecodeError):
        return deepcopy(fallback)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def load_preferences() -> dict:
    preferences = _read_json(PREFERENCES_FILE, DEFAULT_PREFERENCES)
    for profile, defaults in DEFAULT_PREFERENCES.items():
        preferences.setdefault(profile, deepcopy(defaults))
        for key, value in defaults.items():
            preferences[profile].setdefault(key, deepcopy(value))
    return preferences


def update_preferences(profile: str, updates: dict) -> dict:
    preferences = load_preferences()
    if profile not in preferences:
        raise ValueError(f"Unknown preference profile: {profile}")
    allowed = set(DEFAULT_PREFERENCES[profile])
    preferences[profile].update({key: value for key, value in updates.items() if key in allowed})
    _write_json(PREFERENCES_FILE, preferences)
    return preferences[profile]


def add_interest(profile: str, interest: str) -> dict:
    preferences = load_preferences()
    if profile not in preferences:
        raise ValueError(f"Unknown preference profile: {profile}")
    interests = list(preferences[profile].get("interests", []))
    normalized = " ".join(interest.lower().split())
    if normalized and normalized not in interests:
        interests.append(normalized)
    return update_preferences(profile, {"interests": interests})


def hide_category(category: str) -> dict:
    preferences = load_preferences()
    categories = list(preferences["family"].get("disliked_categories", []))
    normalized = " ".join(category.lower().split())
    if normalized and normalized not in categories:
        categories.append(normalized)
    return update_preferences("family", {"disliked_categories": categories})


def load_state() -> dict:
    state = _read_json(STATE_FILE, {"feedback": {}, "recommendations": {}})
    state.setdefault("feedback", {})
    state.setdefault("recommendations", {})
    return state


def save_state(state: dict) -> None:
    _write_json(STATE_FILE, state)


def record_feedback(activity_id: str, value: str, categories: tuple[str, ...], tz: ZoneInfo) -> None:
    state = load_state()
    state["feedback"][activity_id] = {
        "value": value,
        "categories": list(categories),
        "recorded_at": datetime.now(tz).isoformat(),
    }
    save_state(state)
