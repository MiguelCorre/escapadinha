"""`_redirects` and `_headers` for the Astro site (D35), from the exported contract, the built
pages and the path history (`site.paths`, D19/D25), with the rules of `redirects.py`.

Every old URL keeps working (301), never shadowing a built page:

- a page whose path changed since it was published (stable keys: `deal:<id>`, `route:<key>`,
  `destination:<code>` (D30), `origin:<code>`, `page:<path>`) → its current path;
- `/promos/<id>` (short alias) → the promotion's page;
- a promotion the contract no longer lists (expired more than `site.expired_promotions_days`
  ago: the Jinja site kept those pages forever) → its route page;
- `/guias/<slug>/` (the Jinja guides) → the reviewed tip or itinerary whose front matter has
  that `legacy_path` (D33), else the tips index `/dicas/`;
- `site.redirects` from config.

A rule whose target is not a built page is left out (reported) before Cloudflare's 2000-rule
limit counts, so a redirect never ends in a 404; a rule to a path that itself redirects points
at the final page (no chains). Within 10 % of the limit the build warns; above it the build
fails (BuildError) rather than drop old links. Removed pages (a route dropped from config) stay
an honest 404, as before.

The path history the build implies (current paths added, gone promotions folded into their
route's entry) is stored as pending (`site.paths.pending`) and becomes `site.paths` only once
the build is live (`commit`, called by `deploy`): a build that never went out records nothing.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import yaml

from escapadinha import pipeline
from escapadinha.config import Context
from escapadinha.storage import db
from escapadinha.website import DESTINATION_KEY, redirects
from escapadinha.website.node import BuildError

STATIC = ("/", "/sobre/", "/privacidade/")
CONTENT = {"itineraries": "/roteiros/", "tips": "/dicas/"}   # collection -> listing (D33)
GUIDE_KEY = "guide:"                                         # the Jinja guides' history keys
GUIDES = "/guias/"
TIPS_INDEX = "/dicas/"
# meta: the path history of the last build, stored as `site.paths` only once it is live (D35)
PENDING_PATHS = "site.paths.pending"
WARN_MARGIN = 0.10      # warn when the redirects are within 10 % of Cloudflare's limit


def _read(data: Path, name: str) -> dict:
    return json.loads((data / name).read_text("utf-8"))


def current_pages(data: Path) -> dict[str, str]:
    """Stable key -> current path of every page the contract names."""
    pages = {f"page:{p}": p for p in STATIC}
    pages |= {f"deal:{p['id']}": p["path"] for p in _read(data, "promotions.json")["promotions"]}
    pages |= {f"route:{r['key']}": r["path"] for r in _read(data, "routes.json")["routes"]}
    pages |= {f"origin:{o['iata']}": o["path"] for o in _read(data, "origins.json")["origins"]}
    pages |= {f"{DESTINATION_KEY}{d['code']}": d["path"]
              for d in _read(data, "destinations.json")["destinations"]}
    return pages


def built_pages(dist: Path) -> set[str]:
    """Request paths that serve a file of the build: '/voos/x/' for voos/x/index.html,
    '/favicon.svg' for a file."""
    paths = set()
    for file in dist.rglob("*"):
        if not file.is_file() or file.name in ("_redirects", "_headers"):
            continue
        rel = file.relative_to(dist).as_posix()
        paths.add("/" + rel.removesuffix("index.html") if rel.endswith("index.html") else "/" + rel)
    return paths


def _front_matter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    return (yaml.safe_load(text[3:end]) or {}) if end > 0 else {}


def legacy_paths(content: Path) -> dict[str, str]:
    """Old site path -> the page of the itinerary or tip that names it (`legacy_path`), drafts
    included (whether that page is built is decided against the build). `content`: the web
    package's `src/content`."""
    out = {}
    for collection, listing in CONTENT.items():
        for mdx in sorted((content / collection).glob("*.md*")):
            legacy = _front_matter(mdx.read_text("utf-8")).get("legacy_path")
            if legacy:
                out[legacy] = f"{listing}{mdx.stem}/"
    return out


def fold_gone_promotions(conn: sqlite3.Connection, history: dict[str, list[str]],
                         current: dict[str, str]) -> dict[str, list[str]]:
    """The history with every promotion the contract no longer lists folded into its route:
    the promotion's old paths and its `/promos/<id>` alias become old paths of the route page,
    where they redirect anyway, and the `deal:<id>` key goes. The history stops growing a key
    per expired promotion, no build looks those deals up again, and a later route rename takes
    them along (one 301 to the final page, never a chain). A promotion whose route has no page
    keeps its entry (no rule: an honest 404, as for the route)."""
    out = {key: list(paths) for key, paths in history.items()}
    for key, paths in history.items():
        if not key.startswith("deal:") or key in current:
            continue
        deal_id = int(key.removeprefix("deal:"))
        found = db.get_deal(conn, deal_id)
        route_key = found and f"route:{found[1].route_key}"
        if not route_key or route_key not in current:
            continue
        folded = out.setdefault(route_key, [])
        folded += [p for p in [*paths, f"/promos/{deal_id}"] if p not in folded]
        del out[key]
    return out


def plan(ctx: Context, conn: sqlite3.Connection, data: Path, dist: Path, *, content: Path
         ) -> tuple[redirects.RedirectPlan, dict[str, list[str]]]:
    """The redirect plan, and the path history to store once the build is live (`commit`):
    the current pages added, gone promotions folded into their routes."""
    current = current_pages(data)
    built = built_pages(dist)
    history = fold_gone_promotions(conn, pipeline.site_paths(ctx, conn), current)
    # Targets: the current pages, every built path (so no rule ever hides one), and where the
    # pages of the old site that the contract doesn't name now go.
    targets = dict(current) | {f"built:{p}": p for p in built}
    # A Jinja guide's entry goes to the tips index (below: or where its content went). A
    # `deal:` entry still in the history has no route page either: no rule (an honest 404).
    targets |= {key: TIPS_INDEX for key in history
                if key.startswith(GUIDE_KEY) and key not in current}
    legacy = legacy_paths(content)
    old_paths = dict(history)
    for old, page in legacy.items():
        key = f"legacy:{old}"
        old_paths[key] = [old]
        targets[key] = page if page in built else TIPS_INDEX
    # A Jinja guide's history entry goes where its content went, when that content names it.
    for key, paths in history.items():
        if key.startswith(GUIDE_KEY):
            for old in paths:
                if old in legacy:
                    targets[key] = targets[f"legacy:{old}"]
    deal_ids = sorted((int(key.removeprefix("deal:")) for key in current
                       if key.startswith("deal:")), reverse=True)
    aliases = {f"/promos/{deal_id}": current[f"deal:{deal_id}"] for deal_id in deal_ids}
    # Only rules to a page of this build, counted after that filter; one per source, chains
    # collapsed. Over Cloudflare's limit the build fails rather than drop old links silently.
    result = redirects.plan_redirects(targets, old_paths, extra=ctx.config.site.redirects,
                                      aliases=aliases, serves=built.__contains__, limit=None)
    count, limit = len(result.rules), redirects.MAX_STATIC_REDIRECTS
    if count > limit:
        raise BuildError(f"{count} redirects, over Cloudflare Pages' limit of {limit} per "
                         "_redirects file: old links would stop working. Move the oldest to a "
                         "Bulk Redirect (docs/runbooks/brand-switch.md) or prune site.paths (D35).")
    if count >= limit * (1 - WARN_MARGIN):
        result.warnings.append(f"{count} redirects, within {WARN_MARGIN:.0%} of Cloudflare "
                               f"Pages' limit of {limit}: the build fails above it (D35)")
    return result, redirects.update_history(history, current)


def write(ctx: Context, conn: sqlite3.Connection, data: Path, dist: Path, *, content: Path
          ) -> redirects.RedirectPlan:
    """Write `_redirects` and `_headers` into the build, and the path history this build
    implies as pending: `commit` stores it once the build is live (`deploy`), so a build that
    never went live records no path."""
    result, history = plan(ctx, conn, data, dist, content=content)
    (dist / "_redirects").write_text(result.text(), encoding="utf-8", newline="\n")
    (dist / "_headers").write_text(redirects.headers_text(ctx.config.site), encoding="utf-8",
                                   newline="\n")
    db.set_meta(conn, PENDING_PATHS, json.dumps(history, sort_keys=True))
    return result


def commit(conn: sqlite3.Connection) -> bool:
    """After a deploy (or one skipped because the live site already is this build): the
    pending path history becomes `site.paths`. False when there was none."""
    pending = db.get_meta(conn, PENDING_PATHS)
    if not pending:
        return False
    pipeline.save_site_paths(conn, json.loads(pending))
    db.delete_meta(conn, PENDING_PATHS)
    return True
