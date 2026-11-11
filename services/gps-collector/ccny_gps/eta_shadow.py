"""Experimental, local-only CCNY shuttle ETA shadow engine.

Never serves forecasts to students. Uses existing source-timestamped GPS and
source-attributed route shapes. Stores experimental forecasts separately so
they can be compared against future, GPS-inferred stop passages.
"""
from __future__ import annotations

import argparse
import collections
import json
import logging
import math
import os
from dataclasses import asdict,dataclass
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sqlite3
import statistics
import time

from .eta_research import Fix,Segment,read_fixes,gps_passes,observed_segments
from .route_progress import RouteCatalog
from .status import get_status
from .storage import ObservationStore

LOG=logging.getLogger("ccny-eta-shadow")
METHOD_MEDIAN="route_fraction_median_v1"
METHOD_SPEED="speed_blend_experimental_v1"
SHADOW_SCHEMA="""
CREATE TABLE IF NOT EXISTS shadow_forecasts(
 id INTEGER PRIMARY KEY,
 source TEXT NOT NULL,
 vehicle_id TEXT NOT NULL,
 direction TEXT NOT NULL,
 stop_id TEXT NOT NULL,
 source_observed_at TEXT NOT NULL,
 generated_at TEXT NOT NULL,
 model TEXT NOT NULL,
 predicted_arrival_at TEXT NOT NULL,
 earliest_at TEXT NOT NULL,
 latest_at TEXT NOT NULL,
 training_samples INTEGER NOT NULL,
 training_days INTEGER NOT NULL,
 remaining_route_m REAL NOT NULL,
 offroute_m REAL NOT NULL,
 gps_age_s REAL NOT NULL,
 recent_speed_mps REAL,
 display_enabled INTEGER NOT NULL DEFAULT 0,
 UNIQUE(source,vehicle_id,stop_id,source_observed_at,model)
);
CREATE INDEX IF NOT EXISTS shadow_forecast_passage_lookup
  ON shadow_forecasts(vehicle_id,stop_id,generated_at);
"""

@dataclass(frozen=True)
class Prediction:
    source:str
    vehicle_id:str
    direction:str
    stop_id:str
    source_observed_at:datetime
    generated_at:datetime
    model:str
    predicted_arrival_at:datetime
    earliest_at:datetime
    latest_at:datetime
    training_samples:int
    training_days:int
    remaining_route_m:float
    offroute_m:float
    gps_age_s:float
    recent_speed_mps:float|None


def active_segments_before(segments:list[Segment],asof:datetime,
                           origin:str,destination:str)->list[Segment]:
    return [s for s in segments if s.origin==origin and s.destination==destination
            and s.timestamp+timedelta(seconds=s.seconds)<asof]


def _quantile(values:list[float],fraction:float)->float:
    ordered=sorted(values)
    if not ordered:raise ValueError("Cannot quantile empty samples")
    return ordered[min(len(ordered)-1,max(0,round((len(ordered)-1)*fraction)))]


def speed_from_recent(fixes:list[Fix],direction:str,
                      catalog:RouteCatalog,asof:datetime)->float|None:
    points=[]
    for fix in sorted(fixes,key=lambda x:x.timestamp,reverse=True)[:8]:
        age=(asof-fix.timestamp).total_seconds()
        if age<0 or age>85:continue
        matched=catalog.match(fix.lat,fix.lon,direction=direction,max_distance=50)
        if matched is None:continue
        points.append((fix.timestamp,matched.progress_m))
    if len(points)<2:return None
    points.sort()
    # Derive a route-progress speed rather than raw GPS point-to-point jitter.
    start,finish=points[0],points[-1]
    duration=(finish[0]-start[0]).total_seconds()
    distance=finish[1]-start[1]
    if not 12<=duration<=85 or distance<20:return None
    speed=distance/duration
    if not .6<=speed<=15:return None
    return round(speed,3)


def make_predictions(
    fix:Fix, direction:str, reported_status:str|None,
    next_stop_id:str|None, segments:list[Segment],
    catalog:RouteCatalog, now:datetime,
    recent_fixes:list[Fix]|None=None, source:str="student_public",
    min_samples:int=10,
)->list[Prediction]:
    if fix.timestamp.tzinfo is None or now.tzinfo is None:
        raise ValueError("Timestamps must be timezone aware")
    age=(now-fix.timestamp).total_seconds()
    if not 0<=age<=30 or reported_status!="moving" or direction not in ("NB","SB"):
        return []
    match=catalog.match(fix.lat,fix.lon,direction)
    if match is None:return []
    leg=catalog.next_leg(direction,match.progress_m)
    if leg is None:return []
    origin,stop,fraction,remaining=leg
    # No predictions for departure-at-stop cases, stale source statuses or
    # cases where we contradict the source's explicitly reported next stop.
    if fraction<.025 or remaining<18:return []
    if next_stop_id and next_stop_id!=stop:return []
    relevant=active_segments_before(segments,fix.timestamp,origin,stop)
    if len(relevant)<min_samples:return []
    sample=[s.seconds for s in relevant]
    days=len({s.timestamp.date() for s in relevant})
    nominal=statistics.median(sample)*fraction
    # Range comes from HISTORIC between-stop variation plus time uncertainty;
    # it is not a calibrated prediction interval.
    lo=max(10.0,_quantile(sample,.1)*fraction-15)
    hi=max(nominal+15.0,_quantile(sample,.9)*fraction+30)
    if hi<lo:hi=lo+30
    measured=speed_from_recent(recent_fixes or [],direction,catalog,
                               fix.timestamp)
    def output(seconds:float,method:str):
        arrival=fix.timestamp+timedelta(seconds=seconds)
        if arrival<=now-timedelta(seconds=10):return None
        return Prediction(
            source,fix.vehicle_id,direction,stop,fix.timestamp,now,method,
            arrival,fix.timestamp+timedelta(seconds=lo),
            fix.timestamp+timedelta(seconds=hi),
            len(relevant),days,round(remaining,1),
            round(match.offroute_m,1),round(age,1),measured
        )
    result=[output(nominal,METHOD_MEDIAN)]
    if measured is not None:
        # Speed proxy is an EXPERIMENT, not an assured live traffic signal:
        # route GPS speed fluctuates with lights, stop dwell and GPS sampling.
        instant=remaining/measured
        bounded=max(.60*nominal,min(1.55*nominal,instant))
        result.append(output(.75*nominal+.25*bounded,METHOD_SPEED))
    return [x for x in result if x]


class ShadowStore:
    def __init__(self,path:str):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.conn=sqlite3.connect(self.path,timeout=5)
        # This database contains bus-level experimental forecasts. The
        # worker has UMASK=0077, but one-off CLI initialization may not.
        os.chmod(self.path,0o600)
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(SHADOW_SCHEMA)

    def record(self,predictions:list[Prediction])->int:
        if not predictions:return 0
        before=self.conn.total_changes
        with self.conn:
            for p in predictions:
                self.conn.execute(
                    """INSERT OR IGNORE INTO shadow_forecasts (
                      source,vehicle_id,direction,stop_id,source_observed_at,
                      generated_at,model,predicted_arrival_at,earliest_at,
                      latest_at,training_samples,training_days,
                      remaining_route_m,offroute_m,gps_age_s,recent_speed_mps,
                      display_enabled)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                    (p.source,p.vehicle_id,p.direction,p.stop_id,
                     p.source_observed_at.isoformat(),p.generated_at.isoformat(),
                     p.model,p.predicted_arrival_at.isoformat(),
                     p.earliest_at.isoformat(),p.latest_at.isoformat(),
                     p.training_samples,p.training_days,
                     p.remaining_route_m,p.offroute_m,p.gps_age_s,
                     p.recent_speed_mps)
                )
        return self.conn.total_changes-before

    def status(self):
        total=self.conn.execute("SELECT count(*) FROM shadow_forecasts").fetchone()[0]
        variants=self.conn.execute(
            "SELECT model,count(*) FROM shadow_forecasts GROUP BY model"
        ).fetchall()
        return {"shadowForecasts":total,"models":dict(variants),
                "publiclyVisible":False}

    def close(self):self.conn.close()


def snapshot_forecasts(source_db:str,catalog:RouteCatalog,
                       now:datetime|None=None)->list[Prediction]:
    now=now or datetime.now(timezone.utc)
    store=ObservationStore(source_db)
    try:
        snapshot=get_status(store,now)
        # Public GPS stays the only current source; original Samsara data is
        # never conflated with a third-party position and authorization.
        if snapshot.get("source")!="student_public" or not (
            snapshot.get("sourceState")=="live" and
            snapshot.get("transportState")=="healthy"
        ):
            return []
        moving=[v for v in snapshot["vehicles"]
                if v.get("freshness")=="fresh" and
                v.get("reportedStatus")=="moving" and
                v.get("reportedDirection") in ("NB","SB")]
        if not moving:return []
        # Every training segment must have completed before the source fix.
        raw=read_fixes(source_db,"student_public")
        segments=observed_segments(gps_passes(raw))
        results=[]
        for bus in moving:
            fix=Fix(bus["vehicleId"],datetime.fromisoformat(
                bus["observedAt"].replace("Z","+00:00")),
                bus["latitude"],bus["longitude"])
            recent=[
                Fix(fix.vehicle_id,x.observed_at,x.latitude,x.longitude)
                for x in store.recent_observations("student_public",
                                                    fix.vehicle_id,limit=8)
            ]
            results.extend(make_predictions(
                fix,bus["reportedDirection"],bus["reportedStatus"],
                bus.get("reportedNextStopId"),segments,catalog,now,recent))
        return results
    finally:store.close()


def main():
    parser=argparse.ArgumentParser(description="Private experimental ETA shadow engine")
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once",action="store_true")
    mode.add_argument("--loop",action="store_true")
    mode.add_argument("--status",action="store_true")
    parser.add_argument("--db",default="/var/lib/ccny-shuttle/gps.sqlite3")
    parser.add_argument("--shadow-db",default="/var/lib/ccny-shuttle/eta-shadow.sqlite3")
    parser.add_argument("--interval",type=int,default=20)
    args=parser.parse_args()
    if not 15<=args.interval<=600:
        parser.error("interval must be in range 15..600 seconds")
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    shadow=ShadowStore(args.shadow_db)
    try:
        if args.status:
            print(json.dumps(shadow.status(),indent=2))
            return 0
        routes=RouteCatalog.load()
        while True:
            try:
                pending=snapshot_forecasts(args.db,routes)
                stored=shadow.record(pending)
                if pending or args.once:
                    print(json.dumps({"evaluated":len(pending),
                                      "newShadowForecasts":stored,
                                      "publiclyVisible":False,
                                      "state":shadow.status()},default=str),flush=True)
            except (OSError,sqlite3.Error,ValueError) as exc:
                LOG.warning("Shadow ETA tick error: %s",type(exc).__name__)
                if args.once:raise
            if args.once:return 0
            time.sleep(args.interval)
    finally:shadow.close()


if __name__=="__main__":
    raise SystemExit(main())
