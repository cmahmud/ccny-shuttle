# CCNY shuttle v21 — transparent experimental source projections

## Why the student website still shows arrival times while ours went empty

Firecrawl performed one bounded crawl of `https://ccnyshuttlebus.com/` (one publicly indexed page). The student's own beta notice describes its predicted arrivals and departures as experimental. A normal public browser also observed `/tracker-data/feed` with `live.sourceState=live` and new forecast timestamps while bus 88's last GPS fix was 139–151 seconds old. `live.predictionsEnabled=false` was also reported, despite experimental forecasts being displayed. These are source-generated *predictions*, NOT live GPS arrivals or confirmed bus departures. Source-vs-shadow historical stop-passage MAE does not prove forecasts are accurate during prolonged stops.

## v21 arrival display

- Fresh-GPS student forecasts retain the existing experimental source attribution, countdown, NY clock, provided earliest/latest window and earliest valid NEXT highlighting.
- **New sourceUnverifiedProjections API property**, independent of `sourceArrivalEstimates`. Source transport must be healthy; the bus's actual GPS fix must be **30–300 seconds old**; the upstream source forecast itself must be **<=45 seconds old**. The forecast must be **90 seconds–45 minutes in the future**, referenced to that exact source bus ID. The short list contains **one upcoming arrival per stale bus per stop**, at most two rows per stop, not repeated cycles.
- If both stale and fresh vehicles appear in the source, preserve both rows with per-row styling. Stale-vehicle source projections use amber instead of the NEXT highlight, show `GPS Xm old · not live`, display an approximate countdown prefixed with `~`, and are labeled `SOURCE PROJECTION`. Do not imply the bus has left the stop or will arrive on time. Report `Mixed GPS quality` in a mixed state.
- Never cache/persist projections across browser reloads; disable immediately when the API no longer supplies them, the source is unavailable, the app goes offline, projection age exceeds 45 seconds, the GPS fix is older than five minutes, or the user leaves operational hours. Do not synthesize new timestamps from historical travel times, extrapolate positions, or create fictional buses.
- `sourceArrivalEstimates` is unchanged for genuinely fresh GPS vehicles. Past 120-second grace on a **previously fresh** source forecast is also unchanged, and remains explicitly STALE.
- Existing independent ETA shadow worker remains **NOT_APPROVED** for public ETA display. Source windows remain unverified third-party heuristics, not probability-calibrated intervals.

## Frontend cleanup

- Completely remove the old `Going to campus?` walking-routes card from the DOM, along with the destination dropdown, from-137th / selected-stop walking links, and its JavaScript handlers. The lightweight pickup-area link attached to each selected stop remains useful.
- The selected-stop card fills the available right column on desktop. Mobile stacks the stop card and map without reserving the removed panel's height.

## Testing / deployment safeguards

- Backend synthetic tests verify source age thresholds, one result per bus per stop, unsupported/unknown buses rejected, stale GPS >300 seconds rejected, future cycles rejected, fresh GPS separated, and official source isolation.
- Synthetic browser tests verify standalone amber-only projections and **mixed fresh/stale** reports, no NEXT for stale projections, source timestamp expiry, mobile breakpoints and removal of walking routes card.
- Use backups of the versioned entrypoint / service worker and status.py. Restart only the CCNY status service after deployment; the collector, GPS history, ETA shadow research and unrelated OmniRoute domain remain unchanged.

## Missing evidence

The public Samsara share page has been reviewed visually, but **no independently authorized numeric GPS API** has been established. Do not claim real-time independent fixes or better accuracy until confirmed. No paid Firecrawl GPS polling or bypass of source restrictions.
