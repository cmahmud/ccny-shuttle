# Private ETA passage-matching and geofence audit — November 16, 2026

## Discovered error in evaluation selection

The prior paired source-vs-shadow evaluator rejected an inferred stop passage if the **same bus visited the same stop twice within 30 minutes**, regardless of direction. This safeguard intentionally prevented confusing two loops, but it mistakenly rejected many **Marshak** passages because the bus serves Marshak northbound and southbound within that period. It likewise suppressed **135th Street** observations. This was a flaw in the *evaluation dataset construction*, not proof that the GPS or ETA model was broken.

### Conservative fix

- Read only *source-attributed archived moving-direction records* in `vehicle_context_history` (`source='student_public'`, `status='moving'`, direction `NB` or `SB`).
- Assign an inferred geofence passage its **latest reported moving direction before the passage**, no more than **160 seconds old**. A record at the exact passage timestamp or later is never used: it may already describe the next leg.
- For a passage with no trustworthy recent direction, preserve the original conservative 30-minute ambiguity exclusion.
- Require the shadow forecast's direction to match the attributed passage direction. A nearby second passage of the same bus/stop/direction remains ambiguous and is excluded. Only a nearby passage with a *different* trustworthy pre-passage direction can be considered independent.
- The student forecast still has to match the bus, stop, direction and near-identical prediction timestamp of the shadow forecast. No fabricated source forecasts or forecast times are introduced.
- No changes to GPS ingestion, source polling, coordinates, live vehicle visibility, shadow forecast generation, public website, route geometry or third-party source access.

### Private historical effect

Before direction-aware matching, speed-blend evaluation had **189 matched forecast rows**, including **0 at Marshak**, **0 at 135th Street**, **4 at 10-minute lead**. After the conservative direction-aware attribution, the same archived source and model forecasts yielded **331 matched rows**, including **56 Marshak** and **83 at 135th Street**, **9 at 10-minute lead**. The data were not made more accurate; more existing events were correctly evaluable. Direction attribution was available for **587** of approximately 1,039 inferred passages.

Private matched speed-model mean absolute error on the expanded data: **1.731 minutes** versus **1.562 minutes** for the student tracker, so our uncorrected model **does not yet outperform** the student tracker overall. A walk-forward bias-calibrated candidate improves error on a *selected* 135-row subset but is **not released**: those samples are neither independent passenger boarding observations nor representative of the entire route.

## New release-readiness diagnostics

`matchedCoverage` now reports paired forecasts, unique GPS-proxy passage events, and mean absolute error by:

- named stop (`125`, `135`, `marshak`, `145`)
- nominal lead horizon (3, 5, 10 minutes)
- **America/New_York local service day**, not UTC date

Multiple forecasts around the same GPS passage count as multiple predictions, **not** multiple independent arrivals. Only three actual service days presently have a meaningful volume of matched forecasts. The private scorecard adds conservative gates for at least five matched service days (at least five comparisons each) and ten matched passage events at each of the main stops. These do not supplant the existing 10-minute, head-to-head accuracy, manual signoff and real-world boarding validation requirements.

`geofenceSensitivity` additionally tests inferred stop passage counts at **25m / 38m / 50m** entry radii. Initial historical results: **987 / 1,038 / 1,050** inferred passage events respectively. This is diagnostic sensitivity to radius, **not** validation against real-world stopping positions; production geofences were *not changed*. Field validation of the stop coordinates and entrances remains required.

## Status and next measurements

- Public ETA policy: **NOT_APPROVED** for independent shadow predictions.
- Independent Samsara GPS: **not authorized/connected**, do not claim otherwise.
- Need five or more measured service days, twenty or more paired 10-minute forecasts, and genuine field-confirmed arrival/departure evidence (especially at Marshak and 135th) before declaring real-world improvements.
- Candidate statistical gains must be checked against the student tracker on the *identical eligible event subset*, with repeat forecast horizons clustered by actual passage.
- Evaluation metrics are internal; no bus-level identifiers or GPS coordinates are included in the JSON report.
- The model and UI remain unchanged by this release. Only the existing private 30-minute report generator is updated, following successful CI.
