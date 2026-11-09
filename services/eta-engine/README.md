# CCNY Shuttle ETA Engine — Outage Prototype

Status: Standalone, offline model. NOT connected to the public website. Do not display its predictions until real CCNY data is collected, routes are matched, and error intervals are calibrated against real arrivals.

The engine accepts externally provided, measured segment-travel-time histories and route-matched progress. It returns a median prediction, provisional uncertainty interval, last confirmed GPS timestamp, source age, and a status.

Safeguards:
- No prediction when travel history is insufficient or direction is unknown.
- No prediction after a provisional 180-second GPS expiration.
- Terminal dwell and Marshak waiting require measured dwell samples; otherwise no prediction.
- If a stop may already have been passed, report possibly_passed, not a safe countdown.
- Empirical bootstrap is deterministic to enable repeatable regression testing.
- No hard-coded CCNY shuttle timings and no synthetic vehicle shown in the public app.

Run locally using Python standard library:

python3 -m unittest discover -s services/eta-engine/tests -v

IMPORTANT: Default thresholds, simple empirical assumptions and uncertainty margins are engineering placeholders. Before production, validate stop event labeling, traffic/time segmentation, route state classification, data freshness, time-split backtests, and confidence interval coverage.
