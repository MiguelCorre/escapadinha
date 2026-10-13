"""Collector contract: a price source turns (route, month) into stored Observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from escapadinha.models import Observation


@dataclass(frozen=True)
class FetchResult:
    observations: list[Observation]
    n_requests: int
    errors: list[str]


class PriceSource(Protocol):
    name: str

    def fetch_round_trips(self, origin: str, destination: str, month: date, *,
                          min_nights: int, max_nights: int) -> list[Observation]:
        """Cheapest round-trips departing in `month` within the nights range.
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
