"""Official Samsara source integration contract: credentials never hit snapshots.

Synthetic fixtures only. Exercises scope pinning, retry semantics, and the
read-only probe while keeping production collector disabled.
"""
import io
import json
import io
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccny_gps.__main__ import summarize_probe
from ccny_gps.collector import Collector
from ccny_gps.samsara import (
    SamsaraFeed, parse_page, SourcePermissionError, SourceCursorError,
    SourceRateLimited, SourceUnavailable,
)
from ccny_gps.storage import ObservationStore

NOW = datetime(2026, 11, 9, 17, 0, tzinfo=timezone.utc)


def data(time="2026-11-09T16:59:55Z", cursor="synthetic-cursor", has_more=False):
    return {
        "pagination": {"endCursor": cursor, "hasNextPage": has_more},
        "data": [
            {"id": "shuttle-89", "gps": [{
                "time": time, "latitude": 40.8123, "longitude": -73.9512,
                "headingDegrees": 45, "speedMilesPerHour": 12,
            }]},
            {"id": "unrelated", "gps": [{
                "time": time, "latitude": 40.123, "longitude": -73.123,
            }]},
        ],
    }


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def http_error(code, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return HTTPError("https://api.samsara.com/redacted", code, "synthetic", headers, io.BytesIO(b""))


class SourceIntegrationTests(unittest.TestCase):
    def test_read_only_probe_never_discloses_vehicle_ids_or_coordinates(self):
        page = parse_page(data(), frozenset({"shuttle-89"}), NOW)
        result = summarize_probe(page, NOW)
        self.assertEqual(result["matched_observations"], 1)
        self.assertTrue(result["fresh_observation_found"])
        self.assertNotIn("shuttle-89", json.dumps(result))
        self.assertNotIn("40.8123", json.dumps(result))
        self.assertEqual(result["source"], "official_samsara_vehicle_stats")

    def test_probe_fails_freshness_when_source_is_old(self):
        page = parse_page(data(time="2026-11-09T16:40:00Z"), frozenset({"shuttle-89"}), NOW)
        result = summarize_probe(page, NOW)
        self.assertFalse(result["fresh_observation_found"])
        self.assertGreater(result["newest_observation_age_seconds"], 1000)

    def test_scope_pinned_to_cursor_on_first_real_collector(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ObservationStore(str(Path(tmp) / "gps.db"))
            def opener(request, timeout):
                return FakeResponse(json.dumps(data()).encode())
            try:
                collector = Collector(SamsaraFeed("test-token", frozenset({"shuttle-89"}), opener), store)
                result = collector.poll()
                self.assertEqual((result.received, result.inserted), (1, 1))
                self.assertEqual(store.get_cursor("samsara"), "synthetic-cursor")
                self.assertEqual(store.latest_observations()[0].vehicle_id, "shuttle-89")
                # Same IDs are allowed; a change is not silently applied mid-stream.
                store.bind_vehicle_scope("samsara", frozenset({"shuttle-89"}))
                with self.assertRaisesRegex(ValueError, "scope changed"):
                    Collector(SamsaraFeed("test-token", frozenset({"shuttle-99"}), opener), store)
            finally:
                store.close()

    def test_backlogged_feed_keeps_cursor_and_can_catch_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ObservationStore(str(Path(tmp) / "gps.db"))
            requests = []
            def opener(request, timeout):
                from urllib.parse import parse_qs, urlparse
                params = parse_qs(urlparse(request.full_url).query)
                cursor = params.get("after", [None])[0]
                requests.append(cursor)
                payload = data(cursor="page-1", has_more=True) if cursor is None else data(cursor="page-2")
                return FakeResponse(json.dumps(payload).encode())
            try:
                feed = SamsaraFeed("test-token", frozenset({"shuttle-89"}), opener)
                collector = Collector(feed, store, max_pages=1)
                result = collector.poll()
                self.assertTrue(result.has_backlog)
                self.assertEqual(store.get_cursor("samsara"), "page-1")
                result = collector.poll()
                self.assertFalse(result.has_backlog)
                self.assertEqual(store.get_cursor("samsara"), "page-2")
                self.assertEqual(requests, [None,"page-1"])
                self.assertEqual(store.count_observations(), 1)
            finally:
                store.close()

    def test_unpinned_legacy_cursor_requires_explicit_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ObservationStore(str(Path(tmp) / "gps.db"))
            try:
                store.commit_page("samsara", (), "old-unpinned-cursor")
                with self.assertRaisesRegex(ValueError, "Legacy checkpoint"):
                    store.bind_vehicle_scope("samsara", frozenset({"shuttle-89"}))
            finally:
                store.close()

    def test_401_and_403_are_permanent_authorization_errors(self):
        for code in (401,403):
            with self.subTest(code=code):
                def opener(*_,**__):
                    raise http_error(code)
                with self.assertRaises(SourcePermissionError):
                    SamsaraFeed("redacted-token", frozenset({"shuttle-89"}), opener).fetch()

    def test_invalid_saved_cursor_requires_manual_recovery(self):
        for code in (400, 404, 410):
            with self.subTest(code=code):
                def opener(*_,**__):
                    raise http_error(code)
                with self.assertRaises(SourceCursorError):
                    SamsaraFeed("redacted-token", frozenset({"shuttle-89"}), opener).fetch("old-cursor")

    def test_initial_bad_request_is_not_misclassified_as_expired_cursor(self):
        def opener(*_,**__):
            raise http_error(400)
        with self.assertRaises(SourceUnavailable):
            SamsaraFeed("redacted-token", frozenset({"shuttle-89"}), opener).fetch()

    def test_rate_limit_exposes_only_retry_duration(self):
        def opener(*_,**__):
            raise http_error(429, 110)
        with self.assertRaises(SourceRateLimited) as result:
            SamsaraFeed("redacted-token", frozenset({"shuttle-89"}), opener).fetch()
        self.assertEqual(result.exception.retry_after_seconds, 110)
        self.assertNotIn("redacted-token", str(result.exception))

    def test_retry_after_is_clamped(self):
        def opener(*_,**__):
            raise http_error(429, 9999)
        with self.assertRaises(SourceRateLimited) as result:
            SamsaraFeed("redacted-token", frozenset({"shuttle-89"}), opener).fetch()
        self.assertEqual(result.exception.retry_after_seconds, 300)

    def test_future_source_timestamp_is_rejected(self):
        future = (NOW + timedelta(seconds=31)).isoformat()
        with self.assertRaises(ValueError):
            parse_page(data(time=future), frozenset({"shuttle-89"}), NOW)

    def test_no_credentials_are_logged_in_source_errors(self):
        for status in (401, 403, 429, 500):
            def opener(*_,**__):
                raise http_error(status)
            with self.assertRaises(Exception) as caught:
                SamsaraFeed("test-secret-123", frozenset({"shuttle-89"}), opener).fetch("saved")
            self.assertNotIn("test-secret-123", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
