"""Run with PYTHONPATH=services/gps-collector python3 -m ccny_gps --once."""
import argparse
import logging
import os
import random
import time
import json
from datetime import datetime, timezone

from .collector import Collector
from .samsara import (SamsaraFeed, SourcePermissionError, SourceCursorError, SourceRateLimited)
from .storage import ObservationStore

LOG = logging.getLogger("ccny-gps")


def summarize_probe(page, now: datetime) -> dict:
    """One authorized request, no persistence and no output of vehicle locations/IDs."""
    ages = [max(0.0, (now - obs.observed_at).total_seconds()) for obs in page.observations]
    youngest = min(ages) if ages else None
    return {
        "source": "official_samsara_vehicle_stats",
        "connected": True,
        "matched_observations": len(ages),
        "newest_observation_age_seconds": round(youngest, 1) if youngest is not None else None,
        "fresh_observation_found": youngest is not None and youngest <= 30,
        "more_pages": page.has_next_page,
        "note": "Read-only probe; does not establish sustained GPS availability or ETA accuracy",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Authorized CCNY shuttle GPS collector")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="Fetch one page sequence, then exit")
    group.add_argument("--probe", action="store_true", help="One read-only Samsara API request; no database writes")
    group.add_argument("--loop", action="store_true", help="Poll indefinitely (requires credentials)")
    group.add_argument("--status", action="store_true", help="Print confirmed GPS status without network")
    group.add_argument("--serve", action="store_true", help="Serve a local-only, read-only GPS status API")
    parser.add_argument("--db", default="./data/ccny-gps-dev.sqlite3")
    parser.add_argument("--port", type=int, default=8766, help="Local status API port")
    args = parser.parse_args()

    if args.status:
        from .status import get_status
        import json
        store = ObservationStore(args.db)
        try:
            print(json.dumps(get_status(store), indent=2))
        finally:
            store.close()
        return 0
    if args.serve:
        from .http_api import serve
        serve(args.db, port=args.port)
        return 0

    token = os.getenv("SAMSARA_API_TOKEN", "").strip()
    ids = frozenset(x.strip() for x in os.getenv("CCNY_SHUTTLE_VEHICLE_IDS", "").split(",") if x.strip())
    if not token or not ids:
        parser.error("SAMSARA_API_TOKEN and CCNY_SHUTTLE_VEHICLE_IDS must both be configured")
    if args.probe:
        try:
            result = summarize_probe(SamsaraFeed(token, ids).fetch(), datetime.now(timezone.utc))
        except SourcePermissionError:
            print(json.dumps({"connected": False, "reason": "permission_denied"}))
            return 77
        except SourceCursorError:
            print(json.dumps({"connected": False, "reason": "invalid_cursor"}))
            return 78
        except Exception:
            print(json.dumps({"connected": False, "reason": "source_unavailable"}))
            return 1
        print(json.dumps(result, indent=2))
        return 0 if result["fresh_observation_found"] else 3

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = ObservationStore(args.db)
    try:
        collector = Collector(SamsaraFeed(token, ids), store)
        failures = 0
        while True:
            try:
                outcome = collector.poll()
                LOG.info(
                    "GPS feed: pages=%s observations=%s new=%s",
                    outcome.pages, outcome.received, outcome.inserted,
                )
                failures = 0
                if args.once:
                    return 0
                # Samsara permits immediate pagination while a cursor backlog remains.
                # Wait >=5s only after the entire feed has been consumed.
                if not outcome.has_backlog:
                    time.sleep(5)
            except SourcePermissionError:
                LOG.error("GPS permission denied: verify Samsara token and vehicle-scoped read permission")
                return 77
            except SourceCursorError:
                LOG.error("Saved GPS cursor rejected: review explicit recovery/backfill before resuming")
                return 78
            except SourceRateLimited as exc:
                if args.once:
                    return 75
                time.sleep(exc.retry_after_seconds)
            except Exception as exc:
                failures += 1
                LOG.error("GPS collection failed (%s); retrying if loop enabled", type(exc).__name__)
                if args.once:
                    return 1
                time.sleep(min(300, 5 * 2 ** min(failures, 6)) + random.uniform(0, 2))
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
