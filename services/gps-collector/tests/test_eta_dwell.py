import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sys import path
path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.eta_dwell import Sample,Visit,extract_visits,conditional_quantiles,evaluate
from ccny_gps.eta_research import STOP_COORDS
T=datetime(2026,11,20,15,tzinfo=timezone.utc)
LAT,LON=STOP_COORDS['125']
def sample(sec,status,offset=0,received=None):
    at=T+timedelta(seconds=sec)
    return Sample('test',at,LAT+offset,LON,status,at+timedelta(seconds=received or 0))
def visit(i,seconds,completed=True,available=None):
    at=T-timedelta(days=1+i%3,minutes=i*10)
    end=at+timedelta(seconds=seconds)
    return Visit('test','125',at,end,completed,(at,at+timedelta(seconds=10)), 'test',available or end)
class DwellTests(unittest.TestCase):
    def test_complete_visit(self):
        visits,_=extract_visits([sample(0,'moving',.001),sample(10,'standing_at_stop'),sample(20,'standing'),sample(30,'moving',.001)])
        self.assertEqual(len(visits),1)
        self.assertTrue(visits[0].completed)
        self.assertEqual(visits[0].duration,20)
    def test_gap_is_censored_not_departure(self):
        visits,_=extract_visits([sample(0,'moving',.001),sample(10,'standing_at_stop'),sample(20,'standing'),sample(100,'moving',.001,received=8)])
        self.assertFalse(visits[0].completed)
        self.assertEqual(visits[0].duration,10)
        self.assertEqual(visits[0].available_at,T+timedelta(seconds=108))
    def test_unknown_start_not_invented(self):
        visits,_=extract_visits([sample(0,'standing_at_stop'),sample(10,'standing'),sample(20,'moving',.001)])
        self.assertEqual(visits,[])
    def test_unconfirmed_exit_and_end_of_record(self):
        track=[sample(0,'moving',.001),sample(10,'standing_at_stop'),sample(20,'standing')]
        v,_=extract_visits(track+[sample(30,'standing',.001)])
        self.assertFalse(v[0].completed)
        v,_=extract_visits(track)
        self.assertIsNone(v[0].available_at)
    def test_censored_quantile_abstention(self):
        vs=[visit(i,100,False) for i in range(15)]
        self.assertIsNone(conditional_quantiles(vs,0))
        self.assertIsNone(conditional_quantiles(vs,120))
    def test_remaining_conditional(self):
        vs=[visit(i,60 if i<15 else 180) for i in range(30)]
        result=conditional_quantiles(vs,70)
        self.assertEqual(result['medianSeconds'],110)
        self.assertEqual(result['riskCount'],15)
    def test_late_received_history_cannot_train(self):
        history=[visit(i,90,available=T+timedelta(days=1)) for i in range(30)]
        target=Visit('test','125',T,T+timedelta(seconds=60),True,(T,T+timedelta(seconds=10)), 'test',T+timedelta(seconds=60))
        report=evaluate(history+[target],T+timedelta(hours=1))
        self.assertEqual(report['overall']['n'],0)
