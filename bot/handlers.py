import os
import base64
import logging
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from agent.brain import process_message
from config.env import get_env, require_env
from storage.memory import get_history, append_history
from storage.proactivity import record_conversation_turn
from bot.commands import (
    cmd_help,
    cmd_list,
    cmd_prices,
    cmd_scout,
    cmd_scout_add,
    cmd_scout_dismiss,
    cmd_scout_hide,
    cmd_scout_interest,
    cmd_scout_more,
    cmd_scout_preferences,
    cmd_scout_save,
    cmd_today,
    cmd_week,
)

load_dotenv()
logger = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 15 * 1024 * 1024
SUPPORTED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _family_chat_id() -> int:
    return int(require_env("FAMILY_CHAT_ID"))


def _tz() -> ZoneInfo:
    return ZoneInfo(get_env("TIMEZONE", "America/Toronto"))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route incoming family messages through the agent brain."""
    if not update.message:
        return

    # Only respond in the family group chat
    if update.message.chat_id != _family_chat_id():
        logger.warning("Ignored message from chat_id=%s", update.message.chat_id)
        return

    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name or "someone"
    user_text = update.message.text or update.message.caption or ""
    user_content: str | list[dict] = user_text

    image = None
    mime_type = "image/jpeg"
    if update.message.photo:
        image = update.message.photo[-1]
    elif update.message.document and (update.message.document.mime_type or "").startswith("image/"):
        image = update.message.document
        mime_type = update.message.document.mime_type or mime_type

    if image:
        if image.file_size and image.file_size > MAX_IMAGE_BYTES:
            await update.message.reply_text("That image is too large for me to read. Please send a smaller version.")
            return
        if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
            await update.message.reply_text("I can read JPEG, PNG, WEBP, or GIF images. Please resend it in one of those formats.")
            return
        try:
            telegram_file = await context.bot.get_file(image.file_id)
            image_bytes = await telegram_file.download_as_bytearray()
        except Exception as e:
            logger.error("Failed to download Telegram image: %s", e, exc_info=True)
            await update.message.reply_text("I couldn't download that image. Please try sending it again.")
            return
        encoded = base64.b64encode(image_bytes).decode("ascii")
        prompt = user_text or (
            "Read this image and explain the useful details. If it contains an event, "
            "appointment, invitation, or schedule, propose adding it to the family calendar."
        )
        user_content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
        ]

    logger.info("Message from %s (id=%s): %s", user_name, user_id, user_text)

    # Show typing indicator while the agent thinks
    await context.bot.send_chat_action(
        chat_id=update.message.chat_id, action="typing"
    )

    history = get_history(user_id)
    try:
        reply, updated_history = process_message(
            user_content,
            history,
            user_name=user_name,
            user_id=user_id,
        )
        append_history(user_id, updated_history)
        record_conversation_turn(user_id, user_name, user_text, reply, _tz())
    except Exception as e:
        logger.error("Agent error for user %s: %s", user_id, e, exc_info=True)
        reply = "Sorry, I ran into a problem. Try again in a moment."

    await update.message.reply_text(reply)


def build_application() -> Application:
    token = require_env("TELEGRAM_BOT_TOKEN")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("prices", cmd_prices))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("scout", cmd_scout))
    app.add_handler(CommandHandler("scout_add", cmd_scout_add))
    app.add_handler(CommandHandler("scout_save", cmd_scout_save))
    app.add_handler(CommandHandler("scout_dismiss", cmd_scout_dismiss))
    app.add_handler(CommandHandler("scout_more", cmd_scout_more))
    app.add_handler(CommandHandler("scout_preferences", cmd_scout_preferences))
    app.add_handler(CommandHandler("scout_interest", cmd_scout_interest))
    app.add_handler(CommandHandler("scout_hide", cmd_scout_hide))
    message_filter = (filters.TEXT & ~filters.COMMAND) | filters.PHOTO | filters.Document.IMAGE
    app.add_handler(MessageHandler(message_filter, handle_message))
    logger.info("Telegram application built.")
    return app
