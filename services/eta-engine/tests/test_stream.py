"""Incremental GPS -> historical stop-event pipeline, entirely synthetic."""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccny_eta.core import VerifiedStop
from ccny_eta.replay import ReplayConfig
from ccny_eta.stream import IncrementalEventIngestor, config_fingerprint
from ccny_eta.storage import HistoryStore

BASE = datetime(2026, 11, 9, 16, 0, tzinfo=timezone.utc)
A = (40.81234, -73.95321)
B = (40.81814, -73.95018)


def config(*, a_radius=30.0, vehicles=("shuttle-89",)):
    return ReplayConfig(
        stops=(
            VerifiedStop("125", *A, a_radius, verified=True),
            VerifiedStop("marshak", *B, 35, verified=True),
        ),
        vehicles=frozenset(vehicles),
        edges={("125", "marshak"): "south"},
    )


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.gps = root / "observations.sqlite3"
        self.history = root / "events.sqlite3"
        db = sqlite3.connect(self.gps)
        db.execute(
            "CREATE TABLE observations (id INTEGER PRIMARY KEY, source TEXT, vehicle_id TEXT,"
            "observed_at TEXT, latitude REAL, longitude REAL, speed_mph REAL)"
        )
        db.close()

    def tearDown(self):
        self.directory.cleanup()

    def insert(self, time_sec, lat, lon, speed=0, vehicle="shuttle-89", source="samsara"):
        db = sqlite3.connect(self.gps)
        try:
            db.execute(
                "INSERT INTO observations "
                "(source,vehicle_id,observed_at,latitude,longitude,speed_mph) "
                "VALUES (?,?,?,?,?,?)",
                (
                    source, vehicle,
                    (BASE + timedelta(seconds=time_sec)).isoformat(),
                    lat, lon, speed,
                ),
            )
            db.commit()
        finally:
            db.close()

    def leg_inputs(self):
        for event in [(0, *A, 0), (10, *A, 1),
                      (20, 40.814, -73.95321, 10),
                      (30, 40.8142, -73.95321, 11),
                      (270, *B, 0), (280, *B, 1)]:
            self.insert(*event)

    def test_restart_recovers_detector_and_pending_departure(self):
        self.leg_inputs()
        with IncrementalEventIngestor(str(self.gps), str(self.history), config(), batch_size=2) as worker:
            first = worker.process_batch()
            self.assertEqual(first.processed, 2)
            self.assertEqual(first.new_events, 1)
            self.assertEqual(first.new_legs, 0)
            self.assertEqual(first.last_source_id, 2)

        with IncrementalEventIngestor(str(self.gps), str(self.history), config(), batch_size=2) as worker:
            second = worker.process_batch()
            self.assertEqual((second.new_events, second.new_legs), (1, 0))
            third = worker.process_batch()
            self.assertEqual((third.new_events, third.new_legs), (1, 1))
            none = worker.process_batch()
            self.assertEqual((none.processed, none.new_events, none.new_legs), (0, 0, 0))
            self.assertEqual(none.last_source_id, 6)

        store = HistoryStore(str(self.history))
        try:
            self.assertEqual(store.count(), {"stop_events": 3, "travel_samples": 1})
            sample = store.get_samples()[0]
            self.assertEqual((sample.route, sample.from_stop, sample.to_stop),
                             ("south", "125", "marshak"))
            self.assertEqual(sample.duration_seconds, 260)
        finally:
            store.close()

    def test_no_duplicate_stop_events_when_restarted(self):
        self.leg_inputs()
        with IncrementalEventIngestor(str(self.gps), str(self.history), config()) as worker:
            result = worker.process_batch()
            self.assertEqual((result.new_events, result.new_legs), (3, 1))
        with IncrementalEventIngestor(str(self.gps), str(self.history), config()) as worker:
            empty = worker.process_batch()
            self.assertEqual((empty.processed, empty.new_events, empty.new_legs), (0, 0, 0))

    def test_only_allowlisted_samsara_shuttles_used(self):
        self.insert(0, *A, vehicle="external")
        self.insert(10, *A, vehicle="external")
        self.insert(0, *A, source="not_samsara")
        self.insert(10, *A, source="not_samsara")
        self.insert(0, *A)
        self.insert(10, *A)
        with IncrementalEventIngestor(str(self.gps), str(self.history), config()) as worker:
            result = worker.process_batch()
            self.assertEqual(result.processed, 4)  # source-filtered, including 2 disallowed IDs
            self.assertEqual(result.new_events, 1)

    def test_third_party_source_history_is_separately_checkpointed(self):
        self.insert(0,*A,source="samsara")
        self.insert(0,*A,source="student_public")
        self.insert(10,*A,source="student_public")
        self.insert(15,*A,source="samsara")
        with IncrementalEventIngestor(str(self.gps),str(self.history),config(),
                                       source="student_public") as worker:
            first=worker.process_batch()
            self.assertEqual(first.processed,2)
            self.assertEqual(first.new_events,1)
            self.assertEqual(first.last_source_id,3)
        with IncrementalEventIngestor(str(self.gps),str(self.history),config(),
                                       source="student_public") as worker:
            self.assertEqual(worker.process_batch().processed,0)
        store=HistoryStore(str(self.history))
        self.assertEqual([e.kind for e in store.get_events()],["arrival"])
        store.close()
        with self.assertRaisesRegex(ValueError,"different GPS source"):
            IncrementalEventIngestor(str(self.gps),str(self.history),config(),
                                      source="samsara")

    def test_student_source_invalid_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"Unsupported GPS"):
            IncrementalEventIngestor(str(self.gps),str(self.history),config(),
                                      source="unknown")

    def test_new_rows_after_checkpoint_do_not_replay_old_rows(self):
        self.insert(0, *A)
        self.insert(10, *A)
        with IncrementalEventIngestor(str(self.gps), str(self.history), config()) as worker:
            self.assertEqual(worker.process_batch().new_events, 1)
            self.insert(20, 40.814, -73.95321, 10)
            self.insert(30, 40.8142, -73.95321, 10)
            result = worker.process_batch()
            self.assertEqual(result.processed, 2)
            self.assertEqual(result.new_events, 1)

    def test_different_verified_geometry_requires_a_new_history_database(self):
        self.insert(0, *A)
        with IncrementalEventIngestor(str(self.gps), str(self.history), config()) as worker:
            worker.process_batch()
        with self.assertRaisesRegex(ValueError, "configuration has changed"):
            IncrementalEventIngestor(str(self.gps), str(self.history), config(a_radius=45))
        self.assertNotEqual(config_fingerprint(config()), config_fingerprint(config(a_radius=45)))

    def test_concurrent_worker_cannot_overwrite_checkpoint(self):
        self.insert(0, *A)
        self.insert(10, *A)
        with IncrementalEventIngestor(str(self.gps), str(self.history), config()) as first:
            with IncrementalEventIngestor(str(self.gps), str(self.history), config()) as old:
                self.assertEqual(first.process_batch().new_events, 1)
                with self.assertRaisesRegex(RuntimeError, "another process"):
                    old.process_batch()
        store = HistoryStore(str(self.history))
        self.assertEqual(store.count()["stop_events"], 1)
        store.close()

    def test_source_reset_does_not_silently_skip_rows(self):
        self.insert(0, *A)
        self.insert(10, *A)
        with IncrementalEventIngestor(str(self.gps), str(self.history), config()) as worker:
            worker.process_batch()
        db = sqlite3.connect(self.gps)
        db.execute("DELETE FROM observations WHERE id=2")
        db.commit()
        db.close()
        with self.assertRaisesRegex(ValueError, "reset or replaced"):
            IncrementalEventIngestor(str(self.gps), str(self.history), config())

    def test_invalid_row_leaves_checkpoint_and_events_uncommitted(self):
        self.insert(0, *A)
        self.insert(10, 95, -73.95)
        with IncrementalEventIngestor(str(self.gps), str(self.history), config()) as worker:
            with self.assertRaises(ValueError):
                worker.process_batch()
            self.assertEqual(worker._last_id, 0)
            self.assertEqual(worker._store.count()["stop_events"], 0)
        db = sqlite3.connect(self.gps)
        db.execute("UPDATE observations SET latitude=?,longitude=? WHERE id=2", (A[0], A[1]))
        db.commit()
        db.close()
        with IncrementalEventIngestor(str(self.gps), str(self.history), config()) as worker:
            result = worker.process_batch()
            self.assertEqual((result.processed, result.new_events), (2, 1))

    def test_out_of_order_fix_is_ignored_for_stop_detection(self):
        self.insert(10, *A)
        self.insert(5, *A)
        self.insert(20, *A)
        with IncrementalEventIngestor(str(self.gps), str(self.history), config()) as worker:
            self.assertEqual(worker.process_batch().new_events, 1)
        store = HistoryStore(str(self.history))
        self.assertEqual(len(store.get_events()), 1)
        store.close()

    def test_large_gps_gap_does_not_create_departure(self):
        self.insert(0, *A)
        self.insert(10, *A)
        self.insert(500, 40.814, -73.952, 10)
        self.insert(510, 40.814, -73.952, 10)
        with IncrementalEventIngestor(str(self.gps), str(self.history), config()) as worker:
            self.assertEqual(worker.process_batch().new_events, 1)
        store = HistoryStore(str(self.history))
        self.assertEqual([x.kind for x in store.get_events()], ["arrival"])
        store.close()

    def test_empty_source_is_honest_and_no_fake_state_is_created(self):
        with IncrementalEventIngestor(str(self.gps), str(self.history), config()) as worker:
            result = worker.process_batch()
            self.assertEqual(result.processed, 0)
            self.assertEqual(result.last_source_id, 0)
        store = HistoryStore(str(self.history))
        self.assertEqual(store.count(), {"stop_events": 0, "travel_samples": 0})
        store.close()

    def test_rejects_same_source_and_history_db(self):
        with self.assertRaises(ValueError):
            IncrementalEventIngestor(str(self.gps), str(self.gps), config())

    def test_rejects_empty_or_unverified_inputs(self):
        with self.assertRaises(ValueError):
            config(a_radius=200)
        with self.assertRaises(ValueError):
            IncrementalEventIngestor(str(self.gps), str(self.history),
                                     config(vehicles=()))

    def test_rejects_missing_source_database(self):
        with self.assertRaises(FileNotFoundError):
            IncrementalEventIngestor(str(self.history), str(self.gps), config())


if __name__ == "__main__":
    unittest.main()
