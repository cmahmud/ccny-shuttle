"""Synthetic browser checks for the experimental third-party ETA display."""
import asyncio,json,os
from datetime import datetime,timedelta,timezone
from playwright.async_api import async_playwright
SITE=os.getenv('SHUTTLE_SITE_URL','http://127.0.0.1:9822/')
CHROME=os.getenv('SHUTTLE_CHROMIUM_PATH')

def payload(gps_live=True,forecasts_live=True):
    now=datetime.now(timezone.utc)
    fmt=lambda d:d.isoformat().replace('+00:00','Z')
    buses=[
      {'vehicleId':'synthetic-88','busName':'88','latitude':40.81844,'longitude':-73.94949,
       'observedAt':fmt(now-timedelta(seconds=4)),'gpsAgeSeconds':4,'freshness':'fresh',
       'reportedStatus':'moving','reportedDirection':'NB','reportedNextStopId':'145','headingDegrees':28,
       'locationKind':'third_party_observed'},
      {'vehicleId':'synthetic-89','busName':'89','latitude':40.8149,'longitude':-73.95133,
       'observedAt':fmt(now-timedelta(seconds=6)),'gpsAgeSeconds':6,'freshness':'fresh',
       'reportedStatus':'moving','reportedDirection':'SB','reportedNextStopId':'125','headingDegrees':196,
       'locationKind':'third_party_observed'},
    ]
    def row(bus,dir,m):return {'vehicleId':f'synthetic-{bus}','busName':bus,'direction':dir,
                 'arrivalAt':fmt(now+timedelta(minutes=m)),'providerPredictionsEnabled':False}
    estimates={'source':'student_public','experimental':True,'calibrated':False,
      'generatedAt':fmt(now-timedelta(seconds=10 if forecasts_live else 180)),
      'stops':{
        '125':[row('89','SB',17),row('88','SB',35),row('89','SB',58),row('88','SB',76),row('89','SB',98),row('88','SB',116)],
        '135':[row('88','NB',2),row('89','NB',24),row('88','NB',43),row('89','NB',64)],
        'marshak':[row('88','NB',3),row('89','NB',25),row('88','SB',43),row('89','SB',65)],
        '145':[row('88','NB',14),row('89','NB',37),row('88','NB',54),row('89','NB',78)],
      }}
    return {'source':'student_public','sourceState':'live' if gps_live else 'stale',
      'transportState':'healthy','generatedAt':fmt(now),'lastSuccessfulPoll':fmt(now),
      'vehicles':buses if gps_live else [],'sourceArrivalEstimates':estimates}

async def check(browser,width):
    ctx=await browser.new_context(viewport={'width':width,'height':844},is_mobile=width<760,
      has_touch=width<760,service_workers='block')
    page=await ctx.new_page()
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    data={'body':payload()}
    await page.route('**/api/v1/vehicles',lambda route:route.fulfill(status=200,
      content_type='application/json',body=json.dumps(data['body'])))
    await page.goto(SITE,wait_until='domcontentloaded',timeout=28000)
    await page.locator('.arrival-row').first.wait_for(timeout=5000)
    assert await page.locator('.arrival-row').count()==3
    assert '17 min' in await page.locator('.arrival-row').first.inner_text()
    assert await page.locator('.arrival-next-tag').count()==1
    assert await page.locator('.arrival-next-tag').inner_text()=='NEXT'
    assert await page.locator('.arrival-row.is-next').count()==1
    clock=await page.locator('.arrival-clock-time').first.inner_text()
    assert ('AM' in clock or 'PM' in clock),clock
    assert 'Unverified' in await page.locator('#arrival-provenance').inner_text()
    await page.locator('#arrival-more').click()
    assert await page.locator('.arrival-row').count()==6
    assert await page.locator('.arrival-row.is-next').count()==1
    await page.locator('[data-stop="marshak"]').click()
    assert await page.locator('.arrival-row').count()==3
    assert 'To 145th St' in await page.locator('.arrival-row').first.inner_text()
    assert 'To 125th St' in await page.locator('.arrival-rows').inner_text()
    await page.locator('[data-stop="nac"]').click()
    assert await page.locator('#arrival-panel').is_hidden()
    assert await page.locator('#eta-status').inner_text()=='ETA unavailable'
    await page.locator('[data-stop="125"]').click()
    assert await page.locator('.arrival-row').count()==3
    layout=await page.evaluate('''() => ({overflow:document.documentElement.scrollWidth>innerWidth+2,
      mapHeight:Math.round(document.querySelector('.map-wrapper').getBoundingClientRect().height),
      panelHeight:Math.round(document.querySelector('#stop-panel').getBoundingClientRect().height),
      nextHighlighted:document.querySelectorAll('.arrival-row.is-next').length,
      clockVisible:document.querySelector('.arrival-clock-time').getBoundingClientRect().height>0,
      forecastRows:document.querySelectorAll('.arrival-row').length})''')
    assert not layout['overflow'] and not errors,(width,layout,errors)
    assert layout['clockVisible'] and layout['mapHeight']>200
    # Simulate real upstream delay: recent source times stay visible, labeled STALE.
    data['body']=payload(gps_live=False,forecasts_live=False)
    await page.evaluate('() => window.dispatchEvent(new Event("online"))')
    await page.wait_for_timeout(700)
    assert await page.locator('#arrival-panel').is_visible()
    assert 'Stale' in await page.locator('#eta-status').inner_text()
    assert await page.locator('.arrival-row.is-next').count()==0
    assert await page.locator('.arrival-next-tag').count()==0
    assert 'STALE' in await page.locator('#arrival-provenance').inner_text()
    assert 'AM' in await page.locator('.arrival-clock-time').first.inner_text() or 'PM' in await page.locator('.arrival-clock-time').first.inner_text()
    # A reload during the grace period recovers only the saved, labeled snapshot.
    await page.reload(wait_until='domcontentloaded',timeout=30000)
    await page.locator('.arrival-panel.is-stale').wait_for(state='visible',timeout=6000)
    assert await page.locator('.arrival-row.is-next').count()==0
    # Two-minute maximum measured from the SOURCE timestamp, not polling time.
    await page.clock.fast_forward(125000)
    await page.evaluate('() => window.dispatchEvent(new Event("online"))')
    await page.wait_for_timeout(850)
    assert await page.locator('#arrival-panel').is_hidden()
    assert await page.locator('#eta-status').inner_text()=='ETA unavailable'
    print(json.dumps({'width':width,**layout,'errors':errors},ensure_ascii=False),flush=True)
    await ctx.close()

async def main():
    async with async_playwright() as p:
      kw={'headless':True}
      if CHROME:kw.update(executable_path=CHROME,args=['--no-sandbox','--disable-dev-shm-usage'])
      browser=await p.chromium.launch(**kw)
      try:
        for width in (320,390,430,1365):await check(browser,width)
      finally:await browser.close()

if __name__=='__main__':asyncio.run(main())
