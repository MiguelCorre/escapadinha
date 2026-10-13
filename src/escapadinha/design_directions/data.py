"""Real data for the design directions: promotions, recent low prices, photos. Read-only.

Every price on the pages comes from a `price_observations` row (or, for the typical low,
from the detector's median of daily lows over those rows). Nothing here writes to the DB.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from escapadinha import detector
from escapadinha import i18n_pt as pt
from escapadinha.config import AppConfig, Route
from escapadinha.models import Deal, Observation, Photo
from escapadinha.presentation import DISCLOSURE
from escapadinha.storage import db

LIVE = ("approved", "published")
SHOWN = (*LIVE, "expired")   # never new/rendered/rejected: those were not approved or are private
NBSP = "\u00a0"


def eur(amount: float) -> str:
    """pt.eur with a no-break space, so '88,50 €' never wraps before the euro sign."""
    return pt.eur(amount).replace(" €", f"{NBSP}€")


@dataclass(frozen=True)
class PhotoAsset:
    destination: str
    file_name: str
    photographer: str
    photographer_url: str
    source: str           # 'Pixabay'
    source_url: str
    license: str

    @classmethod
    def from_photo(cls, p: Photo) -> PhotoAsset:
        return cls(p.destination, p.file_path, p.photographer, p.photographer_url,
                   p.source.capitalize(), p.source_url, p.license)


@dataclass(frozen=True)
class Trip:
    """One observation, formatted in pt-PT. Shared by promotions and low prices."""
    observation_id: int
    route_key: str
    origin_iata: str
    destination_iata: str
    origin_city: str
    destination_city: str
    arrival_code: str | None
    arrival_airport: str | None    # 'Beauvais (BVA)'
    remote_airport: bool
    price_value: float
    price: str                     # '60 €'
    price_compact: str             # '60€'
    dates: str                     # '25 a 28 de novembro'
    departure_short: str           # 'qua, 25 nov'
    return_short: str
    month: str                     # 'novembro'
    nights: str                    # '3 noites'
    airline: str | None
    direct: bool | None
    found_on: str | None           # day a traveller found the price
    fetched_at: str                # when we fetched it (Lisbon)
    photo: PhotoAsset | None

    @property
    def destination_headline(self) -> str:
        """'Paris (Beauvais)' when the arrival airport is far from the city."""
        if self.remote_airport and self.arrival_code:
            return f"{self.destination_city} ({pt.AIRPORTS.get(self.arrival_code, self.arrival_code)})"
        return self.destination_city


@dataclass(frozen=True)
class LowPrice:
    """A recent observation below the route's typical low (glossary: 'preço baixo')."""
    trip: Trip
    typical_low: str
    typical_low_value: float
    baseline_days: int
    discount_pct: int


@dataclass(frozen=True)
class Promo:
    deal_id: int
    trip: Trip
    status: str
    live: bool
    discount_pct: int | None
    typical_low: str | None
    checked_at: str
    expired_reason: str | None
    booking_url: str | None        # tracked partner link, only while live
    disclosure: str = DISCLOSURE


@dataclass(frozen=True)
class MonthLow:
    label: str          # 'novembro 2026'
    typical_low: str
    value: float
    days: int


@dataclass
class DirectionData:
    built_at: str
    latest_run_at: str | None
    n_observations: int
    n_routes: int
    first_seen: str | None
    promos: list[Promo]
    featured: Promo | None
    lows: list[LowPrice]                          # best per route, biggest discount first
    route_lows: list[LowPrice]                    # more lows on the featured promo's route
    route_months: list[MonthLow]                  # typical low per month, featured route
    photos: dict[str, PhotoAsset] = field(default_factory=dict)

    @property
    def hero(self) -> LowPrice | None:
        return self.lows[0] if self.lows else None

    def all_prices(self) -> set[str]:
        """Every formatted price the pages may show (used by tests)."""
        out = set()
        for p in self.promos:
            out.add(p.trip.price)
        for low in self.lows + self.route_lows:
            out |= {low.trip.price, low.typical_low}
        out |= {m.typical_low for m in self.route_months}
        return out


def _photo_for(conn: sqlite3.Connection, code: str, cache: dict) -> PhotoAsset | None:
    if code not in cache:
        photo = db.get_photo(conn, code)
        cache[code] = PhotoAsset.from_photo(photo) if photo else None
    return cache[code]


def make_trip(o: Observation, cfg: AppConfig, photo: PhotoAsset | None) -> Trip:
    direct = None if o.transfers is None or o.return_transfers is None else detector.is_direct(o)
    code = o.destination_airport.upper() if o.destination_airport else None
    try:
        city = cfg.route(o.route_key).city_pt
    except KeyError:
        city = o.destination
    return Trip(
        observation_id=o.id, route_key=o.route_key, origin_iata=o.origin,
        destination_iata=o.destination, origin_city=cfg.origin_name(o.origin),
        destination_city=city, arrival_code=code, arrival_airport=pt.airport_label(code),
        remote_airport=(code or "") in pt.REMOTE_AIRPORTS,
        price_value=o.price, price=eur(o.price), price_compact=pt.eur_compact(o.price),
        dates=pt.date_range(o.departure_date, o.return_date),
        departure_short=pt.short_date(o.departure_date), return_short=pt.short_date(o.return_date),
        month=pt.MONTHS[o.departure_date.month - 1], nights=pt.nights(o.nights),
        airline=pt.airline_name(o.airline), direct=direct,
        found_on=pt.numeric_date(o.found_date) if o.found_date else None,
        fetched_at=pt.lisbon_timestamp(o.fetched_at), photo=photo,
    )


def _promo(deal: Deal, o: Observation, cfg: AppConfig, photo: PhotoAsset | None) -> Promo:
    live = deal.status in LIVE
    return Promo(
        deal_id=deal.id, trip=make_trip(o, cfg, photo), status=deal.status, live=live,
        discount_pct=None if deal.discount_pct is None else round(deal.discount_pct * 100),
        typical_low=None if deal.baseline_median is None else eur(deal.baseline_median),
        checked_at=pt.lisbon_timestamp(deal.last_checked_at or o.fetched_at),
        expired_reason=None if live or not deal.expired_reason
        else deal.expired_reason.replace(" €", f"{NBSP}€"),
        booking_url=deal.affiliate_url if live else None,
    )


def _route_lows(conn: sqlite3.Connection, cfg: AppConfig, route: Route, candidates: list[Observation],
                now: datetime, photos: dict) -> tuple[list[LowPrice], list[MonthLow]]:
    """Fresh observations below the typical low of their departure month, cheapest first."""
    history = db.route_history(conn, route.origin, route.destination,
                               since=now - timedelta(days=cfg.detector.lookback_days),
                               exclude_run_id=None)
    baselines = detector.month_baselines(history, cfg.detector, now)
    need = cfg.detector.min_baseline_days
    months = [MonthLow(f"{pt.MONTHS[m - 1]} {y}", eur(b.median), b.median, b.sample_size)
              for (y, m), b in sorted(baselines.items())
              if b.median is not None and b.sample_size >= need]
    lows, seen = [], set()
    photo = _photo_for(conn, route.destination, photos)
    for o in sorted(detector.eligible(candidates, cfg.detector), key=lambda o: o.price):
        if o.route_key != route.key or not detector.is_fresh(o, cfg.detector, now):
            continue
        base = baselines.get(detector.month_key(o))
        if base is None or base.median is None or base.sample_size < need or o.price >= base.median:
            continue
        trip_key = (o.departure_date, o.return_date)
        if trip_key in seen:
            continue
        seen.add(trip_key)
        lows.append(LowPrice(make_trip(o, cfg, photo), eur(base.median), base.median,
                             base.sample_size, round((1 - o.price / base.median) * 100)))
    return lows, months


def load(conn: sqlite3.Connection, cfg: AppConfig, now: datetime | None = None,
         deal_id: int | None = None) -> DirectionData:
    now = now or db.utcnow()
    photos: dict[str, PhotoAsset | None] = {}

    promos = [_promo(d, o, cfg, _photo_for(conn, o.destination, photos))
              for d, o in db.deals_with_status(conn, *SHOWN)]
    if deal_id is not None:
        featured = next((p for p in promos if p.deal_id == deal_id), None)
        if featured is None:
            raise KeyError(f"Deal {deal_id} is not approved, published or expired")
    else:
        # Live first, then nonstop trips, then the biggest discount.
        ranked = sorted(promos, key=lambda p: (not p.live, p.trip.direct is not True,
                                               -(p.discount_pct or 0), -p.deal_id))
        featured = ranked[0] if ranked else None

    run_id = db.latest_completed_run_id(conn)
    candidates = db.observations_for_run(conn, run_id) if run_id else []
    best, route_lows, route_months = [], [], []
    for route in cfg.routes:
        lows, months = _route_lows(conn, cfg, route, candidates, now, photos)
        if lows:
            best.append(max(lows, key=lambda low: (low.discount_pct, -low.trip.price_value)))
        if featured and route.key == featured.trip.route_key:
            route_lows, route_months = lows[:4], months
    best.sort(key=lambda low: (-low.discount_pct, low.trip.price_value))

    stats = conn.execute("SELECT COUNT(*), MIN(fetched_at), COUNT(DISTINCT origin || destination) "
                         "FROM price_observations").fetchone()
    run = conn.execute("SELECT finished_at FROM fetch_runs WHERE id = ?", (run_id,)).fetchone() \
        if run_id else None
    return DirectionData(
        built_at=pt.lisbon_timestamp(now),
        latest_run_at=pt.lisbon_timestamp(datetime.fromisoformat(run[0])) if run and run[0] else None,
        n_observations=stats[0], n_routes=stats[2],
        first_seen=pt.numeric_date(datetime.fromisoformat(stats[1]).astimezone(pt.LISBON).date())
        if stats[1] else None,
        promos=promos, featured=featured, lows=best, route_lows=route_lows,
        route_months=route_months,
        photos={k: v for k, v in photos.items() if v is not None},
    )
