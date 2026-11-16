# Compact v16 · Quiet one-screen CCNY shuttle tracker

This update is a **presentation-only cleanup** prompted by the November 16 desktop screenshot. The active GPS source, ETA research, stop geometry, bus marker coordinates, permission boundary, and backend services are unchanged.

## Layout rules

- Keep the top-header GPS pill as the one visible GPS status indicator. The detailed `live-message` remains an accessible ARIA live region for screen readers, but its duplicate visual line and redundant second official tracker link are removed.
- Use short single-line stop-selection pills rather than five full-width, two-line cards. Preserve each stop's secondary descriptor as text available to screen readers and preserve keyboard arrow navigation.
- Hide the empty `Next shuttle —` placeholder. Keep the `ETA unavailable` badge and the inactive `eta-hero` DOM placeholder for a future, separately validated ETA release. Never silently show uncalibrated countdowns.
- Label the fleet list `Buses on route`, not another full sentence about GPS/ETA. Keep bus number, direction, reported movement, next stop, GPS timestamp, last-known locations, and tap-to-focus map behavior.
- Hide disabled Buses/Last map shortcuts until actionable. Keep reset, route lines, provenance labels, attribution, historical pins and popup actions.
- Reduce visual noise in OpenStreetMap tiles using a CSS filter only on the tile pane (not shuttle markers, route geometry or stop icons). Preserve all coordinates and attribution.
- Retain the campus destination selector and both walking links. Remove repeated walking caveat and redundant section badge; the page does not claim a walking route is faster or that an ETA is known.
- On narrow screens, show the selected stop before the map; avoid horizontal page overflow and collisions between the route legend and OpenStreetMap attribution.

## Testing and deployment

- `node --test apps/web/tests/*.test.mjs` tests markup/assets, URL paths and status invariants.
- `browser_compact_cleanup.py` verifies page hierarchy, hidden placeholder, accessible status, functional stop tabs, buttons, no page scroll overflow, source details and legends at multiple widths.
- Existing `browser_mobile_visibility.py`, `browser_route_overlay.py`, `browser_last_known.py`, `browser_smoke.py`, and `browser_service_notice.py` continue testing live, historical, synthetic and date-specific behaviors.
- The `browser_service_notice.py` test uses a fixed November 11, 2026 browser clock; otherwise its Veterans Day-only assertion would fail on subsequent days.
- Site release uses new, immutable `compact-v16.js`, `compact-v12.css` files and `ccny-smart-shuttle-compact-v16` service worker app-shell cache. Keep a pre-update copy of `index.html` and `service-worker.js` for rollback.

No new APIs, paid map services, external calls, live data collection changes or changes to OmniRoute are introduced.
