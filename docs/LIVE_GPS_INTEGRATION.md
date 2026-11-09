# Live GPS integration — access and activation

**Current state: source not connected.** The public site at https://shuttle.syndrid.com is operational, but the GPS endpoint returns `sourceState=no_data` and `transportState=never_connected`. No real CCNY shuttle coordinates have been recorded.

## What is connected and what is not

- The official CCNY Samsara viewer is a **public human-facing reference**. Its browser transport was investigated, but no stable, permitted, source-timestamped programmatic GPS feed was confirmed.
- The student tracker is a **comparison source only**, if its creator allows automated ETA retrieval. Its data endpoints returned HTTP 403 from the VPS. It shares Samsara's upstream and cannot act as an independent failover.
- The supported integration is Samsara's `GET https://api.samsara.com/fleet/vehicles/stats/feed?types=gps&vehicleIds=...`. The source adapter, cursor storage and historical-event worker are implemented and tested, but **no credentials are installed**.
- General permission to build the tracker does not automatically create a Samsara API account/token.

## Administrator action needed

A CCNY Samsara administrator must provision:

1. An API token restricted to **Read Vehicle Statistics** (Vehicles category) and, where available, the tag containing **only** CCNY shuttle vehicles. Never enable write permissions.
2. The **exact Samsara vehicle IDs** for the shuttle buses (not merely bus labels such as 88/89).
3. Authorization for this student-built system to ingest, store and display those shuttle-only GPS positions.

Samsara's own documentation: https://developers.samsara.com/docs/getting-started and https://developers.samsara.com/reference/getvehiclestatsfeed .

The token is sensitive; **do not enter it into chat, GitHub, or the static website**. The deploy operator should place it directly in the VPS's private environment file.

## VPS integration prepared

The following services were installed on the VPS **disabled**:

- `ccny-shuttle-collector.service` — the official Samsara polling connector, no new listening port
- `ccny-shuttle-history.service` — uses previously collected GPS observations and a separately verified stop configuration, no new listening port

The status API remains active on `127.0.0.1:8766`. OmniRoute remains isolated on `127.0.0.1:23128`. Nginx routes the public websites by hostname over standard 443.

No service will start until its required config exists. Auth failures stop with exit code 77; invalid stored cursors stop with code 78 and require deliberate backfill. Rate limits respect `Retry-After`; short network outages use bounded exponential retry. The collector pins its cursor to a hash of the approved vehicle set so ID changes cannot silently skip updates.

### Secure configuration (after authorization)

A privileged operator creates `/etc/ccny-shuttle/collector.env`, group-readable by `ccnyshuttle` only, containing:

```ini
SAMSARA_API_TOKEN=PROVIDED_BY_CCNY_ADMIN
CCNY_SHUTTLE_VEHICLE_IDS=ACTUAL_ID_1,ACTUAL_ID_2
```

The values above are placeholders and **must never be installed as actual credentials**. Set owner `root:ccnyshuttle` and mode `0640`. The directory itself should remain `0750` and `root:ccnyshuttle`.

A one-shot **read-only** probe, run on the VPS as the `ccnyshuttle` account after the environment is loaded, checks the live feed without writing any GPS records:

```sh
sudo -u ccnyshuttle sh -c '
  set -a
  . /etc/ccny-shuttle/collector.env
  set +a
  PYTHONPATH=/opt/ccny-shuttle/services/gps-collector \
    /usr/bin/python3 -m ccny_gps --probe
'
```

Its output contains only whether the source responded, allowed-record count and newest source timestamp age—**no coordinates, vehicle IDs or token**. Exit 0 means at least one fresh (<30s) permitted observation was returned; exit 3 can also occur legitimately outside service hours when all vehicle positions are stale. Exit 77 is a permissions problem; exit 78 is an invalid checkpoint. Missing credentials cause exit 2.

Only after a real shuttle observation is independently verified should the operator enable `ccny-shuttle-collector.service`. The history worker requires physically confirmed geofence coordinates, directions, and its own checked `/etc/ccny-shuttle/verified-stops.json`—**do not use approximate UI map pins**.

## Data quality requirements

- Preserve and display the original Samsara GPS event time, independent of when our HTTP poll occurred.
- Treat observations older than 30 seconds as non-live. Never fabricate a vehicle position when GPS is absent.
- Do not treat the first API request as fresh by default: Samsara returns *last known* vehicle stats, which can be hours old.
- Do not automatically discard a saved expired cursor without a considered backfill/recovery plan.
- Validate route/stop-specific history and actual arrivals independently before displaying public ETA predictions.

## Code and tests

`services/gps-collector` contains the adapter and probe; `services/eta-engine` contains the incremental stop-history processor. All tests use synthetic fixtures; they do not verify a production Samsara account.

```sh
python3 -m unittest discover -s services/gps-collector/tests -v
PYTHONPATH=services/eta-engine python3 -m unittest discover -s services/eta-engine/tests -v
```

**Do not describe the service as live** until an actual shuttle GPS fix, vehicle ID and source timestamp have passed a permitted probe and initial collection.
