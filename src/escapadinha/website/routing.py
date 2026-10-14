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

A rule whose target is not a built page is left out (reported), so a redirect never ends in a
404. Removed pages (a route dropped from config) stay an honest 404, as before.
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

STATIC = ("/", "/sobre/", "/privacidade/")
CONTENT = {"itineraries": "/roteiros/", "tips": "/dicas/"}   # collection -> listing (D33)
GUIDE_KEY = "guide:"                                         # the Jinja guides' history keys
GUIDES = "/guias/"
TIPS_INDEX = "/dicas/"


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


def plan(ctx: Context, conn: sqlite3.Connection, data: Path, dist: Path, *, content: Path
         ) -> tuple[redirects.RedirectPlan, dict[str, str]]:
    """The redirect plan and the current pages (stable keys) to add to the history."""
    current = current_pages(data)
    built = built_pages(dist)
    history = pipeline.site_paths(ctx, conn)
    # Targets: the current pages, every built path (so no rule ever hides one), and where the
    # pages of the old site that the contract doesn't name now go.
    targets = dict(current) | {f"built:{p}": p for p in built}
    for key in history:
        if key in current:
            continue
        if key.startswith("deal:"):
            found = db.get_deal(conn, int(key.removeprefix("deal:")))
            route = found and current.get(f"route:{found[1].route_key}")
            if route:
                targets[key] = route
        elif key.startswith(GUIDE_KEY):
            targets[key] = TIPS_INDEX
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
    deal_targets = {key.removeprefix("deal:"): path for key, path in targets.items()
                    if key.startswith("deal:")}
    aliases = {f"/promos/{deal_id}": path
               for deal_id, path in sorted(deal_targets.items(), key=lambda kv: -int(kv[0]))}
    result = redirects.plan_redirects(targets, old_paths, extra=ctx.config.site.redirects,
                                      aliases=aliases)
    kept = []
    for source, target in result.rules:
        if target.startswith("/") and target not in built:
            result.skipped.append(f"{source} -> {target}: {target} is not a page of the build")
        else:
            kept.append((source, target))
    result.rules = kept
    return result, current


def write(ctx: Context, conn: sqlite3.Connection, data: Path, dist: Path, *, content: Path
          ) -> redirects.RedirectPlan:
    """Write `_redirects` and `_headers` into the build and remember the current paths."""
    result, current = plan(ctx, conn, data, dist, content=content)
    (dist / "_redirects").write_text(result.text(), encoding="utf-8", newline="\n")
    (dist / "_headers").write_text(redirects.headers_text(ctx.config.site), encoding="utf-8",
                                   newline="\n")
    pipeline.save_site_paths(conn, redirects.update_history(pipeline.site_paths(ctx, conn), current))
    return result
