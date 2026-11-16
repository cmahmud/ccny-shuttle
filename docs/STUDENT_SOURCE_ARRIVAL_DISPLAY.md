# Experimental source arrival display (not our calibrated ETA engine)

The public tracker may show future arrival times **from the public student tracker itself**. These estimates are upstream, not predictions from our model and not independently validated CCNY Facilities dispatch data. The upstream live feed returns `predictionsEnabled: false` even when its public page displays these estimated times. The UI therefore labels them prominently **Experimental**, carries an **Unverified** provenance caption, and never claims that our own ETA model is approved.

## Data flow and limits

- The existing public browser relay already parses the visible student feed's `estimates.stops[].arrivals[]` into `benchmark_forecasts`. It does not scrape additional endpoints or access restricted information.
- The historical `forecast_comparisons` table continues sampling at most one forecast per vehicle/stop/direction every 30 seconds for matched benchmarking. Do **not** relax its deduplication, which would bias accuracy evaluations.
- A separate `source_arrival_schedule` table stores only the latest accepted snapshot's upcoming trips; each successful poll replaces its contents. This preserves repeated future cycles the upstream site displays without corrupting historical benchmarks or accumulating an unbounded schedule archive.
- Only allow source `student_public`, exact stop IDs 125, 135, marshak, 145, source-provided NB/SB direction, source-provided verified bus IDs and timestamps, relative forecast lead within 2 hours, forecast age at most 45 seconds and **currently fresh** vehicle GPS from the same source. No forecast is shown when source polling is delayed, absent, there is no fresh bus, or the user's device is offline.
- NAC is **not** present in this student forecast feed; do not assign Marshak ETAs to NAC or invent an arrival time.
- At Marshak the only recorded timing field is arrivalAt; no departureAt is provided through this collection path, so do not render fabricated departure times.
- The local API's `sourceArrivalEstimates` field is marked `experimental: true`, `calibrated: false`; `providerPredictionsEnabled` truthfully reflects the upstream flag even when false. The UI independently rejects records without this source and label.

## Presentation

Show three upcoming trips by default, an optional Show more control up to eight validated source rows, and a clock-time toggle (New York time) alongside minute countdowns. Both formats use the exact same `arrivalAt` timestamp. Screen-reader and UI labels identify them as experimental. The regular observed bus positions, stop selection, route overlays, historical markers, accessibility attributes, and service-calendar banner are unchanged.

**No traffic forecasting, headway extrapolation, synthetic return trips, confidence claims or improvement over the third-party student tracker are introduced.** The independent ETA engine remains in private shadow evaluation pending quality gates.
