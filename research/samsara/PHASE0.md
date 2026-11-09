# Phase 0 — Samsara public-viewer GPS source verification

**Status:** Not yet verified. This is a research plan, not evidence of a working GPS feed.

## Sources under evaluation
- CCNY public viewer: https://cloud.samsara.com/o/4010168/fleet/viewer/FJMjrX1YlqCqlGxIKkXY
- Official Samsara Vehicle Stats API (preferred if restricted credentials are provisioned).
- Student-built tracker: https://ccnyshuttlebus.com/ — competitive baseline only, **not** a production dependency.

## Investigation protocol

1. Use Playwright/browser devtools locally, restricted to the publicly shared official viewer. Do not authenticate as another user or bypass technical controls.
2. Confirm page and map readiness. Observe the browser network requests, including fetch/XHR and WebSocket/SSE if applicable; avoid preserving auth cookies or sensitive response bodies.
3. Determine whether responses contain **shuttle-only** GPS data and which fields are actually present: stable vehicle ID, latitude/longitude, observation timestamp, heading, speed, accuracy, status.
4. Track **distinct GPS source timestamps** (not merely request completion) over at least multiple refresh cycles; identify network and GPS update cadence separately.
5. Check for duplicate, late, stale, off-route, and missing observations. Record visible service-hour and no-bus behavior.
6. Evaluate whether a programmatic source is publicly accessible **and permitted for automated collection**, including relevant published terms and rate limits. Record any unverified permission assumptions as blockers.
7. If the public viewer cannot support a legitimate collector, document the official Samsara API read-only credential requirement. Build an adapter with clearly labeled synthetic fixtures; do not bypass access controls.

## Evidence table (fill after actual test)

| Question | Result | Evidence and date |
|---|---|---|
| Public viewer loads | Unverified in local browser | Pending |
| Data transport (XHR/WebSocket/SSE) | Unknown | Pending |
| Source coordinates visible | Unknown | Pending |
| Source timestamp available | Unknown | Pending |
| Stable shuttle IDs | Unknown | Pending |
| GPS observation cadence | Unknown | Pending |
| Independent permitted retrieval | Unknown | Pending |
| Terms / documented authorization | Unknown | Pending |
| Official API fallback | Read-only credential required | Verify scope with administrator |

## Exit criteria

A minimal local collector captures at least one real, **fresh**, source-timestamped CCNY shuttle observation through an authorized and repeatable interface, with a recorded source, safe sanitized fixture (if redistribution is permitted), and clear freshness diagnostics.

If the source is unavailable, Phase 0 still completes as a **documented blocker** rather than a false success. The production collector remains disabled until access is resolved.
