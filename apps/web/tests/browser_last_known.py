"""Regression: last-known GPS markers must be visible without a tap, and
must remain usable during an upstream/data outage. All positions are synthetic.
"""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from playwright.async_api import async_playwright

SITE = os.getenv("SHUTTLE_SITE_URL", "http://127.0.0.1:9815/")
CHROME = os.getenv("SHUTTLE_CHROMIUM_PATH")


def sample_data(live=False):
    now = datetime.now(timezone.utc)
    iso = lambda t: t.isoformat().replace("+00:00", "Z")
    rows = [
        {"vehicleId":"synthetic-89", "busName":"89", "latitude":40.82001,
         "longitude":-73.949679, "observedAt":iso(now-timedelta(hours=2)),
         "gpsAgeSeconds":7200, "freshness":"stale",
         "locationKind":"third_party_observed", "reportedStatus":None},
        {"vehicleId":"synthetic-88", "busName":"88", "latitude":40.819926,
         "longitude":-73.949855, "observedAt":iso(now-timedelta(hours=4)),
         "gpsAgeSeconds":14400, "freshness":"stale",
         "locationKind":"third_party_observed", "reportedStatus":None}
    ]
    if live:
        rows[0]["observedAt"]=iso(now-timedelta(seconds=5))
        rows[0]["gpsAgeSeconds"]=5
        rows[0]["freshness"]="fresh"
        rows[0]["reportedStatus"]="moving"
    return {
        "source":"student_public", "generatedAt":iso(now),
        "sourceState":"live" if live else "stale",
        "transportState":"healthy" if live else "offline",
        "lastSuccessfulPoll":iso(now),
        "vehicles":rows,
    }


async def run_one(browser, width, live=False, offline_after_reload=False):
    mobile=width < 700
    context=await browser.new_context(
        viewport={"width":width,"height":844},
        is_mobile=mobile, has_touch=mobile, service_workers="block"
    )
    page=await context.new_page()
    errors=[]
    page.on("pageerror", lambda error: errors.append(str(error)[:200]))
    payload=sample_data(live=live)
    failing={"value":False}

    async def route_status(route):
        if failing["value"]:
            await route.abort("failed")
        else:
            await route.fulfill(status=200,content_type="application/json",
                                body=json.dumps(payload))
    await page.route("**/api/v1/vehicles",route_status)
    await page.goto(SITE,wait_until="domcontentloaded",timeout=25000)
    await page.wait_for_timeout(1600)

    history=page.locator(".historical-pin")
    rows=page.locator(".historical-bus-button")
    expected_history=1 if live else 2
    assert await history.count() == expected_history, (width,"no auto last-known pins")
    assert await rows.count() == expected_history, (width,"no last-known rows")
    if expected_history == 2:
        labels = await page.locator(".historical-pin .history-label").evaluate_all(
            "els => els.map(e => {const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom}})"
        )
        assert len(labels)==2
        horizontal=max(0,min(labels[0]["right"],labels[1]["right"])-max(labels[0]["left"],labels[1]["left"]))
        vertical=max(0,min(labels[0]["bottom"],labels[1]["bottom"])-max(labels[0]["top"],labels[1]["top"]))
        assert horizontal * vertical == 0, (width,"overlapping last-GPS labels",labels)
    assert await page.locator("#map-history").get_attribute("aria-pressed") == "true"
    assert "Last reported GPS" in await page.locator("#vehicle-list").inner_text()
    assert "NOT live" in await page.locator("#map-update").inner_text() or live

    await rows.first.click()
    await page.wait_for_timeout(260)
    popup=await page.locator(".leaflet-popup-content").inner_text()
    expected_bus="88" if live else "89"
    assert expected_bus in popup, (width,popup)
    assert "may have moved" in popup
    assert "Open recorded point in Maps" in popup

    # Five-second poll must not close a tapped bus's popup.
    if width == 390 and not live:
        await page.wait_for_timeout(5600)
        assert await page.locator(".leaflet-popup-content").count() == 1, (
            width,"GPS polling closed the popup"
        )

    await page.locator("#map-history").click()
    assert await history.count()==0, (width,"hide toggle broken")
    # Clicking a last-reported row must restore pins and focus that report.
    await rows.first.click()
    await page.wait_for_timeout(280)
    assert await history.count()==expected_history, (width,"last-known row cannot restore map")
    assert expected_bus in await page.locator(".leaflet-popup-content").inner_text()

    if offline_after_reload:
        failing["value"]=True
        await page.reload(wait_until="domcontentloaded",timeout=25000)
        await page.wait_for_timeout(900)
        assert await history.count()==2, (width,"tab-scoped offline historical recovery failed")
        assert await rows.count()==2
        assert await page.locator("#top-status-label").inner_text() == "GPS unavailable"

    layout=await page.evaluate("""() => ({
      overflow: document.documentElement.scrollWidth > window.innerWidth + 2,
      markers: document.querySelectorAll(".historical-pin").length,
      label: document.getElementById("map-update").innerText,
      mapHeight: document.querySelector(".map-card").getBoundingClientRect().height,
      rowHeight: document.querySelector(".historical-bus-button").getBoundingClientRect().height
    })""")
    assert not layout["overflow"] and layout["mapHeight"]>240 and layout["rowHeight"]>=45
    assert not errors, errors
    print(json.dumps({"width":width,"live":live,"offlineReload":offline_after_reload,
                      "layout":layout,"jsErrors":len(errors)}),flush=True)
    await context.close()


async def main():
    async with async_playwright() as p:
        launch={"headless":True}
        if CHROME:
            launch.update({"executable_path":CHROME,
                           "args":["--no-sandbox","--disable-dev-shm-usage"]})
        browser=await p.chromium.launch(**launch)
        try:
            for width in (320,375,390,430,1365):
                await run_one(browser,width,offline_after_reload=(width==390))
            await run_one(browser,390,live=True)
        finally:
            await browser.close()


if __name__=="__main__":
    asyncio.run(main())
