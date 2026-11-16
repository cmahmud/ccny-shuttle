# Accepted-feed cadence and GPS freshness-gap research · November 16, 2026

The existing private `ccny-shuttle-eta-report.timer` now measures timing of **accepted public student feed snapshots**, not just the fraction with a fresh GPS position. No second collector, high-frequency Firecrawl task or new external endpoint is added.

`sourceReliability24h.freshnessGapDiagnostics` reports:

- accepted source snapshot interval p50/p90/p99, from the stored feed quality samples;
- contiguous samples where **at least one vehicle is reported**, upstream feed is live/current, but **none of the reported vehicles has a source GPS fix under 30 seconds old**;
- number of these GPS freshness-gap episodes, counts reaching 60 and 120 observed seconds, and the longest period with UTC start/end and sample count.

An episode stops when a fresh fix arrives, a source response is unhealthy, no vehicles are reported, or an accepted-response interval exceeds 45 seconds. Therefore episode length is a **lower bound on the time actually observed with no fresh GPS**, not an inferred outage duration. The data cannot distinguish deliberate vehicle parking/standing from faulty device uplink. The feed could also be inaccessible between accepted responses. The scorecard does **not** claim service downtime.

### Initial measurement

On 24-hour historical quality samples during November 16, the median accepted feed snapshot interval was approximately **7.4 seconds** (p90 **10.6s**, p99 **12.3s**). There were **26 bounded all-bus GPS freshness-gap episodes**, **11** with at least 120 seconds continuously observed, and the longest lasted **254.8 seconds**. This explains why the UI may show delayed/last-reported bus positions even while the source's tracker banner says live.

### Safety

- Aggregates only; no bus IDs, GPS coordinates, cookies, user data or sample locations in the exported private report.
- No change to GPS parsing, feed access, source poll frequency, active vehicle statuses, public arrival estimates or ETA publication policy.
- Independent Samsara GPS is still unverified and requires a permitted read-only source; see GitHub issue #1.
- Report remains private, `NOT_APPROVED` for independent ETA publication, and refreshed by the already running 30-minute timer.
