"""Read-only replay of authorized persisted GPS observations into historical stop events.

Not connected to live collection. Requires manually verified stop geometry and shuttle IDs.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .core import GPSFix, VerifiedStop, StopDetector, build_travel_samples
from .storage import HistoryStore


@dataclass(frozen=True)
class ReplayConfig:
    stops: tuple[VerifiedStop, ...]
    vehicles: frozenset[str]
    edges: dict[tuple[str, str], str]


def load_config(path: str) -> ReplayConfig:
    config = json.loads(Path(path).read_text())
    if not isinstance(config, dict):
        raise ValueError("Expected a JSON object")
    raw_stops = config.get("stops")
    raw_vehicles = config.get("allowed_vehicle_ids")
    raw_edges = config.get("allowed_legs")
    if not isinstance(raw_stops, list) or not isinstance(raw_vehicles, list) or not isinstance(raw_edges, list):
        raise ValueError("stops, allowed_vehicle_ids and allowed_legs lists are required")
    stops = tuple(VerifiedStop(
        s["id"], float(s["latitude"]), float(s["longitude"]),
        float(s["radius_m"]), verified=s.get("verified") is True
    ) for s in raw_stops)
    if not stops or len({s.id for s in stops}) != len(stops):
        raise ValueError("Verified stops must be nonempty and unique")
    vehicles = frozenset(x for x in raw_vehicles if isinstance(x, str) and x)
    if not vehicles:
        raise ValueError("An explicit shuttle vehicle allowlist is required")
    edges: dict[tuple[str,str],str] = {}
    ids = {x.id for x in stops}
    for e in raw_edges:
        origin, destination, route = e["from"], e["to"], e["route"]
        if origin not in ids or destination not in ids or origin == destination or not route:
            raise ValueError("Leg endpoints require verified, different stops and route ID")
        edges[(origin, destination)] = route
    return ReplayConfig(stops, vehicles, edges)


def read_fixes(db_path: str, allowed: frozenset[str], source: str = "samsara") -> list[GPSFix]:
    if source not in ("samsara", "student_public"):
        raise ValueError("Unsupported GPS source")
    p = Path(db_path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError("GPS observation database is missing")
    connection = sqlite3.connect(f"file:{quote(str(p))}?mode=ro", uri=True)
    try:
        # Only source-confirmed observations already saved by the authorized collector.
        rows = connection.execute(
            "SELECT vehicle_id, observed_at, latitude, longitude, speed_mph "
            "FROM observations WHERE source = ? "
            "ORDER BY observed_at ASC, id ASC", (source,)
        )
        fixes = []
        for vehicle_id, observed_at, latitude, longitude, speed_mph in rows:
            if vehicle_id not in allowed:
                continue
            fixes.append(GPSFix(vehicle_id, datetime.fromisoformat(observed_at),
                                latitude, longitude, speed_mph, source=source))
        return fixes
    finally:
        connection.close()


def replay(config: ReplayConfig, fixes: list[GPSFix]):
    detector = StopDetector(list(config.stops))
    events = []
    for fix in sorted(fixes, key=lambda f: f.observed_at):
        if fix.vehicle_id not in config.vehicles:
            continue
        events.extend(detector.observe(fix))
    return events, build_travel_samples(events, config.edges)


def main():
    parser = argparse.ArgumentParser(description="Replay *previously collected* CCNY GPS history")
    parser.add_argument("--gps-db", required=True, help="Read-only collector SQLite database")
    parser.add_argument("--source", choices=("samsara", "student_public"), default="samsara")
    parser.add_argument("--verified-config", required=True,
                        help="JSON with manually validated stop geofences, shuttle IDs and route edges")
    parser.add_argument("--history-db", help="Separate writable inferred stop-event/history SQLite database")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print derived counts without creating or altering history")
    args = parser.parse_args()
    if not args.dry_run and not args.history_db:
        parser.error("Provide --history-db or --dry-run")
    if args.history_db and Path(args.history_db).resolve() == Path(args.gps_db).resolve():
        parser.error("GPS source and event history cannot use the same database")
    config = load_config(args.verified_config)
    fixes = read_fixes(args.gps_db, config.vehicles, source=args.source)
    events, samples = replay(config, fixes)
    result = {"mode": "dry_run" if args.dry_run else "persistent_replay",
              "gps_source": args.source,
              "gps_observations": len(fixes), "inferred_stop_events": len(events),
              "completed_travel_legs": len(samples), "live_gps": False}
    if not args.dry_run:
        store = HistoryStore(args.history_db)
        try:
            result["new_events"] = store.add_events(events)
            result["new_legs"] = store.add_samples(samples)
            result["total_stored"] = store.count()
        finally:
            store.close()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
