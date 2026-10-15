"""Runs one collection pass over the active routes and stores the observations."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from escapadinha import archive
from escapadinha.collector.base import PriceSource
from escapadinha.collector.plan import Plan
from escapadinha.storage import db
from escapadinha.storage.objects import ObjectStore


@dataclass(frozen=True)
class RunSummary:
    run_id: int
    status: str
    n_requests: int
    n_observations: int     # offers returned by the source
    n_new: int              # of those, stored for the first time
    n_repeated: int         # already stored: last_seen_at/seen_count updated
    archive_key: str | None
    errors: list[str]
    plan: Plan              # what the run asked for: the day's pass or not (D42)


def collect(conn: sqlite3.Connection, source: PriceSource, plan: Plan, *,
            store: ObjectStore, workers: int = 1) -> RunSummary:
    """One request per (route, month) of the plan, each with the route's rules, `workers` at a
    time (the source's rate limiter caps requests per minute). Results are stored in request
    order on this thread (SQLite connections are per-thread). A failing request is recorded
    and skipped. All responses go to one archive object."""
    run_id = db.start_run(conn, source.name)
    n_observations = n_new = 0
    errors: list[str] = []
    responses: list[dict] = []
    tasks = list(plan.tasks)
    n_requests = len(tasks)

    def fetch(task):
        route, month = task
        try:
            return source.fetch(route.origin, route.destination, month,
                                rules=route.rules), None
        except Exception as exc:  # one bad route/month must not lose the rest of the run
            return None, exc

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for (route, month), (fetched, exc) in zip(tasks, pool.map(fetch, tasks)):
            if exc is not None:
                errors.append(f"{route.key} {month:%Y-%m}: {exc}")
                continue
            responses.append(fetched.response)
            stored = db.insert_observations(conn, run_id, fetched.observations)
            n_observations += len(fetched.observations)
            n_new += stored.new

    failed_requests = len(errors)
    archive_key = None
    try:
        archive_key = archive.write_run(store, conn, run_id, responses)
    except Exception as exc:  # prices are stored; say loudly that their payloads are not
        errors.append(f"archive: {exc}")
    if not errors:
        status = "ok"
    elif failed_requests < n_requests:
        status = "partial"
    else:
        status = "failed"
    db.touch_routes_observed(conn, run_id)
    db.finish_run(conn, run_id, status=status, n_requests=n_requests,
                  n_observations=n_observations, n_new=n_new, error="\n".join(errors) or None)
    return RunSummary(run_id, status, n_requests, n_observations, n_new,
                      n_observations - n_new, archive_key, errors, plan)
