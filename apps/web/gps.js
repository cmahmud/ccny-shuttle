/**
 * Presentation-only GPS utilities.
 * No extrapolation: stale GPS observations never become "predicted" coordinates.
 */
export function readableAge(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "Unknown";
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

export function nyTime(value) {
  if (!value || !Number.isFinite(Date.parse(value))) return "—";
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
  }).format(new Date(value));
}

export function classifySnapshot(value) {
  if (!value || typeof value !== "object" || !Array.isArray(value.vehicles)) {
    return { status: "error", label: "Feed unavailable", detail: "The GPS service sent an invalid response." };
  }
  const transport = value.transportState;
  const source = value.sourceState;

  // A working HTTP endpoint is not proof of live GPS; both must be fresh.
  if (source === "live" && transport === "healthy" &&
      value.vehicles.some((v) => v?.freshness === "fresh")) {
    return { status: "live", label: "Live GPS", detail: "Source-confirmed, recently observed shuttle positions" };
  }
  if (transport === "offline" || transport === "never_connected") {
    return { status: "offline", label: "GPS unavailable", detail: "No current connection to the shuttle GPS source." };
  }
  if (source === "stale" || source === "delayed" || transport === "delayed") {
    return { status: "delayed", label: "GPS delayed", detail: "Last confirmed positions may be outdated." };
  }
  return { status: "offline", label: "No live data", detail: "Waiting for a verified CCNY shuttle GPS connection." };
}

export function verifiedVehicles(raw) {
  if (!raw || !Array.isArray(raw.vehicles)) return [];
  return raw.vehicles
    .filter((v) => v && typeof v.vehicleId === "string"
      && Number.isFinite(v.latitude) && v.latitude >= -90 && v.latitude <= 90
      && Number.isFinite(v.longitude) && v.longitude >= -180 && v.longitude <= 180
      && v.locationKind === "confirmed"
      && ["fresh", "delayed", "stale"].includes(v.freshness))
    .map((v) => ({
      id: v.vehicleId,
      freshness: v.freshness,
      observedAt: v.observedAt,
      age: v.gpsAgeSeconds,
      latitude: v.latitude,
      longitude: v.longitude
    }));
}

export const DESTINATIONS = Object.freeze({
  marshak: "Marshak Science Building, City College of New York, New York, NY",
  nac: "North Academic Center, City College of New York, New York, NY",
  shepard: "Shepard Hall, City College of New York, New York, NY",
  steinman: "Steinman Hall, City College of New York, New York, NY",
});

export const STATIONS = Object.freeze({
  "125": {
    name: "125th Street",
    directionsOrigin: "West 125th Street and St Nicholas Avenue, Manhattan, New York, NY"
  },
  "145": {
    name: "145th Street",
    directionsOrigin: "West 145th Street and St Nicholas Avenue, Manhattan, New York, NY"
  },
  "137": {
    name: "137th Street–City College",
    directionsOrigin: "West 137th Street and Broadway, Manhattan, New York, NY"
  },
});

export function directionsUrl(station, destination) {
  const from = STATIONS[station], to = DESTINATIONS[destination];
  if (!from || !to) return null;
  return `https://www.google.com/maps/dir/?api=1&origin=${encodeURIComponent(from.directionsOrigin)}&destination=${encodeURIComponent(to)}&travelmode=walking`;
}
