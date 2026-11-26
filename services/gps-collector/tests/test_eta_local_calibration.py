import unittest
from datetime import datetime,timedelta,timezone
from ccny_gps.eta_local_calibration import evaluate_local_calibration
BASE=datetime(2026,11,2,15,tzinfo=timezone.utc)

def data(days=9):
    result=[]
    for day in range(days):
        for i in range(8):
            stop='125' if i%2==0 else '145'
            done=BASE+timedelta(days=day,minutes=30*i)
            for h in (3,5):
                result.append(dict(vehicle='bus',stop=stop,horizon=h,actualPass=done.isoformat(),forecastAt=(done-timedelta(minutes=h)).isoformat(),shadowSignedErrorMinutes=(4 if stop=='125' else -2)+(h-3),studentAbsErrorMinutes=2))
    return result

class LocalCalibrationTests(unittest.TestCase):
    def test_local_beats_global(self):
        r=evaluate_local_calibration(data())
        self.assertGreater(r['selectionCounts']['stop_horizon'],0)
        self.assertLess(r['overall']['localMAEmin'],r['overall']['globalMAEmin'])
        self.assertFalse(r['publicPredictionAllowed'])
    def test_uncompleted_outcome_cannot_train(self):
        rows=data(3)
        # Same event has many rows but must remain one completed training event.
        r=evaluate_local_calibration(rows*3,min_global_events=25)
        self.assertEqual(r['overall']['n'],0)
    def test_missing_horizon_falls_back_without_future_data(self):
        rows=data(); last=rows[-1].copy(); last['horizon']=10
        r=evaluate_local_calibration(rows+[last]);self.assertGreater(r['selectionCounts']['global'],0)
        self.assertEqual(r['byHorizon']['10']['n'],1)
    def test_invalid_and_empty(self):
        r=evaluate_local_calibration([{},dict(data()[0],shadowSignedErrorMinutes=float('nan'))]);self.assertEqual(r['overall']['n'],0)
        with self.assertRaises(ValueError):evaluate_local_calibration([],min_local_events=0)
