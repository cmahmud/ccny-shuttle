import test from "node:test";
import assert from "node:assert/strict";
import { movingBearing,  STOPS, DESTINATIONS, R137, directionsUrl, observedAgeSeconds, validVehicle, evaluateFeed, outsideListedHours, knownFleetFromPayload, shortBusId, busDisplayName, reportedBusContext, mapLocation, ago } from "../compact-core-v10.js";
const NOW = Date.parse("2026-11-09T18:40:00Z");
const bus = {
  vehicleId: "89",
  locationKind: "confirmed",
  freshness: "fresh",
  latitude: 40.820,
  longitude: -73.95,
  observedAt: "2026-11-09T18:39:50Z"
};
const live = { source: "samsara", generatedAt: "2026-11-09T18:39:59Z", sourceState: "live", transportState: "healthy", vehicles: [bus] };

test("all tabs have a known, properly described stop", () => {
  assert.deepEqual(Object.keys(STOPS), ["125", "135", "145", "marshak", "nac"]);
  assert.match(STOPS["135"].description, /on request/);
  assert.equal(STOPS["135"].point, null);
  assert.equal(STOPS.marshak.point, null);
  assert.match(STOPS["125"].description, /Post Office/);
  assert.match(STOPS["145"].description, /Dunkin/);
});

test("only verified reference coordinates appear in the map", () => {
  assert.deepEqual(Object.keys(STOPS).filter((id) => STOPS[id].point), ["125", "145", "nac"]);
  for (const stop of Object.values(STOPS)) {
    if (!stop.point) continue;
    assert.ok(Math.abs(stop.point[0]) < 90 && Math.abs(stop.point[1]) < 180);
  }
});

test("walking directions never claim bus ETA", () => {
  const url = new URL(directionsUrl(STOPS["125"].directions, "marshak"));
  assert.equal(url.hostname, "www.google.com");
  assert.equal(url.searchParams.get("travelmode"), "walking");
  assert.match(url.searchParams.get("origin"), /125th/);
  assert.match(url.searchParams.get("destination"), /Marshak/);
  assert.equal(directionsUrl(R137, "nac")?.includes("137th"), true);
  assert.equal(directionsUrl(STOPS["125"].directions, "unknown"), null);
});

test("fresh GPS and healthy transport give live status", () => {
  const result = evaluateFeed(live, NOW);
  assert.equal(result.state, "live");
  assert.equal(result.vehicles.length, 1);
});

test("no GPS cannot be labeled live even when collector is healthy", () => {
  const result = evaluateFeed({ ...live, sourceState: "no_data", vehicles: [] }, NOW);
  assert.equal(result.state, "offline");
});

test("disconnected transport cannot show GPS even with fresh vehicle", () => {
  const result = evaluateFeed({ ...live, transportState: "offline" }, NOW);
  assert.equal(result.state, "offline");
  assert.deepEqual(result.vehicles, []);
});

test("stale API response cannot masquerade as current GPS", () => {
  const result = evaluateFeed({ ...live, generatedAt: "2026-11-09T18:38:00Z" }, NOW);
  assert.equal(result.state, "offline");
});

test("GPS older than 30 seconds is not shown as live", () => {
  const result = evaluateFeed({ ...live, vehicles: [{ ...bus, freshness:"delayed", observedAt: "2026-11-09T18:38:00Z" }] }, NOW);
  assert.equal(result.state, "delayed");
  assert.equal(result.vehicles.length, 1);
  assert.match(result.message, /not live/);
});

test("delayed or stale source remains visibly delayed without bus pins", () => {
  for (const state of ["delayed", "stale"]) {
    const result = evaluateFeed({ ...live, sourceState: state }, NOW);
    assert.equal(result.state, "delayed");
    assert.equal(result.vehicles.length, 1);
    assert.match(result.message, /not live/);
  }
});

test("reject malformed, unconfirmed, or invalid vehicles", () => {
  assert.equal(validVehicle({ ...bus, locationKind: "predicted" }, NOW), false);
  assert.equal(validVehicle({ ...bus, latitude: 120 }, NOW), false);
  assert.equal(validVehicle({ ...bus, longitude: NaN }, NOW), false);
  assert.equal(validVehicle({ ...bus, observedAt: "invalid" }, NOW), false);
  assert.equal(validVehicle({ ...bus, observedAt: "2026-11-09T18:40:10Z" }, NOW), false);
  assert.equal(observedAgeSeconds("invalid", NOW), Infinity);
});

test("unknown or empty API responses fail closed", () => {
  for (const bad of [null, undefined, {}, { generatedAt: "bad", vehicles: [] }, { generatedAt: "2026-11-09T18:39:59Z", vehicles: "bad" }]) {
    assert.equal(evaluateFeed(bad, NOW).state, "offline");
  }
});

test("bus ID and duration formatting are conservative", () => {
  assert.equal(shortBusId("vehicle-123456"), "Bus ···23456");
  assert.equal(ago(40), "40s ago");
  assert.equal(ago(180), "3m ago");
  assert.equal(ago(-5), "unknown");
});

test("fresh third-party reports are labeled and never mistaken for official GPS", () => {
  const report = {...bus, locationKind:"third_party_observed"};
  const feed = {...live, source:"student_public", vehicles:[report]};
  const state=evaluateFeed(feed,NOW);
  assert.equal(state.state,"live");
  assert.equal(state.publicRelay,true);
  assert.equal(state.vehicles.length,1);
  assert.match(state.message,/student tracker/);
  assert.deepEqual(evaluateFeed({...feed,source:"samsara"},NOW).vehicles,[]);
  const old=evaluateFeed({...feed,vehicles:[{...report,observedAt:"2026-11-09T18:38:00Z",freshness:"delayed"}]},NOW);
  assert.equal(old.state,"delayed");
  assert.equal(old.vehicles.length,1);
});

test("last-known third-party vehicle remains labeled delayed then expires", () => {
  const report = {...bus, locationKind:"third_party_observed",
    observedAt:"2026-11-09T18:37:40Z",freshness:"stale"};
  const feed = {...live, source:"student_public", sourceState:"stale",vehicles:[report]};
  const delayed=evaluateFeed(feed,NOW);
  assert.equal(delayed.state,"delayed");
  assert.equal(delayed.vehicles.length,1);
  assert.match(delayed.message,/not live/);
  const expired=evaluateFeed({...feed,vehicles:[{...report,observedAt:"2026-11-09T18:30:00Z"}]},NOW);
  assert.equal(expired.vehicles.length,0);
});

test("off hours are calculated in New York, not client timezone", () => {
  assert.equal(outsideListedHours(Date.parse("2026-11-10T03:17:00Z")),true); // Mon 10:17 PM ET
  assert.equal(outsideListedHours(Date.parse("2026-11-09T18:40:00Z")),false);
  assert.equal(outsideListedHours(Date.parse("2026-11-09T11:20:00Z")),true); // Mon 6:20 AM
  assert.equal(outsideListedHours(Date.parse("2026-11-09T11:30:00Z")),false);
  assert.equal(outsideListedHours(Date.parse("2026-11-10T03:00:00Z")),true); // exactly 10 PM
  assert.equal(outsideListedHours(Date.parse("2026-11-08T18:00:00Z")),true); // Sunday
});

test("afterhours stale GPS is unavailable, not misrepresented as a live bus", () => {
  const now=Date.parse("2026-11-10T03:17:00Z");
  const old={...bus,observedAt:"2026-11-10T01:09:33Z",freshness:"stale"};
  const data={source:"student_public",generatedAt:"2026-11-10T03:16:59Z",
    sourceState:"stale",transportState:"offline",vehicles:[{...old,locationKind:"third_party_observed"}]};
  const result=evaluateFeed(data,now);
  assert.equal(result.state,"afterhours");
  assert.equal(result.vehicles.length,0);
  assert.match(result.message,/last bus report 2h ago/);
});

test("genuinely fresh GPS still appears live after listed closing time", () => {
  const now=Date.parse("2026-11-10T03:17:00Z");
  const data={...live,generatedAt:"2026-11-10T03:16:59Z",vehicles:[
    {...bus,observedAt:"2026-11-10T03:16:55Z"}
  ]};
  assert.equal(evaluateFeed(data,now).state,"live");
});

test("previously seen buses remain discoverable when all tracking is offline", () => {
  const now = Date.parse("2026-11-10T07:47:00Z");
  const snapshot = {
    source:"student_public", generatedAt:"2026-11-10T07:46:59Z",
    sourceState:"stale", transportState:"offline",
    vehicles:[
      {...bus, vehicleId:"281475002677140",locationKind:"third_party_observed",
        observedAt:"2026-11-10T01:05:38Z",freshness:"stale"},
      {...bus, vehicleId:"281475002677146",locationKind:"third_party_observed",
        observedAt:"2026-11-10T01:09:33Z",freshness:"stale"}
    ]
  };
  const fleet = knownFleetFromPayload(snapshot,now);
  assert.equal(fleet.length,2);
  assert.equal(fleet[0].vehicleId,"281475002677146");
  assert.ok(fleet.every((v) => v.ageSeconds > 6*3600));
  assert.equal(evaluateFeed(snapshot,now).vehicles.length,0);
});

test("historical fleet rejects unknown provenance, expired or invalid fixes", () => {
  const report={...bus,locationKind:"third_party_observed"};
  const snapshot={...live,source:"student_public",vehicles:[report]};
  assert.equal(knownFleetFromPayload(snapshot,NOW).length,1);
  assert.deepEqual(knownFleetFromPayload({...snapshot,source:"unknown"},NOW),[]);
  assert.deepEqual(knownFleetFromPayload({...snapshot,vehicles:[{...report,latitude:99}]},NOW),[]);
  assert.deepEqual(knownFleetFromPayload({...snapshot,vehicles:[{...report,observedAt:"2026-10-01T00:00:00Z"}]},NOW),[]);
  assert.equal(knownFleetFromPayload({...snapshot,vehicles:[report,report]},NOW).length,1);
});

test("source-reported bus number, direction and standing status display only when fresh", () => {
  const b = {...bus, busName:"88", reportedDirection:"NB", reportedStatus:"standing",
    reportedNextStopId:"145"};
  assert.equal(busDisplayName(b),"Bus 88");
  assert.equal(reportedBusContext(b,NOW),"Northbound · At stop · Next: 145th St");
  assert.equal(reportedBusContext({...b,freshness:"stale"},NOW),"");
  assert.equal(reportedBusContext({...b,observedAt:"2026-11-09T18:30:00Z"},NOW),"");
  assert.equal(busDisplayName({...b,busName:"not a number"}),shortBusId(b.vehicleId));
});

test("stationary GPS visual stabilizer does not alter raw readings", () => {
  const original = {...bus,reportedStatus:"standing",freshness:"fresh",
    displayPosition:{latitude:40.82002,longitude:-73.95002,method:"stationary_median",sampleCount:3,displacementMeters:2}};
  const pos=mapLocation(original,NOW);
  assert.equal(pos.smoothed,true);
  assert.equal(pos.latitude,40.82002);
  assert.equal(original.latitude,bus.latitude);
  assert.equal(mapLocation({...original,reportedStatus:"moving"},NOW).smoothed,false);
  assert.equal(mapLocation({...original,freshness:"stale"},NOW).smoothed,false);
  assert.equal(mapLocation({...original,displayPosition:{...original.displayPosition,latitude:40.825}},NOW).smoothed,false);
  assert.equal(mapLocation({...original,displayPosition:{...original.displayPosition,sampleCount:1}},NOW).smoothed,false);
});


test("directional arrow requires source-reported fresh motion and valid heading", () => {
  const b={...bus,reportedStatus:"moving",freshness:"fresh",headingDegrees:271};
  assert.equal(movingBearing(b,NOW),271);
  assert.equal(movingBearing({...b,headingDegrees:0},NOW),0);
  assert.equal(movingBearing({...b,reportedStatus:"standing"},NOW),null);
  assert.equal(movingBearing({...b,headingDegrees:null},NOW),null);
  assert.equal(movingBearing({...b,headingDegrees:400},NOW),null);
  assert.equal(movingBearing({...b,freshness:"stale"},NOW),null);
  assert.equal(movingBearing({...b,observedAt:"2026-10-02T12:00:00Z"},NOW),null);
});
