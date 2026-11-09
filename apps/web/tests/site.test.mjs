import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const here = new URL("../", import.meta.url);
const read = (name) => readFileSync(new URL(name, here), "utf8");
const html = read("index.html");
const css = read("alpha-v3.css");
const js = read("app.js");
const worker = read("service-worker.js");
const manifest = JSON.parse(read("manifest.webmanifest"));

test("landing page has a documented independent GPS state", () => {
  assert.match(html, /Live shuttle GPS not connected yet/);
  assert.match(html, /Not enough live data yet/);
  assert.match(html, /ETA unavailable/);
  assert.match(html, /Not affiliated with CCNY/);
  assert.match(html, /cloud\.samsara\.com\/o\/4010168/);
});

test("served CSS, JS, manifest, and service-worker filenames agree", () => {
  for (const name of ["alpha-v3.css", "app.js", "manifest.webmanifest", "service-worker.js"]) {
    assert.ok(html.includes(name) || (name === "service-worker.js" && js.includes(name)), name);
  }
  assert.match(css, /\.map-panel\b/);
  assert.match(css, /\.alert-banner\b/);
  assert.ok(manifest.start_url === "/" || manifest.start_url === "/index.html");
});

test("all runtime queried DOM IDs exist in the page", () => {
  const required = [...js.matchAll(/\bel\(\"([^\"]+)\"\)/g)].map((x) => x[1]);
  for (const id of required) assert.match(html, new RegExp('id="' + id + '"'));
});

test("stylesheet covers the named visual classes", () => {
  const classes = [...html.matchAll(/class="([^"]+)"/g)]
    .flatMap((m) => m[1].split(/\s+/).filter(Boolean));
  const ignored = new Set(["site-shell", "next-panel"]);
  const missing = [...new Set(classes)].filter((cl) => !ignored.has(cl)
      && !css.includes("." + cl));
  assert.deepEqual(missing, [], "missing styling for " + missing.join(", "));
});

test("GPS status API path matches the dedicated Nginx route", () => {
  assert.match(js, /const API_ENDPOINT = "\/api\/v1\/vehicles"/);
  assert.match(js, /fetch\(API_ENDPOINT, \{ cache: "no-store"/);
  assert.match(js, /locationKind !== "confirmed"/);
  assert.match(js, /gpsAge > 120/);
  assert.match(js, /sourceState === "live" && transportState === "healthy"/);
});

test("service worker never caches GPS API responses", () => {
  assert.match(worker, /url\.pathname\.startsWith\("\/api\/"\)/);
  assert.match(worker, /if \(url\.pathname\.startsWith/);
  assert.doesNotMatch(worker, /\bBearer\s+[a-zA-Z0-9_-]+/);
});

test("official stops remain clearly labeled approximate on map", () => {
  assert.match(js, /Coordinates are nearby station\/building landmarks, NOT surveyed shuttle boarding points/);
  assert.match(html, /Stop pins are approximate/);
  assert.match(html, /125th Street/);
  assert.match(html, /145th Street/);
});
