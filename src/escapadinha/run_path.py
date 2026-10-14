"""Fast or full path for a run (D25).

Every run collects, rechecks and detects (the fast path). Rendering new deals, building and
deploying the site (the full path) only happen when something the public outputs show
changed since the last successful full path, or when forced (`run --full`, the workflow's
dispatch triggers).

What the outputs depend on is summarised as a fingerprint, one hash per component, stored in
the `meta` table at the end of every successful full path:

- promotions: every deal's id, status and whether it has a tracked link (new deals to
  render, review decisions, expiries);
- low prices: the observation ids the route pages list (D24);
- routes: key, status and Portuguese name of every route (pages appear or get renamed);
- day: the Lisbon date, so typical lows and "Atualizado a" are at most a day old;
- code: the package, config.yaml, content/ (templates, rules or guides changed) and the review
  Function's sources (web/functions and the modules it imports, D29).

A failed full path records nothing, so the next run takes the full path again.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import escapadinha
from escapadinha import i18n_pt, pipeline, routes
from escapadinha.config import Context
from escapadinha.storage import db
from escapadinha.website import LIVE
from escapadinha.website import deploy as site_deploy

FINGERPRINT = "run.full_path_fingerprint"   # meta key: components at the last full path
LABELS = {"promotions": "promotions", "low_prices": "low prices", "routes": "routes",
          "day": "new day", "code": "code or config"}


@dataclass(frozen=True)
class PathDecision:
    full: bool
    reason: str

    @property
    def name(self) -> str:
        return "full" if self.full else "fast"


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _files_digest(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for path in sorted(paths):
        h.update(path.name.encode())
        # Line endings normalised: a Windows checkout and the runner's must agree.
        h.update(hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).digest())
    return h.hexdigest()[:16]


def _code_files(ctx: Context) -> list[Path]:
    package = Path(escapadinha.__file__).parent
    files = [p for p in package.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    content = ctx.guides_dir.parent
    if content.is_dir():
        files += [p for p in content.rglob("*") if p.is_file()]
    # The review Function ships with the site deploy (D29): a change to it must redeploy.
    files += site_deploy.function_files(site_deploy.web_dir(ctx))
    config = ctx.root / "config.yaml"
    return files + ([config] if config.is_file() else [])


def _shown_low_prices(ctx: Context, conn: sqlite3.Connection, now: datetime) -> list[int]:
    run_id = db.latest_completed_run_id(conn)
    run_offers = db.observations_seen_since(conn, run_id) if run_id else []
    with_offers = {o.route_key for o in run_offers}
    promoted = {o.id for _, o in db.deals_with_status(conn, *LIVE)}
    shown = []
    for route in routes.all_routes(conn, ctx.config.routes):
        if route.key not in with_offers:
            continue                                   # no offers this run: no low prices
        history = pipeline.route_history(ctx, conn, route, now)
        shown += [lp.observation.id for lp in pipeline.shown_low_prices(
            ctx, conn, route, history, now, run_offers, promoted)]
    return sorted(shown)


def fingerprint(ctx: Context, conn: sqlite3.Connection, now: datetime | None = None) -> dict[str, str]:
    now = now or db.utcnow()
    all_routes = routes.all_routes(conn, ctx.config.routes)
    return {
        "promotions": _digest(db.deal_states(conn)),
        "low_prices": _digest(_shown_low_prices(ctx, conn, now)),
        "routes": _digest(sorted((r.key, r.status, r.city_pt) for r in all_routes)),
        "day": now.astimezone(i18n_pt.LISBON).date().isoformat(),
        "code": _files_digest(_code_files(ctx)),
    }


def decide(ctx: Context, conn: sqlite3.Connection, *, force: bool = False,
           now: datetime | None = None) -> PathDecision:
    """Full path when forced, on the first run, or when a component changed."""
    if force:
        return PathDecision(True, "forced with --full")
    stored = db.get_meta(conn, FINGERPRINT)
    if stored is None:
        return PathDecision(True, "first full path")
    before, current = json.loads(stored), fingerprint(ctx, conn, now)
    changed = [LABELS[k] for k in current if before.get(k) != current[k]]
    if changed:
        return PathDecision(True, "changed: " + ", ".join(changed))
    return PathDecision(False, "nothing the site shows changed")


def record_full_path(ctx: Context, conn: sqlite3.Connection, now: datetime | None = None) -> None:
    """After a successful full path: what the published outputs now reflect."""
    db.set_meta(conn, FINGERPRINT, json.dumps(fingerprint(ctx, conn, now)))
