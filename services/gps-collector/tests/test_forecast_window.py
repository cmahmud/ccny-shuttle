"""Timestamp indexing must preserve legacy inclusive matching and tie order."""
import random
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sys import path
path.insert(0,str(Path(__file__).resolve().parents[1]))
from ccny_gps.eta_compare import _ForecastWindow

class ForecastWindowTests(unittest.TestCase):
    def test_index_matches_original_filter_including_unsorted_ties(self):
        start=datetime(2026,11,26,10,tzinfo=timezone.utc)
        rng=random.Random(72)
        rows=[{'at':start+timedelta(seconds=rng.randrange(-500,501)), 'id':i} for i in range(1200)]
        index=_ForecastWindow(rows)
        for seconds in (0,1,75,150):
            for offset in (-700,-500,-125,0,125,500,700):
                when=start+timedelta(seconds=offset)
                old=[row for row in rows if abs((row['at']-when).total_seconds())<=seconds]
                self.assertEqual(index.near(when,seconds),old)
    def test_boundaries_and_empty(self):
        now=datetime.now(timezone.utc)
        rows=[{'at':now+timedelta(seconds=s)} for s in (75,-75,76,-76,0)]
        self.assertEqual(_ForecastWindow(rows).near(now,75),[rows[0],rows[1],rows[4]])
        self.assertEqual(_ForecastWindow([]).near(now,75),[])
