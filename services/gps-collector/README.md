# Authorized GPS collector — prototype

**Status:** Tested with synthetic fixtures only. No live CCNY location feed has been verified or enabled.

This standard-library Python prototype uses the documented Samsara **Vehicle Stats GPS Feed**, with an explicit shuttle-only vehicle ID allowlist. It refuses to call Samsara without **both** a read-only API token and vehicle IDs. It never scrapes the student tracker or public viewer.

Docs: https://developers.samsara.com/docs/vehicle-stats-feed

## Test locally (no credentials; no network)

```sh
python3 -m unittest discover -s services/gps-collector/tests -v
```

## Authorized test (only after access has been approved and provisioned)

```sh
export SAMSARA_API_TOKEN='your restricted read-only token'
export CCNY_SHUTTLE_VEHICLE_IDS='shuttle-vehicle-id-1,shuttle-vehicle-id-2'
PYTHONPATH=services/gps-collector python3 -m ccny_gps --once
```

For continued collection, use `--loop`. Minimum interval is five seconds when the feed has no additional pages; failed polls retry with backoff. Keep the token in an approved secret store; **never commit it**.

This prototype stores observations and cursors transactionally in a local SQLite file. It preserves source GPS timestamps separately from reception timestamps, deduplicates observations, and treats old source timestamps as stale. **It does not yet implement PostgreSQL, public APIs, production monitoring, route matching, or real ETA calculations.**

The API's initial response may include the last known position of an inactive vehicle, so the presence of a position does not establish a live bus.

No production service has been deployed.

## Local GPS status API (no Samsara token required)

```sh
# Inspect only the observations actually saved in local development SQLite.
PYTHONPATH=services/gps-collector python3 -m ccny_gps --status

# Local-only read API; not a public deployment.
PYTHONPATH=services/gps-collector python3 -m ccny_gps --serve --port 8766
curl http://127.0.0.1:8766/health
curl http://127.0.0.1:8766/v1/vehicles
```

The API binds to `127.0.0.1` only. Freshness uses the original GPS event timestamp, **not** the last successful HTTP poll time. The `lastSuccessfulPoll` value tracks transport health separately. Endpoints do not extrapolate any coordinates and will display `no_data` / `stale` rather than fake live updates. Before exposing an external API, add authentication, rate limiting, access controls, production storage and explicit operational permission.

Samsara feed cursors expire after 30 days. After such an outage, historical backfill (using authorized stats/history access) should be used rather than silently losing the gap by resetting cursors.

The status API additionally reports `transportState` (`never_connected`, `healthy`, `delayed`, or `offline`) separately from `sourceState` (`no_data`, `live`, `delayed`, `stale`). Transport thresholds are provisional and are **not** evidence of actual GPS freshness.
