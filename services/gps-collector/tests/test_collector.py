"""All tests use synthetic, non-identifying GPS fixtures and no network."""
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccny_gps.collector import Collector
from ccny_gps.models import Observation, parse_time
from ccny_gps.samsara import FeedPage, SamsaraFeed, parse_page
from ccny_gps.storage import ObservationStore


NOW = datetime(2026, 11, 9, 17, 0, tzinfo=timezone.utc)


def event(time="2026-11-09T16:59:45Z", latitude=40.82):
    return {
        "time": time,
        "latitude": latitude,
        "longitude": -73.95,
        "headingDegrees": 45,
        "speedMilesPerHour": 12,
    }


def page(gps=None, cursor="cursor1", more=False):
    return {
        "data": [
            {"id": "shuttle-1", "gps": [event()] if gps is None else gps},
            {"id": "other-fleet", "gps": [event(latitude=38.3)]},
        ],
        "pagination": {"endCursor": cursor, "hasNextPage": more},
    }


class ObservationTests(unittest.TestCase):
    def test_freshness_uses_source_timestamp(self):
        obs = parse_page(page(), frozenset({"shuttle-1"}), NOW).observations[0]
        self.assertEqual(obs.freshness(NOW), "fresh")
        self.assertEqual(obs.freshness(NOW + timedelta(minutes=5)), "stale")

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            parse_time("2026-11-09T16:00:00")

    def test_invalid_coordinate_rejected(self):
        with self.assertRaises(ValueError):
            parse_page(page(gps=[event(latitude=91)]), frozenset({"shuttle-1"}), NOW)

    def test_future_source_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            parse_page(page(gps=[event(time="2026-11-09T17:10:00Z")]), frozenset({"shuttle-1"}), NOW)


class FeedTests(unittest.TestCase):
    def test_shuttle_filter_and_cursor(self):
        result = parse_page(page(), frozenset({"shuttle-1"}), NOW)
        self.assertEqual(len(result.observations), 1)
        self.assertEqual(result.observations[0].vehicle_id, "shuttle-1")
        self.assertEqual(result.end_cursor, "cursor1")

    def test_gps_list_and_single_object(self):
        obj = page(gps=event())
        result = parse_page(obj, frozenset({"shuttle-1"}), NOW)
        self.assertEqual(len(result.observations), 1)

    def test_bad_pagination_fails_closed(self):
        bad = page()
        del bad["pagination"]["endCursor"]
        with self.assertRaises(ValueError):
            parse_page(bad, frozenset({"shuttle-1"}), NOW)

    def test_no_allowlist_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_page(page(), frozenset(), NOW)

    def test_http_uses_authorized_filter_and_cursor(self):
        requests = []
        class Reply(io.BytesIO):
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.close()
        def opener(request, timeout):
            requests.append((request, timeout))
            return Reply(json.dumps(page()).encode())
        feed = SamsaraFeed("test-token", frozenset({"shuttle-1"}), opener=opener)
        feed.fetch("last")
        req, timeout = requests[0]
        params = parse_qs(urlparse(req.full_url).query)
        self.assertEqual(params["types"], ["gps"])
        self.assertEqual(params["vehicleIds"], ["shuttle-1"])
        self.assertEqual(params["after"], ["last"])
        self.assertEqual(req.get_header("Authorization"), "Bearer test-token")


class StorageTests(unittest.TestCase):
    def test_idempotent_checkpoint_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "obs.sqlite3")
            store = ObservationStore(path)
            record = parse_page(page(), frozenset({"shuttle-1"}), NOW).observations
            self.assertEqual(store.commit_page("samsara", record, "cursor1"), 1)
            self.assertEqual(store.commit_page("samsara", record, "cursor2"), 0)
            self.assertEqual(store.count_observations(), 1)
            store.close()
            second = ObservationStore(path)
            self.assertEqual(second.get_cursor("samsara"), "cursor2")
            self.assertEqual(second.count_observations(), 1)
            second.close()

    def test_checkpoint_does_not_advance_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ObservationStore(str(Path(tmp) / "obs.sqlite3"))
            with self.assertRaises(ValueError):
                store.commit_page("samsara", (), "")
            self.assertIsNone(store.get_cursor("samsara"))
            store.close()


class CollectorTests(unittest.TestCase):
    def test_pagination_and_recovery(self):
        class FakeFeed:
            def __init__(self):
                self.calls = []
            def fetch(self, cursor):
                self.calls.append(cursor)
                if cursor is None:
                    return parse_page(page(cursor="a", more=True), frozenset({"shuttle-1"}), NOW)
                return parse_page(page(gps=[], cursor="b"), frozenset({"shuttle-1"}), NOW)
        with tempfile.TemporaryDirectory() as tmp:
            store = ObservationStore(str(Path(tmp) / "obs.sqlite3"))
            feed = FakeFeed()
            out = Collector(feed, store).poll()
            self.assertEqual((out.pages, out.received, out.inserted), (2, 1, 1))
            self.assertEqual(feed.calls, [None, "a"])
            self.assertEqual(store.get_cursor("samsara"), "b")
            store.close()

    def test_stalled_cursor_rejected(self):
        class BadFeed:
            def fetch(self, cursor):
                return FeedPage((), "a", True)
        with tempfile.TemporaryDirectory() as tmp:
            store = ObservationStore(str(Path(tmp) / "obs.sqlite3"))
            store.commit_page("samsara", (), "a")
            with self.assertRaises(RuntimeError):
                Collector(BadFeed(), store).poll()
            store.close()


if __name__ == "__main__":
    unittest.main()
