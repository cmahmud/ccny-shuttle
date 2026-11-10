"""Ordinary-browser public CCNY shuttle GPS relay.

This intentionally uses the website's *normal*, already-scheduled frontend
requests at its native ~7s cadence. There are no replayed private requests,
proxy rotations, account credentials, bot challenges, or response scraping from
restricted 403 endpoints. The source is labeled student_public, not Samsara.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import logging
from math import cos, hypot, radians
from pathlib import Path
from urllib.parse import urlsplit

from .storage import ObservationStore
from .student_public import (
    BASE_URL, FEED_PATH, SOURCE, in_service_window, parse_public_feed,
)

LOG = logging.getLogger("ccny-public-gps")


def surface_distance_m(a, b) -> float:
    """Short local distance in meters between two bus coordinates."""
    dlat = radians(a.latitude - b.latitude)
    dlon = radians(a.longitude - b.longitude)
    mean_lat = radians((a.latitude + b.latitude) / 2)
    return 6_371_000 * hypot(dlat, dlon * cos(mean_lat))


def feed_silence_seconds(
    session_started_at: datetime,
    last_good_response: datetime | None,
    now: datetime,
) -> float:
    """Give every new browser session time to receive its first public feed.

    An earlier session's successful response must never cause the next
    session to time out before its first 7-second frontend poll.
    """
    reference = (
        last_good_response
        if last_good_response and last_good_response > session_started_at
        else session_started_at
    )
    return max(0.0, (now - reference).total_seconds())


class PublicBrowserRelay:
    def __init__(self, store: ObservationStore, browser_path: str):
        self.store = store
        self.browser_path = browser_path
        self.last_good_response: datetime | None = None
        self.last_generated_ms = 0
        self.valid_responses = 0
        self.inserted_total = 0
        self.failed_responses = 0
        self._tasks: set[asyncio.Task] = set()
        self._denied = False
        self._last_positions = {
            obs.vehicle_id: obs for obs in store.latest_observations(SOURCE)
        }

    def accept_payload(self, payload: dict, now: datetime) -> int:
        snapshot = parse_public_feed(payload, now)
        milliseconds = int(snapshot.feed_generated_at.timestamp() * 1000)
        if milliseconds <= self.last_generated_ms:
            return 0
        # Reject out-of-order fixes and impossible position jumps. GPS jitter can
        # alter coordinates without a new original timestamp; ignore those too.
        valid = []
        movement_rejected = 0
        for obs in snapshot.observations:
            previous = self._last_positions.get(obs.vehicle_id)
            if previous:
                dt = (obs.observed_at - previous.observed_at).total_seconds()
                if dt <= 0 or surface_distance_m(obs, previous) > max(55, dt * 35):
                    movement_rejected += 1
                    continue
            valid.append(obs)
        # Each snapshot updates transport separately from the underlying GPS event time.
        inserted = self.store.commit_page(
            SOURCE, tuple(valid), f"public-feed:{milliseconds}", polled_at=now
        )
        for obs in valid:
            self._last_positions[obs.vehicle_id] = obs
        self.last_generated_ms = milliseconds
        self.last_good_response = now
        self.valid_responses += 1
        self.inserted_total += inserted
        if self.valid_responses == 1 or self.valid_responses % 15 == 0:
            LOG.info(
                "Student public relay responsive; upstream_state=%s vehicles=%d "
                "new_observations=%d rejected=%d total=%d",
                snapshot.source_state, len(valid), inserted,
                snapshot.vehicles_rejected + movement_rejected, self.inserted_total,
            )
        return inserted

    async def _handle_response(self, response):
        parsed = urlsplit(response.url)
        if parsed.hostname != "ccnyshuttlebus.com" or parsed.path != FEED_PATH:
            return
        if response.status in (401, 403):
            self._denied = True
            LOG.error("Student public GPS feed denied access; stop rather than bypass")
            return
        if response.status != 200:
            self.failed_responses += 1
            return
        try:
            payload = await response.json()
            self.accept_payload(payload, datetime.now(timezone.utc))
        except (ValueError, TypeError, OverflowError, KeyError) as exc:
            self.failed_responses += 1
            LOG.warning("Rejected third-party GPS feed: %s", type(exc).__name__)
        except Exception as exc:
            self.failed_responses += 1
            LOG.warning("Could not read third-party feed: %s", type(exc).__name__)

    def _schedule_response(self, response):
        task = asyncio.create_task(self._handle_response(response))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def watch_once(self, *, once: bool, timeout_seconds: int = 55):
        """Open one normal public page and listen for its own feed requests."""
        # Deliberately optional import so collector unit tests require no browser.
        from playwright.async_api import async_playwright

        self._denied = False
        session_start = datetime.now(timezone.utc)
        successes_before = self.valid_responses
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                executable_path=self.browser_path,
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                context = await browser.new_context(
                    service_workers="block",
                    viewport={"width": 1100, "height": 850},
                )
                try:
                    page = await context.new_page()
                    page.on("response", self._schedule_response)
                    navigation = await page.goto(
                        BASE_URL, wait_until="domcontentloaded", timeout=30000
                    )
                    if not navigation or navigation.status in (401, 403):
                        raise PermissionError("Public student tracker page denied access")
                    if navigation.status != 200:
                        raise RuntimeError("Public student tracker page unavailable")
                    LOG.info("Ordinary public browser connected to CCNY student tracker")
                    started = asyncio.get_running_loop().time()
                    while (asyncio.get_running_loop().time() - started) < timeout_seconds:
                        if self._denied:
                            raise PermissionError("Public GPS feed denied access")
                        if once and self.valid_responses > successes_before:
                            return True
                        if not once and feed_silence_seconds(
                            session_start, self.last_good_response,
                            datetime.now(timezone.utc),
                        ) > 45:
                            raise TimeoutError("Public feed ceased updating")
                        if not once and not in_service_window(datetime.now(timezone.utc)):
                            return True
                        await asyncio.sleep(1)
                    if self.valid_responses == successes_before:
                        raise TimeoutError("Public tracker returned no usable feed")
                    return True
                finally:
                    await context.close()
            finally:
                if self._tasks:
                    await asyncio.gather(*self._tasks, return_exceptions=True)
                await browser.close()


async def main():
    parser = argparse.ArgumentParser(
        description="CCNY student-public feed reader (normal browser, no private API)"
    )
    run = parser.add_mutually_exclusive_group(required=True)
    run.add_argument("--once", action="store_true", help="Fetch one normal public feed snapshot")
    run.add_argument("--loop", action="store_true", help="Monitor at the website's native poll cadence")
    parser.add_argument("--db", required=True, help="Shared local GPS store")
    parser.add_argument("--browser-path", required=True, help="Installed ordinary Chromium executable")
    args = parser.parse_args()
    if not Path(args.browser_path).is_file():
        parser.error("Browser executable missing")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    store = ObservationStore(args.db)
    worker = PublicBrowserRelay(store, args.browser_path)
    try:
        failures = 0
        while True:
            if args.loop and not in_service_window(datetime.now(timezone.utc)):
                await asyncio.sleep(60)
                continue
            try:
                await worker.watch_once(once=args.once, timeout_seconds=32 if args.once else 1200)
                failures = 0
                if args.once:
                    return 0
            except PermissionError:
                LOG.error("Public feed access denied; intervention required, no retry")
                return 77
            except Exception as exc:
                failures += 1
                LOG.error("Public browser session ended: %s", type(exc).__name__)
                if args.once:
                    return 1
                await asyncio.sleep(min(240, 10 * (2 ** min(failures, 4))))
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
