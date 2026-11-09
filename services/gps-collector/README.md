# CCNY Shuttle GPS collectors

**Current deployment:** The public student tracker relay is running in beta and reading shuttle location reports via one ordinary browser session. Official Samsara API integration remains disabled until CCNY can provision a credential.

## Sources

### Public student tracker relay (working beta)

- Implemented in `ccny_gps/student_public.py` and `ccny_gps/student_public_browser.py`
- Reads only the normal webpage's existing `/tracker-data/feed` responses. No private API requests, credentials, token extraction, proxy rotation, CAPTCHA bypass or restrictive-endpoint retries
- Collects source-timestamped GPS reports with `source=student_public`, not `samsara`
- Normal public browser polls roughly every 7 seconds during school-day service hours
- Rejects malformed, geographically implausible, time-skewed and expired observations
- If the third-party website becomes unavailable, observations expire; no extrapolated positions are presented as live
- Separate `ccny-shuttle-public-relay.service`, running under the unprivileged `ccnyshuttle` account

The source is not independently verified against the official Samsara hardware. Do **not** use its inferred arrival times as ground truth.

### Official Samsara GPS feed (not connected)

`ccny_gps/samsara.py` implements the documented Samsara Vehicle Stats GPS feed and requires a shuttle-scoped read-only API token and the exact vehicle IDs. Neither is currently available. `python3 -m ccny_gps --probe` supports a single read-only API check after approved credentials are installed. No token is stored in the public website.

## API and data

GPS observations are stored in the existing local SQLite database with source provenance. The loopback-only read service on `127.0.0.1:8766` exposes `/v1/vehicles`; Nginx proxies `https://shuttle.syndrid.com/api/v1/vehicles`.

The status service prefers *fresh direct Samsara* data if available, otherwise fresh third-party observations; both preserve the original GPS timestamp independently of the HTTP receipt time. It distinguishes transport health from GPS freshness. The website marks third-party positions as reported and last-seen positions as delayed. There are no calibrated ETA predictions.

## Testing

```sh
python3 -m unittest discover -s services/gps-collector/tests -q
PYTHONPATH=services/eta-engine python3 -m unittest discover -s services/eta-engine/tests -q
node --test apps/web/tests/*.test.mjs
```

See `docs/PUBLIC_GPS_RELAY.md` for service operation, source usage and failure modes; `docs/LIVE_GPS_INTEGRATION.md` for upgrading to official direct Samsara access.
