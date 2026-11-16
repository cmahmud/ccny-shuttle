"""Browser smoke for compact CCNY academic schedule notices (synthetic time)."""
import asyncio,json,os
from datetime import datetime,timezone
from playwright.async_api import async_playwright
SITE=os.getenv('SHUTTLE_SITE_URL','http://127.0.0.1:9819/')
CHROME=os.getenv('SHUTTLE_CHROMIUM_PATH','/opt/ccny-shuttle/runtime/chromium-1228/chrome-linux/chrome')

async def main():
  async with async_playwright() as playwright:
    browser=await playwright.chromium.launch(executable_path=CHROME,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
    try:
      for width in (320,390,430,1365):
        context=await browser.new_context(viewport={'width':width,'height':844},is_mobile=width<760,has_touch=width<760,service_workers='block')
        page=await context.new_page()
        # A deterministic clock prevents this one-day exception test expiring.
        await page.clock.install(time=datetime(2026,11,11,17,0,tzinfo=timezone.utc))
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        await page.route('**/api/v1/vehicles',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps({'source':'student_public','sourceState':'stale','transportState':'healthy','vehicles':[]})))
        await page.goto(SITE,wait_until='domcontentloaded',timeout=30000)
        await page.locator('#service-advisory-title').wait_for(state='visible',timeout=7000)
        title=await page.locator('#service-advisory-title').inner_text()
        detail=await page.locator('#service-advisory-detail').inner_text()
        assert title=='No shuttle service reported', (width,title)
        assert 'Veterans Day' in detail and 'not confirmed' in detail
        assert await page.locator('#service-advisory-link').get_attribute('href')=='https://www.ccny.cuny.edu/about/gettingthere'
        results=await page.evaluate("""async () => {
          const mod=await import('/service-calendar-v1.js');
          const noon=d=>new Date(`${d}T17:00:00.000Z`);
          return {
            nextDay:mod.serviceNotice(noon('2026-11-12')),
            fall:mod.serviceNotice(noon('2026-11-26')),
            spring:mod.serviceNotice(noon('2027-04-23')),
            weekend:mod.serviceNotice(noon('2026-11-14')),
            liveOverride:mod.serviceNotice(noon('2026-11-11'),true),
            utcBoundary:mod.serviceNotice(new Date('2026-11-12T02:00:00Z')),
            overflow:document.documentElement.scrollWidth>window.innerWidth+2,
            noticeHeight:document.querySelector('#service-advisory').getBoundingClientRect().height,
          };
        }""")
        assert results['nextDay'] is None and results['liveOverride'] is None
        assert results['fall']['kind']=='calendar' and results['spring']['kind']=='recess'
        assert results['weekend']['kind']=='weekend' and results['utcBoundary']['kind']=='reported'
        assert not results['overflow'],results
        assert results['noticeHeight']<120,results
        assert not errors,errors
        print(json.dumps({'width':width,'notice':title,'height':round(results['noticeHeight']),'overflow':results['overflow'],'jsErrors':len(errors)}),flush=True)
        await context.close()
    finally:await browser.close()

if __name__=='__main__':asyncio.run(main())
