"""Synthetic tests for *display-only* stationary GPS stabilization."""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.models import Observation
from ccny_gps.storage import ObservationStore
from ccny_gps.location_filter import stationary_display_position
from ccny_gps.status import get_status

NOW=datetime(2026,11,10,20,0,tzinfo=timezone.utc)
SRC="student_public"
VID="test-shuttle-88"


def fix(offset_s, lat, lon, source=SRC, vehicle=VID):
    return Observation(source,vehicle,lat,lon,NOW-timedelta(seconds=offset_s),NOW)


class LocationFilterTests(unittest.TestCase):
    def setUp(self):
        self.fixes=[
            fix(29,40.815000,-73.949000),
            fix(17,40.815025,-73.949018),
            fix(5,40.815035,-73.949004),
        ]

    def test_stationary_median_keeps_raw_fixes_intact(self):
        current=self.fixes[-1]
        smoothed=stationary_display_position(
            current, self.fixes,"standing_at_stop",NOW
        )
        self.assertIsNotNone(smoothed)
        self.assertEqual(smoothed["method"],"stationary_median")
        self.assertEqual(smoothed["sampleCount"],3)
        self.assertGreater(smoothed["displacementMeters"],0.5)
        self.assertAlmostEqual(smoothed["latitude"],40.815025)
        self.assertAlmostEqual(smoothed["longitude"],-73.949004)
        # Median can be exactly equal to latest, in which case no transform.
        self.assertEqual(current.latitude,40.815035)
        self.assertEqual(current.longitude,-73.949004)

    def test_standing_jitter_larger_than_15m_is_not_smoothed(self):
        latest=fix(5,40.8153,-73.9490)
        self.assertIsNone(stationary_display_position(latest,self.fixes+[latest],"standing",NOW))

    def test_moving_or_unverified_stationary_status_is_not_smoothed(self):
        for label in ("moving","inactive","unknown",None):
            with self.subTest(label=label):
                self.assertIsNone(stationary_display_position(
                    self.fixes[-1],self.fixes,label,NOW))

    def test_stale_fix_and_sparse_clusters_are_not_smoothed(self):
        self.assertIsNone(stationary_display_position(
            self.fixes[-1],self.fixes,"standing",NOW+timedelta(seconds=30)))
        self.assertIsNone(stationary_display_position(
            self.fixes[-1],self.fixes[-2:],"standing",NOW))
        early=fix(100,40.81501,-73.94901)
        self.assertIsNone(stationary_display_position(
            self.fixes[-1],[early,self.fixes[-1]],"standing",NOW))

    def test_other_vehicle_or_source_cannot_influence_location(self):
        misc=[fix(17,40.815025,-73.949018,vehicle="wrong"),
              fix(29,40.815000,-73.949000,source="samsara")]
        self.assertIsNone(stationary_display_position(
            self.fixes[-1],misc+[self.fixes[-1]],"standing",NOW))

    def test_database_status_exposes_only_separate_display_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=ObservationStore(str(Path(tmp)/"gps.db"))
            try:
                for i,obs in enumerate(self.fixes):
                    details=((VID,"88","NB","standing","145",obs.observed_at),)
                    store.commit_page(SRC,(obs,),str(i),polled_at=NOW,
                                      vehicle_details=details)
                state=get_status(store,NOW)
                vehicle=state["vehicles"][0]
                self.assertEqual(vehicle["latitude"],self.fixes[-1].latitude)
                self.assertEqual(vehicle["longitude"],self.fixes[-1].longitude)
                self.assertIsNotNone(vehicle["displayPosition"])
                self.assertEqual(vehicle["displayPosition"]["method"],"stationary_median")
                # Any new moving report disables the stationarity filter.
                next_fix=Observation(SRC,VID,40.815050,-73.9490,
                    NOW+timedelta(seconds=7),NOW+timedelta(seconds=7))
                store.commit_page(SRC,(next_fix,),"next",polled_at=NOW+timedelta(seconds=7),
                    vehicle_details=((VID,"88","NB","moving","145",next_fix.observed_at),))
                newest=get_status(store,NOW+timedelta(seconds=7))["vehicles"][0]
                self.assertIsNone(newest["displayPosition"])
            finally:store.close()

if __name__=="__main__":unittest.main()
