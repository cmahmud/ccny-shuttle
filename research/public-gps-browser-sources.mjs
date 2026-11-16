// Public viewer health investigation. No credentials, GPS coordinates, driver data,
// cookies, request bodies, access tokens, or private response content are stored.
import { chromium } from "playwright";

const sources = [
  {name:"official",url:"https://cloud.samsara.com/o/4010168/fleet/viewer/FJMjrX1YlqCqlGxIKkXY"},
  {name:"student",url:"https://ccnyshuttlebus.com/"},
];
const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
try{
  for(const source of sources){
    const ctx=await browser.newContext({serviceWorkers:"block",viewport:{width:1280,height:900}});
    const page=await ctx.newPage();
    const statuses={};const requested={};let fatalErrors=0;
    page.on("response",res=>{
      const status=String(res.status());
      statuses[status]=(statuses[status]||0)+1;
      try{
        const u=new URL(res.url());
        if(source.name==="student" && u.pathname.startsWith("/tracker-data/")){
          requested[u.pathname]=res.status();
        }
        if(source.name==="official" && u.pathname==="/r/graphql"){
          requested["graphql_"+res.status()]=(requested["graphql_"+res.status()]||0)+1;
        }
      }catch{}
    });
    page.on("pageerror",()=>{fatalErrors++;});
    let navStatus="not_reached";
    try{
      const r=await page.goto(source.url,{waitUntil:"domcontentloaded",timeout:30000});
      navStatus=r?.status()??"none";
    }catch(e){navStatus="timeout_or_navigation_failure";}
    await page.waitForTimeout(12000);
    let content="";
    try{content=await page.locator("body").innerText({timeout:4000});}catch{}
    const text=content.toLowerCase();
    // Non-identifying status strings only.
    const states={};
    for(const phrase of ["invalid","expired","unavailable","access denied","not found",
        "loading","no buses","tracker live","tracker offline","bus stops",
        "live tracking","shuttle","sign in","log in","failed to load"]){
      states[phrase]=text.includes(phrase);
    }
    let maps=0;
    try{maps=await page.locator("canvas").count();}catch{}
    console.log(JSON.stringify({source:source.name,navStatus,
      title:(await page.title().catch(()=>"")).slice(0,65),
      bodyLength:content.length,states,httpStatuses:statuses,interfaceStatuses:requested,
      mapsRendered:maps,fatalErrors
    }));
    await ctx.close();
  }
}finally{await browser.close();}
