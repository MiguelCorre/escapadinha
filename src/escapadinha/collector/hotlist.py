"""Which airline-site requests a run makes (D47). Pure: routes, history and the clock passed in.

An airline source is never a bulk collector. Each run asks:
1. the months of the open promotions on that airline's flights, always (their recheck and the
   comparison on the review pages need the airline's price every run), then
2. the next `limit` (pair, month) tasks of a rotation over every known airport pair, busiest
   route first (Eurostat demand rank, D45, then offers seen), so every pair is asked within a
   day or two at a few hundred requests a day in all.

A pair is (route, destination airport): routes are city codes (LON) and the airline flies to
airports (STN); the airports come from the offers the cache already showed for the airline.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from escapadinha import demand
from escapadinha.models import Route


@dataclass(frozen=True)
class Pair:
    route: Route
    airport: str                    # the airline's destination airport on this route

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.route.origin, self.route.destination, self.airport)


@dataclass(frozen=True)
class HotPlan:
    tasks: tuple[tuple[Pair, date], ...]    # in request order: promotions' months first
    cursor: int                             # where the next run's rotation starts
    n_deal_tasks: int                       # tasks asked for open promotions
    n_pairs: int                            # airport pairs known for the airline
    n_months: int                           # months of the rotation per pair

    def describe(self) -> str:
        rotation = len(self.tasks) - self.n_deal_tasks
        text = f"{rotation} of {self.n_pairs * self.n_months} pair-months in rotation"
        if self.n_deal_tasks:
            text += f" + {self.n_deal_tasks} for open promotions"
        return text


def pairs(routes: Iterable[Route], seen: Iterable[tuple[str, str, str, int]]) -> list[Pair]:
    """`seen`: (origin, destination city, destination airport, offers seen) for the airline's
    offers. Pairs on active routes only, busiest first: demand rank (`demand.rank_routes`,
    routes without a figure last), then offers seen, then the key (stable)."""
    active = {r.key: r for r in routes if r.status == "active"}
    counts: dict[tuple[str, str, str], int] = {}
    for origin, destination, airport, n in seen:
        if not airport or f"{origin}-{destination}" not in active:
            continue
        counts[(origin, destination, airport)] = counts.get((origin, destination, airport), 0) + n
    ranks = demand.rank_routes(active.values())
    ordered = sorted(counts, key=lambda k: (ranks.get(f"{k[0]}-{k[1]}", len(active) + 1),
                                            -counts[k], k))
    return [Pair(active[f"{o}-{d}"], a) for o, d, a in ordered]


def plan(known: Sequence[Pair], *, months: Sequence[date],
         deal_trips: Iterable[tuple[str, str, str | None, date]], cursor: int,
         limit: int) -> HotPlan:
    """`deal_trips`: (origin, destination, airport, first day of the departure month) of the
    open promotions on the airline's flights; a trip whose airport is unknown, or whose pair the
    airline has no offers for, is skipped (the cache's recheck still judges it). `cursor`: the
    rotation position stored by the previous run; `limit`: tasks per run in all."""
    by_key = {p.key: p for p in known}
    deal_tasks: list[tuple[Pair, date]] = []
    for origin, destination, airport, month in deal_trips:
        pair = by_key.get((origin, destination, airport or ""))
        if pair is not None and (pair, month) not in deal_tasks:
            deal_tasks.append((pair, month))
    rotation = [(p, m) for p in known for m in months]
    chosen = list(deal_tasks)
    position = cursor % len(rotation) if rotation else 0
    taken = 0
    while rotation and taken < len(rotation) and len(chosen) < max(limit, 0):
        task = rotation[(position + taken) % len(rotation)]
        taken += 1
        if task not in chosen:
            chosen.append(task)
    new_cursor = (position + taken) % len(rotation) if rotation else 0
    return HotPlan(tuple(chosen), new_cursor, len(deal_tasks), len(known), len(months))
