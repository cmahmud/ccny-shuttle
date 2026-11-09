// Shared shuttle stop metadata and defensive GPS classification.
// GPS positions are never estimated by this module.
export const STOPS = Object.freeze({
  "125": {
    name: "125th Street", short: "125th St",
    description: "Post Office · between St. Nicholas & Morningside Ave",
    directions: "West 125th Street post office between St Nicholas Avenue and Morningside Avenue, Manhattan, New York, NY",
    point: [40.81111, -73.95311], kind: "station",
    notice: "Confirm the pickup point by the Post Office."
  },
  "135": {
    name: "135th Street", short: "135th St",
    description: "Convent Avenue · northbound, on request",
    directions: "West 135th Street and Convent Avenue, Manhattan, New York, NY",
    point: null, kind: "request",
    notice: "Request stop. Check with the driver; no surveyed map pin."
  },
  "marshak": {
    name: "Marshak Building", short: "Marshak",
    description: "Convent Avenue · campus shuttle stop",
    directions: "Marshak Science Building, City College of New York, Manhattan, New York, NY",
    point: null, kind: "campus",
    notice: "Campus stop. Confirm the pickup point on Convent Ave."
  },
  "145": {
    name: "145th Street", short: "145th St",
    description: "Dunkin' · between St. Nicholas & Edgecombe Ave",
    directions: "Dunkin West 145th Street between St Nicholas Avenue and Edgecombe Avenue, Manhattan, New York, NY",
    point: [40.82404, -73.944769], kind: "station",
    notice: "Confirm the pickup point by Dunkin'."
  },
  "nac": {
    name: "North Academic Center", short: "NAC",
    description: "Convent Avenue · campus shuttle stop",
    directions: "North Academic Center, City College of New York, Manhattan, New York, NY",
    point: [40.8200332, -73.9497487], kind: "campus",
    notice: "Campus stop. Confirm the boarding point on Convent Ave."
  }
});

export const DESTINATIONS = Object.freeze({
  nac: "North Academic Center, City College of New York, New York, NY",
  marshak: "Marshak Science Building, City College of New York, New York, NY",
  shepard: "Shepard Hall, City College of New York, New York, NY",
  steinman: "Steinman Hall, City College of New York, New York, NY",
  spitzer: "Spitzer School of Architecture, City College of New York, New York, NY"
});

export const R137 = "137th Street City College subway station at Broadway, Manhattan, New York, NY";
export const OFFICIAL = "https://cloud.samsara.com/o/4010168/fleet/viewer/FJMjrX1YlqCqlGxIKkXY";

export function directionsUrl(from, destinationKey) {
  const to = DESTINATIONS[destinationKey];
  if (!from || !to) return null;
  const u = new URL("https://www.google.com/maps/dir/");
  u.searchParams.set("api", "1");
  u.searchParams.set("origin", from);
  u.searchParams.set("destination", to);
  u.searchParams.set("travelmode", "walking");
  return u.toString();
}

export function observedAgeSeconds(timestamp, now = Date.now()) {
  if (typeof timestamp !== "string" || !Number.isFinite(Date.parse(timestamp))) return Infinity;
  const seconds = (now - Date.parse(timestamp)) / 1000;
  return seconds >= 0 ? seconds : Infinity;
}

export function validVehicle(vehicle, now = Date.now()) {
  return vehicle && typeof vehicle.vehicleId === "string" && vehicle.vehicleId.length > 0
    && vehicle.locationKind === "confirmed"
    && vehicle.freshness === "fresh"
    && Number.isFinite(vehicle.latitude) && Math.abs(vehicle.latitude) <= 90
    && Number.isFinite(vehicle.longitude) && Math.abs(vehicle.longitude) <= 180
    && observedAgeSeconds(vehicle.observedAt, now) <= 30;
}

export function evaluateFeed(payload, now = Date.now()) {
  if (!payload || !Array.isArray(payload.vehicles) || !Number.isFinite(Date.parse(payload.generatedAt))) {
    return { state: "offline", label: "GPS unavailable", message: "No verified GPS feed", vehicles: [] };
  }
  // Reject a stale API response even if the response itself claims to be fresh.
  if (observedAgeSeconds(payload.generatedAt, now) > 60) {
    return { state: "offline", label: "GPS unavailable", message: "GPS status response is outdated", vehicles: [] };
  }
  const healthy = payload.transportState === "healthy" && payload.sourceState === "live";
  const vehicles = healthy ? payload.vehicles.filter((v) => validVehicle(v, now)) : [];
  if (healthy && vehicles.length) {
    return { state: "live", label: "GPS live", message: "Verified bus locations · ETAs pending", vehicles };
  }
  if (payload.transportState === "delayed" || payload.sourceState === "delayed" || payload.sourceState === "stale") {
    return { state: "delayed", label: "GPS delayed", message: "Live GPS positions are outdated", vehicles: [] };
  }
  return { state: "offline", label: "GPS unavailable", message: "Live shuttle positions not connected", vehicles: [] };
}

export function shortBusId(id) {
  const clean = String(id || "");
  const last = clean.slice(-5);
  return last ? "Bus ···" + last : "Shuttle";
}

export function ago(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "unknown";
  if (seconds < 60) return Math.floor(seconds) + "s ago";
  if (seconds < 3600) return Math.floor(seconds / 60) + "m ago";
  return Math.floor(seconds / 3600) + "h ago";
}
