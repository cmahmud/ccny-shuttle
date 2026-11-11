"""Offline paired accuracy comparison: CCNY shadow ETAs vs student tracker.

No public API endpoint. Reports are EMPTY until source-provided reference
forecasts and our shadow predictions refer to the same vehicle, stop and
prediction horizon. The observed outcome is an *inferred GPS passage*, not
independent confirmation of a passenger pickup.
"""
from __future__ import annotations

import argparse
import collections
import bisect
from datetime import datetime,timedelta
import json
import sqlite3
import statistics

from .eta_research import Pass,gps_passes,read_fixes
from .eta_shadow import METHOD_MEDIAN,METHOD_SPEED

HORIZONS=(3,5,10)
MAX_PAIR_TIMESTAMP_DIFFERENCE_SECONDS=75


def timeparse(value:str)->datetime:
    result=datetime.fromisoformat(value.replace("Z","+00:00"))
    if result.tzinfo is None:raise ValueError("Naive timestamp")
    return result


def read_shadow_rows(dbpath:str)->list[dict]:
    with sqlite3.connect(f"file:{dbpath}?mode=ro",uri=True) as db:
        try:
            rows=db.execute(
                """SELECT vehicle_id,stop_id,direction,generated_at,
                  source_observed_at,model,predicted_arrival_at,
                  display_enabled FROM shadow_forecasts
                  WHERE source='student_public'
                  ORDER BY generated_at"""
            ).fetchall()
        except sqlite3.OperationalError:return []
    result=[]
    for vehicle,stop,direction,generated,observed,method,eta,enabled in rows:
        try:
            at=timeparse(generated)
            fix=timeparse(observed)
            arrival=timeparse(eta)
            if not (fix<=at and abs((at-fix).total_seconds())<=35):
                continue
            result.append({
                "vehicle":vehicle,"stop":stop,"direction":direction,
                "at":at,"observedAt":fix,"eta":arrival,
                "method":method,"enabled":bool(enabled)
            })
        except (ValueError,TypeError):continue
    return result


def read_student_rows(dbpath:str)->list[dict]:
    with sqlite3.connect(f"file:{dbpath}?mode=ro",uri=True) as db:
        try:
            rows=db.execute(
                """SELECT vehicle_id,stop_id,direction,
                  forecast_generated_at,arrival_at,source_enabled
                  FROM forecast_comparisons WHERE source='student_public'
                  ORDER BY forecast_generated_at"""
            ).fetchall()
        except sqlite3.OperationalError:return []
    result=[]
    for vehicle,stop,direction,generated,eta,enabled in rows:
        try:
            result.append({
                "vehicle":vehicle,"stop":stop,"direction":direction,
                "at":timeparse(generated),"eta":timeparse(eta),
                "enabled":bool(enabled)
            })
        except (ValueError,TypeError):continue
    return result


def summaries(rows:list[dict])->dict:
    if not rows:return {"samples":0,"MAEminutes":None,"medianErrorMinutes":None}
    errors=[r["absErrorMinutes"] for r in rows]
    return {
        "samples":len(rows),
        "MAEminutes":round(statistics.mean(errors),3),
        "medianErrorMinutes":round(statistics.median(errors),3),
        "P90errorMinutes":round(sorted(errors)[round((len(errors)-1)*.9)],3),
    }


def evaluate_pairs(
    events:list[Pass],shadow:list[dict],student:list[dict],
    horizons:tuple[int,...]=HORIZONS,window_seconds:int=75
)->dict:
    by_shadow:dict[tuple,list[dict]]=collections.defaultdict(list)
    by_student:dict[tuple,list[dict]]=collections.defaultdict(list)
    for row in shadow:
        by_shadow[row["vehicle"],row["stop"]].append(row)
    for row in student:
        by_student[row["vehicle"],row["stop"],row["direction"]].append(row)
    comparisons=[]
    shadow_eligible=collections.Counter()
    by_event:dict[tuple,list[datetime]]=collections.defaultdict(list)
    for event in events:
        by_event[event.vehicle_id,event.stop_id].append(event.timestamp)
    for ts in by_event.values():
        ts.sort()
    for event in events:
        for horizon in horizons:
            desired=event.timestamp-timedelta(minutes=horizon)
            candidates=[
                row for row in by_shadow[event.vehicle_id,event.stop_id]
                if abs((row["at"]-desired).total_seconds())<=window_seconds
                and row["observedAt"]<=row["at"]<=event.timestamp
                and row["method"] in (METHOD_MEDIAN,METHOD_SPEED)
            ]
            for method in (METHOD_MEDIAN,METHOD_SPEED):
                possibilities=[r for r in candidates if r["method"]==method]
                if not possibilities:continue
                own=min(possibilities,
                        key=lambda r:abs((r["at"]-desired).total_seconds()))
                shadow_eligible[method]+=1
                others=[
                    r for r in by_student[event.vehicle_id,event.stop_id,
                                           own["direction"]]
                    if abs((r["at"]-own["at"]).total_seconds())
                       <=MAX_PAIR_TIMESTAMP_DIFFERENCE_SECONDS
                    and r["at"]<=event.timestamp
                ]
                if not others:continue
                student_choice=min(others,key=lambda r:abs(
                    (r["at"]-own["at"]).total_seconds()))
                # There must not be another GPS pass of this same bus and stop
                # near the prediction. This guards against matching the next
                # loop's forecast to the previous loop's actual arrival.
                event_times=by_event[event.vehicle_id,event.stop_id]
                nearby_index=bisect.bisect_left(event_times,event.timestamp)
                earlier=event_times[nearby_index-1] if nearby_index>0 else None
                later=event_times[nearby_index+1] if nearby_index+1<len(event_times) else None
                if ((earlier is not None and
                     (event.timestamp-earlier).total_seconds()<1800) or
                    (later is not None and
                     (later-event.timestamp).total_seconds()<1800)):
                    continue
                own_err=abs((own["eta"]-event.timestamp).total_seconds())/60
                student_err=abs((student_choice["eta"]-event.timestamp).total_seconds())/60
                comparisons.append({
                    "method":method,"horizon":horizon,
                    "studentPredictionEnabled":student_choice["enabled"],
                    "shadowAbsErrorMinutes":own_err,
                    "studentAbsErrorMinutes":student_err,
                    "shadowWins":own_err<student_err,
                    "sameTimeToleranceSeconds":round(abs(
                        (own["at"]-student_choice["at"]).total_seconds()),1),
                    "vehicle":event.vehicle_id,"stop":event.stop_id,
                    "actualPass":event.timestamp.isoformat(),
                })
    output={}
    for method in (METHOD_MEDIAN,METHOD_SPEED):
        subset=[x for x in comparisons if x["method"]==method]
        per_horizon={}
        for h in horizons:
            paired=[x for x in subset if x["horizon"]==h]
            per_horizon[str(h)]={
                "pairedSamples":len(paired),
                "shadowMAEminutes":round(statistics.mean(
                    x["shadowAbsErrorMinutes"] for x in paired),3) if paired else None,
                "studentMAEminutes":round(statistics.mean(
                    x["studentAbsErrorMinutes"] for x in paired),3) if paired else None,
                "sourcePredictionsEnabled":sum(x["studentPredictionEnabled"]
                                               for x in paired)
            }
        output[method]={
            "shadowEligible":shadow_eligible[method],
            "pairedSamples":len(subset),
            "shadowMAEminutes":round(statistics.mean(
                x["shadowAbsErrorMinutes"] for x in subset),3) if subset else None,
            "studentMAEminutes":round(statistics.mean(
                x["studentAbsErrorMinutes"] for x in subset),3) if subset else None,
            "shadowWinRate":round(statistics.mean(
                x["shadowWins"] for x in subset),3) if subset else None,
            "byHorizon":per_horizon,
        }
    return {
        "status":"No claim of superiority; matched GPS-proxy outcomes only",
        "passageEvents":len(events),
        "shadowStoredForecasts":len(shadow),
        "studentStoredForecasts":len(student),
        "sameForecastTimeToleranceSeconds":MAX_PAIR_TIMESTAMP_DIFFERENCE_SECONDS,
        "paired":output,
        "publicETAReleaseGateMet":False,
        "limits":[
            "Events are GPS-geofence passages, not staff-confirmed boardings.",
            "Sparse data and a partial upstream forecast source can prevent meaningful comparisons.",
            "Models may share the same student-origin GPS feed; this is not source independence.",
            "No live GPS uncertainty calibration or service-delay model is yet validated."
        ],
    }


def report(gps_db:str,shadow_db:str)->dict:
    events=gps_passes(read_fixes(gps_db))
    return evaluate_pairs(events,read_shadow_rows(shadow_db),
                          read_student_rows(gps_db))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--db",required=True)
    parser.add_argument("--shadow-db",required=True)
    args=parser.parse_args()
    print(json.dumps(report(args.db,args.shadow_db),indent=2))


if __name__=="__main__":main()
