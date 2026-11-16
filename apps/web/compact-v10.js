import { STOPS, DESTINATIONS, R137, OFFICIAL, directionsUrl, evaluateFeed, observedAgeSeconds, ago, shortBusId, knownFleetFromPayload, busDisplayName, reportedBusContext, mapLocation } from "./compact-core-v9.js";

const $ = (id) => document.getElementById(id);
let selected = "125";
let destination = "nac";
let map = null;
let stopMarkers = new Map();
let busMarkers = new Map();
let historicalMarkers = new Map();
let knownFleet = [];
let showHistoricalPins = false;
let lastResult = { state: "offline", label: "GPS unavailable", message: "Live shuttle positions not connected", vehicles: [] };
let inFlight = false;
// Public GPS is already source-timestamped and normally sampled ~12s apart.
 // 5s status refresh reduces *our own UI lag* without polling the source.
const POLL_MS = 5000;

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
  // A real button lets a phone user jump directly from a reported bus
  // to its map marker; the displayed age is never an ETA.
  const row = document.createElement("button");
  row.type = "button";
  row.className = "bus-row bus-row-button";
  const name = busDisplayName(bus);
  const context = reportedBusContext(bus, now);
  row.setAttribute("aria-label", "Locate " + name
    + " on map; GPS last reported " + ago(observedAgeSeconds(bus.observedAt, now))
    + (context ? "; " + context : ""));
  row.addEventListener("click", () => focusBusOnMap(bus.vehicleId));
  const left = document.createElement("span");
  left.className = "bus-summary";
  const title = document.createElement("strong");
  title.textContent = name;
  left.append(title);
  if (context) {
    const sub = document.createElement("small");
    sub.className = "bus-context";
    sub.textContent = context;
    left.append(sub);
  }
  const right = document.createElement("small");
  right.className = "bus-age";
  right.textContent = "GPS " + ago(observedAgeSeconds(bus.observedAt, now));
  row.append(left, right);
  return row;
}

function renderBuses() {
  const list = $("vehicle-list");
  list.replaceChildren();
  const buses = ["live", "delayed"].includes(lastResult.state) ? lastResult.vehicles : [];
  const activeIds = new Set(buses.map((bus) => bus.vehicleId));
  const notReporting = knownFleet.filter((bus) => !activeIds.has(bus.vehicleId));
  if (!buses.length && !notReporting.length) {
    const placeholder = document.createElement("div");
    placeholder.className = "no-buses";
    placeholder.textContent = lastResult.state === "afterhours"
      ? "Outside listed service hours. No recent bus history available."
      : "No current or previously observed buses available.";
    list.append(placeholder);
    return;
  }
  if (buses.length) {
    const subheading = document.createElement("div");
    subheading.className = "fleet-section-label";
    subheading.textContent = lastResult.state === "delayed"
      ? "Recently seen · not live"
      : "Reporting GPS · no calibrated ETA";
    list.append(subheading);
    const now = Date.now();
    for (const bus of buses.slice(0, 8)) list.append(busRow(bus, now));
  }
  if (notReporting.length) {
    const heading = document.createElement("div");
    heading.className = "fleet-section-label historical-heading";
    heading.textContent = "Not currently reporting (" + notReporting.length + ")";
    list.append(heading);
    for (const bus of notReporting.slice(0, 12)) {
      const row = document.createElement("div");
      row.className = "bus-row historical-bus-row";
      const name = document.createElement("strong");
      name.textContent = busDisplayName(bus);
      const time = document.createElement("small");
      time.textContent = "Last GPS " + ago(observedAgeSeconds(bus.observedAt));
      row.append(name, time);
      list.append(row);
    }
    const footnote = document.createElement("div");
    footnote.className = "fleet-disclaimer";
    footnote.textContent = "Not reporting ≠ confirmed inactive. Current location unknown.";
    list.append(footnote);
  }
}

function setStatus(result) {
  lastResult = result;
  status(result.label, result.state, result.message);
  renderBuses();
  clearBusMarkers();
  clearHistoricalMarkers();
  if (["live", "delayed"].includes(result.state) && result.vehicles.length) {
    drawBusMarkers(result.vehicles);
    $("map-update").textContent = result.vehicles.length +
      (result.state === "delayed" ? " last-seen GPS " : result.publicRelay ? " third-party GPS " : " official GPS ") +
      (result.vehicles.length === 1 ? "report" : "reports") +
      (result.state === "delayed" ? " · not live" : "");
  } else {
    $("map-update").textContent = result.state === "delayed" ? "GPS delayed · no recent buses shown" : "No current bus positions";
  }
  const showableBuses = ["live", "delayed"].includes(result.state)
    ? result.vehicles : [];
  const mapBusesButton = $("map-buses");
  mapBusesButton.disabled = showableBuses.length === 0;
  $("map-buses-count").textContent = String(showableBuses.length);
  mapBusesButton.setAttribute("aria-label",
    result.state === "delayed"
      ? "Show recent, not-live bus positions on map"
      : "Show currently reporting buses on map");

  const historyCandidates = historicalCandidates();
  const historyToggle = $("map-history");
  historyToggle.disabled = historyCandidates.length === 0;
  historyToggle.setAttribute("aria-pressed", String(showHistoricalPins));
  $("map-history-count").textContent = String(historyCandidates.length);
  if (showHistoricalPins) {
    drawHistoricalMarkers(historyCandidates);
    if (historyCandidates.length) {
      $("map-update").textContent = historyCandidates.length + " historical GPS pins shown · NOT current locations";
    }
  }
}

function historicalCandidates() {
  const currentIds = new Set(lastResult.vehicles.map((v) => v.vehicleId));
  return knownFleet.filter((v) => !currentIds.has(v.vehicleId)
    && observedAgeSeconds(v.observedAt) <= 24 * 3600);
}

function focusBusOnMap(vehicleId) {
  const marker = busMarkers.get(vehicleId);
  if (!map || !marker) return;
  const point = marker.getLatLng();
  map.setView(point, Math.max(map.getZoom(), 16), {animate: false});
  marker.openPopup();
  // Move the actual map into view rather than losing the selected bus
  // below the visible phone viewport.
  $("map-card").scrollIntoView({
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "instant" : "smooth", block: "center"
  });
}

function focusAllReportingBuses() {
  if (!map || !window.L || !busMarkers.size) return;
  const points = [...busMarkers.values()].map((marker) => marker.getLatLng());
  if (points.length === 1) map.setView(points[0], 16, {animate: false});
  else map.fitBounds(window.L.latLngBounds(points),
    {padding: [36,36], maxZoom: 16, animate: false});
  $("map-card").scrollIntoView({
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "instant" : "smooth", block: "center"
  });
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

function clearHistoricalMarkers() {
  if (map) for (const marker of historicalMarkers.values()) map.removeLayer(marker);
  historicalMarkers.clear();
}

function drawHistoricalMarkers(buses) {
  if (!map || !window.L) return;
  for (const bus of buses) {
    const popup = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = shortBusId(bus.vehicleId) + " · historical";
    const note = document.createElement("div");
    note.textContent = "Last reported " + ago(observedAgeSeconds(bus.observedAt))
      + ". NOT a current location; route status unknown.";
    popup.append(title,note);
    const icon = window.L.divIcon({
      className: "",
      html: '<div class="vehicle-pin historical-pin"></div>',
      iconSize: [20,20], iconAnchor: [10,10]
    });
    historicalMarkers.set(bus.vehicleId, window.L.marker(
      [bus.latitude,bus.longitude], { icon }
    ).bindPopup(popup).addTo(map));
  }
}

function drawBusMarkers(buses) {
  if (!map || !window.L) return;
  for (const bus of buses) {
    const popup = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = busDisplayName(bus);
    const details = reportedBusContext(bus);
    const point = mapLocation(bus);
    const sub = document.createElement("div");
    sub.textContent = (point.smoothed ? "Stationary GPS marker stabilized · " : "") +
      (details ? details + " · " : "") +
      (lastResult.state === "delayed" ? "Last seen (not live)" :
      lastResult.publicRelay ? "Student tracker report" : "Official GPS")
      + " · " + ago(observedAgeSeconds(bus.observedAt)) + " · no stop ETA";
    popup.append(title, sub);
    const icon = window.L.divIcon({
      className: "",
      html: '<div class="vehicle-pin reporting-bus' +
        (lastResult.state === "delayed" ? ' last-seen' : lastResult.publicRelay ? ' third-party' : '') +
        '"><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
        '<rect x="5" y="3.5" width="14" height="15" rx="3" fill="none" stroke="currentColor" stroke-width="2"/>' +
        '<path d="M5 12h14M8 19v2m8-2v2" fill="none" stroke="currentColor" stroke-width="2"/>' +
        '<circle cx="8.5" cy="15.5" r="1" fill="currentColor"/>' +
        '<circle cx="15.5" cy="15.5" r="1" fill="currentColor"/>' +
        '</svg></div>',
      iconSize: [27, 27], iconAnchor: [13, 13]
    });
    const marker = window.L.marker([point.latitude, point.longitude], { icon }).bindPopup(popup).addTo(map);
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
    knownFleet = knownFleetFromPayload(data, Date.now());
    setStatus(evaluateFeed(data, Date.now()));
  } catch {
    // No stale replay on source loss or network failure.
    knownFleet = [];
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
$("map-buses").addEventListener("click", focusAllReportingBuses);
$("map-history").addEventListener("click", () => {
  showHistoricalPins = !showHistoricalPins;
  setStatus(lastResult);
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
  if (document.hidden) { clearBusMarkers(); clearHistoricalMarkers(); }
  else poll();
});
window.addEventListener("offline", () => {
  knownFleet = [];
  setStatus({ state: "offline", label: "Device offline", message: "No internet · saved stop information only", vehicles: [] });
});
window.addEventListener("online", () => poll());
if ("serviceWorker" in navigator && window.isSecureContext) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/service-worker.js").catch(() => {}));
}
