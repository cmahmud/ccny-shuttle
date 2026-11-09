# CCNY Smart Shuttle

An independent, student-focused CCNY shuttle tracker designed to answer **which station should I exit at, can I catch the next shuttle, and when will I reach my building?**

> **Status:** Research and scaffolding. No verified independent live GPS feed yet. This is an independent project, not an official CCNY/Samsara service.

## Goals

1. Collect authenticated or otherwise expressly permitted **shuttle-only** GPS observations from a dependable source.
2. Show **confirmed** vehicle locations separately from **estimated** positions, including the source observation time.
3. Predict arrivals with honest uncertainty ranges, accounting for dwell times, direction, traffic, and stale GPS.
4. Compare **total door-to-campus-building journey time** via 125th Street, 145th Street, 137th Street–City College, other relevant stations, walking, and applicable MTA buses.
5. Remain useful during source and user-device connectivity interruptions without misrepresenting stale data as live.

## Data sources

- **Official public viewer:** https://cloud.samsara.com/o/4010168/fleet/viewer/FJMjrX1YlqCqlGxIKkXY
- **Existing student tracker (comparison only):** https://ccnyshuttlebus.com/
- **Preferred production integration:** Samsara Vehicle Stats GPS Feed, using a restricted, read-only credential if provisioned by the fleet administrator.
- **Alternative:** A stable public-viewer data interface **only if** its permitted automated use and reliability are verified.
- **Transit:** MTA GTFS-Realtime and relevant bus feeds, subject to API terms.

CCNY Facilities has permitted independent project development; this does **not** by itself grant API tokens, permission to bypass access controls, or rights to redistribute data. No hidden credentials, student tracker backend dependency, or source access bypasses are allowed.

## Initial plan

### Milestone 0 — Verify the GPS source (first)

- Inspect **only** network traffic from the publicly shared Samsara viewer using local browser developer tools or Playwright.
- Document request types, public accessibility, expected permissions, GPS fields, vehicle IDs, timestamp behavior, and refresh cadence.
- Determine whether there is a suitable integration; if not, build a mocked adapter and document the blocked dependency.
- Capture no unrelated fleet, driver, or personally identifying information.

**Exit criterion:** A repeatable, permitted way to obtain actual CCNY shuttle observations, or a clearly documented blocker and official API fallback.

### Milestone 1 — Data collection

- Server-side adapter interface with explicit source provenance.
- Retain GPS event timestamp and ingestion timestamp separately.
- Deduplicate and validate observations; persist history in PostgreSQL/PostGIS.
- Handle reboots, timeouts, retries/backoff, stale observations, and source outages.
- Publish collector health and bounded data freshness.

### Milestone 2 — Live tracker and ETA baseline

- MapLibre live vehicle/stop map with source timestamps and confidence labels.
- Route matching and direction/state detection, including Marshak dwell/departure behavior.
- Statistical ETA baselines and backtesting against observed stop arrival times.

### Milestone 3 — Route recommendations and resilience

- Integrate subway arrival estimates, walking routes, applicable buses, and building destinations.
- Compare complete trips and probability of catching a shuttle.
- Make outage estimates explicitly probabilistic; expire projections when unreliable.
- PWA cache for previously synced information; never imply offline data is live.

## Proposed stack

- **Frontend:** Next.js, TypeScript, Tailwind CSS, MapLibre GL JS, PWA
- **Backend:** FastAPI/Python
- **Database:** PostgreSQL + PostGIS
- **Hosting:** Docker Compose on a dedicated Oracle ARM64 VPS deployment
- **Development:** MacBook + T3 Code + Mistral Vibe; GitHub as source of truth

The production VPS and other existing services must not be changed until the collector passes local verification and deployment has been reviewed.

## Repository direction

```text
apps/web/                 # Mobile-first PWA
apps/api/                 # Public application API
services/gps-collector/   # Pluggable permitted GPS adapters
services/eta-engine/      # Prediction, calibration, replay tests
services/transit/         # MTA and walking itinerary data
data/routes/              # Verified route geometry (no fabricated geometry)
data/stops/               # Verified stop metadata
research/samsara/         # Sanitized findings: no credentials or session secrets
tests/                    # Unit, integration, and deterministic replay tests
infra/                    # Isolated compose/deployment configuration
docs/                     # Source evidence, architecture, operations
```

These paths are **planned**, not claims that the implementations exist.

## Accuracy & integrity

Primary evaluation includes median and P90 absolute ETA error, interval coverage, freshness, missed-shuttle recommendation rate, and journey recommendation correctness. Compare with other trackers only using equivalent observations.

- **Confirmed position** = a fresh, source-timestamped GPS observation.
- **Predicted position** = a model output shown with confidence, last-confirmed timestamp, and expiration.
- **Offline** = no new observations can be obtained; predictions are not real-time confirmations.

Do not deploy demo data as live shuttle telemetry.

## Next step

Run the Phase-0 investigation from a local development machine with browser tooling. Record sanitized conclusions in `research/samsara/`, then implement the appropriate collector adapter. See `AGENTS.md` for agent instructions when available.

## Public beta (November 9, 2026)

The independent mobile-first beta is reachable at **https://shuttle.syndrid.com**. A dedicated Nginx vhost serves the static web interface and proxies the read-only status endpoint to `127.0.0.1:8766`. The existing OmniRoute installation at `api.syndrid.com` uses **`127.0.0.1:23128`** and remains separate.

- `apps/web`: destination selector, stop-area map, official shuttle links, honest no-GPS states and installable app shell.
- `services/gps-collector`: credential-gated prototype with durable incremental storage, source-GPS freshness, transport-health separation and a local-only status API.
- `docs/DEPLOYMENT.md`: verified infrastructure, health checks, CSS cache-versioning and rollback.

**Important:** The site is live, but **the independent live GPS feed and shuttle ETA recommendations are not operational yet**. The app intentionally shows an unavailable status rather than synthetic buses or made-up ETAs. Next: confirm an authorized Samsara data connection, collect source-timestamped shuttle observations and validate arrivals before turning on the prediction engine.

Web tests: `node --test apps/web/tests/*.test.mjs`. Backend tests: `python3 -m unittest discover -s services/gps-collector/tests -v`.

## Historical stop logging and ETA baseline

The first historical ETA engine is in `services/eta-engine/` (development-only; not deployed to the public website). It provides:

- Two-observation geofence-based inferred stop arrivals/departures, requiring separately **field-verified** boarding-point coordinates and shuttle-only GPS.
- Idempotent SQLite persistence for stop events and completed directed travel legs.
- Read-only replay of GPS history already captured by the authorized collector. No verified CCNY stop geofence configuration is bundled, so real event collection is **not yet running**.
- Historical route-specific ETA time windows using recent samples and local New York commute-period context. Estimates become unavailable with inadequate history or expired GPS.
- A paired comparison function for independently verified actual arrivals versus our predictions and **permitted** student-site ETA snapshots. This does not retrieve the student's restricted endpoints.
- A clearly identified **synthetic demo** and offline tests with no GPS secrets or remote calls.

Run: `PYTHONPATH=services/eta-engine python3 -m unittest discover -s services/eta-engine/tests -v`. See `services/eta-engine/README.md` for configuration requirements and limitations.

**Integration policy:** Samsara/CCNY is the intended authoritative GPS source (subject to approved programmatic access); the student-made tracker is an optional ETA benchmark, not an independent GPS backup. Neither live source is currently ingesting into our service.
