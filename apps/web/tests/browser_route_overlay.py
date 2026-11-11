import asyncio,json,os
from datetime import datetime,timedelta,timezone
from playwright.async_api import async_playwright
SITE=os.environ.get("SHUTTLE_SITE_URL","http://127.0.0.1:9817/")
CHROME=os.environ.get("SHUTTLE_CHROMIUM_PATH")
def payload(moving=True):
    now=datetime.now(timezone.utc)
    fmt=lambda t:t.isoformat().replace("+00:00","Z")
    return {
      "source":"student_public","generatedAt":fmt(now),
      "sourceState":"live","transportState":"healthy",
      "lastSuccessfulPoll":fmt(now),
      "vehicles":[
        {"vehicleId":"synthetic-bus-88","busName":"88","latitude":40.81992,
          "longitude":-73.94968,"headingDegrees":214,"reportedStatus":"moving" if moving else "standing",
          "reportedDirection":"SB","reportedNextStopId":"125",
          "observedAt":fmt(now-timedelta(seconds=4)),"gpsAgeSeconds":4,
          "freshness":"fresh","locationKind":"third_party_observed"},
        {"vehicleId":"synthetic-bus-89","busName":"89","latitude":40.8171,
         "longitude":-73.9522,"headingDegrees":139,
         "observedAt":fmt(now-timedelta(hours=2)),"gpsAgeSeconds":7200,
         "freshness":"stale","locationKind":"third_party_observed"}
       ]
    }

async def check(browser,width):
 ctx=await browser.new_context(viewport={"width":width,"height":844},is_mobile=width<760,has_touch=width<760,service_workers="block")
 page=await ctx.new_page()
 errors=[];page.on("pageerror",lambda e:errors.append(str(e)+" STACK "+str(e.stack)[:1000]))
 page_data=payload()
 await page.route("**/api/v1/vehicles",lambda r:r.fulfill(status=200,content_type="application/json",body=json.dumps(page_data)))
 await page.goto(SITE,wait_until="domcontentloaded",timeout=23000)
 await page.wait_for_timeout(1450)
 routes=await page.locator("path.leaflet-interactive").count()
 print("DEBUG",width,"errors",errors,"status",await page.locator("#top-status-label").inner_text(),"list",(await page.locator("#vehicle-list").inner_text())[:300],"route",await page.locator("#map-route-source").inner_text(),"arrowcount",await page.locator(".vehicle-arrow").count(),flush=True)
 bearing=await page.locator(".vehicle-arrow").first.get_attribute("style",timeout=2000)
 assert await page.locator(".vehicle-arrow").count()==1
 assert await page.locator(".historical-pin").count()==1
 assert routes>=4, ("route lines missing",routes)
 assert "214deg" in bearing
 assert await page.locator("#map-route-source").inner_text()=="Route via student tracker · approximate"
 await page.locator('[data-stop="135"]').click()
 await page.wait_for_timeout(200)
 assert await page.locator("#stop-name").inner_text()=="135th Street"
 await page.locator('.vehicle-arrow').first.click()
 await page.wait_for_timeout(160)
 assert "Bus 88" in await page.locator(".leaflet-popup-content").inner_text()
 layout=await page.evaluate("""() => ({overflow:document.documentElement.scrollWidth>window.innerWidth+2,
   routeCount:[...document.querySelectorAll('path.leaflet-interactive')].length,
   arrow:document.querySelector('.vehicle-arrow').getAttribute('style'),
   routeMessage:document.querySelector('#map-route-source').innerText,
   mapHeight:document.querySelector('.map-card').getBoundingClientRect().height
 })""")
 assert not layout["overflow"] and not errors
 print(json.dumps({"width":width,**layout},ensure_ascii=False),flush=True)
 await ctx.close()

async def main():
 async with async_playwright() as p:
  kw={"headless":True}
  if CHROME:kw.update(executable_path=CHROME,args=["--no-sandbox","--disable-dev-shm-usage"])
  browser=await p.chromium.launch(**kw)
  try:
   for width in (320,390,430,1365):await check(browser,width)
  finally:await browser.close()
asyncio.run(main())
