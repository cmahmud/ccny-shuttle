# CCNY Smart Shuttle Web Alpha

A lightweight, responsive, installable PWA prototype with **no fabricated ETA or GPS data**.

Features:
- Static mobile-first UI with stops, campus destination selector, official service information.
- Approximate shuttle stop areas shown on an OSM map using Leaflet (CDN and OSM tiles; map gracefully degrades if blocked).
- Polls the existing local GPS status backend via `/api/v1/vehicles` every 15 seconds.
- Shows fresh/stale/unavailable GPS distinctly. Verified GPS markers only; never extrapolates.
- Smart station recommendations and ETAs explicitly labeled unavailable until a validated source/model exists.
- PWA caches static files but **never** GPS API responses, to prevent offline stale observations from masquerading as live.
- Links to CCNY's official shuttle page and the public Samsara viewer.

Deployment target: `shuttle.syndrid.com`, served by Nginx with a dedicated hostname. The status API lives on localhost `127.0.0.1:8766`, not the public interface. No API credentials are present or exposed in this frontend.

This alpha intentionally requires no frontend build tooling or runtime Node process. As the project evolves we can migrate to a TypeScript/Vite or Next.js frontend without changing the collector.

## Research sources

- https://www.ccny.cuny.edu/about/gettingthere
- https://www.ccny.cuny.edu/about/directions
- https://ssa.ccny.cuny.edu/locations/north-academic-center/
- https://www.openstreetmap.org/copyright

Station/building coordinates represent landmarks **near** pickup areas, not surveyed boarding points; verify signed boarding positions before public routing recommendations.

## Testing

Open `index.html` using a local HTTP server or deploy to the isolated Nginx host. Test desktop/mobile layouts, denied tile/CDN loading, network outage, `/api/v1/vehicles` timeout, and PWA offline reload. A smoke check script is in `tests/smoke.py`.
