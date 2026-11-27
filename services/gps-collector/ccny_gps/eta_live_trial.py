"""Private issuance-time experiment. No network access or public ETA endpoint.

The reference is frozen from already-ingested student forecasts, not selected
retrospectively. GPS passages remain shared-source proxies, not boarding truth.
"""
from collections import defaultdict, Counter
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from statistics import median, mean
from zoneinfo import ZoneInfo
import bisect
import json
import math
import sqlite3
from .eta_local_calibration import predicted_lead_band, _fit
from .eta_calibration import _time

NY=ZoneInfo('America/New_York')
LOCAL='issued_stop_calibrated_v1'
LONG='downstream_time_of_day_v1'
SCHEMA='''CREATE TABLE IF NOT EXISTS live_eta_trial (
 id INTEGER PRIMARY KEY, model TEXT NOT NULL, vehicle_id TEXT NOT NULL,
 direction TEXT NOT NULL, stop_id TEXT NOT NULL, observed_at TEXT NOT NULL,
 issued_at TEXT NOT NULL, recorded_at TEXT NOT NULL, arrival_at TEXT NOT NULL,
 earliest_at TEXT NOT NULL, latest_at TEXT NOT NULL,
 reference_issued_at TEXT, reference_ingested_at TEXT, reference_arrival_at TEXT,
 reference_earliest_at TEXT, reference_latest_at TEXT,
 UNIQUE(model,vehicle_id,direction,stop_id,observed_at)
); CREATE INDEX IF NOT EXISTS live_eta_trial_time ON live_eta_trial(issued_at);'''


def fit_profiles(rows, asof):
    """Frozen calibration artifact using only already-completed proxy events."""
    histories=defaultdict(lambda:defaultdict(list))
    for r in rows:
        try:
            at=_time(r['forecastAt']); done=_time(r['actualPass'])
            band=predicted_lead_band(at,_time(r['shadowArrivalAt']))
            err=float(r['shadowSignedErrorMinutes'])
            if not at<done<asof or done<asof-timedelta(days=7) or not band or not math.isfinite(err) or abs(err)>=180:continue
            key=(r['vehicle'],r['stop'],done)
            for group in ('global','band:'+band,'stop:'+r['stop']+':'+band):histories[group][key].append(err)
        except (KeyError,TypeError,ValueError,OverflowError):continue
    profiles={}
    for group,events in histories.items():
        days=len({k[2].astimezone(NY).date() for k in events})
        minimum=12 if group.startswith('stop:') else 25
        if len(events)<minimum or days<3:continue
        bias,half=_fit(events)
        profiles[group]={'biasMinutes':bias,'halfWidthMinutes':half,'events':len(events),'days':days}
    return {'asOf':asof.isoformat(),'profiles':profiles,'training':'completed matched GPS-proxy events only'}


def load_profiles(path):
    try:
        with open(path) as f:return json.load(f).get('matchedComparison',{}).get('liveCalibrationProfiles',{})
    except (OSError,ValueError,TypeError):return {}


def calibrate(base, artifact):
    try:
        at=_time(artifact['asOf']); now=base.generated_at
        if not 0<(now-at).total_seconds()<=43200:return None
        profiles=artifact['profiles']; band=predicted_lead_band(now,base.predicted_arrival_at)
        if not band or 'global' not in profiles:return None
        group=profiles.get('stop:'+base.stop_id+':'+band) or profiles.get('band:'+band) or profiles['global']
        bias=float(group['biasMinutes']); half=float(group['halfWidthMinutes'])
        if not math.isfinite(bias) or not math.isfinite(half) or not 0.5<=half<=45 or abs(bias)>30:return None
        eta=max(now+timedelta(seconds=15),base.predicted_arrival_at-timedelta(minutes=bias))
        return replace(base,model=LOCAL,predicted_arrival_at=eta,
            earliest_at=max(now,eta-timedelta(minutes=half)),latest_at=eta+timedelta(minutes=half),
            training_samples=group['events'],training_days=group['days'])
    except (KeyError,TypeError,ValueError,OverflowError):return None


def downstream(base, segments, catalog):
    """One downstream principal stop, same direction only. Arrival-to-arrival
    durations already include intermediate dwell; never add dwell twice.
    Optional 135th is not assumed to be served on each route.
    """
    ordered=catalog.ordered_stops[base.direction]
    idx=ordered.index(base.stop_id)
    next_stop=next((s for s in ordered[idx+1:] if s!='135'),None)
    if not next_stop:return None
    now=base.generated_at
    relevant=[s for s in segments if s.origin==base.stop_id and s.destination==next_stop
        and s.direction==base.direction and 50<=s.seconds<=2700
        and s.timestamp>=now-timedelta(days=14) and s.timestamp+timedelta(seconds=s.seconds)<base.source_observed_at]
    if len(relevant)<12 or len({s.timestamp.astimezone(NY).date() for s in relevant})<3:return None
    hour=base.predicted_arrival_at.astimezone(NY).hour
    nearby=[s for s in relevant if min((s.timestamp.astimezone(NY).hour-hour)%24,(hour-s.timestamp.astimezone(NY).hour)%24)<=2]
    if len(nearby)>=12 and len({s.timestamp.astimezone(NY).date() for s in nearby})>=3:relevant=nearby
    samples=sorted(s.seconds for s in relevant); lo=samples[round((len(samples)-1)*.1)]; hi=samples[round((len(samples)-1)*.9)]
    eta=base.predicted_arrival_at+timedelta(seconds=median(samples))
    if not 0<(eta-now).total_seconds()<=2700:return None
    return replace(base,model=LONG,stop_id=next_stop,predicted_arrival_at=eta,
        earliest_at=min(eta,max(now,base.earliest_at)+timedelta(seconds=lo)),
        latest_at=max(eta,base.latest_at+timedelta(seconds=hi)),
        training_samples=len(samples),training_days=len({s.timestamp.astimezone(NY).date() for s in relevant}))


def record_trial(conn,source_db,predictions):
    if not predictions:return 0
    conn.executescript(SCHEMA)
    before=conn.total_changes
    recorded=datetime.now(timezone.utc)
    with closing(sqlite3.connect(f'file:{source_db}?mode=ro',uri=True)) as db, conn:
        for p in predictions:
            at=p.generated_at; reference=None
            # The source comparison must have been received BEFORE our issuance.
            # Do not pick a retrospectively closest prediction to the actual stop.
            rows=db.execute('''SELECT forecast_generated_at,ingested_at,arrival_at,earliest_at,latest_at
             FROM forecast_comparisons WHERE source='student_public' AND vehicle_id=? AND stop_id=? AND direction=?
             AND forecast_generated_at>=? AND forecast_generated_at<=? AND ingested_at<=?
             ORDER BY forecast_generated_at DESC LIMIT 12''',
             (p.vehicle_id,p.stop_id,p.direction,(at-timedelta(seconds=45)).isoformat(),at.isoformat(),at.isoformat())).fetchall()
            for row in rows:
                try:
                    issued,ingested,arrival=map(_time,row[:3])
                    if issued<=ingested<=at and 0<=(at-issued).total_seconds()<=45 and 0<(arrival-at).total_seconds()<=2700:
                        reference=row;break
                except (ValueError,TypeError):continue
            conn.execute('''INSERT OR IGNORE INTO live_eta_trial(model,vehicle_id,direction,stop_id,observed_at,issued_at,recorded_at,arrival_at,earliest_at,latest_at,reference_issued_at,reference_ingested_at,reference_arrival_at,reference_earliest_at,reference_latest_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (p.model,p.vehicle_id,p.direction,p.stop_id,p.source_observed_at.isoformat(),at.isoformat(),recorded.isoformat(),p.predicted_arrival_at.isoformat(),p.earliest_at.isoformat(),p.latest_at.isoformat(),*(reference or (None,)*5)))
    return conn.total_changes-before


def score_trial(shadow_db,events,directions,fixes,now):
    """First following passage, known matching direction, continuous observed track.
    One scored row per model/event/predicted lead band; count unscored rows too.
    """
    with closing(sqlite3.connect(f'file:{shadow_db}?mode=ro',uri=True)) as db:
        try:rows=db.execute('SELECT model,vehicle_id,direction,stop_id,issued_at,recorded_at,arrival_at,earliest_at,latest_at,reference_arrival_at,reference_earliest_at,reference_latest_at FROM live_eta_trial ORDER BY issued_at').fetchall()
        except sqlite3.OperationalError:rows=[]
    passes=defaultdict(list); tracks=defaultdict(list)
    for e in events:passes[e.vehicle_id,e.stop_id].append(e)
    for f in fixes:tracks[f.vehicle_id].append(f.timestamp)
    for t in tracks.values():t.sort()
    for t in passes.values():t.sort(key=lambda e:e.timestamp)
    pass_times={k:[e.timestamp for e in v] for k,v in passes.items()}
    counts=defaultdict(Counter); scores=defaultdict(dict)
    for model,bus,direction,stop,issued,recorded,arrival,lo,hi,ref,rlo,rhi in rows:
        c=counts[model];c['issued']+=1
        try:
            at=_time(issued); stored=_time(recorded); eta=_time(arrival)
            if ref:c['withReference']+=1
            if now-at<timedelta(minutes=45):c['pending']+=1;continue
            key=(bus,stop); i=bisect.bisect_right(pass_times.get(key,[]),at)
            candidates=passes.get(key,[])
            if i>=len(candidates):c['noPass']+=1;continue
            e=candidates[i]; actual=e.timestamp
            if actual<=stored or actual-at>timedelta(minutes=45) or directions.get((bus,stop,actual))!=direction:c['ambiguousPass']+=1;continue
            t=tracks.get(bus,[]); a=bisect.bisect_right(t,at);b=bisect.bisect_right(t,actual)
            interval=[at,*t[a:b],actual]
            if any((y-x).total_seconds()>120 for x,y in zip(interval,interval[1:])):c['gpsGap']+=1;continue
            if not ref:c['noReference']+=1;continue
            refeta=_time(ref); band=predicted_lead_band(at,eta)
            if not band:c['invalid']+=1;continue
            own=abs((eta-actual).total_seconds())/60; student=abs((refeta-actual).total_seconds())/60
            low=_time(lo);high=_time(hi)
            source_covered=None;source_width=None
            if rlo and rhi:
                try:
                    rl=_time(rlo);rh=_time(rhi)
                    if rl<=refeta<=rh:source_covered=rl<=actual<=rh;source_width=(rh-rl).total_seconds()/60
                except (ValueError,TypeError):pass
            # First issued row per event and band; no outcome-based picking.
            scores[model].setdefault((bus,stop,actual,band),(own,student,low<=actual<=high,(high-low).total_seconds()/60,band,stop,actual.astimezone(NY).date().isoformat(),source_covered,source_width))
            c['eligibleRows']+=1
        except (ValueError,TypeError,OverflowError):c['invalid']+=1
    def summarize(xs):
        if not xs:return {'n':0}
        sc=[x for x in xs if x[7] is not None]
        return {'n':len(xs),'ourMAEmin':round(mean(x[0] for x in xs),3),'studentMAEmin':round(mean(x[1] for x in xs),3),
            'ourCoverageProxy':round(mean(x[2] for x in xs),3),'ourWidthMin':round(mean(x[3] for x in xs),3),
            'sourceRangeN':len(sc),'sourceCoverageProxy':round(mean(x[7] for x in sc),3) if sc else None,'sourceWidthMin':round(mean(x[8] for x in sc),3) if sc else None}
    result={}
    for model in (LOCAL,LONG):
        xs=list(scores[model].values())
        result[model]={'counts':dict(counts[model]),'overall':summarize(xs),'serviceDays':len({x[6] for x in xs}),
          'uniquePassages':len({k[:3] for k in scores[model]}),'byPredictedLeadBand':{b:summarize([x for x in xs if x[4]==b]) for b in ('0-4','4-8','8+')},'byStop':{s:summarize([x for x in xs if x[5]==s]) for s in ('125','135','marshak','145')}}
    return {'status':'PRIVATE_LIVE_TRIAL','publicPredictionAllowed':False,'models':result,'limits':['Frozen already-ingested source reference; no independent GPS truth.','First future direction-matched inferred passage within 45 minutes; gaps over 120s excluded.','One first-issued prediction per event and predicted lead band; repeated events remain correlated.','Unmatched or pending predictions are counted, not assigned fictional outcomes.','Downstream range combines empirical segment quantiles, not calibrated passenger coverage.']}
