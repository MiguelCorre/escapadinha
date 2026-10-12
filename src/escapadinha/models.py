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
    fetched_at: datetime
    raw_json: str
    found_date: date | None = None   # when a user found the price (source cache), if known
    run_id: int | None = None
    id: int | None = None

    @property
    def nights(self) -> int:
        return (self.return_date - self.departure_date).days

    @property
    def route_key(self) -> str:
        return f"{self.origin}-{self.destination}"

    @property
    def offer_key(self) -> tuple:
        """Identity of an offer independent of when we saw it."""
        return (self.origin, self.destination, self.departure_date, self.return_date,
                self.airline, self.price)


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
