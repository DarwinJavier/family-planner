"""Tool definitions and handlers for the agent's calendar interactions."""
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import logging
from dotenv import load_dotenv
import yaml
from pathlib import Path
from gcal.client import get_events, create_event, delete_event, update_event, get_overlapping_events
from storage.shopping_list import read_shopping_list, write_shopping_list

load_dotenv()
logger = logging.getLogger(__name__)

# Tool schemas in OpenAI function-calling format.
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_calendar",
            "description": (
                "Read family calendar events for a given date range. "
                "Use this to answer questions like 'what's on today?' or 'what do we have this week?'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start of the range in ISO 8601 format, e.g. '2025-05-01'",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End of the range (exclusive) in ISO 8601 format, e.g. '2025-05-08'",
                    },
                },
                "required": ["start_date", "end_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": (
                "Create a new event on the family Google Calendar. "
                "Always confirm with the user before calling this tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Event title"},
                    "start_datetime": {
                        "type": "string",
                        "description": "Event start in ISO 8601 format, e.g. '2025-05-02T09:00:00'",
                    },
                    "end_datetime": {
                        "type": "string",
                        "description": "Event end in ISO 8601 format, e.g. '2025-05-02T10:00:00'",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional event description or notes",
                    },
                    "rrule": {
                        "type": "string",
                        "description": (
                            "Optional recurrence rule in RRULE format for repeating events. "
                            "Examples: 'RRULE:FREQ=WEEKLY;BYDAY=SU;COUNT=13' (every Sunday for 13 weeks), "
                            "'RRULE:FREQ=DAILY;COUNT=5' (every day for 5 days). "
                            "Use this instead of creating multiple separate events."
                        ),
                    },
                },
                "required": ["title", "start_datetime", "end_datetime"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_calendar_event",
            "description": (
                "Delete an existing event from the family Google Calendar by its ID. "
                "Always confirm with the user before calling this tool. "
                "Use read_calendar first to find the event ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "The Google Calendar event ID (from read_calendar output)",
                    },
                    "title": {
                        "type": "string",
                        "description": "Event title — used only for the confirmation message",
                    },
                },
                "required": ["event_id", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_calendar_event",
            "description": (
                "Edit an existing event on the family Google Calendar. "
                "Only the fields you provide will be changed — omit fields you want to keep. "
                "Always confirm with the user before calling this tool. "
                "Use read_calendar first to find the event ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "The Google Calendar event ID (from read_calendar output)",
                    },
                    "title": {
                        "type": "string",
                        "description": "New event title (omit to keep existing)",
                    },
                    "start_datetime": {
                        "type": "string",
                        "description": "New start in ISO 8601 format (omit to keep existing)",
                    },
                    "end_datetime": {
                        "type": "string",
                        "description": "New end in ISO 8601 format (omit to keep existing)",
                    },
                    "description": {
                        "type": "string",
                        "description": "New description (omit to keep existing)",
                    },
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_shopping_list",
            "description": (
                "Read, add to, or clear the family shopping list. "
                "The list lives inside the next upcoming grocery calendar event. "
                "Use 'view' to read it, 'add' to append items, 'clear' to empty it. "
                "Always confirm with the user before clearing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["view", "add", "clear"],
                        "description": "Operation to perform on the list",
                    },
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Items to add — only used with 'add' action",
                    },
                },
                "required": ["action"],
            },
        },
    },
]


def _conflict_note(new_title: str, start: datetime, end: datetime, new_event_id: str) -> str:
    """Return a conflict warning string, or empty string if no conflicts."""
    overlapping = get_overlapping_events(start, end, exclude_id=new_event_id)
    if not overlapping:
        return ""

    rules_path = Path(__file__).parent.parent / "config" / "rules.yaml"
    with open(rules_path) as f:
        rules = yaml.safe_load(f)
    pickup_keywords = rules["event_types"]["pickup_required"]["keywords"]

    overlap_titles = [e.get("summary", "(no title)") for e in overlapping]
    all_titles = [new_title] + overlap_titles
    needs_pickup = any(
        kw in title.lower()
        for title in all_titles
        for kw in pickup_keywords
    )

    note = f"\n\n⚠️ Heads up — this overlaps with: {', '.join(overlap_titles)}."
    if needs_pickup:
        note += " Someone may need to arrange pickup!"
    return note


def handle_tool_call(tool_name: str, tool_input: dict) -> str:
    """Execute a tool call requested by the agent and return the result as a string."""
    tz = ZoneInfo(os.environ.get("TIMEZONE", "America/Toronto"))

    if tool_name == "read_calendar":
        start = datetime.fromisoformat(tool_input["start_date"]).replace(tzinfo=tz)
        end = datetime.fromisoformat(tool_input["end_date"]).replace(tzinfo=tz)
        events = get_events(start, end)
        if not events:
            return "No events found in that date range."
        lines = []
        for e in events:
            time = e["start"].get("dateTime", e["start"].get("date", "all-day"))
            event_id = e.get("id", "unknown")
            lines.append(f"- [id:{event_id}] {time}: {e.get('summary', '(no title)')}")
        return "\n".join(lines)

    if tool_name == "create_calendar_event":
        start = datetime.fromisoformat(tool_input["start_datetime"]).replace(tzinfo=tz)
        end = datetime.fromisoformat(tool_input["end_datetime"]).replace(tzinfo=tz)
        event = create_event(
            title=tool_input["title"],
            start=start,
            end=end,
            description=tool_input.get("description", ""),
            rrule=tool_input.get("rrule"),
        )
        confirmation = f"Event created: '{event.get('summary')}' on {start.strftime('%A %b %d at %I:%M %p')}."
        conflict = _conflict_note(tool_input["title"], start, end, event.get("id", ""))
        return confirmation + conflict

    if tool_name == "delete_calendar_event":
        event_id = tool_input["event_id"]
        title = tool_input.get("title", event_id)
        delete_event(event_id)
        return f"Event '{title}' has been deleted."

    if tool_name == "update_calendar_event":
        event_id = tool_input["event_id"]
        start = None
        end = None
        if "start_datetime" in tool_input:
            start = datetime.fromisoformat(tool_input["start_datetime"]).replace(tzinfo=tz)
        if "end_datetime" in tool_input:
            end = datetime.fromisoformat(tool_input["end_datetime"]).replace(tzinfo=tz)
        event = update_event(
            event_id=event_id,
            title=tool_input.get("title"),
            start=start,
            end=end,
            description=tool_input.get("description"),
        )
        return f"Event updated: '{event.get('summary')}'."

    if tool_name == "manage_shopping_list":
        action = tool_input["action"]
        items, event = read_shopping_list()

        if event is None:
            return (
                "No grocery event found in the next 30 days. "
                "Ask the user if they'd like to create one on the calendar first."
            )

        if action == "view":
            if not items:
                return "The shopping list is empty."
            bullet_list = "\n".join(f"- {i}" for i in items)
            return f"Current shopping list ({len(items)} items):\n{bullet_list}"

        if action == "add":
            new_items = tool_input.get("items", [])
            # Avoid exact duplicates (case-insensitive)
            existing_lower = {i.lower() for i in items}
            to_add = [i for i in new_items if i.lower() not in existing_lower]
            updated = items + to_add
            write_shopping_list(updated, event)
            added_str = ", ".join(to_add) if to_add else "nothing new (already on list)"
            return f"Added: {added_str}. List now has {len(updated)} items."

        if action == "clear":
            write_shopping_list([], event)
            return "Shopping list cleared."

    return f"Unknown tool: {tool_name}"
