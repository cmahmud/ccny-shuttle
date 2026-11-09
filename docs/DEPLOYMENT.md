# Production alpha deployment — 2026-11-09

URL: https://shuttle.syndrid.com

This is an independent, public *alpha*. It is **not** a working live shuttle ETA service until verified GPS observations and prediction model calibration are available.

## Verified on the Oracle ARM64 VPS

- Public website responds HTTPS 200 and has a valid Let's Encrypt certificate covering shuttle.syndrid.com (current expiry: 2027-02-07).
- Cloudflare-proxied DNS resolves and serves the intended origin vhost.
- Nginx has a dedicated shuttle.syndrid.com host, isolated from the other Syndrid virtual hosts.
- Static HTML/CSS/JS/PWA assets are served from /var/www/shuttle.syndrid.com.
- Read-only GPS status service runs via systemd unit ccny-shuttle-status.service as the unprivileged ccnyshuttle user.
- GPS status backend binds to 127.0.0.1:8766 only; Nginx proxies /api/v1/vehicles and /api/health. No public access to the backend port.
- State storage is isolated at /var/lib/ccny-shuttle/gps.sqlite3.
- Python backend files reside at /opt/ccny-shuttle/services/gps-collector.
- As of deployment, status was sourceState=no_data and transportState=never_connected. No private credentials or simulated bus markers are present in production.
- Other app hostnames api.syndrid.com and proxy.syndrid.com were tested and continued to respond.

## Source files

- apps/web/: mobile-first frontend, versioned alpha-v2.css, offline-safe PWA, and web smoke tests
- services/gps-collector/: Samsara authenticated adapter and read-only status API
- infra/nginx-shuttle.conf: Nginx vhost template (requires an existing valid certificate before enabling TLS)
- infra/ccny-shuttle-status.service: restricted systemd unit
- services/eta-engine/: synthetic-only outage-prediction model, **not deployed to public status API**

The website code was verified in both desktop and mobile headless Chromium. The map loaded OSM tiles, GPS unavailable state appeared, no mobile horizontal overflow occurred, destination-specific walking links changed correctly, and cached UI reopened offline.

## Maintenance

Only operate on the shuttle-specific paths and unit. Do not change other services.

To inspect:

    systemctl status ccny-shuttle-status.service
    journalctl -u ccny-shuttle-status.service --no-pager -n 40
    sudo nginx -t
    curl -fsS https://shuttle.syndrid.com/api/health
    curl -fsS https://shuttle.syndrid.com/api/v1/vehicles

Before applying source changes:

1. Compare the deploy branch and working snapshot; do not blindly deploy from main while the stacked PRs are unmerged.
2. Run all unit/smoke tests.
3. Back up the existing shuttle vhost and the currently deployed static files.
4. Update only the dedicated shuttle static directory, backend package, and systemd unit when necessary.
5. Test Nginx configuration before reload, confirm TLS origin, and validate both the public site and both API endpoints.
6. Check other Syndrid hostnames for regressions.

## TLS renewal

The certificate was issued using HTTP-01 webroot /var/www/letsencrypt, with the challenge location configured in the dedicated shuttle Nginx vhost. Certbot reported a scheduled automatic renewal task.

A renewal **dry-run was attempted but did not complete** (a concurrent Certbot process prevented this instance); do not report successful renewal simulation yet. Verify renewal status before the certificate expires.

## Outstanding source and accuracy dependencies

- Official Samsara Vehicle Stats GPS Feed requires an authorized read-only token and an explicit list of CCNY shuttle vehicle IDs.
- The public viewer is accessible, and passive browser investigation showed browser-managed GraphQL requests, but **no independently permitted, stable shuttle GPS feed was established**.
- Do not scrape private API responses, bypass authentication, or rely on the student-made tracker backend.
- Historical arrival labels, route geometry, stop boarding areas, and ETA interval calibration are still outstanding.
- No actual bus ETAs, station-exit recommendations, or offline vehicle projections should be published as reliable without verification.

The status API intentionally displays an unavailable state instead of making up locations or arrival times.
