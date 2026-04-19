"""In-memory conversation history per Telegram user. Resets on bot restart."""
from collections import defaultdict

# Maps telegram user_id (int) → list of OpenAI message dicts
_history: dict[int, list[dict]] = defaultdict(list)

MAX_TURNS = 20  # keep last 20 messages per user to avoid unbounded growth


def get_history(user_id: int) -> list[dict]:
    return _history[user_id]


def append_history(user_id: int, history: list[dict]) -> None:
    _history[user_id] = history[-MAX_TURNS:]


def clear_history(user_id: int) -> None:
    _history[user_id] = []
