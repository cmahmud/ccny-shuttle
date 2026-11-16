"""PRIVATE walk-forward ETA bias/range calibration experiment.

Only completed historical GPS-geofence passages are eligible training data.
This experiment does not change the live ETA worker or student-facing UI.
"""
from __future__ import annotations

import collections
from datetime import datetime,timedelta,timezone
import statistics


def _time(text:str)->datetime:
    parsed=datetime.fromisoformat(text.replace('Z','+00:00'))
    if parsed.tzinfo is None:raise ValueError('Naive forecast timestamp')
    return parsed.astimezone(timezone.utc)


def _quantile(values:list[float],q:float)->float:
    ordered=sorted(values)
    return ordered[max(0,min(len(ordered)-1,round((len(ordered)-1)*q)))]


def walk_forward_calibration(rows:list[dict],min_completed_events:int=25,
                             lookback_days:int=7,min_distinct_days:int=3)->dict:
    """Score point-bias adjustment plus empirical uncertainty without leakage.

    A unique GPS passage is one training event, regardless of how many forecast
    horizons predicted it. For each new forecast we use only events that had
    already *completed* before its prediction timestamp. This prevents using a
    later stop passage, a future forecast or the same event to self-calibrate.
    """
    if min_completed_events<2 or lookback_days<1 or min_distinct_days<1:
        raise ValueError('Invalid walk-forward training constraints')
    by_event:dict[tuple,list[float]]=collections.defaultdict(list)
    events={}
    for r in rows:
        try:
            completed=_time(r['actualPass'])
            signed=float(r['shadowSignedErrorMinutes'])
            if not -180<signed<180:continue
            key=(r['vehicle'],r['stop'],completed)
            by_event[key].append(signed)
            events[key]=completed
        except (ValueError,TypeError,KeyError,OverflowError):continue
    prior=[(event_time,statistics.median(by_event[key]))
           for key,event_time in events.items()]
    scored=[]
    for r in rows:
        try:
            issued=_time(r['forecastAt']);completed=_time(r['actualPass'])
            signed=float(r['shadowSignedErrorMinutes'])
            source_err=float(r['studentAbsErrorMinutes'])
            if not -180<signed<180 or issued>completed:continue
        except (ValueError,TypeError,KeyError,OverflowError):continue
        lower=issued-timedelta(days=lookback_days)
        available=[(at,error) for at,error in prior if lower<=at<issued]
        if len(available)<min_completed_events or len({at.date() for at,_ in available})<min_distinct_days:
            continue
        historical=[error for _,error in available]
        bias=statistics.median(historical)
        # q90 of prior event-level residuals after removing the historical
        # median bias. These are NOT calibrated passenger confidence bounds.
        halfwidth=max(.5,_quantile([abs(err-bias) for err in historical],.90))
        adjusted_error=signed-bias
        scored.append({
            'horizon':r['horizon'],
            'baselineAbsErrorMin':abs(signed),
            'adjustedAbsErrorMin':abs(adjusted_error),
            'studentAbsErrorMin':source_err,
            'sourceCoverageProxy':r.get('sourceRangeCovered'),
            'rangeCoveredProxy':abs(adjusted_error)<=halfwidth,
            'rangeWidthMin':2*halfwidth,
            'biasCorrectionMin':bias,
            'priorEvents':len(available),
        })
    if not scored:return {
        'eligible':0,'baselineMAEmin':None,'adjustedMAEmin':None,
        'rangeCoverageProxy':None,'meanWidthMin':None,'studentMAEmin':None,
        'trainingMethod':'prior_completed_event_median_bias_plus_q90_abs_error',
        'status':'INSUFFICIENT_WALK_FORWARD_HISTORY',
        'publicPredictionAllowed':False,
    }
    mean=lambda field:round(statistics.mean(r[field] for r in scored),3)
    by_horizon={}
    for h in sorted({r['horizon'] for r in scored}):
        subset=[r for r in scored if r['horizon']==h]
        by_horizon[str(h)]={
            'n':len(subset),
            'adjustedMAEmin':round(statistics.mean(r['adjustedAbsErrorMin'] for r in subset),3),
            'rangeCoverageProxy':round(statistics.mean(r['rangeCoveredProxy'] for r in subset),3),
        }
    return {
        'eligible':len(scored),
        'baselineMAEmin':mean('baselineAbsErrorMin'),
        'adjustedMAEmin':mean('adjustedAbsErrorMin'),
        'studentMAEmin':mean('studentAbsErrorMin'),
        'rangeCoverageProxy':mean('rangeCoveredProxy'),
        'meanWidthMin':mean('rangeWidthMin'),
        'medianBiasCorrectionMin':round(statistics.median(r['biasCorrectionMin'] for r in scored),3),
        'medianPriorEvents':round(statistics.median(r['priorEvents'] for r in scored),1),
        'byHorizon':by_horizon,
        'trainingMethod':'prior_completed_event_median_bias_plus_q90_abs_error',
        'minimumCompletedEvents':min_completed_events,
        'minimumDistinctDays':min_distinct_days,
        'lookbackDays':lookback_days,
        'status':'RESEARCH_ONLY_GPS_PROXY',
        'publicPredictionAllowed':False,
        'limits':[
            'Training uses only completed historical GPS-geofence passages before each forecast.',
            'Grouped event-level residuals reduce reuse of correlated forecast horizons.',
            'Reported coverage is for inferred GPS passages, not true passenger boarding arrivals.',
            'The candidate is evaluated only where shadow and source forecasts were already paired; this may bias the sample.',
            'This is an exploratory calibration, not a published 90% confidence interval.',
        ],
    }
