"""Walk-forward bias and interval candidate cannot train on future trip data."""
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sys import path as python_path
python_path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.eta_calibration import walk_forward_calibration

BASE=datetime(2026,11,1,14,tzinfo=timezone.utc)

def event(i,offset=2.0,horizon=5):
    at=BASE+timedelta(hours=i*4)
    return {'vehicle':'test-bus','stop':'135','forecastAt':(at-timedelta(minutes=horizon)).isoformat(),
            'actualPass':at.isoformat(),'shadowSignedErrorMinutes':offset,
            'studentAbsErrorMinutes':1.,'horizon':horizon}

class WalkForwardTests(unittest.TestCase):
    def test_bias_and_source_error_compared_using_only_past_events(self):
        rows=[event(i,2.0+(.2 if i%2 else -.2)) for i in range(44)]
        result=walk_forward_calibration(rows)
        self.assertGreater(result['eligible'],1)
        self.assertLess(result['adjustedMAEmin'],result['baselineMAEmin'])
        self.assertGreater(result['rangeCoverageProxy'],.8)
        self.assertEqual(result['studentMAEmin'],1)
        self.assertFalse(result['publicPredictionAllowed'])
        self.assertEqual(result['status'],'RESEARCH_ONLY_GPS_PROXY')

    def test_future_events_are_not_training_even_with_large_residual(self):
        # The future event must never change a forecast that happened before
        # that event finished. Compare the historical (already scored) subset.
        rows=[event(i,2.0) for i in range(38)]
        base=walk_forward_calibration(rows)
        future=event(44,120.)
        extended=walk_forward_calibration(rows+[future])
        self.assertEqual(base['medianBiasCorrectionMin'],extended['medianBiasCorrectionMin'])
        # The old set's forecasts retain their original estimates.
        self.assertGreaterEqual(extended['eligible'],base['eligible'])

    def test_duplicated_forecast_horizons_do_not_inflate_event_count(self):
        rows=[]
        for i in range(15):
            rows.append(event(i,2.,3))
            rows.append(event(i,2.,5))
        result=walk_forward_calibration(rows,min_completed_events=25)
        self.assertEqual(result['eligible'],0)
        self.assertEqual(result['status'],'INSUFFICIENT_WALK_FORWARD_HISTORY')

    def test_insufficient_service_days_prevents_training(self):
        rows=[event(i,2.) for i in range(20)]
        result=walk_forward_calibration(rows,min_completed_events=5,min_distinct_days=10)
        self.assertEqual(result['eligible'],0)

if __name__=='__main__':unittest.main()
