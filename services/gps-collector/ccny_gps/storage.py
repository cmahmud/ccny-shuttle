"""Transactional SQLite prototype storage; migrate to PostgreSQL for production."""
from pathlib import Path
import sqlite3

from .models import Observation


class ObservationStore:
    def __init__(self, path: str):
        database = Path(path).expanduser()
        database.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(database)
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.execute("PRAGMA journal_mode = WAL")
        with self.conn:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY,
                    source TEXT NOT NULL,
                    vehicle_id TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    observed_at TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    heading_degrees REAL,
                    speed_mph REAL,
                    UNIQUE(source, vehicle_id, observed_at, latitude, longitude)
                );
                CREATE INDEX IF NOT EXISTS observations_by_vehicle_time
                    ON observations(vehicle_id, observed_at DESC);
                CREATE TABLE IF NOT EXISTS cursors (
                    source TEXT PRIMARY KEY,
                    end_cursor TEXT NOT NULL
                );
            """)

    def get_cursor(self, source: str) -> str | None:
        row = self.conn.execute(
            "SELECT end_cursor FROM cursors WHERE source = ?", (source,)
        ).fetchone()
        return row[0] if row else None

    def commit_page(self, source: str, observations: tuple[Observation, ...], cursor: str) -> int:
        """Persist events and cursor in the SAME transaction to avoid gaps."""
        if not cursor:
            raise ValueError("Cannot checkpoint an empty cursor")
        before = self.conn.total_changes
        with self.conn:
            for obs in observations:
                self.conn.execute(
                    """INSERT OR IGNORE INTO observations
                    (source, vehicle_id, latitude, longitude, observed_at, received_at,
                     heading_degrees, speed_mph)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        obs.source, obs.vehicle_id, obs.latitude, obs.longitude,
                        obs.observed_at.isoformat(), obs.received_at.isoformat(),
                        obs.heading_degrees, obs.speed_mph,
                    ),
                )
            after_events = self.conn.total_changes
            self.conn.execute(
                """INSERT INTO cursors(source, end_cursor) VALUES (?, ?)
                ON CONFLICT(source) DO UPDATE SET end_cursor = excluded.end_cursor""",
                (source, cursor),
            )
        return after_events - before

    def count_observations(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

    def close(self) -> None:
        self.conn.close()
