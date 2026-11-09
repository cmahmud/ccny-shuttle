
## November 9 JavaScript module MIME fix

**Symptom:** Map remained at “Loading stop map…” and GPS remained at “Checking GPS” even though the GPS API responded.

**Verified root cause:** Nginx served the imported `compact-core.mjs` file with `Content-Type: application/octet-stream` and `X-Content-Type-Options: nosniff`, so browsers rejected the ES module and none of the page initialization code ran. This was a *frontend module-loading failure*, not a Samsara/GPS outage.

**Change:** The site now uses `/compact-v2.js` importing `/compact-core-v2.js`. Both are served as `application/javascript` without changing any Nginx configuration. The service worker cache was bumped to `ccny-smart-shuttle-compact-v2` to replace old cached app assets. Both old files remain available temporarily for rollback.

**Regression verification:** Playwright in Chromium confirmed the map initializes, OSM map tiles load, 145th Street selection changes the stop panel, walking direction links work, and neither desktop (1365×880) nor phone (390×844) overflows horizontally. A browser smoke test is in `apps/web/tests/browser_smoke.py` and its GitHub Actions workflow.

**Current GPS data state:** No verified live GPS source has been connected; `/api/v1/vehicles` honestly reports `no_data / never_connected`. Don't display predicted arrival times until real observations are validated.
