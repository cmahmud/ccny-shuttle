"""Pure ETA models: source-aware GPS stop events and history-based travel windows.

No network access, live scraping, or automatic production prediction.
Only administratively verified geofences may trigger visit events.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import asin, cos, isfinite, radians, sin, sqrt
from statistics import median
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def _quantile(values: list[float], q: float) -> float:
    """Linear-interpolated empirical quantile, useful for transparent baselines."""
    if not values or not (0 <= q <= 1):
        raise ValueError("Nonempty values and quantile in [0, 1] required")
    values = sorted(values)
    x = (len(values) - 1) * q
    lo = int(x)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] * (hi - x) + values[hi] * (x - lo)


@dataclass(frozen=True)
class VerifiedStop:
    id: str
    latitude: float
    longitude: float
    radius_m: float
    verified: bool = False

    def __post_init__(self):
        if not self.id or not self.verified:
            raise ValueError("Stop geofence must be explicitly verified before use")
        if not (isfinite(self.latitude) and isfinite(self.longitude)
                and -90 <= self.latitude <= 90 and -180 <= self.longitude <= 180):
            raise ValueError("Invalid geofence coordinates")
        if not 10 <= self.radius_m <= 100:
            raise ValueError("Stop geofence radius must be between 10m and 100m")


@dataclass(frozen=True)
class GPSFix:
    vehicle_id: str
    observed_at: datetime
    latitude: float
    longitude: float
    speed_mph: float | None
    source: str = "samsara"

    def __post_init__(self):
        if not self.vehicle_id or not self.source:
            raise ValueError("GPS vehicle and source required")
        _utc(self.observed_at)
        if not (isfinite(self.latitude) and -90 <= self.latitude <= 90):
            raise ValueError("Invalid latitude")
        if not (isfinite(self.longitude) and -180 <= self.longitude <= 180):
            raise ValueError("Invalid longitude")
        if self.speed_mph is not None and (not isfinite(self.speed_mph) or self.speed_mph < 0):
            raise ValueError("Invalid speed")


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Approximate surface distance in meters using the Haversine formula."""
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = p2 - p1, radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * 6371000 * asin(min(1, sqrt(a)))


@dataclass(frozen=True)
class StopEvent:
    vehicle_id: str
    stop_id: str
    kind: str  # arrival or departure
    event_at: datetime
    detected_at: datetime
    method: str = "geofence_inferred"

    def __post_init__(self):
        if self.kind not in ("arrival", "departure"):
            raise ValueError("Invalid event type")
        _utc(self.event_at)
        _utc(self.detected_at)
        if self.event_at > self.detected_at:
            raise ValueError("Event cannot occur after detection")


@dataclass
class _FenceState:
    first_inside: datetime | None = None
    last_inside: datetime | None = None
    samples_inside: int = 0
    slow_samples: int = 0
    confirmed: bool = False
    outside_count: int = 0
    last_fix: datetime | None = None


class StopDetector:
    """Conservative geofence detector; ignores drive-bys and stale / out-of-order GPS.

    Arrival: 2 consecutive in-fence fixes, with a low-speed fix OR >=20s dwell.
    Departure: 2 outside fixes after a confirmed arrival, with no long GPS gap.
    A GPS gap >120s drops pending state rather than pretending a departure.
    """

    def __init__(self, stops: list[VerifiedStop], max_gap_seconds: int = 120):
        if not stops or len(set(x.id for x in stops)) != len(stops):
            raise ValueError("Stops must be nonempty with unique IDs")
        if max_gap_seconds < 5:
            raise ValueError("GPS gap bound too small")
        self.stops = tuple(stops)
        self.max_gap_seconds = max_gap_seconds
        self.states: dict[tuple[str, str], _FenceState] = {}

    def observe(self, fix: GPSFix) -> list[StopEvent]:
        now = _utc(fix.observed_at)
        output: list[StopEvent] = []
        for stop in self.stops:
            key = (fix.vehicle_id, stop.id)
            state = self.states.setdefault(key, _FenceState())
            if state.last_fix and now <= state.last_fix:
                continue  # duplicate/out-of-order, never revise historical events
            if state.last_fix and (now - state.last_fix).total_seconds() > self.max_gap_seconds:
                state = _FenceState()
                self.states[key] = state
            state.last_fix = now
            meters = distance_m(fix.latitude, fix.longitude, stop.latitude, stop.longitude)
            # Hysteresis avoids spurious repeated departures due to GPS jitter.
            inside = meters <= stop.radius_m
            outside = meters > stop.radius_m + 20
            if inside:
                state.outside_count = 0
                if state.first_inside is None:
                    state.first_inside = now
                    state.samples_inside = 0
                    state.slow_samples = 0
                state.last_inside = now
                state.samples_inside += 1
                if fix.speed_mph is not None and fix.speed_mph <= 5:
                    state.slow_samples += 1
                dwell = (now - state.first_inside).total_seconds()
                if not state.confirmed and state.samples_inside >= 2 and (
                    state.slow_samples > 0 or dwell >= 20
                ):
                    state.confirmed = True
                    output.append(StopEvent(fix.vehicle_id, stop.id, "arrival",
                                            state.first_inside, now))
            elif outside:
                state.outside_count += 1
                if state.confirmed and state.outside_count >= 2 and state.last_inside:
                    output.append(StopEvent(fix.vehicle_id, stop.id, "departure",
                                            state.last_inside, now))
                    self.states[key] = _FenceState(last_fix=now)
                elif not state.confirmed and state.outside_count >= 2:
                    self.states[key] = _FenceState(last_fix=now)
            else:
                # Transitional 20m margin does not confirm or end a visit.
                state.outside_count = 0
        return output


@dataclass(frozen=True)
class TravelSample:
    route: str
    from_stop: str
    to_stop: str
    departed_at: datetime
    arrived_at: datetime
    vehicle_id: str
    evidence: str = "geofence_inferred"

    def __post_init__(self):
        if not self.route or not self.vehicle_id or not self.from_stop or not self.to_stop:
            raise ValueError("Travel sample needs route, vehicle and stops")
        if self.from_stop == self.to_stop:
            raise ValueError("Travel segment cannot loop to same stop")
        seconds = (_utc(self.arrived_at) - _utc(self.departed_at)).total_seconds()
        if not 60 <= seconds <= 3600:
            raise ValueError("Travel time outside usable 1–60 minute window")
        if self.evidence not in ("geofence_inferred", "staff_verified", "manual_verified"):
            raise ValueError("Unknown observation provenance")

    @property
    def duration_seconds(self) -> float:
        return (_utc(self.arrived_at) - _utc(self.departed_at)).total_seconds()


def build_travel_samples(
    events: list[StopEvent], allowed_legs: dict[tuple[str, str], str]
) -> list[TravelSample]:
    """Build only allowed adjacent legs, and never use another bus's stop events."""
    by_vehicle: dict[str, list[StopEvent]] = {}
    for event in events:
        by_vehicle.setdefault(event.vehicle_id, []).append(event)
    samples: list[TravelSample] = []
    for vehicle, ordered in by_vehicle.items():
        previous_departure: StopEvent | None = None
        for ev in sorted(ordered, key=lambda e: (e.event_at, 0 if e.kind == "departure" else 1)):
            if ev.kind == "departure":
                previous_departure = ev
                continue
            if previous_departure:
                key = (previous_departure.stop_id, ev.stop_id)
                route = allowed_legs.get(key)
                if route:
                    try:
                        samples.append(TravelSample(
                            route, previous_departure.stop_id, ev.stop_id,
                            previous_departure.event_at, ev.event_at, vehicle
                        ))
                    except ValueError:
                        pass  # unknown service gaps, implausibly short/long legs
            previous_departure = None  # never pair the same departure with two arrivals
    return samples


@dataclass(frozen=True)
class EtaWindow:
    route: str
    from_stop: str
    to_stop: str
    median_seconds: int
    lower_seconds: int
    upper_seconds: int
    sample_count: int
    context: str
    gps_recent: bool = False  # Fresh telemetry does NOT establish calibrated live ETA

    def __post_init__(self):
        if not (0 <= self.lower_seconds <= self.median_seconds <= self.upper_seconds):
            raise ValueError("Invalid ETA interval")


class EtaBaseline:
    """History-based travel times, with contextual subgroups only when well supported.

    A baseline is NOT a live vehicle prediction. Inputs are complete observed legs.
    """

    def __init__(self, samples: list[TravelSample], min_samples: int = 5,
                 subgroup_samples: int = 8, history_days: int = 90):
        if min_samples < 3 or subgroup_samples < min_samples or history_days < 7:
            raise ValueError("Invalid training thresholds")
        self.samples = tuple(samples)
        self.min_samples = min_samples
        self.subgroup_samples = subgroup_samples
        self.history_days = history_days

    @staticmethod
    def _bucket(time: datetime) -> tuple[bool, int]:
        local = _utc(time).astimezone(NY)
        return (local.weekday() < 5, local.hour // 3)

    def predict_travel(
        self, route: str, from_stop: str, to_stop: str, as_of: datetime
    ) -> EtaWindow | None:
        now = _utc(as_of)
        # Prevent lookahead: only completed observed legs before prediction time.
        group = [s for s in self.samples
                 if (s.route, s.from_stop, s.to_stop) == (route, from_stop, to_stop)
                 and _utc(s.arrived_at) <= now
                 and timedelta(0) <= now - _utc(s.arrived_at) <= timedelta(days=self.history_days)]
        if len(group) < self.min_samples:
            return None
        same = [s for s in group if self._bucket(s.departed_at) == self._bucket(as_of)]
        contextual = len(same) >= self.subgroup_samples
        chosen = same if contextual else group
        durations = [s.duration_seconds for s in chosen]
        middle = int(round(median(durations)))
        lower = int(round(_quantile(durations, .10)))
        upper = int(round(_quantile(durations, .90)))
        # Must not imply greater measurement precision than a 30s GPS cadence.
        lower = max(0, min(lower, middle) - 30)
        upper = max(middle, upper + 30)
        return EtaWindow(route, from_stop, to_stop, middle, lower, upper,
                         len(chosen), "time_of_day" if contextual else "all_recent_history")

    def predict_from_departure(
        self, route: str, from_stop: str, to_stop: str,
        departed_at: datetime, gps_last_observed_at: datetime, as_of: datetime
    ) -> EtaWindow | None:
        now = _utc(as_of)
        departure = _utc(departed_at)
        last_gps = _utc(gps_last_observed_at)
        age = (now - last_gps).total_seconds()
        if departure > now or last_gps > now or last_gps < departure or age > 300:
            return None  # no ETA if bus not observed after departure, or stale >5m
        baseline = self.predict_travel(route, from_stop, to_stop, now)
        if baseline is None:
            return None
        elapsed = int((now - departure).total_seconds())
        if elapsed > baseline.upper_seconds + 120:
            return None  # bus overdue; do not claim it should arrive in 0 seconds
        # Outage makes the window wider: historical baseline remains the only evidence.
        uncertainty = int(max(0, age - 30) * .7)
        lo = max(0, baseline.lower_seconds - elapsed - uncertainty)
        mid = max(0, baseline.median_seconds - elapsed)
        hi = max(mid, baseline.upper_seconds - elapsed + uncertainty)
        return EtaWindow(route, from_stop, to_stop, mid, min(lo, mid), hi,
                         baseline.sample_count, baseline.context, gps_recent=age <= 30)


@dataclass(frozen=True)
class BenchmarkPrediction:
    provider: str  # 'ours' or 'student'
    trip_id: str
    predicted_at: datetime
    predicted_arrival_at: datetime

    def __post_init__(self):
        if self.provider not in ("ours", "student") or not self.trip_id:
            raise ValueError("Invalid benchmark prediction")
        if _utc(self.predicted_arrival_at) < _utc(self.predicted_at):
            raise ValueError("Arrival prediction precedes prediction time")


@dataclass(frozen=True)
class ActualArrival:
    trip_id: str
    arrived_at: datetime
    evidence: str = "manual_verified"

    def __post_init__(self):
        if not self.trip_id or self.evidence not in ("staff_verified", "manual_verified"):
            raise ValueError("Benchmarks require independently verified actual arrivals")
        _utc(self.arrived_at)


def benchmark_errors(
    predictions: list[BenchmarkPrediction], actuals: list[ActualArrival],
    max_prediction_lead_minutes: int = 60,
) -> dict[str, dict[str, float | int]]:
    """Compare on same matched trip and prediction timestamps; no lookahead.

    This does not prove superiority; report paired errors and sample counts.
    """
    by_trip = {a.trip_id: a for a in actuals}
    # Pair only samples where both trackers predicted the same trip and instant.
    groups: dict[tuple[str, datetime], dict[str, float]] = {}
    for p in predictions:
        actual = by_trip.get(p.trip_id)
        if not actual:
            continue
        lead = (_utc(actual.arrived_at) - _utc(p.predicted_at)).total_seconds()
        if not 0 <= lead <= max_prediction_lead_minutes * 60:
            continue
        error = abs((_utc(p.predicted_arrival_at) - _utc(actual.arrived_at)).total_seconds())
        groups.setdefault((p.trip_id, _utc(p.predicted_at)), {})[p.provider] = error
    paired = [v for v in groups.values() if {"ours", "student"} <= v.keys()]
    output: dict[str, dict[str, float | int]] = {}
    for provider in ("ours", "student"):
        values = [row[provider] for row in paired]
        if values:
            output[provider] = {
                "paired_samples": len(values),
                "median_absolute_error_seconds": round(median(values), 1),
                "p90_absolute_error_seconds": round(_quantile(values, .9), 1),
            }
    return output
