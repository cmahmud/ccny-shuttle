"""Leakage-controlled historical replay for the *experimental* ETA shadow model.

Old GPS data lack per-fix vehicle context. This replay therefore uses route
direction and target stop learned from the subsequent stop pair. That is
an ORACLE direction assumption, and metrics cannot be reported as live ETA
performance or a fair head-to-head against the student tracker.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import json
import math
from datetime import datetime,timedelta
import statistics

from .eta_research import Fix,read_fixes,gps_passes,observed_segments
from .eta_shadow import make_predictions,METHOD_MEDIAN,METHOD_SPEED
from .route_progress import RouteCatalog


def backtest(dbpath:str,horizons:tuple[int,...]=(3,5,10),
             tolerance_s:float=70)->dict:
    fixes=read_fixes(dbpath)
    catalog=RouteCatalog.load()
    segments=observed_segments(gps_passes(fixes))
    history_by_vehicle:dict[str,list[Fix]]=collections.defaultdict(list)
    for fix in fixes:history_by_vehicle[fix.vehicle_id].append(fix)
    for track in history_by_vehicle.values():
        track.sort(key=lambda f:f.timestamp)
    timestamps_by_vehicle={
        name:[fix.timestamp for fix in track]
        for name,track in history_by_vehicle.items()
    }
    trials=[]
    included=collections.Counter()
    for segment in segments:
        if segment.origin not in catalog.stop_progress.get(segment.direction,{}) or (
            segment.destination not in catalog.stop_progress.get(segment.direction,{})
        ):continue
        # Candidate fixes lie after the previous stop pass; the final pass is
        # ground truth for evaluation only. Never use its timestamp to predict.
        track=history_by_vehicle[segment.vehicle_id]
        times=timestamps_by_vehicle[segment.vehicle_id]
        end=segment.timestamp+timedelta(seconds=segment.seconds)
        begin=bisect.bisect_right(times,segment.timestamp)
        finish=bisect.bisect_left(times,end)
        if finish<=begin:continue
        for horizon in horizons:
            target=end-timedelta(minutes=horizon)
            options=[
                f for f in track[begin:finish]
                if abs((f.timestamp-target).total_seconds())<=tolerance_s
            ]
            if not options:continue
            candidate=min(options,key=lambda f:abs((f.timestamp-target).total_seconds()))
            i=bisect.bisect_right(times,candidate.timestamp)
            recent=track[max(0,i-8):i]
            forecasts=make_predictions(
                candidate,segment.direction,"moving",segment.destination,
                segments,catalog,candidate.timestamp,recent)
            if not forecasts:continue
            included[horizon]+=1
            for result in forecasts:
                err=(result.predicted_arrival_at-end).total_seconds()/60
                trials.append({
                    "direction":segment.direction,
                    "leg":segment.origin+"->"+segment.destination,
                    "stop":segment.destination,
                    "method":result.model,
                    "horizon":horizon,
                    "errorMin":round(err,4),
                    "absErrorMin":abs(err),
                    "historyDays":result.training_days,
                    "trainingSamples":result.training_samples,
                    "offrouteM":result.offroute_m,
                    "sourceFixTime":candidate.timestamp.isoformat(),
                    "eventTime":end.isoformat(),
                    "vehicleId":segment.vehicle_id,
                    "withinShadowRange":result.earliest_at<=end<=result.latest_at,
                })
    metrics={}
    for method in (METHOD_MEDIAN,METHOD_SPEED):
        rows=[r for r in trials if r["method"]==method]
        if not rows:
            metrics[method]={"n":0,"maeMin":None}
            continue
        errors=[r["absErrorMin"] for r in rows]
        metrics[method]={
            "n":len(rows),
            "maeMin":round(statistics.mean(errors),3),
            "medianAbsoluteErrorMin":round(statistics.median(errors),3),
            "p90AbsoluteErrorMin":round(sorted(errors)[round((len(errors)-1)*.9)],3),
            "meanBiasMin":round(statistics.mean(r["errorMin"] for r in rows),3),
            "historicalRangeCoverage":round(statistics.mean(
                1. if r["withinShadowRange"] else 0. for r in rows),3),
            "byHorizon":{
                str(h):{
                    "n":len(z),
                    "maeMin":round(statistics.mean(r["absErrorMin"] for r in z),3)
                } for h in horizons if (z:=[r for r in rows if r["horizon"]==h])
            }
        }
    # Only compare methods on the *same* stop event and prediction timestamp.
    speed={(r["vehicleId"],r["eventTime"],r["sourceFixTime"]):r
           for r in trials if r["method"]==METHOD_SPEED}
    common=[
        (r,speed[key]) for r in trials if r["method"]==METHOD_MEDIAN
        if (key:=(r["vehicleId"],r["eventTime"],r["sourceFixTime"])) in speed
    ]
    comparison={
        "pairedSamples":len(common),
        "medianMAEOnPairedMin":round(statistics.mean(
            p[0]["absErrorMin"] for p in common),3) if common else None,
        "speedBlendMAEOnPairedMin":round(statistics.mean(
            p[1]["absErrorMin"] for p in common),3) if common else None,
    }
    return {
        "status":"RESEARCH ONLY - not live ETA validation",
        "limitations":[
            "The replay infers direction and next stop from the FUTURE observed trip; not source metadata available at prediction time.",
            "Geofence arrivals are GPS proxies, not audited boarding/arrival timestamps.",
            "The period is short and may not represent holidays, closures, outages, or route changes.",
            "Selecting fixes near true event time uses hindsight only for evaluation sampling.",
            "Shadow uncertainties use historical trip distributions, not calibrated predictive confidence intervals.",
        ],
        "fixes":len(fixes),"passagePairs":len(segments),
        "horizonsMinutes":list(horizons),
        "eligibleEventsByHorizon":dict(sorted(included.items())),
        "metrics":metrics,
        "pairedComparison":comparison,
        "experimentalCandidate":"not_selected",
        "publicETAsEnabled":False,
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--db",required=True)
    args=parser.parse_args()
    print(json.dumps(backtest(args.db),indent=2))


if __name__=="__main__":main()
