"""Pure geometry operations for source-attributed CCNY shuttle routes.

Coordinates describe approximate third-party route centrelines. Route matching
never changes the underlying, source-timestamped GPS coordinates.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

M_PER_DEG = 111195.0
ORIGIN_LAT = 40.82
ORIGIN_LON = -73.95
LON_SCALE = math.cos(math.radians(ORIGIN_LAT))
MAX_MATCH_DISTANCE_M = 70.0


@dataclass(frozen=True, slots=True)
class Match:
    direction: str
    progress_m: float
    route_length_m: float
    offroute_m: float
    tangent_bearing: float


def xy(lat: float, lon: float) -> tuple[float, float]:
    """Local east/north meters, appropriate only for the campus area."""
    return ((lon-ORIGIN_LON)*M_PER_DEG*LON_SCALE,
            (lat-ORIGIN_LAT)*M_PER_DEG)


def _segment_projection(point, a, b):
    dx,dy = b[0]-a[0],b[1]-a[1]
    length2=dx*dx+dy*dy
    if length2 < 1:
        return None
    t=max(0.0,min(1.0,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/length2))
    foot=(a[0]+t*dx,a[1]+t*dy)
    distance=math.hypot(point[0]-foot[0],point[1]-foot[1])
    length=math.sqrt(length2)
    bearing=(math.degrees(math.atan2(dx,dy))+360)%360
    return t, distance, length, bearing


class RouteCatalog:
    def __init__(self, config: dict):
        if config.get("attribution")!="student_public_tracker_bootstrap":
            raise ValueError("Route source attribution missing")
        self.paths:dict[str,list[tuple[float,float]]]={}
        self.xy_paths={}
        self.cumulative={}
        self.stop_progress:dict[str,dict[str,float]]={}
        for direction in ("NB","SB"):
            raw=config["paths"][direction]
            if len(raw)<3 or len(raw)>100:
                raise ValueError("Invalid route geometry")
            coords=[]
            for lat,lon in raw:
                if not (math.isfinite(lat) and math.isfinite(lon) and
                        40.78<lat<40.86 and -74.02<lon<-73.88):
                    raise ValueError("Route point out of campus bounds")
                coords.append((lat,lon))
            points=[xy(*point) for point in coords]
            distances=[0.0]
            for a,b in zip(points,points[1:]):
                step=math.dist(a,b)
                if step<2 or step>1250:
                    raise ValueError("Route segment discontinuity")
                distances.append(distances[-1]+step)
            self.paths[direction]=coords
            self.xy_paths[direction]=points
            self.cumulative[direction]=distances
        self.stops={}
        for name,point in config["stops"].items():
            if name not in ("125","135","marshak","145"):
                raise ValueError("Unexpected stop ID")
            lat,lon=point
            if not (40.78<lat<40.86 and -74.02<lon<-73.88):
                raise ValueError("Invalid stop point")
            self.stops[name]=(lat,lon)
        self.ordered_stops={
            "NB":("125","135","marshak","145"),
            "SB":("145","marshak","125"),
        }
        for direction in ("NB","SB"):
            projected={}
            for stop in self.ordered_stops[direction]:
                result=self.match(*self.stops[stop],direction=direction,
                                  max_distance=100)
                if result is None:
                    raise ValueError("Stop too far from route: "+stop)
                projected[stop]=result.progress_m
            if any(a>=b for a,b in zip(projected.values(),
                                       list(projected.values())[1:])):
                raise ValueError("Stop mileposts are not ordered")
            self.stop_progress[direction]=projected

    @classmethod
    def load(cls, path: str | Path | None = None) -> "RouteCatalog":
        path=Path(path) if path else Path(__file__).with_name("route_geometry.json")
        return cls(json.loads(path.read_text()))

    def match(self,lat: float,lon: float,direction: str,
              max_distance:float=MAX_MATCH_DISTANCE_M) -> Match | None:
        if direction not in self.paths or not (
            math.isfinite(lat) and math.isfinite(lon)) or not (
            40.78<lat<40.86 and -74.02<lon<-73.88
        ):
            return None
        point=xy(lat,lon)
        pts=self.xy_paths[direction]
        candidates=[]
        for i,(a,b) in enumerate(zip(pts,pts[1:])):
            candidate=_segment_projection(point,a,b)
            if candidate is None:
                continue
            t,offroute,length,bearing=candidate
            progress=self.cumulative[direction][i]+t*length
            candidates.append((offroute,progress,bearing))
        if not candidates:
            return None
        offroute,progress,bearing=min(candidates,key=lambda c:c[0])
        if offroute>max_distance:
            return None
        return Match(direction,progress,self.cumulative[direction][-1],
                     offroute,bearing)

    def next_leg(self,direction:str,progress_m:float):
        """Return (previous stop, next stop, fraction remaining, distance).

        The terminal and each on-request stop have explicit restrictions.
        """
        stops=self.stop_progress.get(direction)
        if stops is None or not math.isfinite(progress_m):
            return None
        ordered=list(stops.items())
        for (previous,origin),(following,target) in zip(ordered,ordered[1:]):
            if progress_m <= target+3 and progress_m>=origin-80:
                leg=max(1.0,target-origin)
                remaining=max(0.0,min(1.0,(target-progress_m)/leg))
                return previous,following,remaining,max(0.0,target-progress_m)
        return None
