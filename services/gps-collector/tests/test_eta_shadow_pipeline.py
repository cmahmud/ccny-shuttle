"""Integration: local GPS SQLite -> status -> shadow predictions, never public."""
import tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sys import path as py_path
py_path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.models import Observation
from ccny_gps.storage import ObservationStore
from ccny_gps.route_progress import RouteCatalog
from ccny_gps.eta_shadow import snapshot_forecasts,ShadowStore,METHOD_MEDIAN

NOW=datetime(2026,11,13,17,0,tzinfo=timezone.utc)
ROUTE=RouteCatalog.load()
BUS="synthetic-shuttle-88"

def obs(timestamp,lat,lon):
    return Observation("student_public",BUS,lat,lon,timestamp,timestamp)

class ShadowPipelineTests(unittest.TestCase):
    def test_live_source_uses_completed_history_but_never_public_eta(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=str(Path(tmp)/"gps.db")
            shadow_path=str(Path(tmp)/"shadow.db")
            store=ObservationStore(db)
            try:
                old=[]
                start=NOW-timedelta(days=1,hours=3)
                for i in range(14):
                    t=start-timedelta(days=i%3)+timedelta(minutes=40*i)
                    for delay,stop in ((0,"125"),(5,"135"),(6,"marshak"),(13,"145")):
                        lat,lon=ROUTE.stops[stop]
                        old.append(obs(t+timedelta(minutes=delay),lat,lon))
                a=ROUTE.paths["NB"][2]
                b=ROUTE.paths["NB"][3]
                fix=obs(NOW-timedelta(seconds=4),
                        (a[0]+b[0])/2,(a[1]+b[1])/2)
                store.commit_page(
                    "student_public",tuple(old+[fix]),"synthetic-only",
                    polled_at=NOW,
                    vehicle_details=((BUS,"88","NB","moving","135",fix.observed_at),)
                )
            finally:
                store.close()
            trial=[]
            predictions=snapshot_forecasts(db,ROUTE,now=NOW,trial_candidates=trial)
            self.assertEqual(len(trial),1)
            self.assertEqual(trial[0].stop_id,"marshak")
            self.assertEqual(trial[0].model,"downstream_time_of_day_v1")
            self.assertEqual(len(predictions),1,predictions)
            pred=predictions[0]
            self.assertEqual(pred.stop_id,"135")
            self.assertEqual(pred.model,METHOD_MEDIAN)
            self.assertGreaterEqual(pred.training_samples,10)
            self.assertGreater(pred.predicted_arrival_at,NOW)
            shadow=ShadowStore(shadow_path)
            try:
                self.assertEqual(shadow.record(predictions),1)
                self.assertEqual(shadow.record(predictions),0)
                self.assertFalse(shadow.status()["publiclyVisible"])
            finally:shadow.close()

if __name__=="__main__":
    unittest.main()
