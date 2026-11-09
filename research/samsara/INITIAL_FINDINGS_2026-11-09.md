# Phase 0 — Initial evidence, November 9, 2026

**Status:** Official API adapter implemented with synthetic fixtures; **no live CCNY shuttle feed verified or running.**

## Observations

1. An ordinary HTTP GET from the user's Oracle ARM64 VPS returned **HTTP 200** with the public Samsara viewer's HTML, but this does not show which background requests provide real coordinates.
2. The existing student tracker's index and public front-end bundle were retrievable. Its browser-facing code references `/tracker-data/bootstrap`, `/tracker-data/feed`, `/tracker-data/runtime` and `/tracker-data/alerts`. Direct requests to the first three from the VPS returned **HTTP 403**. This site is not a production data dependency.
3. A sandboxed Chromium/Playwright navigation to `cloud.samsara.com` reported `net::ERR_BLOCKED_BY_ADMINISTRATOR` from the sandbox environment. This establishes an **investigation-environment restriction**, not that Samsara is unavailable to CCNY students or that Samsara blocks all browser access. No network requests or live GPS coordinates were inspected.
4. Official Samsara documentation confirms that the authenticated `GET /fleet/vehicles/stats/feed?types=gps` returns a cursor-based feed, can filter by `vehicleIds`, and recommends at least five seconds between polls once `hasNextPage=false`. The endpoint requires the **Read Vehicle Statistics** permission.

## Implementation

The prototype in `services/gps-collector/` implements a source-timestamped normalized observation model, a restricted vehicle-ID allowlist, pagination, an idempotent transactionally checkpointed SQLite store, and exponential-backoff polling. **13 unit tests passed** against synthetic GPS observations on the ARM64 VPS using Python 3.14. No credentials were available and no Samsara API calls were made.

## Blockers and next validation

- Confirm a permitted programmatic GPS source. Ideally obtain a restricted, read-only Samsara API token **and the exact shuttle vehicle IDs** from an authorized Samsara administrator; CCNY Facilities' general permission to build the tracker does not automatically provide these.
- Alternatively, verify from an authorized browser/integration setting that a public, automatable viewer data interface exists and that its use is permitted and reliable. No bypass of authentication, anti-bot measures or rate limits.
- On a weekday during shuttle service, confirm at least one **source-timestamped** real shuttle observation, actual distinct GPS cadence, vehicle-ID stability, and stale-data behavior.
- Then replace SQLite prototype storage with a production PostgreSQL/PostGIS pipeline before offering a public live service.

## Sources

- https://developers.samsara.com/docs/vehicle-stats-feed
- https://developers.samsara.com/reference/getvehiclestatsfeed
- https://developers.samsara.com/docs/pagination
- https://cloud.samsara.com/o/4010168/fleet/viewer/FJMjrX1YlqCqlGxIKkXY
- https://ccnyshuttlebus.com/

Do not describe the collector as live until the GPS source is validated.
