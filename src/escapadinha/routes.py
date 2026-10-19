"""Routes as data: the `routes` table is the source of truth, config.yaml only shapes it.

Config holds per-kind default rules, per-route overrides, exclusions, the long-haul list
and a one-off seed for an empty table. `sync` applies config to the table at the start of
every command; the rest of the code reads `Route` records with their effective rules.

Lifecycle (#5): discovery adds the routes it finds and reactivates dormant ones it finds
again (`apply_discovery`); a route without prices for `dormant_after_days` becomes dormant
(`mark_dormant`). Nothing is ever deleted.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from escapadinha.config import RoutesConfig
from escapadinha.discovery import Found, LongHaul
from escapadinha.models import Route, RouteRules
from escapadinha.storage import db

RULE_FIELDS = ("direct_only", "min_nights", "max_nights", "max_transfers")


def sync(conn: sqlite3.Connection, cfg: RoutesConfig, now: datetime) -> None:
    """Seed an empty table, add long-haul routes, mirror the config overrides and names."""
    if not db.route_rows(conn):
        for r in cfg.seed:
            if not cfg.excluded(r.origin, r.destination):
                db.insert_route(conn, origin=r.origin, destination=r.destination,
                                city_pt=r.city_pt, kind=r.kind, discovered_at=now)
    for dest in cfg.long_haul:
        for origin in dest.origins:
            if not cfg.excluded(origin, dest.destination):
                db.insert_route(conn, origin=origin, destination=dest.destination,
                                city_pt=dest.city_pt, kind="long_haul", discovered_at=now)
    for row in db.route_rows(conn):
        override = cfg.overrides.get(f"{row['origin']}-{row['destination']}")
        db.set_route_overrides(conn, row["origin"], row["destination"],
                               override.model_dump(exclude_none=True) if override else {})
    for destination, name in cfg.city_names.items():
        db.set_city_name(conn, destination, name)


def _route(row: sqlite3.Row, cfg: RoutesConfig) -> Route:
    defaults = cfg.kinds[row["kind"]].model_dump()
    rules = {f: defaults[f] if row[f] is None else row[f] for f in RULE_FIELDS}
    rules["direct_only"] = bool(rules["direct_only"])
    return Route(
        origin=row["origin"], destination=row["destination"], city_pt=row["city_pt"],
        kind=row["kind"], rules=RouteRules(**rules), status=row["status"],
        price_cap_eur=None if row["price_cap_eur"] is None else float(row["price_cap_eur"]),
        destination_airports=row["destination_airports"],
        discovered_at=datetime.fromisoformat(row["discovered_at"]),
        last_observed_at=(datetime.fromisoformat(row["last_observed_at"])
                          if row["last_observed_at"] else None),
        city_en=row["city_en"],
        demand_pax_month=(None if row["demand_pax_month"] is None
                          else float(row["demand_pax_month"])),
        demand_period=row["demand_period"],
    )


def all_routes(conn: sqlite3.Connection, cfg: RoutesConfig) -> list[Route]:
    """Every stored route with its effective rules (dormant and excluded included)."""
    return [_route(row, cfg) for row in db.route_rows(conn)]


def active_routes(conn: sqlite3.Connection, cfg: RoutesConfig) -> list[Route]:
    """Routes the collector and detector work on: active and not excluded."""
    return [r for r in all_routes(conn, cfg)
            if r.status == "active" and not cfg.excluded(r.origin, r.destination)]


def get_route(conn: sqlite3.Connection, cfg: RoutesConfig, key: str) -> Route:
    for r in all_routes(conn, cfg):
        if r.key == key.upper():
            return r
    raise KeyError(f"Route {key} is not in the routes table (see `escapadinha routes list`)")


def per_origin(routes: list[Route], cfg: RoutesConfig) -> dict[str, Counter]:
    """origin -> Counter of 'active' / 'dormant' / 'excluded' (an excluded route counts only there)."""
    out: dict[str, Counter] = {}
    for r in routes:
        state = "excluded" if cfg.excluded(r.origin, r.destination) else r.status
        out.setdefault(r.origin, Counter())[state] += 1
    return out


# --- discovery and dormancy ---------------------------------------------------------

def curated_long_haul(cfg: RoutesConfig) -> list[LongHaul]:
    return [LongHaul(d.destination.upper(), d.city_pt, tuple(o.upper() for o in d.origins))
            for d in cfg.long_haul]


@dataclass
class Applied:
    """What a discovery changed in the table."""

    found: list[Found] = field(default_factory=list)          # routes the sources returned
    added: list[Found] = field(default_factory=list)          # new rows (status active)
    reactivated: list[Found] = field(default_factory=list)    # dormant -> active
    excluded: list[Found] = field(default_factory=list)       # found but excluded in config


def apply_discovery(conn: sqlite3.Connection, cfg: RoutesConfig, found: list[Found],
                    now: datetime, *, dry_run: bool = False) -> Applied:
    """Add new routes, reactivate dormant ones found again, refresh airports and English
    names. Existing names, kinds and rules are kept; nothing is removed."""
    stored = {(r["origin"], r["destination"]): r for r in db.route_rows(conn)}
    result = Applied(found=list(found))
    for f in found:
        f = replace(f, city_pt=cfg.city_names.get(f.destination, f.city_pt))
        if cfg.excluded(f.origin, f.destination):
            result.excluded.append(f)
            continue
        airports = ",".join(sorted(f.airports)) or None
        row = stored.get((f.origin, f.destination))
        if row is None:
            result.added.append(f)
            if not dry_run:
                db.insert_route(conn, origin=f.origin, destination=f.destination,
                                city_pt=f.city_pt, city_en=f.city_en, kind=f.kind, discovered_at=now,
                                destination_airports=airports)
            continue
        if row["status"] == "dormant":
            result.reactivated.append(f)
        if not dry_run:
            db.set_route_catalogue(conn, f.origin, f.destination, city_en=f.city_en,
                                   destination_airports=airports)
    if not dry_run:
        db.set_route_status(conn, [(f.origin, f.destination) for f in result.reactivated], "active")
    return result


def due_dormant(routes: list[Route], now: datetime, days: int) -> list[Route]:
    """Active routes with no price seen for `days`, counted from the newest sighting or, for
    a route never observed, from `discovered_at` (a new route gets its full period).

    A reactivated route keeps its old `last_observed_at`: the next collection is its probe,
    and without prices it goes back to sleep until a discovery finds it again.
    """
    cutoff = now - timedelta(days=days)
    return [r for r in routes if r.status == "active"
            and max(t for t in (r.last_observed_at, r.discovered_at) if t is not None) < cutoff]


def mark_dormant(conn: sqlite3.Connection, cfg: RoutesConfig, now: datetime, *,
                 spare: Collection[str] = ()) -> list[Route]:
    """Put routes without prices for `dormant_after_days` to sleep (excluded ones are left alone).

    `spare`: keys of routes the collection didn't ask for (never-seen routes between daily
    passes, D42): a route is only put to sleep after a collection that probed it."""
    stale = [r for r in due_dormant(active_routes(conn, cfg), now, cfg.dormant_after_days)
             if r.key not in spare]
    db.set_route_status(conn, [(r.origin, r.destination) for r in stale], "dormant")
    return stale
