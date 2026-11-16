# Source reliability and chronological ETA calibration (v20)

## Grounded source comparison · November 16, 2026

- `ccnyshuttlebus.com`: its ordinary, public website presents an independent **beta** shuttle tracker based on CCNY's current shuttle source; it openly describes its estimates as **experimental**. Its browser-presented feed (`/tracker-data/feed`) currently reports buses **88 and 89** with source timestamps, source statuses and multiple upcoming-arrival entries. The student tracker is **not an independent position source relative to us**: our collector currently consumes that same browser-presented feed.
- Public Samsara live-sharing viewer: `https://cloud.samsara.com/o/4010168/fleet/viewer/FJMjrX1YlqCqlGxIKkXY`. The publicly rendered page was examined in an ordinary, unauthenticated browser. It visibly said **Search 2 vehicles** and a clicked marker identified **88**. The live-sharing page did not present reliable numerical GPS timestamps/coordinates to the text inspector, so **no automated, independent numerical comparison is established**. Do not reverse-engineer a private API or bypass authentication or rate limits. Facilities' approval of the independent website is **not a Samsara API credential**.
- Firecrawl: used for low-frequency **research** of the public student and Samsara pages (both returned HTTP 200 and descriptive static HTML). A live Firecrawl Samsara browser inspection timed out; ordinary Playwright public-page inspection subsequently succeeded for visible details. Do not use Firecrawl for every 5–7s GPS poll: it is credit-billed and does not supply confirmed numeric timestamps/positions from the official viewer. It can be used economically to research official shuttle schedules, service-day announcements and public documentation.

## Source data freshness — what new metrics mean

A healthy HTTP browser relay does not imply a fresh bus location. The previous collector log's `rejected=2` often represented **identical GPS timestamps**, not impossible location jumps. The revised collector separately records, on each **distinct accepted browser feed timestamp**:

- upstream feed age and upstream poll age
- reported/parsed vehicle totals, accepted new GPS fixes, unchanged GPS fixes, impossible GPS jumps and invalid source reports
- count of source records with a GPS fix no older than 30s; freshest and oldest source GPS ages

`relay_health_samples` stores **only nonidentifying aggregate counts**, without bus IDs, coordinates, passenger data, browser cookies, or access tokens. It retains at most 14 days; the collector prunes opportunistically. The private 30-minute `eta-evaluation.json` report contains `sourceReliability24h`, including the fractions of successful browser feed samples with genuinely fresh GPS. These fractions measure **samples**, not all-day uptime. Report `no_samples_yet` until collection begins; do not backfill fictional history.

## Strictly private ETA comparison

The existing source-vs-shadow matched comparison still pairs the **same bus, stop, horizon and nearly simultaneous forecast timestamps** against an inferred GPS-geofence stop passage. It is **not a verified passenger pickup time**. The upgraded report adds:

- Source and shadow earliest/latest range **coverage of GPS-proxy passages** and average interval widths on the *same* paired rows.
- An event-cluster bootstrap: correlated forecasts from different horizons for one passage are resampled as one **completed stop event**. Positive `shadow - student` error means our model is **worse**; the confidence interval is exploratory, not proof of real-world independence.
- A new **walk-forward bias and interval calibration candidate**, private only. At each matched forecast timestamp it uses **at least 25 unique completed earlier passage events across three days in a seven-day lookback**, applies the historical median signed error as a bias correction, and computes an exploratory empirical 90th-percentile absolute-residual radius. It cannot use current or later passage outcomes to train itself. It reports adjusted point MAE, source MAE on the identical eligible subset, GPS-proxy interval coverage and width. The range is **not** a published 90% passenger-confidence interval.

### First private test — November 16, 2026

On 55 eligible speed-blend matched forecasts, walk-forward correction reduced point MAE from **1.763 min** to **1.372 min**, compared with **1.605 min** for the source predictions on the same subset. The exploratory range covered **80.0%** of GPS-proxy passages at **5.529 min** mean width. This is *selection-limited historical evidence*, not proof of better production ETA performance; the full-source paired baseline remains worse than the student tracker. Publication remains `NOT_APPROVED` and the visitor site must not show our shadow predictions.

## What is not implemented or established

- No official Samsara API key, authorized second GPS feed, or independently verified live bus position.
- No authenticated or restricted endpoint crawling, no artificial GPS jumps/interpolation, no location claims when the upstream feed is old.
- No traffic-API routing or paid keys; observed segment history is only a traffic **proxy**.
- No vehicle status inference beyond fresh source-reported metadata.
- No public release or automatic green-light when the numeric model looks promising. Route geofences, long-horizon coverage, independent service days, repeated actual stop passage validation and manual signoff remain mandatory.

## Operations

- Source telemetry: source-fed `relay_health_samples` in `/var/lib/ccny-shuttle/gps.sqlite3`.
- Research report: `ccny-shuttle-eta-report.timer` already executes the private report on a 30-minute schedule. This release enriches that **existing job**, without creating additional recurring pollers or spending Firecrawl credits on GPS.
- Existing online GPS, browser source, status API and ETA shadow worker run in their own isolated CCNY services. Do not modify OmniRoute at `api.syndrid.com`, shared Nginx config, or unrelated Oracle services.
- Rollback: back up the existing Python modules, plus use SQLite's `backup` method while the database is live. Restoring previous Python modules leaves the new aggregate table inert and does not harm GPS history.
