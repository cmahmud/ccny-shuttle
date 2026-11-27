"""Private aggregate GPS continuity and historical corridor travel audit.
No live traffic feed, coordinate changes or public prediction release.
"""
from collections import defaultdict, Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime,timedelta
from statistics import median,mean
from zoneinfo import ZoneInfo
import bisect
import sqlite3
from .eta_research import Fix,STOP_COORDS,ROUTE_EDGES,distance_m,gps_passes
NY=ZoneInfo('America/New_York')

@dataclass(frozen=True)
class Sample:
    fix:Fix
    received:datetime
    status:str|None

@dataclass(frozen=True)
class Leg:
    origin:str
    destination:str
    direction:str
    start:datetime
    end:datetime
    available:datetime
    @property
    def seconds(self):return (self.end-self.start).total_seconds()


def qtile(values,q):
    if not values:return None
    xs=sorted(values)
    return round(xs[round((len(xs)-1)*q)],1)


def audit(samples):
    """Attribute gaps only to the last observed stop zone, not the unseen bus."""
    tracks=defaultdict(list)
    for s in samples:tracks[s.fix.vehicle_id].append(s)
    stats=defaultdict(Counter);offsets=defaultdict(list); gaps=defaultdict(list)
    for track in tracks.values():
        prev=None
        for s in sorted(track,key=lambda r:r.fix.timestamp):
            f=s.fix;pos=(f.lat,f.lon)
            stop=min(STOP_COORDS,key=lambda k:distance_m(pos,STOP_COORDS[k]))
            dist=distance_m(pos,STOP_COORDS[stop]);zone=stop if dist<=65 else 'outside_stop_zones'
            stats[zone]['fixes']+=1
            if s.status is None:stats[zone]['missingStatus']+=1
            if s.status=='standing_at_stop':
                offsets[stop].append(dist)
                if dist>65:stats[zone]['standingOutside65m']+=1
            if prev:
                delta=(f.timestamp-prev[0].fix.timestamp).total_seconds();prior=prev[1]
                if delta>0:
                    stats[prior]['intervals']+=1
                    if 45<delta<=1800:
                        stats[prior]['gaps45To1800s']+=1;gaps[prior].append(delta)
                    elif delta>1800:stats[prior]['longBreaksOver30min']+=1
                    elif s.status is None:stats[prior]['nextStatusMissingWithin45s']+=1
            prev=(s,zone)
    return {'byLastObservedZone':{k:{**dict(stats[k]),'gapSecondsP50':qtile(gaps[k],.5),'gapSecondsP90':qtile(gaps[k],.9)} for k in (*STOP_COORDS,'outside_stop_zones')},'nearestStopOffsets':{k:{'standingFixes':len(offsets[k]),'distanceMetersP50':qtile(offsets[k],.5),'distanceMetersP90':qtile(offsets[k],.9),'outside38m':sum(d>38 for d in offsets[k])} for k in STOP_COORDS},'limits':['A gap is attributed to the last observed zone, not a location during the gap. Long breaks separated; no cause or service outage inferred.','Nearest-stop distance is a source geometry diagnostic, not a surveyed stop position.']}


def continuous_legs(samples,max_gap=120):
    """Filter adjacent inferred stop passages to tracks with observed entries
    and no large intervening gap. Receipt time bounds training availability."""
    tracks=defaultdict(list); events=defaultdict(list)
    for s in samples:tracks[s.fix.vehicle_id].append(s)
    for e in gps_passes(s.fix for s in samples):events[e.vehicle_id].append(e)
    legs=[]; exclusions=Counter()
    for bus,track in tracks.items():
        track.sort(key=lambda x:x.fix.timestamp);ts=[s.fix.timestamp for s in track]
        for a,b in zip(events[bus],events[bus][1:]):
            direction=ROUTE_EDGES.get((a.stop_id,b.stop_id));secs=(b.timestamp-a.timestamp).total_seconds()
            if not direction or not 50<=secs<=2700:continue
            i=bisect.bisect_left(ts,a.timestamp);j=bisect.bisect_left(ts,b.timestamp)
            if i<1 or j<=i or j>=len(ts):exclusions['missing_entry']+=1;continue
            # An inferred entrance after a blackout is not a reliable arrival.
            before=track[i-1].fix; prior=track[j-1].fix
            if any(distance_m((f.lat,f.lon),STOP_COORDS[stop])<=38 for f,stop in ((before,a.stop_id),(prior,b.stop_id))):exclusions['uncertain_entry']+=1;continue
            if any((ts[k+1]-ts[k]).total_seconds()>max_gap for k in range(i-1,j)):
                exclusions['gps_gap']+=1;continue
            available=max(max(s.received,s.fix.timestamp) for s in track[i-1:j+1])
            legs.append(Leg(a.stop_id,b.stop_id,direction,a.timestamp,b.timestamp,available))
    return sorted(legs,key=lambda x:x.start),dict(exclusions)


def evaluate(legs):
    """Same-sample chronological comparison at the origin passage. Destination
    is assumed known; this is not a live trip selection or a traffic measure."""
    history=defaultdict(list);rows=[];abstained=0
    for leg in sorted(legs,key=lambda x:x.start):
        key=(leg.origin,leg.destination,leg.direction)
        past=[x for x in history[key] if x.available<leg.start and x.end<leg.start and x.start>=leg.start-timedelta(days=14)]
        history[key].append(leg)
        if len(past)<12 or len({x.start.astimezone(NY).date() for x in past})<3:abstained+=1;continue
        hour=leg.start.astimezone(NY).hour
        near=[x for x in past if min((x.start.astimezone(NY).hour-hour)%24,(hour-x.start.astimezone(NY).hour)%24)<=2]
        baseline=median(x.seconds for x in past)
        use_hour=len(near)>=12 and len({x.start.astimezone(NY).date() for x in near})>=3
        hour_eta=.6*median(x.seconds for x in near)+.4*baseline if use_hour else baseline
        recent=[x.seconds for x in past if leg.start-x.end<=timedelta(minutes=90)]
        use_recent=len(recent)>=3
        recent_eta=.5*median(recent)+.5*hour_eta if use_recent else hour_eta
        rows.append((key,abs(baseline-leg.seconds)/60,abs(hour_eta-leg.seconds)/60,abs(recent_eta-leg.seconds)/60,use_hour,use_recent,leg.start.astimezone(NY).date()))
    def summary(xs):
        if not xs:return {'n':0,'baselineMAEmin':None,'hourMAEmin':None,'hourPlusRecentMAEmin':None}
        return {'n':len(xs),'baselineMAEmin':round(mean(x[1] for x in xs),3),'hourMAEmin':round(mean(x[2] for x in xs),3),'hourPlusRecentMAEmin':round(mean(x[3] for x in xs),3),'hourUsed':sum(x[4] for x in xs),'recentUsed':sum(x[5] for x in xs),'localDays':len({x[6] for x in xs})}
    return {'overall':summary(rows),'abstained':abstained,'byLeg':{a+'->'+b:summary([x for x in rows if x[0]==(a,b,d)]) for (a,b),d in ROUTE_EDGES.items()},'hourEligibleSubset':summary([x for x in rows if x[4]]),'recentEligibleSubset':summary([x for x in rows if x[5]])}


def report(dbpath,now):
    with closing(sqlite3.connect(f'file:{dbpath}?mode=ro',uri=True)) as db:
        rows=db.execute('''SELECT o.vehicle_id,o.observed_at,o.received_at,o.latitude,o.longitude,v.reported_status FROM observations o LEFT JOIN vehicle_context_history v ON o.source=v.source AND o.vehicle_id=v.vehicle_id AND o.observed_at=v.observed_at WHERE o.source='student_public' ORDER BY o.vehicle_id,o.observed_at''').fetchall()
    samples=[]
    for bus,at,received,lat,lon,status in rows:
        at=datetime.fromisoformat(at);received=datetime.fromisoformat(received)
        if at.tzinfo and received.tzinfo and at<=now and received<=now:samples.append(Sample(Fix(bus,at,lat,lon),received,status))
    legs,excluded=continuous_legs(samples)
    return {'status':'PRIVATE_CORRIDOR_RESEARCH','publicPredictionAllowed':False,'continuity':audit(samples),'continuousLegs':len(legs),'excludedLegs':excluded,'walkForward':evaluate(legs),'limits':['Travel time includes stop dwell and is not measured traffic.','Known destination assumed at origin; retrospective inferred GPS passages, not physical arrivals.','Only earlier completed and received trips train estimates; fallback to baseline if hour/recent evidence is insufficient.','No coordinates or geometry changes, no new external source.']}
