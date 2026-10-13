"""Routes as data: the `routes` table is the source of truth, config.yaml only shapes it.

Config holds per-kind default rules, per-route overrides, exclusions, the long-haul list
and a one-off seed for an empty table. `sync` applies config to the table at the start of
every command; the rest of the code reads `Route` records with their effective rules.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from escapadinha.config import RoutesConfig
from escapadinha.models import Route, RouteRules
from escapadinha.storage import db

RULE_FIELDS = ("direct_only", "min_nights", "max_nights", "max_transfers")


def sync(conn: sqlite3.Connection, cfg: RoutesConfig, now: datetime) -> None:
    """Seed an empty table, add long-haul routes, mirror the config overrides."""
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
