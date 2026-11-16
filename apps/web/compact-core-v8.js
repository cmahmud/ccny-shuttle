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

export function validVehicle(vehicle, now = Date.now(), source = "samsara") {
  const kindMatches = source === "samsara" ? vehicle?.locationKind === "confirmed"
    : source === "student_public" ? vehicle?.locationKind === "third_party_observed" : false;
  return vehicle && typeof vehicle.vehicleId === "string" && vehicle.vehicleId.length > 0
    && kindMatches
    && vehicle.freshness === "fresh"
    && Number.isFinite(vehicle.latitude) && Math.abs(vehicle.latitude) <= 90
    && Number.isFinite(vehicle.longitude) && Math.abs(vehicle.longitude) <= 180
    && observedAgeSeconds(vehicle.observedAt, now) <= 30;
}

export function validRecentVehicle(vehicle, now = Date.now(), source = "samsara") {
  const correctProvenance = source === "samsara" ? vehicle?.locationKind === "confirmed"
    : source === "student_public" ? vehicle?.locationKind === "third_party_observed" : false;
  return Boolean(vehicle && correctProvenance && typeof vehicle.vehicleId === "string"
    && vehicle.vehicleId.length > 0
    && Number.isFinite(vehicle.latitude) && Math.abs(vehicle.latitude) <= 90
    && Number.isFinite(vehicle.longitude) && Math.abs(vehicle.longitude) <= 180
    && ["fresh", "delayed", "stale"].includes(vehicle.freshness)
    && observedAgeSeconds(vehicle.observedAt, now) <= 180);
}

export function outsideListedHours(now = Date.now()) {
  // Use the *campus* timezone, not the device timezone.
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York", weekday: "short",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23"
    }).formatToParts(new Date(now)).filter((p) => p.type !== "literal")
      .map((p) => [p.type, p.value])
  );
  if (["Sat", "Sun"].includes(parts.weekday)) return true;
  const minutes = Number(parts.hour) * 60 + Number(parts.minute);
  return minutes < 6 * 60 + 30 || minutes >= 22 * 60;
}

function newestReportAge(vehicles, now) {
  const ages = vehicles.map((v) => observedAgeSeconds(v.observedAt, now))
    .filter((age) => Number.isFinite(age));
  return ages.length ? Math.min(...ages) : Infinity;
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
  const publicRelay = payload.source === "student_public";
  const official = payload.source === "samsara";
  const vehicles = healthy && (publicRelay || official)
    ? payload.vehicles.filter((v) => validVehicle(v, now, payload.source)) : [];
  if (healthy && vehicles.length) {
    return { state: "live", source: payload.source,
      label: publicRelay ? "GPS via student" : "GPS live",
      message: publicRelay ? "Bus reports via student tracker · ETAs pending"
        : "Official GPS positions · ETAs pending",
      publicRelay, vehicles };
  }
  // The normal CCNY schedule ends at 10 PM ET. A truly fresh bus
  // still takes precedence (late service may happen), but stale telemetry
  // must not be labeled a currently running shuttle.
  if (outsideListedHours(now)) {
    const age = newestReportAge(payload.vehicles, now);
    return {
      state: "afterhours", label: "Outside shuttle hours",
      message: "Listed service: Mon–Fri 6:30 AM–10 PM ET" +
        (Number.isFinite(age) ? " · last bus report " + ago(age) : " · no recent bus reports"),
      vehicles: []
    };
  }
  const lastSeen = (publicRelay || official) &&
    ["healthy", "delayed"].includes(payload.transportState) &&
    ["live", "delayed", "stale"].includes(payload.sourceState)
    ? payload.vehicles.filter((v) => validRecentVehicle(v, now, payload.source)) : [];
  if (lastSeen.length) {
    return { state: "delayed", source: payload.source, publicRelay,
      label: "GPS delayed", message: "Last reported position (not live) · no ETAs",
      vehicles: lastSeen };
  }
  if (payload.transportState === "delayed" || payload.sourceState === "delayed" || payload.sourceState === "stale") {
    return { state: "delayed", label: "GPS delayed", message: "Live GPS positions are outdated", vehicles: [] };
  }
  return { state: "offline", label: "GPS unavailable", message: "Live shuttle positions not connected", vehicles: [] };
}

// A previously observed vehicle is not necessarily parked or off duty.
// Never reinterpret stale coordinates as its present location or an ETA.
export function knownFleetFromPayload(payload, now = Date.now()) {
  if (!payload || !["samsara", "student_public"].includes(payload.source)
    || !Array.isArray(payload.vehicles)) return [];
  const byId = new Map();
  for (const vehicle of payload.vehicles.slice(0, 100)) {
    const age = observedAgeSeconds(vehicle?.observedAt, now);
    const kind = payload.source === "student_public" ? "third_party_observed" : "confirmed";
    if (typeof vehicle?.vehicleId !== "string" || !vehicle.vehicleId
      || vehicle.vehicleId.length > 96 || vehicle.locationKind !== kind
      || !Number.isFinite(age) || age > 7 * 86400
      || !Number.isFinite(vehicle.latitude) || !Number.isFinite(vehicle.longitude)
      || vehicle.latitude < 40.78 || vehicle.latitude > 40.86
      || vehicle.longitude < -74.02 || vehicle.longitude > -73.88) continue;
    const older = byId.get(vehicle.vehicleId);
    if (!older || age < older.ageSeconds) byId.set(vehicle.vehicleId, {
      vehicleId: vehicle.vehicleId,
      busName: typeof vehicle.busName === "string" &&
        /^[0-9]{1,3}$/.test(vehicle.busName) ? vehicle.busName : null,
      observedAt: vehicle.observedAt,
      latitude: vehicle.latitude,
      longitude: vehicle.longitude,
      ageSeconds: age,
      source: payload.source
    });
  }
  return [...byId.values()].sort((a,b) => a.ageSeconds - b.ageSeconds);
}

export function busDisplayName(bus) {
  const raw = bus?.busName;
  if (typeof raw === "string" && /^[0-9]{1,3}$/.test(raw)) return "Bus " + raw;
  return shortBusId(bus?.vehicleId);
}

export function reportedBusContext(bus, now = Date.now()) {
  // These are only source-reported statuses tied to a recent GPS fix.
  // Do not display them as current once their GPS observation ages out.
  if (!bus || bus.freshness !== "fresh" ||
      observedAgeSeconds(bus.observedAt, now) > 30) return "";
  const direction = bus.reportedDirection === "NB" ? "Northbound"
    : bus.reportedDirection === "SB" ? "Southbound" : null;
  const status = bus.reportedStatus === "standing" ||
    bus.reportedStatus === "standing_at_stop" ? "At stop"
    : bus.reportedStatus === "moving" ? "Moving"
    : bus.reportedStatus === "stopped" ? "Stopped" : null;
  const stopNames = {
    "125": "125th St", "135": "135th St", "marshak": "Marshak", "145": "145th St"
  };
  const next = stopNames[bus.reportedNextStopId];
  return [direction, status, next ? "Next: " + next : null].filter(Boolean).join(" · ");
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
