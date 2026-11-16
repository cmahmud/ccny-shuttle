# Mobile bus visibility and navigation — November 10, 2026

The phone tracker now makes active GPS reports directly discoverable. The formerly cramped mobile map header is a single row, with compact, accessible controls:

- **Buses (N)** zooms to currently reported positions (or recently observed positions clearly labeled delayed). This action is disabled when no reportable buses are available.
- **Last (N)** toggles historical positions; these are **not current bus locations**.
- **All** returns to the stop-area overview.
- Each current/recent bus list entry is a keyboard-accessible button that focuses the corresponding marker and opens a descriptive popup. It does not claim the bus is arriving at the selected stop.

The active bus marker is a teal, bus-shaped icon, visually distinct from orange campus pins, purple stop pins, and gray historical pins. The source remains attributed as *GPS via student*, and GPS freshness labels remain prominent.

Additional phone layout changes: ETA panel/list spacing, map-header single-line layout, simplified control labels, no horizontal scroll. The selected-stop panel stays above the map on small screens; the map buttons and bus list provide quick navigation without requiring users to search a zoomed-out map.

## Verification

- Static suite: 38 web tests.
- Browser smoke on deployed `https://shuttle.syndrid.com/`: desktop and 390px mobile passed.
- A separate browser regression test (`apps/web/tests/browser_mobile_visibility.py`) stubs **synthetic** GPS data in the browser only. It covers 320, 375, 390 and 430px phone widths and 1365px desktop, checking map-header geometry, clear separation of ETA and bus list, no horizontal overflow, visible marker after tapping Buses, and popup after tapping a bus row.
- No changes to the live GPS collector, its original timestamps, ETA computation, or OmniRoute. Source age and fleet activity disclaimers remain intact.

Source work is on a development PR; the public static frontend is deployed. Do not turn synthetic browser-test data into public API data.
