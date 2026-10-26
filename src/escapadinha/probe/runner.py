"""One run of the probe on the PC (D48, D49): read `probe/wanted.json`, search each trip on every
engine in turn (Google Flights, then Kayak: one browser, one search at a time) at a human pace,
write one results file, keep `probe/state.json`. A wall ends the run **for that engine**, which
pauses for `paused_hours` (`state["engines"][name]`); the other engines go on. The pipeline's
import step reads the results on its next run."""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from escapadinha.probe import results, wanted
from escapadinha.probe.engine import Engine, Session, Wall
from escapadinha.storage.objects import ObjectStore


@dataclass(frozen=True)
class EngineSummary:
    name: str
    searched: int
    with_options: int
    wall: str | None = None                 # the wall that stopped this engine, if one did
    paused_until: datetime | None = None    # already paused before the run, or paused by it


@dataclass(frozen=True)
class ProbeSummary:
    status: str                     # ok | partial | paused | empty | wall | disabled
    trips: int
    searched: int                   # trips at least one engine searched
    with_options: int               # trips at least one engine priced
    results_key: str | None
    paused_until: datetime | None = None
    reason: str | None = None
    engines: tuple[EngineSummary, ...] = field(default_factory=tuple)

    def describe(self) -> str:
        if self.status == "disabled":
            return "probe: off (probe.enabled)"
        if self.status == "paused":
            return f"probe: paused until {self.paused_until:%Y-%m-%d %H:%M} UTC ({self.reason})"
        if self.status == "empty":
            return "probe: nothing to search (probe/wanted.json is empty or missing)"
        text = (f"probe: {self.status}, {self.searched} of {self.trips} trips searched, "
                f"{self.with_options} with booking options")
        for e in self.engines:
            text += f"; {e.name}: {e.searched} searched, {e.with_options} priced"
            if e.wall:
                text += f", {e.wall}, paused until {e.paused_until:%Y-%m-%d %H:%M} UTC"
            elif e.paused_until:
                text += f", paused until {e.paused_until:%Y-%m-%d %H:%M} UTC"
        return text


def read_state(store: ObjectStore) -> dict:
    try:
        return json.loads(store.get(results.STATE_KEY).decode("utf-8"))
    except KeyError:
        return {}


def paused_until(state: dict, now: datetime, engine: str | None = None) -> datetime | None:
    """Until when an engine is paused: its own entry under `engines`, or the pre-D49 top-level
    pause (which was the whole probe's). None when it may run."""
    candidates = [state.get("paused_until")]
    if engine:
        candidates.append((state.get("engines") or {}).get(engine, {}).get("paused_until"))
    stamps = [datetime.fromisoformat(u) for u in candidates if u]
    live = [u for u in stamps if u > now]
    return max(live) if live else None


def run(store: ObjectStore, open_session: Callable[[], Session], *, now: datetime,
        limit: int, pause: tuple[float, float], paused_hours: int, enabled: bool = True,
        engine_names: tuple[str, ...] | None = None,
        rng: random.Random | None = None,
        clock: Callable[[], datetime] | None = None) -> ProbeSummary:
    """`open_session` opens the browser (and the engines over it) only when there is something
    to search and at least one engine is not paused; its `engines` run in order on each trip.
    `engine_names` (config `probe.engines`) says which engines this run may use: when given, an
    engine the session offers but the config does not name is skipped."""
    rng = rng or random.Random()
    clock = clock or (lambda: now)
    if not enabled:
        return ProbeSummary("disabled", 0, 0, 0, None)
    state = read_state(store)
    known = engine_names or tuple((state.get("engines") or {}).keys()) or ("google_flights",)
    prior = {name: paused_until(state, now, name) for name in known}
    if all(prior.values()):
        reasons = sorted({(state.get("engines") or {}).get(n, {}).get("reason") or state.get("reason") or "wall"
                          for n in known})
        return ProbeSummary("paused", 0, 0, 0, None, max(prior.values()), ", ".join(reasons))
    try:
        doc = json.loads(store.get(wanted.KEY).decode("utf-8"))
    except KeyError:
        doc = {}
    trips = wanted.from_json(doc) if doc else []
    trips = trips[:limit]
    if not trips:
        return ProbeSummary("empty", 0, 0, 0, None)
    session = open_session()
    records: list[dict] = []
    walls: dict[str, str] = {}
    searched: dict[str, int] = {}
    priced: dict[str, int] = {}
    trips_searched: set[int] = set()
    trips_priced: set[int] = set()
    try:
        engines: list[Engine] = [e for e in session.engines
                                 if (engine_names is None or e.name in engine_names)
                                 and not paused_until(state, now, e.name)]
        if not engines:
            return ProbeSummary("paused", len(trips), 0, 0, None,
                                max((u for u in prior.values() if u), default=None),
                                "every engine is paused")
        for i, trip in enumerate(trips):
            active = [e for e in engines if e.name not in walls]
            if not active:
                break
            if i:
                active[0].pause(rng.uniform(*pause))
            for j, engine in enumerate(active):
                if j:
                    engine.pause(rng.uniform(*pause) / 2)      # a shorter breath between engines
                try:
                    found = engine.search(trip.origin, trip.airport or trip.destination,
                                          trip.departure, trip.return_date, rng=rng)
                except Wall as wall:
                    walls[engine.name] = wall.reason
                    continue
                searched[engine.name] = searched.get(engine.name, 0) + 1
                trips_searched.add(i)
                if found.options:
                    priced[engine.name] = priced.get(engine.name, 0) + 1
                    trips_priced.add(i)
                records.append(results.record(trip, found, clock(), engine=engine.name))
    finally:
        session.close()
    finished = clock()
    key = None
    engine_order = tuple(e.name for e in engines)
    if records:
        key = results.results_key(finished)
        store.put(key, results.dumps(results.document(
            records, engines=engine_order, started_at=now, finished_at=finished,
            stopped=walls or None, wanted_generated_at=doc.get("generated_at"))))
    old_engines = dict(state.get("engines") or {})
    new_engines: dict[str, dict] = {}
    for name, entry in old_engines.items():          # keep a paused engine's pause
        if paused_until({"engines": {name: entry}}, now, name):
            new_engines[name] = entry
    summaries: list[EngineSummary] = []
    for name in engine_order:
        entry = {"last_searched": searched.get(name, 0), "last_priced": priced.get(name, 0)}
        until = None
        if name in walls:
            until = now + timedelta(hours=paused_hours)
            entry |= {"paused_until": until.isoformat(), "reason": walls[name],
                      "paused_at": now.isoformat()}
        new_engines[name] = entry
        summaries.append(EngineSummary(name, searched.get(name, 0), priced.get(name, 0),
                                       walls.get(name), until))
    for name, until in prior.items():                # engines paused before this run
        if until and name not in engine_order:
            summaries.append(EngineSummary(name, 0, 0, None, until))
    new_state = {"last_run_at": finished.isoformat(), "last_trips": len(trips),
                 "last_searched": len(trips_searched), "last_results": key,
                 "engines": new_engines}
    store.put(results.STATE_KEY, json.dumps(new_state, ensure_ascii=False).encode("utf-8"))
    engines_out = tuple(sorted(summaries, key=lambda e: (engine_order + tuple(prior)).index(e.name)
                               if e.name in engine_order + tuple(prior) else 99))
    if walls:
        until = max(e.paused_until for e in summaries if e.wall)
        return ProbeSummary("wall", len(trips), len(trips_searched), len(trips_priced), key, until,
                            ", ".join(f"{n}: {r}" for n, r in walls.items()), engines_out)
    status = "ok" if len(trips_searched) == len(trips) else "partial"
    return ProbeSummary(status, len(trips), len(trips_searched), len(trips_priced), key,
                        engines=engines_out)
