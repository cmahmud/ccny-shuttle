import test from "node:test";
import assert from "node:assert/strict";
import { STOPS, DESTINATIONS, R137, directionsUrl, observedAgeSeconds, validVehicle, evaluateFeed, shortBusId, ago } from "../compact-core-v2.js";
const NOW = Date.parse("2026-11-09T18:40:00Z");
const bus = {
  vehicleId: "89",
  locationKind: "confirmed",
  freshness: "fresh",
  latitude: 40.820,
  longitude: -73.95,
  observedAt: "2026-11-09T18:39:50Z"
};
const live = { generatedAt: "2026-11-09T18:39:59Z", sourceState: "live", transportState: "healthy", vehicles: [bus] };

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
  const result = evaluateFeed({ ...live, vehicles: [{ ...bus, observedAt: "2026-11-09T18:38:00Z" }] }, NOW);
  assert.equal(result.state, "offline");
  assert.deepEqual(result.vehicles, []);
});

test("delayed or stale source remains visibly delayed without bus pins", () => {
  for (const state of ["delayed", "stale"]) {
    const result = evaluateFeed({ ...live, sourceState: state }, NOW);
    assert.equal(result.state, "delayed");
    assert.deepEqual(result.vehicles, []);
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
