# Agent instructions — CCNY Smart Shuttle

## Mission
Build an independent, reliable CCNY shuttle tracker that optimizes **whole journeys** to campus, not only vehicle pins. Preserve the distinction between confirmed GPS, extrapolated position, and absent data.

## Work order
1. **Phase 0: verify a legitimate GPS data source.** Do not implement production scraping before documenting the source's permission/access model, observation fields, freshness and reliability.
2. Establish an adapter contract and deterministic fixtures.
3. Build an idempotent GPS collector, database persistence, health monitoring, and tests.
4. Implement transparent ETA baselines and replay-based evaluation.
5. Build routing recommendations, resilient PWA, and production monitoring.

## Safety, privacy, and integrity
- Independent development permission from CCNY Facilities is **not** an API token or automatic authorization to circumvent Samsara restrictions.
- Do not bypass authentication, CAPTCHA, rate limiting, anti-bot protections, paywalls, or technical controls. No harvested session cookies, authentication tokens, or hidden private fleet endpoints.
- Do not depend on the student-made tracker's backend or copy its proprietary code. It is a comparison target only.
- Collect **shuttle-only** GPS observations; no unrelated vehicles, drivers, student identifiers, or personal device location history on the server without an explicit reason and consent.
- Never commit secrets, HAR files with cookies, session data, raw authorization headers, or personally identifiable data. Sanitize network traces before documentation.
- Track original GPS observation time **and** ingestion time independently. A successful poll does not mean new GPS was emitted.
- Never label extrapolation as live; stale predictions must degrade and eventually expire. Fail closed to “unavailable” if reliability is not supported.
- Mock data must be labeled simulated end-to-end, never presented as real shuttle positions.
- Do not change, restart, reconfigure, or overwrite existing VPS services (including OmniRoute and proxy scraping). No deployment without explicit review of hostnames/ports/volumes, secrets, and resource usage.

## Engineering conventions
- Follow repo code patterns once established; prioritize small, reviewable commits.
- Prefer static typing and explicit schemas: TypeScript on the web, Python type hints and Pydantic on the API.
- Make each GPS adapter implement a common normalized observation model (source, vehicle_id, coordinates, source_at, received_at, optional heading/speed/accuracy).
- Deduplicate by source + vehicle + source timestamp + coordinate information.
- Validate timestamps, plausible coordinates, vehicle status, and malformed source payloads.
- Use bounded retries, exponential backoff with jitter, persistent cursors when supported, and observability for stalled sources.
- Store timestamps in UTC; display America/New_York in the user interface.
- Model departure dwell separately from road travel, especially at Marshak.
- Evaluate predictions with time-split backtests, median/P90 absolute errors and calibrated interval coverage. Do not claim superiority without benchmark evidence.
- Prefer a simple statistical baseline before more complex ML.
- Keep source-specific code in adapters, not in application UI or prediction logic.
- Add unit and deterministic replay tests for changes to data parsing, state recognition and ETA computation.

## Phase 0 deliverables
Document in `research/samsara/`:
- Tested browser environment and observation date.
- Public viewer request patterns and protocols, without secrets or unnecessary endpoint details.
- What GPS fields are actually visible and how frequently source timestamps change.
- Whether an independent, permitted collector is technically feasible.
- Risks, access restrictions, and official API fallback.
- A minimal reproducible **permitted** test and its result, or a clearly stated blocker.

**No claim of working live GPS collection until fresh, real CCNY shuttle observations have been independently verified.**
