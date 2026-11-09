import { classifySnapshot, verifiedVehicles, readableAge, nyTime, directionsUrl, STATIONS, DESTINATIONS } from "./gps.js";

const $ = (id) => document.getElementById(id);
const REFRESH_INTERVAL_MS = 15000;
let latestSnapshot = null;
let refreshing = false;

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function renderEmpty(title, description) {
  const wrap = node("div", "tracker-empty");
  const illustration = node("div", "empty-illustration");
  illustration.setAttribute("aria-hidden", "true");
  illustration.textContent = "🚌";
  illustration.style.fontSize = "37px";
  wrap.append(illustration, node("h3", "", title), node("p", "", description));
  $("trackerBody").replaceChildren(wrap);
}

function renderVehicles(vehicles) {
  const wrap = node("div", "tracker-empty");
  wrap.style.justifyContent = "flex-start";
  wrap.style.alignItems = "stretch";
  wrap.style.textAlign = "left";
  const heading = node("h3", "", `${vehicles.length} confirmed vehicle${vehicles.length === 1 ? "" : "s"}`);
  heading.style.margin = "12px 0 16px";
  const list = node("div", "vehicle-list");
  for (const vehicle of vehicles) {
    const line = node("div", "vehicle-line");
    const left = node("div");
    // No claim about a bus's intended next stop until route classification exists.
    const shortId = vehicle.id.length > 10 ? vehicle.id.slice(-6) : vehicle.id;
    left.append(node("strong", "", `Vehicle ···${shortId}`), node("small", "", `GPS observed ${nyTime(vehicle.observedAt)} ET`));
    const right = node("div", "vehicle-age");
    right.append(node("span", "", readableAge(vehicle.age)), node("small", "", vehicle.freshness === "fresh" ? "Confirmed GPS" : "Older GPS"));
    line.append(left, right);
    list.append(line);
  }
  wrap.append(heading, list);
  $("trackerBody").replaceChildren(wrap);
}

function renderSnapshot(snapshot) {
  const assessment = classifySnapshot(snapshot);
  const isLive = assessment.status === "live";
  $("headerStatus").className = `live-pill ${isLive ? "is-live" : "is-offline"}`;
  $("headerStatusText").textContent = assessment.label;
  $("feedState").textContent = assessment.label;
  $("feedState").className = `feed-tag ${isLive ? "feed-live" : assessment.status === "delayed" ? "feed-delayed" : "feed-unavailable"}`;

  const transport = snapshot?.transportState;
  $("transportLabel").textContent = ({
    healthy: "Online",
    delayed: "Slow updates",
    offline: "Disconnected",
    never_connected: "Not configured",
  })[transport] || "Unavailable";
  $("transportDot").className = `small-dot ${transport === "healthy" ? "dot-green" : "dot-amber"}`;

  const vehicles = verifiedVehicles(snapshot);
  const latestAt = vehicles
    .map((v) => v.observedAt)
    .filter((value) => Number.isFinite(Date.parse(value)))
    .sort()
    .at(-1);
  $("gpsTimestamp").textContent = latestAt ? `${nyTime(latestAt)} ET` : "—";

  if (vehicles.length) {
    renderVehicles(vehicles);
  } else {
    renderEmpty(
      assessment.status === "error" ? "GPS service unavailable" : "Live GPS coming soon",
      assessment.status === "error"
        ? "We couldn't verify shuttle locations. Try again later or open CCNY's official tracker."
        : "Our independent shuttle GPS feed is not connected yet. For live bus positions, use CCNY's official tracker linked to the right."
    );
  }
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  const button = $("refreshButton");
  button.classList.add("busy");
  button.disabled = true;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 7500);
  try {
    const response = await fetch("/api/vehicles", { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const snapshot = await response.json();
    latestSnapshot = snapshot;
    renderSnapshot(snapshot);
  } catch {
    // Never reuse old GPS coordinates as fresh data after an HTTP error.
    renderSnapshot(null);
    $("transportLabel").textContent = navigator.onLine ? "Request failed" : "Device offline";
  } finally {
    clearTimeout(timeoutId);
    button.classList.remove("busy");
    button.disabled = false;
    refreshing = false;
  }
}

function renderPlan() {
  const station = $("stationSelect").value;
  const destination = $("destinationSelect").value;
  const url = directionsUrl(station, destination);
  const result = $("planResult");
  result.replaceChildren();
  const notice = node("span", "planner-result-icon", "ℹ");
  const body = node("div");
  const heading = node("strong", "", "Trip options are not live yet.");
  const description = node("span", "", ` We cannot recommend whether to wait for a shuttle at ${STATIONS[station].name} without current GPS and arrival information. `);
  body.append(heading, description);
  if (url) {
    const link = node("a", "", "View walking directions ↗");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    body.append(link);
  }
  result.append(notice, body);
}

function updateConnectivity() {
  if (!navigator.onLine) {
    $("headerStatus").className = "live-pill is-offline";
    $("headerStatusText").textContent = "Device offline";
    $("transportLabel").textContent = "Device offline";
    $("feedState").textContent = "Offline";
    $("feedState").className = "feed-tag feed-unavailable";
    renderEmpty("You're offline", "The app can show cached pickup information, but it cannot receive new shuttle positions until your internet connection returns.");
  } else {
    refresh();
  }
}

$("refreshButton").addEventListener("click", refresh);
$("planButton").addEventListener("click", renderPlan);
window.addEventListener("online", updateConnectivity);
window.addEventListener("offline", updateConnectivity);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && navigator.onLine) refresh();
});
setInterval(() => {
  if (!document.hidden && navigator.onLine) refresh();
}, REFRESH_INTERVAL_MS);

if ("serviceWorker" in navigator && window.isSecureContext) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
refresh();
