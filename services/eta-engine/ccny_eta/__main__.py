"""A strictly synthetic example; does not connect to Samsara or the website."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from .core import EtaBaseline, TravelSample


def demo():
    base = datetime(2026, 10, 20, 13, 0, tzinfo=timezone.utc)
    samples = [
        TravelSample("south", "marshak", "125", base+timedelta(days=i),
                     base+timedelta(days=i,minutes=8+i%5),
                     "synthetic-bus-1")
        for i in range(12)
    ]
    result = EtaBaseline(samples).predict_travel(
        "south", "marshak", "125", base+timedelta(days=15)
    )
    return {
        "dataset": "SYNTHETIC DEMO — not CCNY shuttle data",
        "kind": "historical_baseline_not_live_arrival",
        "median_seconds": result.median_seconds if result else None,
        "lower_seconds": result.lower_seconds if result else None,
        "upper_seconds": result.upper_seconds if result else None,
        "sample_count": result.sample_count if result else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="CCNY ETA engine development utilities")
    parser.add_argument("--synthetic-demo", action="store_true")
    args = parser.parse_args()
    if not args.synthetic_demo:
        parser.error("Use --synthetic-demo (no live shuttle data configured)")
    print(json.dumps(demo(), indent=2))


if __name__ == "__main__":
    main()
