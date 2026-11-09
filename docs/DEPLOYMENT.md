# CCNY Shuttle beta — VPS deployment and port isolation

## Verified deployment (November 9, 2026)

- Public URL: **https://shuttle.syndrid.com/**
- DNS: proxied through Cloudflare to the existing Oracle ARM64 VPS
- Nginx: dedicated `server_name shuttle.syndrid.com` (shares only public ports 80/443)
- Static web root: `/var/www/shuttle.syndrid.com`
- TLS: dedicated Let's Encrypt certificate for `shuttle.syndrid.com`; automatic renewal should be checked periodically
- Local-only GPS status service: **`127.0.0.1:8766`**, systemd `ccny-shuttle-status.service`, dedicated unprivileged `ccnyshuttle` user
- Local GPS prototype database: `/var/lib/ccny-shuttle/gps.sqlite3`
- OmniRoute: **`127.0.0.1:23128`**, remains separate under `api.syndrid.com`

No real GPS feed is running. The read-only status API should return `sourceState: no_data` and `transportState: never_connected` until a permitted CCNY shuttle GPS source is configured and verified.

## Request paths

- `/`: web interface, no separate frontend backend port
- `/alpha-v3.css`: current versioned stylesheet
- `/app.js`: browser app
- `/api/v1/vehicles`: Nginx proxy to `http://127.0.0.1:8766/v1/vehicles`
- `/api/health`: Nginx proxy to `http://127.0.0.1:8766/health`
- All other `/api/` routes are 404.

**Never route shuttle traffic to port 23128.** Public HTTPS port 443 is shared by Nginx virtual hosts and is not a collision between the app backends.

## Health checks

```sh
sudo nginx -t
systemctl is-active ccny-shuttle-status.service
ss -ltnp | grep -E ':(8766|23128) '
curl -fsS https://shuttle.syndrid.com/api/health
curl -fsS https://shuttle.syndrid.com/api/v1/vehicles
curl -fsS -o /dev/null -w '%{http_code}\n' https://shuttle.syndrid.com/
curl -fsS -o /dev/null -w '%{http_code}\n' https://api.syndrid.com/
```

The correct GPS API must report the *source observation time*, not just the latest successful HTTP poll. The absence of source data is not a functioning GPS feed.

## Change management

1. Run `node --test apps/web/tests/*.test.mjs` and `python3 -m unittest discover -s services/gps-collector/tests -v`.
2. Review the PR; never add credentials to GitHub.
3. Backup site files before modifying `/var/www/shuttle.syndrid.com`.
4. Deploy only the shuttle web root or dedicated shuttle service. Do not restart unrelated sites.
5. Nginx static-only updates need no reload; routing changes need `sudo nginx -t` **before** `sudo systemctl reload nginx`.
6. Cloudflare caches static assets; publish future CSS/JS changes under **new versioned URLs** (and update HTML and service-worker cache version), or users can keep an old cached stylesheet for hours.
7. Validate HTTPS, GPS `no_data` state, JS/CSS loading, and that OmniRoute still responds independently.
8. If a deployment fails, restore only the previous shuttle web files or dedicated Nginx shuttle config. Do not change the existing OmniRoute vhost.

## Notes

- `/api/v1/vehicles` intentionally uses GET, not HEAD, because the prototype Python HTTP handler exposes only GET.
- The backend is **read-only and loopback-only**. Collection is not configured, and no data is scraped from student websites.
- Stop pins are *approximate geographic references* and not confirmed boarding coordinates.
- Live ETA and station optimization remain disabled until data access and prediction accuracy are established.
