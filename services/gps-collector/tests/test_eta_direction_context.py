"""Direction-aware stop passage evaluation uses prior moving reports only."""
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sys import path as sys_path
sys_path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.eta_direction_context import directions_before_passages
from ccny_gps.eta_compare import evaluate_pairs
from ccny_gps.eta_research import Pass
from ccny_gps.eta_shadow import METHOD_MEDIAN

T=datetime(2026,11,16,18,30,tzinfo=timezone.utc)
A=Pass('test-bus','marshak',T,6,1)
B=Pass('test-bus','marshak',T+timedelta(minutes=14),4,1)

def shadow(at,direction='NB'):
    return {'vehicle':'test-bus','stop':'marshak','direction':direction,
            'at':at,'observedAt':at-timedelta(seconds=5),
            'eta':T+timedelta(minutes=1),'method':METHOD_MEDIAN,
            'enabled':False}

def student(at,direction='NB'):
    return {'vehicle':'test-bus','stop':'marshak','direction':direction,
            'at':at,'eta':T+timedelta(minutes=2),'enabled':False}

class ContextTests(unittest.TestCase):
    def test_uses_before_moving_only_not_future_or_standing(self):
        rows=[
          ('test-bus',T-timedelta(seconds=90),'NB','moving'),
          ('test-bus',T-timedelta(seconds=5),'SB','standing_at_stop'),
          ('test-bus',T,'SB','moving'), # must not switch direction at passage
          ('test-bus',B.timestamp-timedelta(seconds=15),'SB','moving'),
          ('test-bus',B.timestamp+timedelta(seconds=1),'NB','moving'),
        ]
        directions=directions_before_passages([A,B],rows)
        self.assertEqual(directions[A.vehicle_id,A.stop_id,A.timestamp],'NB')
        self.assertEqual(directions[B.vehicle_id,B.stop_id,B.timestamp],'SB')

    def test_no_old_stale_or_unknown_direction_is_inferred(self):
        rows=[('test-bus',T-timedelta(minutes=4),'NB','moving')]
        self.assertFalse(directions_before_passages([A],rows))
        self.assertFalse(directions_before_passages([A],[('test-bus',T,'SB','moving')]))
        self.assertFalse(directions_before_passages([A],[('test-bus',T-timedelta(seconds=3),'SB','stopped')]))
        self.assertFalse(directions_before_passages([A],[('test-bus',T-timedelta(seconds=3),'XX','moving')]))

    def test_opposite_direction_repeat_can_be_scored_safely(self):
        at=T-timedelta(minutes=5)
        prior=shadow(at)
        forecast=student(at)
        old=evaluate_pairs([A,B],[prior],[forecast])
        self.assertEqual(old['paired'][METHOD_MEDIAN]['pairedSamples'],0)
        directions={(A.vehicle_id,A.stop_id,A.timestamp):'NB',
                    (B.vehicle_id,B.stop_id,B.timestamp):'SB'}
        new=evaluate_pairs([A,B],[prior],[forecast],event_directions=directions)
        self.assertEqual(new['paired'][METHOD_MEDIAN]['pairedSamples'],1)
        self.assertFalse(new['publicETAReleaseGateMet'])

    def test_same_direction_repeat_still_ambiguous(self):
        at=T-timedelta(minutes=5)
        directions={(A.vehicle_id,A.stop_id,A.timestamp):'NB',
                    (B.vehicle_id,B.stop_id,B.timestamp):'NB'}
        report=evaluate_pairs([A,B],[shadow(at)],[student(at)],event_directions=directions)
        self.assertEqual(report['paired'][METHOD_MEDIAN]['pairedSamples'],0)

    def test_opposite_direction_shadow_is_not_matched(self):
        at=T-timedelta(minutes=5)
        directions={(A.vehicle_id,A.stop_id,A.timestamp):'SB',
                    (B.vehicle_id,B.stop_id,B.timestamp):'NB'}
        report=evaluate_pairs([A,B],[shadow(at,'NB')],[student(at,'NB')],event_directions=directions)
        self.assertEqual(report['paired'][METHOD_MEDIAN]['pairedSamples'],0)

if __name__=='__main__':unittest.main()
