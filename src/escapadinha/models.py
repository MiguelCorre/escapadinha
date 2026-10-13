"""Plain data records shared between collector, storage, detector and renderer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Observation:
    """One price returned by a source. Never constructed from anything but API data."""

    source: str
    origin: str
    destination: str
    origin_airport: str | None
    destination_airport: str | None
    departure_date: date
    return_date: date
    price: float
    currency: str
    airline: str | None
    flight_number: str | None
    transfers: int | None
    return_transfers: int | None
    deep_link: str | None
    fetched_at: datetime                 # first time we saw this offer
    raw_json: str = ""                   # API item; archived per run, not stored in the table
    found_date: date | None = None   # when a user found the price (source cache), if known
    run_id: int | None = None            # first run that saw it
    id: int | None = None
    departure_at: str | None = None      # source timestamps, part of the offer's identity
    return_at: str | None = None
    last_seen_at: datetime | None = None
    last_run_id: int | None = None
    seen_count: int = 1                  # number of runs that returned this offer

    @property
    def nights(self) -> int:
        return (self.return_date - self.departure_date).days

    @property
    def route_key(self) -> str:
        return f"{self.origin}-{self.destination}"

    @property
    def dedup_key(self) -> str:
        """Identity of an offer independent of when we saw it: repeats are stored once."""
        parts = (self.source, self.origin, self.destination,
                 self.departure_at or self.departure_date.isoformat(),
                 self.return_at or self.return_date.isoformat(),
                 self.airline or "", self.flight_number or "", f"{self.price:.2f}",
                 self.found_date.isoformat() if self.found_date else "")
        return "|".join(parts)


@dataclass(frozen=True)
class RouteRules:
    """What counts as a usable offer on a route. Defaults come from the route's kind."""

    direct_only: bool = True           # nonstop both ways (overrides max_transfers)
    min_nights: int = 2
    max_nights: int = 10
    max_transfers: int | None = 0      # per direction; None = no limit

    def to_json(self) -> dict:
        """The rules as the data contracts carry them (site data, review snapshot)."""
        return {"direct_only": self.direct_only, "min_nights": self.min_nights,
                "max_nights": self.max_nights, "max_transfers": self.max_transfers}

    def allows(self, o: Observation) -> bool:
        """Within the nights range and the stop limit. Unknown transfer counts never pass a limit."""
        if not self.min_nights <= o.nights <= self.max_nights:
            return False
        limit = 0 if self.direct_only else self.max_transfers
        if limit is None:
            return True
        return (o.transfers is not None and o.return_transfers is not None
                and o.transfers <= limit and o.return_transfers <= limit)


@dataclass(frozen=True)
class Route:
    """A watched origin → destination pair, independent of dates (stored in `routes`)."""

    origin: str
    destination: str                   # provider city code (e.g. LON)
    city_pt: str
    kind: str                          # europe | long_haul | domestic
    rules: RouteRules
    status: str = "active"             # active | dormant
    price_cap_eur: float | None = None
    destination_airports: str | None = None
    discovered_at: datetime | None = None
    last_observed_at: datetime | None = None
    city_en: str | None = None         # English name from the provider catalogue (photo search)

    @property
    def key(self) -> str:
        return f"{self.origin}-{self.destination}"


@dataclass(frozen=True)
class Deal:
    id: int
    observation_id: int
    rule: str
    baseline_median: float | None
    sample_size: int
    discount_pct: float | None
    threshold: float
    detected_at: datetime
    status: str
    affiliate_url: str | None = None     # tracked link from the partner links API
    affiliate_error: str | None = None   # why conversion failed, if it did
    last_checked_at: datetime | None = None
    last_seen_price: float | None = None
    expired_reason: str | None = None
    output_path: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    published_at: datetime | None = None
    post_url: str | None = None


@dataclass(frozen=True)
class Photo:
    destination: str
    file_path: str
    source: str
    source_url: str
    photographer: str
    photographer_url: str
    license: str
    fetched_at: datetime
