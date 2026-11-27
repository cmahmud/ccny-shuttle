"""Periodic PRIVATE ETA accuracy report (shadow-only, no UI publishing).

Writes a small aggregate report with no vehicle coordinates or identifiers.
Requires independently verified source forecasts, service-day diversity, and
manual audit before the UI is allowed to display any ETA.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from .eta_compare import report as paired_report
from .eta_readiness import diagnose
from .eta_shadow import METHOD_MEDIAN,METHOD_SPEED
from .eta_shadow_backtest import backtest
from .source_reliability import report as reliability_report
from .eta_research import read_fixes
from .eta_validation_audit import geofence_sensitivity
from .eta_dwell import report as dwell_report
from .eta_corridor_research import report as corridor_report


def compile_report(source_db:str,shadow_db:str,now:datetime|None=None)->dict:
    now=now or datetime.now(timezone.utc)
    replay=backtest(source_db)
    paired=paired_report(source_db,shadow_db,now)
    collection_health=diagnose(source_db,shadow_db,now)
    source_reliability=reliability_report(source_db,now)
    median=paired["paired"][METHOD_MEDIAN]
    # Hard publication gate: this script never changes the website and never
    # automatically sets the green light even if the numeric thresholds pass.
    reasons=[]
    if median["pairedSamples"] < 90:
        reasons.append("Fewer than 90 same-event paired source/our forecasts")
    for horizon,entry in median["byHorizon"].items():
        if entry["pairedSamples"]<20:
            reasons.append("Fewer than 20 paired forecasts at "+horizon+" minute lead")
    with sqlite3.connect(f"file:{source_db}?mode=ro",uri=True) as db:
        days=db.execute(
            """SELECT count(distinct substr(observed_at,1,10))
               FROM observations WHERE source='student_public'"""
        ).fetchone()[0]
    if days<7:
        reasons.append("Fewer than 7 observation calendar days")
    observed_days=median["matchedCoverage"]["serviceDaysWithAtLeastFivePairs"]
    if observed_days<5:
        reasons.append("Fewer than 5 independent matched local service days with 5+ paired forecasts")
    if any(median["matchedCoverage"]["byStop"][stop]["uniquePassages"]<10
           for stop in ("125","marshak","145")):
        reasons.append("Fewer than 10 matched GPS-proxy passages at one or more principal stops")
    if median["pairedSamples"] and (
        median["shadowMAEminutes"] is None or
        median["studentMAEminutes"] is None or
        median["shadowMAEminutes"] >= median["studentMAEminutes"]*.9
    ):
        reasons.append("Not demonstrably at least 10% lower paired MAE")
    reasons.extend([
        "Historical source route geometry and GPS geofence passages still require real stop-location validation",
        "Manual service/route reliability signoff required before production ETA release",
    ])
    return {
        "generatedAt":now.isoformat(),
        "mode":"shadow_only",
        "source":"third_party_student_tracker",
        "publicationStatus":"NOT_APPROVED",
        "reviewRequired":True,
        "gatesOutstanding":reasons,
        "history":{
            "gpsObservations":replay["fixes"],
            "gpsPassagePairs":replay["passagePairs"],
            "days":days,
            "replayAssumesFutureTripDirection":True,
            "replayModels":replay["metrics"],
            "replayPairedSpeedComparison":replay["pairedComparison"],
        },
        "geofenceSensitivity":geofence_sensitivity(read_fixes(source_db)),
        "collectionHealth":collection_health,
        "stationaryDepartureResearch":dwell_report(source_db,now),
        "corridorResearch":corridor_report(source_db,now),
        "sourceReliability24h":source_reliability,
        "matchedComparison":paired,
    }


def atomic_write_json(output:str,result:dict):
    destination=Path(output)
    destination.parent.mkdir(parents=True,exist_ok=True)
    temp_path=None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",encoding="utf-8",prefix=".eta-eval-",
            suffix=".json",dir=destination.parent,delete=False
        ) as f:
            temp_path=Path(f.name)
            os.fchmod(f.fileno(),0o600)
            json.dump(result,f,indent=2,sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path,destination)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def main():
    parser=argparse.ArgumentParser(description="Private GPS ETA accuracy scorecard")
    parser.add_argument("--db",default="/var/lib/ccny-shuttle/gps.sqlite3")
    parser.add_argument("--shadow-db",default="/var/lib/ccny-shuttle/eta-shadow.sqlite3")
    parser.add_argument("--output",default="/var/lib/ccny-shuttle/eta-evaluation.json")
    args=parser.parse_args()
    result=compile_report(args.db,args.shadow_db)
    atomic_write_json(args.output,result)
    print(json.dumps({
        "publicationStatus":result["publicationStatus"],
        "observationDays":result["history"]["days"],
        "shadowMedianSamples":result["matchedComparison"]["paired"][METHOD_MEDIAN]["pairedSamples"],
        "shadowSpeedSamples":result["matchedComparison"]["paired"][METHOD_SPEED]["pairedSamples"],
        "comparisonReady":False
    }))


if __name__=="__main__":
    main()
