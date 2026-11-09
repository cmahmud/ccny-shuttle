"use strict";

const API_ENDPOINT = "/api/v1/vehicles";
const SOURCE_URL = "https://cloud.samsara.com/o/4010168/fleet/viewer/FJMjrX1YlqCqlGxIKkXY";
const STOPS = [
  // Coordinates are nearby station/building landmarks, NOT surveyed shuttle boarding points.
  { name: "125th Street", lat: 40.81111, lon: -73.95311, type: "stop", description: "Shuttle stop near Post Office, between St. Nicholas & Morningside" },
  { name: "145th Street", lat: 40.82404, lon: -73.944769, type: "stop", description: "Shuttle stop near Dunkin', between St. Nicholas & Edgecombe" },
  { name: "North Academic Center", lat: 40.8200332, lon: -73.9497487, type: "campus", description: "Campus building near shuttle stop on Convent Avenue" },
];
const CAMPUS_DESTINATIONS = {
  nac: "North Academic Center CCNY New York",
  marshak: "Marshak Science Building City College New York",
  shepard: "Shepard Hall City College New York",
  steinman: "Steinman Hall City College New York",
  spitzer: "Spitzer School of Architecture City College New York",
};
const RECHECK_MS = 15000;
let map = null;
let vehicleMarkers = new Map();
let refreshTimeout = null;

function el(id) { return document.getElementById(id); }
function setText(id, content) { const node = el(id); if (node) node.textContent = content; }
function humanTime(iso) {
  if (!iso || Number.isNaN(Date.parse(iso))) return "Never";
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
function lastConfirmedAge(seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds)) return "Unknown age";
  if (seconds < 60) return Math.floor(seconds) + " seconds ago";
  if (seconds < 3600) return Math.floor(seconds / 60) + " min ago";
  return Math.floor(seconds / 3600) + " hr ago";
}
function encodeDirections(fromName, destinationName) {
  return "https://www.google.com/maps/dir/?api=1&origin=" +
    encodeURIComponent(fromName + ", Manhattan, New York") +
    "&destination=" + encodeURIComponent(destinationName) +
    "&travelmode=walking";
}
function initDestination() {
  const select = el("destination-select");
  if (!select) return;
  select.addEventListener("change", () => {
    const value = CAMPUS_DESTINATIONS[select.value] || CAMPUS_DESTINATIONS.nac;
    const anchors = document.querySelectorAll("[data-walk-link]");
    for (const anchor of anchors) anchor.href = encodeDirections(anchor.dataset.walkLink, value);
  });
  select.dispatchEvent(new Event("change"));
}
function initMap() {
  const container = el("map");
  if (!container) return;
  if (typeof window.L === "undefined") {
    container.innerHTML = '<div class="map-placeholder">Map temporarily unavailable. Use the stop links below for directions.</div>';
    return;
  }
  container.textContent = "";
  map = window.L.map(container, { zoomControl: false, scrollWheelZoom: false });
  window.L.control.zoom({ position: "bottomright" }).addTo(map);
  window.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
    maxZoom: 19,
  }).addTo(map);
  const bounds = window.L.latLngBounds();
  for (const stop of STOPS) {
    const icon = window.L.divIcon({
      className: "",
      html: '<div class="map-pin ' + (stop.type === "campus" ? "map-pin-campus" : "") + '"></div>',
      iconSize: [19, 19],
      iconAnchor: [10, 10],
    });
    window.L.marker([stop.lat, stop.lon], { icon })
      .bindPopup("<strong>" + stop.name + "</strong><div>" + stop.description + "</div><small>Approximate stop area</small>")
      .addTo(map);
    bounds.extend([stop.lat, stop.lon]);
  }
  map.fitBounds(bounds.pad(.22), { maxZoom: 14 });
  window.addEventListener("resize", () => map.invalidateSize());
}
function clearVehicleMarkers() {
  for (const marker of vehicleMarkers.values()) if (map) map.removeLayer(marker);
  vehicleMarkers.clear();
}
function renderVehicles(data) {
  clearVehicleMarkers();
  if (!map || !Array.isArray(data.vehicles)) return;
  const nowMs = Date.parse(data.generatedAt) || Date.now();
  for (const vehicle of data.vehicles) {
    const coords = [Number(vehicle.latitude), Number(vehicle.longitude)];
    if (coords.some(value => !Number.isFinite(value)) || Math.abs(coords[0]) > 90 || Math.abs(coords[1]) > 180) continue;
    const gpsAge = (nowMs - Date.parse(vehicle.observedAt)) / 1000;
    // Never pin a vehicle whose GPS position is already too old to describe its present position.
    if (!Number.isFinite(gpsAge) || gpsAge > 120 || gpsAge < -300 || vehicle.locationKind !== "confirmed") continue;
    const icon = window.L.divIcon({
      className: "",
      html: '<div class="map-pin map-pin-shuttle"></div>',
      iconSize: [19, 19], iconAnchor: [10, 10],
    });
    const marker = window.L.marker(coords, { icon })
      .bindPopup('<strong>Shuttle ' + String(vehicle.vehicleId).replace(/[<>&"]/g, "") +
                 '</strong><div>Confirmed GPS at ' + humanTime(vehicle.observedAt) +
                 '</div><div>Source age: ' + lastConfirmedAge(Math.max(0, gpsAge)) + '</div>')
      .addTo(map);
    vehicleMarkers.set(vehicle.vehicleId, marker);
  }
}
function updateStatus(data) {
  const sourceState = data && typeof data.sourceState === "string" ? data.sourceState : "no_data";
  const transportState = data && typeof data.transportState === "string" ? data.transportState : "never_connected";
  const node = el("top-status");
  const banner = el("source-banner");
  const live = sourceState === "live" && transportState === "healthy" &&
    Array.isArray(data.vehicles) && data.vehicles.some(v => v.freshness === "fresh");
  if (node) {
    node.classList.toggle("live", live);
    node.lastChild.textContent = live ? "GPS connected" : "GPS unavailable";
  }
  if (banner) banner.classList.toggle("connected", live);
  if (live) {
    setText("banner-title", "GPS positions are being received");
    setText("banner-detail", "Confirmed locations can appear on the map. Stop arrival predictions are not available yet.");
    setText("banner-state", "GPS CONNECTED");
  } else {
    setText("banner-title", sourceState === "stale" ? "GPS positions are outdated" : "Live shuttle GPS not connected yet");
    setText("banner-detail", "Arrival estimates are unavailable. For current shuttle positions, use the official CCNY tracker.");
    setText("banner-state", transportState === "offline" ? "COLLECTOR OFFLINE" : "SOURCE OFFLINE");
  }
  setText("refreshed-label", live ? "GPS checked at " + humanTime(data.generatedAt) : "GPS: unavailable");
  renderVehicles(data);
}
async function refreshStatus() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(API_ENDPOINT, { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error("GPS status fetch failed: " + response.status);
    const data = await response.json();
    if (!data || !Array.isArray(data.vehicles)) throw new Error("Invalid status response");
    updateStatus(data);
  } catch (_) {
    clearVehicleMarkers();
    updateStatus({ sourceState: "no_data", transportState: "offline", vehicles: [] });
    setText("banner-detail", "Status service is unreachable. No live arrivals are available. Use the official CCNY tracker.");
  } finally {
    clearTimeout(timeout);
    refreshTimeout = setTimeout(refreshStatus, RECHECK_MS);
  }
}
document.addEventListener("DOMContentLoaded", () => {
  initDestination();
  initMap();
  refreshStatus();
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/service-worker.js").catch(() => {});
    });
  }
  window.addEventListener("beforeunload", () => clearTimeout(refreshTimeout));
});
