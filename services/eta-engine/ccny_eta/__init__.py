"""CCNY shuttle historical stop logging and transparent ETA baselines.

All current examples are synthetic until validated GPS/stop geometry is available.
"""
from .core import (
    GPSFix, VerifiedStop, StopEvent, StopDetector,
    TravelSample, EtaWindow, EtaBaseline, build_travel_samples,
    ActualArrival, BenchmarkPrediction, benchmark_errors,
)
from .storage import HistoryStore

__all__ = [
    "GPSFix", "VerifiedStop", "StopEvent", "StopDetector",
    "TravelSample", "EtaWindow", "EtaBaseline", "build_travel_samples",
    "ActualArrival", "BenchmarkPrediction", "benchmark_errors", "HistoryStore",
]
