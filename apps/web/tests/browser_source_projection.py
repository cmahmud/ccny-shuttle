"""Do not turn source-generated time projections into live GPS arrivals."""
import asyncio,json,os
from datetime import datetime,timedelta,timezone
from playwright.async_api import async_playwright
SITE=os.getenv('SHUTTLE_SITE_URL','http://127.0.0.1:9826/')
CHROME=os.getenv('SHUTTLE_CHROMIUM_PATH')

def fmt(dt):return dt.isoformat().replace('+00:00','Z')

def scenario(projection=True,gps_age=155,generated_age=6):
    now=datetime.now(timezone.utc)
    bus=[{'vehicleId':'synthetic-88','busName':'88','latitude':40.81844,'longitude':-73.94949,
       'observedAt':fmt(now-timedelta(seconds=gps_age)),'gpsAgeSeconds':gps_age,
       'freshness':'stale','reportedStatus':'standing_at_stop','reportedDirection':'NB',
       'reportedNextStopId':'145','locationKind':'third_party_observed'}]
    forecast={
        'vehicleId':'synthetic-88','busName':'88','direction':'SB',
        'arrivalAt':fmt(now+timedelta(minutes=9)),
        'earliestAt':fmt(now+timedelta(minutes=6)),
        'latestAt':fmt(now+timedelta(minutes=13)),
        'gpsAgeSeconds':gps_age,'providerPredictionsEnabled':False
    }
    estimates={'source':'student_public','experimental':True,'calibrated':False,
        'mode':'projection_without_fresh_gps','liveGPSConfirmed':False,
        'generatedAt':fmt(now-timedelta(seconds=generated_age)),
        'stops':{'125':[forecast],'135':[],'marshak':[],'145':[]}}
    return {'source':'student_public','sourceState':'stale','transportState':'healthy',
       'generatedAt':fmt(now),'lastSuccessfulPoll':fmt(now),'vehicles':bus,
       'sourceArrivalEstimates':None,
       'sourceUnverifiedProjections':estimates if projection else None}

async def check(browser,width):
    ctx=await browser.new_context(viewport={'width':width,'height':844},is_mobile=width<760,
       has_touch=width<760,service_workers='block')
    page=await ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    data={'body':scenario()}
    await page.route('**/api/v1/vehicles',lambda route:route.fulfill(status=200,
      content_type='application/json',body=json.dumps(data['body'])))
    await page.goto(SITE,wait_until='domcontentloaded',timeout=30000)
    await page.locator('.arrival-row').first.wait_for(timeout=6500)
    assert await page.locator('.arrival-panel.is-projection').is_visible(),width
    assert await page.locator('#eta-status').inner_text()=='GPS-old projections'
    assert await page.locator('.arrival-row').count()==1
    assert await page.locator('.arrival-next-tag').count()==0
    assert await page.locator('.arrival-row.is-next').count()==0
    assert 'GPS 3m old' in await page.locator('.arrival-gps-warning').inner_text()
    assert 'SOURCE PROJECTION' in await page.locator('#arrival-provenance').inner_text()
    assert 'not live' in (await page.locator('#arrival-provenance').inner_text()).lower()
    assert '~' in await page.locator('.arrival-estimate').first.inner_text()
    assert 'Source window' in await page.locator('.arrival-source-window').first.inner_text()
    clock=await page.locator('.arrival-clock-time').first.inner_text()
    assert 'AM' in clock or 'PM' in clock
    assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth+2')
    data['body']=scenario(gps_age=310)
    await page.evaluate('() => window.dispatchEvent(new Event("online"))')
    await page.wait_for_timeout(700)
    assert await page.locator('#arrival-panel').is_hidden(),width
    data['body']=scenario(generated_age=95)
    await page.evaluate('() => window.dispatchEvent(new Event("online"))')
    await page.wait_for_timeout(700)
    assert await page.locator('#arrival-panel').is_hidden(),width
    data['body']=scenario(projection=False)
    await page.evaluate('() => window.dispatchEvent(new Event("online"))')
    await page.wait_for_timeout(700)
    assert await page.locator('#arrival-panel').is_hidden(),width
    # Mixed condition: one bus has fresh GPS while the other has an old fix.
    mixed=scenario()
    now=datetime.now(timezone.utc)
    mixed['sourceState']='live'
    mixed['vehicles'].append({
       'vehicleId':'synthetic-89','busName':'89','latitude':40.819,'longitude':-73.948,
       'observedAt':fmt(now-timedelta(seconds=5)),'gpsAgeSeconds':5,
       'freshness':'fresh','reportedStatus':'moving','reportedDirection':'SB',
       'reportedNextStopId':'125','locationKind':'third_party_observed'})
    mixed['sourceArrivalEstimates']={
       'source':'student_public','experimental':True,'calibrated':False,
       'generatedAt':fmt(now-timedelta(seconds=5)),
       'stops':{'125':[{
           'vehicleId':'synthetic-89','busName':'89','direction':'SB',
           'arrivalAt':fmt(now+timedelta(minutes=6)),
           'earliestAt':fmt(now+timedelta(minutes=4)),
           'latestAt':fmt(now+timedelta(minutes=8)),
           'providerPredictionsEnabled':False}],
           '135':[],'145':[],'marshak':[]}}
    data['body']=mixed
    await page.evaluate('() => window.dispatchEvent(new Event("online"))')
    await page.wait_for_timeout(750)
    assert await page.locator('.arrival-row').count()==2,(width,await page.locator('#arrival-panel').inner_text())
    assert await page.locator('.arrival-row.is-source-projection').count()==1
    assert await page.locator('.arrival-next-tag').count()==1
    assert 'Mixed GPS quality' in await page.locator('#eta-status').inner_text()
    assert await page.locator('.trip-card').count()==0
    assert not errors,(width,errors)
    print(json.dumps({'width':width,'sourceProjections':True,'noNextBadge':True,
       'oldSourceHidden':True,'oldGPSHidden':True,'errors':errors}),flush=True)
    await ctx.close()

async def main():
 async with async_playwright() as p:
    opts={'headless':True}
    if CHROME:opts.update(executable_path=CHROME,args=['--no-sandbox','--disable-dev-shm-usage'])
    browser=await p.chromium.launch(**opts)
    try:
      for width in (320,390,430,1365):await check(browser,width)
    finally:await browser.close()

if __name__=='__main__':asyncio.run(main())
