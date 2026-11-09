# CCNY Shuttle — Public GPS Relay (beta)

**Status on November 9, 2026:** An ordinary Chromium browser on the VPS can access the public student tracker at https://ccnyshuttlebus.com and observe its documented UI's existing `/tracker-data/feed` JSON responses. We do **not** call restricted endpoints from outside the normal page session: direct server requests to those endpoints returned HTTP 403 and are not used.

The public page itself requests the feed approximately every 7 seconds. A single dedicated browser session consumes those native responses. No login, credentials, rotating proxies, captcha bypass, reverse engineering of private tokens, or Context.dev subscription is used.

## The honest source hierarchy

1. `samsara` — preferred official GPS API when CCNY can provide shuttle-scoped authenticated access; **currently unavailable**.
2. `student_public` — a third-party relay of Samsara-derived GPS observations, **currently running in beta**. The original GPS coordinate and time may be accurate, but we have not independently verified it against CCNY's hardware.
3. No data — if all sources stop producing recent valid observations, the website returns an explicitly delayed/offline status. It never generates fake GPS positions.

The website identifies the source as **GPS via student**, and shows last-seen positions for at most three minutes with a separate delayed style. It never labels third-party reports independently verified and it does **not** copy the other website's experimental ETAs.

## Collection, validation, and retention

- `services/gps-collector/ccny_gps/student_public.py` validates the feed schema; original Unix millisecond timestamps; 90-second maximum feed-response age; upstream polling freshness; no more than 25 vehicles; CCNY-area geographic bounds; and <=10-minute age per GPS fix before saving.
- `services/gps-collector/ccny_gps/student_public_browser.py` observes responses from exactly `ccnyshuttlebus.com/tracker-data/feed`. No private credentials, cookies or response bodies are logged. Logs contain only aggregate counts and errors.
- Snapshots are stored in the **existing** `/var/lib/ccny-shuttle/gps.sqlite3` database, with `source=student_public`. Existing official Samsara records are preserved and preferred when available.
- Duplicates are ignored using the source+vehicle+observation timestamp+coordinates constraint. The original upstream GPS observation timestamp is retained separately from our receive timestamp.
- The normal browser session operates only during a conservative weekday window near CCNY shuttle service hours. The webpage itself may indicate closure on holidays.
- The visible map has no calibrated arrival times; history is being collected for future validation, not presented as independently verified stop arrivals.

## VPS deployment

- `ccny-shuttle-public-relay.service` — enabled, runs as `ccnyshuttle` (no new listening ports), uses a pinned Playwright+Chromium runtime at `/opt/ccny-shuttle`. CPU/memory limits and systemd restart protection apply.
- `ccny-shuttle-status.service` — existing read-only loopback API on `127.0.0.1:8766`.
- `api.syndrid.com` OmniRoute remains on `127.0.0.1:23128`, unaffected.
- `shuttle.syndrid.com` is served via dedicated HTTPS hostname routing and source-aware frontend modules.

The browser service may stop if the student website changes, returns HTTP 403, or stops publishing usable data. In that case it **fails closed**, rather than bypassing restrictions. Because both sites rely on the same Samsara GPS upstream, this is not an independent GPS hardware source.

## Context.dev evaluation

Context.dev (https://www.context.dev) provides JS-rendered page crawling and scraping, but it requires its own API key and charges request credits. At a five-second interval, a 30-day tracker would request around 518,400 pages; the current 1,000-credit free allocation would not be sufficient. Context.dev can help with *occasional* site audits, but a persistent ordinary-browser session is more economical for the public feed we verified.

## Checks

```sh
sudo systemctl status ccny-shuttle-public-relay.service
sudo journalctl -u ccny-shuttle-public-relay.service -n 35 --no-pager
curl -fsS https://shuttle.syndrid.com/api/v1/vehicles
python3 -m unittest discover -s services/gps-collector/tests -q
node --test apps/web/tests/*.test.mjs
```

Expected JSON when fresh: `source=student_public`, `sourceState=live`, `transportState=healthy`, `independentlyVerified=false`, `locationKind=third_party_observed`.

## Next steps toward better ETAs

- Collect multiple weeks of source-timestamped raw observations, but assess whether sparse stationary reports and gaps make individual geofence events reliable.
- Validate actual boarding-point geofences and route directions in person. UI map pins are **approximate** and must not be used as verified geofences.
- Evaluate event timing versus independently observed actual arrivals, and calibrate trip and Marshak dwell-time models.
- Compare our predictions on matching trips against a permitted student-site benchmark only. Source-site predictions are **not** ground truth.
- Add raw position retention management after defining CCNY's data-handling expectations and ensuring the stop-event derivative pipeline is replay-safe.
