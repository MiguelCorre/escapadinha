"""Which route-months a collection run asks for (D42). Pure: the clock and the routes are passed in.

Every run asks for the next `months_ahead` departure months (1-3). Once a Lisbon day, the first
run at or after `daily_pass_hour` is the day's pass: it also asks for months 4-`daily_months_ahead`,
of every route when no route has a demand figure, else only of the `deep_routes` busiest routes
by Eurostat passengers (D45, `demand.rank_routes`).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from escapadinha import demand
from escapadinha.collector.base import departure_months
from escapadinha.i18n_pt import LISBON
from escapadinha.models import Route


def daily_pass_due(last: date | None, now: datetime, hour: int) -> bool:
    """`last`: the Lisbon day of the latest daily pass. Due on the first run at or after `hour`
    (Lisbon) of a later day; on any run when there never was one."""
    if last is None:
        return True
    local = now.astimezone(LISBON)
    return local.date() > last and local.hour >= hour


def first_far_month(today: date, months_ahead: int) -> date:
    """The first departure month only the day's pass asks for: month `months_ahead` + 1 (the
    current month is month 1). The plan and the site's newest prices both start the far months
    here."""
    return departure_months(today, months_ahead + 1)[-1]


@dataclass(frozen=True)
class Plan:
    daily: bool                                 # the day's pass
    months: tuple[date, ...]                    # departure months every asked route gets
    tasks: tuple[tuple[Route, date], ...]       # (route, departure month), in request order
    waiting: tuple[Route, ...] = ()             # never-seen routes left for the day's pass
    n_far_deal_months: int = 0                  # far route-months asked for open promotions
    far_months: tuple[date, ...] = ()           # months only the `deep` routes get (D45)
    deep: frozenset[str] = frozenset()          # keys of the routes asked the far months too

    def describe(self) -> str:
        """For the run log, e.g. "daily pass: months 1–6 of 360 routes", or with the demand
        rank narrowing the far months, "daily pass: months 1–6 of 80 routes, months 1–3 of 280
        routes"."""
        asked = len({route.key for route, _ in self.tasks})
        if self.deep:
            text = (f"daily pass: months 1–{len(self.months) + len(self.far_months)} of "
                    f"{_count(len(self.deep), 'route')}, months 1–{len(self.months)} of "
                    f"{_count(asked - len(self.deep), 'route')}")
        else:
            text = (f"{'daily' if self.daily else 'regular'} pass: months 1–{len(self.months)} of "
                    f"{_count(asked, 'route')}")
        if self.n_far_deal_months:
            text += f" + {_count(self.n_far_deal_months, 'far month')} of open promotions"
        if self.waiting:
            text += f"; {_count(len(self.waiting), 'never-seen route')} wait for the daily pass"
        return text


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def never_seen(route: Route) -> bool:
    """No price ever stored for the route (it has no `last_observed_at`)."""
    return route.last_observed_at is None


def deep_routes_by_demand(routes: Iterable[Route], limit: int | None) -> frozenset[str]:
    """Keys of the routes the day's pass asks the far months (D45): the `limit` busiest by
    `demand.rank_routes`. Empty when `limit` is None or no route has a figure: then every route
    gets them (D42 as before)."""
    if limit is None:
        return frozenset()
    ranks = demand.rank_routes(routes)
    return frozenset(key for key, rank in ranks.items() if rank <= limit) if ranks else frozenset()


def plan(routes: list[Route], *, today: date, daily: bool, months_ahead: int,
         daily_months_ahead: int, deal_months: Iterable[tuple[str, date]] = (),
         deep_routes: int | None = None) -> Plan:
    """`today`: the Lisbon date of the run. The day's pass asks every route; another run leaves
    out the routes that never returned a price, until a daily pass finds their first one.

    `deal_months`: (route key, first day of the departure month) of every open promotion. A run
    that is not the day's pass still asks for those far months, so the recheck judges each
    open promotion on every run against prices asked for its month (D13, D42).

    `deep_routes` (D45): on the day's pass, only the routes ranked up to here by demand get
    months `months_ahead` + 1 to `daily_months_ahead`; the rest get `months_ahead` like a
    regular run. None, or no route with a demand figure: every route gets the far months."""
    near = tuple(departure_months(today, months_ahead))
    start = first_far_month(today, months_ahead)
    far = tuple(m for m in departure_months(today, daily_months_ahead) if m >= start)
    deep = deep_routes_by_demand(routes, deep_routes) if daily else frozenset()
    months = (near if deep else near + far) if daily else near
    wanted = set(deal_months)
    waiting = () if daily else tuple(r for r in routes if never_seen(r))
    left_out = {r.key for r in waiting}
    tasks: list[tuple[Route, date]] = []
    extra = 0
    for route in routes:
        if route.key in left_out:
            continue
        if deep and route.key in deep:
            tasks += [(route, month) for month in (*months, *far)]
            continue
        deals = [] if daily and not deep else [m for m in far if (route.key, m) in wanted]
        extra += len(deals)
        tasks += [(route, month) for month in (*months, *deals)]
    return Plan(daily, months, tuple(tasks), waiting, extra, far if deep else (), deep)
