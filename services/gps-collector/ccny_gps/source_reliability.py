"""Private source-quality scorecard; no coordinates, bus IDs or GPS extrapolation.

Each sample is one *distinct, successfully parsed public feed response*, not
an independent Samsara poll or a measurement of absolute uptime. The source
may return fresh HTML/JSON while reporting unchanged or old bus positions.
"""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
import sqlite3
import statistics


def _percentile(values:list[float], fraction:float)->float|None:
    if not values:return None
    ordered=sorted(values)
    pos=round((len(ordered)-1)*fraction)
    return round(ordered[pos],1)


def summarize_samples(rows:list[tuple], now:datetime)->dict:
    """Summarize private aggregate delivery observations (not service uptime)."""
    if now.tzinfo is None:raise ValueError("now must be timezone aware")
    if not rows:return {
        'samples':0,'measurement':'accepted feed snapshots only',
        'sourceHealthySampleFraction':None,'freshBusSampleFraction':None,
        'unchangedFixes':0,'jumpRejections':0,'invalidReports':0,
        'status':'no_samples_yet',
        'limits':['No conclusions about bus activity or service uptime without samples.'],
    }
    # columns: timestamp, sourceState, feedAge, upstreamAge, reported,
    # parsed, accepted, unchanged, jumped, invalid, fresh, newestAge, oldestAge
    total=len(rows)
    fraction=lambda n:round(n/total,3)
    accepted=sum(x[6] for x in rows)
    unchanged=sum(x[7] for x in rows)
    jumps=sum(x[8] for x in rows)
    invalid=sum(x[9] for x in rows)
    source_ok=sum(x[1]=='live' and x[3]<=45 for x in rows)
    gps_fresh=sum(x[10]>0 and x[1]=='live' and x[3]<=45 for x in rows)
    valid_ages=[x[11] for x in rows if x[11] is not None]
    upstream_ages=[x[3] for x in rows]
    # Exposure by state is per observed response, not fake seconds of uptime.
    states={name:sum(x[1]==name for x in rows) for name in
            ('live','delayed','stale','offline','no_data','unconfigured')}
    by_hour={}
    for x in rows:
        stamp=datetime.fromisoformat(x[0])
        if stamp.tzinfo is None:continue
        hour=stamp.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:00Z')
        bucket=by_hour.setdefault(hour,{'samples':0,'freshVehicleSamples':0,'acceptedFixes':0})
        bucket['samples']+=1
        bucket['freshVehicleSamples']+=int(x[10]>0)
        bucket['acceptedFixes']+=x[6]
    return {
        'samples':total,
        'measurement':'accepted feed snapshots only',
        'sourceHealthySampleFraction':fraction(source_ok),
        'freshBusSampleFraction':fraction(gps_fresh),
        'noFreshBusSamples':total-gps_fresh,
        'acceptedFixes':accepted,
        'unchangedFixes':unchanged,
        'jumpRejections':jumps,
        'invalidReports':invalid,
        'sourceStateSamples':states,
        'newestGpsAgeSecondsP50':_percentile(valid_ages,.5),
        'newestGpsAgeSecondsP90':_percentile(valid_ages,.9),
        'upstreamPollAgeSecondsP90':_percentile(upstream_ages,.9),
        'latestSampleAt':rows[-1][0],
        'hourlyUtc':by_hour,
        'limits':[
            'Source-accepted response sampling is not continuous uptime monitoring.',
            'A browser response can be healthy while all bus locations are stale.',
            'The student website and this project share underlying GPS; the official Samsara viewer has not yielded an independent machine-readable feed.',
            'No bus status or ETA accuracy is established by source freshness alone.',
        ],
    }


def report(dbpath:str,now:datetime|None=None,hours:int=24)->dict:
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('Timezone-aware now required')
    if not 1<=hours<=336:raise ValueError('Health report hours out of range')
    since=(now-timedelta(hours=hours)).astimezone(timezone.utc).isoformat()
    with sqlite3.connect(f'file:{dbpath}?mode=ro',uri=True) as db:
        try:
            rows=db.execute('''SELECT recorded_at,source_state,feed_age_s,upstream_poll_age_s,
              source_reported_vehicles,parsed_vehicles,accepted_fixes,unchanged_fixes,
              jump_rejections,invalid_reports,fresh_source_vehicles,
              newest_vehicle_age_s,oldest_vehicle_age_s
              FROM relay_health_samples WHERE source='student_public'
              AND recorded_at>=? ORDER BY recorded_at''',(since,)).fetchall()
        except sqlite3.OperationalError:rows=[]
    summary=summarize_samples(rows,now)
    summary['periodHours']=hours
    summary['source']='student_public'
    summary['officialViewerReadiness']='public page reachable; independent live records not verified'
    return summary
