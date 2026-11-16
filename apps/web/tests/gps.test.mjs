import test from "node:test";
import assert from "node:assert/strict";
import { classifySnapshot, verifiedVehicles, readableAge, nyTime, directionsUrl } from "../gps.js";

const goodVehicle = Object.freeze({
  vehicleId: "only-shuttle",
  latitude: 40.818,
  longitude: -73.95,
  freshness: "fresh",
  observedAt: "2026-11-09T17:00:00Z",
  gpsAgeSeconds: 12,
  locationKind: "confirmed",
});
test("fresh transport without a fresh GPS event is not labeled live", () => {
  assert.equal(classifySnapshot({ transportState: "healthy", sourceState: "no_data", vehicles: [] }).status, "offline");
});
test("fresh actual GPS and healthy transport is labeled live", () => {
  assert.equal(classifySnapshot({ transportState: "healthy", sourceState: "live", vehicles: [goodVehicle] }).status, "live");
});
test("transport outage overrides stale live signal", () => {
  assert.equal(classifySnapshot({ transportState: "offline", sourceState: "live", vehicles: [goodVehicle] }).status, "offline");
});
test("bad responses fail closed", () => {
  for (const value of [null, {}, { vehicles: "wrong" }, undefined]) {
    assert.equal(classifySnapshot(value).status, "error");
  }
});
test("only confirmed coordinates are accepted", () => {
  const snapshot = { vehicles: [
    goodVehicle, {...goodVehicle, vehicleId: "predicted", locationKind: "predicted"},
    {...goodVehicle, vehicleId: "bad-lat", latitude: 100},
    {...goodVehicle, vehicleId: "bad-freshness", freshness: "none"},
    {...goodVehicle, vehicleId: "bad-lon", longitude: NaN},
  ] };
  assert.deepEqual(verifiedVehicles(snapshot).map(v => v.id), ["only-shuttle"]);
});
test("age formatting is conservative", () => {
  assert.equal(readableAge(59.7), "59s ago");
  assert.equal(readableAge(120), "2m ago");
  assert.equal(readableAge(3600), "1h ago");
  assert.equal(readableAge(-7), "Unknown");
});
test("timezone formatting does not depend on server zone", () => {
  assert.equal(nyTime("2026-11-09T17:00:00Z"), "12:00 PM");
  assert.equal(nyTime("invalid"), "—");
});
test("walking links point to configured stops and destinations", () => {
  const url = new URL(directionsUrl("145", "marshak"));
  assert.equal(url.hostname, "www.google.com");
  assert.equal(url.searchParams.get("travelmode"), "walking");
  assert.match(url.searchParams.get("origin"), /145th Street/);
  assert.match(url.searchParams.get("destination"), /Marshak/);
  assert.equal(directionsUrl("unknown", "nac"), null);
  assert.equal(directionsUrl("145", "unknown"), null);
});
