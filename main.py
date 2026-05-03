import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from bot.handlers import build_application
from scheduler.jobs import start_scheduler


def configure_logging() -> None:
    """Log to both the terminal and the rotating app log file."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = TimedRotatingFileHandler(
        log_dir / "family-agent.log",
        when="midnight",
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root.handlers.clear()
    root.addHandler(console_handler)
    root.addHandler(file_handler)


configure_logging()
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
