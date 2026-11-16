"""Quality metrics tests use generated timestamps and no external GPS calls."""
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.models import Observation
from ccny_gps.storage import ObservationStore
from ccny_gps.quality import quality_report

NOW=datetime(2026,11,9,20,0,tzinfo=timezone.utc)


def obs(bus,seconds_ago,latency):
    received=NOW-timedelta(seconds=seconds_ago)
    return Observation("student_public",bus,40.812,-73.95,
        received-timedelta(seconds=latency),received)


class QualityTests(unittest.TestCase):
    def test_source_delays_and_cadences_are_aggregated(self):
        with tempfile.TemporaryDirectory() as d:
            file=str(Path(d)/"gps.sqlite3")
            store=ObservationStore(file)
            try:
                rows=(
                    obs("bus1",100,10),
                    obs("bus1",80,20),
                    obs("bus1",50,100),
                    obs("bus2",65,5),
                )
                store.commit_page("student_public",rows,"c",polled_at=NOW)
            finally:store.close()
            q=quality_report(file,now=NOW)
            self.assertEqual(q["sampleCount"],4)
            self.assertEqual(q["vehicleCount"],2)
            self.assertEqual(q["freshWhenReceivedFraction"],.75)
            self.assertEqual(q["upTo3MinOldWhenReceivedFraction"],.25)
            self.assertEqual(q["p50SourceDelaySeconds"],15)
            self.assertGreater(q["p90SourceDelaySeconds"],20)
            self.assertNotIn("bus1",str(q))
            self.assertNotIn("40.812",str(q))
            self.assertEqual(q["source"],"student_public")

    def test_empty_source_yields_insufficient_metrics(self):
        with tempfile.TemporaryDirectory() as d:
            file=str(Path(d)/"gps.sqlite3")
            store=ObservationStore(file);store.close()
            q=quality_report(file,now=NOW)
            self.assertEqual(q["sampleCount"],0)
            self.assertIsNone(q["p90SourceDelaySeconds"])
            self.assertIsNone(q["pollAgeSeconds"])

    def test_cannot_mix_official_and_third_party_data(self):
        with tempfile.TemporaryDirectory() as d:
            file=str(Path(d)/"gps.sqlite3")
            store=ObservationStore(file)
            try:
                record=Observation("samsara","official",40.812,-73.95,NOW,NOW)
                store.commit_page("samsara",(record,),"a",polled_at=NOW)
                store.commit_page("student_public",(obs("student",10,10),),"b",polled_at=NOW)
            finally:store.close()
            ours=quality_report(file,source="student_public",now=NOW)
            official=quality_report(file,source="samsara",now=NOW)
            self.assertEqual(ours["sampleCount"],1)
            self.assertEqual(official["sampleCount"],1)

    def test_missing_db_and_source_rejected(self):
        with self.assertRaises(ValueError):
            quality_report("/does-not-exist",source="unknown")
        with self.assertRaises(FileNotFoundError):
            quality_report("/does-not-exist")

if __name__=="__main__":unittest.main()
