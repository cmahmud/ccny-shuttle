# CCNY Smart Shuttle — Web Beta

The first public beta is a responsive, static, installable web app deployed on `https://shuttle.syndrid.com` through a **dedicated Nginx virtual host**. It uses Leaflet and OpenStreetMap for an **approximate stop-area map**, not a survey-grade boarding position map.

## What works now

- Mobile-first page, destination selection, campus information and official shuttle station descriptions.
- Approximate map markers with clear labels that they **are not the precise boarding point**.
- Status from the separate GPS API at `GET /api/v1/vehicles`.
- Distinct transport/polling health and original GPS freshness indicators.
- Service-worker app shell for offline informational access; GPS API is **never cached**.
- Links to official CCNY shuttle information and the Samsara live viewer.

## Not available yet

- **Independent live CCNY GPS observations:** We don't have verified authorized read access yet.
- **Stop ETAs and train-exit recommendations:** Intentionally disabled until both GPS and trip model validation.
- **GPS outage predictions:** Not yet implemented.

Never present synthetic locations, rough walking times, or unobserved bus positions as live. The source GPS timestamp and collection timestamp must remain distinct.

## Development

HTML/CSS/JavaScript are dependency-free and can be served directly; a Leaflet CDN stylesheet/script and OSM tile server are used for the map. Node.js is used for tests only.

```bash
node --test apps/web/tests/*.test.mjs
```

Run a static development server with:

```bash
python3 -m http.server 9000 --directory apps/web
```

This static server does not proxy `/api/v1/vehicles`; the UI must show the source as unavailable in that environment.

## Routing and isolation

Public HTTPS requests for `shuttle.syndrid.com` use the same **public** port 443 as other virtual hosts, but the dedicated shuttle backend listens only on `127.0.0.1:8766`. The existing `api.syndrid.com` OmniRoute backend listens on **`127.0.0.1:23128`**, untouched.

See `../../docs/DEPLOYMENT.md` for verification and rollback.

## Source references

- CCNY: https://www.ccny.cuny.edu/about/gettingthere
- Public viewer: https://cloud.samsara.com/o/4010168/fleet/viewer/FJMjrX1YlqCqlGxIKkXY
- Existing student-built service is for benchmarking only; not a backend dependency.


## Compact dashboard (November 9, 2026)

The previous landing-page hero and stacked informational sections were replaced with **one dashboard** at `/`. The deployed assets are `compact-v1.css`, `compact-v1.js`, and `compact-core.mjs`; each is referenced with its exact, versioned filename to avoid stale Cloudflare cached CSS/JS.

- Desktop: header, GPS state, five stop tabs, large map, selected-stop card, walking options in one compact screen.
- Phone: horizontally scrollable stop tabs, selected-stop card **before** the map, walking options below.
- Tab selection updates stop details, pickup-area links, selected map marker/focus, and destination walking links; keyboard arrow navigation is supported.
- 135th Street request stop and Marshak remain selectable but their exact coordinates are **not fabricated** on the map.
- Source-timestamped, confirmed, fresh shuttle GPS locations may appear when an authorized GPS collector becomes available. This is **not** an ETA engine: arrival displays remain unavailable until proper calibration.
- Offline app shell caches static UI only. `/api/` GPS responses are always network-only.

Testing: `node --test apps/web/tests/*.test.mjs` runs both state/ETA safety checks and compact UI contract checks.
