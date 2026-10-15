"""Collector contract: a price source turns (route, month) into stored Observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from escapadinha.models import Observation, RouteRules


@dataclass(frozen=True)
class Fetched:
    observations: list[Observation]
    response: dict      # request + verbatim API payload, for the run archive


class PriceSource(Protocol):
    name: str

    def fetch(self, origin: str, destination: str, month: date, *, rules: RouteRules) -> Fetched:
        """Cheapest round-trips departing in `month` that the route's rules can use (its nights
        range; nonstop ones only when it takes nothing else, D39), plus the raw response.
        Raises on transport/API errors."""
        ...


def departure_months(today: date, months_ahead: int) -> list[date]:
    """First day of the current month and the following months, `months_ahead` in total."""
    months = []
    y, m = today.year, today.month
    for _ in range(months_ahead):
        months.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months
