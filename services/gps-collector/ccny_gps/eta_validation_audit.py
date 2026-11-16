"""Private confidence checks for GPS-proxy ETA evaluation.

Counts/diagnostics only, never personal location, bus identifiers, or a public
confidence claim. Changing a GPS geofence does not create a real-world truth.
"""
from __future__ import annotations

import collections
from datetime import datetime
import statistics
from zoneinfo import ZoneInfo

from .eta_research import Fix,Pass,gps_passes,STOP_COORDS

NY = ZoneInfo('America/New_York')


def matched_coverage(rows:list[dict])->dict:
    """Independent GPS passage coverage by local service day, stop and horizon.

    Each paired 3/5/10 minute forecast is a distinct observation, but several
    forecasts can refer to the same geofence passage. Count unique passages
    explicitly and never mistake a large number of repeated forecasts for
    distinct arrival observations.
    """
    by_stop=collections.defaultdict(list)
    by_day=collections.defaultdict(list)
    by_horizon=collections.defaultdict(list)
    passage_keys=set()
    for row in rows:
        try:
            pass_at=datetime.fromisoformat(row['actualPass'].replace('Z','+00:00'))
            if pass_at.tzinfo is None: continue
            day=pass_at.astimezone(NY).date().isoformat()
            stop=row['stop']
            horizon=int(row['horizon'])
            if stop not in STOP_COORDS or horizon not in (3,5,10):continue
            if not isinstance(row['shadowAbsErrorMinutes'],(float,int)) or not isinstance(row['studentAbsErrorMinutes'],(float,int)):continue
            passage_keys.add((row['vehicle'],stop,pass_at.isoformat()))
        except (KeyError,ValueError,TypeError):continue
        by_stop[stop].append(row)
        by_day[day].append(row)
        by_horizon[str(horizon)].append(row)
    def metrics(entries):
        if not entries:return {'forecasts':0,'uniquePassages':0,'shadowMAEmin':None,'studentMAEmin':None}
        return {'forecasts':len(entries),
                'uniquePassages':len({(r['vehicle'],r['stop'],r['actualPass']) for r in entries}),
                'shadowMAEmin':round(statistics.mean(r['shadowAbsErrorMinutes'] for r in entries),3),
                'studentMAEmin':round(statistics.mean(r['studentAbsErrorMinutes'] for r in entries),3)}
    return {
        'serviceDaysWithPairs':len(by_day),
        'serviceDaysWithAtLeastFivePairs':sum(len(rs)>=5 for rs in by_day.values()),
        'uniquePassages':len(passage_keys),
        'byStop':{k:metrics(by_stop[k]) for k in ('125','135','marshak','145')},
        'byHorizon':{k:metrics(by_horizon[k]) for k in ('3','5','10')},
        'byServiceDay':{k:metrics(v) for k,v in sorted(by_day.items())},
        'definition':'NY local day of GPS-inferred geofence passage; forecasts are NOT independent stop events',
        'publicationAllowed':False,
    }


def geofence_sensitivity(fixes:list[Fix],variants:tuple[int,...]=(25,38,50)) -> dict:
    """How much inferred GPS passage counts depend on a chosen stop radius.

    Return aggregate counts and matching fractions; changes are *not* errors
    without physical stop confirmation. This never changes live geofences.
    """
    if 38 not in variants or any(v<10 or v>55 for v in variants):
        raise ValueError('Expected baseline 38m and bounded radii')
    snapshots={radius:gps_passes(fixes,enter_m=radius,exit_m=max(65,radius+25)) for radius in variants}
    baseline=snapshots[38]
    by_baseline=collections.defaultdict(list)
    for e in baseline:by_baseline[(e.vehicle_id,e.stop_id)].append(e.timestamp)
    out={}
    for radius,events in snapshots.items():
        if radius==38:
            matched=len(events)
        else:
            matched=sum(any(abs((e.timestamp-t).total_seconds())<=90
                for t in by_baseline[(e.vehicle_id,e.stop_id)]) for e in events)
        out[str(radius)]={
            'inferredPassages':len(events),
            'matchingBaselineWithin90s':matched,
            'fractionOfCandidatePassagesMatchingBaseline':round(matched/len(events),3) if events else None,
            'byStop':{stop:sum(e.stop_id==stop for e in events) for stop in STOP_COORDS},
        }
    return {
        'baselineEnterRadiusMeters':38,
        'baselineExitRadiusMeters':65,
        'candidateRadiiMeters':list(variants),
        'variants':out,
        'interpretation':'Geofence-radius sensitivity only; no verified physical stop arrival ground truth',
        'requiresFieldValidation':True,
        'changedProductionGeofences':False,
    }
