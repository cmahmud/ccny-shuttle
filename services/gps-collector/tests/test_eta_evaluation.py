"""Periodic ETA scorecard never authorizes public ETA predictions."""
import json,os,tempfile,unittest
from pathlib import Path
from sys import path as py_path
py_path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.storage import ObservationStore
from ccny_gps.eta_shadow import ShadowStore
from ccny_gps.eta_evaluation import compile_report,atomic_write_json

class EvaluationSafetyTests(unittest.TestCase):
    def test_empty_new_project_is_never_marked_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            gps=str(Path(temp)/"gps.db")
            shadow=str(Path(temp)/"eta-shadow.db")
            db=ObservationStore(gps);db.close()
            db=ShadowStore(shadow);db.close()
            report=compile_report(gps,shadow)
            self.assertEqual(report["mode"],"shadow_only")
            self.assertEqual(report["publicationStatus"],"NOT_APPROVED")
            self.assertTrue(report["reviewRequired"])
            self.assertFalse(report["matchedComparison"]["publicETAReleaseGateMet"])
            self.assertTrue(any("paired" in reason for reason in report["gatesOutstanding"]))

    def test_private_atomic_report_does_not_expose_bus_identifiers(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/"report.json"
            atomic_write_json(str(output),{
                "mode":"shadow_only","publicationStatus":"NOT_APPROVED",
                "gatesOutstanding":["Needs verified stop passage observations"]
            })
            self.assertEqual(os.stat(output).st_mode&0o777,0o600)
            record=json.loads(output.read_text())
            self.assertEqual(record["publicationStatus"],"NOT_APPROVED")
            self.assertNotIn("vehicleId",output.read_text())
            self.assertEqual(len(list(Path(temp).glob(".eta-eval-*.json"))),0)

if __name__=="__main__":
    unittest.main()
