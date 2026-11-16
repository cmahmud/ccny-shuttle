"""Synthetic tests for GPS-only route passage research.

These stop-events are *surrogates* and never constitute passenger arrivals.
"""
import sys
import unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.eta_research import (
    Fix, Pass, Segment, gps_passes, observed_segments, historical_baseline,
    STOP_COORDS
)

NOW=datetime(2026,11,10,12,0,tzinfo=timezone.utc)
BUS="test-88"

def fix(minutes, stop, delta_lat=0.0, vehicle=BUS):
    lat,lon=STOP_COORDS[stop]
    return Fix(vehicle,NOW+timedelta(minutes=minutes),lat+delta_lat,lon)

class ETAResearchTests(unittest.TestCase):
    def test_stationary_jitter_counts_one_geofence_visit(self):
        fixes=[fix(0,"125"),fix(.2,"125",.00005),
               fix(.4,"125"),fix(.6,"125",.00002)]
        passes=gps_passes(fixes)
        self.assertEqual(len([e for e in passes if e.stop_id=="125"]),1)
        self.assertEqual(passes[0].stop_id,"125")

    def test_return_pass_counts_after_moving_away(self):
        fixes=[fix(0,"125"),fix(1,"135"),fix(2,"125")]
        hits=gps_passes(fixes,min_repeat_s=30)
        self.assertEqual(len([p for p in hits if p.stop_id=="125"]),2)

    def test_short_gps_gap_does_not_create_second_pass(self):
        fixes=[fix(0,"125"),fix(2,"125")]
        self.assertEqual(len([e for e in gps_passes(fixes)
                              if e.stop_id=="125"]),1)

    def test_one_route_segment_and_direction(self):
        hits=[
            Pass(BUS,"125",NOW,3,1),
            Pass(BUS,"135",NOW+timedelta(minutes=5),8,1),
            Pass(BUS,"marshak",NOW+timedelta(minutes=6),5,1),
        ]
        result=observed_segments(hits)
        self.assertEqual([(s.origin,s.destination,s.direction)
                           for s in result],
                         [("125","135","NB"),("135","marshak","NB")])

    def test_no_wild_outages_counted_as_travel_time(self):
        hits=[
            Pass(BUS,"125",NOW,3,1),
            Pass(BUS,"135",NOW+timedelta(hours=4),8,1),
        ]
        self.assertFalse(observed_segments(hits))

    def test_chronological_baseline_does_not_peek_into_future(self):
        prior=[Segment(BUS,"125","135","NB",300,NOW+timedelta(minutes=i))
               for i in range(5)]
        next_sample=Segment(BUS,"125","135","NB",600,NOW+timedelta(minutes=6))
        trials=historical_baseline(prior+[next_sample],min_train=5)
        self.assertEqual(len(trials),1)
        self.assertEqual(trials[0]["predictedSeconds"],300)
        self.assertEqual(trials[0]["observedSeconds"],600)
        self.assertEqual(trials[0]["trainingCount"],5)

    def test_geofence_timestamp_validation(self):
        with self.assertRaisesRegex(ValueError,"timezone"):
            gps_passes([Fix(BUS,datetime(2026,11,10),40.811144,-73.953374)])

if __name__=="__main__":unittest.main()
