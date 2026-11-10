import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
const read = (name) => readFileSync(new URL("../" + name, import.meta.url), "utf8");
const html = read("index.html");
const css = read("compact-v5.css");
const js = read("compact-v6.js");
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
  assert.match(html, /\/compact-v5\.css/);
  assert.match(html, /\/compact-v6\.js/);
  assert.match(js, /\.\/compact-core-v6\.js/);
  assert.match(html, /\/service-worker\.js|\/compact-v6\.js/);
  for (const file of ["compact-v5.css","compact-v6.js","compact-core-v6.js"]) {
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
  assert.match(html, /Pins are approximate/);
  assert.match(js, /location|validVehicle|evaluateFeed/);
  assert.match(js, /No current bus positions/);
  assert.doesNotMatch(html, /\b\d+ min to (?:125th|145th)/);
});

test("offline caching never stores current GPS", () => {
  assert.match(worker, /url\.pathname\.startsWith\("\/api\/"\)/);
  assert.match(worker, /ccny-smart-shuttle-compact-v6/);
  assert.doesNotMatch(worker,/APP_SHELL[^;]*\/api\/v1\/vehicles/s);
});

test("documented official tracker, service hours, and directions present", () => {
  assert.match(html,/cloud\.samsara\.com\/o\/4010168/);
  assert.match(html,/6:30 AM–10 PM/);
  assert.match(html,/Independent student project/);
  assert.match(js,/directionsUrl/);
});

test("active module dependencies use JS served with the correct MIME type", () => {
  assert.match(html, /\/compact-v6\.js/);
  assert.match(js, /\.\/compact-core-v6\.js/);
  assert.doesNotMatch(js, /from \"[^\"]+\.mjs\"/);
  assert.doesNotMatch(worker, /\/compact-core\.mjs/);
});

test("previously seen shuttles are discoverable but do not get live ETAs", () => {
  assert.match(html,/id="map-history"/);
  assert.match(html,/aria-pressed="false"/);
  assert.match(js,/Not currently reporting/);
  assert.match(js,/Not reporting ≠ confirmed inactive/);
  assert.match(js,/historical GPS pins shown · NOT current locations/);
  assert.match(js,/knownFleetFromPayload/);
});
