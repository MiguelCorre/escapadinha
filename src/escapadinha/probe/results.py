"""What a probe run writes (`probe/results/<stamp>.json`) and how the pipeline turns it into
observations (D48). Pure. A record is one trip's search; an observation per booking option
(seller + price), source `google_flights`, no link (a comparison source: never a deal, never a
button; D47's link rule), `gate` = the seller, `found_at` = when the probe read the page."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from escapadinha.models import Observation
from escapadinha.probe import google_flights as gf
from escapadinha.probe.wanted import Trip

VERSION = 1
RESULTS_PREFIX = "probe/results/"
STATE_KEY = "probe/state.json"


def results_key(at: datetime) -> str:
    return f"{RESULTS_PREFIX}{at:%Y%m%dT%H%M%SZ}.json"


def record(trip: Trip, found: gf.Search, searched_at: datetime) -> dict:
    """One trip's search as the file keeps it: the page's own texts and numbers, nothing added."""
    def row(r: gf.Result | None) -> dict | None:
        return None if r is None else {"price": r.price, "airline": r.airline, "nonstop": r.nonstop,
                                       "departs": r.departs, "arrives": r.arrives, "text": r.text}
    return {"trip": trip.to_json(), "searched_at": searched_at.isoformat(), "url": found.url,
            "outcome": found.outcome, "outbound": row(found.outbound), "inbound": row(found.inbound),
            "options": [{"seller": o.seller, "kind": o.kind, "price": o.price} for o in found.options]}


def document(records: list[dict], *, engine: str, started_at: datetime, finished_at: datetime,
             stopped: str | None, wanted_generated_at: str | None) -> dict:
    return {"version": VERSION, "engine": engine, "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(), "stopped": stopped,
            "wanted_generated_at": wanted_generated_at, "records": records}


def dumps(doc: dict) -> bytes:
    return json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")


@dataclass(frozen=True)
class Imported:
    observations: list[Observation]
    records: int
    searches_ok: int


def to_observations(doc: dict) -> Imported:
    """Observations from a results document: one per booking option of a search that reached
    them, the trip's dates and route from the record. A record without options (no results,
    no nonstop, a wall before the booking page) yields nothing: nothing is guessed."""
    if doc.get("version") != VERSION:
        raise ValueError(f"probe results version {doc.get('version')!r}, expected {VERSION}")
    out: list[Observation] = []
    ok = 0
    for rec in doc.get("records", []):
        trip = Trip.from_json(rec["trip"])
        options = rec.get("options") or []
        if not options:
            continue
        ok += 1
        searched_at = datetime.fromisoformat(rec["searched_at"])
        inbound, outbound = rec.get("inbound") or {}, rec.get("outbound") or {}
        airline = gf.airline_code(outbound.get("airline"))
        for opt in options:
            price = opt.get("price")
            if not isinstance(price, (int, float)) or price <= 0 or not opt.get("seller"):
                continue
            out.append(Observation(
                source=gf.SOURCE, origin=trip.origin, destination=trip.destination,
                origin_airport=trip.origin, destination_airport=trip.airport,
                departure_date=trip.departure, return_date=trip.return_date, price=float(price),
                currency="EUR", airline=airline, flight_number=None, transfers=0,
                return_transfers=0, deep_link=None, fetched_at=searched_at,
                raw_json=json.dumps({**opt, "outbound": outbound.get("text"),
                                     "inbound": inbound.get("text")}, ensure_ascii=False,
                                    sort_keys=True),
                found_date=searched_at.date(), departure_at=None, return_at=None,
                gate=str(opt["seller"]), found_at=searched_at))
    return Imported(out, len(doc.get("records", [])), ok)
