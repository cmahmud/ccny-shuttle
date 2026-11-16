"""Conservative display-only GPS stabilization for stationary shuttle reports.

Only when a fresh, explicitly stationary source report agrees with at least
two recent independent GPS fixes within a compact geographic cluster.
The original GPS coordinates are never modified.
"""
from __future__ import annotations

from datetime import datetime
from math import cos, hypot, radians, isfinite
from statistics import median
from .models import Observation

EARTH_M = 6_371_000.0
MAX_FIX_AGE_SECONDS = 30
MAX_WINDOW_SECONDS = 45
MAX_CLUSTER_DIAMETER_METERS = 15
MIN_SAMPLES = 3
VALID_STATIONARY = frozenset({"standing", "standing_at_stop", "stopped"})


def distance_m(a: Observation, b: Observation) -> float:
    """Approximate horizontal GPS separation at campus scale."""
    mean_lat = radians((a.latitude + b.latitude) / 2)
    return EARTH_M * hypot(
        radians(a.latitude - b.latitude),
        radians(a.longitude - b.longitude) * cos(mean_lat),
    )


def stationary_display_position(
    latest: Observation, recent: list[Observation],
    reported_status: str | None, now: datetime,
) -> dict | None:
    """Return derived display coordinates, or None if any safety gate fails.

    Not a claim of absolute hardware accuracy or true vehicle position.
    """
    if reported_status not in VALID_STATIONARY or latest.age_seconds(now) > MAX_FIX_AGE_SECONDS:
        return None
    # Do not mix GPS sources/vehicle IDs or timestamps, even for the same bus.
    fixes = [latest]
    seen = {latest.observed_at}
    for fix in sorted(recent, key=lambda x: x.observed_at, reverse=True):
        lag = (latest.observed_at - fix.observed_at).total_seconds()
        if not (0 < lag <= MAX_WINDOW_SECONDS):
            continue
        if (fix.source, fix.vehicle_id) != (latest.source, latest.vehicle_id):
            continue
        if fix.observed_at in seen:
            continue
        seen.add(fix.observed_at)
        fixes.append(fix)
    if len(fixes) < MIN_SAMPLES or latest.observed_at not in seen:
        return None
    fixes = fixes[:4]
    # Require all fixes to form a tight cluster. If the vehicle is really
    # leaving a stop, the filter disengages immediately.
    if any(distance_m(a, b) > MAX_CLUSTER_DIAMETER_METERS
           for i, a in enumerate(fixes) for b in fixes[i + 1:]):
        return None
    lat = median([f.latitude for f in fixes])
    lon = median([f.longitude for f in fixes])
    if not (isfinite(lat) and isfinite(lon)):
        return None
    displacement = EARTH_M * hypot(
        radians(lat - latest.latitude),
        radians(lon - latest.longitude) * cos(radians(lat)),
    )
    if displacement < 0.5:
        return None
    return {
        "latitude": round(lat, 7), "longitude": round(lon, 7),
        "method": "stationary_median",
        "sampleCount": len(fixes),
        "displacementMeters": round(displacement, 1),
    }
