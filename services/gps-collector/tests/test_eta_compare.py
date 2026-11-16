"""Paired benchmark must match same stop/bus/horizon and avoid fake samples."""
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sys import path as py_path

py_path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.eta_compare import evaluate_pairs
from ccny_gps.eta_research import Pass
from ccny_gps.eta_shadow import METHOD_MEDIAN,METHOD_SPEED

ARRIVAL=datetime(2026,11,11,18,30,tzinfo=timezone.utc)
VEHICLE="synthetic-test-bus"


def shadow(at,arrival,method=METHOD_MEDIAN,direction="NB"):
    return {
        "vehicle":VEHICLE,"stop":"135","direction":direction,
        "at":at,"observedAt":at-timedelta(seconds=5),
        "eta":arrival,"method":method,"enabled":False,
    }


def student(at,arrival,enabled=True,direction="NB"):
    return {
        "vehicle":VEHICLE,"stop":"135","direction":direction,
        "at":at,"eta":arrival,"enabled":enabled,
    }


class HeadToHeadTests(unittest.TestCase):
    def test_paired_same_horizon_same_bus_and_stop(self):
        event=Pass(VEHICLE,"135",ARRIVAL,8,3)
        at=ARRIVAL-timedelta(minutes=5)
        own=shadow(at,ARRIVAL+timedelta(minutes=1))
        other=student(at+timedelta(seconds=15),
                      ARRIVAL+timedelta(minutes=2))
        result=evaluate_pairs([event],[own],[other])
        entry=result["paired"][METHOD_MEDIAN]
        self.assertEqual(entry["pairedSamples"],1)
        self.assertEqual(entry["shadowMAEminutes"],1)
        self.assertEqual(entry["studentMAEminutes"],2)
        self.assertEqual(entry["shadowWinRate"],1)
        self.assertEqual(entry["byHorizon"]["5"]["sourcePredictionsEnabled"],1)
        self.assertFalse(result["publicETAReleaseGateMet"])

    def test_different_source_direction_or_time_is_not_paired(self):
        event=Pass(VEHICLE,"135",ARRIVAL,3,1)
        at=ARRIVAL-timedelta(minutes=5)
        for alternative in (
            student(at,ARRIVAL,direction="SB"),
            student(at+timedelta(seconds=150),ARRIVAL),
            {**student(at,ARRIVAL),"vehicle":"another"},
            {**student(at,ARRIVAL),"stop":"125"},
        ):
            with self.subTest(alternative=alternative):
                report=evaluate_pairs([event],
                                      [shadow(at,ARRIVAL)],[alternative])
                self.assertEqual(report["paired"][METHOD_MEDIAN]["pairedSamples"],0)

    def test_one_snapshot_per_stop_and_horizon(self):
        event=Pass(VEHICLE,"135",ARRIVAL,4,1)
        at=ARRIVAL-timedelta(minutes=5)
        forecast=[shadow(at,ARRIVAL),shadow(at+timedelta(seconds=20),ARRIVAL)]
        result=evaluate_pairs([event],forecast,[student(at,ARRIVAL)])
        self.assertEqual(result["paired"][METHOD_MEDIAN]["pairedSamples"],1)
        self.assertEqual(result["paired"][METHOD_MEDIAN]["shadowEligible"],1)

    def test_same_vehicle_ambiguous_short_loop_is_not_scored(self):
        event=Pass(VEHICLE,"135",ARRIVAL,4,1)
        other=Pass(VEHICLE,"135",ARRIVAL+timedelta(minutes=15),7,1)
        at=ARRIVAL-timedelta(minutes=5)
        result=evaluate_pairs(
            [event,other],[shadow(at,ARRIVAL)],
            [student(at,ARRIVAL)])
        self.assertEqual(result["paired"][METHOD_MEDIAN]["pairedSamples"],0)

    def test_source_window_coverage_is_gps_proxy_only(self):
        event=Pass(VEHICLE,"135",ARRIVAL,4,1)
        at=ARRIVAL-timedelta(minutes=5)
        own=shadow(at,ARRIVAL+timedelta(minutes=1))
        own.update(earliest=ARRIVAL-timedelta(minutes=1),
                   latest=ARRIVAL+timedelta(minutes=3))
        other=student(at,ARRIVAL+timedelta(minutes=2))
        other.update(earliest=ARRIVAL-timedelta(minutes=2),
                     latest=ARRIVAL+timedelta(minutes=4))
        result=evaluate_pairs([event],[own],[other])['paired'][METHOD_MEDIAN]
        self.assertEqual(result['sourceRange']['eligible'],1)
        self.assertEqual(result['sourceRange']['coverageOfGpsProxy'],1)
        self.assertEqual(result['sourceRange']['meanWidthMinutes'],6)
        self.assertEqual(result['shadowRange']['coverageOfGpsProxy'],1)
        self.assertEqual(result['shadowRange']['meanWidthMinutes'],4)
        self.assertEqual(result['uniquePassageEvents'],1)
        self.assertEqual(result['pairedMAEDifferenceMin'],-1)
        self.assertEqual(result['eventClusterUncertainty']['events'],1)
        self.assertEqual(result['eventClusterUncertainty']['difference95CiMin'],[-1,-1])

    def test_invalid_source_range_is_absent_not_assumed(self):
        event=Pass(VEHICLE,'135',ARRIVAL,4,1)
        at=ARRIVAL-timedelta(minutes=5)
        own=shadow(at,ARRIVAL+timedelta(minutes=1))
        other=student(at,ARRIVAL)
        other.update(earliest=ARRIVAL+timedelta(minutes=2),
                     latest=ARRIVAL+timedelta(minutes=5))
        result=evaluate_pairs([event],[own],[other])['paired'][METHOD_MEDIAN]
        self.assertEqual(result['sourceRange']['eligible'],0)
        self.assertIsNone(result['sourceRange']['coverageOfGpsProxy'])
        self.assertEqual(result['shadowRange']['eligible'],0)

    def test_multiple_horizons_share_one_event_bootstrap_cluster(self):
        event=Pass(VEHICLE,'135',ARRIVAL,4,1)
        f1=ARRIVAL-timedelta(minutes=3)
        f2=ARRIVAL-timedelta(minutes=5)
        owns=[shadow(f1,ARRIVAL+timedelta(minutes=2)),
              shadow(f2,ARRIVAL+timedelta(minutes=3))]
        other=[student(f1,ARRIVAL+timedelta(minutes=1)),
               student(f2,ARRIVAL+timedelta(minutes=1))]
        result=evaluate_pairs([event],owns,other)['paired'][METHOD_MEDIAN]
        self.assertEqual(result['pairedSamples'],2)
        self.assertEqual(result['uniquePassageEvents'],1)
        self.assertEqual(result['eventClusterUncertainty']['difference95CiMin'],[1.5,1.5])

    def test_empty_comparison_is_null_not_zero_accuracy(self):
        result=evaluate_pairs([],[],[])
        self.assertIsNone(result["paired"][METHOD_MEDIAN]["shadowMAEminutes"])
        self.assertIsNone(result["paired"][METHOD_MEDIAN]["studentMAEminutes"])


if __name__=="__main__":
    unittest.main()
