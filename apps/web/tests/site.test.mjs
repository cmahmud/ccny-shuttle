import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
const read = (name) => readFileSync(new URL("../" + name, import.meta.url), "utf8");
const html = read("index.html");
const css = read("compact-v15.css");
const js = read("compact-v19.js");
const worker = read("service-worker.js");

test("single compact tracker has no large hero or multi-page navigation", () => {
  assert.match(html, /class="shell dashboard"/);
  assert.match(html, /id="stop-tabs"/);
  assert.match(html, /id="map"/);
  assert.match(html, /id="stop-panel"/);
  assert.match(html, /id="destination-select"/);
  assert.doesNotMatch(html, /class="hero"/);
  assert.doesNotMatch(html, /#about|#stops|#how-it-works/);
});

test("five fully functional stop tabs have accessible controls", () => {
  for (const id of ["125", "135", "marshak", "145", "nac"]) {
    assert.match(html, new RegExp('id="tab-' + id + '"'));
    assert.match(html, new RegExp('data-stop="' + id + '"'));
  }
  assert.match(html, /role="tablist"/);
  assert.match(html, /role="tabpanel"/);
  assert.match(js, /event\.key === "ArrowRight"/);
  assert.match(js, /selectStop\(tab\.dataset\.stop\)/);
});

test("page has one map and compact responsive mobile layout", () => {
  assert.equal((html.match(/id="map"/g)||[]).length,1);
  assert.match(css, /@media \(max-width: 760px\)/);
  assert.match(css, /@media \(max-width: 450px\)/);
  assert.match(css, /\.stop-tabs\{display:flex;overflow-x:auto/);
  assert.match(css, /\.main-grid\{display:flex;flex-direction:column/);
  assert.match(css, /\.stop-card\{order:1/);
});

test("HTML references deployed versioned assets", () => {
  assert.match(html, /\/compact-v14\.css/);
  assert.match(html, /\/compact-v19\.js/);
  assert.match(js, /\.\/compact-core-v10\.js/);
  assert.match(html, /\/service-worker\.js|\/compact-v19\.js/);
  for (const file of ["compact-v15.css","compact-v19.js","compact-core-v10.js"]) {
    assert.ok(worker.includes("/" + file),file);
  }
});

test("all IDs needed for UI updates exist in markup", () => {
  for (const match of js.matchAll(/\$\("([^"]+)"\)/g)) {
    assert.match(html, new RegExp('id="' + match[1] + '"'),"missing " + match[1]);
  }
});

test("no guesses about ETAs or fake bus positions", () => {
  assert.match(html, /ETA unavailable/);
  assert.match(js, /Live shuttle positions not connected/);
  assert.match(html, /map-route-source/);
  assert.match(js, /location|validVehicle|evaluateFeed/);
  assert.match(js, /No current bus positions/);
  assert.doesNotMatch(html, /\b\d+ min to (?:125th|145th)/);
});

test("offline caching never stores current GPS", () => {
  assert.match(worker, /url\.pathname\.startsWith\("\/api\/"\)/);
  assert.match(worker, /ccny-smart-shuttle-compact-v19/);
  assert.doesNotMatch(worker,/APP_SHELL[^;]*\/api\/v1\/vehicles/s);
});

test("documented official tracker, service hours, and directions present", () => {
  assert.match(html,/cloud\.samsara\.com\/o\/4010168/);
  assert.match(html,/6:30 AM–10 PM/);
  assert.match(html,/Independent student project/);
  assert.match(js,/directionsUrl/);
});

test("active module dependencies use JS served with the correct MIME type", () => {
  assert.match(html, /\/compact-v19\.js/);
  assert.match(js, /\.\/compact-core-v10\.js/);
  assert.doesNotMatch(js, /from \"[^\"]+\.mjs\"/);
  assert.doesNotMatch(worker, /\/compact-core\.mjs/);
});

test("previously seen shuttles are discoverable but do not get live ETAs", () => {
  assert.match(html,/id="map-history"/);
  assert.match(html,/aria-pressed="true"/);
  assert.match(js,/Last reported GPS/);
  assert.match(js,/Not live or confirmed inactive/);
  assert.match(js,/last-reported GPS location/);
  assert.match(js,/knownFleetFromPayload/);
});


test("one-tap bus navigation and accessible mobile map shortcuts exist", () => {
  assert.match(html, /id="map-buses"/);
  assert.match(html, /id="map-card"/);
  assert.match(js, /focusBusOnMap/);
  assert.match(js, /focusAllReportingBuses/);
  assert.match(js, /row\.addEventListener\("click"/);
  assert.match(css, /\.vehicle-pin\.reporting-bus/);
  assert.match(css, /\.card-bar-title \.meta \{display:none\}/);
});

test("visible tab polls local GPS status faster without touching upstream directly", () => {
  assert.match(js,/const POLL_MS = 5000;/);
  assert.match(js,/if \(!document.hidden\) poll\(\)/);
  assert.match(js,/fetch\("\/api\/v1\/vehicles"/);
});

test("last reported buses display their original positions by default", () => {
  assert.match(js, /let showHistoricalPins = true/);
  assert.match(js, /drawHistoricalMarkers\(historyCandidates\)/);
  assert.match(js, /focusHistoricalBusOnMap/);
  assert.match(js, /historical-bus-button/);
  assert.match(js, /lastReportedClock/);
  assert.match(css, /\.vehicle-pin\.historical-pin span/);
  assert.match(html, /Last GPS/);
});

test("GPS update outages preserve historical positions but never claim they are live", () => {
  assert.match(js, /restoreLastPositions\(\)/);
  assert.match(js, /sessionStorage\.setItem/);
  assert.match(js, /Last known positions shown · NOT live GPS/);
  assert.match(js, /validCachedFleet/);
  assert.match(js, /drawHistoricalMarkers/);
  assert.match(js, /existing\.setPopupContent\(popup\)/);
});


test("overlapping historical GPS pins have exact anchors and offset visual labels", () => {
  assert.match(js,/function labelPositionFor/);
  assert.match(js,/distanceBetweenReportedPoints/);
  assert.match(js,/iconSize: \[12,12\], iconAnchor: \[6,6\]/);
  assert.match(css,/\.history-anchor/);
  assert.match(css,/\.historical-pin\.label-sw/);
});


test("northbound and southbound route overlays are source attributed", () => {
  assert.match(js, /ROUTE_PATHS, ROUTE_STOPS, ROUTE_SOURCE/);
  assert.match(js, /drawRoutes\(\)/);
  assert.match(js, /lineCap:"round"/);
  assert.match(html,/route-legend north/);
  assert.match(html,/map-route-source/);
});
test("fresh source moving buses use bearing arrows, not inferred historical motion", () => {
  assert.match(js,/movingBearing\(bus\)/);
  assert.match(js,/vehicle-arrow-wrap/);
  assert.match(js,/lastResult.state==="live"/);
  assert.match(css,/\.vehicle-arrow/);
});


test("map defaults to full route overview while preserving manual bus focus", () => {
  assert.match(js,/function fitRouteOverview/);
  assert.match(js,/map\.getBounds\(\)/);
  assert.match(js,/\$\("map-reset"\)\.addEventListener\("click", fitRouteOverview\)/);
  assert.match(js,/routeStopMarkers\.set\(key,marker\)/);
});


test("quiet UI hides uncalibrated empty ETA panel without removing accessible status or source", () => {
  assert.match(html, /id="eta-hero" hidden/);
  assert.match(css, /\.eta-hero\[hidden\]\{display:none!important\}/);
  assert.match(html, /id="live-line" aria-live="polite"/);
  assert.match(css, /\.tracker-top \.live-line\.sr-only/);
  assert.match(js, /"Buses on route"/);
  assert.match(html, /id="top-status"/);
  assert.match(html, /id="service-advisory"/);
  assert.match(html, /id="map-route-source"/);
});

test("map buttons hide only when disabled, leaving active map controls accessible", () => {
  assert.match(css, /\.map-actions \.icon-button:disabled\{display:none\}/);
  assert.match(html, /id="map-history"/);
  assert.match(html, /id="map-buses"/);
  assert.match(js, /focusBusOnMap/);
});


test("source-only experimental arrivals have their own labeled panel and clock control",()=>{
  assert.match(html,/id="arrival-panel"/);
  assert.doesNotMatch(html,/id="arrival-clock"/);
  assert.match(html,/Minutes \+ clock time/);
  assert.match(html,/id="arrival-more"/);
  assert.match(js,/sourceArrivalEstimates/);
  assert.match(js,/Experimental times/);
  assert.match(js,/Unverified estimates/);
  assert.match(worker,/\/arrival-ui-v2\.js/);
});

test("arrival highlight, combined times, and stale warning never claim calibration", () => {
  assert.match(js,/arrival-next-tag/);
  assert.match(js,/arrival-clock-time/);
  assert.match(js,/STALE_ARRIVAL_GRACE_MS/);
  assert.match(js,/Last predicted/);
  assert.match(css,/\.arrival-row\.is-next/);
  assert.match(css,/\.arrival-panel\.is-stale/);
});


test("uncertainty comes from source earliest/latest, never invented GPS",()=>{
  assert.match(js,/sourceArrivalWindow/);
  assert.match(js,/arrival-source-window/);
  assert.match(css,/\.arrival-source-window/);
  assert.match(js,/sourceBusStatus/);
  assert.match(css,/\.bus-condition/);
  assert.match(js,/Student GPS/);
});
