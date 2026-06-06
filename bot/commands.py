"""Telegram slash command handlers: /today, /week, /list, /help."""
import html
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
from urllib.parse import urlparse
from telegram import Update
from telegram.ext import ContextTypes
from gcal.client import get_events
from storage.shopping_list import read_shopping_list
from agent.brain import queue_calendar_write
from opportunity.service import (
    build_calendar_proposal,
    discover_recommendations,
    dismiss_recommendation,
    format_recommendations,
    recommend_more_like,
    save_recommendation,
)
from opportunity.preferences import add_interest, hide_category, load_preferences
from storage.price_research import research_prices

logger = logging.getLogger(__name__)


def _tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("TIMEZONE", "America/Toronto"))


def _is_google_calendar_link(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    return parsed.scheme == "https" and host in {"calendar.google.com", "www.google.com", "google.com"}


def _event_label(event: dict) -> str:
    title = html.escape(event.get("summary", "(no title)"))
    link = event.get("htmlLink")
    if _is_google_calendar_link(link):
        return f'<a href="{html.escape(link, quote=True)}">{title}</a>'
    return title


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
        lines.append(f"  • {time_str} — {_event_label(e)}")
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
    text = f"📅 <b>{html.escape(date_str)}</b>\n\n{_format_events(events, tz)}"
    await update.message.reply_text(text, parse_mode="HTML")


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

    lines = ["📅 <b>This week:</b>\n"]
    for day, day_events in days.items():
        lines.append(f"<b>{html.escape(day)}</b>")
        lines.append(_format_events(day_events, tz))
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


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

    bullet_list = "\n".join(f"• {html.escape(i)}" for i in items)
    event_title = _event_label(event)
    await update.message.reply_text(
        f"🛒 <b>Shopping list</b> (for {event_title}):\n\n{bullet_list}\n\n"
        "Use /prices to compare current prices.",
        parse_mode="HTML",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help — what Juanito can do."""
    text = (
        "👋 *Hey! I'm Juanito, your family assistant.*\n\n"
        "*Slash commands:*\n"
        "  /today — today's schedule\n"
        "  /week — this week at a glance\n"
        "  /list — current shopping list\n"
        "  /prices — compare prices for shopping-list items\n"
        "  /scout — realistic local activity matches\n"
        "  /scout_preferences — current Scout interests and limits\n"
        "  /help — this message\n\n"
        "*Just chat with me to:*\n"
        "  • Add, edit, or delete calendar events\n"
        "  • Ask what's coming up\n"
        "  • Add items to the shopping list\n"
        "  • Read images, invitations, and schedule screenshots\n"
        "  • Get smart reminders before events\n\n"
        "_Hablo español e inglés, chamo. Escríbeme como quieras!_ 🇻🇪"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


def _command_id(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    return context.args[0].strip() if context.args else None


async def cmd_scout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Find a small set of local activities that genuinely fit the calendar."""
    try:
        recommendations, warnings = discover_recommendations()
        text = format_recommendations(recommendations, warnings)
    except Exception as exc:
        logger.error("/scout failed: %s", exc, exc_info=True)
        text = "Opportunity Scout couldn't check the calendar and local options right now. Try again shortly."
    await update.message.reply_text(text, disable_web_page_preview=True)


async def cmd_prices(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Research current prices for explicit items or the existing shopping list."""
    request_context = " ".join(context.args)
    items = [request_context] if context.args else []
    if not items:
        try:
            items, event = read_shopping_list()
        except Exception as exc:
            logger.error("/prices failed to read shopping list: %s", exc, exc_info=True)
            await update.message.reply_text("I couldn't read the shopping list right now.")
            return
        if event is None or not items:
            await update.message.reply_text("Tell me what to price-check, for example: /prices milk and eggs")
            return

    await context.bot.send_chat_action(chat_id=update.message.chat_id, action="typing")
    result = await asyncio.to_thread(
        research_prices,
        items,
        "Ottawa, Ontario",
        request_context,
    )
    await update.message.reply_text(result, disable_web_page_preview=True)


async def cmd_scout_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    activity_id = _command_id(context)
    recommendation = save_recommendation(activity_id) if activity_id else None
    text = (
        f"Saved {recommendation.activity.title} for later."
        if recommendation
        else "I couldn't find that recommendation. Run /scout again for fresh options."
    )
    await update.message.reply_text(text)


async def cmd_scout_dismiss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    activity_id = _command_id(context)
    recommendation = dismiss_recommendation(activity_id) if activity_id else None
    text = (
        f"Got it. I won't prioritize {recommendation.activity.title} again."
        if recommendation
        else "I couldn't find that recommendation. Run /scout again for fresh options."
    )
    await update.message.reply_text(text)


async def cmd_scout_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    activity_id = _command_id(context)
    recommendation = recommend_more_like(activity_id) if activity_id else None
    text = (
        f"Got it. I'll prioritize more activities like {recommendation.activity.title}."
        if recommendation
        else "I couldn't find that recommendation. Run /scout again for fresh options."
    )
    await update.message.reply_text(text)


async def cmd_scout_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    activity_id = _command_id(context)
    try:
        result = build_calendar_proposal(activity_id) if activity_id else None
    except Exception as exc:
        logger.error("/scout_add failed: %s", exc, exc_info=True)
        result = None
    if not result:
        await update.message.reply_text("I couldn't find that recommendation. Run /scout again for fresh options.")
        return

    proposal, conflicts = result
    queue_calendar_write(update.message.from_user.id, proposal)
    start = datetime.fromisoformat(proposal["start_datetime"]).astimezone(_tz())
    end = datetime.fromisoformat(proposal["end_datetime"]).astimezone(_tz())
    conflict_note = f" Warning: it overlaps with {', '.join(conflicts)}." if conflicts else ""
    await update.message.reply_text(
        f"Should I add {proposal['title']} from {start.strftime('%I:%M %p').lstrip('0')} "
        f"to {end.strftime('%I:%M %p').lstrip('0')} including preparation and travel?{conflict_note}"
    )


async def cmd_scout_preferences(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    preferences = load_preferences()
    family = preferences["family"]
    text = (
        "Opportunity Scout preferences:\n"
        f"Family interests: {', '.join(family['interests'])}\n"
        f"Older child: {', '.join(preferences['older_child']['interests'])}\n"
        f"Younger child: {', '.join(preferences['younger_child']['interests'])}\n"
        f"Maximum travel: {family['max_travel_minutes']} min\n"
        f"Maximum activity cost: ${family['max_cost_per_activity']}\n"
        f"Hidden categories: {', '.join(family['disliked_categories']) or 'none'}\n\n"
        "Add an interest with /scout_interest PROFILE INTEREST or hide one with /scout_hide CATEGORY."
    )
    await update.message.reply_text(text)


async def cmd_scout_interest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Use /scout_interest family|older_child|younger_child INTEREST.")
        return
    profile, interest = context.args[0], " ".join(context.args[1:])
    try:
        updated = add_interest(profile, interest)
        await update.message.reply_text(f"Added {interest} to {profile}. Interests: {', '.join(updated['interests'])}")
    except ValueError:
        await update.message.reply_text("Profile must be family, older_child, or younger_child.")


async def cmd_scout_hide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Use /scout_hide CATEGORY.")
        return
    category = " ".join(context.args)
    updated = hide_category(category)
    await update.message.reply_text(f"Hidden category: {category}. Hidden list: {', '.join(updated['disliked_categories'])}")
