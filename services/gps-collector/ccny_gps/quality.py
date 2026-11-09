"""Read-only GPS telemetry quality report: cadence, delay, gaps, and coverage.

No location coordinates, vehicle IDs, or driver data are printed.
The metric can help validate whether third-party GPS reports are sufficient
for ETA modeling, but it does not itself establish prediction accuracy.
"""
from __future__ import annotations
import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from statistics import median
from urllib.parse import quote


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * q
    low = int(index)
    high = min(low + 1, len(sorted_values) - 1)
    return round(sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (index - low), 1)


def quality_report(path: str, source: str = "student_public",
                   hours: int = 24, now: datetime | None = None) -> dict:
    if source not in ("student_public", "samsara"):
        raise ValueError("Unknown GPS source")
    if not 1 <= hours <= 720:
        raise ValueError("Window must be between 1 and 720 hours")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Timezone-aware time required")
    now = now.astimezone(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError("GPS history DB does not exist")
    connection = sqlite3.connect(f"file:{quote(str(p))}?mode=ro",uri=True)
    try:
        rows = connection.execute(
            "SELECT vehicle_id,observed_at,received_at FROM observations "
            "WHERE source=? AND received_at>=? AND received_at<=? "
            "ORDER BY vehicle_id,observed_at",
            (source, cutoff.isoformat(), now.isoformat())
        ).fetchall()
        last_poll = connection.execute(
            "SELECT last_successful_poll_at FROM feed_state WHERE source=?", (source,)
        ).fetchone()
    finally:
        connection.close()
    vehicles: dict[str,list[datetime]] = defaultdict(list)
    latency: list[float] = []
    fresh = 0
    delayed = 0
    bad = 0
    for vid, observed_s, received_s in rows:
        try:
            observed = datetime.fromisoformat(observed_s).astimezone(timezone.utc)
            received = datetime.fromisoformat(received_s).astimezone(timezone.utc)
            age = (received-observed).total_seconds()
            if age < -30 or age > 24*3600:
                bad += 1
                continue
            latency.append(max(0,age))
            vehicles[vid].append(observed)
            fresh += age <= 30
            delayed += 30 < age <= 180
        except (TypeError,ValueError,OverflowError):
            bad += 1
    gaps: list[float] = []
    for times in vehicles.values():
        for a,b in zip(times,times[1:]):
            gap = (b-a).total_seconds()
            if gap > 0:
                gaps.append(gap)
    poll_age = None
    if last_poll:
        poll_age = max(0,(now-datetime.fromisoformat(last_poll[0]).astimezone(timezone.utc)).total_seconds())
    return {
        "source":source,
        "windowHours":hours,
        "sampleCount":len(latency),
        "vehicleCount":len(vehicles),
        "qualitySampleSize":"preliminary" if len(latency)<100 else "developing",
        "freshWhenReceivedFraction":round(fresh/len(latency),3) if latency else None,
        "upTo3MinOldWhenReceivedFraction":round(delayed/len(latency),3) if latency else None,
        "p50SourceDelaySeconds":percentile(latency,.5),
        "p90SourceDelaySeconds":percentile(latency,.9),
        "p50GpsReportingIntervalSeconds":percentile(gaps,.5),
        "p90GpsReportingIntervalSeconds":percentile(gaps,.9),
        "maxObservedGapSeconds":round(max(gaps),1) if gaps else None,
        "pollAgeSeconds":round(poll_age,1) if poll_age is not None else None,
        "discardedInvalidRows":bad,
        "note":"Raw update quality only; no actual stop arrivals or ETA accuracy verified",
    }


def main() -> None:
    p=argparse.ArgumentParser(description="Aggregate CCNY Shuttle GPS quality without IDs or locations")
    p.add_argument("--db",required=True)
    p.add_argument("--source",choices=["student_public","samsara"],default="student_public")
    p.add_argument("--hours",type=int,default=24)
    args=p.parse_args()
    print(json.dumps(quality_report(args.db,args.source,args.hours),indent=2))


if __name__=="__main__":
    main()
