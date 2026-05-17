"""Scheduler jobs — morning briefing, pre-event reminders, etc."""
import os
import asyncio
import html
import yaml
import logging
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telegram.ext import Application, CallbackContext
from gcal.client import get_events
from agent.enrichment import enrich_event
from storage.proactivity import (
    due_open_loops,
    event_was_followed,
    mark_event_followed,
    mark_open_loop_followed,
)

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


def _is_google_calendar_link(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    return parsed.scheme == "https" and host in {"calendar.google.com", "www.google.com", "google.com"}


def _event_label(event: dict) -> str:
    title = html.escape(event.get("summary", "(sin título)"))
    link = event.get("htmlLink")
    if _is_google_calendar_link(link):
        return f'<a href="{html.escape(link, quote=True)}">{title}</a>'
    return title


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
        lines.append(f"  • {time_str} — {_event_label(e)}")
    return "\n".join(lines)


def _event_start(event: dict, tz: ZoneInfo) -> datetime | None:
    raw = event["start"].get("dateTime", event["start"].get("date", ""))
    if not raw:
        return None
    try:
        if "T" in raw:
            return datetime.fromisoformat(raw).astimezone(tz)
        return datetime.fromisoformat(raw).replace(tzinfo=tz)
    except ValueError:
        return None


def _event_end(event: dict, tz: ZoneInfo) -> datetime | None:
    raw = event.get("end", {}).get("dateTime", event.get("end", {}).get("date", ""))
    if not raw:
        return None
    try:
        if "T" in raw:
            return datetime.fromisoformat(raw).astimezone(tz)
        return datetime.fromisoformat(raw).replace(tzinfo=tz)
    except ValueError:
        return None


def _chief_of_staff_notes(events: list[dict], tz: ZoneInfo) -> str:
    """Return proactive operational notes for the morning briefing."""
    if not events:
        return "  • Día libre en el calendario: buen momento para adelantar compras, tareas o descanso."

    rules = _load_rules()
    sports_keywords = rules["event_types"]["sports"]["keywords"]
    exam_keywords = rules["event_types"]["exam"]["keywords"]
    grocery_keywords = rules["event_types"]["grocery"]["keywords"]
    pickup_keywords = rules["event_types"]["pickup_required"]["keywords"]

    notes: list[str] = []
    timed_events = [(event, _event_start(event, tz), _event_end(event, tz)) for event in events]
    timed_events = [(event, start, end) for event, start, end in timed_events if start is not None]
    timed_events.sort(key=lambda item: item[1])

    for event, start, _ in timed_events:
        title = event.get("summary", "(sin título)")
        title_lower = title.lower()
        if "dateTime" in event.get("start", {}) and any(kw in title_lower for kw in pickup_keywords):
            leave_by = start - timedelta(minutes=20)
            event_label = _event_label(event)
            notes.append(
                f"Para {event_label}, asignen quién lleva/busca y apunten salir tipo {leave_by.strftime('%I:%M %p').lstrip('0')}."
            )
        if any(kw in title_lower for kw in sports_keywords):
            notes.append(f"Dejen listo agua, snack y equipo para {_event_label(event)}.")
        if any(kw in title_lower for kw in exam_keywords):
            notes.append(f"Para {_event_label(event)}, mejor repaso corto + desayuno tranquilo. Nada de corredera, mi amor.")
        if any(kw in title_lower for kw in grocery_keywords):
            notes.append(f"Antes de {_event_label(event)}, revisen la lista de compras y agreguen lo que falta.")

    for index, (first, _first_start, first_end) in enumerate(timed_events):
        if first_end is None:
            continue
        for second, second_start, _second_end in timed_events[index + 1:]:
            if second_start < first_end:
                notes.append(
                    f"Ojo: {_event_label(first)} se cruza con {_event_label(second)}."
                )

    if timed_events:
        first_start = timed_events[0][1]
        notes.append(
            f"Primer compromiso: {_event_label(timed_events[0][0])} a las {first_start.strftime('%I:%M %p').lstrip('0')}. Todo listo 30 min antes, chamo."
        )

    deduped = list(dict.fromkeys(notes))
    return "\n".join(f"  • {note}" for note in deduped[:4])


def _should_follow_up_event(event: dict, rules: dict) -> bool:
    title = event.get("summary", "").lower()
    if not title or "dateTime" not in event.get("start", {}):
        return False
    skip_words = ["grocery", "costco", "walmart", "supermarket", "compras", "mercado", "reminder"]
    if any(word in title for word in skip_words):
        return False

    interesting_keywords = (
        rules["event_types"]["sports"]["keywords"]
        + rules["event_types"]["exam"]["keywords"]
        + rules["event_types"]["pickup_required"]["keywords"]
        + ["doctor", "dentist", "appointment", "school", "class", "meeting", "médico", "dentista", "cita"]
    )
    return any(keyword in title for keyword in interesting_keywords)


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
        f"🌞 <b>Buenos días familia Hernandez!</b> Aquí su compadre Juanito con el resumen del día.\n\n"
        f"<b>Hoy — {html.escape(today_str)}:</b>\n{_format_events(today_events, tz)}\n\n"
        f"<b>Juanito Chief of Staff:</b>\n{_chief_of_staff_notes(today_events, tz)}\n\n"
        f"<b>Mañana — {html.escape(tomorrow_str)}:</b>\n{_format_events(tomorrow_events, tz)}\n\n"
        f"<i>¡Que tengan un día arrecho!</i> 🇻🇪"
    )

    await context.bot.send_message(
        chat_id=_family_chat_id(),
        text=message,
        parse_mode="HTML",
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


async def post_event_followup_check(context: CallbackContext) -> None:
    """Ask how important events went after they should be finished."""
    tz = _tz()
    now = datetime.now(tz)
    window_start = now - timedelta(hours=4)
    window_end = now - timedelta(minutes=30)

    try:
        events = get_events(window_start, window_end)
    except Exception as e:
        logger.error("Failed to fetch events for post-event follow-up: %s", e)
        return

    rules = _load_rules()
    sent = 0
    for event in events:
        if sent >= 2:
            break
        event_id = event.get("id")
        if not event_id or event_was_followed(event_id) or not _should_follow_up_event(event, rules):
            continue

        end = _event_end(event, tz)
        if end is None or not (window_start <= end <= window_end):
            continue

        title = event.get("summary", "(sin título)")
        message = (
            f"Épale familia, ¿cómo les fue con *{title}*?\n"
            "Si salió algo pendiente, díganmelo y lo convierto en próximo paso, recordatorio o evento. "
            "Chief of Staff mode, pues."
        )
        try:
            await context.bot.send_message(
                chat_id=_family_chat_id(),
                text=message,
                parse_mode="Markdown",
            )
            mark_event_followed(event_id, tz)
            sent += 1
            logger.info("Post-event follow-up sent for '%s'.", title)
        except Exception as e:
            logger.error("Failed to send post-event follow-up for '%s': %s", title, e)


async def conversation_followup_check(context: CallbackContext) -> None:
    """Nudge the family when Juanito asked a question and nobody answered."""
    tz = _tz()
    for loop in due_open_loops(tz, limit=2):
        user_id = loop.get("user_id")
        user_name = loop.get("user_name") or "familia"
        question = loop.get("assistant_reply") or "un punto pendiente"
        message = (
            f"Pendiente con {user_name}: quedó abierta esta vaina:\n"
            f"“{question}”\n\n"
            "¿Lo cerramos, lo agendamos, o lo dejamos quieto?"
        )
        try:
            await context.bot.send_message(chat_id=_family_chat_id(), text=message)
            if user_id:
                mark_open_loop_followed(user_id)
            logger.info("Conversation follow-up sent for user_id=%s.", user_id)
        except Exception as e:
            logger.error("Failed to send conversation follow-up: %s", e)


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
    jq.run_repeating(post_event_followup_check, interval=60 * 30, first=60 * 20, name="post_event_followup_check")
    jq.run_repeating(conversation_followup_check, interval=60 * 60, first=60 * 30, name="conversation_followup_check")

    logger.info("Scheduler ready: briefing, reminders, event follow-ups, and conversation follow-ups active.")
