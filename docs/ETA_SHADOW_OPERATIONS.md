# CCNY Shuttle — private ETA calibration engine

Implemented 2026-11-11. **The public site still does not publish GPS-derived ETAs.**

## Deployment status

- `ccny-shuttle-eta-shadow.service`: enabled, running, **20-second interval**. Reads local GPS data already collected; does **not** poll either public website, Samsara, Google, or Waze. Output: `/var/lib/ccny-shuttle/eta-shadow.sqlite3` (SQLite, enforced **0600 owner-only**, including one-off CLI initialization).
- `ccny-shuttle-eta-report.timer` and `ccny-shuttle-eta-report.service`: enabled, **30-minute interval**, writing an aggregate owner-only JSON report at `/var/lib/ccny-shuttle/eta-evaluation.json` with atomic replacement (0600). The `/var/lib/ccny-shuttle` directory is restricted to the `ccnyshuttle` service user/group, and the private worker/report files cannot be reached through `shuttle.syndrid.com`.
- `vehicle_context_history` in original GPS SQLite: appends each **source-timestamped bus direction, reported status, and next-stop context**. Previous collector retained only the last state, which would make historical live-decision backtests optimistic. The original GPS observation entries are unchanged.
- The existing `forecast_comparisons` table records eligible student tracker reference predictions only when provided in an ordinary browser feed, at native source cadence, up to one per 30-second bus/stop/direction interval. No upstream request increase.
- The original `ccny-shuttle-status.service`, public relay and `api.syndrid.com` OmniRoute were not repurposed. The new worker uses a **separate local SQLite database** and has no new network listeners or API endpoints.

## Forecast algorithm

1. Reject any non-live transport, GPS older than 30 seconds, unknown source direction, nonmoving status, or missing route match (outside 70m of the approximate source route).
2. Project fresh GPS onto the **appropriate NB or SB** public, approximate CCNY shuttle route polyline. The two lines have distinct lengths and stop orders. GPS source coordinates are never rewritten, moved onto the polyline, or presented as newly measured coordinates.
3. Identify the **next stop on that direction's route**, and reject if a source-reported next stop contradicts it.
4. Train on **at least 10 historical, completed, direction-compatible trips** on that exact stop segment, each completed **strictly before the source GPS fix**. The route-fraction model uses a historical median full-leg travel time multiplied by the remaining route-progress fraction, producing an absolute ETA from the original GPS event time.
5. Experimental secondary model uses change in recent source GPS route progress as a **speed/congestion proxy**, blended with the median only when recent GPS has sufficient forward movement and no off-route jump. It never automatically replaces the baseline.
6. Only the **next stop** gets a shadow ETA. We intentionally do not invent terminal layovers, missing southbound segment estimates, or travel beyond the nearest known next stop. All forecasts include source time, data age, training counts/days, rough historical travel-time bounds, model/version and `display_enabled=0`.

**No live ETA is shown by the public site until independent accuracy validation.** Historical range bounds are *not* calibrated prediction intervals; GPS outage mode still shows **historical positions**, not moving guesses.

## Initial historical replay — NOT a true online ETA evaluation

The Nov 9–11 GPS archive contained **4,590 raw observations** for two observed buses, **303 GPS-inferred stop passages**, and **149** plausible stop-to-stop passage segments.

- Strict walk-forward historical segment median: **121 segment-duration predictions**, **1.46 min MAE** (previous research).
- Route-progress median replay: **146 optimistically selected historical fix forecasts**, **1.348 min MAE**; P90 absolute error **2.498 min**; historical range coverage only **57.5%**.
- Recent-speed blending: **89 forecasts**, **1.448 min MAE**; on the same 89 samples the route-progress median had **1.444 min MAE**. **No improvement**, so this speed correction is shadow-only, not a selected public estimator.
- The per-horizon sample sizes for the progress model were **87** near 3 minutes, **55** near 5 minutes, and only **4** near 10 minutes. There is **no reliable 10-minute ETA calibration** yet.

**Critical leakage disclosure:** Past per-fix source direction/status were not preserved before this implementation. Historical replay must therefore select the route direction and target stop using a *future* observed passage. This is an **optimistic oracle-direction test**, and the numbers **must not be presented as actual online arrival prediction accuracy**. Training samples themselves strictly precede each evaluated GPS fix.

The geofenced passages were inferred from approximate third-party stop coordinates; they have not been field-audited against real pickup events. With a small number of days and two observed buses, the model is experimental.

## Paired comparison and release criteria

The offline `eta_compare.py` evaluator pairs a shadow model forecast with a student forecast for the **same bus, stop, direction, and approximately the same prediction timestamp (within 75 seconds)**. Each model is evaluated at the same **3-, 5-, or 10-minute** lead time, using one prediction per observed stop pass to avoid duplicating one trip into many samples. Ambiguous same-bus repeat passes within 30 minutes are excluded.

As of initial deployment, the **source reference forecast table had zero eligible entries** and the new shadow worker had zero live-bus forecasts due to stale vehicle GPS. Consequently there are **zero head-to-head samples**. No improvement over the student tracker has been demonstrated.

The automated scorecard records unmet gates including:

- ≥90 matched paired observations, with ≥20 at each 3/5/10-minute horizon.
- ≥7 days of GPS observation coverage and later proper separate service-day holdout.
- At least 10% lower paired mean absolute error before considering the more complex model.
- Manual validation of stop locations, direction annotations, geofence events, uncertainty coverage, device/GPS outage behavior and operator review.

Even if numeric gates become satisfied, the report **never auto-enables public ETAs**. A release requires manual review and an explicitly separate frontend/API change.

## VPS read-only inspection commands

```bash
systemctl status ccny-shuttle-eta-shadow.service
systemctl status ccny-shuttle-eta-report.timer
sudo -u ccnyshuttle env PYTHONPATH=/opt/ccny-shuttle/services/gps-collector \
  python3 -m ccny_gps.eta_shadow --status \
  --db /var/lib/ccny-shuttle/gps.sqlite3 \
  --shadow-db /var/lib/ccny-shuttle/eta-shadow.sqlite3

sudo -u ccnyshuttle env PYTHONPATH=/opt/ccny-shuttle/services/gps-collector \
  python3 -m ccny_gps.eta_compare \
  --db /var/lib/ccny-shuttle/gps.sqlite3 \
  --shadow-db /var/lib/ccny-shuttle/eta-shadow.sqlite3

sudo -u ccnyshuttle cat /var/lib/ccny-shuttle/eta-evaluation.json
```

## Traffic API note

Do not add Google Routes/Mapbox API billing or unapproved Waze crawling without an appropriate key, terms review and the owner's explicit selection. Inferred bus GPS speed was already evaluated as an empirical traffic proxy; that naive adjustment **did not improve** the initial paired historical replay, so its output remains research-only.

For future optional external traffic studies, request road-segment travel times along the **fixed shuttle path**, not the fastest car route or every student's page refresh. Include scheduled stops, queueing/dwell, boarding and turnaround separately. Compare traffic-aware and nontraffic models on the **same time-separated rides**, not on leakage-prone random GPS points.
