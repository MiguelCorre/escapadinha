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
import shutil
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from escapadinha import pipeline, site_data
from escapadinha.config import Context
from escapadinha.storage import db
from escapadinha.website import deploy as site_deploy
from escapadinha.website import node, redirects
from escapadinha.website.images import write_promo_images
from escapadinha.website.node import BuildError

STAMP = ".escapadinha-npm-ci"     # in web/node_modules: what it was installed from (`install_key`)

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
    warnings: list[str] = field(default_factory=list)          # e.g. redirects near the limit


def npm() -> str:
    found = node.tool("npm")
    if found is None:
        raise BuildError("npm not found: install Node.js 22+ (https://nodejs.org) to build the site")
    return found


def _run_npm(web: Path, *args: str, env: dict[str, str], until: float) -> None:
    """One npm command in `web/` within the deadline `until`; BuildError with the end of its
    output when it fails or runs out of time."""
    what = f"npm {' '.join(args)}"
    result = node.run([npm(), *args], cwd=web, env=env, until=until, error=BuildError, what=what)
    if result.returncode != 0:
        raise BuildError(f"{what} failed:\n{node.failed(result)}")


def runtime(web: Path, until: float) -> str:
    """'v22.11.0 linux x64': the Node that `npm ci` installs for (native packages such as
    esbuild's binary are installed per platform and architecture)."""
    tool = node.tool("node")
    if tool is None:
        raise BuildError("node not found: install Node.js 22+ (https://nodejs.org) to build the site")
    script = "console.log([process.version, process.platform, process.arch].join(' '))"
    result = node.run([tool, "-e", script], cwd=web, env={}, until=until, error=BuildError,
                      what="node --version")
    if result.returncode != 0:
        raise BuildError(f"node --version failed:\n{node.failed(result)}")
    return result.stdout.strip()


def install_key(web: Path, until: float) -> str:
    """What node_modules must have been installed from: the lockfile's sha256 plus the Node
    version, platform and architecture (a PC that upgraded Node, or a node_modules copied from
    another machine, installs again)."""
    lock = hashlib.sha256((web / "package-lock.json").read_bytes()).hexdigest()
    return f"{lock} node {runtime(web, until)}"


def ensure_dependencies(web: Path, until: float | None = None) -> bool:
    """`npm ci` unless node_modules was installed from this very lockfile by this Node. True
    when it ran."""
    until = node.deadline() if until is None else until
    stamp = web / "node_modules" / STAMP
    wanted = install_key(web, until)
    if stamp.is_file() and stamp.read_text("utf-8").strip() == wanted:
        return False
    _run_npm(web, "ci", env={}, until=until)
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


def astro_build(web: Path, data: Path, dist: Path | None = None, *,
                until: float | None = None) -> None:
    """`npm run build` on the contract in `data` (absolute, so a stray SITE_DATA_DIR pointing at
    the fixtures can't be what gets built), into `web/dist` or `dist`."""
    until = node.deadline() if until is None else until
    out = dist or web / node.DIST
    if out.exists():
        shutil.rmtree(out)           # a failed build must never leave the previous one behind
    extra = ("--", "--outDir", str(out.resolve())) if dist else ()
    _run_npm(web, "run", "build", *extra,
             env={"SITE_DATA_DIR": str(data.resolve()), "ASTRO_TELEMETRY_DISABLED": "1"},
             until=until)
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


def build(ctx: Context, conn: sqlite3.Connection, *, until: float | None = None) -> BuildSummary:
    """npm ci (when needed) → astro build on the export → promotion images → routing files.
    `until`: the full path's deadline (`node.deadline()`), shared with the deploy (D35)."""
    started = time.monotonic()
    until = node.deadline() if until is None else until
    web, data = node.web_dir(ctx), site_data.default_dir(ctx).resolve()
    if not (data / "meta.json").is_file():
        raise BuildError(f"no site data in {data}: run `escapadinha export site-data` first")
    if not (web / "package-lock.json").is_file():
        raise BuildError(f"{web} is not the web package (no package-lock.json)")
    try:
        site_deploy.function_files(web)     # the review Function must bundle without packages
    except site_deploy.DeployError as exc:
        raise BuildError(str(exc)) from None
    installed = ensure_dependencies(web, until)
    dist = node.dist_dir(ctx)
    astro_build(web, data, until=until)
    images, missing, plan = finish(ctx, conn, data, dist, content=web / "src" / "content")
    size = sum(p.stat().st_size for p in dist.rglob("*") if p.is_file())
    return BuildSummary(round(time.monotonic() - started, 1), installed, page_counts(dist),
                        images, missing, len(plan.rules), plan.skipped, size, plan.warnings)
