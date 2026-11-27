import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sys import path
path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.eta_corridor_research import Sample,Leg,audit,continuous_legs,evaluate
from ccny_gps.eta_research import Fix,STOP_COORDS
T=datetime(2026,11,20,15,tzinfo=timezone.utc)

def sample(seconds,stop,offset=0,status='moving',delay=0):
    lat,lon=STOP_COORDS[stop];at=T+timedelta(seconds=seconds)
    return Sample(Fix('synthetic',at,lat+offset,lon),at+timedelta(seconds=delay),status)

class CorridorTests(unittest.TestCase):
    def test_gap_location_and_long_break_are_separate(self):
        r=audit([sample(0,'marshak',status='standing_at_stop'),sample(300,'145'),sample(2400,'125')])
        self.assertEqual(r['byLastObservedZone']['marshak']['gaps45To1800s'],1)
        self.assertEqual(r['byLastObservedZone']['marshak']['gapSecondsP50'],300)
        self.assertEqual(r['byLastObservedZone']['145']['longBreaksOver30min'],1)
        self.assertEqual(r['nearestStopOffsets']['marshak']['distanceMetersP50'],0)
    def test_continuous_leg_and_receipt_bound(self):
        rows=[sample(0,'125',-.001),sample(10,'125'),sample(100,'135',-.001),sample(110,'135',delay=25)]
        legs,excluded=continuous_legs(rows)
        self.assertEqual(len(legs),1)
        self.assertEqual(legs[0].seconds,100)
        self.assertEqual(legs[0].available,T+timedelta(seconds=135))
        self.assertEqual(excluded,{})
    def test_gap_rejects_segment(self):
        rows=[sample(0,'125',-.001),sample(10,'125'),sample(200,'135',-.001),sample(210,'135')]
        legs,excluded=continuous_legs(rows)
        self.assertEqual(legs,[])
        self.assertEqual(excluded['gps_gap'],1)
    def test_unobserved_initial_entrance(self):
        legs,excluded=continuous_legs([sample(0,'125'),sample(60,'135',-.001),sample(90,'135')])
        self.assertEqual(legs,[])
        self.assertEqual(excluded['missing_entry'],1)
    def test_future_receipt_cannot_train(self):
        prior=[]
        for i in range(30):
            at=T-timedelta(days=1+i%3,minutes=i*7)
            prior.append(Leg('125','135','NB',at,at+timedelta(seconds=180),T+timedelta(days=1)))
        target=Leg('125','135','NB',T,T+timedelta(seconds=180),T+timedelta(seconds=180))
        self.assertEqual(evaluate(prior+[target])['overall']['n'],0)
    def test_comparison_uses_same_eligible_sample(self):
        prior=[]
        for i in range(45):
            at=T-timedelta(days=1+i%3,minutes=i*5);end=at+timedelta(seconds=180)
            prior.append(Leg('125','135','NB',at,end,end))
        r=evaluate(prior)
        self.assertGreater(r['overall']['n'],0)
        self.assertEqual(r['overall']['baselineMAEmin'],0)
        self.assertEqual(r['overall']['hourPlusRecentMAEmin'],0)
        self.assertEqual(r['overall']['n']+r['abstained'],len(prior))
