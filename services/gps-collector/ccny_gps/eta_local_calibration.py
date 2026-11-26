"""Private same-horizon, stop-conditioned walk-forward experiment.

All training outcomes precede issuance. Never publish these intervals as
passenger-arrival confidence intervals: outcomes are GPS-geofence proxies.
"""
from collections import defaultdict, Counter
from datetime import timedelta
from zoneinfo import ZoneInfo
from statistics import median, mean
from math import ceil, isfinite
from .eta_calibration import _time


def _fit(history):
    errors=[median(values) for values in history.values()]
    bias=median(errors)
    residuals=sorted(abs(x-bias) for x in errors)
    # Conservative finite-sample empirical quantile. Not a coverage guarantee.
    index=min(len(residuals)-1,ceil((len(residuals)+1)*.9)-1)
    return bias,max(.5,residuals[index])


def predicted_lead_band(issued, predicted):
    """Feature available at issuance, never the eventual time to arrival."""
    lead=(predicted-issued).total_seconds()/60
    if not 0<=lead<=120:return None
    return '0-4' if lead<4 else '4-8' if lead<8 else '8+'


def evaluate_local_calibration(rows, lookback_days=7, min_local_events=12,
                               min_global_events=25, min_days=3, *, prospective=False):
    if min(min_local_events,min_global_events)<2 or min_days<1 or lookback_days<1:
        raise ValueError('Invalid training requirements')
    clean=[]
    for row in rows:
        try:
            issued=_time(row['forecastAt']); done=_time(row['actualPass'])
            error=float(row['shadowSignedErrorMinutes']); source=float(row['studentAbsErrorMinutes'])
            if issued>=done or not isfinite(error) or abs(error)>=180 or not isfinite(source) or source<0:
                continue
            key=(row['vehicle'],row['stop'],done)
            band=predicted_lead_band(issued,_time(row['shadowArrivalAt'])) if prospective else row['horizon']
            if band is None:continue
            clean.append((issued,done,key,row['stop'],band,error,source,row['horizon']))
        except (KeyError,TypeError,ValueError,OverflowError):continue
    completed=sorted(clean,key=lambda x:x[1]); upcoming=sorted(clean,key=lambda x:x[0]); cursor=0
    past=[]; scored=[]; choices=Counter()
    for issued,done,key,stop,band,error,source,horizon in upcoming:
        while cursor<len(completed) and completed[cursor][1]<issued:
            past.append(completed[cursor]);cursor+=1
        lower=issued-timedelta(days=lookback_days)
        past=[r for r in past if r[1]>=lower]
        all_history=defaultdict(list); horizon_history=defaultdict(list); local_history=defaultdict(list)
        for _,d,k,s,h,e,_,_actual_h in past:
            all_history[k].append(e)
            if h==band:
                horizon_history[k].append(e)
                if s==stop:local_history[k].append(e)
        def enough(history,n):
            return len(history)>=n and len({k[2].astimezone(ZoneInfo('America/New_York')).date() for k in history})>=min_days
        # Same comparison cohort for baseline calibration and candidate.
        if not enough(all_history,min_global_events):continue
        global_bias,global_half=_fit(all_history)
        if enough(local_history,min_local_events):history=local_history; tier='stop_horizon'
        elif enough(horizon_history,min_global_events):history=horizon_history;tier='horizon'
        else:history=all_history;tier='global'
        bias,half=_fit(history)
        choices[tier]+=1
        scored.append(dict(stop=stop,horizon=horizon,band=band,raw=abs(error),student=source,
                           globalError=abs(error-global_bias),localError=abs(error-bias),
                           localCovered=abs(error-bias)<=half,globalCovered=abs(error-global_bias)<=global_half,
                           width=2*half,globalWidth=2*global_half))
    def summary(items):
        if not items:return {'n':0}
        fields={'rawMAEmin':'raw','studentMAEmin':'student','globalMAEmin':'globalError','localMAEmin':'localError',
                'localCoverageProxy':'localCovered','globalCoverageProxy':'globalCovered','localWidthMin':'width','globalWidthMin':'globalWidth'}
        return {'n':len(items),**{k:round(mean(r[v] for r in items),3) for k,v in fields.items()}}
    return {'status':'RESEARCH_ONLY_GPS_PROXY','publicPredictionAllowed':False,
            'overall':summary(scored),'selectionCounts':dict(choices),
            'conditioningFeature':'issued_predicted_lead_band' if prospective else 'retrospective_actual_horizon',
            'byPredictedLeadBand':{str(b):summary([r for r in scored if r['band']==b]) for b in sorted({r['band'] for r in scored})} if prospective else {},
            'byStop':{s:summary([r for r in scored if r['stop']==s]) for s in sorted({r['stop'] for r in scored})},
            'byHorizon':{str(h):summary([r for r in scored if r['horizon']==h]) for h in sorted({r['horizon'] for r in scored})},
            'byStopHorizon':{s:{str(h):summary([r for r in scored if r['stop']==s and r['horizon']==h]) for h in sorted({r['horizon'] for r in scored if r['stop']==s})} for s in sorted({r['stop'] for r in scored})},
            'lookbackDays':lookback_days,'minimumLocalEvents':min_local_events,'minimumGlobalEvents':min_global_events,'minimumDays':min_days,
            'limits':['Historical matched sample is selected using eventual arrivals; not a prospective live deployment trial.', 'Predicted lead is available at issue time.' if prospective else 'Actual lead horizon is known only after arrival; this retrospective result cannot support live model selection.', 'Same-event GPS proxy, not observed boarding.','Shared student GPS source; no independence claim.','Matched forecasts only; selection bias possible.','Fixed hierarchical fallback; long-horizon samples may be sparse.']}
