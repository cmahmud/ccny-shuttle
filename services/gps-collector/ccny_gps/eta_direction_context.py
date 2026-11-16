"""Conservative contemporaneous direction attribution for GPS-pass evaluation.

Only moving statuses timestamped BEFORE the geofence passage are eligible.
No future route labels, no vehicle positions, no public ETA changes.
"""
from __future__ import annotations

import bisect
import collections
from datetime import datetime
import sqlite3

from .eta_research import Pass


def directions_before_passages(events:list[Pass],rows:list[tuple],
                               max_age_seconds:int=160)->dict[tuple,str]:
    """Map (vehicle, stop, passage timestamp) to the latest prior moving direction.

    Any uncertain event is omitted. A bus's direction reported at the stop can
    already refer to its NEXT trip; exclude contemporaneous or future samples.
    """
    if not 30<=max_age_seconds<=300:
        raise ValueError('Direction context age outside conservative range')
    by_vehicle=collections.defaultdict(list)
    for vehicle,observed,direction,status in rows:
        if direction not in ('NB','SB') or status!='moving':continue
        try:
            dt=observed if isinstance(observed,datetime) else datetime.fromisoformat(observed.replace('Z','+00:00'))
            if dt.tzinfo is None:continue
        except (ValueError,TypeError,AttributeError):continue
        by_vehicle[vehicle].append((dt,direction))
    for track in by_vehicle.values():track.sort(key=lambda x:x[0])
    by_time={vehicle:[at for at,_ in track] for vehicle,track in by_vehicle.items()}
    result={}
    for event in events:
        track=by_vehicle.get(event.vehicle_id,[])
        if not track:continue
        ix=bisect.bisect_left(by_time[event.vehicle_id],event.timestamp)
        if ix==0:continue
        at,direction=track[ix-1]
        age=(event.timestamp-at).total_seconds()
        if 0<age<=max_age_seconds:
            result[event.vehicle_id,event.stop_id,event.timestamp]=direction
    return result


def read_event_directions(gps_db:str,events:list[Pass])->dict[tuple,str]:
    """Use publicly reported moving direction from the archived source only."""
    with sqlite3.connect(f'file:{gps_db}?mode=ro',uri=True) as db:
        try:
            rows=db.execute("""SELECT vehicle_id, observed_at, direction, reported_status
                FROM vehicle_context_history WHERE source='student_public'
                AND direction IN ('NB','SB') AND reported_status='moving'
                ORDER BY vehicle_id, observed_at""").fetchall()
        except sqlite3.OperationalError:
            return {}
    return directions_before_passages(events,rows)
