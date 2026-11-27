"""Private aggregate stop dwell research; no public forecasts."""
from collections import defaultdict, Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean, median
from zoneinfo import ZoneInfo
import sqlite3
from .eta_research import STOP_COORDS, distance_m
NY=ZoneInfo('America/New_York')
STANDING={'standing','standing_at_stop'}
LANDMARKS=(0,30,60,120,180,300)

@dataclass(frozen=True)
class Sample:
    bus:str
    at:datetime
    lat:float
    lon:float
    status:str|None
    received:datetime|None=None

@dataclass(frozen=True)
class Visit:
    bus:str
    stop:str
    start:datetime
    end:datetime
    completed:bool
    stationary_times:tuple
    reason:str
    available_at:datetime|None=None
    @property
    def duration(self):return (self.end-self.start).total_seconds()


def extract_visits(samples):
    """Observed moving-to-standing onset and two standing fixes required.
    Unknown status or gaps censor a visit, never manufacture a departure."""
    tracks=defaultdict(list)
    for s in samples:tracks[s.bus].append(s)
    visits=[]; rejected=Counter()
    for bus,track in tracks.items():
        prev=None; active=None; times=[]; last=None; availability=None
        def finish(end,complete,reason,known):
            if len(times)>=2 and (end-active[1]).total_seconds()>0:
                visits.append(Visit(bus,active[0],active[1],end,complete,tuple(times),reason,known))
            else:rejected['unconfirmed_single_fix']+=1
        for s in sorted(track,key=lambda x:x.at):
            if prev and s.at<=prev.at:continue
            contiguous=prev is not None and 0<(s.at-prev.at).total_seconds()<=45
            if active:
                availability=max(availability,s.at,s.received or s.at)
                dist=distance_m((s.lat,s.lon),STOP_COORDS[active[0]])
                if not contiguous or s.status not in STANDING|{'moving'}:
                    finish(last,False,'gap_or_unknown',availability);active=None
                elif (s.at-active[1]).total_seconds()>1800:
                    finish(last,False,'duration_limit',availability);active=None
                elif dist>=65:
                    finish(s.at if s.status=='moving' else last,s.status=='moving','moving_exit' if s.status=='moving' else 'unconfirmed_exit',availability);active=None
                else:
                    if s.status in STANDING:times.append(s.at)
                    last=s.at;prev=s;continue
            if s.status=='standing_at_stop':
                stop=min(STOP_COORDS,key=lambda k:distance_m((s.lat,s.lon),STOP_COORDS[k]))
                if distance_m((s.lat,s.lon),STOP_COORDS[stop])<=38:
                    if contiguous and prev.status=='moving':
                        active=(stop,s.at);times=[s.at];last=s.at;availability=max(s.at,s.received or s.at,prev.received or prev.at)
                    else:rejected['standing_fix_without_observed_onset']+=1
                else:rejected['reported_stop_outside_geofence']+=1
            prev=s
        if active:finish(last,False,'end_of_record',None)
    return sorted(visits,key=lambda v:v.start),dict(rejected)


def conditional_quantiles(visits,elapsed):
    """Kaplan-Meier residual duration conditional on observed elapsed time.
    Censored visits contribute exposure, not departure events."""
    risk=[v for v in visits if v.duration>=elapsed]
    if len(risk)<12 or len({v.start.astimezone(NY).date() for v in risk})<3:return None
    grouped=defaultdict(lambda:[0,0])
    for v in risk:grouped[v.duration][0 if v.completed else 1]+=1
    n=len(risk); survival=1.; quantiles={}
    for t,(events,censored) in sorted(grouped.items()):
        if events:survival*=1-events/n
        for q in (.1,.5,.9):
            if q not in quantiles and 1-survival+1e-12>=q:quantiles[q]=max(0,t-elapsed)
        n-=events+censored
    if len(quantiles)!=3:return None
    return {'lowSeconds':quantiles[.1],'medianSeconds':quantiles[.5],'highSeconds':quantiles[.9],'riskCount':len(risk)}


def evaluate(visits,now):
    """Use only visits with known endpoints before the evaluated onset.
    Score first observed stationary fix at each landmark; abstain explicitly."""
    results=[]; counts=Counter(); bystop=defaultdict(Counter)
    for v in visits:
        prior=[x for x in visits if x.stop==v.stop and x.start>=v.start-timedelta(days=14) and x.available_at is not None and x.available_at<v.start and x.end<now]
        used=set()
        for landmark in LANDMARKS:
            issued=next((t for t in v.stationary_times[1:] if (t-v.start).total_seconds()>=landmark),None)
            if issued is None or issued in used or issued>=v.end or issued>=now:continue
            used.add(issued);elapsed=(issued-v.start).total_seconds()
            counts['queries']+=1;bystop[v.stop]['queries']+=1
            est=conditional_quantiles(prior,elapsed);baseline=conditional_quantiles(prior,0)
            if est is None or baseline is None:
                counts['abstained']+=1;bystop[v.stop]['abstained']+=1;continue
            counts['predicted']+=1;bystop[v.stop]['predicted']+=1
            if not v.completed or v.end>=now:counts['censored']+=1;bystop[v.stop]['censored']+=1;continue
            remaining=(v.end-issued).total_seconds()
            results.append((v.stop,landmark,abs(est['medianSeconds']-remaining)/60,abs(max(0,baseline['medianSeconds']-elapsed)-remaining)/60,est['lowSeconds']<=remaining<=est['highSeconds'],(est['highSeconds']-est['lowSeconds'])/60,(v.bus,v.start)))
    def summary(rows):
        if not rows:return {'n':0,'uniqueVisits':0,'conditionalMAEmin':None,'baselineMAEmin':None,'coverageProxy':None,'meanWidthMin':None}
        return {'n':len(rows),'uniqueVisits':len({r[6] for r in rows}),'conditionalMAEmin':round(mean(r[2] for r in rows),3),'baselineMAEmin':round(mean(r[3] for r in rows),3),'coverageProxy':round(mean(r[4] for r in rows),3),'meanWidthMin':round(mean(r[5] for r in rows),3)}
    return {'counts':dict(counts),'overall':summary(results),'byStop':{s:{**summary([r for r in results if r[0]==s]),'counts':dict(bystop[s])} for s in STOP_COORDS},'byElapsedLandmarkSeconds':{str(k):summary([r for r in results if r[1]==k]) for k in LANDMARKS}}


def report(dbpath,now):
    with closing(sqlite3.connect(f'file:{dbpath}?mode=ro',uri=True)) as db:
        rows=db.execute('''SELECT o.vehicle_id,o.observed_at,o.latitude,o.longitude,v.reported_status,o.received_at
        FROM observations o LEFT JOIN vehicle_context_history v ON o.source=v.source AND o.vehicle_id=v.vehicle_id AND o.observed_at=v.observed_at
        WHERE o.source='student_public' ORDER BY o.vehicle_id,o.observed_at''').fetchall()
    samples=[]
    for bus,stamp,lat,lon,status,received in rows:
        at=datetime.fromisoformat(stamp.replace('Z','+00:00'))
        received_at=datetime.fromisoformat(received.replace("Z","+00:00"))
        if at.tzinfo and received_at.tzinfo and at<=now and received_at<=now:samples.append(Sample(bus,at,lat,lon,status,received_at))
    visits,rejected=extract_visits(samples)
    counts={}
    for stop in STOP_COORDS:
        group=[v for v in visits if v.stop==stop];completed=[v.duration for v in group if v.completed]
        counts[stop]={'completed':len(completed),'censored':len(group)-len(completed),'completedMedianSeconds':round(median(completed),1) if completed else None,'days':len({v.start.astimezone(NY).date() for v in group})}
    return {'status':'PRIVATE_DWELL_RESEARCH','publicPredictionAllowed':False,'observedVisits':len(visits),'completedVisits':sum(v.completed for v in visits),'censoredVisits':sum(not v.completed for v in visits),'censorReasons':dict(Counter(v.reason for v in visits if not v.completed)),'excludedFixDiagnostics':rejected,'byStop':counts,'walkForward':evaluate(visits,now),'limits':['GPS stop-zone exit proxy, not actual dispatch or passenger boarding.','Observed moving-to-standing onset and two standing fixes; gaps over 45 seconds censor visits.','Earlier endpoints must have been received before the evaluated onset; context receipt times are unavailable. Informative censoring may bias estimates.','Retrospective evaluation at observation timestamps, not live issuance; coverage scored only on completed visits; repeated landmarks correlate.','No independent GPS, no source departure benchmark, no live issuance or public predictions.']}
