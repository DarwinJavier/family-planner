"""Configured discovery-source metadata and source-use policy."""
from __future__ import annotations

from pathlib import Path

import yaml

SOURCE_CONFIG = Path(__file__).parent.parent / "config" / "opportunity_sources.yaml"


def load_source_registry() -> list[dict]:
    with open(SOURCE_CONFIG, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return [source for source in data.get("sources", []) if source.get("enabled", False)]


def source_research_guidance() -> str:
    lines = []
    for source in load_source_registry():
        lines.append(
            f"- {source['name']} ({source['kind']}, reliability={source['reliability']}): "
            f"{source['url']} {source.get('notes', '')}".strip()
        )
    return "\n".join(lines)
