"""Opportunity Scout discovery and recommendation package."""

from .service import (
    accept_recommendation,
    build_calendar_proposal,
    discover_recommendations,
    dismiss_recommendation,
    format_recommendations,
    get_recommendation,
    recommend_more_like,
    save_recommendation,
)

__all__ = [
    "build_calendar_proposal",
    "accept_recommendation",
    "discover_recommendations",
    "dismiss_recommendation",
    "format_recommendations",
    "get_recommendation",
    "recommend_more_like",
    "save_recommendation",
]
