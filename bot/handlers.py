import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from agent.brain import process_message
from storage.memory import get_history, append_history
from bot.commands import cmd_today, cmd_week, cmd_list, cmd_help

load_dotenv()
logger = logging.getLogger(__name__)


def _family_chat_id() -> int:
    chat_id = os.environ.get("FAMILY_CHAT_ID")
    if not chat_id:
        raise RuntimeError("FAMILY_CHAT_ID is not set in .env")
    return int(chat_id)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route incoming family messages through the agent brain."""
    if not update.message or not update.message.text:
        return

    # Only respond in the family group chat
    if update.message.chat_id != _family_chat_id():
        logger.warning("Ignored message from chat_id=%s", update.message.chat_id)
        return

    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name or "someone"
    user_text = update.message.text

    logger.info("Message from %s (id=%s): %s", user_name, user_id, user_text)

    # Show typing indicator while the agent thinks
    await context.bot.send_chat_action(
        chat_id=update.message.chat_id, action="typing"
    )

    history = get_history(user_id)
    try:
        reply, updated_history = process_message(user_text, history)
        append_history(user_id, updated_history)
    except Exception as e:
        logger.error("Agent error for user %s: %s", user_id, e, exc_info=True)
        reply = "Sorry, I ran into a problem. Try again in a moment."

    await update.message.reply_text(reply)


def build_application() -> Application:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Telegram application built.")
    return app
