# Historical Shuttle Stop Logger & ETA Baseline

**Research/development module, NOT a live GPS/ETA service.** This engine uses synthetic fixtures until shuttle-only source access, verified stop geofences, route directions, and actual arrival labels have been established.

## Modules

- `ccny_eta.core.StopDetector`: consumes source-timestamped GPS fixes and logs conservative **inferred** stop arrivals and departures using verified geofences, two GPS fixes, low-speed/dwell evidence, and a 20m hysteresis zone. Large GPS gaps drop incomplete stop visits instead of inventing events.
- `ccny_eta.storage.HistoryStore`: persist stop events and completed travel legs idempotently in a local SQLite development database, using timezone-aware UTC timestamps and WAL. No production data is collected.
- `ccny_eta.core.build_travel_samples`: turns departures and subsequent arrivals of **the same vehicle** into travel-time samples only on explicitly approved route edges.
- `ccny_eta.core.EtaBaseline`: predicts the 10th–90th percentile **historical leg travel time**, not a live bus arrival. It requires at least 5 completed legs; time-of-day subgrouping requires 8 matching examples. History lookback: 90 days. Uses only historical trips completed before the prediction time to prevent data leakage.
- `EtaBaseline.predict_from_departure`: can estimate remaining leg duration when an *observed departure* is supplied; gradually widens its interval as GPS ages and expires completely after 5 minutes without confirmation. Do not expose as a live ETA until validated on real data.
- `benchmark_errors`: pairs our and student-tracker ETA snapshots on exact trip ID **and prediction timestamp**, evaluated against independently verified arrivals only. Neither the student website nor its private API is scraped by this module.

## Development-only commands

```sh
PYTHONPATH=services/eta-engine python3 -m unittest discover -s services/eta-engine/tests -v
PYTHONPATH=services/eta-engine python3 -m ccny_eta --synthetic-demo
```

## Integrating live data (later)

1. Verify the official GPS data source, the shuttle vehicle-ID allowlist, and *physical* boarding-point geometry. Approximate map markers from the website are **not** verified geofences and MUST NOT be plugged into this detector.
2. Normalize each authorized GPS observation to `GPSFix`, using its original source timestamp, not the time a server fetched it.
3. Feed verified per-vehicle ordered fixes into `StopDetector.observe`, store resulting events, and use `build_travel_samples` only with observed valid route edges.
4. Collect independently confirmed stop arrivals/departures to evaluate GPS-based inferred events (GPS sampling and stop proximity do not prove passengers boarded).
5. Compare time-split ETA accuracy vs historical baselines and permitted student ETA benchmark snapshots. Never claim superiority without paired evidence.
6. Move persistence to PostgreSQL for production and implement robust restart/replay of in-progress detector state.

**Data source roles:**

- Samsara (official): preferred primary GPS telemetry if permitted and authorized; credentials currently unavailable.
- Student tracker: optional **benchmark only** if approved/accessible; public endpoint currently returns HTTP 403 from our VPS. It is not independent upstream GPS redundancy.
- Our own event history: the model's continuously improving dataset once real GPS access exists.

Stop-event timestamps are **inferred approximate** times within the GPS sampling cadence; do not mislabel them as independently verified ground truth. No model should predict a bus stopped at Marshak will depart at a fixed time without a separate validated dwell-time model.

## Authorized GPS history replay (disabled until stop coordinates are verified)

The module `ccny_eta.replay` can process the existing GPS collector's saved `observations` table **without changing that table**. It takes a separate manually confirmed geofence configuration and a shuttle-vehicle allowlist. No production geofence file or actual CCNY boarding coordinates is bundled, so this cannot run against real CCNY stops until their locations are confirmed.

Example JSON **schema only; placeholder names and no coordinates are supplied**:

```json
{
  "allowed_vehicle_ids": ["ACTUAL_AUTHORIZED_CCNY_SHUTTLE_ID"],
  "stops": [],
  "allowed_legs": []
}
```

The `stops` array must be filled with `{id, latitude, longitude, radius_m, verified: true}` records validated in the field. Each `allowed_legs` record identifies `{from, to, route}` for a real directed edge. Empty or unverified stops are rejected.

```sh
# Dry run: no writes to the GPS source or history database.
PYTHONPATH=services/eta-engine python3 -m ccny_eta.replay \
  --gps-db ./data/ccny-gps-dev.sqlite3 \
  --verified-config ./private/verified-stops.json --dry-run

# Persist deduplicated derived events/legs in a DIFFERENT database.
PYTHONPATH=services/eta-engine python3 -m ccny_eta.replay \
  --gps-db ./data/ccny-gps-dev.sqlite3 \
  --verified-config ./private/verified-stops.json \
  --history-db ./data/ccny-eta-dev.sqlite3
```

Observations and events are replayed in source-event timestamp order, not request order. Re-running the replay does not duplicate event history. GPS gaps do **not** create imaginary departures; a leg can still be recorded if both the actual source-timestamped departure and next arrival were observed. This is a backfill prototype, not a background daemon.

Do not publish inferred geofence detections as independently verified "actual" arrivals. For comparative accuracy we need field-verified arrival times, with student-site predictions collected only under its permitted access rules.

## Continuous incremental GPS-to-stop history (development ready)

`ccny_eta.stream` reads **only newly inserted** observations in the already-existing authorized Samsara GPS collector database. Unlike a full replay, it preserves the stop-detector state and the next-route-leg candidate in a separate, durable, checkpointed history database. Every batch atomically commits: derived stop arrivals/departures, completed travel legs, the source-row checkpoint, and detector state.

It fails closed if a stop geofence/route/vehicle configuration changes, the GPS source has been reset, a row is malformed, or another worker advances the history checkpoint. GPS observation data is opened **read-only**. Neither script contacts Samsara or scrapes the student tracker.

This worker **must not** be started with approximate map marker coordinates. Fill `private/verified-stops.json` with physically confirmed boarding positions and route edges, plus the approved shuttle vehicle IDs (same allowlist as the official GPS collector). Store that private file outside the public web root and GitHub. Example **shape only**:

```json
{
  "allowed_vehicle_ids": ["REPLACE_WITH_AUTHORIZED_CCNY_SHUTTLE_ID"],
  "stops": [
    {
      "id": "125",
      "latitude": 0,
      "longitude": 0,
      "radius_m": 35,
      "verified": true
    }
  ],
  "allowed_legs": [
    {"from": "125", "to": "marshak", "route": "south"}
  ]
}
```

The coordinates above are **not real**, and the example cannot be used for real tracking. It deliberately lacks a complete route. Never mark a stop `verified` until the location is physically confirmed, and use a different history database if you change the stop layout.

```sh
# One-time incremental processing, no external network access.
PYTHONPATH=services/eta-engine python3 -m ccny_eta.stream \
  --gps-db /path/to/authorized/gps.sqlite3 \
  --history-db /path/to/eta-history.sqlite3 \
  --verified-config /private/verified-stops.json --once

# Continuously process newly stored GPS rows; not enabled in production.
PYTHONPATH=services/eta-engine python3 -m ccny_eta.stream \
  --gps-db /path/to/authorized/gps.sqlite3 \
  --history-db /path/to/eta-history.sqlite3 \
  --verified-config /private/verified-stops.json --loop
```

The ingestor's `live_gps: false` CLI marker means it performs historical ingestion only; it never establishes Samsara connectivity. Stop arrivals remain **inferred** from source GPS, never independently observed passenger boarding events. Live ETA predictions will require enough accurately verified stop history and validation.

Run the new regression suite:

```sh
PYTHONPATH=services/eta-engine python3 -m unittest discover -s services/eta-engine/tests -v
```

## Public relay GPS source support (2026-11-09)

The historical-event engine now accepts an explicit `--source student_public` flag for previously collected third-party browser-relay GPS. Official `samsara` observations remain supported separately. This merely enables **source-aware processing**; it does not mean stop arrivals have been verified or that ETA predictions are ready.

```sh
# Requires a PRIVATE, field-verified geofence configuration and an explicit
# allowlist of the shuttle IDs exactly as exposed by the selected source.
PYTHONPATH=services/eta-engine python3 -m ccny_eta.replay \
  --gps-db /var/lib/ccny-shuttle/gps.sqlite3 \
  --source student_public \
  --verified-config /etc/ccny-shuttle/verified-stops.json --dry-run

# When validated, backfill into a dedicated third-party source DB:
PYTHONPATH=services/eta-engine python3 -m ccny_eta.stream \
  --gps-db /var/lib/ccny-shuttle/gps.sqlite3 \
  --source student_public \
  --history-db /var/lib/ccny-shuttle/student-eta-history.sqlite3 \
  --verified-config /etc/ccny-shuttle/verified-stops.json --once
```

**Source provenance guard:** the incremental ingestor refuses to process one GPS source into a database already checkpointed for another. The source observation DB is always read-only, the geofences must be explicitly confirmed, and inferred geofence stop events are **not** independently verified actual arrivals. The old `ccny-shuttle-history.service` remains disabled because no valid `/etc/ccny-shuttle/verified-stops.json` file has been provisioned.
