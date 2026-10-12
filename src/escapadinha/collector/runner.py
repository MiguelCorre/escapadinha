"""Runs one collection pass over all configured routes and stores the observations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from escapadinha.collector.base import PriceSource, departure_months
from escapadinha.config import Route
from escapadinha.storage import db


@dataclass(frozen=True)
class RunSummary:
    run_id: int
    status: str
    n_requests: int
    n_observations: int
    errors: list[str]


def collect(conn: sqlite3.Connection, source: PriceSource, routes: list[Route], *,
            today: date, months_ahead: int) -> RunSummary:
    """One request per (route, month). A failing request is recorded and skipped."""
    run_id = db.start_run(conn, source.name)
    n_requests = n_observations = 0
    errors: list[str] = []
    for route in routes:
        for month in departure_months(today, months_ahead):
            n_requests += 1
            try:
                observations = source.fetch_round_trips(route.origin, route.destination, month)
            except Exception as exc:  # one bad route/month must not lose the rest of the run
                errors.append(f"{route.key} {month:%Y-%m}: {exc}")
                continue
            n_observations += db.insert_observations(conn, run_id, observations)

    if not errors:
        status = "ok"
    elif len(errors) < n_requests:
        status = "partial"
    else:
        status = "failed"
    db.finish_run(conn, run_id, status=status, n_requests=n_requests,
                  n_observations=n_observations, error="\n".join(errors) or None)
    return RunSummary(run_id, status, n_requests, n_observations, errors)
