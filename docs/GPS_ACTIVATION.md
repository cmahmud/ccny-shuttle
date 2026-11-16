# Live GPS activation checklist — NOT ACTIVE

**State (2026-11-09):** The read-only GPS status endpoint on `127.0.0.1:8766` is online, but returns `no_data / never_connected`. The official Samsara collector and stop-event history logger are **not enabled**. No live vehicle or ETA observation has yet been validated.

## Source decision

1. **Primary: Official Samsara Vehicle Stats Feed.** Use a restricted `Read Vehicle Statistics` token, scoped to CCNY shuttle vehicles via a dedicated Samsara tag or explicit vehicle IDs. See https://developers.samsara.com/docs/vehicle-stats-feed. Query `types=gps` at a minimum 5-second interval, persist `endCursor` and both the source observation timestamp and received timestamp. Expired cursors require a deliberate backfill plan via the authorized history API, not a silent reset.
2. **Supplemental: CCNY public fleet viewer** at https://cloud.samsara.com/o/4010168/fleet/viewer/FJMjrX1YlqCqlGxIKkXY. Chromium on GitHub Actions can load the shared viewer (HTTP 200). Diagnostic recordings found GraphQL, a live-sharing token exchange and WebSocket invalidations, but **no verified shuttle GPS observations**. An HTML page loading does not establish a supported geolocation feed. Do not extract unrelated fleet data, bypass access controls, or assume the share link is durable.
3. **Comparison only: student tracker** at https://ccnyshuttlebus.com. Its browser-facing data endpoints returned HTTP 403 from our VPS. Do not bypass restrictions, copy its predicted ETAs as ours, or treat it as an independent failover source (it uses the same Samsara upstream).

## Before live collection can start

- An authorized Samsara administrator provides a **shuttle-only** token with `Read Vehicle Statistics` and the exact CCNY shuttle vehicle IDs. The general permission to build a student application does not by itself provision Samsara API access.
- Verify the actual source timestamps and a permitted shuttle GPS fix during service hours. Test live sampling cadence and 15-minute outages; observe stale GPS alerts.
- Physically confirm shuttle boarding-point coordinates and route direction before setting any `verified: true` geofence. The website's display pins are approximate landmarks and do not qualify.
- Confirm retention/privacy rules with CCNY and run the collector with a restricted, unprivileged user. Do not expose token values, credentials, private fleet members, or unnecessary driver/vehicle metadata.

## Prepared but NOT installed / NOT enabled

- `infra/systemd/ccny-shuttle-collector.service`: dedicated GPS polling process that writes to `/var/lib/ccny-shuttle/gps.sqlite3` used by the existing local status API.
- `infra/systemd/ccny-shuttle-history.service`: separate 10-second incremental event logger, read-only access to GPS observations, writes derived history in `/var/lib/ccny-shuttle/eta-history.sqlite3`. It refuses missing or unverified geofences.
- `infra/systemd/collector.env.example`: **placeholder**, never a live secret.

When authorized access becomes available, an administrator should create `/etc/ccny-shuttle/collector.env` (owner `root:ccnyshuttle`, mode 0640), outside the public web root, containing only the two necessary environment variables. A verified-stop config should also live outside GitHub under `/etc/ccny-shuttle/verified-stops.json`, with the same permissions.

**Do not enable services until configs have been reviewed.** After deployment, run a one-time collector poll with the allowed IDs, check that `observed_at` matches actual source time and that GPS is fresh, and independently verify at least one shuttle stop visit. Only then consider enabling the sustained polling unit and history logger. The public `/api/v1/vehicles` currently does not expose ETA predictions.

## Port isolation

- `shuttle.syndrid.com` frontend: Nginx static files, public 443 hostname routing.
- Shuttle status API: `127.0.0.1:8766` (already running, read-only).
- OmniRoute `api.syndrid.com`: `127.0.0.1:23128` (**never changed**).
- Collector and history logger: **no new listening ports**.

## Validation

```sh
PYTHONPATH=services/eta-engine python3 -m unittest discover -s services/eta-engine/tests -v
python3 -m unittest discover -s services/gps-collector/tests -v
sudo nginx -t
curl -sS https://shuttle.syndrid.com/api/v1/vehicles
systemctl is-active ccny-shuttle-status.service
ss -ltn | grep -E ':(8766|23128)\\b'
```

A `healthy` HTTP status without recent GPS is **not** sufficient evidence of a working shuttle tracker. No synthetic or stale locations may be labeled live.
