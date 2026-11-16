"""End-to-end smoke tests for the compact public-facing CCNY Shuttle page.

Run against a local static server or the user's test/production domain.
Requires: pip install playwright && python -m playwright install chromium

No authenticated requests, GPS scraping, or private account access.
"""
import asyncio
import json
import os

from playwright.async_api import async_playwright

SITE_URL = os.environ.get("SHUTTLE_SITE_URL", "http://127.0.0.1:9000/")
CHROMIUM_PATH = os.environ.get("SHUTTLE_CHROMIUM_PATH")
SCREENSHOT_DIR = os.environ.get("SHUTTLE_SCREENSHOT_DIR")


async def verify(browser, label, width, height, mobile):
    ctx = await browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=1,
        is_mobile=mobile,
        has_touch=mobile,
    )
    page = await ctx.new_page()
    failures = []
    try:
        page.on("pageerror", lambda exc: failures.append("Runtime error: " + str(exc)))
        page.on(
            "console",
            lambda msg: failures.append("Module MIME error: " + msg.text)
            if msg.type == "error" and ("MIME type" in msg.text or "module script" in msg.text)
            else None,
        )
        resp = await page.goto(SITE_URL, wait_until="domcontentloaded", timeout=30000)
        assert resp and resp.status == 200, "Homepage failed to load"
        # Avoid wait_for_function: it uses dynamic evaluation blocked by production CSP.
        for _ in range(50):
            if await page.locator("#top-status-label").inner_text() != "Checking GPS":
                break
            await asyncio.sleep(0.2)
        else:
            raise AssertionError("Frontend never advanced beyond Checking GPS")
        await page.wait_for_selector(".leaflet-container", timeout=15000)
        assert await page.evaluate("Boolean(window.L)"), "Leaflet did not load"
        await page.locator('button[data-stop="145"]').click()
        assert await page.locator("#stop-name").inner_text() == "145th Street"
        assert await page.locator('button[data-stop="145"]').get_attribute("aria-selected") == "true"
        pickup = await page.locator("#stop-directions").get_attribute("href")
        assert pickup and pickup.startswith("https://www.google.com/maps/"), "Missing pickup-area link"
        assert await page.locator('.trip-card').count()==0, "Walking routes panel should be removed"
        overflow = await page.evaluate(
            "document.documentElement.scrollWidth > window.innerWidth + 3"
        )
        assert not overflow, "Unexpected horizontal scrolling"
        assert not failures, "; ".join(failures)

        result = {
            "viewport": label,
            "status": await page.locator("#top-status-label").inner_text(),
            "leaflet_initialized": True,
            "selected_stop": "145th Street",
            "horizontal_overflow": overflow,
            "no_script_errors": not failures,
        }
        print(json.dumps(result), flush=True)

        if SCREENSHOT_DIR:
            from pathlib import Path
            folder = Path(SCREENSHOT_DIR)
            folder.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(folder / f"shuttle-{label}.png"), full_page=True)
    finally:
        await ctx.close()


async def main():
    async with async_playwright() as p:
        opts = {"headless": True}
        if CHROMIUM_PATH:
            opts["executable_path"] = CHROMIUM_PATH
            opts["args"] = ["--no-sandbox", "--disable-dev-shm-usage"]
        browser = await p.chromium.launch(**opts)
        try:
            await verify(browser, "desktop", 1365, 880, False)
            await verify(browser, "phone", 390, 844, True)
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
