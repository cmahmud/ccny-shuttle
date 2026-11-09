"""Read-only, source-timestamp-aware status and vehicle snapshot.

The API NEVER invents or extrapolates vehicle coordinates.
"""
from datetime import datetime, timezone

from .models import Observation
from .storage import ObservationStore


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def get_status(store: ObservationStore, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    last_poll = store.last_successful_poll("samsara")
    poll_age = max(0.0, (now - last_poll).total_seconds()) if last_poll else None
    # Transport health and GPS freshness are independent.
    transport_state = (
        "never_connected" if poll_age is None
        else "healthy" if poll_age <= 45
        else "delayed" if poll_age <= 120
        else "offline"
    )
    records = store.latest_observations()
    vehicles = []
    for obs in records:
        age = round(obs.age_seconds(now), 1)
        freshness = obs.freshness(now)
        vehicles.append({
            "vehicleId": obs.vehicle_id,
            "latitude": obs.latitude,
            "longitude": obs.longitude,
            "headingDegrees": obs.heading_degrees,
            "speedMilesPerHour": obs.speed_mph,
            "observedAt": iso_z(obs.observed_at),
            "receivedAt": iso_z(obs.received_at),
            "gpsAgeSeconds": age,
            "freshness": freshness,
            "locationKind": "confirmed",
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
        "generatedAt": iso_z(now),
        "source": "samsara",
        "sourceState": source_state,
        "lastSuccessfulPoll": iso_z(last_poll) if last_poll else None,
        "lastPollAgeSeconds": round(poll_age, 1) if poll_age is not None else None,
        "transportState": transport_state,
        "observationsStored": store.count_observations(),
        "vehicles": vehicles,
        "warning": (
            "No real-time predictions are available. Vehicle GPS may be old."
            if source_state != "live" else None
        ),
    }
