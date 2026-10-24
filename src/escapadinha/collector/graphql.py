"""Aviasales GraphQL Flights Data API client (Travelpayouts), for enrichment only (D43).

Same cache and token as the REST Data API (`travelpayouts.py`), 60 requests a minute. It is
not a price source: nothing it returns is ever stored as a price. It answers one question per
low price or promotion candidate: which cached offer is this exactly (`ticket_link`), does it
include a checked bag (`with_baggage`, `baggage_code`), which agency sells it (`gate`) and when
exactly a traveller found it (`found_at`, a Unix timestamp).

Matching an observation to a row (`match`) is pure. The REST item's link and the GraphQL
`ticket_link` carry the same `t=` token (ticket, search and agency price), so an offer with a
link is matched by that token: the same cached offer, nothing guessed. Without a link the
fallback is the airline, the local trip dates and the price; the REST price is rounded to the
euro, so a value that rounds to it matches. A field is stored only when every matching row
agrees on it; otherwise it stays unknown.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import httpx

from escapadinha.collector.travelpayouts import RateLimiter, TravelpayoutsError, local_dates
from escapadinha.models import Observation
from escapadinha.storage.db import utcnow

API_URL = "https://api.travelpayouts.com/graphql/v1/query"
SOURCE = "travelpayouts-graphql"
PAGE_LIMIT = 400          # the API's maximum `paging.limit` ("limit must be equal or less than 400")
REQUESTS_PER_MINUTE = 60  # the API's limit (`X-Rate-Limit: 60`); config caps below it
FIELDS = ("departure_at return_at origin_airport_iata destination_airport_iata destination_city_iata "
          "value currency number_of_changes main_airline found_at with_baggage baggage_code gate "
          "ticket_link")
QUERY = f"""query PricesRoundTrip($params: ParamsRoundTrip!, $paging: Paging, $currency: String, $market: String) {{
  prices_round_trip(params: $params, paging: $paging, grouping: NONE, sorting: VALUE_ASC,
                    currency: $currency, market: $market) {{
    {FIELDS}
  }}
}}"""
# Aviasales' own "special offers" (D46): round trips from one origin they flag as abnormally
# cheap, each with `discount`, their deviation from their average price for the ticket (a
# percentage; their measure, never shown as a price). Introspected 2026-10-24
# (`ParamsSpecialOfferRoundTrip`: origin, destination, depart_months, direct, ...; no sorting).
SPECIAL_OFFERS_QUERY = f"""query SpecialOffers($params: ParamsSpecialOfferRoundTrip!, $paging: Paging, $currency: String, $market: String) {{
  special_offers_round_trip(params: $params, paging: $paging, currency: $currency, market: $market) {{
    {FIELDS} discount
  }}
}}"""
SPECIAL_OFFERS_FIELD = "special_offers_round_trip"


class GraphQLError(TravelpayoutsError):
    """Same kinds as the REST client's: "http" (`status`), "api" (the answer carries `errors`),
    "token", "error"."""


@dataclass(frozen=True)
class Offer:
    """One row of `prices_round_trip` (the API's `Price` type), the fields we read."""

    departure_at: str
    return_at: str | None
    origin_airport: str
    destination_airport: str
    value: float
    currency: str
    transfers: int
    airline: str                  # `main_airline`
    found_at: datetime            # UTC, exact
    with_baggage: bool
    baggage_code: str             # "0PC" = no checked bag, "1PC20" = one 20 kg bag, "" unknown
    gate: str                     # the selling agency
    ticket_link: str              # the REST link's path without its `/search` prefix
    discount: float | None = None # special offers only (D46): Aviasales' % below their average
    destination_city: str | None = None   # `destination_city_iata`, when the answer has it

    @property
    def ticket(self) -> str | None:
        return ticket_token(self.ticket_link)

    @property
    def trip_dates(self) -> tuple[date, date] | None:
        """Local departure and return dates, from the link like the REST collector does."""
        if not self.return_at:
            return None
        dep = datetime.fromisoformat(self.departure_at).date()
        ret = datetime.fromisoformat(self.return_at).date()
        return local_dates("/search" + self.ticket_link, dep, ret)


@dataclass(frozen=True)
class Answer:
    offers: list[Offer]
    response: dict       # request variables + verbatim payload, for the run archive (D18)


@dataclass(frozen=True)
class Match:
    """What `match` found for one observation: a field is None when unknown (no row, or the
    matching rows disagree). `how`: "ticket" (same `t=` token), "offer" (airline, dates and
    price), "none"."""

    with_baggage: bool | None
    baggage_code: str | None
    gate: str | None
    found_at: datetime | None
    how: str

    @property
    def found(self) -> bool:
        return self.how != "none"


NO_MATCH = Match(None, None, None, None, "none")


def ticket_token(link: str | None) -> str | None:
    """The `t=` query parameter of an Aviasales search link, or None."""
    if not link:
        return None
    values = parse_qs(urlsplit(link).query).get("t")
    return values[0] if values and values[0] else None


def variables(origin: str, destination: str, departure: date, ret: date, *, direct: bool,
              currency: str, market: str | None, limit: int = PAGE_LIMIT) -> dict:
    """The query variables for one trip. Dates are given as windows of a day around the stored
    local dates, because the API's timestamps can sit on the UTC day; the match picks the exact
    offer. `direct` only when the route wants nonstop flights (the rows then are the ones the
    route accepts); the cheapest rows come first (VALUE_ASC), one page of `limit`."""
    params = {
        "origin": origin,
        "destination": destination,
        "depart_date_min": (departure - timedelta(days=1)).isoformat(),
        "depart_date_max": departure.isoformat(),
        "return_date_min": (ret - timedelta(days=1)).isoformat(),
        "return_date_max": (ret + timedelta(days=1)).isoformat(),
    }
    if direct:
        params["direct"] = True
    return {"params": params, "paging": {"limit": limit, "offset": 0},
            "currency": currency.lower(), "market": market}


def special_offers_variables(origin: str, *, currency: str, market: str | None,
                             limit: int = PAGE_LIMIT) -> dict:
    """The variables of one `special_offers_round_trip` query: every flagged round trip from
    this origin, one page of `limit`."""
    return {"params": {"origin": origin}, "paging": {"limit": limit, "offset": 0},
            "currency": currency.lower(), "market": market}


def parse_response(payload: dict, field: str = "prices_round_trip") -> list[Offer]:
    """The rows of a `prices_round_trip` (or, `field`, a `special_offers_round_trip`) answer.
    GraphQL errors raise; rows missing a field we need are dropped, never patched up."""
    if not isinstance(payload, dict):
        raise GraphQLError("GraphQL: not a JSON object", kind="api")
    errors = payload.get("errors")
    if errors:
        first = errors[0] if isinstance(errors, list) and errors else errors
        message = first.get("message", "unknown") if isinstance(first, dict) else str(first)
        raise GraphQLError(f"GraphQL error: {message}", kind="api")
    data = payload.get("data") or {}
    rows = data.get(field) if isinstance(data, dict) else None
    if rows is None:
        raise GraphQLError(f"GraphQL: no {field} in the answer", kind="api")
    offers = []
    for row in rows:
        try:
            value = float(row["value"])
            found = row["found_at"]
            if value <= 0 or not isinstance(found, (int, float)) or isinstance(found, bool):
                continue
            offers.append(Offer(
                departure_at=str(row["departure_at"]),
                return_at=None if row.get("return_at") is None else str(row["return_at"]),
                origin_airport=str(row["origin_airport_iata"]),
                destination_airport=str(row["destination_airport_iata"]),
                value=value, currency=str(row.get("currency") or "").upper(),
                transfers=int(row["number_of_changes"]),
                airline=str(row["main_airline"]).upper(),
                found_at=datetime.fromtimestamp(found, timezone.utc),
                with_baggage=bool(row["with_baggage"]),
                baggage_code=str(row.get("baggage_code") or ""),
                gate=str(row["gate"]),
                ticket_link=str(row["ticket_link"]),
                discount=_percentage(row.get("discount")),
                destination_city=(None if row.get("destination_city_iata") is None
                                  else str(row["destination_city_iata"])),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return offers


def _percentage(value: object) -> float | None:
    """A finite number as given (Aviasales' `discount`, a percentage), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def special_offer_for(obs: Observation, offers: list[Offer]) -> Offer | None:
    """The special offer that is this observation's trip (D46): same destination city or
    airport, same local dates, nonstop status compatible and a price within rounding
    (`price_matches`), else None. Several matching rows: the one with the largest discount."""
    rows = [o for o in offers
            if o.destination_airport == (obs.destination_airport or obs.destination)
            or _city(o) == obs.destination]
    rows = [o for o in rows if o.trip_dates == (obs.departure_date, obs.return_date)
            and price_matches(o.value, obs.price)]
    rows = [o for o in rows if o.discount is not None]
    return max(rows, key=lambda o: o.discount, default=None)


def _city(offer: Offer) -> str | None:
    return offer.destination_city


def price_matches(value: float, price: float) -> bool:
    """Within a cent, or, as the REST API rounds prices to the euro (92.5 € comes back as 93),
    a value that rounds (half up) to a whole-euro price."""
    if abs(value - price) <= 0.01:
        return True
    return float(price).is_integer() and math.floor(value + 0.5) == price


def _agreed(rows: list[Offer], field: str):
    values = {getattr(r, field) for r in rows}
    return values.pop() if len(values) == 1 else None


def match(obs: Observation, offers: list[Offer]) -> Match:
    """The GraphQL rows that are this observation's offer, reduced to the fields we store.

    By the link's `t=` token when the observation has one (the same ticket from the same
    search at the same agency price), else by airline, local trip dates and price. Rows that
    disagree on a field leave it unknown: nothing is guessed.
    """
    token = ticket_token(obs.deep_link)
    rows = [o for o in offers if token and o.ticket == token]
    how = "ticket"
    if not rows:
        airline = (obs.airline or "").upper()
        rows = [o for o in offers
                if o.airline == airline and o.trip_dates == (obs.departure_date, obs.return_date)
                and price_matches(o.value, obs.price)]
        how = "offer"
    if not rows:
        return NO_MATCH
    return Match(with_baggage=_agreed(rows, "with_baggage"), baggage_code=_agreed(rows, "baggage_code"),
                 gate=_agreed(rows, "gate"), found_at=_agreed(rows, "found_at"), how=how)


class GraphQLClient:
    """`POST` queries with the token in `X-Access-Token`, a 429 or 5xx retried after waiting
    (`X-Rate-Limit-Reset` / `Retry-After` seconds, else a minute), under a per-minute limiter
    shared by concurrent callers."""

    def __init__(self, token: str, *, currency: str, market: str | None = None,
                 client: httpx.Client | None = None, now: Callable[[], datetime] | None = None,
                 sleep: Callable[[float], None] = time.sleep, max_attempts: int = 3,
                 limiter: RateLimiter | None = None, limit: int = PAGE_LIMIT):
        if not token:
            raise GraphQLError("TRAVELPAYOUTS_TOKEN is not set (see .env.example)", kind="token")
        self._client = client or httpx.Client(timeout=60)
        self._headers = {"X-Access-Token": token, "Accept-Encoding": "gzip, deflate"}
        self._currency = currency
        self._market = market
        self._now = now or utcnow
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._limiter = limiter
        self._limit = limit

    def special_offers_round_trip(self, origin: str) -> Answer:
        """Aviasales' special offers from one origin (D46), with their `discount`."""
        vars_ = special_offers_variables(origin, currency=self._currency, market=self._market,
                                         limit=self._limit)
        payload = self._post(vars_, SPECIAL_OFFERS_QUERY)
        fetched_at = self._now()
        offers = parse_response(payload, SPECIAL_OFFERS_FIELD)
        return Answer(offers, {
            "source": SOURCE, "query": SPECIAL_OFFERS_FIELD, "origin": origin,
            "fetched_at": fetched_at.isoformat(), "variables": vars_, "payload": payload})

    def prices_round_trip(self, origin: str, destination: str, departure: date, ret: date, *,
                          direct: bool) -> Answer:
        """The cached round trips of one route and trip dates, cheapest first."""
        vars_ = variables(origin, destination, departure, ret, direct=direct,
                          currency=self._currency, market=self._market, limit=self._limit)
        payload = self._post(vars_)
        fetched_at = self._now()
        offers = parse_response(payload)
        return Answer(offers, {
            "source": SOURCE, "origin": origin, "destination": destination,
            "departure": departure.isoformat(), "return": ret.isoformat(),
            "fetched_at": fetched_at.isoformat(), "variables": vars_, "payload": payload})

    def _post(self, vars_: dict, query: str = QUERY) -> dict:
        body = {"query": query, "variables": vars_}
        for attempt in range(1, self._max_attempts + 1):
            if self._limiter:
                self._limiter.wait()
            response = self._client.post(API_URL, json=body, headers=self._headers)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self._max_attempts:
                    break
                self._sleep(_wait_seconds(response))
                continue
            if response.status_code != 200:
                raise GraphQLError(f"HTTP {response.status_code}: {response.text[:200]}",
                                   kind="http", status=response.status_code)
            try:
                return response.json()
            except json.JSONDecodeError:
                raise GraphQLError("GraphQL: the answer is not JSON", kind="api") from None
        raise GraphQLError(f"HTTP {response.status_code} after {self._max_attempts} attempts",
                           kind="http", status=response.status_code)


def _wait_seconds(response: httpx.Response) -> float:
    """How long a 429 / 5xx asks us to wait: the limit's reset, Retry-After, else a minute
    (rate limits are per minute) or five seconds (a server error)."""
    for header in ("X-Rate-Limit-Reset", "Retry-After"):
        value = response.headers.get(header)
        if value:
            try:
                return max(1.0, float(value))
            except ValueError:
                continue
    return 60.0 if response.status_code == 429 else 5.0
