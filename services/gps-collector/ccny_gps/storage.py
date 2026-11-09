"""Transactional SQLite prototype storage; migrate to PostgreSQL for production."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime, timezone
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
                CREATE TABLE IF NOT EXISTS feed_state (
                    source TEXT PRIMARY KEY,
                    last_successful_poll_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feed_scopes (
                    source TEXT PRIMARY KEY,
                    vehicle_ids_hash TEXT NOT NULL
                );
            """)

    def bind_vehicle_scope(self, source: str, vehicle_ids: frozenset[str]) -> None:
        """Pin checkpoint to exact vehicle allowlist; never skip vehicles silently.

        Changing scope requires a deliberate new database/backfill. A historical
        DB with a cursor but no prior scope binding is also rejected.
        """
        if not source or not vehicle_ids or any(not x.strip() for x in vehicle_ids):
            raise ValueError("Nonempty source and vehicle ID allowlist are mandatory")
        digest = sha256("\n".join(sorted(vehicle_ids)).encode("utf-8")).hexdigest()
        with self.conn:
            previous = self.conn.execute(
                "SELECT vehicle_ids_hash FROM feed_scopes WHERE source = ?", (source,)
            ).fetchone()
            if previous:
                if previous[0] != digest:
                    raise ValueError("Shuttle vehicle scope changed; create a new feed checkpoint")
                return
            if self.get_cursor(source) is not None:
                raise ValueError("Legacy checkpoint has no vehicle scope; explicit migration required")
            self.conn.execute(
                "INSERT INTO feed_scopes(source,vehicle_ids_hash) VALUES(?,?)",
                (source, digest),
            )

    def get_cursor(self, source: str) -> str | None:
        row = self.conn.execute(
            "SELECT end_cursor FROM cursors WHERE source = ?", (source,)
        ).fetchone()
        return row[0] if row else None

    def commit_page(
        self, source: str, observations: tuple[Observation, ...], cursor: str,
        polled_at: datetime | None = None,
    ) -> int:
        """Persist events and cursor in the SAME transaction to avoid gaps."""
        if not cursor:
            raise ValueError("Cannot checkpoint an empty cursor")
        polled_at = polled_at or datetime.now(timezone.utc)
        if polled_at.tzinfo is None:
            raise ValueError("Polling timestamp must include a timezone")
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
            self.conn.execute(
                """INSERT INTO feed_state(source, last_successful_poll_at) VALUES (?, ?)
                ON CONFLICT(source) DO UPDATE
                SET last_successful_poll_at = excluded.last_successful_poll_at""",
                (source, polled_at.astimezone(timezone.utc).isoformat()),
            )
        return after_events - before


    def last_successful_poll(self, source: str) -> datetime | None:
        row = self.conn.execute(
            "SELECT last_successful_poll_at FROM feed_state WHERE source = ?", (source,)
        ).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def latest_observations(self, source: str = "samsara") -> list[Observation]:
        rows = self.conn.execute("""
            WITH latest AS (
                SELECT source, vehicle_id, latitude, longitude, observed_at, received_at,
                       heading_degrees, speed_mph,
                       ROW_NUMBER() OVER (
                           PARTITION BY source, vehicle_id
                           ORDER BY observed_at DESC, id DESC
                       ) AS rn
                FROM observations WHERE source = ?
            )
            SELECT source, vehicle_id, latitude, longitude, observed_at, received_at,
                   heading_degrees, speed_mph
            FROM latest WHERE rn = 1 ORDER BY vehicle_id
        """, (source,)).fetchall()
        return [
            Observation(
                source=row[0], vehicle_id=row[1], latitude=row[2], longitude=row[3],
                observed_at=datetime.fromisoformat(row[4]),
                received_at=datetime.fromisoformat(row[5]),
                heading_degrees=row[6], speed_mph=row[7],
            )
            for row in rows
        ]

    def count_observations(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

    def close(self) -> None:
        self.conn.close()
