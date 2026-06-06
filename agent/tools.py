"""Tool definitions and handlers for the agent's calendar interactions."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import logging
import re
from urllib.parse import urlparse
from dotenv import load_dotenv
from openai import OpenAI
import yaml
from pathlib import Path
from gcal.client import get_events, create_event, delete_event, update_event, get_overlapping_events
from agent.enrichment import enrich_event
from storage.shopping_list import read_shopping_list, write_shopping_list

load_dotenv()
logger = logging.getLogger(__name__)

RESEARCH_MODEL = os.environ.get("OPENAI_RESEARCH_MODEL", "gpt-4o")

TRUSTED_LINK_DOMAINS = [
    "canada.ca",
    "ontario.ca",
    "ottawa.ca",
    "ottawapublichealth.ca",
    "cheo.on.ca",
    "mayoclinic.org",
    "cdc.gov",
    "who.int",
    "healthychildren.org",
    "khanacademy.org",
    "britannica.com",
    "wikipedia.org",
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "cbc.ca",
    "ctvnews.ca",
    "theweathernetwork.com",
    "weather.gc.ca",
    "google.com",
    "youtube.com",
    "spotify.com",
    "goodreads.com",
    "commonsensemedia.org",
    "openai.com",
    "microsoft.com",
    "apple.com",
    "ottawaisnotboring.com",
    "facebook.com",
]

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
                "Call this as soon as the user asks to schedule an event. "
                "The application enforces confirmation before the write is executed."
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
                "Call this after finding the event. The application enforces confirmation before deletion. "
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
                "Call this after finding the event. The application enforces confirmation before updating. "
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
    {
        "type": "function",
        "function": {
            "name": "research_shopping_prices",
            "description": (
                "Research current Canadian retailer prices for explicit items or the current family shopping list. "
                "Use this when the family asks where an item is cheaper, what something costs, or for shopping-list price comparisons."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Items to research. Omit or pass an empty list to research the current shopping list.",
                    },
                    "location": {
                        "type": "string",
                        "description": "Shopping location, default Ottawa, Ontario.",
                    },
                    "context": {
                        "type": "string",
                        "description": "The user's price request, including any retailer or place they mentioned.",
                    },
                    "preferred_retailers": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "costco", "walmart", "superstore", "loblaws", "metro", "sobeys",
                                "amazon", "best buy", "canadian tire", "home depot", "rona", "staples", "ikea",
                            ],
                        },
                        "description": "Retailers explicitly requested by the user, in priority order.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_opportunities",
            "description": (
                "Run Opportunity Scout to find a small number of realistic local activities "
                "that fit the family calendar, preferences, travel limits, and budget."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum recommendations to return, from 1 to 5.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_opportunity",
            "description": (
                "Save, dismiss, or prepare a specific Opportunity Scout recommendation for the calendar. "
                "For action 'add', use the returned event details to call create_calendar_event."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["save", "dismiss", "more_like", "add"]},
                    "activity_id": {"type": "string"},
                    "reason": {
                        "type": "string",
                        "enum": ["dismissed", "not_relevant", "too_expensive", "too_far", "wrong_age", "wrong_time"],
                    },
                },
                "required": ["action", "activity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "research_question",
            "description": (
                "Research a factual question with web search before answering. "
                "Use this for current events, local details, prices, schedules, products, medical/general health facts, "
                "travel, sports, technology, laws, or any random question where the base model may be stale. "
                "Do not use this to expose private family calendar details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The user's factual question to research.",
                    },
                    "language": {
                        "type": "string",
                        "description": "Preferred answer language, e.g. English or Spanish.",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_for_calendar",
            "description": (
                "Read calendar events in a date range and return practical family-assistant recommendations: "
                "when to leave, what to prepare, possible conflicts, supplies, and useful event context. "
                "Use when the user asks for planning help, preparation, priorities, logistics, or how to handle a day/week."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start of the range in ISO 8601 format, e.g. '2026-05-17'",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End of the range (exclusive) in ISO 8601 format, e.g. '2026-05-18'",
                    },
                    "focus": {
                        "type": "string",
                        "description": "Optional planning focus, such as morning routine, sports, school, errands, or conflicts.",
                    },
                },
                "required": ["start_date", "end_date"],
            },
        },
    },
]


def _sanitize_text(text: str, max_length: int = 900) -> str:
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", text or "")
    text = " ".join(text.split())
    return text[:max_length]


def _extract_response_text(response) -> str:
    for item in response.output:
        if item.type == "message":
            for content in item.content:
                if content.type == "output_text":
                    return content.text.strip()
    return ""


def _is_trusted_https_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    return any(host == domain or host.endswith(f".{domain}") for domain in TRUSTED_LINK_DOMAINS)


def _strip_untrusted_links(text: str) -> str:
    """Remove links that are not HTTPS links on known trusted domains."""
    markdown_link_re = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
    bare_url_re = re.compile(r"https?://[^\s)>\]]+")

    def replace_markdown(match: re.Match) -> str:
        label = match.group(1)
        url = match.group(2)
        return match.group(0) if _is_trusted_https_url(url) else label

    text = markdown_link_re.sub(replace_markdown, text)

    def replace_bare(match: re.Match) -> str:
        url = match.group(0).rstrip(".,;:")
        suffix = match.group(0)[len(url):]
        return f"{url}{suffix}" if _is_trusted_https_url(url) else ""

    return bare_url_re.sub(replace_bare, text).strip()


def _research_question(question: str, language: str | None = None) -> str:
    safe_question = _sanitize_text(question)
    safe_language = _sanitize_text(language or "the user's language", 80)
    if not safe_question:
        return "No research question provided."

    trusted_domains = ", ".join(TRUSTED_LINK_DOMAINS)
    prompt = f"""Answer this family chat question using web search when useful.

Question: {safe_question}
Preferred language: {safe_language}

Rules:
- Be concise and practical.
- If the user names a company, retailer, venue, organization, or website, prioritize its official site before broader sources.
- Verify that every linked page directly supports the claim beside it. Prefer a specific product, event, policy, or detail page over a homepage, search page, or category page.
- When an official source cannot verify a claim, clearly label it as uncertain instead of presenting it as fact.
- Include 1-3 source links when the answer depends on current or specific facts.
- Only include HTTPS links from these known domains or their subdomains: {trusted_domains}
- Never include HTTP links, shortened links, suspicious domains, forums, random blogs, or links you are not sure are real.
- Say when the evidence is uncertain or when the answer may vary by location.
- Do not mention internal tool use.
- Do not give emergency medical/legal/financial advice; suggest a professional for high-stakes decisions."""

    try:
        response = OpenAI(api_key=os.environ.get("OPENAI_API_KEY")).responses.create(
            model=RESEARCH_MODEL,
            tools=[{"type": "web_search_preview"}],
            input=prompt,
        )
        result = _extract_response_text(response)
        return _strip_untrusted_links(result) if result else "I couldn't find a solid answer from search."
    except Exception as e:
        logger.error("Research failed: %s", e)
        return "Research failed. Answer cautiously from general knowledge or ask the user to try again."


def _parse_event_start(event: dict, tz: ZoneInfo) -> datetime | None:
    raw = event.get("start", {}).get("dateTime", event.get("start", {}).get("date", ""))
    if not raw:
        return None
    try:
        if "T" in raw:
            return datetime.fromisoformat(raw).astimezone(tz)
        return datetime.fromisoformat(raw).replace(tzinfo=tz)
    except ValueError:
        return None


def _format_event_for_recommendation(event: dict, tz: ZoneInfo) -> str:
    start = _parse_event_start(event, tz)
    title = event.get("summary", "(no title)")
    if start is None:
        return f"- {title}"
    raw = event.get("start", {}).get("dateTime", event.get("start", {}).get("date", ""))
    if "T" not in raw:
        return f"- all day: {title}"
    return f"- {start.strftime('%a %b %d, %I:%M %p').lstrip('0')}: {title}"


def _recommend_for_calendar(start_date: str, end_date: str, focus: str | None = None) -> str:
    tz = ZoneInfo(os.environ.get("TIMEZONE", "America/Toronto"))
    start = datetime.fromisoformat(start_date).replace(tzinfo=tz)
    end = datetime.fromisoformat(end_date).replace(tzinfo=tz)
    events = get_events(start, end)

    if not events:
        return "No events found. Recommend protecting the open time and asking if the family wants reminders, errands, or meal planning added."

    rules_path = Path(__file__).parent.parent / "config" / "rules.yaml"
    with open(rules_path) as f:
        rules = yaml.safe_load(f)

    sports_keywords = rules["event_types"]["sports"]["keywords"]
    exam_keywords = rules["event_types"]["exam"]["keywords"]
    grocery_keywords = rules["event_types"]["grocery"]["keywords"]
    pickup_keywords = rules["event_types"]["pickup_required"]["keywords"]

    lines = ["Calendar facts:"]
    lines.extend(_format_event_for_recommendation(e, tz) for e in events)

    recommendations: list[str] = []
    timed_events = [(e, _parse_event_start(e, tz)) for e in events]
    timed_events = [(e, s) for e, s in timed_events if s is not None]

    for event, event_start in timed_events:
        title = event.get("summary", "(no title)")
        title_lower = title.lower()

        if any(kw in title_lower for kw in pickup_keywords):
            leave_by = event_start - timedelta(minutes=20)
            recommendations.append(
                f"For '{title}', assign pickup/drop-off and aim to leave by {leave_by.strftime('%I:%M %p').lstrip('0')}."
            )
        elif "T" in event.get("start", {}).get("dateTime", ""):
            leave_by = event_start - timedelta(minutes=15)
            recommendations.append(
                f"For '{title}', keep a 15-minute buffer; target leaving by {leave_by.strftime('%I:%M %p').lstrip('0')} if travel is involved."
            )

        if any(kw in title_lower for kw in sports_keywords):
            recommendations.append(f"Pack water, gear, snack, and a change of clothes for '{title}'.")
        if any(kw in title_lower for kw in exam_keywords):
            recommendations.append(f"For '{title}', do a short review the night before and prep breakfast/water early.")
        if any(kw in title_lower for kw in grocery_keywords):
            recommendations.append(f"Before '{title}', check the shopping list and add missing staples.")

    for i, (first_event, first_start) in enumerate(timed_events):
        first_end_raw = first_event.get("end", {}).get("dateTime")
        if not first_end_raw:
            continue
        try:
            first_end = datetime.fromisoformat(first_end_raw).astimezone(tz)
        except ValueError:
            continue
        for second_event, second_start in timed_events[i + 1:]:
            if second_start < first_end:
                recommendations.append(
                    f"Conflict risk: '{first_event.get('summary', '(no title)')}' overlaps with '{second_event.get('summary', '(no title)')}'."
                )

    enrichments = []
    for event, _ in timed_events[:3]:
        title = event.get("summary", "")
        context = enrich_event(title, event.get("description", ""))
        if context:
            enrichments.append(f"{title}: {context}")

    if not recommendations:
        recommendations.append("No obvious conflicts. Suggest confirming transportation and adding reminders for anything important.")

    result = lines + ["", "Recommendations:"] + [f"- {r}" for r in recommendations[:8]]
    if enrichments:
        result += ["", "Useful context:"] + [f"- {item}" for item in enrichments[:3]]
    if focus:
        result.append(f"\nUser focus: {_sanitize_text(focus, 160)}")
    return "\n".join(result)


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
            link = e.get("htmlLink")
            link_text = f" Open in Google Calendar: {link}" if _is_trusted_https_url(link or "") else ""
            lines.append(f"- [id:{event_id}] {time}: {e.get('summary', '(no title)')}.{link_text}")
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
        link = event.get("htmlLink")
        link_text = f" Open in Google Calendar: {link}" if _is_trusted_https_url(link or "") else ""
        confirmation = f"Event created: '{event.get('summary')}' on {start.strftime('%A %b %d at %I:%M %p')}.{link_text}"
        opportunity_match = re.search(r"opportunity_id:\s*([^\s]+)", tool_input.get("description", ""))
        if opportunity_match:
            from opportunity.service import accept_recommendation
            accept_recommendation(opportunity_match.group(1))
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

    if tool_name == "research_shopping_prices":
        from storage.price_research import research_prices

        items = tool_input.get("items") or []
        if not items:
            items, event = read_shopping_list()
            if event is None:
                return "No grocery event or shopping list was found. Ask which items the user wants priced."
        return research_prices(
            items,
            tool_input.get("location", "Ottawa, Ontario"),
            context=tool_input.get("context", ""),
            preferred_retailers=tool_input.get("preferred_retailers"),
        )

    if tool_name == "find_opportunities":
        from opportunity.service import discover_recommendations, format_recommendations

        limit = min(5, max(1, int(tool_input.get("limit", 5))))
        recommendations, warnings = discover_recommendations(limit=limit)
        return format_recommendations(recommendations, warnings)

    if tool_name == "manage_opportunity":
        from opportunity.service import (
            build_calendar_proposal,
            dismiss_recommendation,
            recommend_more_like,
            save_recommendation,
        )

        activity_id = tool_input["activity_id"]
        action = tool_input["action"]
        if action == "save":
            recommendation = save_recommendation(activity_id)
            return (
                f"Saved '{recommendation.activity.title}' for later."
                if recommendation
                else "Recommendation not found. Run Opportunity Scout again."
            )
        if action == "dismiss":
            recommendation = dismiss_recommendation(activity_id, tool_input.get("reason", "dismissed"))
            return (
                f"Dismissed '{recommendation.activity.title}' and recorded the feedback."
                if recommendation
                else "Recommendation not found. Run Opportunity Scout again."
            )
        if action == "more_like":
            recommendation = recommend_more_like(activity_id)
            return (
                f"Recorded a preference for more activities like '{recommendation.activity.title}'."
                if recommendation
                else "Recommendation not found. Run Opportunity Scout again."
            )
        proposal = build_calendar_proposal(activity_id)
        if not proposal:
            return "Recommendation not found. Run Opportunity Scout again."
        event_input, conflicts = proposal
        warning = f" Conflicts before confirmation: {', '.join(conflicts)}." if conflicts else ""
        return (
            "Call create_calendar_event with these exact arguments so the application asks for confirmation: "
            f"{event_input}.{warning}"
        )

    if tool_name == "research_question":
        return _research_question(
            question=tool_input["question"],
            language=tool_input.get("language"),
        )

    if tool_name == "recommend_for_calendar":
        return _recommend_for_calendar(
            start_date=tool_input["start_date"],
            end_date=tool_input["end_date"],
            focus=tool_input.get("focus"),
        )

    return f"Unknown tool: {tool_name}"
