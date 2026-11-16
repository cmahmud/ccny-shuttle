"""Synthetic tests for private ETA readiness checks (no real bus records)."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sqlite3,tempfile,unittest
from sys import path as py_path
py_path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.storage import ObservationStore
from ccny_gps.eta_shadow import ShadowStore
from ccny_gps.eta_readiness import diagnose
from ccny_gps.eta_evaluation import compile_report

NOW=datetime(2026,11,11,17,0,tzinfo=timezone.utc)


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.gps=str(Path(self.temp.name)/'gps.sqlite3')
        self.shadow=str(Path(self.temp.name)/'shadow.sqlite3')
        ObservationStore(self.gps).close()
        ShadowStore(self.shadow).close()

    def tearDown(self):
        self.temp.cleanup()

    def seed(self, *, poll_seconds=3, gps_seconds=None, status='moving', context=True):
        with sqlite3.connect(self.gps) as db:
            db.execute('INSERT OR REPLACE INTO feed_state VALUES (?,?)',
                       ('student_public',(NOW-timedelta(seconds=poll_seconds)).isoformat()))
            if gps_seconds is not None:
                observed=(NOW-timedelta(seconds=gps_seconds)).isoformat()
                db.execute('''INSERT INTO observations
                   (source,vehicle_id,latitude,longitude,observed_at,received_at,
                    heading_degrees,speed_mph) VALUES (?,?,?,?,?,?,?,?)''',
                    ('student_public','fake-vehicle',40.82,-73.95,observed,NOW.isoformat(),0,None))
                if context:
                    db.execute('''INSERT INTO vehicle_context
                        (source,vehicle_id,bus_name,direction,reported_status,
                         next_stop_id,observed_at,updated_at)
                         VALUES (?,?,?,?,?,?,?,?)''',
                        ('student_public','fake-vehicle','89','NB',status,'145',observed,NOW.isoformat()))

    def test_absent_poll_is_not_a_live_source(self):
        data=diagnose(self.gps,self.shadow,NOW)
        self.assertEqual(data['reason'],'relay_never_polled')
        self.assertFalse(data['healthyRelayPoll'])
        self.assertEqual(data['freshVehicles'],0)

    def test_healthy_poll_without_gps_is_explicit(self):
        self.seed()
        data=diagnose(self.gps,self.shadow,NOW)
        self.assertEqual(data['reason'],'upstream_has_no_fresh_vehicle_positions')
        self.assertTrue(data['healthyRelayPoll'])
        self.assertEqual(data['studentForecastRows'],0)

    def test_stale_gps_remains_unavailable_even_when_poll_works(self):
        self.seed(gps_seconds=3600)
        data=diagnose(self.gps,self.shadow,NOW)
        self.assertEqual(data['reason'],'upstream_has_no_fresh_vehicle_positions')
        self.assertEqual(data['latestGpsAgeSeconds'],3600)
        self.assertEqual(data['historicallyObservedVehicles'],1)

    def test_moving_status_must_match_fresh_gps_timestamp(self):
        self.seed(gps_seconds=4,context=False)
        data=diagnose(self.gps,self.shadow,NOW)
        self.assertEqual(data['reason'],'no_fresh_directional_moving_vehicle')
        self.assertEqual(data['freshVehicles'],1)
        self.assertEqual(data['freshMovingCandidates'],0)

    def test_stationary_vehicle_is_not_a_prediction_candidate(self):
        self.seed(gps_seconds=4,status='standing')
        data=diagnose(self.gps,self.shadow,NOW)
        self.assertEqual(data['freshMovingCandidates'],0)

    def test_live_candidate_does_not_mean_approved_eta(self):
        self.seed(gps_seconds=4)
        data=diagnose(self.gps,self.shadow,NOW)
        self.assertEqual(data['freshMovingCandidates'],1)
        self.assertFalse(data['pairedComparisonPossible'])
        report=compile_report(self.gps,self.shadow,NOW)
        self.assertEqual(report['publicationStatus'],'NOT_APPROVED')
        self.assertEqual(report['collectionHealth']['freshMovingCandidates'],1)
        self.assertNotIn('fake-vehicle',str(report))

    def test_stale_relay_poll_has_priority(self):
        self.seed(poll_seconds=130,gps_seconds=3600)
        self.assertEqual(diagnose(self.gps,self.shadow,NOW)['reason'],'relay_poll_delayed')

    def test_naive_clock_rejected(self):
        with self.assertRaisesRegex(ValueError,'timezone'):
            diagnose(self.gps,self.shadow,datetime(2026,11,11))

if __name__=='__main__':unittest.main()
