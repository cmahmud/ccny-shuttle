"""GPS reliability metrics never confuse fresh browser polling with fresh buses."""
import tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sys import path as python_path
python_path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.storage import ObservationStore
from ccny_gps.source_reliability import report,summarize_samples

NOW=datetime(2026,11,16,17,45,tzinfo=timezone.utc)

def sample(timestamp=NOW,source_state='live',fresh=1,unchanged=0,jumped=0):
    return {
        'source':'student_public','recorded_at':timestamp,
        'source_state':source_state,'feed_age_s':5,'upstream_poll_age_s':4,
        'source_reported_vehicles':2,'parsed_vehicles':2 if fresh else 0,
        'accepted_fixes':1 if fresh else 0,'unchanged_fixes':unchanged,
        'jump_rejections':jumped,'invalid_reports':0,
        'fresh_source_vehicles':fresh,
        'newest_vehicle_age_s':12 if fresh else 180,
        'oldest_vehicle_age_s':25 if fresh else 300,
    }

class ReliabilityMetricsTests(unittest.TestCase):
    def test_healthy_browser_can_report_no_fresh_gps(self):
        with tempfile.TemporaryDirectory() as temp:
            path=str(Path(temp)/'gps.db');db=ObservationStore(path)
            db.record_relay_health(sample(NOW-timedelta(seconds=10)))
            db.record_relay_health(sample(NOW,source_state='live',fresh=0,unchanged=2))
            db.close()
            output=report(path,NOW)
            self.assertEqual(output['samples'],2)
            self.assertEqual(output['sourceHealthySampleFraction'],1)
            self.assertEqual(output['freshBusSampleFraction'],0.5)
            self.assertEqual(output['unchangedFixes'],2)
            self.assertEqual(output['newestGpsAgeSecondsP90'],180)
            self.assertEqual(output['acceptedFixes'],1)
            self.assertNotIn('vehicleId',str(output))
            self.assertNotIn('latitude',str(output))

    def test_only_recent_24_hour_window(self):
        with tempfile.TemporaryDirectory() as temp:
            path=str(Path(temp)/'gps.db');db=ObservationStore(path)
            db.record_relay_health(sample(NOW-timedelta(days=2)))
            db.record_relay_health(sample(NOW,source_state='stale',fresh=0,jumped=1))
            db.close()
            output=report(path,NOW)
            self.assertEqual(output['samples'],1)
            self.assertEqual(output['jumpRejections'],1)
            self.assertEqual(output['sourceHealthySampleFraction'],0)

    def test_empty_legacy_db_and_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            path=str(Path(temp)/'gps.db');db=ObservationStore(path)
            row=sample();row['reportedStatus']='inactive'
            db.record_relay_health(row)
            with self.assertRaises(ValueError):db.record_relay_health({**sample(),'source_reported_vehicles':-1})
            with self.assertRaises(ValueError):db.record_relay_health({**sample(),'recorded_at':NOW.replace(tzinfo=None)})
            db.close()
        self.assertEqual(summarize_samples([],NOW)['status'],'no_samples_yet')

if __name__=='__main__':unittest.main()
