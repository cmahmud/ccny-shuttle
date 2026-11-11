"""Read-only, aggregate ETA collection health diagnostics.

No bus identifiers, GPS coordinates, or forecasts are exposed. A healthy source
poll is not evidence of a fresh bus position or a valid passenger arrival ETA.
"""
from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

FRESH_SECONDS = 30
POLL_SECONDS = 45


def _when(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Stored source timestamp lacks timezone')
    return parsed.astimezone(timezone.utc)


def _age(now: datetime, value: str | None) -> float | None:
    at = _when(value)
    return round(max(0.0, (now-at).total_seconds()), 1) if at else None


def diagnose(source_db: str, shadow_db: str, now: datetime | None = None) -> dict:
    """Return a private, non-identifying summary of missing ETA inputs."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now must have timezone information')
    now = now.astimezone(timezone.utc)
    with sqlite3.connect(f'file:{source_db}?mode=ro', uri=True) as gps:
        latest_poll = gps.execute(
            "SELECT last_successful_poll_at FROM feed_state WHERE source='student_public'"
        ).fetchone()
        latest_fix = gps.execute(
            "SELECT MAX(observed_at) FROM observations WHERE source='student_public'"
        ).fetchone()[0]
        historic_buses = gps.execute(
            "SELECT count(distinct vehicle_id) FROM observations WHERE source='student_public'"
        ).fetchone()[0]
        # Count at most one fix per vehicle, not thousands of older samples.
        latest_rows = gps.execute(
            """SELECT o.vehicle_id,o.observed_at,
                      c.reported_status,c.direction,c.observed_at
               FROM observations AS o
               JOIN (SELECT vehicle_id,MAX(observed_at) as latest_at
                     FROM observations WHERE source='student_public'
                     GROUP BY vehicle_id) AS latest
                 ON o.vehicle_id=latest.vehicle_id AND o.observed_at=latest.latest_at
               LEFT JOIN vehicle_context AS c
                 ON c.source=o.source AND c.vehicle_id=o.vehicle_id
               WHERE o.source='student_public'"""
        ).fetchall()
        student_count = gps.execute(
            "SELECT count(*) FROM forecast_comparisons WHERE source='student_public'"
        ).fetchone()[0]
        context_count = gps.execute(
            "SELECT count(*) FROM vehicle_context_history WHERE source='student_public'"
        ).fetchone()[0]
    with sqlite3.connect(f'file:{shadow_db}?mode=ro', uri=True) as shadow:
        shadow_count = shadow.execute(
            "SELECT count(*) FROM shadow_forecasts WHERE source='student_public'"
        ).fetchone()[0]
    poll_age = _age(now, latest_poll[0] if latest_poll else None)
    fix_age = _age(now, latest_fix)
    fresh_rows = [row for row in latest_rows
                  if (age := _age(now, row[1])) is not None and age <= FRESH_SECONDS]
    moving = sum(1 for row in fresh_rows if row[2]=='moving' and
                 row[3] in ('NB','SB') and row[4]==row[1])
    if poll_age is None:
        reason = 'relay_never_polled'
    elif poll_age > POLL_SECONDS:
        reason = 'relay_poll_delayed'
    elif not fresh_rows:
        reason = 'upstream_has_no_fresh_vehicle_positions'
    elif not moving:
        reason = 'no_fresh_directional_moving_vehicle'
    else:
        reason = 'fresh_moving_vehicle_available_for_shadow_checks'
    return {
        'reason': reason,
        'healthyRelayPoll': poll_age is not None and poll_age <= POLL_SECONDS,
        'sourcePollAgeSeconds': poll_age,
        'latestGpsAgeSeconds': fix_age,
        'historicallyObservedVehicles': historic_buses,
        'freshVehicles': len(fresh_rows),
        'freshMovingCandidates': moving,
        'studentForecastRows': student_count,
        'shadowForecastRows': shadow_count,
        'contextHistoryRows': context_count,
        'pairedComparisonPossible': student_count > 0 and shadow_count > 0,
        'explanation': 'This health summary does not validate ETA accuracy or enable public predictions.'
    }
