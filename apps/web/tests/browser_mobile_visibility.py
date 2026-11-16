"""Browser regression for phone-sized GPS layout with SYNTHETIC data only."""
import asyncio, json, os
from datetime import datetime, timedelta, timezone
from playwright.async_api import async_playwright
CHROME=os.getenv("SHUTTLE_CHROMIUM_PATH")
SITE=os.getenv("SHUTTLE_SITE_URL","http://127.0.0.1:9813/")
async def verify(browser, label,w,h, mobile, count):
    context=await browser.new_context(viewport={"width":w,"height":h},is_mobile=mobile,has_touch=mobile,service_workers="block")
    page=await context.new_page()
    clock=datetime.now(timezone.utc)
    now=clock.isoformat().replace("+00:00","Z")
    old=(clock-timedelta(minutes=12)).isoformat().replace("+00:00","Z")
    data={
      "source":"student_public","sourceLabel":"Student shuttle tracker (third-party GPS relay)",
      "generatedAt":now,"sourceState":"live","transportState":"healthy","lastSuccessfulPoll":now,
      "vehicles":[
        {"vehicleId":"fake-77140","latitude":40.816,"longitude":-73.9495,
         "observedAt":now,"receivedAt":now,"gpsAgeSeconds":5,"freshness":"fresh",
         "locationKind":"third_party_observed"},
        {"vehicleId":"fake-77146","latitude":40.817,"longitude":-73.951,
         "observedAt":old,"receivedAt":now,"gpsAgeSeconds":720,"freshness":"stale",
         "locationKind":"third_party_observed"}
      ]
    }
    await page.route("**/api/v1/vehicles",lambda route:route.fulfill(status=200, content_type="application/json",body=json.dumps(data)))
    errors=[]
    page.on("pageerror",lambda error:errors.append(str(error)[:150]))
    await page.goto(SITE,wait_until="domcontentloaded",timeout=25000)
    await page.wait_for_timeout(1700)
    initial=await page.evaluate('''() => {
      const props=(s)=>{const e=document.querySelector(s);if(!e)return null;const r=e.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height}};
      return {card:props(".card-bar"),title:props(".card-bar-title"),actions:props(".map-actions"),
        eta:props(".eta-hero"),stopLocation:props(".stop-location"),
        fleet:props(".fleet-section-label"),map:props(".map-wrapper"),
        scrollWidth:document.documentElement.scrollWidth,viewportWidth:window.innerWidth};
    }''')
    bus_button=page.locator("#map-buses")
    assert not await bus_button.is_disabled(),"Buses button incorrectly disabled"
    row=page.locator(".bus-row-button")
    assert await row.count()==1,"Expected 1 synthetic live bus row"
    bus_start=await page.locator(".vehicle-pin.reporting-bus").count()
    await bus_button.click()
    await page.wait_for_timeout(280)
    pin_box=await page.locator(".vehicle-pin.reporting-bus").bounding_box()
    map_box=await page.locator(".map-wrapper").bounding_box()
    assert pin_box and map_box
    center_in_map=(pin_box['x']>=map_box['x'] and pin_box['x']+pin_box['width']<=map_box['x']+map_box['width'] and pin_box['y']>=map_box['y'] and pin_box['y']+pin_box['height']<=map_box['y']+map_box['height'])
    await row.click()
    await page.wait_for_timeout(250)
    popup=await page.locator(".leaflet-popup-content").inner_text()
    res={"viewport":label,"width":w,"one_live_bus":bus_start,
         "known_historical":await page.locator(".historical-bus-row").count(),
         "map_header_one_line":initial['title']['height']<=initial['card']['height']-2,
         "map_header_no_overlap":initial['title']['right']+4<=initial['actions']['left'],
         "empty_eta_is_hidden":await page.locator(".eta-hero").is_hidden(),
         "fleet_after_stop_gap_px":round(initial['fleet']['top']-initial['stopLocation']['bottom'],1),
         "pin_fitted_after_tap":center_in_map,"popup_shows_bus":"77140" in popup,
         "horizontal_overflow":initial['scrollWidth']>initial['viewportWidth']+2,
         "errors":errors}
    print(json.dumps(res),flush=True)
    assert res["map_header_one_line"] and res["map_header_no_overlap"]
    assert res['empty_eta_is_hidden'] and 0 <= res['fleet_after_stop_gap_px'] <= 40
    assert res["pin_fitted_after_tap"] and res["popup_shows_bus"] and not res["horizontal_overflow"] and not errors
    await context.close()
async def main():
  async with async_playwright() as pw:
    options={"headless":True}
    if CHROME:
      options["executable_path"]=CHROME
      options["args"]=["--no-sandbox","--disable-dev-shm-usage"]
    browser=await pw.chromium.launch(**options)
    try:
      for w in (320,375,390,430):
        await verify(browser,f"phone-{w}",w,844,True,1)
      await verify(browser,"desktop",1365,880,False,1)
    finally:
      await browser.close()
asyncio.run(main())
