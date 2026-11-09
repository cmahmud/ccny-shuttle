"""Read-only GPS replay and explicit stop geometry permission tests."""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ccny_eta.replay import load_config, read_fixes, replay
from ccny_eta.storage import HistoryStore

BASE=datetime(2026,11,9,15,0,tzinfo=timezone.utc)
CENTER=[40.81234,-73.95321]
NEXT=[40.81635,-73.95120]

class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.root=Path(self.folder.name)
        self.gps=self.root/"collector.sqlite3"
        self.config=self.root/"verified.json"
        c=sqlite3.connect(self.gps)
        c.execute("CREATE TABLE observations (id INTEGER PRIMARY KEY,source TEXT,vehicle_id TEXT,observed_at TEXT,latitude REAL,longitude REAL,speed_mph REAL)")
        entries=[
          # Two slow in first stop => arrival, two outside => departure.
          ("samsara","shuttle-A",0,*CENTER,0.0),
          ("samsara","shuttle-A",10,*CENTER,0.0),
          ("samsara","shuttle-A",20,*CENTER,0.0),
          ("samsara","shuttle-A",30,40.8133,-73.95321,9.0),
          ("samsara","shuttle-A",40,40.8137,-73.95321,10.0),
          # Arrives at next stop about 6 minutes later.
          ("samsara","shuttle-A",380,*NEXT,0.0),
          ("samsara","shuttle-A",390,*NEXT,0.0),
          ("samsara","shuttle-A",400,*NEXT,0.0),
          # Unrelated fleet coordinates are filtered by the replay allowlist.
          ("samsara","unrelated-vehicle",10,*CENTER,0.0),
        ]
        for source,vehicle,secs,lat,lon,speed in entries:
            c.execute("INSERT INTO observations(source,vehicle_id,observed_at,latitude,longitude,speed_mph) VALUES(?,?,?,?,?,?)",
             (source,vehicle,(BASE+timedelta(seconds=secs)).isoformat(),lat,lon,speed))
        c.commit();c.close()
        self._save_config(verified=True)

    def tearDown(self):
        self.folder.cleanup()

    def _save_config(self, verified=True, allowed=None):
        document={
          "allowed_vehicle_ids":allowed or ["shuttle-A"],
          "stops":[
             {"id":"125","latitude":CENTER[0],"longitude":CENTER[1],"radius_m":35,"verified":verified},
             {"id":"marshak","latitude":NEXT[0],"longitude":NEXT[1],"radius_m":35,"verified":verified}
          ],
          "allowed_legs":[{"from":"125","to":"marshak","route":"south"}]
        }
        self.config.write_text(json.dumps(document))

    def test_unverified_geofence_cannot_run(self):
        self._save_config(verified=False)
        with self.assertRaises(ValueError):
            load_config(str(self.config))

    def test_invalid_leg_cannot_run(self):
        document=json.loads(self.config.read_text())
        document["allowed_legs"][0]["to"]="not_verified"
        self.config.write_text(json.dumps(document))
        with self.assertRaises(ValueError):
            load_config(str(self.config))

    def test_readonly_filtered_import_and_replay(self):
        conf=load_config(str(self.config))
        fixes=read_fixes(str(self.gps),conf.vehicles)
        self.assertEqual(len(fixes),8)
        events,samples=replay(conf,fixes)
        self.assertEqual([(x.stop_id,x.kind) for x in events],
                         [("125","arrival"),("125","departure"),("marshak","arrival")])
        self.assertEqual(len(samples),1)
        # Departure and arrival were independently seen, so elapsed trip time is known
        # even though there were no mid-leg GPS observations.

    def test_event_history_replay_is_idempotent(self):
        config=load_config(str(self.config))
        events,samples=replay(config,read_fixes(str(self.gps),config.vehicles))
        store=HistoryStore(str(self.root/"history.sqlite3"))
        self.assertEqual(store.add_events(events),3)
        self.assertEqual(store.add_events(events),0)
        self.assertEqual(store.add_samples(samples),1)
        self.assertEqual(store.add_samples(samples),0)
        self.assertEqual(store.count()["stop_events"],3)
        store.close()

    def test_explicit_third_party_replay_only_reads_that_source(self):
        db=sqlite3.connect(self.gps)
        db.execute("INSERT INTO observations(source,vehicle_id,observed_at,latitude,longitude,speed_mph) VALUES(?,?,?,?,?,?)",
          ("student_public","shuttle-A",BASE.isoformat(),CENTER[0],CENTER[1],None))
        db.commit();db.close()
        third=read_fixes(str(self.gps),frozenset({"shuttle-A"}),source="student_public")
        self.assertEqual(len(third),1)
        self.assertEqual(third[0].source,"student_public")
        normal=read_fixes(str(self.gps),frozenset({"shuttle-A"}),source="samsara")
        self.assertEqual(len(normal),8)
        with self.assertRaises(ValueError):
            read_fixes(str(self.gps),frozenset({"shuttle-A"}),source="incorrect")

    def test_missing_gps_database_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            read_fixes(str(self.root/"no.sqlite3"),frozenset({"shuttle-A"}))


if __name__ == "__main__":
    unittest.main()
