"""Public CCNY shuttle tracker feed adapter (third-party GPS relay).

Reads publicly available /tracker-data/feed responses emitted by an ordinary
browser session on the student tracker, without replaying private URLs,
collecting cookies or bypassing HTTP 403. The JSON payload is not Samsara's
official feed, and must never be labeled independently verified GPS.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from zoneinfo import ZoneInfo

from .models import Observation

SOURCE = "student_public"
BASE_URL = "https://ccnyshuttlebus.com/"
FEED_PATH = "/tracker-data/feed"
NY = ZoneInfo("America/New_York")

# Loose campus-area safety bounds; not exact stop coordinates.
BOUNDS = (40.78, 40.86, -74.02, -73.88)
MAX_FEED_AGE_SECONDS = 90
MAX_FIX_AGE_SECONDS = 600
MAX_VEHICLES = 25


@dataclass(frozen=True)
class PublicSnapshot:
    observations: tuple[Observation, ...]
    feed_generated_at: datetime
    upstream_polled_at: datetime
    source_state: str
    vehicles_rejected: int


def _milliseconds(value: object, name: str) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be a valid Unix millisecond timestamp")
    if value < 1_600_000_000_000 or value > 4_000_000_000_000:
        raise ValueError(f"{name} must be Unix milliseconds, not seconds")
    return datetime.fromtimestamp(value / 1000, timezone.utc)


def parse_public_feed(payload: object, received_at: datetime) -> PublicSnapshot:
    if received_at.tzinfo is None:
        raise ValueError("Reception time must include timezone")
    received_at = received_at.astimezone(timezone.utc)
    if not isinstance(payload, dict) or not isinstance(payload.get("live"), dict):
        raise ValueError("Student feed must contain a live object")
    live = payload["live"]
    generated = _milliseconds(live.get("generatedAt"), "generatedAt")
    polled = _milliseconds(live.get("lastSuccessfulPoll"), "lastSuccessfulPoll")
    age = (received_at - generated).total_seconds()
    poll_age = (received_at - polled).total_seconds()
    if not -20 <= age <= MAX_FEED_AGE_SECONDS:
        raise ValueError("Student public feed response is stale or future-dated")
    if not -20 <= poll_age <= 120:
        raise ValueError("Upstream GPS polling status is stale or future-dated")
    state = live.get("sourceState")
    if not isinstance(state, str) or state not in (
        "live", "delayed", "stale", "no_data", "unconfigured", "offline"
    ):
        raise ValueError("Unrecognized third-party source state")
    reported = live.get("vehicles")
    if not isinstance(reported, list) or len(reported) > MAX_VEHICLES:
        raise ValueError("Malformed or oversized public vehicle list")
    observations = []
    rejected = 0
    used = set()
    for vehicle in reported:
        if not isinstance(vehicle, dict):
            rejected += 1
            continue
        try:
            vid = vehicle["vehicleId"]
            if not isinstance(vid, str) or not vid or len(vid) > 96:
                raise ValueError("Invalid vehicle ID")
            if vid in used:
                raise ValueError("Duplicate vehicle ID")
            lat = float(vehicle["lat"])
            lon = float(vehicle["lon"])
            if not (BOUNDS[0] < lat < BOUNDS[1] and BOUNDS[2] < lon < BOUNDS[3]):
                raise ValueError("Location outside CCNY region")
            observed = _milliseconds(vehicle.get("observedAt"), "observedAt")
            observed_age = (received_at - observed).total_seconds()
            if not -20 <= observed_age <= MAX_FIX_AGE_SECONDS:
                raise ValueError("GPS observation expired or in future")
            heading = vehicle.get("heading")
            if heading is not None:
                heading = float(heading)
            obs = Observation(
                source=SOURCE,
                vehicle_id=vid,
                latitude=lat,
                longitude=lon,
                observed_at=observed,
                received_at=received_at,
                heading_degrees=heading,
                speed_mph=None,
            )
            observations.append(obs)
            used.add(vid)
        except (TypeError, ValueError, OverflowError, KeyError):
            rejected += 1

    # Do not promote an upstream outage to 'live'. Previously recorded fixes
    # stay in history but will age out of the live status API.
    if state != "live":
        observations.clear()
    return PublicSnapshot(
        tuple(observations), generated, polled, state, rejected
    )


def in_service_window(now: datetime) -> bool:
    """Avoid crawling a closed service all night. Holidays can still close it."""
    if now.tzinfo is None:
        raise ValueError("Timezone-aware time required")
    local = now.astimezone(NY)
    return local.weekday() < 5 and (6 * 60 + 15 <= local.hour * 60 + local.minute <= 22 * 60 + 15)
