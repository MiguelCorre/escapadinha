"""Ryanair's own fare finder (D47): the cheapest round trip per departure day, live.

`roundTripFares` is the JSON behind ryanair.com's "Fare Finder": for an airport pair and an
outbound window it returns, per outbound day, the cheapest return within the requested trip
length, with the price Ryanair itself shows at that moment (`priceUpdated` says when its fare
cache last changed it). Nonstop by construction: the fare finder lists Ryanair's own flights.

The rules of the source (D47, amending D13): low volume (a bounded, rotating hot list and the
open promotions' months), one plain request at a time, a user-agent that names the site, and
never a step around a bot wall: the first 403, 429 or challenge page raises `blocked` and the
pipeline pauses the source for `airlines.ryanair.blocked_hours`. No retries.

Every price stored is the payload's own (`raw_json` keeps the fare); the link goes to
ryanair.com for the same dates (the airline's site, no commission: D47's link rule).
"""

from __future__ import annotations

import calendar
import json
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from escapadinha.collector.base import Fetched
from escapadinha.collector.travelpayouts import RateLimiter
from escapadinha.models import Observation, RouteRules
from escapadinha.storage.db import utcnow

SOURCE = "ryanair"
# Every source that is an airline's own site (D47): their links go to the airline, no partner.
AIRLINE_SOURCES = frozenset({SOURCE})
AIRLINE = "FR"
SELLER = "Ryanair"
API_URL = "https://www.ryanair.com/api/farfnd/v4/roundTripFares"
BOOKING_URL = "https://www.ryanair.com/pt/pt/trip/flights/select"
MARKET = "pt-pt"
CURRENCY = "EUR"


class RyanairError(RuntimeError):
    """`kind`: "blocked" (403, 429 or a challenge page instead of JSON: the pipeline pauses the
    source), "http" (any other non-200), "api" (200 but not the expected JSON)."""

    def __init__(self, message: str, *, kind: str, status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status


def month_end(month: date) -> date:
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def request_params(origin: str, airport: str, month: date, rules: RouteRules) -> dict:
    """One request: every outbound day of `month`, returns `min_nights`–`max_nights` later."""
    start, end = month.replace(day=1), month_end(month)
    return {
        "departureAirportIataCode": origin,
        "arrivalAirportIataCode": airport,
        "outboundDepartureDateFrom": start.isoformat(),
        "outboundDepartureDateTo": end.isoformat(),
        "inboundDepartureDateFrom": (start + timedelta(days=rules.min_nights)).isoformat(),
        "inboundDepartureDateTo": (end + timedelta(days=rules.max_nights)).isoformat(),
        "durationFrom": rules.min_nights,
        "durationTo": rules.max_nights,
        "market": MARKET,
        "adultPaxCount": 1,
        "currency": CURRENCY,
        "searchMode": "ALL",
        "outboundDepartureTimeFrom": "00:00",
        "outboundDepartureTimeTo": "23:59",
        "inboundDepartureTimeFrom": "00:00",
        "inboundDepartureTimeTo": "23:59",
    }


def booking_url(origin: str, airport: str, departure: date, ret: date) -> str:
    """ryanair.com's flight selection for these dates: the airline's own page, no tracking."""
    return BOOKING_URL + "?" + urlencode({
        "adults": 1, "teens": 0, "children": 0, "infants": 0,
        "dateOut": departure.isoformat(), "dateIn": ret.isoformat(),
        "isConnectedFlight": "false", "isReturn": "true", "discount": 0,
        "originIata": origin, "destinationIata": airport,
    })


def user_agent(base_url: str) -> str:
    """Identifies the site in every request (D47): who is asking and where to write."""
    return f"pontonomada.pt price check (+{base_url.rstrip('/')}/sobre/)"


def _updated(leg: dict) -> datetime | None:
    value = leg.get("priceUpdated")
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def _flight_number(leg: dict) -> str | None:
    number = leg.get("flightNumber")
    if not isinstance(number, str) or not number:
        return None
    return number[len(AIRLINE):] if number.startswith(AIRLINE) else number


def parse_fares(payload: dict, *, origin: str, destination: str, airport: str,
                fetched_at: datetime, rules: RouteRules) -> list[Observation]:
    """Round-trip Observations from a `roundTripFares` payload: `destination` is the route's
    city code (the route key), `airport` the Ryanair airport the fares land at.

    A fare without both legs, without a positive summary price or outside the route's nights
    range is dropped, never patched up. `found_at`/`found_date` = the newer `priceUpdated` of
    the two legs (when Ryanair last changed the price), the closest thing to a traveller's
    "found" time for a live source.
    """
    fares = payload.get("fares")
    if not isinstance(fares, list):
        raise RyanairError("unexpected payload: no `fares` list", kind="api")
    out = []
    for fare in fares:
        outbound, inbound, summary = fare.get("outbound"), fare.get("inbound"), fare.get("summary")
        if not (isinstance(outbound, dict) and isinstance(inbound, dict) and isinstance(summary, dict)):
            continue
        price = (summary.get("price") or {}).get("value")
        departure_at, return_at = outbound.get("departureDate"), inbound.get("departureDate")
        if (not isinstance(price, (int, float)) or price <= 0
                or not isinstance(departure_at, str) or not isinstance(return_at, str)):
            continue
        try:
            departure = datetime.fromisoformat(departure_at).date()
            ret = datetime.fromisoformat(return_at).date()
        except ValueError:
            continue
        if not rules.min_nights <= (ret - departure).days <= rules.max_nights:
            continue
        updated = [t for t in (_updated(outbound), _updated(inbound)) if t is not None]
        found_at = max(updated) if updated else None
        out.append(Observation(
            source=SOURCE,
            origin=origin,
            destination=destination,
            origin_airport=(outbound.get("departureAirport") or {}).get("iataCode") or origin,
            destination_airport=(outbound.get("arrivalAirport") or {}).get("iataCode") or airport,
            departure_date=departure,
            return_date=ret,
            price=float(price),
            currency=str((summary.get("price") or {}).get("currencyCode") or CURRENCY).upper(),
            airline=AIRLINE,
            flight_number=_flight_number(outbound),
            transfers=0,
            return_transfers=0,
            deep_link=booking_url(origin, airport, departure, ret),
            fetched_at=fetched_at,
            raw_json=json.dumps(fare, ensure_ascii=False, sort_keys=True),
            found_date=found_at.date() if found_at else fetched_at.date(),
            departure_at=departure_at,
            return_at=return_at,
            gate=SELLER,
            found_at=found_at,
        ))
    return out


class RyanairSource:
    """`fetch_fares` is the collector's entry: one request per (origin, airport, month). It is
    not a `PriceSource` (those take a city code): the hot list runner and the live check pass
    the airport the fares are for."""

    name = SOURCE

    def __init__(self, *, user_agent: str, client: httpx.Client | None = None,
                 now: Callable[[], datetime] | None = None,
                 limiter: RateLimiter | None = None):
        self._client = client or httpx.Client(timeout=30)
        self._headers = {"User-Agent": user_agent, "Accept": "application/json",
                         "Accept-Language": "pt-PT,pt;q=0.9", "Accept-Encoding": "gzip, deflate"}
        self._now = now or utcnow
        self._limiter = limiter

    def fetch_fares(self, origin: str, destination: str, airport: str, month: date, *,
                    rules: RouteRules) -> Fetched:
        params = request_params(origin, airport, month, rules)
        payload = self._get(params)
        fetched_at = self._now()
        observations = parse_fares(payload, origin=origin, destination=destination,
                                   airport=airport, fetched_at=fetched_at, rules=rules)
        return Fetched(observations, {
            "source": SOURCE, "origin": origin, "destination": destination, "airport": airport,
            "month": month.strftime("%Y-%m"), "fetched_at": fetched_at.isoformat(),
            "params": params, "payload": payload})

    def _get(self, params: dict) -> dict:
        if self._limiter:
            self._limiter.wait()
        response = self._client.get(API_URL, params=params, headers=self._headers)
        content_type = response.headers.get("content-type", "")
        if response.status_code in (403, 429) or (
                response.status_code == 200 and "json" not in content_type):
            raise RyanairError(f"blocked: HTTP {response.status_code} ({content_type or 'no type'})",
                               kind="blocked", status=response.status_code)
        if response.status_code != 200:
            raise RyanairError(f"HTTP {response.status_code}: {response.text[:200]}",
                               kind="http", status=response.status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            raise RyanairError(f"not JSON: {exc}", kind="api") from exc
        if not isinstance(payload, dict):
            raise RyanairError("unexpected payload: not an object", kind="api")
        return payload


def pause_until(blocked_at: datetime, hours: int) -> datetime:
    return blocked_at + timedelta(hours=hours)


__all__ = ["AIRLINE", "API_URL", "RyanairError", "RyanairSource", "SELLER", "SOURCE",
           "booking_url", "parse_fares", "pause_until", "request_params", "user_agent"]

