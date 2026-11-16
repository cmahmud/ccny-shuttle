"""Durable history tables for inferred stop events and completed shuttle legs.

SQLite is a development baseline. No external services or GPS source required.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .core import StopEvent, TravelSample


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Timezone required")
    return value.astimezone(timezone.utc).isoformat()


class HistoryStore:
    def __init__(self, path: str):
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(p)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        with self.connection:
            self.connection.executescript("""
              CREATE TABLE IF NOT EXISTS stop_events (
                vehicle_id TEXT NOT NULL,
                stop_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('arrival','departure')),
                event_at TEXT NOT NULL,
                detected_at TEXT NOT NULL,
                method TEXT NOT NULL,
                PRIMARY KEY(vehicle_id,stop_id,kind,event_at)
              );
              CREATE INDEX IF NOT EXISTS idx_stop_events_at ON stop_events(event_at);
              CREATE TABLE IF NOT EXISTS travel_samples (
                vehicle_id TEXT NOT NULL,
                route TEXT NOT NULL,
                from_stop TEXT NOT NULL,
                to_stop TEXT NOT NULL,
                departed_at TEXT NOT NULL,
                arrived_at TEXT NOT NULL,
                evidence TEXT NOT NULL,
                PRIMARY KEY(vehicle_id,route,from_stop,to_stop,departed_at)
              );
              CREATE INDEX IF NOT EXISTS idx_travel_legs ON travel_samples(route,from_stop,to_stop,arrived_at);
            """)

    def add_events(self, events: list[StopEvent]) -> int:
        before = self.connection.total_changes
        with self.connection:
            for e in events:
                self.connection.execute(
                    "INSERT OR IGNORE INTO stop_events VALUES (?,?,?,?,?,?)",
                    (e.vehicle_id,e.stop_id,e.kind,_iso(e.event_at),_iso(e.detected_at),e.method),
                )
        return self.connection.total_changes - before

    def get_events(self) -> list[StopEvent]:
        return [
            StopEvent(v, stop, kind, datetime.fromisoformat(at),
                      datetime.fromisoformat(detected), method)
            for v,stop,kind,at,detected,method in self.connection.execute(
                "SELECT vehicle_id,stop_id,kind,event_at,detected_at,method "
                "FROM stop_events ORDER BY event_at,detected_at,vehicle_id"
            )
        ]

    def add_samples(self, samples: list[TravelSample]) -> int:
        before = self.connection.total_changes
        with self.connection:
            for s in samples:
                self.connection.execute(
                    "INSERT OR IGNORE INTO travel_samples VALUES (?,?,?,?,?,?,?)",
                    (s.vehicle_id,s.route,s.from_stop,s.to_stop,
                     _iso(s.departed_at),_iso(s.arrived_at),s.evidence),
                )
        return self.connection.total_changes - before

    def get_samples(self) -> list[TravelSample]:
        return [
            TravelSample(route, origin, destination,
                         datetime.fromisoformat(departure),datetime.fromisoformat(arrival),
                         vehicle, evidence)
            for vehicle,route,origin,destination,departure,arrival,evidence in
                self.connection.execute(
                    "SELECT vehicle_id,route,from_stop,to_stop,departed_at,arrived_at,evidence "
                    "FROM travel_samples ORDER BY arrived_at"
                )
        ]

    def count(self) -> dict[str, int]:
        return {table: self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("stop_events","travel_samples")}

    def close(self):
        self.connection.close()
