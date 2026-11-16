"""Incremental, crash-recoverable stop-event ingestion from the authorized GPS database.

The GPS database is opened read-only. All derived stop events, travel segments,
geofence detector states and source checkpoint are committed atomically to a
separate SQLite database. This command intentionally requires a validated stop
configuration and does not connect to Samsara itself.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import quote

from .core import (
    GPSFix, StopDetector, StopEvent, TravelSample, _FenceState
)
from .replay import ReplayConfig, load_config
from .storage import HistoryStore


STATE_SCHEMA_VERSION = 1


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("UTC timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def config_fingerprint(config: ReplayConfig) -> str:
    canonical = {
        "schema": STATE_SCHEMA_VERSION,
        "vehicles": sorted(config.vehicles),
        "stops": sorted(
            [{
                "id": stop.id, "lat": stop.latitude, "lon": stop.longitude,
                "radius": stop.radius_m, "verified": stop.verified,
            } for stop in config.stops], key=lambda x: x["id"]
        ),
        "legs": sorted([
            [a, b, route] for (a, b), route in config.edges.items()
        ]),
    }
    return sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _format_event(event: StopEvent) -> dict:
    return {
        "vehicle_id": event.vehicle_id, "stop_id": event.stop_id,
        "kind": event.kind, "event_at": _utc_iso(event.event_at),
        "detected_at": _utc_iso(event.detected_at), "method": event.method,
    }


def _parse_event(data: dict) -> StopEvent:
    return StopEvent(
        data["vehicle_id"], data["stop_id"], data["kind"],
        datetime.fromisoformat(data["event_at"]),
        datetime.fromisoformat(data["detected_at"]), data["method"]
    )


def _serialize_detector(detector: StopDetector) -> str:
    states = []
    for (vehicle, stop), state in detector.states.items():
        obj = asdict(state)
        for key in ("first_inside", "last_inside", "last_fix"):
            obj[key] = _utc_iso(obj[key]) if obj[key] else None
        states.append({"vehicle": vehicle, "stop": stop, "state": obj})
    return json.dumps(
        sorted(states, key=lambda obj: (obj["vehicle"], obj["stop"])),
        separators=(",", ":")
    )


def _restore_detector(detector: StopDetector, saved: str, config: ReplayConfig) -> None:
    allowed_stops = {stop.id for stop in config.stops}
    for record in json.loads(saved):
        vehicle, stop = record["vehicle"], record["stop"]
        if vehicle not in config.vehicles or stop not in allowed_stops:
            raise ValueError("Persisted detector state has disallowed vehicle/stop")
        attrs = record["state"]
        for key in ("first_inside", "last_inside", "last_fix"):
            attrs[key] = datetime.fromisoformat(attrs[key]) if attrs[key] else None
        detector.states[(vehicle, stop)] = _FenceState(**attrs)


@dataclass(frozen=True)
class BatchResult:
    processed: int
    new_events: int
    new_legs: int
    last_source_id: int
    source_has_more: bool


class IncrementalEventIngestor:
    """Only one worker should write a given history DB at a time.

    Source inserts are read by monotonically increasing observation primary key.
    Per-vehicle out-of-order GPS timestamps are safely ignored by StopDetector.
    """

    def __init__(
        self, gps_db: str, history_db: str,
        config: ReplayConfig, batch_size: int = 500
    ):
        gps = Path(gps_db).expanduser().resolve()
        history = Path(history_db).expanduser().resolve()
        if gps == history:
            raise ValueError("GPS and historical events MUST use separate databases")
        if not gps.is_file():
            raise FileNotFoundError("GPS observations database is missing")
        if batch_size < 1 or batch_size > 5000:
            raise ValueError("Batch size must be between 1 and 5000")
        if not config.stops or not config.vehicles:
            raise ValueError("Require verified stops and explicit shuttle vehicles")

        self.config = config
        self.batch_size = batch_size
        self.fingerprint = config_fingerprint(config)
        self._source = sqlite3.connect(f"file:{quote(str(gps))}?mode=ro", uri=True)
        self._store = HistoryStore(str(history))
        self._store.connection.execute("PRAGMA busy_timeout=5000")
        with self._store.connection:
            self._store.connection.execute("""
                CREATE TABLE IF NOT EXISTS ingest_checkpoint (
                    source TEXT PRIMARY KEY,
                    config_fingerprint TEXT NOT NULL,
                    last_observation_id INTEGER NOT NULL,
                    detector_json TEXT NOT NULL,
                    departures_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                )
            """)
        self._detector = StopDetector(list(config.stops))
        self._pending: dict[str, StopEvent] = {}
        self._last_id = 0
        record = self._store.connection.execute(
            "SELECT config_fingerprint,last_observation_id,detector_json,departures_json "
            "FROM ingest_checkpoint WHERE source='samsara'"
        ).fetchone()
        if record:
            fingerprint, last_id, detector_json, departure_json = record
            if fingerprint != self.fingerprint:
                self.close()
                raise ValueError("Verified stop/route/vehicle configuration has changed; "
                                 "use a new history database and reprocess")
            self._last_id = int(last_id)
            _restore_detector(self._detector, detector_json, config)
            self._pending = {
                key: _parse_event(obj) for key, obj in json.loads(departure_json).items()
            }
            if any(key not in config.vehicles for key in self._pending):
                self.close()
                raise ValueError("Saved pending departure has a disallowed vehicle")
        max_id = self._source.execute("SELECT COALESCE(MAX(id),0) FROM observations").fetchone()[0]
        if max_id < self._last_id:
            self.close()
            raise ValueError("Source GPS database was reset or replaced; refusing to skip history")

    def close(self):
        self._source.close()
        self._store.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def process_batch(self) -> BatchResult:
        rows = self._source.execute(
            "SELECT id,source,vehicle_id,observed_at,latitude,longitude,speed_mph "
            "FROM observations WHERE id > ? ORDER BY id LIMIT ?",
            (self._last_id, self.batch_size + 1)
        ).fetchall()
        more = len(rows) > self.batch_size
        rows = rows[:self.batch_size]
        if not rows:
            return BatchResult(0, 0, 0, self._last_id, False)

        detector = StopDetector(list(self.config.stops))
        _restore_detector(
            detector, _serialize_detector(self._detector), self.config
        )
        pending = dict(self._pending)
        events: list[StopEvent] = []
        legs: list[TravelSample] = []
        for index, source, vehicle, timestamp, lat, lon, speed in rows:
            if source != "samsara" or vehicle not in self.config.vehicles:
                continue
            fix = GPSFix(
                vehicle, datetime.fromisoformat(timestamp), lat, lon, speed, source
            )
            for event in detector.observe(fix):
                events.append(event)
                if event.kind == "departure":
                    pending[vehicle] = event
                else:
                    prior = pending.pop(vehicle, None)
                    if prior is None:
                        continue
                    route = self.config.edges.get((prior.stop_id, event.stop_id))
                    if route:
                        try:
                            legs.append(TravelSample(
                                route, prior.stop_id, event.stop_id,
                                prior.event_at, event.event_at, vehicle,
                            ))
                        except ValueError:
                            pass  # Too short/long, or inconsistent route.

        next_id = rows[-1][0]
        detected_at = _utc_iso(datetime.now(timezone.utc))
        before_events = self._store.connection.total_changes
        with self._store.connection:
            # Prevent two concurrent workers from overwriting each other's
            # detector states/checkpoints. SQLite serializes the write transaction.
            checkpoint = self._store.connection.execute(
                "SELECT config_fingerprint,last_observation_id "
                "FROM ingest_checkpoint WHERE source='samsara'"
            ).fetchone()
            if checkpoint:
                if checkpoint[0] != self.fingerprint or checkpoint[1] != self._last_id:
                    raise RuntimeError("History checkpoint advanced from another process; restart worker")
            elif self._last_id != 0:
                raise RuntimeError("Missing history checkpoint; restart worker")
            for event in events:
                self._store.connection.execute(
                    "INSERT OR IGNORE INTO stop_events "
                    "(vehicle_id,stop_id,kind,event_at,detected_at,method) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        event.vehicle_id, event.stop_id, event.kind,
                        _utc_iso(event.event_at), _utc_iso(event.detected_at),
                        event.method,
                    )
                )
            inserted_events = self._store.connection.total_changes - before_events
            before_legs = self._store.connection.total_changes
            for leg in legs:
                self._store.connection.execute(
                    "INSERT OR IGNORE INTO travel_samples "
                    "(vehicle_id,route,from_stop,to_stop,departed_at,arrived_at,evidence) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        leg.vehicle_id, leg.route, leg.from_stop, leg.to_stop,
                        _utc_iso(leg.departed_at), _utc_iso(leg.arrived_at),
                        leg.evidence,
                    )
                )
            inserted_legs = self._store.connection.total_changes - before_legs
            self._store.connection.execute(
                "INSERT INTO ingest_checkpoint "
                "(source,config_fingerprint,last_observation_id,detector_json,departures_json,recorded_at) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(source) DO UPDATE SET "
                "config_fingerprint=excluded.config_fingerprint,"
                "last_observation_id=excluded.last_observation_id,"
                "detector_json=excluded.detector_json,"
                "departures_json=excluded.departures_json,"
                "recorded_at=excluded.recorded_at",
                ("samsara", self.fingerprint, next_id,
                 _serialize_detector(detector),
                 json.dumps({key: _format_event(event) for key, event in pending.items()}),
                 detected_at),
            )
        self._detector = detector
        self._pending = pending
        self._last_id = next_id
        return BatchResult(len(rows), inserted_events, inserted_legs, next_id, more)


def main():
    parser = argparse.ArgumentParser(
        description="Derive verified stop-event history from previously stored authorized GPS"
    )
    parser.add_argument("--gps-db", required=True)
    parser.add_argument("--history-db", required=True)
    parser.add_argument("--verified-config", required=True,
                        help="Manually verified shuttle vehicle IDs, stop geofences and routes")
    parser.add_argument("--once", action="store_true", help="Process all currently queued GPS rows")
    parser.add_argument("--loop", action="store_true", help="Poll local stored GPS rows every 10s")
    args = parser.parse_args()
    if args.once == args.loop:
        parser.error("Choose exactly one of --once or --loop")
    config = load_config(args.verified_config)
    with IncrementalEventIngestor(args.gps_db, args.history_db, config) as worker:
        while True:
            totals = {"processed": 0, "new_events": 0, "new_legs": 0}
            while True:
                batch = worker.process_batch()
                totals["processed"] += batch.processed
                totals["new_events"] += batch.new_events
                totals["new_legs"] += batch.new_legs
                if not batch.source_has_more:
                    break
            print(json.dumps({**totals, "last_source_id": batch.last_source_id,
                              "live_gps": False, "mode": "authorized_history_ingest"}),
                  flush=True)
            if args.once:
                break
            time.sleep(10)


if __name__ == "__main__":
    main()
