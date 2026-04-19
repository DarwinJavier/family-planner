"""Telegram slash command handlers: /today, /week, /list, /help."""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
from telegram import Update
from telegram.ext import ContextTypes
from gcal.client import get_events
from storage.shopping_list import read_shopping_list

logger = logging.getLogger(__name__)


def _tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("TIMEZONE", "America/Toronto"))


def _format_events(events: list[dict], tz: ZoneInfo) -> str:
    if not events:
        return "  Nothing scheduled — free day! 🎉"
    lines = []
    for e in events:
        raw = e["start"].get("dateTime", e["start"].get("date", ""))
        if "T" in raw:
            dt = datetime.fromisoformat(raw).astimezone(tz)
            time_str = dt.strftime("%I:%M %p").lstrip("0")
        else:
            time_str = "all day"
        lines.append(f"  • {time_str} — {e.get('summary', '(no title)')}")
    return "\n".join(lines)


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/today — today's full schedule."""
    tz = _tz()
    now = datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    try:
        events = get_events(start, end)
    except Exception as e:
        logger.error("/today failed to fetch events: %s", e)
        await update.message.reply_text(
            "Épale, couldn't reach the calendar right now. Try again in a moment!"
        )
        return

    date_str = now.strftime("%A, %B %d")
    text = f"📅 *{date_str}*\n\n{_format_events(events, tz)}"
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/week — this week's schedule grouped by day."""
    tz = _tz()
    now = datetime.now(tz)
    week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)

    try:
        events = get_events(week_start, week_end)
    except Exception as e:
        logger.error("/week failed to fetch events: %s", e)
        await update.message.reply_text(
            "Épale, couldn't reach the calendar right now. Try again in a moment!"
        )
        return

    # Group events by day
    days: dict[str, list[dict]] = {}
    for e in events:
        raw = e["start"].get("dateTime", e["start"].get("date", ""))
        if "T" in raw:
            dt = datetime.fromisoformat(raw).astimezone(tz)
        else:
            dt = datetime.fromisoformat(raw).replace(tzinfo=tz)
        day_key = dt.strftime("%A %b %d")
        days.setdefault(day_key, []).append(e)

    if not days:
        await update.message.reply_text("Nothing on the calendar this week — enjoy the break! 😎")
        return

    lines = ["📅 *This week:*\n"]
    for day, day_events in days.items():
        lines.append(f"*{day}*")
        lines.append(_format_events(day_events, tz))
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/list — current shopping list."""
    try:
        items, event = read_shopping_list()
    except Exception as e:
        logger.error("/list failed: %s", e)
        await update.message.reply_text(
            "Couldn't read the shopping list right now, chamo. Try again in a moment!"
        )
        return

    if event is None:
        await update.message.reply_text(
            "No grocery event found in the next 30 days. "
            "Add one to the calendar and I'll keep the list there! 🛒"
        )
        return

    if not items:
        await update.message.reply_text("The shopping list is empty. Add something, pana! 🛒")
        return

    bullet_list = "\n".join(f"• {i}" for i in items)
    event_title = event.get("summary", "grocery run")
    await update.message.reply_text(
        f"🛒 *Shopping list* (for {event_title}):\n\n{bullet_list}",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help — what Juanito can do."""
    text = (
        "👋 *Hey! I'm Juanito, your family assistant.*\n\n"
        "*Slash commands:*\n"
        "  /today — today's schedule\n"
        "  /week — this week at a glance\n"
        "  /list — current shopping list\n"
        "  /help — this message\n\n"
        "*Just chat with me to:*\n"
        "  • Add, edit, or delete calendar events\n"
        "  • Ask what's coming up\n"
        "  • Add items to the shopping list\n"
        "  • Get smart reminders before events\n\n"
        "_Hablo español e inglés, chamo. Escríbeme como quieras!_ 🇻🇪"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
