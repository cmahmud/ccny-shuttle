"""Issuance-time trial contracts; synthetic records never touch production."""
import sqlite3,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sys import path
path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.eta_live_trial import *
from ccny_gps.eta_shadow import Prediction
from ccny_gps.eta_research import Segment,Pass,Fix
from ccny_gps.route_progress import RouteCatalog
from ccny_gps.storage import ObservationStore
T=datetime(2026,11,27,16,tzinfo=timezone.utc)

def base(at=T):
    return Prediction('student_public','synthetic','NB','marshak',at-timedelta(seconds=5),at,'speed',at+timedelta(minutes=3),at+timedelta(minutes=1),at+timedelta(minutes=5),20,3,100,2,5,3)

class LiveTrialTests(unittest.TestCase):
    def test_fit_completed_events_only(self):
        rows=[]
        for i in range(30):
            done=T-timedelta(days=1+i%3,minutes=i*5)
            rows.append(dict(forecastAt=(done-timedelta(minutes=3)).isoformat(),actualPass=done.isoformat(),shadowArrivalAt=(done+timedelta(minutes=1)).isoformat(),shadowSignedErrorMinutes=1,vehicle='bus',stop='marshak'))
        a=fit_profiles(rows,T)
        future=dict(rows[0],actualPass=(T+timedelta(minutes=1)).isoformat(),shadowSignedErrorMinutes=100)
        self.assertEqual(a,fit_profiles(rows+[future],T))
        self.assertEqual(a['profiles']['global']['events'],30)
        p=calibrate(base(),a);self.assertIsNone(p) # artifact must precede issuance
        p=calibrate(base(T+timedelta(seconds=1)),a)
        self.assertEqual(p.predicted_arrival_at,T+timedelta(minutes=2,seconds=1))
        self.assertIsNone(calibrate(base(T+timedelta(days=1)),a))
    def test_downstream_is_directional_and_no_future_segments(self):
        segments=[Segment('bus','marshak','145','NB',360,T-timedelta(days=1+i%3,minutes=i*7)) for i in range(15)]
        result=downstream(base(),segments,RouteCatalog.load())
        self.assertEqual(result.stop_id,'145');self.assertEqual(result.predicted_arrival_at,T+timedelta(minutes=9))
        self.assertIsNone(downstream(base(),[Segment('bus','marshak','145','NB',360,T+timedelta(minutes=i)) for i in range(15)],RouteCatalog.load()))
    def test_frozen_reference_and_dedup(self):
        with tempfile.TemporaryDirectory() as temp:
            source=str(Path(temp)/'gps.db'); shadow=str(Path(temp)/'shadow.db')
            store=ObservationStore(source);store.close()
            with sqlite3.connect(source) as db:
                for i,issued,received,eta in [(1,-20,-10,240),(2,-5,5,60)]:
                    db.execute('INSERT INTO forecast_comparisons(source,stop_id,vehicle_id,direction,forecast_generated_at,forecast_bucket,arrival_at,source_enabled,ingested_at) VALUES(?,?,?,?,?,?,?,?,?)',('student_public','marshak','synthetic','NB',(T+timedelta(seconds=issued)).isoformat(),i,(T+timedelta(seconds=eta)).isoformat(),0,(T+timedelta(seconds=received)).isoformat()))
            with sqlite3.connect(shadow) as db:
                p=replace(base(),model=LOCAL)
                self.assertEqual(record_trial(db,source,[p]),1)
                self.assertEqual(record_trial(db,source,[p]),0)
                self.assertEqual(db.execute('select reference_arrival_at from live_eta_trial').fetchone()[0],(T+timedelta(minutes=4)).isoformat())
                # Explicit synthetic recording timestamp, not a production backfill.
                db.execute('update live_eta_trial set recorded_at=?',((T+timedelta(seconds=1)).isoformat(),))
            actual=T+timedelta(minutes=3); e=Pass('synthetic','marshak',actual,5,1)
            d={('synthetic','marshak',actual):'NB'}
            fixes=[Fix('synthetic',T+timedelta(seconds=i),40.82,-73.95) for i in (30,60,90,120,150,180)]
            report=score_trial(shadow,[e],d,fixes,T+timedelta(minutes=46))
            self.assertEqual(report['models'][LOCAL]['overall']['ourMAEmin'],0)
            self.assertEqual(report['models'][LOCAL]['overall']['studentMAEmin'],1)
            self.assertFalse(report['publicPredictionAllowed'])
            self.assertEqual(score_trial(shadow,[e],d,[],T+timedelta(minutes=46))['models'][LOCAL]['counts']['gpsGap'],1)
            self.assertEqual(score_trial(shadow,[e],{},fixes,T+timedelta(minutes=46))['models'][LOCAL]['counts']['ambiguousPass'],1)
            self.assertEqual(score_trial(shadow,[e],d,fixes,T+timedelta(minutes=4))['models'][LOCAL]['counts']['pending'],1)
