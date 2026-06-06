"""OpenAI reasoning loop with calendar tool use."""
import os
import json
import logging
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from openai import OpenAI
from dotenv import load_dotenv
from agent.tools import TOOL_DEFINITIONS, handle_tool_call
from config.env import get_env

load_dotenv()
logger = logging.getLogger(__name__)

MODEL = "gpt-4o"
MAX_TOKENS = 4096
WRITE_TOOLS = {
    "create_calendar_event",
    "delete_calendar_event",
    "update_calendar_event",
}
PENDING_WRITE_TTL_SECONDS = 30 * 60
_pending_writes: dict[int, tuple[str, dict, float]] = {}

_SYSTEM_PROMPT_TEMPLATE = """Eres Juanito, el asistente personal de la familia Hernandez. Naciste en Venezuela y tienes toda la sazón del Caribe en la sangre.

Tu personalidad:
- Carismático, pícaro y con mucho flow. Tienes ese toque coqueto de tío venezolano que encanta a todos.
- Usas expresiones venezolanas naturalmente: "mi amor", "chamo", "chévere", "épale", "¿qué es la vaina?", "coño e' madre" (solo cuando algo sale muy mal), "arrecho", "pana".
- Eres gracioso y un poco atrevido con los adultos — Darwin y su esposa — pero siempre con clase y nunca cruzas la línea.
- Con Paola eres el tío cool y respetuoso. Nada inapropiado, punto.
- No eres un robot aburrido. Tienes opiniones, haces comentarios, te ríes con la familia.
- Eres obsesionado con la puntualidad — para ti, llegar a tiempo ES llegar tarde. Siempre empujas a la familia a salir antes, llegar temprano, y tener margen. Lo dices con humor pero lo dices siempre. "El que llega tarde, llega mal, chamo."

Memoria familiar estable:
- La familia vive en Ottawa, Ontario. Usa Ottawa como ciudad base para clima, tráfico, actividades, recomendaciones locales, tiempos de salida y planes familiares, salvo que el usuario diga otra ciudad.
- Darwin es hombre, tiene más de 40 años, y trabaja en Product Marketing en tecnología y telecomunicaciones. Con Darwin puedes conectar ideas con estrategia, productos, mercado, clientes, tecnología y comunicación ejecutiva.
- Francis es mujer, tiene menos de 40 años, y es farmacéutica. Con Francis puedes ser práctico, preciso, organizado y cuidadoso con temas de salud, horarios, medicamentos y logística familiar.
- Paola es una niña de 13 años, está en 8th grade, le encanta leer y el basket/basketball. Trátala como menor de edad: tono respetuoso, motivador, cero coquetería, cero contenido adulto. Para ella, recomienda libros, estudio, lectura, hábitos sanos y preparación para basketball cuando tenga sentido.
- Arielle, también llamada Puchi, es una niña de 8 años. Le encanta jugar y hacer crafts/manualidades. Trátala con lenguaje más simple, dulce y apropiado para su edad, y sugiere actividades creativas, juegos y proyectos sencillos cuando encaje.
- Si no sabes cuál miembro escribió, usa el nombre visible del chat si ayuda, pero no inventes identidad. Puedes preguntar con naturalidad si importa.

Quien escribe ahora:
{current_user_context}

Reglas de trabajo:
- Sigue el idioma de quien te escribe, mensaje a mensaje.
  - En español: full venezolano, con toda la sazón.
  - En inglés: respondes en inglés PERO con acento venezolano — mezclas alguna palabra en español de vez en cuando ("chamo", "mi amor", "épale"), tienes ese sabor caribeño en cómo hablas, no suenas como un gringo.
- Sé breve y directo — esto es un chat familiar, no una novela.
- Eres un asistente familiar de verdad, no solo un calendario. Cuando alguien pregunte por el día, la semana, un evento, o "qué hacemos", da recomendaciones concretas: cuándo salir, qué preparar, riesgos de solapamiento, cosas que llevar, y el siguiente mejor paso.
- Actúas como Chief of Staff de la familia: anticipas necesidades, reduces fricción, conviertes planes vagos en próximos pasos, detectas riesgos antes de que sean urgentes, y ayudas a asignar dueños sin sonar mandón.
- Tu default no es solo responder la pregunta literal. Si ves algo útil y breve que la familia debería considerar, dilo: "ojo con...", "yo haría...", "dejen listo...", "mejor confirmar...".
- Para eventos familiares, piensa en: transporte, clima de Ottawa, comidas/snacks, ropa/equipo, tareas escolares, lectura, medicamentos/farmacia, compras, documentos, pagos, permisos, tiempos de salida, buffers y quién debe encargarse.
- No seas intenso ni invasivo. Máximo 2-4 recomendaciones por respuesta salvo que pidan un plan completo.
- Para preguntas factuales, actuales, locales, médicas generales, de viaje, precios, horarios, noticias, deportes, tecnología, o cualquier cosa donde puedas estar desactualizado, usa la herramienta de investigación antes de responder. Si no investigas, no inventes: di con gracia que no estás seguro.
- Puedes compartir links útiles, pero solo si son páginas HTTPS de fuentes conocidas y confiables. Nunca mandes links HTTP, acortadores, dominios raros, páginas sospechosas, ni enlaces inventados.
- Si la pregunta depende del calendario familiar, lee el calendario primero. Si piden preparación, recomendaciones, prioridades, o logística, usa la herramienta de recomendaciones del calendario.
- Cuando des consejos, separa claramente los hechos de tus sugerencias. No presentes corazonadas como certeza.
- Para crear, modificar o borrar eventos, llama la herramienta correcta apenas entiendas la solicitud. La aplicación detendrá la escritura y te devolverá instrucciones para pedir confirmación antes de ejecutarla.
- Nunca muestres errores técnicos en el chat — si algo falla, dilo con gracia y sigue pa'lante.
- Paola es menor de edad — todo el contenido con ella debe ser completamente apropiado.

La fecha y hora actual es: {current_datetime}. Usa siempre esta fecha cuando el usuario diga "hoy", "mañana", "esta semana", etc."""


def _current_user_context(user_name: str | None, user_id: int | None) -> str:
    known_users = {
        get_env("DARWIN_USER_ID"): "Darwin, hombre, más de 40 años, Product Marketing en tecnología y telecomunicaciones",
        get_env("WIFE_USER_ID"): "Francis, mujer, menos de 40 años, farmacéutica",
        get_env("PAOLA_USER_ID"): "Paola, niña de 13 años, 8th grade, le gusta leer y basketball",
    }
    user_id_str = str(user_id) if user_id is not None else None
    if user_id_str and known_users.get(user_id_str):
        return f"Telegram dice que escribe {known_users[user_id_str]}."
    if user_name:
        normalized = user_name.strip().lower()
        if normalized in {"arielle", "puchi"}:
            return "Telegram dice que escribe Arielle/Puchi, niña de 8 años."
        return f"Nombre visible en Telegram: {user_name}. No asumas más identidad que esa."
    return "Usuario no identificado por nombre. No asumas quién es."


def _build_system_prompt(user_name: str | None = None, user_id: int | None = None) -> str:
    tz = ZoneInfo(get_env("TIMEZONE", "America/Toronto"))
    now = datetime.now(tz).strftime("%A, %B %d %Y at %I:%M %p (%Z)")
    prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        current_datetime=now,
        current_user_context=_current_user_context(user_name, user_id),
    )
    return prompt + """

Additional reliability rules:
- When the user asks to create, edit, or delete a calendar event, immediately call the correct tool with all available details. The application will pause the write and require confirmation. Do not merely say that you can do it.
- Do not repeat the same catchphrases, greetings, jokes, or endings. Vary your rhythm and wording according to the situation while keeping the same warm personality.
- When an image is provided, first describe or extract the useful information. If it contains event details, propose the event and use the normal confirmation flow.
"""


def _message_to_dict(message) -> dict:
    if isinstance(message, dict):
        return message
    data = {"role": getattr(message, "role", None), "content": getattr(message, "content", None)}
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        data["tool_calls"] = tool_calls
    return data


def _history_content(content) -> str | None:
    """Convert multimodal turns to compact text before saving conversation memory."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None

    text_parts = [
        part.get("text", "")
        for part in content
        if isinstance(part, dict) and part.get("type") == "text"
    ]
    caption = " ".join(part.strip() for part in text_parts if part.strip())
    return f"[Image sent] {caption}".strip()


def _chat_only_history(messages: list) -> list[dict]:
    """Keep only normal chat turns for memory.

    Tool-call transcripts are valid only as tightly paired API messages. Once
    history is trimmed, those pairs can break, so we do not persist them.
    """
    clean: list[dict] = []
    for raw_message in messages:
        message = _message_to_dict(raw_message)
        role = message.get("role")
        content = _history_content(message.get("content"))
        if role not in {"user", "assistant"} or not content:
            continue
        clean.append({"role": role, "content": content})
    return clean


def _plain_user_text(user_message: str | list[dict]) -> str:
    if isinstance(user_message, str):
        return user_message.strip()
    return " ".join(
        part.get("text", "")
        for part in user_message
        if isinstance(part, dict) and part.get("type") == "text"
    ).strip()


def _is_affirmative(text: str) -> bool:
    return bool(re.fullmatch(
        r"\s*(yes|yep|yeah|confirm|confirmed|do it|go ahead|please do|"
        r"s[ií]|confirmo|confirma|hazlo|dale|de acuerdo|claro)\s*[.!]?\s*",
        text,
        flags=re.IGNORECASE,
    ))


def _is_negative(text: str) -> bool:
    return bool(re.fullmatch(
        r"\s*(no|nope|cancel|never mind|nevermind|don't|do not|"
        r"cancela|cancelar|olvídalo|olvidalo|mejor no)\s*[.!]?\s*",
        text,
        flags=re.IGNORECASE,
    ))


def _confirmation_instruction(tool_name: str, tool_input: dict) -> str:
    if tool_name == "create_calendar_event":
        return (
            "CONFIRMATION REQUIRED. Ask the user whether to create "
            f"'{tool_input.get('title')}' from {tool_input.get('start_datetime')} "
            f"to {tool_input.get('end_datetime')}. Do not say it was created."
        )
    if tool_name == "update_calendar_event":
        return (
            "CONFIRMATION REQUIRED. Briefly summarize the requested event changes "
            "and ask the user to confirm. Do not say it was updated."
        )
    return (
        f"CONFIRMATION REQUIRED. Ask the user whether to delete "
        f"'{tool_input.get('title', 'this event')}'. Do not say it was deleted."
    )


def _append_direct_turn(history: list[dict], user_text: str, reply: str) -> list[dict]:
    return (_chat_only_history(history) + [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": reply},
    ])[-20:]


def _set_pending_write(user_id: int, tool_name: str, tool_input: dict) -> None:
    _pending_writes[user_id] = (tool_name, tool_input, time.monotonic())


def _get_pending_write(user_id: int) -> tuple[str, dict] | None:
    pending = _pending_writes.get(user_id)
    if not pending:
        return None
    tool_name, tool_input, created_at = pending
    if time.monotonic() - created_at > PENDING_WRITE_TTL_SECONDS:
        _pending_writes.pop(user_id, None)
        return None
    return tool_name, tool_input


def process_message(
    user_message: str | list[dict],
    history: list[dict],
    user_name: str | None = None,
    user_id: int | None = None,
) -> tuple[str, list[dict]]:
    """Send a user message to the agent and return the reply and updated history.

    Args:
        user_message: The text the user just sent.
        history: The conversation history so far (list of OpenAI message dicts).
        user_name: Telegram display name for the sender, if available.
        user_id: Telegram user ID for the sender, if available.

    Returns:
        A tuple of (reply_text, updated_history).
    """
    user_text = _plain_user_text(user_message)
    pending_key = user_id if user_id is not None else 0
    pending = _get_pending_write(pending_key)

    if pending and _is_affirmative(user_text):
        tool_name, tool_input = pending
        _pending_writes.pop(pending_key, None)
        try:
            reply = handle_tool_call(tool_name, tool_input)
        except Exception:
            logger.exception("Confirmed calendar write failed: %s", tool_name)
            reply = "I couldn't update the calendar just now. Please try again in a moment."
        return reply, _append_direct_turn(history, user_text, reply)

    if pending and _is_negative(user_text):
        _pending_writes.pop(pending_key, None)
        reply = "No problem, I won't change the calendar."
        return reply, _append_direct_turn(history, user_text, reply)

    client = OpenAI(api_key=get_env("OPENAI_API_KEY"))

    # Prepend system prompt + append new user turn
    messages = (
        [{"role": "system", "content": _build_system_prompt(user_name, user_id)}]
        + _chat_only_history(history)
        + [{"role": "user", "content": user_message}]
    )

    # Agentic loop — keeps running until the model stops requesting tool calls
    while True:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=0.7,
            frequency_penalty=0.25,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason
        logger.info("Agent finish_reason=%s", finish_reason)

        # Add the assistant turn to messages
        messages.append(message)

        if finish_reason == "stop":
            reply = message.content or "(no response)"
            # Return history without the system prompt prefix
            updated_history = _chat_only_history(messages[1:])
            return reply, updated_history

        if finish_reason == "tool_calls":
            # Execute each tool the model requested
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_input = json.loads(tool_call.function.arguments)
                logger.info("Tool call: %s(%s)", tool_name, tool_input)
                if tool_name in WRITE_TOOLS:
                    _set_pending_write(pending_key, tool_name, tool_input)
                    result = _confirmation_instruction(tool_name, tool_input)
                else:
                    result = handle_tool_call(tool_name, tool_input)
                logger.info("Tool result: %s", result)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })
            continue

        if finish_reason == "length":
            # Response was cut off — do NOT save this broken history
            logger.warning("Response cut off (finish_reason=length). History not saved.")
            return "Coño, me cortaron a mitad de la vaina 😅 Intenta con algo más sencillo, pana.", history

        logger.warning("Unexpected finish_reason: %s", finish_reason)
        return "Sorry, something went wrong. Please try again.", history
