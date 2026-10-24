"""What the probe searches (D48). Pure: the pipeline decides, the probe only reads
`probe/wanted.json`. The open promotions' trips first (the comparison next to each one), then the
cheapest fresh nonstop offer of each route, busiest route first, in rotation (meta cursor), up to
`limit` trips a run: a run of the probe is three page loads a trip at a human pace."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime

from escapadinha.models import Observation

VERSION = 1
KEY = "probe/wanted.json"


@dataclass(frozen=True)
class Trip:
    origin: str                 # airport
    destination: str            # the route's city code (the observation's route key)
    airport: str | None         # destination airport when known (STN), else the city (LON)
    departure: date
    return_date: date
    reason: str                 # promotion | low
    deal_id: int | None = None
    observation_id: int | None = None

    @property
    def key(self) -> tuple[str, str, date, date]:
        return (self.origin, self.destination, self.departure, self.return_date)

    def to_json(self) -> dict:
        d = asdict(self)
        d["departure"], d["return_date"] = self.departure.isoformat(), self.return_date.isoformat()
        return d

    @classmethod
    def from_json(cls, d: dict) -> Trip:
        return cls(d["origin"], d["destination"], d.get("airport"), date.fromisoformat(d["departure"]),
                   date.fromisoformat(d["return_date"]), d.get("reason", "low"), d.get("deal_id"),
                   d.get("observation_id"))


@dataclass(frozen=True)
class Wanted:
    trips: tuple[Trip, ...]
    cursor: int                 # where the next run's rotation starts
    n_promotions: int

    def describe(self) -> str:
        text = f"{len(self.trips)} trips"
        if self.n_promotions:
            text += f" ({self.n_promotions} open promotions first)"
        return text


def trip_of(o: Observation, reason: str, deal_id: int | None = None) -> Trip:
    return Trip(o.origin, o.destination, o.destination_airport, o.departure_date, o.return_date,
                reason, deal_id, o.id)


def plan(promotions: Iterable[tuple[int, Observation]], cheapest: Sequence[Observation], *,
         cursor: int, limit: int) -> Wanted:
    """`promotions`: (deal id, observation) of every open promotion; `cheapest`: one fresh
    nonstop offer per route, busiest route first (the caller ranks them). One rotation: the
    promotions (each trip once) then `cheapest`, from `cursor` on, wrapping around, `limit`
    trips a run; `n_promotions` counts the promotions in this run's list."""
    limit = max(limit, 0)
    trips: list[Trip] = []
    seen: set[tuple[str, str, date, date]] = set()
    promo_trips: list[Trip] = []
    for deal_id, o in promotions:
        t = trip_of(o, "promotion", deal_id)
        if t.key not in seen:
            promo_trips.append(t)
            seen.add(t.key)
    # One rotation over promotions then the routes' cheapest offers: with more open promotions
    # than `limit` (23 against 10 on 2026-10-24) every promotion still gets its turn.
    rotation = promo_trips + [trip_of(o, "low") for o in cheapest]
    position = cursor % len(rotation) if rotation else 0
    taken = 0
    keys: set[tuple[str, str, date, date]] = set()
    while rotation and taken < len(rotation) and len(trips) < limit:
        t = rotation[(position + taken) % len(rotation)]
        taken += 1
        if t.key not in keys:
            trips.append(t)
            keys.add(t.key)
    new_cursor = (position + taken) % len(rotation) if rotation else 0
    return Wanted(tuple(trips), new_cursor, sum(t.reason == "promotion" for t in trips))


def to_json(wanted: Wanted, *, generated_at: datetime, run_id: int | None) -> dict:
    return {"version": VERSION, "generated_at": generated_at.isoformat(), "run": run_id,
            "trips": [t.to_json() for t in wanted.trips]}


def from_json(doc: dict) -> list[Trip]:
    if doc.get("version") != VERSION:
        raise ValueError(f"probe/wanted.json version {doc.get('version')!r}, expected {VERSION}")
    return [Trip.from_json(t) for t in doc.get("trips", [])]
