"""Manually trigger the pre-event check to test reminder formatting in Telegram."""
import sys, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import os
from dotenv import load_dotenv
from telegram.ext import Application, CallbackContext
from scheduler.jobs import pre_event_check

load_dotenv()


async def main() -> None:
    app = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    async with app:
        context = CallbackContext(application=app)
        await pre_event_check(context)
        print("Pre-event check done — check Telegram (or terminal if no events in window).")


asyncio.run(main())
