"""Official Samsara Vehicle Stats feed adapter; credentials required.

This module deliberately does not scrape the public viewer or bypass access controls.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Observation, parse_time


API_URL = "https://api.samsara.com/fleet/vehicles/stats/feed"


@dataclass(frozen=True, slots=True)
class FeedPage:
    observations: tuple[Observation, ...]
    end_cursor: str
    has_next_page: bool


def parse_page(
    payload: dict,
    allowed_vehicle_ids: frozenset[str],
    received_at: datetime,
) -> FeedPage:
    """Accept Samsara's GPS stat event arrays and enforce an explicit shuttle allowlist."""
    if not allowed_vehicle_ids:
        raise ValueError("A shuttle vehicle ID allowlist is mandatory")
    if not isinstance(payload, dict):
        raise ValueError("Feed response must be an object")
    pagination = payload.get("pagination")
    if not isinstance(pagination, dict):
        raise ValueError("Feed pagination is missing")
    cursor = pagination.get("endCursor")
    has_next = pagination.get("hasNextPage")
    if not isinstance(cursor, str) or not cursor:
        raise ValueError("Feed endCursor is missing")
    if not isinstance(has_next, bool):
        raise ValueError("Feed hasNextPage is invalid")
    vehicles = payload.get("data")
    if not isinstance(vehicles, list):
        raise ValueError("Feed data must be an array")
    observations: list[Observation] = []
    for vehicle in vehicles:
        if not isinstance(vehicle, dict):
            continue
        vehicle_id = str(vehicle.get("id", ""))
        if vehicle_id not in allowed_vehicle_ids:
            continue
        events = vehicle.get("gps", [])
        if isinstance(events, dict):
            events = [events]  # Compatible with snapshot-shaped fixture records.
        if not isinstance(events, list):
            raise ValueError("GPS must be an array or object")
        for event in events:
            if not isinstance(event, dict):
                continue
            try:
                observation = Observation(
                    source="samsara",
                    vehicle_id=vehicle_id,
                    latitude=float(event["latitude"]),
                    longitude=float(event["longitude"]),
                    observed_at=parse_time(event["time"]),
                    received_at=received_at,
                    heading_degrees=(
                        float(event["headingDegrees"])
                        if event.get("headingDegrees") is not None else None
                    ),
                    speed_mph=(
                        float(event["speedMilesPerHour"])
                        if event.get("speedMilesPerHour") is not None else None
                    ),
                )
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError("Invalid GPS event in authorized vehicle feed") from exc
            observations.append(observation)
    return FeedPage(tuple(observations), cursor, has_next)


class SamsaraFeed:
    """Request one page; cursor management is handled by the collector."""

    def __init__(
        self,
        api_token: str,
        vehicle_ids: frozenset[str],
        opener: Callable = urlopen,
        timeout: float = 15.0,
    ) -> None:
        if not api_token.strip():
            raise ValueError("Samsara API token is required")
        if not vehicle_ids:
            raise ValueError("Set explicit shuttle vehicle IDs before connecting")
        self._token = api_token
        self.vehicle_ids = vehicle_ids
        self._opener = opener
        self._timeout = timeout

    def fetch(self, cursor: str | None = None) -> FeedPage:
        params = {"types": "gps", "vehicleIds": ",".join(sorted(self.vehicle_ids))}
        if cursor:
            params["after"] = cursor
        request = Request(
            API_URL + "?" + urlencode(params),
            headers={
                "Authorization": "Bearer " + self._token,
                "Accept": "application/json",
                "User-Agent": "ccny-smart-shuttle/0.1",
            },
        )
        with self._opener(request, timeout=self._timeout) as response:
            payload = json.load(response)
        return parse_page(payload, self.vehicle_ids, datetime.now(timezone.utc))
