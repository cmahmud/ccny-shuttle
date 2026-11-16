"""Synthetic-only regression tests for historical arrival logging and ETA baselines."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from math import nan
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccny_eta import (
    GPSFix, VerifiedStop, StopDetector, TravelSample, EtaBaseline, HistoryStore,
    StopEvent, build_travel_samples, BenchmarkPrediction, ActualArrival, benchmark_errors,
)

BASE = datetime(2026, 10, 20, 13, 0, tzinfo=timezone.utc)
STOP = VerifiedStop("test-station", 40.81234, -73.95321, 35, verified=True)


def fix(seconds: int, lat: float = STOP.latitude,
        lon: float = STOP.longitude, speed: float | None = 0.0,
        bus: str = "synthetic-bus") -> GPSFix:
    return GPSFix(bus, BASE + timedelta(seconds=seconds), lat, lon, speed)


def sample(n: int, duration_min: int = 12, route: str = "south",
           origin: str = "marshak", target: str = "125",
           bus: str = "synthetic-bus") -> TravelSample:
    departure = BASE + timedelta(days=n)
    return TravelSample(route, origin, target, departure,
                        departure + timedelta(minutes=duration_min), bus)


class EventDetectionTests(unittest.TestCase):
    def test_requires_verified_fences(self):
        with self.assertRaises(ValueError):
            VerifiedStop("unknown", 40.81234, -73.95321, 30)
        with self.assertRaises(ValueError):
            VerifiedStop("too-wide", 40.81234, -73.95321, 200, verified=True)

    def test_nonfinite_fence_coordinate_rejected(self):
        with self.assertRaises(ValueError):
            VerifiedStop("not-a-coordinate", nan, -73.95, 30, verified=True)

    def test_one_drive_by_does_not_create_stop(self):
        detector = StopDetector([STOP])
        events = []
        for pos in [fix(0, speed=24), fix(10, lat=40.813, speed=23),
                    fix(20, lat=40.8131, speed=23)]:
            events.extend(detector.observe(pos))
        self.assertEqual(events, [])

    def test_two_fast_fixes_not_enough(self):
        detector = StopDetector([STOP])
        self.assertEqual(detector.observe(fix(0, speed=22)), [])
        self.assertEqual(detector.observe(fix(10, speed=22)), [])

    def test_two_slow_fixes_emit_one_arrival_and_departure(self):
        detector = StopDetector([STOP])
        events = []
        for item in [fix(0, speed=2), fix(10, speed=0), fix(15, speed=0),
                     fix(20, lat=40.813, speed=16), fix(30, lat=40.8132, speed=17)]:
            events.extend(detector.observe(item))
        self.assertEqual([e.kind for e in events], ["arrival", "departure"])
        self.assertEqual(events[0].event_at, BASE)
        self.assertEqual(events[0].detected_at, BASE + timedelta(seconds=10))
        self.assertEqual(events[1].event_at, BASE + timedelta(seconds=15))
        self.assertEqual(events[1].detected_at, BASE + timedelta(seconds=30))
        self.assertEqual(events[0].method, "geofence_inferred")

    def test_long_dwell_without_speed_is_detected(self):
        detector = StopDetector([STOP])
        self.assertEqual(detector.observe(fix(0, speed=None)), [])
        events = detector.observe(fix(25, speed=None))
        self.assertEqual([x.kind for x in events], ["arrival"])

    def test_out_of_order_fixes_ignored(self):
        d = StopDetector([STOP])
        d.observe(fix(10))
        self.assertEqual(d.observe(fix(5)), [])
        self.assertEqual(d.observe(fix(10)), [])
        events = d.observe(fix(20))
        self.assertEqual([e.kind for e in events], ["arrival"])

    def test_long_gap_does_not_fake_departure(self):
        d = StopDetector([STOP])
        d.observe(fix(0))
        d.observe(fix(10))
        self.assertEqual(d.observe(fix(300,lat=40.814)), [])
        self.assertEqual(d.observe(fix(310,lat=40.814)), [])

    def test_multiple_vehicles_independent(self):
        d = StopDetector([STOP])
        events = []
        for t in [0,10]:
            events.extend(d.observe(fix(t,bus="a")))
            events.extend(d.observe(fix(t,bus="b")))
        self.assertEqual({e.vehicle_id for e in events},{"a","b"})
        self.assertEqual(len(events),2)

    def test_gps_validation(self):
        with self.assertRaises(ValueError):
            fix(0, speed=-1)
        with self.assertRaises(ValueError):
            fix(0, lat=99)
        with self.assertRaises(ValueError):
            GPSFix("x",BASE.replace(tzinfo=None),STOP.latitude,STOP.longitude,0)


class SegmentTests(unittest.TestCase):
    def test_only_explicit_allowed_adjacent_legs(self):
        events = [
            StopEvent("a", "marshak", "departure", BASE, BASE + timedelta(seconds=5)),
            StopEvent("b", "125", "arrival", BASE + timedelta(minutes=5),
                      BASE + timedelta(minutes=6)),
            StopEvent("a", "125", "arrival", BASE + timedelta(minutes=12),
                      BASE + timedelta(minutes=13)),
            StopEvent("a", "125", "departure", BASE + timedelta(minutes=18),
                      BASE + timedelta(minutes=18)),
            StopEvent("a", "145", "arrival", BASE + timedelta(minutes=26),
                      BASE + timedelta(minutes=27)),
        ]
        allowed={("marshak","125"):"south"}
        legs=build_travel_samples(events,allowed)
        self.assertEqual(len(legs),1)
        self.assertEqual(legs[0].vehicle_id,"a")
        self.assertEqual(legs[0].duration_seconds,720)

    def test_bad_or_same_stop_legs_rejected(self):
        with self.assertRaises(ValueError):
            sample(0, target="marshak", origin="marshak")
        with self.assertRaises(ValueError):
            sample(0,duration_min=63)

    def test_negative_or_sub_minute_leg_rejected(self):
        with self.assertRaises(ValueError):
            sample(0,duration_min=0)

    def test_time_split_no_future_leakage(self):
        future=[sample(n,15) for n in range(10)]
        baseline=EtaBaseline(future)
        self.assertIsNone(baseline.predict_travel("south","marshak","125",BASE-timedelta(hours=1)))

    def test_insufficient_history_unavailable(self):
        baseline=EtaBaseline([sample(i,15) for i in range(4)])
        self.assertIsNone(baseline.predict_travel(
            "south","marshak","125",BASE+timedelta(days=6)))

    def test_distinct_routes_not_mixed(self):
        dataset=[sample(i,11) for i in range(9)]+[
            sample(i,29,route="north") for i in range(8)]
        model=EtaBaseline(dataset)
        now=BASE+timedelta(days=17)
        south=model.predict_travel("south","marshak","125",now)
        north=model.predict_travel("north","marshak","125",now)
        self.assertEqual(south.median_seconds,660)
        self.assertEqual(north.median_seconds,1740)

    def test_contextual_groups_only_when_sufficient(self):
        # Only matching morning departures are grouped; other hours excluded.
        local_start=datetime(2026,10,20,9,0,tzinfo=ZoneInfo("America/New_York"))
        morning=[]
        for i in range(12):
            start=local_start+timedelta(days=i)
            morning.append(TravelSample("south","marshak","125",start,
                         start+timedelta(minutes=10),"synthetic-bus"))
        evening=[]
        for i in range(12):
            start=local_start+timedelta(days=i,hours=7)
            evening.append(TravelSample("south","marshak","125",start,
                         start+timedelta(minutes=22),"synthetic-bus"))
        model=EtaBaseline(morning+evening)
        predicted_at=local_start+timedelta(days=20)
        estimate=model.predict_travel("south","marshak","125",predicted_at)
        self.assertEqual(estimate.context,"time_of_day")
        self.assertEqual(estimate.median_seconds,600)
        self.assertEqual(estimate.sample_count,9)

    def test_no_departure_or_stale_gps_no_live_eta(self):
        model=EtaBaseline([sample(i,12) for i in range(10)])
        now=BASE+timedelta(days=15)
        departed=now-timedelta(minutes=2)
        self.assertIsNone(model.predict_from_departure("south","marshak","125",
                      departed,now-timedelta(minutes=6),now))
        self.assertIsNone(model.predict_from_departure("south","marshak","125",
                      now+timedelta(seconds=5),now,now))
        self.assertIsNone(model.predict_from_departure("south","marshak","125",
                      departed,departed-timedelta(seconds=1),now))

    def test_very_overdue_vehicle_is_not_predicted_arriving_now(self):
        model=EtaBaseline([sample(i,12) for i in range(10)])
        now=BASE+timedelta(days=15)
        departure=now-timedelta(minutes=20)
        self.assertIsNone(model.predict_from_departure(
            "south","marshak","125",departure,now-timedelta(seconds=10),now))

    def test_outage_widens_range_without_claiming_live(self):
        model=EtaBaseline([sample(i,10+i%4) for i in range(12)])
        now=BASE+timedelta(days=15)
        depart=now-timedelta(minutes=3)
        fresh=model.predict_from_departure("south","marshak","125",
                                           depart,now-timedelta(seconds=10),now)
        stale=model.predict_from_departure("south","marshak","125",
                                           depart,now-timedelta(minutes=2),now)
        self.assertTrue(fresh.gps_recent)
        self.assertFalse(stale.gps_recent)
        self.assertLessEqual(stale.lower_seconds,fresh.lower_seconds)
        self.assertGreaterEqual(stale.upper_seconds,fresh.upper_seconds)

    def test_output_references_samples_not_mock_live_data(self):
        model=EtaBaseline([sample(i,13) for i in range(6)])
        t=model.predict_travel("south","marshak","125",BASE+timedelta(days=9))
        self.assertFalse(t.gps_recent)
        self.assertGreaterEqual(t.upper_seconds,t.median_seconds)
        self.assertGreaterEqual(t.median_seconds,t.lower_seconds)


class PersistenceTests(unittest.TestCase):
    def test_durable_idempotent_stop_events_and_travel_times(self):
        with tempfile.TemporaryDirectory() as temp:
            path=str(Path(temp)/"history.db")
            store=HistoryStore(path)
            e=StopEvent("a","125","arrival",BASE,BASE+timedelta(seconds=10))
            self.assertEqual(store.add_events([e,e]),1)
            self.assertEqual(store.add_events([e]),0)
            self.assertEqual(store.get_events(),[e])
            one=sample(0,12)
            self.assertEqual(store.add_samples([one,one]),1)
            self.assertEqual(store.add_samples([one]),0)
            self.assertEqual(store.get_samples(),[one])
            store.close()
            again=HistoryStore(path)
            self.assertEqual(again.count(),{"stop_events":1,"travel_samples":1})
            again.close()


class BenchmarkTests(unittest.TestCase):
    def test_pairs_only_exact_trip_id_and_prediction_instant(self):
        actual=[ActualArrival("bus89-125-trip1",BASE+timedelta(minutes=15))]
        ours=BenchmarkPrediction("ours","bus89-125-trip1",BASE,
                                BASE+timedelta(minutes=14))
        student=BenchmarkPrediction("student","bus89-125-trip1",BASE,
                                   BASE+timedelta(minutes=12))
        mismatch=BenchmarkPrediction("student","bus89-125-trip1",
                   BASE+timedelta(minutes=1),BASE+timedelta(minutes=19))
        values=benchmark_errors([ours,student,mismatch],actual)
        self.assertEqual(values["ours"]["paired_samples"],1)
        self.assertEqual(values["ours"]["median_absolute_error_seconds"],60)
        self.assertEqual(values["student"]["median_absolute_error_seconds"],180)

    def test_does_not_use_inferred_arrivals_as_ground_truth(self):
        with self.assertRaises(ValueError):
            ActualArrival("trip",BASE,evidence="geofence_inferred")

    def test_without_permissioned_benchmark_inputs_returns_empty(self):
        self.assertEqual(benchmark_errors([],[]),{})
        ours=[BenchmarkPrediction("ours","x",BASE,BASE+timedelta(minutes=10))]
        self.assertEqual(benchmark_errors(ours,[]),{})


if __name__ == "__main__":
    unittest.main()
