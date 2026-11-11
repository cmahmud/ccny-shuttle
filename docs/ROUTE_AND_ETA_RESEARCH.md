# CCNY shuttle route overlay + ETA research (November 11, 2026)

## Source and map behavior

The public student tracker `https://ccnyshuttlebus.com/` provides normal browser-readable `/tracker-data/bootstrap` route geometry. We captured **two directional line shapes** (12 points northbound, 15 southbound) and the public stop reference coordinates for 125th, northbound-on-request 135th, Marshak and 145th. A versioned, attributed `apps/web/route-data-v1.js` stores the public geometries as [latitude, longitude] pairs.

Our Leaflet map now shows:

- A **solid dark-purple northbound** polyline, a **lighter dashed southbound** polyline, each with an outline for contrast, plus a compact mobile legend.
- Source-attributed, approximate 135th and Marshak stop markers. These are **not** surveyed boarding points; use signs and CCNY's official service information to confirm exact pickup locations.
- **Teal directional arrow** only when a bus has a fresh (<30s), source-reported `moving` status and a valid original heading. Heading 0 is valid north, while null/invalid headings are not interpreted as direction.
- A conventional stationary bus icon when status is stopped/standing/unknown, or direction is unavailable. Stale historical locations remain gray and visually detached from live service. No geographic coordinates are inferred from direction.
- Tapping a route displays a notice that it came from the student site. The route is a schematic centerline, **not independently surveyed**. Paths may not perfectly follow every permitted lane or detour.
- Stops, current moving buses and historical bus reports are independently clickable; repeated five-second GPS status polling does not close an existing popup.

**Verified:** Full map and moving arrow pass Chromium on 320px, 390px and 430px phones and 1365px desktop, with no page overflow or script errors. The public production site passed the same synthetic tests. No API credentials or new source scraping were introduced for the map.

## GPS-pass event / ETA research

`services/gps-collector/ccny_gps/eta_research.py` is intentionally **offline/shadow mode**. It reads existing raw SQLite GPS observations and creates GPS-inferred geofence passages at source stop coordinates. Entry/exit hysteresis and a repeat-time gate avoid counting continuous stationary jitter as multiple arrivals; implausibly long pairs and unsupported route directions are excluded. These are **not independently verified boarding events**.

Snapshot of the November 11 analysis:

- **4,590** accepted original GPS observations from two observed shuttles over the November 9–11 UTC dates.
- **303** inferred geofence passages and **149** plausibly ordered stop-to-stop travel time samples.
- **121** strictly chronological walk-forward segment median evaluations, about **1.46 min MAE**, using **only earlier** samples for each prediction. This is a segment-duration baseline, **not a validated live ETA model**.
- A simple historical **time-of-day traffic proxy** had **1.48 min MAE**, slightly worse than the regular median baseline. It has not been enabled as an adjustment.
- Sample counts and error margins differ by segment. Current training data span just a short period and only two buses, and some supposed stop passages may be through traffic rather than actual passenger stops.

This does **not** demonstrate superiority to the student tracker's arrival prediction engine. We must compare forecasts on equal vehicle/stop/time horizons and evaluate against independently audited stop passages before promising greater accuracy.

## Source forecast benchmarking now being collected

The existing **same normal browser feed** contains optional `estimates.stops[].arrivals` entries with predicted stop-arrival timestamps and optional earliest/latest bounds. Some responses contain `predictionsEnabled:false` even when experimental values exist. We now validate and store only the source-provided bus ID, direction, stop ID, timestamped forecast and optional bounds, with its enabled flag, into a separate SQLite `forecast_comparisons` table in **30-second buckets**. Records are never forwarded to the public GPS API or claimed to be our ETAs.

The offline `student_forecast_reference()` benchmark can select one forecast per observed bus/stop passage at about **10 minutes before arrival** (±2 minutes) to avoid counting near-duplicate forecasts as independent trips. The comparison outcome stays null until real reference forecast records and later GPS passages become available. As of initial deployment, the table contains 0 rows because the current public feed supplied no eligible forecast arrivals.

## Traffic-data plan

Traffic can improve shuttle estimates but has costs and model risks:

1. **Free first signal:** actual bus speeds inferred from source GPS and route progress, plus segment dwell and historical stop-to-stop distributions. A congestion adjustment is allowed only after a walk-forward backtest shows lower error and acceptable uncertainty.
2. **Optional licensed external signal:** Google Routes API `TRAFFIC_AWARE` or `TRAFFIC_AWARE_OPTIMAL`, or Mapbox `driving-traffic`. These need a service-side API credential and may be billed. Query bounded **fixed CCNY route segments**, not each student page refresh; respect licensing/retention terms. Cars may be routed differently from a mandatory shuttle route; never substitute an unconstrained car ETA directly for a shuttle ETA, and always add dwell/stop buffers calibrated from real bus behavior.
3. Waze's own city traffic feed is a partner resource, **not a freely available unauthenticated public API**. It should not be scraped through web maps. NYC DOT traffic-speed feeds have primary coverage on major arterials and highways, possibly not the exact campus road legs.
4. **Outage mode:** do not represent extrapolated coordinates as current GPS. Future ETA ranges could be displayed as **predicted with increasing uncertainty** for brief gaps only after calibration, and disabled for prolonged GPS loss.
5. **Release gate:** a minimum independently evaluated stop-passage sample count, walk-forward holdout across separate class days, proper per-stop calibration, and a head-to-head error comparison against source ETA forecasts at consistent prediction horizons. Until then the public interface correctly says `ETA unavailable`.

## Service isolation and security

Route geometry, source-reported moving-marker heading, and visual styling are frontend-only changes. New forecast-logging code runs only inside the existing normal browser collector, consumes the existing feed response (no additional website requests), and writes a separate local table. It does not store individual student geolocation, drivers' identities, user sessions, source credentials, or browser cookies.

Shuttle status stays isolated on loopback `127.0.0.1:8766`; OmniRoute remains on loopback `127.0.0.1:23128`. The source GPS observation table is not rewritten, and existing ETA warnings remain unchanged.
