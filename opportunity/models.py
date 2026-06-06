"""Validated Opportunity Scout domain models."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse


def _required_text(value: Any, field_name: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise ValueError(f"{field_name} is required")
    return text[:500]


def _optional_https_url(value: Any) -> str | None:
    if not value:
        return None
    url = str(value).strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("external URLs must use HTTPS")
    return url


def _datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return result


@dataclass(frozen=True)
class ExternalEvent:
    id: str
    title: str
    description: str
    source: str
    source_url: str
    venue: str
    address: str
    start: datetime
    end: datetime
    categories: tuple[str, ...]
    min_age: int | None = None
    max_age: int | None = None
    indoor_outdoor: str = "unknown"
    registration_required: bool = False
    registration_deadline: datetime | None = None
    availability_status: str = "unknown"
    admission_cost: float = 0
    parking_cost: float = 0
    incidental_cost: float = 0
    travel_minutes: int = 20
    relevant_members: tuple[str, ...] = ("family",)
    weather_sensitive: bool = False
    accessibility: str = ""
    cancellation_policy: str = ""
    image_url: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    confidence: float = 0.7
    discovered_at: datetime | None = None
    last_verified_at: datetime | None = None

    @property
    def total_cost(self) -> float:
        return round(self.admission_cost + self.parking_cost + self.incidental_cost, 2)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ExternalEvent":
        start = _datetime(raw.get("start"), "start")
        end = _datetime(raw.get("end"), "end")
        if end <= start:
            raise ValueError("event end must be after start")

        categories = tuple(
            dict.fromkeys(
                _required_text(category, "category").lower()
                for category in raw.get("categories", [])
            )
        )
        if not categories:
            raise ValueError("at least one category is required")

        min_age = raw.get("min_age")
        max_age = raw.get("max_age")
        if min_age is not None and max_age is not None and int(min_age) > int(max_age):
            raise ValueError("min_age cannot exceed max_age")

        confidence = float(raw.get("confidence", 0.7))
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")

        return cls(
            id=_required_text(raw.get("id"), "id"),
            title=_required_text(raw.get("title"), "title"),
            description=_required_text(raw.get("description"), "description"),
            source=_required_text(raw.get("source"), "source"),
            source_url=_optional_https_url(raw.get("source_url")) or "",
            venue=_required_text(raw.get("venue"), "venue"),
            address=_required_text(raw.get("address"), "address"),
            start=start,
            end=end,
            categories=categories,
            min_age=int(min_age) if min_age is not None else None,
            max_age=int(max_age) if max_age is not None else None,
            indoor_outdoor=str(raw.get("indoor_outdoor", "unknown")).lower(),
            registration_required=bool(raw.get("registration_required", False)),
            registration_deadline=_datetime(raw["registration_deadline"], "registration_deadline")
            if raw.get("registration_deadline")
            else None,
            availability_status=str(raw.get("availability_status", "unknown")).lower(),
            admission_cost=max(0, float(raw.get("admission_cost", 0))),
            parking_cost=max(0, float(raw.get("parking_cost", 0))),
            incidental_cost=max(0, float(raw.get("incidental_cost", 0))),
            travel_minutes=max(0, int(raw.get("travel_minutes", 20))),
            relevant_members=tuple(raw.get("relevant_members", ["family"])),
            weather_sensitive=bool(raw.get("weather_sensitive", False)),
            accessibility=str(raw.get("accessibility", ""))[:300],
            cancellation_policy=str(raw.get("cancellation_policy", ""))[:300],
            image_url=_optional_https_url(raw.get("image_url")),
            latitude=float(raw["latitude"]) if raw.get("latitude") is not None else None,
            longitude=float(raw["longitude"]) if raw.get("longitude") is not None else None,
            confidence=confidence,
            discovered_at=_datetime(raw["discovered_at"], "discovered_at") if raw.get("discovered_at") else None,
            last_verified_at=_datetime(raw["last_verified_at"], "last_verified_at")
            if raw.get("last_verified_at")
            else None,
        )


@dataclass(frozen=True)
class FreeWindow:
    start: datetime
    end: datetime
    available_members: tuple[str, ...] = ("family",)
    kind: str = "full_family"

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass(frozen=True)
class Recommendation:
    activity: ExternalEvent
    window: FreeWindow
    score: float
    explanation: str
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["activity"]["start"] = self.activity.start.isoformat()
        data["activity"]["end"] = self.activity.end.isoformat()
        for key in ("registration_deadline", "discovered_at", "last_verified_at"):
            value = getattr(self.activity, key)
            data["activity"][key] = value.isoformat() if value else None
        data["window"]["start"] = self.window.start.isoformat()
        data["window"]["end"] = self.window.end.isoformat()
        return data
