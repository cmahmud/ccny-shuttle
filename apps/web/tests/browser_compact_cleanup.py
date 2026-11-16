"""Browser visual-behavior contract for quieter desktop/phone tracker UI.

All position fixtures are synthetic; the service's live API remains untouched.
"""
import asyncio,json,os
from datetime import datetime,timedelta,timezone
from playwright.async_api import async_playwright
SITE=os.getenv('SHUTTLE_SITE_URL','http://127.0.0.1:9821/')
CHROME=os.getenv('SHUTTLE_CHROMIUM_PATH')

async def check(browser,width):
  context=await browser.new_context(viewport={'width':width,'height':844},
    is_mobile=width<760,has_touch=width<760,service_workers='block')
  page=await context.new_page()
  errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  now=datetime.now(timezone.utc)
  fmt=lambda dt:dt.isoformat().replace('+00:00','Z')
  vehicles=[{
    'vehicleId':'synthetic-bus-88','busName':'88','latitude':40.8199,'longitude':-73.94968,
    'observedAt':fmt(now-timedelta(seconds=5)),'gpsAgeSeconds':5,'freshness':'fresh',
    'reportedStatus':'moving','reportedDirection':'SB','reportedNextStopId':'125',
    'headingDegrees':214,'locationKind':'third_party_observed',
  }]
  response={'source':'student_public','sourceState':'live','transportState':'healthy',
    'generatedAt':fmt(now),'vehicles':vehicles}
  await page.route('**/api/v1/vehicles',lambda route:route.fulfill(status=200,
    content_type='application/json',body=json.dumps(response)))
  await page.goto(SITE,wait_until='domcontentloaded',timeout=25000)
  await page.wait_for_timeout(1150)
  layout=await page.evaluate('''() => {
    const rect=s=>{let r=document.querySelector(s).getBoundingClientRect();return {top:r.top,height:r.height,width:r.width}};
    return { overflow:document.documentElement.scrollWidth>innerWidth+2,
      stopPills:[...document.querySelectorAll('.stop-tab')].map(x=>x.getBoundingClientRect().height),
      header:rect('.tracker-top'), map:rect('.map-wrapper'),
      gpsBannerPosition:getComputedStyle(document.querySelector('.live-line')).position,
      mapTileFilter:getComputedStyle(document.querySelector('.leaflet-tile-pane')).filter,
      etaHidden:document.querySelector('.eta-hero').hidden,
      lastPinControlHidden:getComputedStyle(document.querySelector('#map-history')).display==='none',
      mapBusControlHidden:getComputedStyle(document.querySelector('#map-buses')).display==='none',
      legend:rect('.map-note'),
      attribution:rect('.leaflet-control-attribution'),
      lastTabRect:(()=>{const r=document.querySelector('#tab-nac').getBoundingClientRect();return {right:r.right,left:r.left};})(),
      transitHintHidden:getComputedStyle(document.querySelector('.trip-hint')).display==='none'
    };
  }''')
  assert not layout['overflow'] and not errors,(width,errors,layout)
  assert layout['etaHidden'] and layout['gpsBannerPosition']=='absolute'
  assert layout['header']['height']<=29,layout
  assert max(layout['stopPills'])<=44,layout
  assert layout['lastPinControlHidden'] and not layout['mapBusControlHidden']
  assert layout['transitHintHidden'] and layout['map']['height']>200
  assert layout['mapTileFilter']!='none'
  if width>=390:
    assert layout['lastTabRect']['right'] <= width-8,layout
  if width<760:
    # Attribution stays in the bottom-right; legend in the top-left.
    assert layout['legend']['top'] < layout['attribution']['top']-20,layout
  assert 'Buses on route' in await page.locator('#vehicle-list').inner_text()
  assert 'no calibrated ETA' not in await page.locator('#vehicle-list').inner_text()
  assert await page.locator('#top-status-label').inner_text()=='GPS via student'
  assert await page.locator('#service-advisory').is_hidden()
  assert await page.locator('#map-buses').is_enabled()
  await page.locator('#map-buses').click()
  await page.locator('[data-stop="marshak"]').click()
  assert (await page.locator('#stop-name').inner_text()).startswith('Marshak')
  assert await page.locator('#stop-directions').get_attribute('href')
  print(json.dumps({'width':width,'topBarHeight':round(layout['header']['height']),
    'stopPillHeight':round(layout['stopPills'][0]),'mapHeight':round(layout['map']['height']),
    'etaPlaceholderHidden':layout['etaHidden'],'overflow':layout['overflow'],
    'errors':errors}),flush=True)
  await context.close()

async def main():
  async with async_playwright() as p:
    args={'headless':True}
    if CHROME:args.update(executable_path=CHROME,args=['--no-sandbox','--disable-dev-shm-usage'])
    browser=await p.chromium.launch(**args)
    try:
      for width in (320,375,390,430,1365):await check(browser,width)
    finally:await browser.close()

if __name__=='__main__':asyncio.run(main())
