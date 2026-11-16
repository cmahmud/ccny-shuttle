# CCNY Shuttle v19 — explicit bus status and source arrival windows

## Provenance

The source is the publicly presented **student tracker** feed, not an independent GPS receiver and not an official CCNY API. A healthy browser relay does not mean a bus fix is recent. When the source has no fresh GPS, report `Student GPS Nm old` rather than claiming live bus tracking. GPS positions and status should not be extrapolated from an outdated feed.

## Current vs last status

- Display `Standing at stop` only for a **fresh**, source-reported `standing_at_stop` event associated with the latest observed GPS timestamp.
- Display `Inactive (reported)` only for a **fresh**, explicitly source-reported `inactive` status. `moving`, `standing`, and `stopped` remain distinct.
- After a GPS fix ages out, use `Last: at stop`, `Last: inactive`, etc. A stale report must **not** be presented as a current stop or parking state.
- Missing or unrecognized statuses display `Status unknown`, **not** `inactive`.
- Last-reported fleet history uses historical terms; no bus coordinates or directions are invented.
- The browser-readable public feed presently contains only buses 88 and 89. Other public-page bus labels (64, 68, 90) do not have source-provided fresh status or GPS records in this feed. **Do not** add them as confirmed inactive, even if a separate webpage lists them as inactive at a particular moment.

## Experimental arrival ranges

- Forecasts are still **third-party student source estimates**. They are not predictions from our independent shadow ETA model and do not represent officially validated arrival-time confidence intervals.
- The student source already supplies optional `earliestAt` and `latestAt` bounds, in addition to its `arrivalAt` point prediction. Preserve these exact source timestamps and validate `earliestAt <= arrivalAt <= latestAt`, timezone-awareness, and an at-most-two-hour range before passing them to the public API.
- The client shows a `Source window A–B min` alongside the point countdown and New York clock time only when BOTH source bounds are present, ordered, and within a reasonable lookahead. Missing bounds produce no range. The client does not widen or shrink the bounds with invented multipliers or convert them into a claimed coverage probability.
- Source forecast data still requires fresh matching GPS (or at most 120 seconds of historical presentation after that GPS fails, with a prominent stale warning). On stale views both the point and range are frozen at the last source update. Do not show either as live.
- The independent shadow model remains NOT_APPROVED because paired validation favors the student tracker, long-horizon samples are sparse, and the route geometry and geofences still require validation.

## Deployment safety

This release alters the read-only status API serialization and the compact frontend only. It does not touch browser-collector logic, sources, GPS timestamps, forecasting research, reverse geocoding, or OmniRoute. Back up existing `status.py`, `index.html` and `service-worker.js` before deploying. Keep the source range experimental and unverified, not a service guarantee.
