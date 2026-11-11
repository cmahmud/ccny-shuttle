import { serviceNotice } from "./service-calendar-v1.js";
import { STOPS, DESTINATIONS, R137, OFFICIAL, directionsUrl, evaluateFeed, observedAgeSeconds, ago, shortBusId, knownFleetFromPayload, busDisplayName, reportedBusContext, mapLocation, movingBearing } from "./compact-core-v10.js";
import { ROUTE_PATHS, ROUTE_STOPS, ROUTE_SOURCE } from "./route-data-v1.js";

const $ = (id) => document.getElementById(id);
let selected = "125";
let destination = "nac";
let map = null;
let stopMarkers = new Map();
let routeLayers = [];
let routeStopMarkers = new Map();
let busMarkers = new Map();
let historicalMarkers = new Map();
let knownFleet = [];
// Last-reported positions are visible by default, always marked historical.
let showHistoricalPins = true;
let autoFramedFirstPositions = false;
const SAVED_FLEET_KEY = "ccny-shuttle-tab-last-fixes-v1";
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

function lastReportedClock(timestamp) {
  const value = Date.parse(timestamp);
  if (!Number.isFinite(value)) return "time unknown";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit", timeZoneName: "short"
  }).format(new Date(value));
}

function validCachedFleet(data, now = Date.now()) {
  if (!data || !["samsara","student_public"].includes(data.source)
      || !Array.isArray(data.vehicles) || data.vehicles.length > 25
      || !Number.isFinite(data.savedAt)
      || data.savedAt > now + 30000 || now-data.savedAt > 24*3600000) return [];
  const sourceKind = data.source === "student_public" ?
    "third_party_observed" : "confirmed";
  return knownFleetFromPayload({
    source: data.source, vehicles: data.vehicles.map((v) =>
      ({ ...v, locationKind: sourceKind }))
  }, now).filter((v) => observedAgeSeconds(v.observedAt, now) <= 24 * 3600);
}

function restoreLastPositions() {
  try {
    const stored = sessionStorage.getItem(SAVED_FLEET_KEY);
    if (!stored || stored.length > 12000) return [];
    return validCachedFleet(JSON.parse(stored));
  } catch {
    return [];
  }
}

function rememberLastPositions(source) {
  if (!["student_public", "samsara"].includes(source) || !knownFleet.length) return;
  try {
    // Tab-scoped, limited to public GPS fixes; no driver, location of the
    // student, device identifiers, credentials, or private response fields.
    sessionStorage.setItem(SAVED_FLEET_KEY, JSON.stringify({
      savedAt: Date.now(), source,
      vehicles: knownFleet.slice(0,25).map((b) => ({
        vehicleId: b.vehicleId, busName: b.busName,
        latitude: b.latitude, longitude: b.longitude,
        observedAt: b.observedAt
      }))
    }));
  } catch {
    // Storage is optional (private browsing, blocked, quota).
  }
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
    heading.textContent = "Last reported GPS (" + notReporting.length + ")";
    list.append(heading);
    for (const bus of notReporting.slice(0, 12)) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "bus-row historical-bus-row historical-bus-button";
      row.setAttribute("aria-label", "View last reported location for " +
        busDisplayName(bus) + ", from " + lastReportedClock(bus.observedAt) +
        ". Not a current location.");
      row.addEventListener("click", () => focusHistoricalBusOnMap(bus.vehicleId));
      const info = document.createElement("span");
      info.className = "historical-bus-info";
      const name = document.createElement("strong");
      name.textContent = busDisplayName(bus);
      const time = document.createElement("small");
      time.className = "historical-time";
      time.textContent = "Last GPS " + ago(observedAgeSeconds(bus.observedAt)) +
        " · " + lastReportedClock(bus.observedAt);
      info.append(name, time);
      const locate = document.createElement("span");
      locate.className = "historical-view";
      locate.textContent = "Map ↗";
      locate.setAttribute("aria-hidden","true");
      row.append(info, locate);
      list.append(row);
    }
    const footnote = document.createElement("div");
    footnote.className = "fleet-disclaimer";
    footnote.textContent = "Not live or confirmed inactive. Buses may have moved.";
    list.append(footnote);
  }
}

function updateServiceAdvisory(result, now = new Date()) {
  const hasLiveBuses = result.state === "live" &&
    Array.isArray(result.vehicles) && result.vehicles.some(bus => bus.freshness === "fresh");
  const notice = serviceNotice(now, hasLiveBuses);
  const banner = $("service-advisory");
  banner.hidden = !notice;
  if (!notice) return;
  banner.dataset.kind = notice.kind;
  $("service-advisory-title").textContent = notice.title;
  $("service-advisory-detail").textContent = notice.detail;
  const link = $("service-advisory-link");
  link.href = notice.url;
  link.textContent = notice.sourceLabel + " ↗";
}

function setStatus(result) {
  lastResult = result;
  status(result.label, result.state, result.message);
  updateServiceAdvisory(result);
  renderBuses();
  if (["live", "delayed"].includes(result.state) && result.vehicles.length) {
    drawBusMarkers(result.vehicles);
    $("map-update").textContent = result.vehicles.length +
      (result.state === "delayed" ? " last-seen GPS " : result.publicRelay ? " third-party GPS " : " official GPS ") +
      (result.vehicles.length === 1 ? "report" : "reports") +
      (result.state === "delayed" ? " · not live" : "");
  } else {
    clearBusMarkers();
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
  historyToggle.title = showHistoricalPins ?
    "Hide last-reported bus locations" : "Show last-reported bus locations";
  historyToggle.setAttribute("aria-label", historyToggle.title);
  $("map-history-count").textContent = String(historyCandidates.length);
  if (showHistoricalPins && historyCandidates.length) {
    drawHistoricalMarkers(historyCandidates);
    const recentCount = result.vehicles.length;
    $("map-update").textContent = recentCount
      ? recentCount + " recent GPS · " + historyCandidates.length + " last-reported (not live)"
      : historyCandidates.length + " last-reported GPS location" +
        (historyCandidates.length === 1 ? "" : "s") + " · NOT live";
  } else {
    clearHistoricalMarkers();
  }
  $("map-update").classList.toggle("is-history",
    historicalMarkers.size > 0 && !busMarkers.size);
  if (!autoFramedFirstPositions && map && (busMarkers.size || historicalMarkers.size)) {
    autoFramedFirstPositions = true;
    // Keep the entire route visible on initial load. Only reframe GPS pins
    // if the bus is *outside* the already visible route overview.
    const markers=[...busMarkers.values(),...historicalMarkers.values()];
    const inOverview=map.getBounds();
    if (!routeLayers.length ||
        markers.some(marker=>!inOverview.contains(marker.getLatLng()))) {
      frameMarkers(markers,false);
    }
  }
}

function historicalCandidates() {
  const currentIds = new Set(lastResult.vehicles.map((v) => v.vehicleId));
  // Allow up to seven days of last-known history, always marked stale.
  return knownFleet.filter((v) => !currentIds.has(v.vehicleId)
    && observedAgeSeconds(v.observedAt) <= 7 * 24 * 3600);
}

function showMapOnPhone() {
  $("map-card").scrollIntoView({
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ?
      "instant" : "smooth",
    block: "center"
  });
}

function frameMarkers(markers, scrollToMap = true) {
  if (!map || !window.L || !markers.length) return;
  const points = markers.map((marker) => marker.getLatLng());
  if (points.length === 1) map.setView(points[0], 16, {animate:false});
  else map.fitBounds(window.L.latLngBounds(points),
    {padding:[45,45],maxZoom:16,animate:false});
  if (scrollToMap) showMapOnPhone();
}

function focusHistoricalBusOnMap(vehicleId) {
  if (!showHistoricalPins) {
    showHistoricalPins = true;
    setStatus(lastResult);
  }
  const marker = historicalMarkers.get(vehicleId);
  if (!marker || !map) return;
  map.setView(marker.getLatLng(), 17, {animate:false});
  marker.openPopup();
  showMapOnPhone();
}

function focusBusOnMap(vehicleId) {
  const marker = busMarkers.get(vehicleId);
  if (!map || !marker) return;
  const point = marker.getLatLng();
  map.setView(point, Math.max(map.getZoom(), 16), {animate: false});
  marker.openPopup();
  // Move the actual map into view rather than losing the selected bus
  // below the visible phone viewport.
  showMapOnPhone();
}

function focusAllReportingBuses() {
  if (!map || !window.L || !busMarkers.size) return;
  frameMarkers([...busMarkers.values()]);
}

function drawRoutes() {
  if (!map || !window.L) return;
  const palette = {NB:"#694edd",SB:"#b37df7"};
  for (const path of ROUTE_PATHS) {
    if (!["NB","SB"].includes(path.direction) || !Array.isArray(path.coordinates)
        || path.coordinates.length < 2) continue;
    const points = path.coordinates.filter((p) =>
      Array.isArray(p) && p.length === 2 &&
      p[0] >= 40.78 && p[0] <= 40.86 &&
      p[1] >= -74.02 && p[1] <= -73.88);
    if (points.length !== path.coordinates.length) continue;
    // Low-opacity outline gives the route legibility over detailed OSM tiles.
    const base = window.L.polyline(points,{
      color:"#ffffff",weight:10,opacity:.83,interactive:false
    }).addTo(map);
    const route = window.L.polyline(points,{
      color:palette[path.direction],weight:5,opacity:.94,
      lineCap:"round",lineJoin:"round",
      dashArray:path.direction==="SB"?"8 10":null
    }).addTo(map);
    const popup = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = path.direction==="NB" ?
      "Northbound route" : "Southbound route";
    const note = document.createElement("div");
    note.textContent = ROUTE_SOURCE +
      ". Source-drawn path; road turns and pickup points must be field-verified.";
    popup.append(strong,note);
    route.bindPopup(popup);
    routeLayers.push(base,route);
  }
  // Student-public approximate stop coordinates fill gaps where our old
  // UI intentionally had no surveyed 135th/Marshak pins.
  for(const key of ["135","marshak"]) {
    const stop = ROUTE_STOPS[key];
    if (!stop || !stop.point) continue;
    const popup = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = stop.label;
    const note = document.createElement("div");
    note.textContent = "Approximate stop location via student tracker." +
      (key==="135"?" Northbound, on request.":"") +
      " Verify the posted stop sign before boarding.";
    popup.append(name,note);
    const marker = window.L.circleMarker(stop.point,{
      radius:7,color:"#fff",weight:3,
      fillColor:"#694edd",fillOpacity:.95
    }).addTo(map).bindPopup(popup);
    marker.on("click",()=>selectStop(key));
    routeStopMarkers.set(key,marker);
  }
  // Route and official UI pins have their own markers and can be toggled
  // separately from historical bus telemetry.
  if (routeLayers.length) {
    $("map-route-source").textContent = "Route via student tracker · approximate";
  }
}

function fitRouteOverview() {
  if (!map || !window.L) return;
  const bounds = [...stopMarkers.values()].map(marker=>marker.getLatLng());
  for (const layer of routeLayers) {
    const candidate=layer.getBounds?.();
    if (candidate?.isValid()) {
      bounds.push(candidate.getSouthWest(),candidate.getNorthEast());
    }
  }
  if (bounds.length) {
    map.fitBounds(window.L.latLngBounds(bounds),
      {padding:[30,30],maxZoom:14,animate:false});
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
  drawRoutes();
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
  }
  fitRouteOverview();
  window.addEventListener("resize", () => map.invalidateSize());
  setTimeout(() => map && map.invalidateSize(), 100);
}

function highlightMap(key) {
  if (!map) return;
  for (const [stopKey, marker] of stopMarkers) marker.setIcon(markerIcon(STOPS[stopKey].kind, stopKey === key));
  for (const [stopKey, marker] of routeStopMarkers) {
    const highlighted=stopKey===key;
    marker.setStyle({radius:highlighted?9:7,weight:highlighted?4:3,
      color:"#fff",fillColor:highlighted?"#5840da":"#694edd"});
  }
  const stop = STOPS[key];
  if (stop.point) map.setView(stop.point, Math.max(map.getZoom(), 15), { animate: true });
  // 135th and Marshak stop coordinates are sourced from the student map,
  // not field surveyed. We can focus those route stop markers, but don't
  // assert the point is the exact place to board.
  else if (ROUTE_STOPS[key]?.point) map.setView(ROUTE_STOPS[key].point, 15, {animate:true});
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

function distanceBetweenReportedPoints(a, b) {
  const metersPerDegree = 111195;
  const lngScale = Math.cos(a.latitude * Math.PI / 180);
  return metersPerDegree * Math.hypot(
    a.latitude-b.latitude, (a.longitude-b.longitude)*lngScale
  );
}

function labelPositionFor(bus, buses) {
  // Split only screen-space *labels*, never the GPS anchor itself.
  // Overlapping source fixes are intentionally still geolocated correctly.
  const nearby = buses.filter((item) =>
    distanceBetweenReportedPoints(item,bus) < 40
  ).sort((a,b) => String(a.vehicleId).localeCompare(String(b.vehicleId)));
  if (nearby.length < 2) return "solo";
  const index = nearby.findIndex((item) => item.vehicleId === bus.vehicleId);
  return ["label-ne","label-sw","label-nw","label-se"][index % 4];
}

function drawHistoricalMarkers(buses) {
  if (!map || !window.L) return;
  const visible = new Set();
  for (const bus of buses) {
    visible.add(bus.vehicleId);
    const popup = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = busDisplayName(bus) + " · last reported";
    const note = document.createElement("div");
    note.textContent = lastReportedClock(bus.observedAt) + " (" +
      ago(observedAgeSeconds(bus.observedAt)) + "). Last recorded GPS only." +
      " This bus may have moved.";
    const directions = document.createElement("a");
    directions.href = "https://www.google.com/maps/search/?api=1&query=" +
      encodeURIComponent(bus.latitude + "," + bus.longitude);
    directions.target = "_blank";
    directions.rel = "noopener noreferrer";
    directions.textContent = "Open recorded point in Maps ↗";
    popup.append(title,note,directions);
    const number = typeof bus.busName === "string" && /^[0-9]{1,3}$/.test(bus.busName)
      ? bus.busName : "•";
    const labelPosition = labelPositionFor(bus, buses);
    const icon = window.L.divIcon({
      className: "",
      html: '<div class="vehicle-pin historical-pin ' + labelPosition +
        '"><span class="history-anchor"></span>' +
        '<span class="history-stem"></span><span class="history-label">' +
        number + '</span></div>',
      // Tiny raw GPS anchor remains centered at the original coordinates;
      // label displacement is a *screen-space annotation* only.
      iconSize: [12,12], iconAnchor: [6,6]
    });
    const existing = historicalMarkers.get(bus.vehicleId);
    if (existing) {
      const pos = existing.getLatLng();
      if (pos.lat !== bus.latitude || pos.lng !== bus.longitude) {
        existing.setLatLng([bus.latitude,bus.longitude]);
      }
      if (existing._ccnyDisplayNumber !== number ||
          existing._ccnyLabelPosition !== labelPosition) {
        existing.setIcon(icon);
        existing._ccnyDisplayNumber = number;
        existing._ccnyLabelPosition = labelPosition;
      }
      existing.setPopupContent(popup);
    } else {
      const marker = window.L.marker(
        [bus.latitude,bus.longitude], { icon }
      ).bindPopup(popup).addTo(map);
      marker._ccnyDisplayNumber = number;
      marker._ccnyLabelPosition = labelPosition;
      historicalMarkers.set(bus.vehicleId, marker);
    }
  }
  for (const [id,marker] of historicalMarkers) {
    if (!visible.has(id)) {
      map.removeLayer(marker);
      historicalMarkers.delete(id);
    }
  }
}

function drawBusMarkers(buses) {
  if (!map || !window.L) return;
  const visible = new Set();
  for (const bus of buses) {
    visible.add(bus.vehicleId);
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
    const bearing = lastResult.state==="live" ? movingBearing(bus) : null;
    const isMoving = bearing !== null;
    const label = (typeof bus.busName === "string" && /^[0-9]{1,3}$/.test(bus.busName))
      ? bus.busName : "";
    const icon = window.L.divIcon({
      className:"",
      html: isMoving
        ? '<div class="vehicle-arrow-wrap"><div class="vehicle-arrow"' +
            ' style="transform:rotate(' + bearing + 'deg)">' +
            '<svg viewBox="0 0 32 38" aria-hidden="true"><path' +
            ' d="M16 2L30 34L16 28L2 34Z" fill="currentColor" stroke="#fff"' +
            ' stroke-width="2.7" stroke-linejoin="round"/></svg>' +
            '</div>' + (label ? '<span class="arrow-number">' + label + '</span>' : '') +
            '</div>'
        : '<div class="vehicle-pin reporting-bus' +
          (lastResult.state === "delayed" ? ' last-seen' : lastResult.publicRelay ? ' third-party' : '') +
          '"><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
          '<rect x="5" y="3.5" width="14" height="15" rx="3" fill="none" stroke="currentColor" stroke-width="2"/>' +
          '<path d="M5 12h14M8 19v2m8-2v2" fill="none" stroke="currentColor" stroke-width="2"/>' +
          '<circle cx="8.5" cy="15.5" r="1" fill="currentColor"/>' +
          '<circle cx="15.5" cy="15.5" r="1" fill="currentColor"/>' +
          '</svg></div>',
      iconSize: isMoving ? [34,42] : [27,27],
      iconAnchor: isMoving ? [17,20] : [13,13]
    });
    const state = lastResult.state === "delayed" ? "delayed" :
      lastResult.publicRelay ? "student" : "official";
    const iconState = state + ":" +
      (isMoving ? "arrow:" + Math.round(bearing / 4) * 4 + ":" + label : "stopped");

    const existing = busMarkers.get(bus.vehicleId);
    if (existing) {
      const old = existing.getLatLng();
      if (old.lat !== point.latitude || old.lng !== point.longitude) {
        existing.setLatLng([point.latitude,point.longitude]);
      }
      if (existing._ccnyState !== iconState) {
        existing.setIcon(icon);
        existing._ccnyState = iconState;
      }
      existing.setPopupContent(popup);
    } else {
      const marker = window.L.marker(
        [point.latitude,point.longitude], { icon }
      ).bindPopup(popup).addTo(map);
      marker._ccnyState = iconState;
      busMarkers.set(bus.vehicleId, marker);
    }
  }
  for (const [id,marker] of busMarkers) {
    if (!visible.has(id)) {
      map.removeLayer(marker);
      busMarkers.delete(id);
    }
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
    const freshFleet = knownFleetFromPayload(data, Date.now());
    if (freshFleet.length) {
      knownFleet = freshFleet;
      rememberLastPositions(data.source);
    } else if (!knownFleet.length) {
      knownFleet = restoreLastPositions();
    }
    setStatus(evaluateFeed(data, Date.now()));
  } catch {
    // Preserve *only* old, explicitly historical GPS reports during network
    // loss. Never replay an in-memory observation as live or predict an ETA.
    if (!knownFleet.length) knownFleet = restoreLastPositions();
    setStatus({ state: "offline", label: navigator.onLine ?
      "GPS unavailable" : "Device offline",
      message: knownFleet.length
        ? "Last known positions shown · NOT live GPS"
        : navigator.onLine ? "GPS status request failed" : "No internet · stop map only",
      vehicles: [] });
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
  if (showHistoricalPins && historicalMarkers.size) {
    frameMarkers([...historicalMarkers.values()]);
  }
});
$("map-reset").addEventListener("click", fitRouteOverview);
selectStop("125");
updateServiceAdvisory(lastResult);
initMap();
// Restore a tab-scoped last-known snapshot before requesting the latest
// source. Saved records are historical only; never classified live.
knownFleet = restoreLastPositions();
if (knownFleet.length) {
  setStatus({state:"offline",label:"Checking GPS",
    message:"Previous GPS reports available · NOT live",vehicles:[]});
}
poll();
setInterval(() => { if (!document.hidden) poll(); }, POLL_MS);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) { clearBusMarkers(); clearHistoricalMarkers(); }
  else poll();
});
window.addEventListener("offline", () => {
  if (!knownFleet.length) knownFleet = restoreLastPositions();
  setStatus({ state: "offline", label: "Device offline",
    message: knownFleet.length
      ? "Saved last GPS reports · NOT live positions"
      : "No internet · saved stop information only", vehicles: [] });
});
window.addEventListener("online", () => poll());
if ("serviceWorker" in navigator && window.isSecureContext) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/service-worker.js").catch(() => {}));
}
