"""Fast or full path for a run (D25).

Every run collects, rechecks and detects (the fast path). Rendering new deals, exporting the
site data, building and deploying the site (the full path) only happen when something the
public outputs show changed since the last successful full path, or when forced (`run --full`,
the workflow's dispatch triggers).

What the outputs depend on is summarised as a fingerprint, one hash per component, stored in
the `meta` table at the end of every successful full path:

- promotions: every deal's id, status and whether it has a tracked link (new deals to
  render, review decisions, expiries; a deal that isn't public yet isn't in the site data);
- site data: the website data contract exactly as the Astro site would be built from it
  (D35), computed in memory without creating partner links (`site_data.build_export`), minus
  the run's bookkeeping the site never shows (`site_data.PER_RUN`, `site_data.shown_digest`);
- routes: key, status and Portuguese name of every route (pages appear or get renamed);
- day: the Lisbon date, so typical lows, past pontes and "Atualizado a" are at most a day old;
- code: the package, config.yaml, content/ (rules, holidays, guides), the web package's sources
  (`web/src` without the exported data, `web/public`, `web/functions`, its config and
  lockfile) and the logo and fonts the build inlines.

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
from escapadinha import i18n_pt, routes, site_data
from escapadinha.config import Context
from escapadinha.storage import db
from escapadinha.website import node

FINGERPRINT = "run.full_path_fingerprint"   # meta key: components at the last full path
LABELS = {"promotions": "promotions", "site_data": "site data", "routes": "routes",
          "day": "new day", "code": "code or config"}
# The web package's sources: what `npm run build` turns into the site (D35). web/src/data is
# the export (its own component), node_modules and dist are installed or built.
WEB_SOURCES = ("src", "public", "functions")
WEB_FILES = ("astro.config.ts", "package.json", "package-lock.json")
WEB_SKIP = ("src/data",)


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


def web_source_files(web: Path) -> list[Path]:
    """The web package's sources (WEB_SOURCES, WEB_FILES), not the export, packages or build."""
    files = [web / name for name in WEB_FILES if (web / name).is_file()]
    for folder in WEB_SOURCES:
        root = web / folder
        if root.is_dir():
            files += [p for p in root.rglob("*") if p.is_file()
                      and not any(p.relative_to(web).as_posix().startswith(f"{skip}/")
                                  for skip in WEB_SKIP)]
    return files


def _code_files(ctx: Context) -> list[Path]:
    package = Path(escapadinha.__file__).parent
    files = [p for p in package.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    content = ctx.guides_dir.parent
    if content.is_dir():
        files += [p for p in content.rglob("*") if p.is_file()]
    files += web_source_files(node.web_dir(ctx))   # the Function's sources are among them
    # What the Astro build reads from outside web/: the logo (inlined) and the fonts.
    assets = ctx.assets_dir
    files += [p for p in (assets / "logo-light.svg",) if p.is_file()]
    files += sorted((assets / "fonts").glob("*.woff2")) if (assets / "fonts").is_dir() else []
    config = ctx.root / "config.yaml"
    return files + ([config] if config.is_file() else [])


def site_data_digest(ctx: Context, conn: sqlite3.Connection, now: datetime) -> str:
    """The site data as the next build would see it (stored partner links only, nothing
    written), minus the run's bookkeeping (`site_data.PER_RUN`, `shown_digest`)."""
    return site_data.shown_digest(site_data.build_export(ctx, conn, now, new_links=False))


def fingerprint(ctx: Context, conn: sqlite3.Connection, now: datetime | None = None, *,
                export: site_data.Export | None = None) -> dict[str, str]:
    """The components now, or, with `export`, as of that export (its data and its day)."""
    if export is not None:
        now = export.generated_at
    now = now or db.utcnow()
    all_routes = routes.all_routes(conn, ctx.config.routes)
    return {
        "promotions": _digest(db.deal_states(conn)),
        "site_data": (site_data.shown_digest(export) if export is not None
                      else site_data_digest(ctx, conn, now)),
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


def record_full_path(ctx: Context, conn: sqlite3.Connection, export: site_data.Export) -> None:
    """After a successful full path: what the published outputs now reflect. `export` is the
    site data that was written and built (and deployed): its digest and its day are recorded,
    not the database's state at a later moment (an offer that went stale, or a new Lisbon day,
    between the export and now must still take the next run's full path)."""
    db.set_meta(conn, FINGERPRINT, json.dumps(fingerprint(ctx, conn, export=export)))
