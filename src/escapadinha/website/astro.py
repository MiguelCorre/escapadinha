"""Build the public website, the Astro package in `web/` (D28), from the pipeline (D35).

`build` is the full path's site step, after `export site-data` wrote the contract into
`site.data_dir` (`web/src/data`):

1. `npm ci` when `web/node_modules` is missing or `package-lock.json` changed since the last
   install (a stamp in node_modules holds the lockfile's hash), so the PC installs once and a
   CI runner once per job (from the npm cache);
2. `npm run build` with `SITE_DATA_DIR` = the export (absolute), so a stray variable pointing at
   the fixtures can't be what gets built; the build validates the data and writes `web/dist`;
3. the promotion images the contract names (`promotions[].images`), converted from the rendered
   slides (`pipeline.deal_folder`: downloaded on a runner, each once, D25) into `web/dist/img/`;
4. `_redirects` and `_headers` (`website.routing`), so every old URL keeps working.

`deploy.deploy` then uploads `web/dist` with the review Function.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from escapadinha import pipeline, site_data
from escapadinha.config import Context
from escapadinha.storage import db
from escapadinha.website import deploy as site_deploy
from escapadinha.website import redirects
from escapadinha.website.images import write_promo_images

STAMP = ".escapadinha-npm-ci"     # in web/node_modules: sha256 of the lockfile it was installed from
DIST = "dist"
NPM_TIMEOUT = 900                 # seconds, per npm command (well inside the job's 45 minutes)


class BuildError(RuntimeError):
    pass


@dataclass
class BuildSummary:
    seconds: float
    installed: bool                             # npm ci ran
    pages: Counter = field(default_factory=Counter)   # first path segment ('voos', '/' ...) -> pages
    images: int = 0
    missing_images: list[str] = field(default_factory=list)   # contract paths not produced
    redirects: int = 0
    skipped_redirects: list[str] = field(default_factory=list)
    size_bytes: int = 0


def web_dir(ctx: Context) -> Path:
    return site_deploy.web_dir(ctx)


def dist_dir(ctx: Context) -> Path:
    return web_dir(ctx) / DIST


def npm() -> str:
    found = site_deploy.node_tool("npm")
    if found is None:
        raise BuildError("npm not found: install Node.js 22+ (https://nodejs.org) to build the site")
    return found


def _run_npm(web: Path, *args: str, env: dict[str, str]) -> None:
    """One npm command in `web/`; BuildError with the end of its output when it fails."""
    tool = npm()
    full_env = os.environ | env
    full_env["PATH"] = str(Path(tool).parent) + os.pathsep + full_env.get("PATH", "")
    result = subprocess.run([tool, *args], cwd=web, env=full_env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=NPM_TIMEOUT)
    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip()
        raise BuildError(f"npm {' '.join(args)} failed:\n{output[-3000:]}")


def _lock_hash(web: Path) -> str:
    return hashlib.sha256((web / "package-lock.json").read_bytes()).hexdigest()


def ensure_dependencies(web: Path) -> bool:
    """`npm ci` unless node_modules was installed from this very lockfile. True when it ran."""
    stamp = web / "node_modules" / STAMP
    wanted = _lock_hash(web)
    if stamp.is_file() and stamp.read_text("utf-8").strip() == wanted:
        return False
    _run_npm(web, "ci", env={})
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(wanted + "\n", "utf-8")
    return True


def _promotion_images(ctx: Context, conn: sqlite3.Connection, data: Path, dist: Path
                      ) -> tuple[int, list[str]]:
    """Write every image the contract's promotions name; (files written, paths still missing)."""
    promotions = json.loads((data / "promotions.json").read_text("utf-8"))["promotions"]
    written, missing = 0, []
    for promo in promotions:
        images = promo.get("images")
        if not images:
            continue
        wanted = [*images["slides"], images.get("thumb"), images.get("og")]
        wanted = [p for p in wanted if p]
        found = db.get_deal(conn, promo["id"])
        folder = pipeline.deal_folder(ctx, found[0], pipeline.SLIDES) if found else None
        if folder is not None:
            out = dist / Path(wanted[0].lstrip("/")).parent
            written += len(write_promo_images(folder, out))
        missing += [p for p in wanted if not (dist / p.lstrip("/")).is_file()]
    return written, missing


def page_counts(dist: Path) -> Counter:
    """Built HTML pages by first path segment ('/' for the home page, '404' for 404.html)."""
    counts = Counter()
    for page in dist.rglob("*.html"):
        rel = page.relative_to(dist).as_posix()
        if rel == "index.html":
            counts["/"] += 1
        elif rel == "404.html":
            counts["404"] += 1
        else:
            counts[rel.split("/", 1)[0]] += 1
    return counts


def astro_build(web: Path, data: Path, dist: Path | None = None) -> None:
    """`npm run build` on the contract in `data` (absolute, so a stray SITE_DATA_DIR pointing at
    the fixtures can't be what gets built), into `web/dist` or `dist`."""
    out = dist or web / DIST
    if out.exists():
        shutil.rmtree(out)           # a failed build must never leave the previous one behind
    extra = ("--", "--outDir", str(out.resolve())) if dist else ()
    _run_npm(web, "run", "build", *extra,
             env={"SITE_DATA_DIR": str(data.resolve()), "ASTRO_TELEMETRY_DISABLED": "1"})
    if not (out / "index.html").is_file():
        raise BuildError(f"npm run build wrote no {out / 'index.html'}")


def finish(ctx: Context, conn: sqlite3.Connection, data: Path, dist: Path, *, content: Path
           ) -> tuple[int, list[str], redirects.RedirectPlan]:
    """What the pipeline adds to a build: promotion images, `_redirects`, `_headers`.
    `content`: the web package's content collections (itineraries/tips, for `legacy_path`)."""
    from escapadinha.website import routing

    images, missing = _promotion_images(ctx, conn, data, dist)
    plan = routing.write(ctx, conn, data, dist, content=content)
    return images, missing, plan


def build(ctx: Context, conn: sqlite3.Connection) -> BuildSummary:
    """npm ci (when needed) → astro build on the export → promotion images → routing files."""
    started = time.monotonic()
    web, data = web_dir(ctx), site_data.default_dir(ctx).resolve()
    if not (data / "meta.json").is_file():
        raise BuildError(f"no site data in {data}: run `escapadinha export site-data` first")
    if not (web / "package-lock.json").is_file():
        raise BuildError(f"{web} is not the web package (no package-lock.json)")
    installed = ensure_dependencies(web)
    dist = web / DIST
    astro_build(web, data)
    images, missing, plan = finish(ctx, conn, data, dist, content=web / "src" / "content")
    size = sum(p.stat().st_size for p in dist.rglob("*") if p.is_file())
    return BuildSummary(round(time.monotonic() - started, 1), installed, page_counts(dist),
                        images, missing, len(plan.rules), plan.skipped, size)
