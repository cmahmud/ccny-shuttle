"""Read-only, provenance-aware status and vehicle snapshot.

Trusted official GPS is preferred. If that source is not currently active, a
clearly labeled student-public relay may be shown as a *third-party report*.
No service estimates, extrapolates, or fabricates vehicle coordinates.
"""
from datetime import datetime, timezone

from .models import Observation
from .storage import ObservationStore

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
        vehicles.append({
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
        "independentlyVerified": not is_public_relay and live(chosen),
        "warning": (
            "Third-party Samsara-derived GPS reports; not independently verified. "
            "No calibrated arrival estimates available."
            if is_public_relay
            else "No calibrated arrival estimates available. Vehicle GPS may be old."
        ),
    }
