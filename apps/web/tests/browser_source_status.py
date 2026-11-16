"""Status semantics: fresh standing vs explicitly inactive vs unknown; stale stays historical."""
import asyncio,json,os
from datetime import datetime,timedelta,timezone
from playwright.async_api import async_playwright
SITE=os.getenv('SHUTTLE_SITE_URL','http://127.0.0.1:9824/')
CHROME=os.getenv('SHUTTLE_CHROMIUM_PATH')

def response(age=5,source_state='live',statuses=('standing_at_stop','inactive')):
    now=datetime.now(timezone.utc)
    fmt=lambda d:d.isoformat().replace('+00:00','Z')
    rows=[]
    for name,status in zip(('88','89'),statuses):
        rows.append({'vehicleId':'synthetic-'+name,'busName':name,'latitude':40.819,'longitude':-73.949,
            'observedAt':fmt(now-timedelta(seconds=age)),
            'gpsAgeSeconds':age,'freshness':'fresh' if age<=30 else 'stale',
            'reportedStatus':status,'reportedDirection':'NB' if name=='88' else 'SB',
            'reportedNextStopId':'145' if name=='88' else '125',
            'locationKind':'third_party_observed'})
    return {'source':'student_public','sourceState':source_state,'transportState':'healthy',
         'generatedAt':fmt(now),'lastSuccessfulPoll':fmt(now),'vehicles':rows,
         'sourceArrivalEstimates':None}

async def check(browser,width):
    ctx=await browser.new_context(viewport={'width':width,'height':844},
      is_mobile=width<760,has_touch=width<760,service_workers='block')
    page=await ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    served={'payload':response()}
    await page.route('**/api/v1/vehicles',lambda route:route.fulfill(status=200,
      content_type='application/json',body=json.dumps(served['payload'])))
    await page.goto(SITE,wait_until='domcontentloaded',timeout=25000)
    await page.locator('.bus-condition').first.wait_for(timeout=7000)
    labels=await page.locator('.bus-condition').all_inner_texts()
    assert 'Standing at stop' in labels and 'Inactive (reported)' in labels,(width,labels)
    assert await page.locator('.bus-condition.is-current').count()==2
    served['payload']=response(age=105,source_state='stale')
    await page.evaluate('() => window.dispatchEvent(new Event("online"))')
    await page.wait_for_timeout(700)
    labels=await page.locator('.bus-condition').all_inner_texts()
    assert 'Last: at stop' in labels and 'Last: inactive' in labels,(width,labels)
    assert await page.locator('.bus-condition.is-current').count()==0
    assert 'Student GPS' in await page.locator('#top-status-label').inner_text()
    assert 'old' in await page.locator('#top-status-label').inner_text()
    served['payload']=response(age=7,source_state='live',statuses=(None,None))
    await page.evaluate('() => window.dispatchEvent(new Event("online"))')
    await page.wait_for_timeout(700)
    labels=await page.locator('.bus-condition').all_inner_texts()
    assert labels==['Status unknown','Status unknown'],(width,labels)
    assert not errors,errors
    assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth+2')
    print(json.dumps({'width':width,'live':['Standing at stop','Inactive (reported)'],
        'stale':['Last: at stop','Last: inactive'],'missingStatus':labels,'errors':errors}),flush=True)
    await ctx.close()

async def main():
    async with async_playwright() as p:
        kw={'headless':True}
        if CHROME:kw.update(executable_path=CHROME,args=['--no-sandbox','--disable-dev-shm-usage'])
        browser=await p.chromium.launch(**kw)
        try:
            for width in (320,390,1365):await check(browser,width)
        finally:await browser.close()

if __name__=='__main__':asyncio.run(main())
