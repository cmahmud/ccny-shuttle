# Private stationary stop-zone departure research

This adds an aggregate section (`stationaryDepartureResearch`) to the existing 30-minute private ETA report. It does not issue live departure forecasts or change public ETAs, positions, source access, or the existing shadow worker.

## Method

Join archived student-source GPS observations to exact-timestamp reported vehicle status. Require a moving-to-explicit-standing-at-stop transition within 45 seconds, entry within 38 m of a known stop, and two stationary observations. A moving fix outside 65 m ends a completed visit. Missing or unknown status, gaps over 45 seconds, an unconfirmed exit or the record ending censor the visit at the last observed fix. Single fixes and unknown onsets are not accepted. This measures the interval from first reported standing fix to observed moving zone exit, not actual boarding dwell, departure dispatch or parking status.

Estimate remaining duration using stop-specific conditional Kaplan-Meier quantiles, including censored observations in risk sets, with at least 12 at-risk visits from three New York local days. Walk-forward evaluation uses only history in the preceding 14 days whose endpoint was observed and received before the target onset. Status-context receipt timestamps are unavailable, and evaluation uses observation times rather than actual live issuance. Score the first stationary observation after confirmation at each elapsed landmark. Abstain when quantiles cannot be estimated. Compare against the same historical unconditional median minus elapsed time. Do not use censored outcomes as exact departures. Repeated landmarks from the same visit are correlated. Informative censoring and the selection of completed outcomes for accuracy scoring can bias results.

## Initial archive results (November 27, 2026)

824 qualifying visits, 478 completed, 346 censored. Marshak has 39 completed and 260 censored. Of 772 historical queries, 185 abstained and 23 predicted queries were censored, leaving 564 scored queries across 369 completed visits. Conditional MAE 0.193 minutes vs unconditional baseline 0.206 minutes. Empirical interval coverage of the GPS exit proxy 76.4%, mean width 0.553 minutes. No scored queries at 120 seconds or later: prolonged stops remain unsupported. This is not a comparison with the student tracker departure algorithm and not a guarantee of passenger arrival accuracy.

## Operations

Research report remains private and NOT_APPROVED for public predictions. Seven synthetic regression tests cover known onset, moving exit, missing data, censoring, conditional residuals, insufficient evidence and receipt-time leakage. Keep existing public ETA behavior unchanged. Future work needs trustworthy stationary departure outcomes (especially Marshak), direction and time-of-day stratification, an issuance-time trial, and a validated next-stop travel-time connection. Do not claim the current dwell estimates recover GPS during source outages.
