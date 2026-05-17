"""Small persistent state for proactive follow-ups.

This keeps Juanito helpful without becoming noisy:
- one open conversation loop per Telegram user
- one post-event follow-up per Google Calendar event
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

STATE_FILE = Path(__file__).with_name("proactivity_state.json")


def _now(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {"open_loops": {}, "followed_events": {}}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"open_loops": {}, "followed_events": {}}
    data.setdefault("open_loops", {})
    data.setdefault("followed_events", {})
    return data


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _trim(text: str, limit: int = 180) -> str:
    text = " ".join((text or "").split())
    return text[: limit - 1] + "…" if len(text) > limit else text


def _looks_like_open_loop(reply: str) -> bool:
    reply_lower = reply.lower()
    if "?" in reply or "¿" in reply:
        return True
    return bool(
        re.search(
            r"\b(confirm|confirmar|confírm|tell me|let me know|avísame|me dices|quieres que|should i|shall i)\b",
            reply_lower,
        )
    )


def record_conversation_turn(
    user_id: int,
    user_name: str,
    user_text: str,
    assistant_reply: str,
    tz: ZoneInfo,
) -> None:
    """Resolve the user's previous loop, then store a new one if Juanito asked for input."""
    state = _load_state()
    user_key = str(user_id)
    state["open_loops"].pop(user_key, None)

    if _looks_like_open_loop(assistant_reply):
        due_at = _now(tz) + timedelta(hours=3)
        state["open_loops"][user_key] = {
            "user_name": user_name,
            "user_text": _trim(user_text),
            "assistant_reply": _trim(assistant_reply),
            "due_at": due_at.isoformat(),
            "created_at": _now(tz).isoformat(),
        }

    _save_state(state)


def due_open_loops(tz: ZoneInfo, limit: int = 2) -> list[dict]:
    state = _load_state()
    now = _now(tz)
    due: list[dict] = []
    for user_key, loop in list(state["open_loops"].items()):
        try:
            due_at = datetime.fromisoformat(loop["due_at"])
        except (KeyError, ValueError):
            state["open_loops"].pop(user_key, None)
            continue
        if due_at <= now:
            loop["user_id"] = user_key
            due.append(loop)
    due.sort(key=lambda loop: loop.get("due_at", ""))
    _save_state(state)
    return due[:limit]


def mark_open_loop_followed(user_id: str) -> None:
    state = _load_state()
    state["open_loops"].pop(str(user_id), None)
    _save_state(state)


def event_was_followed(event_id: str) -> bool:
    state = _load_state()
    return event_id in state["followed_events"]


def mark_event_followed(event_id: str, tz: ZoneInfo) -> None:
    state = _load_state()
    state["followed_events"][event_id] = _now(tz).isoformat()
    _save_state(state)
