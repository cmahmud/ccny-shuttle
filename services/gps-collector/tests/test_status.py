"""Status service tests: no network or production GPS required."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccny_gps.models import Observation
from ccny_gps.storage import ObservationStore
from ccny_gps.status import get_status
from ccny_gps.http_api import respond

NOW = datetime(2026, 11, 9, 17, 0, tzinfo=timezone.utc)


def obs(age_seconds: int, vehicle_id: str = "shuttle-synthetic-1") -> Observation:
    return Observation(
        source="samsara", vehicle_id=vehicle_id,
        latitude=40.823, longitude=-73.95,
        observed_at=NOW - timedelta(seconds=age_seconds), received_at=NOW,
    )


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = ObservationStore(str(Path(self.folder.name) / "data.sqlite3"))

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def test_empty_is_no_data_not_live(self):
        result = get_status(self.store, NOW)
        self.assertEqual(result["sourceState"], "no_data")
        self.assertIsNone(result["lastSuccessfulPoll"])
        self.assertEqual(result["transportState"], "never_connected")
        self.assertEqual(result["vehicles"], [])

    def test_fresh_delayed_stale_use_original_gps_time(self):
        for seconds, expected in [(15, "fresh"), (60, "delayed"), (300, "stale")]:
            with self.subTest(seconds=seconds):
                fresh_db = ObservationStore(str(Path(self.folder.name) / f"{seconds}.sqlite3"))
                fresh_db.commit_page("samsara", (obs(seconds),), f"cursor-{seconds}", polled_at=NOW)
                result = get_status(fresh_db, NOW)
                self.assertEqual(result["vehicles"][0]["freshness"], expected)
                self.assertEqual(result["vehicles"][0]["locationKind"], "confirmed")
                self.assertEqual(result["sourceState"], "live" if expected == "fresh" else expected)
                fresh_db.close()

    def test_latest_position_only_per_vehicle(self):
        self.store.commit_page("samsara", (obs(90), obs(10), obs(50, "shuttle-synthetic-2")), "c", polled_at=NOW)
        result = get_status(self.store, NOW)
        self.assertEqual(len(result["vehicles"]), 2)
        self.assertEqual(result["vehicles"][0]["gpsAgeSeconds"], 10.0)
        self.assertEqual(result["vehicles"][1]["gpsAgeSeconds"], 50.0)

    def test_empty_feed_updates_poll_time_not_vehicle_time(self):
        self.store.commit_page("samsara", (obs(900),), "a", polled_at=NOW)
        self.store.commit_page("samsara", (), "b", polled_at=NOW + timedelta(seconds=30))
        result = get_status(self.store, NOW + timedelta(seconds=30))
        self.assertEqual(result["sourceState"], "stale")
        self.assertEqual(result["lastSuccessfulPoll"], "2026-11-09T17:00:30Z")
        self.assertEqual(result["transportState"], "healthy")
        self.assertEqual(result["vehicles"][0]["gpsAgeSeconds"], 930.0)

    def test_transport_can_fail_while_gps_remains_separate(self):
        self.store.commit_page("samsara", (obs(30),), "c", polled_at=NOW)
        result = get_status(self.store, NOW + timedelta(minutes=5))
        self.assertEqual(result["transportState"], "offline")
        self.assertEqual(result["sourceState"], "stale")
        self.assertEqual(result["lastPollAgeSeconds"], 300.0)

    def test_transport_delay_with_empty_recent_page(self):
        self.store.commit_page("samsara", (), "empty", polled_at=NOW)
        result = get_status(self.store, NOW + timedelta(seconds=75))
        self.assertEqual(result["transportState"], "delayed")
        self.assertEqual(result["sourceState"], "no_data")

    def test_http_routes_are_read_only_and_explicit(self):
        code, data = respond("/v1/vehicles", self.store)
        self.assertEqual(code, 200)
        self.assertEqual(data["sourceState"], "no_data")
        self.assertEqual(respond("/health", self.store)[0], 200)
        self.assertEqual(respond("/v1/vehicles?token=abc", self.store)[0], 404)
        self.assertEqual(respond("/unsafe", self.store)[0], 404)

    def test_stored_vehicle_filter_preserved(self):
        self.store.commit_page("samsara", (obs(5),), "only-shuttle", polled_at=NOW)
        result = get_status(self.store, NOW)
        self.assertEqual([x["vehicleId"] for x in result["vehicles"]], ["shuttle-synthetic-1"])


if __name__ == "__main__":
    unittest.main()
