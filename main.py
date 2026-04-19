import logging
from bot.handlers import build_application
from scheduler.jobs import start_scheduler

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    app = build_application()
    start_scheduler(app)
    logger.info("Bot is running. Press Ctrl+C to stop.")
    try:
        app.run_polling()
    except Exception as e:
        logger.error("run_polling() failed: %s", e, exc_info=True)


if __name__ == "__main__":
    main()
