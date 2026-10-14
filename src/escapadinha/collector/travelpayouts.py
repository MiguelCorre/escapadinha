"""Travelpayouts / Aviasales Data API client (v3 prices_for_dates).

Data is a cache of prices Aviasales users found recently, so it is not live. Each response
is archived verbatim with the run; each offer is stored once with our own fetched_at
timestamp and the day the price was actually found (`search_date` in the item's link),
which can be days earlier.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx

from escapadinha.collector.base import Fetched
from escapadinha.models import Observation
from escapadinha.storage.db import utcnow

API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
DEFAULT_BOOKING_BASE = "https://www.aviasales.pt"   # euros, 24h clock, EU dates
SOURCE = "travelpayouts"


class TravelpayoutsError(RuntimeError):
    """The message is technical (logs, run errors). `kind` says what failed, for a pt-PT reason
    shown to a reviewer (`pipeline.check_failure`): "http" (`status` set), "api" (the payload
    says success false), "token" (no API token) or "error"."""

    def __init__(self, message: str, *, kind: str = "error", status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status


# "/search/LIS1811LON22111?..." -> local departure 18/11 and return 22/11 (then passengers).
_LINK_DATES = re.compile(r"^/search/[A-Z]{3}(\d{2})(\d{2})[A-Z]{3}(\d{2})(\d{2})\d")


def _near(day: int, month: int, utc_day: date) -> date | None:
    """The date with this day/month that is within one day of the UTC date, if any."""
    for year in (utc_day.year - 1, utc_day.year, utc_day.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if abs(candidate - utc_day) <= timedelta(days=1):
            return candidate
    return None


def local_dates(link: str | None, departure_utc: date, return_utc: date) -> tuple[date, date]:
    """Local trip dates from the Aviasales link; API timestamps are UTC, which shifts
    flights just after midnight to the previous day. Falls back to the UTC dates."""
    m = _LINK_DATES.match(link or "")
    if not m:
        return departure_utc, return_utc
    dep = _near(int(m[1]), int(m[2]), departure_utc)
    ret = _near(int(m[3]), int(m[4]), return_utc)
    if dep is None or ret is None:
        return departure_utc, return_utc
    return dep, ret


def found_date(link: str | None) -> date | None:
    """Day an Aviasales user found this price: `search_date=DDMMYYYY` in the link."""
    if not link:
        return None
    values = parse_qs(urlsplit(link).query).get("search_date")
    try:
        return datetime.strptime(values[0], "%d%m%Y").date() if values else None
    except ValueError:
        return None


def parse_response(payload: dict, *, origin: str, destination: str, fetched_at: datetime,
                   min_nights: int, max_nights: int,
                   booking_base: str = DEFAULT_BOOKING_BASE) -> list[Observation]:
    """Turn an API payload into round-trip Observations within the nights range.

    Items without a return date or a positive price are dropped, never patched up.
    """
    if not payload.get("success", False):
        raise TravelpayoutsError(f"API error: {payload.get('error') or 'unknown'}", kind="api")

    currency = str(payload.get("currency", "")).upper()
    observations = []
    for item in payload.get("data") or []:
        price = item.get("price")
        departure_at, return_at = item.get("departure_at"), item.get("return_at")
        if not departure_at or not return_at or not isinstance(price, (int, float)) or price <= 0:
            continue
        link = item.get("link")
        departure, ret = local_dates(link, datetime.fromisoformat(departure_at).date(),
                                     datetime.fromisoformat(return_at).date())
        nights = (ret - departure).days
        if not (min_nights <= nights <= max_nights):
            continue
        observations.append(Observation(
            source=SOURCE,
            origin=origin,
            destination=destination,
            origin_airport=item.get("origin_airport"),
            destination_airport=item.get("destination_airport"),
            departure_date=departure,
            return_date=ret,
            price=float(price),
            currency=currency,
            airline=item.get("airline"),
            flight_number=None if item.get("flight_number") is None else str(item["flight_number"]),
            transfers=item.get("transfers"),
            return_transfers=item.get("return_transfers"),
            deep_link=f"{booking_base}{link}" if link and link.startswith("/") else link,
            fetched_at=fetched_at,
            found_date=found_date(link),
            raw_json=json.dumps(item, ensure_ascii=False, sort_keys=True),
            departure_at=departure_at,
            return_at=return_at,
        ))
    return observations


class RateLimiter:
    """At most `per_minute` calls in any 60-second window (sliding window, injectable clock).

    The v3 API allows 600 requests a minute; at ~300 routes × 3 months a run makes ~900, so
    a fast connection would hit the limit. Waiting here is cheaper than a 429 (which blocks
    until the minute resets and costs a retry). Thread-safe: concurrent requests share it.
    """

    def __init__(self, per_minute: int, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self._per_minute = per_minute
        self._clock = clock
        self._sleep = sleep
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:                 # a waiting thread holds the others back: that's the point
            self._wait()

    def _wait(self) -> None:
        now = self._clock()
        while self._calls and now - self._calls[0] >= 60:
            self._calls.popleft()
        if len(self._calls) >= self._per_minute:
            self._sleep(60 - (now - self._calls[0]))
            now = self._clock()
            while self._calls and now - self._calls[0] >= 60:
                self._calls.popleft()
        self._calls.append(now)


def request_params(origin: str, destination: str, month: date, *, currency: str, limit: int,
                   market: str | None) -> dict:
    """Query of one route-month request (the token goes in a header, not here). The review
    snapshot carries it so the review Function's live check asks exactly the same (D26)."""
    params = {
        "origin": origin,
        "destination": destination,
        "departure_at": month.strftime("%Y-%m"),
        "one_way": "false",
        "currency": currency.lower(),
        "sorting": "price",
        "unique": "false",
        "limit": limit,
    }
    if market:
        params["market"] = market
    return params


class TravelpayoutsSource:
    name = SOURCE

    def __init__(self, token: str, *, currency: str, limit: int, market: str | None = None,
                 booking_base: str = DEFAULT_BOOKING_BASE, client: httpx.Client | None = None,
                 now: Callable[[], datetime] | None = None,
                 sleep: Callable[[float], None] = time.sleep, max_attempts: int = 3,
                 limiter: RateLimiter | None = None):
        if not token:
            raise TravelpayoutsError("TRAVELPAYOUTS_TOKEN is not set (see .env.example)",
                                     kind="token")
        self._client = client or httpx.Client(timeout=30)
        self._headers = {"X-Access-Token": token, "Accept-Encoding": "gzip, deflate"}
        self._currency = currency.lower()
        self._limit = limit
        self._market = market
        self._booking_base = booking_base.rstrip("/")
        self._now = now or utcnow
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._limiter = limiter

    def fetch_round_trips(self, origin: str, destination: str, month: date, *,
                          min_nights: int, max_nights: int) -> list[Observation]:
        return self.fetch(origin, destination, month, min_nights=min_nights,
                          max_nights=max_nights).observations

    def fetch(self, origin: str, destination: str, month: date, *,
              min_nights: int, max_nights: int) -> Fetched:
        params = self.request_params(origin, destination, month)
        payload = self._get(params)
        fetched_at = self._now()
        observations = parse_response(payload, origin=origin, destination=destination,
                                      fetched_at=fetched_at, min_nights=min_nights,
                                      max_nights=max_nights, booking_base=self._booking_base)
        return Fetched(observations, {
            "origin": origin, "destination": destination, "month": month.strftime("%Y-%m"),
            "fetched_at": fetched_at.isoformat(), "params": params, "payload": payload})

    def request_params(self, origin: str, destination: str, month: date) -> dict:
        return request_params(origin, destination, month, currency=self._currency,
                              limit=self._limit, market=self._market)


    def _get(self, params: dict) -> dict:
        for attempt in range(1, self._max_attempts + 1):
            if self._limiter:
                self._limiter.wait()
            response = self._client.get(API_URL, params=params, headers=self._headers)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self._max_attempts:
                    break
                # Rate limits are per minute; a 429 blocks until the minute resets.
                retry_after = response.headers.get("Retry-After")
                self._sleep(float(retry_after) if retry_after else 60.0 if response.status_code == 429 else 5.0)
                continue
            if response.status_code != 200:
                raise TravelpayoutsError(f"HTTP {response.status_code}: {response.text[:200]}",
                                         kind="http", status=response.status_code)
            return response.json()
        raise TravelpayoutsError(f"HTTP {response.status_code} after {self._max_attempts} attempts",
                                 kind="http", status=response.status_code)
