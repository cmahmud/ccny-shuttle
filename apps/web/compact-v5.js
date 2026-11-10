import { STOPS, DESTINATIONS, R137, OFFICIAL, directionsUrl, evaluateFeed, observedAgeSeconds, ago, shortBusId } from "./compact-core-v5.js";

const $ = (id) => document.getElementById(id);
let selected = "125";
let destination = "nac";
let map = null;
let stopMarkers = new Map();
let busMarkers = new Map();
let lastResult = { state: "offline", label: "GPS unavailable", message: "Live shuttle positions not connected", vehicles: [] };
let inFlight = false;
const POLL_MS = 15000;

function status(label, state, message) {
  const top = $("top-status");
  top.classList.toggle("is-live", state === "live");
  top.classList.toggle("is-delayed", state === "delayed");
  top.classList.toggle("is-afterhours", state === "afterhours");
  $("top-status-label").textContent = label;
  const line = $("live-line");
  line.classList.toggle("is-live", state === "live");
  line.classList.toggle("is-delayed", state === "delayed");
  line.classList.toggle("is-afterhours", state === "afterhours");
  $("live-message").textContent = message;
  $("eta-description").textContent = state === "live"
    ? "Bus positions available · stop ETAs not calibrated"
    : state === "delayed"
      ? "GPS updates delayed · ETA unavailable"
      : state === "afterhours"
        ? "Outside listed service hours · no ETA"
        : "Waiting for verified GPS data";
}

function stopAreaUrl(stopKey) {
  const stop = STOPS[stopKey];
  return "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(stop.directions);
}

function selectStop(key, focusButton = false) {
  if (!STOPS[key]) return;
  selected = key;
  for (const button of document.querySelectorAll("[data-stop]")) {
    const chosen = button.dataset.stop === key;
    button.classList.toggle("is-selected", chosen);
    button.setAttribute("aria-selected", String(chosen));
    button.tabIndex = chosen ? 0 : -1;
    if (chosen && focusButton) button.focus();
  }
  const stop = STOPS[key];
  $("stop-panel").setAttribute("aria-labelledby", "tab-" + key);
  $("stop-name").textContent = stop.name;
  $("stop-location").textContent = stop.description;
  $("stop-directions").href = stopAreaUrl(key);
  $("stop-warning").textContent = stop.notice;
  $("eta-status").textContent = "ETA unavailable";
  $("eta-value").textContent = "—";
  renderBuses();
  updateWalkLinks();
  highlightMap(key);
}

function updateWalkLinks() {
  const stop = STOPS[selected];
  $("walk-selected").href = directionsUrl(stop.directions, destination) || "#";
  $("walk-137").href = directionsUrl(R137, destination) || "#";
  // Do not claim any option is quicker without a journey comparison model.
  $("trip-hint").textContent = "Walking routes only · shuttle comparison pending live data.";
}

function busRow(bus, now) {
  const row = document.createElement("div");
  row.className = "bus-row";
  const left = document.createElement("strong");
  left.textContent = shortBusId(bus.vehicleId);
  const right = document.createElement("small");
  right.textContent = "Position " + ago(observedAgeSeconds(bus.observedAt, now));
  row.append(left, right);
  return row;
}

function renderBuses() {
  const list = $("vehicle-list");
  list.replaceChildren();
  const buses = ["live", "delayed"].includes(lastResult.state) ? lastResult.vehicles : [];
  if (!buses.length) {
    const placeholder = document.createElement("div");
    placeholder.className = "no-buses";
    placeholder.textContent = lastResult.state === "delayed"
      ? "Recent bus positions are outdated. No arrival estimate."
      : lastResult.state === "afterhours"
        ? "Outside listed shuttle hours. Check the official tracker for exceptions."
        : "No current bus positions. Check the official tracker.";
    list.append(placeholder);
    return;
  }
  const subheading = document.createElement("div");
  subheading.className = "no-buses";
  subheading.textContent = lastResult.state === "delayed"
    ? "Last-known bus reports (not live) · no ETA"
    : lastResult.publicRelay
      ? "Student-tracker bus reports · stop ETA unavailable"
      : "Official GPS positions · stop ETA unavailable";
  list.append(subheading);
  const now = Date.now();
  for (const bus of buses.slice(0, 8)) list.append(busRow(bus, now));
}

function setStatus(result) {
  lastResult = result;
  status(result.label, result.state, result.message);
  renderBuses();
  clearBusMarkers();
  if (["live", "delayed"].includes(result.state) && result.vehicles.length) {
    drawBusMarkers(result.vehicles);
    $("map-update").textContent = result.vehicles.length +
      (result.state === "delayed" ? " last-seen GPS " : result.publicRelay ? " third-party GPS " : " official GPS ") +
      (result.vehicles.length === 1 ? "report" : "reports") +
      (result.state === "delayed" ? " · not live" : "");
  } else {
    $("map-update").textContent = result.state === "delayed" ? "GPS delayed · no recent buses shown" : "No current bus positions";
  }
}

function markerIcon(kind, highlighted = false) {
  const className = kind === "campus" ? "stop-pin campus-pin" : "stop-pin";
  return window.L.divIcon({
    className: "",
    html: '<div class="' + className + '" style="' + (highlighted ? "outline:3px solid #7770ff66;outline-offset:3px;" : "") + 'width:20px;height:20px"></div>',
    iconSize: [22, 22], iconAnchor: [11, 11]
  });
}

function initMap() {
  const container = $("map");
  if (!window.L) {
    container.textContent = "Stop map unavailable. Use Find pickup area to open directions.";
    container.className = "map-placeholder";
    return;
  }
  map = window.L.map(container, { zoomControl: false, scrollWheelZoom: false, attributionControl: true });
  window.L.control.zoom({ position: "topright" }).addTo(map);
  window.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'
  }).addTo(map);
  const bounds = [];
  for (const [key, stop] of Object.entries(STOPS)) {
    if (!stop.point) continue; // Do not fabricate 135th or Marshak coordinates.
    const popup = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = stop.name;
    const desc = document.createElement("div");
    desc.textContent = stop.description + " · approximate area";
    popup.append(title, desc);
    const marker = window.L.marker(stop.point, { icon: markerIcon(stop.kind, key === selected) })
      .bindPopup(popup).on("click", () => selectStop(key));
    marker.addTo(map);
    stopMarkers.set(key, marker);
    bounds.push(stop.point);
  }
  if (bounds.length) map.fitBounds(bounds, { padding: [35, 35], maxZoom: 14 });
  window.addEventListener("resize", () => map.invalidateSize());
  setTimeout(() => map && map.invalidateSize(), 100);
}

function highlightMap(key) {
  if (!map) return;
  for (const [stopKey, marker] of stopMarkers) marker.setIcon(markerIcon(STOPS[stopKey].kind, stopKey === key));
  const stop = STOPS[key];
  if (stop.point) map.setView(stop.point, Math.max(map.getZoom(), 15), { animate: true });
  // For unverified stop geometry, keep the real campus area in view.
  else map.setView(STOPS.nac.point, 15, { animate: true });
}

function clearBusMarkers() {
  if (map) for (const marker of busMarkers.values()) map.removeLayer(marker);
  busMarkers.clear();
}

function drawBusMarkers(buses) {
  if (!map || !window.L) return;
  for (const bus of buses) {
    const popup = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = shortBusId(bus.vehicleId);
    const sub = document.createElement("div");
    sub.textContent = (lastResult.state === "delayed" ? "Last seen (not live)" :
      lastResult.publicRelay ? "Student tracker report" : "Official GPS")
      + " · " + ago(observedAgeSeconds(bus.observedAt)) + " · no stop ETA";
    popup.append(title, sub);
    const icon = window.L.divIcon({
      className: "", html: '<div class="vehicle-pin' + (lastResult.state === "delayed" ? ' last-seen' : lastResult.publicRelay ? ' third-party' : '') + '"></div>',
      iconSize: [20, 20], iconAnchor: [10, 10]
    });
    const marker = window.L.marker([bus.latitude, bus.longitude], { icon }).bindPopup(popup).addTo(map);
    busMarkers.set(bus.vehicleId, marker);
  }
}

async function poll() {
  if (inFlight || document.hidden) return;
  inFlight = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 6500);
  try {
    const resp = await fetch("/api/v1/vehicles", { cache: "no-store", signal: controller.signal });
    if (!resp.ok) throw new Error("Status HTTP " + resp.status);
    const data = await resp.json();
    setStatus(evaluateFeed(data, Date.now()));
  } catch {
    // No stale replay on source loss or network failure.
    setStatus({ state: "offline", label: "GPS unavailable",
      message: navigator.onLine ? "GPS status request failed" : "Your device is offline", vehicles: [] });
  } finally {
    clearTimeout(timeout);
    inFlight = false;
  }
}

function bindStopTabs() {
  const tabs = [...document.querySelectorAll("[data-stop]")];
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectStop(tab.dataset.stop));
    tab.addEventListener("keydown", (event) => {
      const next = event.key === "ArrowRight" ? (index + 1) % tabs.length :
        event.key === "ArrowLeft" ? (index - 1 + tabs.length) % tabs.length :
        event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
      if (next === null) return;
      event.preventDefault();
      selectStop(tabs[next].dataset.stop, true);
    });
  });
}

bindStopTabs();
$("destination-select").addEventListener("change", (event) => {
  if (!DESTINATIONS[event.target.value]) return;
  destination = event.target.value;
  updateWalkLinks();
});
$("map-reset").addEventListener("click", () => {
  if (!map || !window.L) return;
  const points = [...stopMarkers.values()].map((marker) => marker.getLatLng());
  if (points.length) map.fitBounds(window.L.latLngBounds(points), { padding: [35,35], maxZoom: 14 });
});
selectStop("125");
initMap();
poll();
setInterval(() => { if (!document.hidden) poll(); }, POLL_MS);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) { clearBusMarkers(); }
  else poll();
});
window.addEventListener("offline", () => {
  setStatus({ state: "offline", label: "Device offline", message: "No internet · saved stop information only", vehicles: [] });
});
window.addEventListener("online", () => poll());
if ("serviceWorker" in navigator && window.isSecureContext) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/service-worker.js").catch(() => {}));
}
