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
                CREATE TABLE IF NOT EXISTS forecast_comparisons (
                    id INTEGER PRIMARY KEY,
                    source TEXT NOT NULL,
                    stop_id TEXT NOT NULL,
                    vehicle_id TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    forecast_generated_at TEXT NOT NULL,
                    forecast_bucket INTEGER NOT NULL,
                    arrival_at TEXT NOT NULL,
                    earliest_at TEXT,
                    latest_at TEXT,
                    source_enabled INTEGER NOT NULL,
                    ingested_at TEXT NOT NULL,
                    UNIQUE(source,stop_id,vehicle_id,direction,forecast_bucket)
                );
                CREATE INDEX IF NOT EXISTS forecast_comparisons_by_time
                    ON forecast_comparisons(forecast_generated_at,vehicle_id,stop_id);
                -- Latest upstream stop arrival schedule, distinct from the
                -- sampled forecasts used for historical accuracy benchmarks.
                CREATE TABLE IF NOT EXISTS source_arrival_schedule (
                    source TEXT NOT NULL,
                    stop_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    vehicle_id TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    arrival_at TEXT NOT NULL,
                    earliest_at TEXT,
                    latest_at TEXT,
                    source_enabled INTEGER NOT NULL,
                    ingested_at TEXT NOT NULL,
                    PRIMARY KEY(source,stop_id,ordinal)
                );
                CREATE INDEX IF NOT EXISTS arrival_schedule_by_source
                    ON source_arrival_schedule(source,ingested_at);
                CREATE TABLE IF NOT EXISTS vehicle_context_history (
                    source TEXT NOT NULL,
                    vehicle_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    bus_name TEXT,
                    direction TEXT,
                    reported_status TEXT,
                    next_stop_id TEXT,
                    PRIMARY KEY(source,vehicle_id,observed_at)
                );
                CREATE INDEX IF NOT EXISTS vehicle_context_history_by_time
                    ON vehicle_context_history(observed_at,vehicle_id);
                CREATE TABLE IF NOT EXISTS vehicle_context (
                    source TEXT NOT NULL,
                    vehicle_id TEXT NOT NULL,
                    bus_name TEXT,
                    direction TEXT,
                    reported_status TEXT,
                    next_stop_id TEXT,
                    observed_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(source, vehicle_id)
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
        vehicle_details: tuple[tuple[str, str | None, str | None, str | None, str | None, datetime], ...] = (),
        benchmark_forecasts: tuple[tuple[str, str, str, datetime, datetime, datetime | None, datetime | None, bool], ...] = (),
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
            for vehicle_id, bus_name, direction, reported_status, next_stop, source_time in vehicle_details:
                if source_time.tzinfo is None:
                    raise ValueError("Source vehicle status time must be timezone-aware")
                # Store the source status at EVERY accepted GPS fix. Previously
                # only the latest status was retained, forcing historical ETA
                # backtests to guess directions using future stops (leakage).
                self.conn.execute(
                    """INSERT OR IGNORE INTO vehicle_context_history
                    (source,vehicle_id,observed_at,bus_name,direction,reported_status,next_stop_id)
                    VALUES(?,?,?,?,?,?,?)""",
                    (source,vehicle_id,source_time.astimezone(timezone.utc).isoformat(),
                     bus_name,direction,reported_status,next_stop),
                )
                self.conn.execute(
                    """INSERT INTO vehicle_context
                    (source,vehicle_id,bus_name,direction,reported_status,next_stop_id,observed_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(source,vehicle_id) DO UPDATE SET
                    bus_name=excluded.bus_name,
                    direction=excluded.direction,
                    reported_status=excluded.reported_status,
                    next_stop_id=excluded.next_stop_id,
                    observed_at=excluded.observed_at,
                    updated_at=excluded.updated_at
                    WHERE excluded.observed_at >= vehicle_context.observed_at""",
                    (source,vehicle_id,bus_name,direction,reported_status,next_stop,
                     source_time.astimezone(timezone.utc).isoformat(),
                     polled_at.astimezone(timezone.utc).isoformat()),
                )
            # Replace the ephemeral upcoming arrival schedule on each accepted
            # source poll (including an empty response). The research sample
            # below is still deduplicated separately, preserving benchmark data.
            if source == "student_public":
                self.conn.execute(
                    "DELETE FROM source_arrival_schedule WHERE source = ?", (source,)
                )
                per_stop = {}
                for stop,vehicle_id,direction,predicted_at,arrival,early,late,enabled in benchmark_forecasts[:96]:
                    if stop not in ("125","135","marshak","145") or direction not in ("NB","SB"):
                        continue
                    if any(t.tzinfo is None for t in (predicted_at,arrival)):
                        continue
                    ordinal=per_stop.get(stop,0)
                    if ordinal >= 12:
                        continue
                    per_stop[stop] = ordinal+1
                    self.conn.execute(
                        """INSERT INTO source_arrival_schedule
                        (source,stop_id,ordinal,vehicle_id,direction,generated_at,
                         arrival_at,earliest_at,latest_at,source_enabled,ingested_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (source,stop,ordinal,vehicle_id,direction,
                         predicted_at.astimezone(timezone.utc).isoformat(),
                         arrival.astimezone(timezone.utc).isoformat(),
                         early.astimezone(timezone.utc).isoformat() if early else None,
                         late.astimezone(timezone.utc).isoformat() if late else None,
                         int(enabled),polled_at.astimezone(timezone.utc).isoformat()),
                    )
            # Cap storage to one source forecast per bus/stop/direction per
            # 30-second interval. This is for offline evidence, not the API.
            if source == "student_public":
                for stop,vehicle_id,direction,predicted_at,arrival,early,late,enabled in benchmark_forecasts[:96]:
                    if stop not in ("125","135","marshak","145") or direction not in ("NB","SB"):
                        continue
                    if any(t.tzinfo is None for t in (predicted_at,arrival)):
                        continue
                    bucket=int(predicted_at.timestamp())//30
                    self.conn.execute(
                        """INSERT OR IGNORE INTO forecast_comparisons
                        (source,stop_id,vehicle_id,direction,forecast_generated_at,
                        forecast_bucket,arrival_at,earliest_at,latest_at,source_enabled,ingested_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (source,stop,vehicle_id,direction,
                         predicted_at.astimezone(timezone.utc).isoformat(),
                         bucket,arrival.astimezone(timezone.utc).isoformat(),
                         early.astimezone(timezone.utc).isoformat() if early else None,
                         late.astimezone(timezone.utc).isoformat() if late else None,
                         int(enabled),polled_at.astimezone(timezone.utc).isoformat()),
                    )
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

    def latest_vehicle_context(self, source: str) -> dict[str, dict]:
        rows = self.conn.execute(
            "SELECT vehicle_id,bus_name,direction,reported_status,next_stop_id,observed_at "
            "FROM vehicle_context WHERE source=?", (source,)
        ).fetchall()
        return {
            vid: {
                "busName": name,
                "reportedDirection": direction,
                "reportedStatus": reported_status,
                "reportedNextStopId": next_stop,
                "reportedObservedAt": observed,
            }
            for vid, name, direction, reported_status, next_stop, observed in rows
        }

    def recent_observations(
        self, source: str, vehicle_id: str, limit: int = 6
    ) -> list[Observation]:
        """Recent raw fixes for display-only stabilization; never mutate GPS."""
        if not 1 <= limit <= 12:
            raise ValueError("Invalid recent GPS limit")
        rows = self.conn.execute(
            """SELECT source,vehicle_id,latitude,longitude,observed_at,received_at,
                      heading_degrees,speed_mph
               FROM observations
               WHERE source=? AND vehicle_id=?
               ORDER BY observed_at DESC,id DESC LIMIT ?""",
            (source,vehicle_id,limit),
        ).fetchall()
        return [
            Observation(
                source=r[0],vehicle_id=r[1],latitude=r[2],longitude=r[3],
                observed_at=datetime.fromisoformat(r[4]),
                received_at=datetime.fromisoformat(r[5]),
                heading_degrees=r[6],speed_mph=r[7],
            )
            for r in rows
        ]

    def current_source_arrivals(
        self, now: datetime, source: str = "student_public", max_age_seconds: float = 45,
    ) -> list[dict]:
        """Fresh, ephemeral third-party forecasts, not our approved ETAs.

        Never serve stale schedules, fabricated future cycles or old forecast
        rows from the benchmark table. Caller further filters by fresh GPS IDs.
        """
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        rows = self.conn.execute(
            """SELECT stop_id,vehicle_id,direction,generated_at,arrival_at,
                      earliest_at,latest_at,source_enabled,ingested_at
               FROM source_arrival_schedule WHERE source=?
               ORDER BY stop_id,arrival_at,ordinal LIMIT 96""",(source,)
        ).fetchall()
        result = []
        for stop,vid,direction,generated,arrival,early,late,enabled,ingested in rows:
            try:
                issued=datetime.fromisoformat(generated)
                received=datetime.fromisoformat(ingested)
                arrives=datetime.fromisoformat(arrival)
                if any(t.tzinfo is None for t in (issued,received,arrives)):
                    continue
                age=max((now-issued).total_seconds(),(now-received).total_seconds())
                lead=(arrives-now).total_seconds()
                if age < -10 or age > max_age_seconds or not -30 <= lead <= 7200:
                    continue
                result.append({
                    "stopId":stop,"vehicleId":vid,"direction":direction,
                    "generatedAt":issued.astimezone(timezone.utc).isoformat().replace("+00:00","Z"),
                    "arrivalAt":arrives.astimezone(timezone.utc).isoformat().replace("+00:00","Z"),
                    "earliestAt":early,"latestAt":late,
                    "providerPredictionsEnabled":bool(enabled),
                })
            except (ValueError,TypeError,OverflowError):
                continue
        return result

    def count_forecast_comparisons(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM forecast_comparisons").fetchone()[0]

    def count_observations(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

    def close(self) -> None:
        self.conn.close()
