"""Environment variable helpers with safe diagnostics."""
from __future__ import annotations

import logging
import os
import re
import unicodedata

logger = logging.getLogger(__name__)


def _normalize_key(key: str) -> str:
    normalized = unicodedata.normalize("NFKC", key).upper()
    return re.sub(r"[^A-Z0-9_]", "", normalized)


def get_env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value:
        return value.strip()

    normalized_name = _normalize_key(name)
    for key, candidate in os.environ.items():
        if _normalize_key(key) == normalized_name and candidate:
            logger.warning(
                "Using environment variable %r as %s. Rename it to exactly %s.",
                key,
                name,
                name,
            )
            return candidate.strip()

    return default


def require_env(name: str) -> str:
    value = get_env(name)
    if value:
        return value

    related = [
        key
        for key in sorted(os.environ)
        if any(part in _normalize_key(key) for part in _normalize_key(name).split("_"))
    ]
    logger.error(
        "Missing required environment variable %s. Related variable names visible: %s",
        name,
        related[:20],
    )
    raise RuntimeError(f"{name} is not set")
