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
