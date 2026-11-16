"""Source gap reporting never confuses stationary GPS with confirmed outages."""
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sys import path as sys_path
sys_path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.source_reliability import _sample_gap_episodes

NOW=datetime(2026,11,16,17,0,tzinfo=timezone.utc)

def row(seconds,fresh=0,source_state='live',reported=2):
    at=(NOW+timedelta(seconds=seconds)).isoformat()
    return (at,source_state,3.,4.,reported,2,0,0,0,0,fresh,120.,130.)

class SampleGapTests(unittest.TestCase):
    def test_contiguous_no_fresh_gps_and_reset_on_live_fix(self):
        rows=[row(0),row(20),row(40),row(60),row(80),row(100,1),row(120),row(140)]
        s=_sample_gap_episodes(rows)
        self.assertEqual(s['allVehicleNoFreshGpsEpisodes'],2)
        self.assertEqual(s['episodesWithObservedDurationAtLeast60Seconds'],1)
        self.assertEqual(s['longestObservedNoFreshGpsSeconds'],80)
        self.assertEqual(s['sampleIntervalSecondsP50'],20)
        self.assertEqual(s['longestObservedNoFreshGpsWindowUTC']['sourceSamples'],5)
        self.assertIn('not evidence',s['interpretation'])

    def test_breaks_on_source_response_gaps_and_missing_fleet(self):
        s=_sample_gap_episodes([row(0),row(20),row(140),row(160),row(180,reported=0)])
        self.assertEqual(s['allVehicleNoFreshGpsEpisodes'],2)
        self.assertEqual(s['longestObservedNoFreshGpsSeconds'],20)
        self.assertEqual(s['episodesWithObservedDurationAtLeast60Seconds'],0)

    def test_only_live_transport_snapshots_count(self):
        s=_sample_gap_episodes([row(0,source_state='stale'),row(10,source_state='offline'),row(20,fresh=2)])
        self.assertEqual(s['allVehicleNoFreshGpsEpisodes'],0)
        self.assertIsNone(s['longestObservedNoFreshGpsSeconds'])

    def test_empty_has_no_fake_samples(self):
        s=_sample_gap_episodes([])
        self.assertIsNone(s['sampleIntervalSecondsP90'])
        self.assertIsNone(s['longestObservedNoFreshGpsWindowUTC'])

if __name__=='__main__':unittest.main()
