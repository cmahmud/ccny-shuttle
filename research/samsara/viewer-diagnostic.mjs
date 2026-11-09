// One-shot observation of publicly shared Samsara fleet viewer network metadata.
// DO NOT log session tokens, cookies, response bodies, coordinates, or driver data.
import { chromium } from "playwright";
const url = "https://cloud.samsara.com/o/4010168/fleet/viewer/FJMjrX1YlqCqlGxIKkXY";
const browser = await chromium.launch({headless: true, args: ["--no-sandbox"]});
let errors=0;
const counts=new Map();
const patterns=new Map();
const protocols={xhr:0,fetch:0,websocket:0,eventsource:0,other:0};
const graphqlResponses=[];
const websocketFrames={received:0,sent:0};
function safePath(raw) {
  try {
    const u=new URL(raw);
    const path=u.pathname.split("/").map(segment=>{
      if (/^\d{3,}$/.test(segment) || /^[A-Za-z0-9_-]{16,}$/.test(segment) || /^[0-9a-fA-F-]{24,}$/.test(segment)) return ":redacted";
      return segment.replace(/[?&#]/g,"");
    }).join("/");
    return u.hostname+path.slice(0,160);
  }catch {return "invalid-url";}
}
try {
  const context=await browser.newContext({serviceWorkers:"block"});
  const page=await context.newPage();
  page.on("request",(request)=>{
    const kind=request.resourceType();
    if(["xhr","fetch","websocket","eventsource"].includes(kind)) {
      protocols[kind]++;
      const key=safePath(request.url())+" ["+kind+"]";
      patterns.set(key,(patterns.get(key)||0)+1);
    }else {
      protocols.other++;
    }
    try{
      const host=new URL(request.url()).hostname;
      counts.set(host,(counts.get(host)||0)+1);
    }catch{}
  });
  page.on("requestfailed",(request)=>{errors++;});
  page.on("websocket",(socket)=>{
    protocols.websocket++;
    socket.on("framereceived",()=>{websocketFrames.received++;});
    socket.on("framesent",()=>{websocketFrames.sent++;});
  });
  page.on("response", async(response)=>{
    try{
      const u=new URL(response.url());
      if(u.hostname !== "us4-ws.cloud.samsara.com" || u.pathname !== "/r/graphql") return;
      const record={status:response.status(),contentType:(response.headers()["content-type"]||"").split(";")[0]};
      if(record.contentType.includes("json")){
        const json=await response.json();
        record.topLevelKeys=Object.keys(json||{}).slice(0,12);
        record.dataFields=json?.data&&typeof json.data==="object"?Object.keys(json.data).slice(0,12):[];
        record.errorCount=Array.isArray(json?.errors)?json.errors.length:0;
        record.dataPresent=Boolean(json?.data);
      }
      graphqlResponses.push(record);
    }catch {graphqlResponses.push({status:"unreadable"});}
  });
  let navigation;
  try{
    navigation=await page.goto(url,{waitUntil:"domcontentloaded",timeout:30000});
    await page.waitForTimeout(15000);
  }catch(error){console.log("Navigation failed:",error.name,"(no retry or bypass attempted)");}
  console.log("Viewer navigation HTTP:",navigation?.status()??"not reached");
  console.log("Page title:",(await page.title().catch(()=>"unknown")).slice(0,100));
  console.log("Network request counts by host:",JSON.stringify(Object.fromEntries(counts)));
  console.log("Dynamic transport counts:",JSON.stringify(protocols));
  console.log("Dynamic request path patterns (sanitized; no query params):",JSON.stringify([...patterns].slice(0,30)));
  console.log("Request failures:",errors);
  console.log("GraphQL response structure (metadata only):",JSON.stringify(graphqlResponses));
  console.log("WebSocket frame counts (no payloads):",JSON.stringify(websocketFrames));
  // No screenshots, saved HTML, tokens, or response payloads.
  await context.close();
}finally{await browser.close();}
