"""Official Samsara Vehicle Stats feed adapter; credentials required.

This module deliberately does not scrape the public viewer or bypass access controls.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Callable
from urllib.error import HTTPError, URLError
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Observation, parse_time


API_URL = "https://api.samsara.com/fleet/vehicles/stats/feed"


class SamsaraFeedError(RuntimeError):
    """Remote feed failed; never includes tokens or response bodies."""


class SourcePermissionError(SamsaraFeedError):
    """Credentials are invalid or lack shuttle GPS read permissions."""


class SourceCursorError(SamsaraFeedError):
    """The cursor may be expired/invalid; requires deliberate recovery."""


class SourceRateLimited(SamsaraFeedError):
    """Back off rather than repeatedly requesting rate-limited data."""

    def __init__(self, retry_after_seconds: float = 30):
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Samsara GPS feed temporarily rate-limited")


class SourceUnavailable(SamsaraFeedError):
    """Temporary upstream/network issue."""


def _retry_seconds(raw: str | None, now: datetime) -> float:
    if not raw:
        return 30
    try:
        return min(300.0, max(5.0, float(raw)))
    except (ValueError, TypeError):
        pass
    try:
        when = parsedate_to_datetime(raw)
        return min(300.0, max(5.0, (when - now).total_seconds()))
    except (ValueError, TypeError, OverflowError):
        return 30



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
        try:
            with self._opener(request, timeout=self._timeout) as response:
                # Preserve source-connection failures as sanitized errors.
                payload = json.load(response)
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise SourcePermissionError(
                    "Samsara token is invalid or lacks vehicle statistics permission"
                ) from None
            if exc.code == 429:
                delay = _retry_seconds(exc.headers.get("Retry-After"), datetime.now(timezone.utc))
                raise SourceRateLimited(delay) from None
            if exc.code in (400, 404, 410) and cursor:
                raise SourceCursorError(
                    "Samsara rejected the saved cursor; backfill/recovery must be reviewed"
                ) from None
            raise SourceUnavailable(f"Samsara HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError) as exc:
            raise SourceUnavailable("Samsara network request failed") from None
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SourceUnavailable("Samsara did not return valid JSON") from None
        return parse_page(payload, self.vehicle_ids, datetime.now(timezone.utc))
