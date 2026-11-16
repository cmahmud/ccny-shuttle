# Last-known and non-reporting shuttles (beta)

**Implemented November 10, 2026:** The one-page tracker now keeps previously observed buses visible as a separate **Not currently reporting** group, even when the GPS service is outside its listed hours.

## Truthful source interpretation

- `Reporting GPS`: original source GPS observed within the freshness limit and the upstream transport is healthy; this is **not** a verified service/route assignment.
- `Not currently reporting`: a bus that appeared in our stored GPS observations within the last seven days but is not shown in the current live/recent positions. **This does not establish that a bus is off duty, parked, or physically at its last reported point.**
- `Last seen (N)`: an opt-in map overlay of GPS coordinates **no older than 24 hours**, displayed with separate gray historical markers and an explicit “NOT current locations” notice. The historical overlay is off by default.
- GPS histories older than seven days or invalid/out-of-region records are excluded from the compact fleet list.

This is based solely on source-validated historical observations already present in the status endpoint. It is not a complete official fleet inventory. If a shuttle has never reported GPS to this collector, there is no source evidence with which to list it. The student feed returned an empty vehicle list outside service hours during the investigation, so we cannot independently confirm the status of unobserved buses.

No derived ETA, bus motion, or stop arrival is inferred from last-known GPS. Active shuttle map pins and historical positions have distinct presentation and lifecycle policies.

## Verification

- Unit/UI suite: 37 frontend tests passed.
- Live Chromium smoke on desktop (1365×880) and phone (390×844): two not-currently-reporting bus rows, two optional historical map markers, no JavaScript errors, no unwanted horizontal overflow.
- Site and API remain on `shuttle.syndrid.com`, no additional GPS collector or OmniRoute port changes.

The next accurate fleet-status improvement would require a genuine shuttle roster plus explicit status/assignment data from the official or student source; never substitute guesses based only on an old GPS timestamp.
