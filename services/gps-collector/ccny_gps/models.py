"""Normalized, source-timestamped shuttle observations."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite


def parse_time(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("GPS observation timestamp is missing")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("GPS observation timestamp must include a timezone")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class Observation:
    source: str
    vehicle_id: str
    latitude: float
    longitude: float
    observed_at: datetime
    received_at: datetime
    heading_degrees: float | None = None
    speed_mph: float | None = None

    def __post_init__(self) -> None:
        if not self.vehicle_id or not self.source:
            raise ValueError("Source and vehicle ID are required")
        if not isfinite(self.latitude) or not -90 <= self.latitude <= 90:
            raise ValueError("Invalid latitude")
        if not isfinite(self.longitude) or not -180 <= self.longitude <= 180:
            raise ValueError("Invalid longitude")
        if self.observed_at.tzinfo is None or self.received_at.tzinfo is None:
            raise ValueError("Timestamps must include a timezone")
        if self.observed_at > self.received_at + timedelta(minutes=5):
            raise ValueError("Source timestamp is implausibly far in the future")
        if self.heading_degrees is not None and (
            not isfinite(self.heading_degrees) or not 0 <= self.heading_degrees <= 360
        ):
            raise ValueError("Invalid heading")
        if self.speed_mph is not None and (
            not isfinite(self.speed_mph) or self.speed_mph < 0
        ):
            raise ValueError("Invalid speed")

    def age_seconds(self, now: datetime) -> float:
        if now.tzinfo is None:
            raise ValueError("Current time must include a timezone")
        return max(0.0, (now - self.observed_at).total_seconds())

    def freshness(self, now: datetime) -> str:
        age = self.age_seconds(now)
        if age <= 30:
            return "fresh"
        if age <= 120:
            return "delayed"
        return "stale"
