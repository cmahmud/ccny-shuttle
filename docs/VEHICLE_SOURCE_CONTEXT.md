# Student-public bus identity, direction and status (beta)

The ordinary public browser relay at `ccnyshuttlebus.com` provides an authenticated-free page-rendered structured `/tracker-data/feed` payload. Some `live.vehicles` entries include short, human-readable bus numbers (`name`), direction (`NB` / `SB`), status (`standing`, `moving`, etc.), and an immediate next-stop ID.

This update **does not attempt to infer bus numbers from arbitrary long Samsara IDs**. It stores only source-asserted numeric names (1–3 ASCII digits) and known enums. The fields are written transactionally with source-timestamped accepted GPS observations to a separate `vehicle_context` table. Old/out-of-order or impossible-jump GPS readings do not overwrite newer context. The public API supplies `busName`, `reportedDirection`, `reportedStatus`, and `reportedNextStopId`, and serves these only if the saved context source timestamp matches the vehicle's latest accepted observation.

The website shows source-reported direction/status/next stop only for a **fresh (<=30 seconds old)** accepted GPS observation and never treats them as independent verification of a physical pickup-stop arrival. It shows the bus's human-readable number when available and safely falls back to a short GPS identifier otherwise. Historical "not currently reporting" buses may show a previously recorded number but no current activity status.

For example, the public data reported that the vehicle ending in `677146` is "Bus 88"; while moving or standing it may report northbound/southbound and a next stop. The bus name/next-stop label is not a calibrated ETA.

## Experimental student arrival predictions

The source publishes an additional `estimates.stops[].arrivals[]` object with `arrivalAt`, `confidence`, `basis`, `sampleCount`, `uncertaintySeconds`, and optional earliest/latest bounds. The source marks the estimates `experimental: true`, and during inspection returned `predictionsEnabled: false` even while showing arrival entries. Some initial predictions had confidence near 0.21. Therefore **do not present them as our own validated ETA calculations**.

Next development steps: independently verify stop geometry/directions, collect observed stop crossings, benchmark student estimates against observed events, and display our own calibrated arrival ranges (with source labels and outage handling). The student-derived ETA fields remain research comparison data; the current public site intentionally does not offer GPS-based arrival predictions.

## Deployment and tests

- Collector: `services/gps-collector/ccny_gps/student_public.py`, `student_public_browser.py`, `storage.py`, `status.py`
- Web: `apps/web/compact-core-v8.js`, `compact-v8.js`, `compact-v7.css`, versioned service-worker cache and updated unit tests
- 58 synthetic GPS collector tests and 39 web tests passed.
- The live feed successfully surfaced a current `Bus 88 · Southbound · At stop · Next: Marshak` report on both phone and desktop, without guessed arrival times.
- The website and collector remained isolated from OmniRoute on separate loopback ports.
