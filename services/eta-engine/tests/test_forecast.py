"""ETA model tests use synthetic travel histories only."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ccny_eta.forecast import SegmentHistory, VehicleState, forecast_arrival

NOW=datetime(2026,11,9,17,0,tzinfo=timezone.utc)

def segment(samples=(110,115,120,125,130,135,140,145)):
    return SegmentHistory("synthetic-segment", tuple(samples))

def state(age=0, fraction=0.0, mode="moving", segment_index=0, dwell=0.0):
    return VehicleState("synthetic-vehicle",segment_index,fraction,NOW-timedelta(seconds=age),mode,dwell)

class ForecastTests(unittest.TestCase):
    def test_fresh_prediction_has_ordered_bounds(self):
        x=forecast_arrival(state(fraction=.5),(segment(),),NOW)
        self.assertEqual(x.status,"predicted")
        self.assertTrue(x.is_displayable_eta)
        self.assertLessEqual(x.lower_eta_seconds,x.median_eta_seconds)
        self.assertLessEqual(x.median_eta_seconds,x.upper_eta_seconds)
        self.assertEqual(x.probability_already_passed,0)

    def test_deterministic_replay(self):
        a=forecast_arrival(state(fraction=.2),(segment(),),NOW)
        b=forecast_arrival(state(fraction=.2),(segment(),),NOW)
        self.assertEqual(a,b)

    def test_multiple_segments_require_more_time(self):
        a=forecast_arrival(state(fraction=.2),(segment(),),NOW)
        b=forecast_arrival(state(fraction=.2),(segment(),segment()),NOW)
        self.assertGreater(b.median_eta_seconds,a.median_eta_seconds)

    def test_insufficient_data_is_not_an_eta(self):
        f=forecast_arrival(state(),(segment((100,110)),),NOW)
        self.assertEqual((f.status,f.reason),("unavailable","insufficient_measured_history"))
        self.assertIsNone(f.median_eta_seconds)

    def test_unknown_direction_is_not_an_eta(self):
        self.assertEqual(forecast_arrival(state(mode="unknown"),(segment(),),NOW).reason,"vehicle_direction_unknown")

    def test_gps_expiry_is_not_an_eta(self):
        f=forecast_arrival(state(age=181),(segment(),),NOW)
        self.assertEqual((f.status,f.reason),("unavailable","gps_expired"))

    def test_possible_passage_does_not_countdown(self):
        f=forecast_arrival(state(age=110),(segment((70,85,95,108,120,145,160,170)),),NOW)
        self.assertEqual(f.status,"possibly_passed")
        self.assertFalse(f.is_displayable_eta)
        self.assertGreaterEqual(f.probability_already_passed,.15)

    def test_already_past_is_unavailable(self):
        f=forecast_arrival(state(age=170),(segment((40,45,50,55,60,65,70,75)),),NOW)
        self.assertEqual((f.status,f.reason),("unavailable","likely_passed_stop"))

    def test_terminal_without_dwell_history_is_unavailable(self):
        f=forecast_arrival(state(mode="waiting_at_terminal"),(segment(),),NOW)
        self.assertEqual((f.status,f.reason),("unavailable","terminal_departure_unknown"))

    def test_terminal_with_dwell_history(self):
        f=forecast_arrival(
            state(mode="waiting_at_terminal",dwell=80),
            (segment(),),NOW,terminal_dwell_samples_seconds=tuple(range(160,240,10))
        )
        self.assertEqual((f.status,f.reason),("predicted","terminal_dwell_estimated"))
        self.assertGreater(f.median_eta_seconds,120)

    def test_bad_vehicle_progress_rejected(self):
        with self.assertRaises(ValueError):state(fraction=1.2)

    def test_naive_observation_rejected(self):
        with self.assertRaises(ValueError):VehicleState("x",0,0,datetime(2026,11,9))

    def test_invalid_historical_duration_rejected(self):
        with self.assertRaises(ValueError):segment((1,2,float("inf")))

    def test_outage_increases_uncertainty(self):
        samples=(300,310,320,330,340,350,360,370)
        fresh=forecast_arrival(state(age=30),(segment(samples),),NOW)
        stale=forecast_arrival(state(age=90),(segment(samples),),NOW)
        self.assertGreater(stale.upper_eta_seconds-stale.lower_eta_seconds,fresh.upper_eta_seconds-fresh.lower_eta_seconds)

    def test_invalid_segment_index_rejected(self):
        with self.assertRaises(ValueError):forecast_arrival(state(segment_index=3),(segment(),),NOW)

if __name__=="__main__":
    unittest.main()
