"""Unverified source projections during short stale GPS periods remain separate."""
import tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sys import path as python_path
python_path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.storage import ObservationStore
from ccny_gps.status import get_status
from ccny_gps.models import Observation

NOW=datetime(2026,11,16,20,0,tzinfo=timezone.utc)
SOURCE='student_public'

def forecast(at,bus,minutes,stop='125',direction='SB'):
    return (stop,bus,direction,at,at+timedelta(minutes=minutes),
            at+timedelta(minutes=minutes-3),at+timedelta(minutes=minutes+4),False)

class SourceProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=ObservationStore(str(Path(self.tmp.name)/'gps.db'))

    def tearDown(self):
        self.db.close();self.tmp.cleanup()

    def old(self):
        fix=Observation(SOURCE,'bus88',40.82,-73.95,NOW-timedelta(seconds=4),NOW)
        self.db.commit_page(SOURCE,(fix,),'gps-1',polled_at=NOW,
            vehicle_details=(('bus88','88','SB','standing_at_stop','125',fix.observed_at),))

    def poll(self,at,entries):
        self.db.commit_page(SOURCE,(),'schedule-'+str(at.timestamp()),polled_at=at,
                            benchmark_forecasts=entries)

    def test_old_bus_positions_get_a_short_explicitly_unconfirmed_source_projection(self):
        self.old();at=NOW+timedelta(minutes=2)
        self.poll(at,(forecast(at,'bus88',8),forecast(at,'bus88',26),
                      forecast(at,'unknown',5)))
        result=get_status(self.db,at)
        self.assertEqual(result['sourceState'],'stale')
        self.assertIsNone(result['sourceArrivalEstimates'])
        projection=result['sourceUnverifiedProjections']
        self.assertEqual(projection['mode'],'projection_without_fresh_gps')
        self.assertFalse(projection['liveGPSConfirmed'])
        self.assertFalse(projection['calibrated'])
        self.assertEqual(len(projection['stops']['125']),1)
        row=projection['stops']['125'][0]
        self.assertEqual(row['busName'],'88')
        self.assertEqual(row['gpsAgeSeconds'],124)
        self.assertEqual(row['arrivalAt'],forecast(at,'bus88',8)[4].isoformat().replace('+00:00','Z'))
        self.assertFalse(row['providerPredictionsEnabled'])

    def test_projection_only_within_five_minutes_of_last_gps_and_fresh_source(self):
        self.old();at=NOW+timedelta(minutes=6)
        self.poll(at,(forecast(at,'bus88',7),))
        self.assertIsNone(get_status(self.db,at)['sourceUnverifiedProjections'])

    def test_future_cycles_and_boarding_now_are_excluded(self):
        self.old();at=NOW+timedelta(minutes=2)
        self.poll(at,(forecast(at,'bus88',.5),forecast(at,'bus88',66)))
        self.assertIsNone(get_status(self.db,at)['sourceUnverifiedProjections'])

    def test_fresh_bus_estimates_not_reclassified_as_stale_projections(self):
        self.old()
        result=get_status(self.db,NOW)
        self.assertIsNone(result['sourceUnverifiedProjections'])

    def test_official_fresh_source_does_not_inherit_third_party_projections(self):
        self.old();at=NOW+timedelta(minutes=2)
        self.poll(at,(forecast(at,'bus88',8),))
        official=Observation('samsara','official',40.81,-73.952,at-timedelta(seconds=4),at)
        self.db.commit_page('samsara',(official,),'official',polled_at=at)
        result=get_status(self.db,at)
        self.assertEqual(result['source'],'samsara')
        self.assertIsNone(result['sourceUnverifiedProjections'])

if __name__=='__main__':unittest.main()
