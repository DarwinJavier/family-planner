"""Scheduler jobs — morning briefing, pre-event reminders, etc."""
import os
import asyncio
import yaml
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telegram.ext import Application, CallbackContext
from gcal.client import get_events
from agent.enrichment import enrich_event

load_dotenv()
logger = logging.getLogger(__name__)

# Tracks event IDs already reminded this session to avoid duplicate messages
_reminded_events: set[str] = set()


def _family_chat_id() -> int:
    return int(os.environ["FAMILY_CHAT_ID"])


def _tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("TIMEZONE", "America/Toronto"))


def _load_rules() -> dict:
    rules_path = Path(__file__).parent.parent / "config" / "rules.yaml"
    with open(rules_path) as f:
        return yaml.safe_load(f)


def _detect_event_type(title: str, rules: dict) -> str | None:
    """Return the event type ('sports', 'exam', 'grocery') or None."""
    title_lower = title.lower()
    for event_type, config in rules["event_types"].items():
        if any(kw in title_lower for kw in config["keywords"]):
            return event_type
    return None


def _build_reminder(event_title: str, event_type: str | None, start: datetime, enrichment: str = "") -> str:
    time_str = start.strftime("%I:%M %p").lstrip("0")

    if event_type == "sports":
        tips = enrichment or (
            "• 5 min trote suave para calentar\n"
            "• Estiramientos dinámicos — piernas y brazos\n"
            "• Toma agua AHORA, no después\n"
            "• Lleva tu equipo completo"
        )
        return (
            f"🏃 *{event_title}* es en menos de una hora ({time_str}), chamo!\n\n"
            f"Calentamiento rápido:\n{tips}\n\n"
            f"_¡Arréchate y a darlo todo!_ 💪🇻🇪"
        )

    if event_type == "exam":
        tips = enrichment or (
            "• Repasa tus apuntes clave, no todo\n"
            "• Respira profundo — tú puedes con esto\n"
            "• Come algo ligero si no lo has hecho\n"
            "• Lee bien cada pregunta antes de responder"
        )
        return (
            f"📚 *{event_title}* es en menos de una hora ({time_str})!\n\n"
            f"Tips de último momento:\n{tips}\n\n"
            f"_¡Tú sabes esto, pana! A brillar!_ ⭐"
        )

    if event_type == "grocery":
        return (
            f"🛒 *{event_title}* en menos de una hora ({time_str})!\n\n"
            f"No olvides revisar la lista antes de salir. "
            f"_(La lista de compras llega en la próxima versión de Juanito 😎)_"
        )

    # Generic reminder — append enrichment if available
    base = (
        f"⏰ Recordatorio: *{event_title}* empieza a las {time_str}.\n"
        f"_¡Épale, no llegues tarde que eso no se ve bien!_ 😄"
    )
    if enrichment:
        return f"{base}\n\n{enrichment}"
    return base


def _format_events(events: list[dict], tz: ZoneInfo) -> str:
    if not events:
        return "  Nada, día libre chamo 🎉"
    lines = []
    for e in events:
        raw = e["start"].get("dateTime", e["start"].get("date", ""))
        if "T" in raw:
            dt = datetime.fromisoformat(raw).astimezone(tz)
            time_str = dt.strftime("%I:%M %p").lstrip("0")
        else:
            time_str = "todo el día"
        lines.append(f"  • {time_str} — {e.get('summary', '(sin título)')}")
    return "\n".join(lines)


async def morning_briefing(context: CallbackContext) -> None:
    """Daily 5:45am digest of today's and tomorrow's events."""
    tz = _tz()
    now = datetime.now(tz)

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    tomorrow_start = today_end
    tomorrow_end = tomorrow_start + timedelta(days=1)

    try:
        today_events = get_events(today_start, today_end)
        tomorrow_events = get_events(tomorrow_start, tomorrow_end)
    except Exception as e:
        logger.error("Failed to fetch events for briefing: %s", e)
        await context.bot.send_message(
            chat_id=_family_chat_id(),
            text="Épale familia, quise revisar el calendario pa' darles el resumen pero algo falló. Intenten más tarde 🙈",
        )
        return

    today_str = today_start.strftime("%A %d de %B")
    tomorrow_str = tomorrow_start.strftime("%A %d de %B")

    message = (
        f"🌞 *Buenos días familia Hernandez!* Aquí su compadre Juanito con el resumen del día.\n\n"
        f"*Hoy — {today_str}:*\n{_format_events(today_events, tz)}\n\n"
        f"*Mañana — {tomorrow_str}:*\n{_format_events(tomorrow_events, tz)}\n\n"
        f"_¡Que tengan un día arrecho!_ 🇻🇪"
    )

    await context.bot.send_message(
        chat_id=_family_chat_id(),
        text=message,
        parse_mode="Markdown",
    )
    logger.info("Morning briefing sent.")


async def pre_event_check(context: CallbackContext) -> None:
    """Runs every 30 min — sends reminders for events starting in 60-90 minutes."""
    tz = _tz()
    now = datetime.now(tz)
    window_start = now + timedelta(minutes=60)
    window_end = now + timedelta(minutes=90)

    try:
        events = get_events(window_start, window_end)
    except Exception as e:
        logger.error("Failed to fetch events for pre-event check: %s", e)
        return

    rules = _load_rules()

    for event in events:
        event_id = event.get("id")
        if not event_id or event_id in _reminded_events:
            continue

        title = event.get("summary", "(sin título)")
        raw_start = event["start"].get("dateTime", event["start"].get("date", ""))
        if not raw_start:
            continue

        start = datetime.fromisoformat(raw_start).astimezone(tz)
        event_type = _detect_event_type(title, rules)
        event_description = event.get("description", "")

        enrichment = await asyncio.to_thread(enrich_event, title, event_description)

        message = _build_reminder(title, event_type, start, enrichment)

        try:
            await context.bot.send_message(
                chat_id=_family_chat_id(),
                text=message,
                parse_mode="Markdown",
            )
            _reminded_events.add(event_id)
            logger.info("Reminder sent for event '%s' (type=%s).", title, event_type)
        except Exception as e:
            logger.error("Failed to send reminder for '%s': %s", title, e)


def start_scheduler(app: Application) -> None:
    """Register all scheduled jobs on the application's JobQueue."""
    tz = _tz()
    jq = app.job_queue

    # Daily morning briefing at 5:45am
    jq.run_daily(
        morning_briefing,
        time=datetime.now(tz).replace(hour=5, minute=45, second=0, microsecond=0).timetz(),
        name="morning_briefing",
    )

    # Pre-event check every 30 minutes
    jq.run_repeating(pre_event_check, interval=60 * 30, first=60, name="pre_event_check")

    logger.info("Scheduler ready — briefing at 5:45am, pre-event check every 30 min.")
