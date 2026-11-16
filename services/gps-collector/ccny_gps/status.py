"""Read-only, provenance-aware status and vehicle snapshot.

Trusted official GPS is preferred. If that source is not currently active, a
clearly labeled student-public relay may be shown as a *third-party report*.
No service estimates, extrapolates, or fabricates vehicle coordinates.
"""
from datetime import datetime, timezone

from .models import Observation
from .storage import ObservationStore
from .location_filter import stationary_display_position

SOURCES = ("samsara", "student_public")


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _source_status(store: ObservationStore, source: str, now: datetime) -> dict:
    last_poll = store.last_successful_poll(source)
    poll_age = max(0.0, (now - last_poll).total_seconds()) if last_poll else None
    transport = (
        "never_connected" if poll_age is None
        else "healthy" if poll_age <= 45
        else "delayed" if poll_age <= 120
        else "offline"
    )
    observations = store.latest_observations(source)
    details = store.latest_vehicle_context(source) if source == "student_public" else {}
    vehicles = []
    for obs in observations:
        age = round(obs.age_seconds(now), 1)
        reported = details.get(obs.vehicle_id)
        # A status is an observation at a specific GPS fix, not a persistent
        # truth about this vehicle. Only expose it when it matches our accepted
        # latest GPS event; downstream UI must still respect GPS freshness.
        if reported and reported["reportedObservedAt"] != obs.observed_at.isoformat():
            reported = None
        stabilized = None
        if reported and obs.freshness(now) == "fresh" and reported["reportedStatus"] in (
            "standing", "standing_at_stop", "stopped"
        ):
            recent = store.recent_observations(source, obs.vehicle_id, limit=6)
            stabilized = stationary_display_position(
                obs, recent, reported["reportedStatus"], now
            )
        vehicles.append({
            "displayPosition": stabilized,
            "busName": reported["busName"] if reported else None,
            "reportedDirection": reported["reportedDirection"] if reported else None,
            "reportedStatus": reported["reportedStatus"] if reported else None,
            "reportedNextStopId": reported["reportedNextStopId"] if reported else None,
            "vehicleId": obs.vehicle_id,
            "latitude": obs.latitude,
            "longitude": obs.longitude,
            "headingDegrees": obs.heading_degrees,
            "speedMilesPerHour": obs.speed_mph,
            "observedAt": iso_z(obs.observed_at),
            "receivedAt": iso_z(obs.received_at),
            "gpsAgeSeconds": age,
            "freshness": obs.freshness(now),
            "locationKind": (
                "confirmed" if source == "samsara" else "third_party_observed"
            ),
        })
    freshnesses = {item["freshness"] for item in vehicles}
    if not vehicles:
        source_state = "no_data"
    elif "fresh" in freshnesses:
        source_state = "live"
    elif "delayed" in freshnesses:
        source_state = "delayed"
    else:
        source_state = "stale"
    return {
        "source": source, "sourceState": source_state,
        "transportState": transport, "vehicles": vehicles,
        "last_poll": last_poll, "poll_age": poll_age,
    }


def get_status(store: ObservationStore, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")

    official = _source_status(store, "samsara", now)
    third_party = _source_status(store, "student_public", now)

    def live(candidate):
        return candidate["sourceState"] == "live" and candidate["transportState"] == "healthy"

    if live(official):
        chosen = official
    elif live(third_party):
        chosen = third_party
    else:
        available = [c for c in (official, third_party) if c["last_poll"] is not None]
        chosen = max(
            available, key=lambda c: (c["last_poll"], c["source"] == "samsara")
        ) if available else official

    source = chosen["source"]
    is_public_relay = source == "student_public"
    # Publicly shown *student-site* predictions are not verified arrival times.
    # Only expose a bounded, source-attributed snapshot when source transport
    # and the corresponding source-reported vehicles are both fresh.
    source_arrivals = None
    if is_public_relay and live(chosen):
        fresh_by_id = {v["vehicleId"]:v for v in chosen["vehicles"]
                       if v["freshness"] == "fresh"}
        rows = [r for r in store.current_source_arrivals(now)
                if r["vehicleId"] in fresh_by_id]
        if rows:
            by_stop = {k:[] for k in ("125","135","marshak","145")}
            for row in rows:
                bus = fresh_by_id[row["vehicleId"]]
                # The student source publishes an earliest/latest window for
                # some experimental forecasts. This is NOT an independently
                # validated confidence interval. Only forward intact, sane
                # source bounds; do not construct our own range here.
                early = row.get("earliestAt")
                late = row.get("latestAt")
                try:
                    estimate = datetime.fromisoformat(row["arrivalAt"].replace("Z", "+00:00"))
                    early_dt = datetime.fromisoformat(early) if early else None
                    late_dt = datetime.fromisoformat(late) if late else None
                    valid_bounds = (
                        early_dt is not None and late_dt is not None
                        and all(dt.tzinfo for dt in (estimate, early_dt, late_dt))
                        and early_dt <= estimate <= late_dt
                        and (late_dt - early_dt).total_seconds() <= 7200
                        and (late_dt - early_dt).total_seconds() >= 0
                    )
                except (ValueError, TypeError, OverflowError):
                    valid_bounds = False
                by_stop[row["stopId"]].append({
                    "vehicleId":row["vehicleId"],
                    "busName":bus["busName"],
                    "direction":row["direction"],
                    "arrivalAt":row["arrivalAt"],
                    "earliestAt":early if valid_bounds else None,
                    "latestAt":late if valid_bounds else None,
                    "providerPredictionsEnabled":row["providerPredictionsEnabled"],
                })
            source_arrivals = {
                "source":"student_public",
                "experimental":True,
                "calibrated":False,
                "generatedAt":max(row["generatedAt"] for row in rows),
                "stops":by_stop,
            }
    # Separately expose a *small, explicitly unverified* set of the student's
    # source-generated projections when a bus GPS fix is old. These are NOT
    # GPS-derived ETAs, not live arrivals, and never substitute coordinates.
    # Avoid the student's extrapolated multi-loop schedule: one future slot
    # per known bus per stop, at most 2 rows, 45-minute horizon, >90s lead.
    source_projections = None
    if is_public_relay and chosen["transportState"] == "healthy":
        old_by_id = {v["vehicleId"]:v for v in chosen["vehicles"]
                     if v["freshness"] != "fresh"
                     and 30 < v["gpsAgeSeconds"] <= 300}
        if old_by_id:
            projected = {k:[] for k in ("125","135","marshak","145")}
            seen = {k:set() for k in projected}
            issued = []
            for row in store.current_source_arrivals(now, max_age_seconds=45):
                bus = old_by_id.get(row["vehicleId"])
                stop = row["stopId"]
                if bus is None or stop not in projected:
                    continue
                if row["vehicleId"] in seen[stop] or len(projected[stop]) >= 2:
                    continue
                try:
                    at = datetime.fromisoformat(row["arrivalAt"].replace("Z","+00:00"))
                    lead = (at - now).total_seconds()
                    if not 90 <= lead <= 2700:
                        continue
                    early = datetime.fromisoformat(row["earliestAt"].replace("Z","+00:00")) if row.get("earliestAt") else None
                    late = datetime.fromisoformat(row["latestAt"].replace("Z","+00:00")) if row.get("latestAt") else None
                    good_range = (early is not None and late is not None
                                  and all(dt.tzinfo for dt in (at,early,late))
                                  and early <= at <= late
                                  and 0 <= (late-early).total_seconds() <= 7200)
                except (ValueError,TypeError,OverflowError):
                    continue
                seen[stop].add(row["vehicleId"])
                projected[stop].append({
                    "vehicleId":row["vehicleId"],
                    "busName":bus["busName"],
                    "direction":row["direction"],
                    "arrivalAt":row["arrivalAt"],
                    "earliestAt":row["earliestAt"] if good_range else None,
                    "latestAt":row["latestAt"] if good_range else None,
                    "providerPredictionsEnabled":row["providerPredictionsEnabled"],
                    "gpsAgeSeconds":bus["gpsAgeSeconds"],
                })
                issued.append(row["generatedAt"])
            if issued:
                source_projections = {
                    "source":"student_public", "experimental":True,
                    "calibrated":False, "mode":"projection_without_fresh_gps",
                    "generatedAt":max(issued),"stops":projected,
                    "liveGPSConfirmed":False,
                }
    return {
        "generatedAt": iso_z(now),
        "source": source,
        "sourceLabel": (
            "Student shuttle tracker (third-party GPS relay)"
            if is_public_relay else "Official Samsara GPS"
        ),
        "sourceState": chosen["sourceState"],
        "lastSuccessfulPoll": (
            iso_z(chosen["last_poll"]) if chosen["last_poll"] else None
        ),
        "lastPollAgeSeconds": (
            round(chosen["poll_age"], 1) if chosen["poll_age"] is not None else None
        ),
        "transportState": chosen["transportState"],
        "observationsStored": store.count_observations(),
        "vehicles": chosen["vehicles"],
        "sourceArrivalEstimates": source_arrivals,
        "sourceUnverifiedProjections": source_projections,
        "independentlyVerified": not is_public_relay and live(chosen),
        "warning": (
            "Third-party Samsara-derived GPS reports; not independently verified. "
            "No calibrated arrival estimates available."
            if is_public_relay
            else "No calibrated arrival estimates available. Vehicle GPS may be old."
        ),
    }
