"""Offline GPS pass-event and travel-time research.

A pass event is a position within a geo-fence, NOT a confirmed passenger
boarding or observed stop dwell. Kept strictly separate from public ETAs.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sqlite3
import statistics
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

STOP_COORDS = {
    "125": (40.811144, -73.953374),
    "135": (40.81833995298843, -73.95099996354817),
    "marshak": (40.81992752226471, -73.9496900738688),
    "145": (40.82393, -73.94458),
}
ROUTE_EDGES = {
    ("125", "135"): "NB",
    ("125", "marshak"): "NB",
    ("135", "marshak"): "NB",
    ("135", "145"): "NB",
    ("marshak", "145"): "NB",
    ("145", "marshak"): "SB",
    ("145", "125"): "SB",
    ("marshak", "125"): "SB",
}

@dataclass(frozen=True)
class Fix:
    vehicle_id: str
    timestamp: datetime
    lat: float
    lon: float

@dataclass(frozen=True)
class Pass:
    vehicle_id: str
    stop_id: str
    timestamp: datetime
    closest_m: float
    fixes: int

@dataclass(frozen=True)
class Segment:
    vehicle_id: str
    origin: str
    destination: str
    direction: str
    seconds: float
    timestamp: datetime


def distance_m(a: tuple[float,float], b: tuple[float,float]) -> float:
    return 111195 * math.hypot(
        a[0]-b[0], (a[1]-b[1])*math.cos(math.radians((a[0]+b[0])/2))
    )


def gps_passes(fixes: Iterable[Fix], enter_m: float = 38,
               exit_m: float = 65, min_repeat_s: float = 240) -> list[Pass]:
    """Detect first entrance into stop zones using exit hysteresis.

    A new pass cannot be created by GPS jitter or prolonged idling inside
    the stop geofence; a driver must have left or a long gap occurred.
    """
    by_bus: dict[str,list[Fix]] = collections.defaultdict(list)
    for fix in fixes:
        if fix.timestamp.tzinfo is None:
            raise ValueError("Fix timestamps must be timezone aware")
        if not (40.78 <= fix.lat <= 40.86 and -74.02 <= fix.lon <= -73.88):
            continue
        by_bus[fix.vehicle_id].append(fix)
    result: list[Pass] = []
    for vehicle_id, track in by_bus.items():
        active = {stop: False for stop in STOP_COORDS}
        previous = None
        most_recent: dict[str,datetime] = {}
        for fix in sorted(track, key=lambda f:f.timestamp):
            if previous and (fix.timestamp-previous).total_seconds()>300:
                active = {stop:False for stop in STOP_COORDS}
            previous = fix.timestamp
            for stop,coords in STOP_COORDS.items():
                distance=distance_m((fix.lat,fix.lon),coords)
                if distance >= exit_m:
                    active[stop]=False
                    continue
                if distance > enter_m:
                    continue
                if active[stop]:
                    continue
                active[stop]=True
                last=most_recent.get(stop)
                if last and (fix.timestamp-last).total_seconds()<min_repeat_s:
                    continue
                most_recent[stop]=fix.timestamp
                result.append(Pass(vehicle_id,stop,fix.timestamp,round(distance,1),1))
    return sorted(result, key=lambda r:(r.vehicle_id,r.timestamp))


def observed_segments(events: Iterable[Pass]) -> list[Segment]:
    by_bus:dict[str,list[Pass]] = collections.defaultdict(list)
    for event in events:by_bus[event.vehicle_id].append(event)
    result=[]
    for bus,items in by_bus.items():
        ordered=sorted(items,key=lambda x:x.timestamp)
        for a,b in zip(ordered,ordered[1:]):
            direction=ROUTE_EDGES.get((a.stop_id,b.stop_id))
            if not direction:continue
            sec=(b.timestamp-a.timestamp).total_seconds()
            if 50<=sec<=2700 and a.closest_m<=38 and b.closest_m<=38:
                result.append(Segment(bus,a.stop_id,b.stop_id,direction,sec,a.timestamp))
    return sorted(result,key=lambda x:x.timestamp)


def historical_baseline(
    segments:list[Segment], min_train:int=5,
    method:str="median"
) -> list[dict]:
    """Strictly chronological training; no future information leakage."""
    if method not in ("median", "hour_conditioned"):
        raise ValueError("Unknown historical ETA baseline")
    ordered=sorted(segments,key=lambda x:x.timestamp)
    history:dict[tuple[str,str],list[Segment]]=collections.defaultdict(list)
    trials=[]
    for s in ordered:
        key=(s.origin,s.destination)
        earlier=history[key]
        if len(earlier)>=min_train:
            prediction=statistics.median([x.seconds for x in earlier])
            if method=="hour_conditioned":
                # A *historical time-of-day traffic proxy*, not real-time
                # Google/Waze traffic. Leave-one-forward out by construction.
                hour=s.timestamp.astimezone(ZoneInfo("America/New_York")).hour
                near=[x.seconds for x in earlier if (
                    (abs(x.timestamp.astimezone(
                        ZoneInfo("America/New_York")).hour-hour) + 12) % 24)-12
                    in (-3,-2,-1,0,1,2,3)]
                if len(near)>=7:
                    prediction=round(.6*statistics.median(near)+.4*prediction,1)
            trials.append({
                "route":s.origin+"->"+s.destination,
                "observedSeconds":s.seconds,
                "predictedSeconds":prediction,
                "absoluteErrorMinutes":round(abs(prediction-s.seconds)/60,2),
                "trainingCount":len(earlier),
                "day":s.timestamp.date().isoformat(),
            })
        earlier.append(s)
    return trials


def read_fixes(dbpath:str, source:str="student_public")->list[Fix]:
    with sqlite3.connect(f"file:{dbpath}?mode=ro",uri=True) as conn:
        rows=conn.execute(
            """SELECT vehicle_id,observed_at,latitude,longitude
            FROM observations WHERE source=? ORDER BY vehicle_id,observed_at""",
            (source,)
        ).fetchall()
    return [Fix(bus,datetime.fromisoformat(time),lat,lon)
            for bus,time,lat,lon in rows]


def student_forecast_reference(
    dbpath:str, events:list[Pass], horizon_minutes:int=10
) -> dict:
    """Evaluate source predictions near a fixed forecast horizon.

    Select at most one snapshot per bus/stop pass, avoiding the inflated
    confidence of evaluating a forecast every 30 seconds for one bus trip.
    The target is a GPS geofence passage, NOT verified passenger boarding.
    """
    with sqlite3.connect(f"file:{dbpath}?mode=ro",uri=True) as conn:
        try:
            rows=conn.execute(
                """SELECT stop_id,vehicle_id,forecast_generated_at,arrival_at,
                  source_enabled FROM forecast_comparisons
                  ORDER BY forecast_generated_at"""
            ).fetchall()
        except sqlite3.OperationalError:
            return {"samples":0,"meanAbsoluteErrorMinutes":None,
                    "caveat":"Forecast comparison table not initialized"}
    records:dict[tuple[str,str],list[tuple]]=collections.defaultdict(list)
    for stop,vehicle,generated,arrival,enabled in rows:
        try:
            ts=datetime.fromisoformat(generated)
            predicted=datetime.fromisoformat(arrival)
            if ts.tzinfo is None or predicted.tzinfo is None:
                continue
            records[(vehicle,stop)].append((ts,predicted,bool(enabled)))
        except ValueError:
            continue
    errors=[]
    matched_live=0
    target=horizon_minutes*60
    for event in events:
        eligible=[]
        for forecast_at, arrival, enabled in records[(event.vehicle_id,event.stop_id)]:
            time_to_pass=(event.timestamp-forecast_at).total_seconds()
            if not target-120 <= time_to_pass <= target+120:
                continue
            # Prevent a forecast for another shuttle loop being matched to
            # the wrong observed pass event.
            if abs((event.timestamp-arrival).total_seconds())>1800:
                continue
            eligible.append((abs(time_to_pass-target),forecast_at,arrival,enabled))
        if not eligible:continue
        _,_,predicted,enabled=min(eligible,key=lambda x:(x[0],x[1]))
        matched_live += int(enabled)
        errors.append(abs((predicted-event.timestamp).total_seconds())/60)
    return {
        "samples":len(errors),
        "referencePredictionsEnabledCount":matched_live,
        "meanAbsoluteErrorMinutes":round(statistics.mean(errors),2) if errors else None,
        "evaluatedHorizonMinutes":horizon_minutes,
        "caveat":"Reference forecasts versus GPS-inferred geofence passages; not real boarding events",
    }


def report(dbpath:str)->dict:
    fixes=read_fixes(dbpath)
    events=gps_passes(fixes)
    segments=observed_segments(events)
    backtest=historical_baseline(segments,min_train=5)
    conditioned=historical_baseline(segments,min_train=5,method="hour_conditioned")
    stats={}
    groups=collections.defaultdict(list)
    for s in segments:groups[s.origin+"->"+s.destination].append(s.seconds/60)
    for edge,durations in sorted(groups.items()):
        stats[edge]={"samples":len(durations),
            "medianMinutes":round(statistics.median(durations),1),
            "p10Minutes":round(sorted(durations)[max(0,int(len(durations)*.1))],1),
            "p90Minutes":round(sorted(durations)[min(len(durations)-1,int(len(durations)*.9))],1)}
    trials_by_edge=collections.Counter(r["route"] for r in backtest)
    return {
        "notice":"GPS-inferred geofence passages only; not verified passenger boarding events.",
        "observations":len(fixes),"passEvents":len(events),
        "segmentSamples":len(segments),"routeSegments":stats,
        "walkForwardEvaluations":len(backtest),
        "meanAbsoluteErrorMinutes":round(statistics.mean(
            r["absoluteErrorMinutes"] for r in backtest),2) if backtest else None,
        "hourConditionedMAEMinutes":round(statistics.mean(
            r["absoluteErrorMinutes"] for r in conditioned),2) if conditioned else None,
        "backtestSamplesBySegment":dict(trials_by_edge),
        "trainingDates":sorted(set(f.timestamp.date().isoformat() for f in fixes)),
        "studentForecastReference":student_forecast_reference(dbpath,events),
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--db",required=True)
    args=ap.parse_args()
    print(json.dumps(report(args.db),indent=2))


if __name__=="__main__":main()
