"""One run of the probe on the PC (D48): read `probe/wanted.json`, search each trip at a human
pace, write one results file, keep `probe/state.json`. A wall ends the run and pauses the probe
for `paused_hours`; the pipeline's import step reads the results on its next run."""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from escapadinha.probe import google_flights as gf
from escapadinha.probe import results, wanted
from escapadinha.storage.objects import ObjectStore


@dataclass(frozen=True)
class ProbeSummary:
    status: str                     # ok | partial | paused | empty | wall | disabled
    trips: int
    searched: int
    with_options: int
    results_key: str | None
    paused_until: datetime | None = None
    reason: str | None = None

    def describe(self) -> str:
        if self.status == "disabled":
            return "probe: off (probe.enabled)"
        if self.status == "paused":
            return f"probe: paused until {self.paused_until:%Y-%m-%d %H:%M} UTC ({self.reason})"
        if self.status == "empty":
            return "probe: nothing to search (probe/wanted.json is empty or missing)"
        text = (f"probe: {self.status}, {self.searched} of {self.trips} trips searched, "
                f"{self.with_options} with booking options")
        if self.status == "wall":
            text += f"; {self.reason}, paused until {self.paused_until:%Y-%m-%d %H:%M} UTC"
        return text


def read_state(store: ObjectStore) -> dict:
    try:
        return json.loads(store.get(results.STATE_KEY).decode("utf-8"))
    except KeyError:
        return {}


def paused_until(state: dict, now: datetime) -> datetime | None:
    until = state.get("paused_until")
    if until and datetime.fromisoformat(until) > now:
        return datetime.fromisoformat(until)
    return None


def run(store: ObjectStore, open_flights: Callable[[], gf.Flights], *, now: datetime,
        limit: int, pause: tuple[float, float], paused_hours: int, enabled: bool = True,
        rng: random.Random | None = None,
        clock: Callable[[], datetime] | None = None) -> ProbeSummary:
    """`open_flights` builds the browser only when there is something to search (and the
    probe is not paused); it must have a `close()`."""
    rng = rng or random.Random()
    clock = clock or (lambda: now)
    if not enabled:
        return ProbeSummary("disabled", 0, 0, 0, None)
    state = read_state(store)
    until = paused_until(state, now)
    if until is not None:
        return ProbeSummary("paused", 0, 0, 0, None, until, state.get("reason"))
    try:
        doc = json.loads(store.get(wanted.KEY).decode("utf-8"))
    except KeyError:
        doc = {}
    trips = wanted.from_json(doc) if doc else []
    trips = trips[:limit]
    if not trips:
        return ProbeSummary("empty", 0, 0, 0, None)
    flights = open_flights()
    records: list[dict] = []
    stopped: str | None = None
    searched = with_options = 0
    try:
        for i, trip in enumerate(trips):
            if i:
                flights.pause(rng.uniform(*pause))
            try:
                found = gf.search(flights, trip.origin, trip.airport or trip.destination,
                                  trip.departure, trip.return_date, rng=rng)
            except gf.Wall as wall:
                stopped = wall.reason
                break
            searched += 1
            with_options += bool(found.options)
            records.append(results.record(trip, found, clock()))
    finally:
        close = getattr(flights, "close", None)
        if close:
            close()
    finished = clock()
    key = None
    if records:
        key = results.results_key(finished)
        store.put(key, results.dumps(results.document(
            records, engine=gf.ENGINE, started_at=now, finished_at=finished, stopped=stopped,
            wanted_generated_at=doc.get("generated_at"))))
    new_state = {"last_run_at": finished.isoformat(), "last_trips": len(trips),
                 "last_searched": searched, "last_results": key}
    until = None
    if stopped:
        until = now + timedelta(hours=paused_hours)
        new_state |= {"paused_until": until.isoformat(), "reason": stopped,
                      "paused_at": now.isoformat()}
    store.put(results.STATE_KEY, json.dumps(new_state, ensure_ascii=False).encode("utf-8"))
    if stopped:
        return ProbeSummary("wall", len(trips), searched, with_options, key, until, stopped)
    return ProbeSummary("ok" if searched == len(trips) else "partial", len(trips), searched,
                        with_options, key)
