"""Pure, private ETA gate data quality diagnostics, not passenger arrival truth."""
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sys import path as sys_path
sys_path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.eta_validation_audit import matched_coverage,geofence_sensitivity
from ccny_gps.eta_research import Fix,STOP_COORDS

UTC=timezone.utc
BASE=datetime(2026,11,16,4,30,tzinfo=UTC) # Sunday 11:30PM in NY

def row(day,vehicle='88',stop='125',horizon=3,sh=2,st=1):
    dt=BASE+timedelta(days=day)
    return {'vehicle':vehicle,'stop':stop,'horizon':horizon,
            'actualPass':dt.isoformat(),
            'shadowAbsErrorMinutes':sh,'studentAbsErrorMinutes':st}

class MatchedCoverageTests(unittest.TestCase):
    def test_multiple_horizons_are_one_unique_passage(self):
        report=matched_coverage([row(0,horizon=3),row(0,horizon=5)])
        self.assertEqual(report['serviceDaysWithPairs'],1)
        self.assertEqual(report['uniquePassages'],1)
        self.assertEqual(report['byStop']['125']['forecasts'],2)
        self.assertEqual(report['byStop']['125']['uniquePassages'],1)
        self.assertEqual(report['byHorizon']['10']['forecasts'],0)
        self.assertIsNone(report['byHorizon']['10']['studentMAEmin'])
        self.assertEqual(list(report['byServiceDay']),['2026-11-15'])
        self.assertFalse(report['publicationAllowed'])

    def test_local_day_boundary_not_utc(self):
        a=row(0)
        b={**row(0), 'vehicle':'89','actualPass':(BASE+timedelta(minutes=15)).isoformat()}
        c=row(1)
        report=matched_coverage([a,b,c])
        self.assertEqual(report['serviceDaysWithPairs'],2)
        self.assertEqual(report['byServiceDay']['2026-11-15']['forecasts'],2)
        self.assertEqual(report['byServiceDay']['2026-11-16']['forecasts'],1)
        self.assertEqual(report['serviceDaysWithAtLeastFivePairs'],0)

    def test_invalid_stop_or_missing_metadata_not_counted(self):
        invalid={**row(0),'stop':'nac'}
        report=matched_coverage([invalid,{**row(0),'actualPass':'bad-timestamp'}])
        self.assertEqual(report['serviceDaysWithPairs'],0)
        self.assertEqual(report['uniquePassages'],0)

class RadiusAuditTests(unittest.TestCase):
    def test_radius_sensitivity_uses_only_gps_proxies(self):
        lat,lon=STOP_COORDS['125']
        points=[Fix('88',BASE+timedelta(seconds=t),lat+offset,lon)
                for t,offset in [(0,.0007),(20,.00033),(40,0.),(60,.00033),(80,.0007)]]
        report=geofence_sensitivity(points)
        self.assertEqual(report['variants']['38']['inferredPassages'],1)
        self.assertEqual(report['variants']['25']['inferredPassages'],1)
        self.assertTrue(report['requiresFieldValidation'])
        self.assertFalse(report['changedProductionGeofences'])
        self.assertNotIn('vehicle',str(report))
        self.assertNotIn('latitude',str(report))

    def test_empty_and_invalid_bounds(self):
        report=geofence_sensitivity([])
        self.assertEqual(report['variants']['38']['inferredPassages'],0)
        self.assertIsNone(report['variants']['25']['fractionOfCandidatePassagesMatchingBaseline'])
        with self.assertRaises(ValueError):geofence_sensitivity([],variants=(38,100))

if __name__=='__main__':unittest.main()
