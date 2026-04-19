"""Manually trigger the morning briefing to verify formatting in Telegram."""
import sys, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import os
from dotenv import load_dotenv
from telegram import Bot
from telegram.ext import CallbackContext, Application
from scheduler.jobs import morning_briefing

load_dotenv()


async def main() -> None:
    app = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    async with app:
        # Build a minimal context the job function can use
        context = CallbackContext(application=app)
        await morning_briefing(context)
        print("Briefing sent — check Telegram.")


asyncio.run(main())
