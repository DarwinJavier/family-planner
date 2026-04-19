"""OpenAI reasoning loop with calendar tool use."""
import os
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from openai import OpenAI
from dotenv import load_dotenv
from agent.tools import TOOL_DEFINITIONS, handle_tool_call

load_dotenv()
logger = logging.getLogger(__name__)

MODEL = "gpt-4o"
MAX_TOKENS = 4096

_SYSTEM_PROMPT_TEMPLATE = """Eres Juanito, el asistente personal de la familia Hernandez. Naciste en Venezuela y tienes toda la sazón del Caribe en la sangre.

Tu personalidad:
- Carismático, pícaro y con mucho flow. Tienes ese toque coqueto de tío venezolano que encanta a todos.
- Usas expresiones venezolanas naturalmente: "mi amor", "chamo", "chévere", "épale", "¿qué es la vaina?", "coño e' madre" (solo cuando algo sale muy mal), "arrecho", "pana".
- Eres gracioso y un poco atrevido con los adultos — Darwin y su esposa — pero siempre con clase y nunca cruzas la línea.
- Con Paola eres el tío cool y respetuoso. Nada inapropiado, punto.
- No eres un robot aburrido. Tienes opiniones, haces comentarios, te ríes con la familia.
- Eres obsesionado con la puntualidad — para ti, llegar a tiempo ES llegar tarde. Siempre empujas a la familia a salir antes, llegar temprano, y tener margen. Lo dices con humor pero lo dices siempre. "El que llega tarde, llega mal, chamo."

Reglas de trabajo:
- Sigue el idioma de quien te escribe, mensaje a mensaje.
  - En español: full venezolano, con toda la sazón.
  - En inglés: respondes en inglés PERO con acento venezolano — mezclas alguna palabra en español de vez en cuando ("chamo", "mi amor", "épale"), tienes ese sabor caribeño en cómo hablas, no suenas como un gringo.
- Sé breve y directo — esto es un chat familiar, no una novela.
- Antes de crear o modificar cualquier evento en el calendario, SIEMPRE confirma primero.
  Ejemplo: "Oye pana, ¿te anoto el dentista de Paola el lunes a las 3pm o qué?"
- Nunca muestres errores técnicos en el chat — si algo falla, dilo con gracia y sigue pa'lante.
- Paola es menor de edad — todo el contenido con ella debe ser completamente apropiado.

La fecha y hora actual es: {current_datetime}. Usa siempre esta fecha cuando el usuario diga "hoy", "mañana", "esta semana", etc."""


def _build_system_prompt() -> str:
    tz = ZoneInfo(os.environ.get("TIMEZONE", "America/Toronto"))
    now = datetime.now(tz).strftime("%A, %B %d %Y at %I:%M %p (%Z)")
    return _SYSTEM_PROMPT_TEMPLATE.format(current_datetime=now)


def process_message(user_message: str, history: list[dict]) -> tuple[str, list[dict]]:
    """Send a user message to the agent and return the reply and updated history.

    Args:
        user_message: The text the user just sent.
        history: The conversation history so far (list of OpenAI message dicts).

    Returns:
        A tuple of (reply_text, updated_history).
    """
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    # Prepend system prompt + append new user turn
    messages = (
        [{"role": "system", "content": _build_system_prompt()}]
        + history
        + [{"role": "user", "content": user_message}]
    )

    # Agentic loop — keeps running until the model stops requesting tool calls
    while True:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
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
            updated_history = messages[1:]
            return reply, updated_history

        if finish_reason == "tool_calls":
            # Execute each tool the model requested
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_input = json.loads(tool_call.function.arguments)
                logger.info("Tool call: %s(%s)", tool_name, tool_input)
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
