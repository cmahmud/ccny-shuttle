"""Synthetic safeguards for source-attributed, uncalibrated arrival snapshots."""
import tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sys import path as python_path
python_path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.models import Observation
from ccny_gps.storage import ObservationStore
from ccny_gps.status import get_status

NOW=datetime(2026,11,16,16,15,0,tzinfo=timezone.utc)

class SourceArrivalDisplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=ObservationStore(str(Path(self.tmp.name)/'synthetic.sqlite3'))

    def tearDown(self):
        self.db.close();self.tmp.cleanup()

    def load(self,when=NOW,source='student_public',with_observation=True,entries=None,vehicle_id='fake-bus-1'):
        obs=(Observation(source=source,vehicle_id=vehicle_id,latitude=40.82,longitude=-73.95,
              observed_at=when-timedelta(seconds=4),received_at=when),) if with_observation else ()
        if entries is None:
            entries=(
                ('125',vehicle_id,'SB',when,when+timedelta(minutes=6),None,None,False),
                ('125',vehicle_id,'SB',when,when+timedelta(minutes=28),None,None,False),
                ('125',vehicle_id,'SB',when,when+timedelta(minutes=51),None,None,False),
                ('marshak',vehicle_id,'NB',when,when+timedelta(minutes=10),None,None,False),
                ('marshak',vehicle_id,'SB',when,when+timedelta(minutes=13),None,None,False),
            )
        self.db.commit_page(source,obs,'test-commit-'+str(when.timestamp()),polled_at=when,
            vehicle_details=((vehicle_id,'89','SB','moving','125',when-timedelta(seconds=4)),)
              if with_observation and source=='student_public' else (),
            benchmark_forecasts=entries)

    def test_repeated_cycles_are_preserved_without_inflating_benchmark(self):
        self.load()
        assert self.db.count_forecast_comparisons()==3, 'benchmark is still bucket-deduplicated'
        result=get_status(self.db,NOW)
        estimates=result['sourceArrivalEstimates']
        self.assertEqual(len(estimates['stops']['125']),3)
        self.assertEqual(len(estimates['stops']['marshak']),2)
        self.assertEqual(estimates['stops']['125'][0]['busName'],'89')
        self.assertEqual([e['direction'] for e in estimates['stops']['marshak']],['NB','SB'])
        self.assertTrue(estimates['experimental'])
        self.assertFalse(estimates['calibrated'])
        self.assertFalse(estimates['stops']['125'][1]['providerPredictionsEnabled'])

    def test_new_poll_replaces_schedules_even_within_same_bucket(self):
        self.load()
        later=NOW+timedelta(seconds=5)
        self.load(when=later,entries=(('145','fake-bus-1','NB',later,later+timedelta(minutes=8),None,None,False),))
        estimates=get_status(self.db,later)['sourceArrivalEstimates']
        self.assertEqual(len(estimates['stops']['125']),0)
        self.assertEqual(len(estimates['stops']['145']),1)
        self.assertEqual(self.db.count_forecast_comparisons(),4)

    def test_outage_or_stale_gps_clears_forecasts(self):
        self.load()
        self.assertIsNone(get_status(self.db,NOW+timedelta(minutes=2))['sourceArrivalEstimates'])
        self.db.commit_page('student_public',(), 'empty',polled_at=NOW+timedelta(seconds=15),
                            benchmark_forecasts=())
        self.assertIsNone(get_status(self.db,NOW+timedelta(seconds=15))['sourceArrivalEstimates'])

    def test_forecasts_require_known_fresh_vehicle(self):
        self.load(entries=(('125','unknown-bus','NB',NOW,NOW+timedelta(minutes=5),None,None,False),))
        self.assertIsNone(get_status(self.db,NOW)['sourceArrivalEstimates'])

    def test_forecast_source_timestamp_and_bounded_horizon(self):
        self.load(entries=(
            ('125','fake-bus-1','SB',NOW-timedelta(minutes=3),NOW+timedelta(minutes=6),None,None,False),
            ('125','fake-bus-1','SB',NOW,NOW+timedelta(hours=3),None,None,False),
        ))
        self.assertIsNone(get_status(self.db,NOW)['sourceArrivalEstimates'])

    def test_official_gps_must_not_inherit_third_party_forecast(self):
        self.load()
        when=NOW+timedelta(seconds=1)
        self.load(when=when,source='samsara')
        response=get_status(self.db,when)
        self.assertEqual(response['source'],'samsara')
        self.assertIsNone(response['sourceArrivalEstimates'])

    def test_source_provided_bounds_are_forwarded_only_when_ordered(self):
        estimate=NOW+timedelta(minutes=12)
        earliest=NOW+timedelta(minutes=8)
        latest=NOW+timedelta(minutes=17)
        self.load(entries=(('125','fake-bus-1','SB',NOW,estimate,earliest,latest,False),))
        row=get_status(self.db,NOW)['sourceArrivalEstimates']['stops']['125'][0]
        self.assertEqual(row['earliestAt'],earliest.isoformat())
        self.assertEqual(row['latestAt'],latest.isoformat())
        self.assertFalse(row['providerPredictionsEnabled'])
        self.assertFalse(get_status(self.db,NOW)['sourceArrivalEstimates']['calibrated'])

    def test_bogus_earliest_latest_never_fabricate_a_range(self):
        estimate=NOW+timedelta(minutes=12)
        self.load(entries=(('125','fake-bus-1','SB',NOW,estimate,
                            NOW+timedelta(minutes=16),NOW+timedelta(minutes=20),False),))
        row=get_status(self.db,NOW)['sourceArrivalEstimates']['stops']['125'][0]
        self.assertIsNone(row['earliestAt'])
        self.assertIsNone(row['latestAt'])

    def test_no_forecast_for_nac_or_unknown_stop(self):
        self.load()
        output=get_status(self.db,NOW)['sourceArrivalEstimates']
        self.assertNotIn('nac',output['stops'])
        self.assertNotIn('other',output['stops'])

if __name__=='__main__':unittest.main()
