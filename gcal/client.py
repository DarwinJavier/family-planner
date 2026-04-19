"""Calendar client functions such as get_events and create_event."""
import os
import yaml
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from gcal.auth import get_credentials
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def _service():
    """Build and return an authenticated Google Calendar API service."""
    return build("calendar", "v3", credentials=get_credentials())


def _calendar_id() -> str:
    cal_id = os.environ.get("GOOGLE_CALENDAR_ID")
    if not cal_id:
        raise RuntimeError("GOOGLE_CALENDAR_ID is not set in .env")
    return cal_id


def _timezone() -> str:
    return os.environ.get("TIMEZONE", "America/Toronto")


def get_events(start: datetime, end: datetime) -> list[dict]:
    """Return all calendar events between start and end (timezone-aware datetimes)."""
    try:
        result = (
            _service()
            .events()
            .list(
                calendarId=_calendar_id(),
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = result.get("items", [])
        logger.info("Fetched %d events from Google Calendar.", len(events))
        return events
    except HttpError as e:
        logger.error("Google Calendar API error fetching events: %s", e)
        raise


def get_next_grocery_event() -> dict | None:
    """Return the next upcoming event that matches grocery keywords, or None."""
    rules_path = Path(__file__).parent.parent / "config" / "rules.yaml"
    with open(rules_path) as f:
        rules = yaml.safe_load(f)
    keywords = rules["event_types"]["grocery"]["keywords"]

    tz = ZoneInfo(_timezone())
    now = datetime.now(tz)
    future = now + timedelta(days=30)

    events = get_events(now, future)
    for event in events:
        title = event.get("summary", "").lower()
        if any(kw in title for kw in keywords):
            return event
    return None


def get_overlapping_events(start: datetime, end: datetime, exclude_id: str | None = None) -> list[dict]:
    """Return events that overlap with the given window, optionally excluding one by ID."""
    events = get_events(start, end)
    if exclude_id:
        events = [e for e in events if e.get("id") != exclude_id]
    return events


def delete_event(event_id: str) -> None:
    """Delete a calendar event by its ID."""
    try:
        _service().events().delete(calendarId=_calendar_id(), eventId=event_id).execute()
        logger.info("Deleted event id=%s", event_id)
    except HttpError as e:
        logger.error("Google Calendar API error deleting event %s: %s", event_id, e)
        raise


def update_event(
    event_id: str,
    title: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    description: str | None = None,
) -> dict:
    """Partially update a calendar event. Only provided fields are changed."""
    tz = _timezone()
    body: dict = {}
    if title is not None:
        body["summary"] = title
    if description is not None:
        body["description"] = description
    if start is not None:
        body["start"] = {"dateTime": start.isoformat(), "timeZone": tz}
    if end is not None:
        body["end"] = {"dateTime": end.isoformat(), "timeZone": tz}
    try:
        event = (
            _service()
            .events()
            .patch(calendarId=_calendar_id(), eventId=event_id, body=body)
            .execute()
        )
        logger.info("Updated event id=%s", event_id)
        return event
    except HttpError as e:
        logger.error("Google Calendar API error updating event %s: %s", event_id, e)
        raise


def create_event(
    title: str,
    start: datetime,
    end: datetime,
    description: str = "",
    rrule: str | None = None,
) -> dict:
    """Create a calendar event and return the created event object.

    Pass rrule (e.g. 'RRULE:FREQ=WEEKLY;BYDAY=SU;COUNT=13') for recurring events.
    """
    tz = _timezone()
    body = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": tz},
        "end": {"dateTime": end.isoformat(), "timeZone": tz},
    }
    if rrule:
        body["recurrence"] = [rrule]
    try:
        event = _service().events().insert(calendarId=_calendar_id(), body=body).execute()
        logger.info("Created event '%s' (id=%s)", title, event.get("id"))
        return event
    except HttpError as e:
        logger.error("Google Calendar API error creating event: %s", e)
        raise
