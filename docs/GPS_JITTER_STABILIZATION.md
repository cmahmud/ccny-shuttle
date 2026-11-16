# GPS precision improvements — stationary-jitter filter (beta)

## Empirical bottleneck (November 10, 2026)

The student-public GPS relay operates through the student website's normal public browser feed. A live 12-hour quality report measured **3,029** GPS observations from **2** known shuttle IDs: median source-to-collector delay **9.4 s**, 90th percentile **14.0 s**, and median original GPS fix interval **12.0 s**. A long maximum observed gap means upstream availability, rather than browser polling, is the largest source of reliability risk.

Increasing browser polling cannot create observations that the Samsara device or upstream service has not produced. Samsara documents a 5-second polling interval for its *official authenticated* stats feed, but that credential is not available to this project.

## Implemented: display-only stabilization when stopped

- Keep the original source latitude, longitude, and observed timestamp unchanged in `observations` and the public API.
- Add `ccny_gps.location_filter.stationary_display_position` to generate an *optional* `displayPosition` for the map only.
- Filter requires a **fresh source fix no older than 30 seconds**, a source-reported `standing` / `standing_at_stop` / `stopped` status tied to the latest accepted fix, and at least **3 distinct source timestamps within 45 seconds**, from the **same vehicle and source**, whose pairwise maximum distance is **15 meters**.
- Use the median coordinate of up to four close observations only for the visual marker. If the fixes disperse, the bus moves, status is unavailable, or GPS is delayed/stale, fall back immediately to the **unaltered original source position**.
- The front end independently rejects a derived display point more than **15 meters** from the source GPS, an invalid coordinate, stale GPS, or mismatched activity label. Historical pins always use raw source coordinates. The popup explicitly labels a stabilized stationary marker.
- The filter may reduce **visual jitter** around a stop; it is *not evidence of increased absolute hardware GPS accuracy*. It neither predicts motion nor invents locations.

## Deployment

- Status server reads recent positions from the existing SQLite DB and computes a derived field without writing extra coordinates.
- Reactivity and collector cadence remain unchanged; the GPS status API stays on `127.0.0.1:8766`.
- Public compact web uses `compact-v10.js` (poll interval reduced from 15 seconds to 5 seconds), `compact-core-v9.js` and service-worker cache v10. The five-second polling targets **our own localhost-backed API**, not the student's source or Samsara, and pauses when the tab is hidden. This reduces avoidable client display lag; it does not change upstream GPS sampling frequency.
- OmniRoute stays separate on `127.0.0.1:23128`.

## Tests and future work

- 64 GPS unit/integration tests and 41 frontend tests passed, including 6 synthetic edge cases for the location filter.
- Production desktop and phone browser smoke passed; 320/375/390/430px phone widths passed their synthetic GPS navigation regression.
- Next steps for **real geographic accuracy**: field-verify the road route and boarding points; map-match continuous traces to a campus shuttle route using a locally controlled algorithm; quantify raw versus map-matched geofence crossing error against independent observed bus arrivals; calibrate location uncertainty rather than claiming a precise accuracy radius.
- For **truly independent and higher-frequency GPS**, CCNY must approve a physically separate bus-mounted GPS/mobile device feed with appropriate access, consent, and hardware mounting. The student browser relay remains derived from the same Samsara upstream.
