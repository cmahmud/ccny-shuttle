"""Empirical, outage-aware shuttle arrival estimates.

Only trained on externally supplied observed historical data. The public site
must not display these predictions before real route matching and calibration.
"""
from dataclasses import dataclass
from datetime import datetime
from math import isfinite, floor, ceil
from random import Random
from typing import Literal

ETAStatus = Literal["predicted", "possibly_passed", "unavailable"]
VehicleMode = Literal["moving", "waiting_at_terminal", "unknown"]
MIN_SAMPLES = 8
MAX_GPS_AGE_S = 180
FRESH_GPS_S = 30


@dataclass(frozen=True)
class SegmentHistory:
    name: str
    durations_seconds: tuple[float, ...]

    def __post_init__(self):
        if not self.name or any(not isfinite(x) or x <= 0 for x in self.durations_seconds):
            raise ValueError("Invalid measured segment duration history")


@dataclass(frozen=True)
class VehicleState:
    vehicle_id: str
    segment_index: int
    segment_fraction: float
    observed_at: datetime
    mode: VehicleMode = "moving"
    terminal_elapsed_seconds: float = 0.0

    def __post_init__(self):
        if not self.vehicle_id or self.segment_index < 0:
            raise ValueError("Vehicle ID and nonnegative segment index required")
        if not isfinite(self.segment_fraction) or not 0 <= self.segment_fraction <= 1:
            raise ValueError("Route progress must be in [0,1]")
        if self.observed_at.tzinfo is None:
            raise ValueError("Observed timestamp must be timezone-aware")
        if self.mode not in ("moving","waiting_at_terminal","unknown"):
            raise ValueError("Invalid vehicle operational mode")
        if not isfinite(self.terminal_elapsed_seconds) or self.terminal_elapsed_seconds < 0:
            raise ValueError("Invalid measured dwell elapsed time")


@dataclass(frozen=True)
class Forecast:
    status: ETAStatus
    reason: str
    generated_at: datetime
    last_confirmed_at: datetime
    source_age_seconds: float
    median_eta_seconds: float | None
    lower_eta_seconds: float | None
    upper_eta_seconds: float | None
    probability_already_passed: float | None
    observation_count_min: int | None

    @property
    def is_displayable_eta(self):
        return self.status == "predicted" and self.median_eta_seconds is not None


def percentile(values: list[float], fraction: float) -> float:
    if not values or not 0 <= fraction <= 1:
        raise ValueError("Invalid percentile")
    values = sorted(values)
    k = (len(values)-1)*fraction
    a,b = floor(k),ceil(k)
    return values[a] + (values[b]-values[a])*(k-a)


def forecast_arrival(
    state: VehicleState,
    segments_to_stop: tuple[SegmentHistory, ...],
    now: datetime,
    *,
    terminal_dwell_samples_seconds: tuple[float, ...] | None = None,
    max_model_age_seconds: float = MAX_GPS_AGE_S,
    draws: int = 512,
) -> Forecast:
    if now.tzinfo is None:
        raise ValueError("Prediction timestamp must be timezone-aware")
    age = (now - state.observed_at).total_seconds()
    if age < -5:
        raise ValueError("Confirmed GPS timestamp is implausibly in future")
    age = max(0.0, age)
    if not isfinite(max_model_age_seconds) or max_model_age_seconds <= 0:
        raise ValueError("Expiry must be finite and positive")
    if not 64 <= draws <= 5000:
        raise ValueError("Invalid sample count")
    if not segments_to_stop or state.segment_index >= len(segments_to_stop):
        raise ValueError("Route sequence does not contain matched segment")

    def unavailable(reason: str) -> Forecast:
        return Forecast("unavailable",reason,now,state.observed_at,age,None,None,None,None,None)

    if age > max_model_age_seconds:
        return unavailable("gps_expired")
    if state.mode == "unknown":
        return unavailable("vehicle_direction_unknown")
    remaining_segments = segments_to_stop[state.segment_index:]
    if any(len(s.durations_seconds) < MIN_SAMPLES for s in remaining_segments):
        return unavailable("insufficient_measured_history")
    if state.mode == "waiting_at_terminal":
        if terminal_dwell_samples_seconds is None or len(terminal_dwell_samples_seconds) < MIN_SAMPLES:
            return unavailable("terminal_departure_unknown")
        if any(not isfinite(x) or x <= 0 for x in terminal_dwell_samples_seconds):
            raise ValueError("Invalid terminal dwell samples")

    rng=Random(68123)
    trajectories=[]
    passed=0
    for _ in range(draws):
        remaining=0.0
        if state.mode == "waiting_at_terminal":
            total_dwell=rng.choice(terminal_dwell_samples_seconds)
            remaining+=max(0.0,total_dwell-state.terminal_elapsed_seconds)
        for i,segment in enumerate(remaining_segments):
            historical_duration=rng.choice(segment.durations_seconds)
            fraction=1.0 if i>0 or state.mode=="waiting_at_terminal" else 1.0-state.segment_fraction
            remaining+=historical_duration*fraction
        remaining-=age
        if remaining <= 0:
            passed+=1
        trajectories.append(max(0.0,remaining))

    already_passed=passed/draws
    n=min(len(s.durations_seconds) for s in remaining_segments)
    if already_passed >= .90:
        return Forecast("unavailable","likely_passed_stop",now,state.observed_at,age,None,None,None,already_passed,n)

    lower=percentile(trajectories,.1)
    median=percentile(trajectories,.5)
    upper=percentile(trajectories,.9)
    # Provisional outage margin; must be calibrated before any production use.
    if age>FRESH_GPS_S:
        margin=(age-FRESH_GPS_S)*.2
        lower=max(0.0,lower-margin)
        upper+=margin

    status: ETAStatus="possibly_passed" if already_passed >= .15 else "predicted"
    reason=("stop_may_have_been_passed" if status=="possibly_passed"
            else "terminal_dwell_estimated" if state.mode=="waiting_at_terminal"
            else "gps_projection" if age>FRESH_GPS_S
            else "historical_travel_time_estimate")
    return Forecast(status,reason,now,state.observed_at,age,median,lower,upper,already_passed,n)
