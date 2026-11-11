"""Synthetic contract tests for CCNY route matching and shadow ETA engine."""
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sys import path as py_path

py_path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.route_progress import RouteCatalog
from ccny_gps.eta_research import Fix,Segment,STOP_COORDS
from ccny_gps.eta_shadow import (
    ShadowStore,make_predictions,speed_from_recent,
    METHOD_MEDIAN,METHOD_SPEED
)

BASE=datetime(2026,11,11,16,0,tzinfo=timezone.utc)
CATALOG=RouteCatalog.load()
BUS="synthetic-bus-77140"


def fix(time,stop,dir="NB",offset_m=0):
    progress=CATALOG.stop_progress[dir][stop]+offset_m
    positions=CATALOG.cumulative[dir]
    points=CATALOG.paths[dir]
    for i,(a,b) in enumerate(zip(positions,positions[1:])):
        if progress<=b:
            t=max(0,min(1,(progress-a)/(b-a)))
            lat=points[i][0]+t*(points[i+1][0]-points[i][0])
            lon=points[i][1]+t*(points[i+1][1]-points[i][1])
            return Fix(BUS,time,lat,lon)
    return Fix(BUS,time,*points[-1])


def training(start="125",dest="135",direction="NB",count=20,seconds=300):
    return [
        Segment(BUS,start,dest,direction,seconds+i%3*12,
                BASE-timedelta(days=1,hours=2)+timedelta(minutes=i))
        for i in range(count)
    ]


class RouteGeometryTests(unittest.TestCase):
    def test_ordering_and_stop_progress(self):
        self.assertEqual(list(CATALOG.stop_progress["NB"]),["125","135","marshak","145"])
        self.assertEqual(list(CATALOG.stop_progress["SB"]),["145","marshak","125"])
        self.assertGreater(CATALOG.cumulative["NB"][-1],1000)
        self.assertGreater(CATALOG.cumulative["SB"][-1],1000)

    def test_next_stop_requires_progress_before_geofence(self):
        halfway=fix(BASE,"125",offset_m=426)
        match=CATALOG.match(halfway.lat,halfway.lon,"NB")
        self.assertIsNotNone(match)
        a,b,fraction,rem=CATALOG.next_leg("NB",match.progress_m)
        self.assertEqual((a,b),("125","135"))
        self.assertAlmostEqual(fraction,.5,delta=.05)

    def test_off_route_or_bad_coordinates_are_rejected(self):
        self.assertIsNone(CATALOG.match(41.2,-73.99,"NB"))
        self.assertIsNone(CATALOG.match(40.814,-73.96,"NB"))
        self.assertIsNone(CATALOG.match(40.82,-73.95,"XX"))

    def test_southbound_near_marshak_targets_125(self):
        f=fix(BASE,"marshak",dir="SB",offset_m=70)
        proj=CATALOG.match(f.lat,f.lon,"SB")
        self.assertEqual(CATALOG.next_leg("SB",proj.progress_m)[1],"125")


class ShadowPredictionTests(unittest.TestCase):
    def test_progress_based_forecast_is_source_timestamped(self):
        f=fix(BASE,"125",offset_m=426)
        result=make_predictions(
            f,"NB","moving","135",training(),CATALOG,
            BASE+timedelta(seconds=8),recent_fixes=[f]
        )
        self.assertEqual(len(result),1)
        eta=result[0]
        self.assertEqual(eta.model,METHOD_MEDIAN)
        self.assertEqual(eta.stop_id,"135")
        self.assertGreater(eta.training_samples,10)
        self.assertAlmostEqual((eta.predicted_arrival_at-f.timestamp).total_seconds(),156,delta=16)
        self.assertLess(eta.earliest_at,eta.predicted_arrival_at)
        self.assertGreater(eta.latest_at,eta.predicted_arrival_at)

    def test_no_future_data_leakage(self):
        future=training()
        future=[Segment(x.vehicle_id,x.origin,x.destination,x.direction,x.seconds,
                        BASE+timedelta(minutes=20+i)) for i,x in enumerate(future)]
        f=fix(BASE,"125",offset_m=300)
        self.assertEqual(make_predictions(f,"NB","moving","135",future,CATALOG,BASE),[])

    def test_guardrails_and_missing_calibration(self):
        f=fix(BASE,"125",offset_m=200)
        kwargs=dict(fix=f,direction="NB",reported_status="moving",
                    next_stop_id="135",segments=training(),catalog=CATALOG,
                    now=BASE+timedelta(seconds=5))
        self.assertEqual(make_predictions(**{**kwargs,"reported_status":"standing"}),[])
        self.assertEqual(make_predictions(**{**kwargs,"direction":"XX"}),[])
        self.assertEqual(make_predictions(**{**kwargs,"next_stop_id":"145"}),[])
        self.assertEqual(make_predictions(**{**kwargs,"now":BASE+timedelta(seconds=50)}),[])
        self.assertEqual(make_predictions(**{**kwargs,"segments":training(count=3)}),[])
        off=Fix(BUS,BASE,40.811144,-73.947)
        self.assertEqual(make_predictions(**{**kwargs,"fix":off}),[])

    def test_speed_variant_appears_only_on_valid_measured_movement(self):
        earlier=fix(BASE-timedelta(seconds=30),"125",offset_m=180)
        newer=fix(BASE,"125",offset_m=280)
        measured=speed_from_recent([earlier,newer],"NB",CATALOG,BASE)
        self.assertIsNotNone(measured)
        self.assertAlmostEqual(measured,100/30,delta=.5)
        f=fix(BASE,"125",offset_m=280)
        forecasts=make_predictions(f,"NB","moving","135",
                                   training(),CATALOG,BASE,[earlier,newer])
        self.assertEqual({x.model for x in forecasts},{METHOD_MEDIAN,METHOD_SPEED})
        no_speed=make_predictions(f,"NB","moving","135",
                                  training(),CATALOG,BASE,[f])
        self.assertEqual(len(no_speed),1)

    def test_forecasts_deduplicated_without_public_enablement(self):
        f=fix(BASE,"125",offset_m=426)
        forecasts=make_predictions(f,"NB","moving","135",
                                   training(),CATALOG,BASE)
        with tempfile.TemporaryDirectory() as temp:
            store=ShadowStore(str(Path(temp)/"shadow.db"))
            try:
                self.assertEqual(store.record(forecasts),1)
                self.assertEqual(store.record(forecasts),0)
                status=store.status()
                self.assertEqual(status["shadowForecasts"],1)
                self.assertFalse(status["publiclyVisible"])
                row=store.conn.execute(
                    "SELECT display_enabled,stop_id,predicted_arrival_at "
                    "FROM shadow_forecasts").fetchone()
                self.assertEqual(row[0],0)
                self.assertEqual(row[1],"135")
            finally:store.close()


if __name__=="__main__":
    unittest.main()
