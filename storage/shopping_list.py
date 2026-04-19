"""Shopping list stored in the [agent] block of the next grocery calendar event."""
import re
import logging
from gcal.client import get_next_grocery_event, update_event

logger = logging.getLogger(__name__)

# Matches the full [agent]...[/agent] block including surrounding whitespace
_BLOCK_RE = re.compile(r"\[agent\].*?\[/agent\]", re.DOTALL)


def _parse_block(description: str) -> dict:
    """Return key-value pairs from the [agent] block, or {} if none found."""
    match = _BLOCK_RE.search(description or "")
    if not match:
        return {}
    data = {}
    for line in match.group(0).splitlines():
        line = line.strip()
        if ":" in line and not line.startswith("["):
            key, _, value = line.partition(":")
            data[key.strip()] = value.strip()
    return data


def _build_block(data: dict) -> str:
    lines = "\n".join(f"{k}: {v}" for k, v in data.items())
    return f"[agent]\n{lines}\n[/agent]"


def _replace_block(description: str, new_block: str) -> str:
    """Swap out the existing [agent] block, or append one if none exists."""
    if _BLOCK_RE.search(description or ""):
        return _BLOCK_RE.sub(new_block, description)
    sep = "\n\n" if description and not description.endswith("\n\n") else ""
    return f"{description or ''}{sep}{new_block}"


def read_shopping_list() -> tuple[list[str], dict | None]:
    """Return (items, event) for the next grocery event.

    Returns ([], None) if no grocery event exists in the next 30 days.
    """
    event = get_next_grocery_event()
    if not event:
        return [], None
    data = _parse_block(event.get("description", ""))
    raw = data.get("shopping_list", "")
    items = [i.strip() for i in raw.split(",") if i.strip()] if raw else []
    return items, event


def write_shopping_list(items: list[str], event: dict) -> None:
    """Write updated items back into the grocery event's [agent] block."""
    description = event.get("description", "")
    data = _parse_block(description)
    data["type"] = "grocery"
    data["shopping_list"] = ", ".join(items)
    new_description = _replace_block(description, _build_block(data))
    update_event(event_id=event["id"], description=new_description)
    logger.info("Shopping list updated: %d items", len(items))
