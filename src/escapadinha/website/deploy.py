"""Deploy the Astro build (`web/dist`, D35) to Cloudflare Pages with wrangler (Direct Upload).

Skips the upload when the content did not change since the last deploy. The build's own
timestamps (the footer's "Atualizado a ...", the explorer data's `generated_at`) are ignored
for that comparison, so a rebuild with the same content doesn't create a new deployment.
A fixture build (`<html data-fixture="true">`, D28) is refused.

The review Function (D29) ships in the same deployment: wrangler compiles `<cwd>/functions`,
so it runs in `web/` (D35; `pages deploy` never auto-detects a framework for an existing
project, checked in wrangler 4.149's source). The Function must still bundle without npm
packages (`function_files` refuses a package import), and the deploy hash covers its files
(line endings normalised), so a Function change redeploys an unchanged site.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
from pathlib import Path

import httpx

from escapadinha.config import Context
from escapadinha.storage import db
from escapadinha.website import node

# The build's timestamps: the footer ("Atualizado a <span class="num">14/10/2026 às 10:01</span>"
# in the Astro pages, without the span in the legacy Jinja ones) and the explorer data's
# generated_at. Not content: a rebuild that only moved them is not deployed again.
BUILT_AT = re.compile(rb"Atualizado a (?:<span[^>]*>)?[^<]*")
GENERATED_AT = re.compile(rb'"generated_at":"[^"]*"')
FIXTURE = b'data-fixture="true"'     # a build from the committed fixtures (D28): never deployed
DEPLOYED = "site.deployed"   # meta: {hash, url} of the last deployment (D25)
API = "https://api.cloudflare.com/client/v4"
FUNCTIONS = "functions"          # under the web package (web/functions, D28/D29)
# Module specifiers a TypeScript source loads: `import … from "x"` / `export … from "x"`,
# side-effect `import "x"`, and dynamic `import("x")`.
_IMPORT = re.compile(r"""^\s*(?:import|export)\b[^"']*?\bfrom\s+["']([^"']+)["']"""
                     r"""|^\s*import\s+["']([^"']+)["']"""
                     r"""|\bimport\s*\(\s*["']([^"']+)["']\s*\)""", re.M)


def _imports(source: str) -> list[str]:
    return [next(g for g in m.groups() if g) for m in _IMPORT.finditer(source)]


class DeployError(RuntimeError):
    pass


def content_hash(site_dir: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in site_dir.rglob("*") if p.is_file() and p.name != "build.json"):
        data = path.read_bytes()
        if path.suffix == ".html":
            data = BUILT_AT.sub(b"", data)
        elif path.suffix == ".json":
            data = GENERATED_AT.sub(b"", data)
        h.update(path.relative_to(site_dir).as_posix().encode())
        h.update(hashlib.sha256(data).digest())
    return h.hexdigest()


def function_files(web: Path) -> list[Path]:
    """`web/functions/**/*.ts` and the modules they import (transitively, relative imports
    only): what wrangler needs to bundle the review Function without node_modules. Sorted;
    empty without a functions folder. DeployError when an import doesn't resolve inside `web/`."""
    root = web / FUNCTIONS
    if not root.is_dir():
        return []
    todo = sorted(p for p in root.rglob("*.ts") if p.is_file())
    seen: set[Path] = set()
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        for spec in _imports(path.read_text("utf-8")):
            if not spec.startswith("."):
                raise DeployError(f"{path.relative_to(web).as_posix()} imports the package "
                                  f"'{spec}': the review Function must bundle without node_modules")
            base = (path.parent / spec).resolve()
            found = next((c for c in (base.with_name(base.name + ".ts"), base, base / "index.ts")
                          if c.is_file()), None)
            if found is None or not found.is_relative_to(web.resolve()):
                raise DeployError(f"{path.relative_to(web).as_posix()}: import '{spec}' not found "
                                  "inside web/")
            todo.append(web / found.relative_to(web.resolve()))
    return sorted(seen, key=lambda p: p.relative_to(web).as_posix())


def deploy_hash(site_dir: Path, web: Path, files: list[Path] | None = None) -> str:
    """The site's content hash plus the Function's sources (line endings normalised, so a
    Windows checkout and the runner's agree). `files`: `function_files(web)`, when the caller
    already has them."""
    files = function_files(web) if files is None else files
    if not files:
        return content_hash(site_dir)
    h = hashlib.sha256(content_hash(site_dir).encode())
    for path in files:
        h.update(path.relative_to(web).as_posix().encode())
        h.update(hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).digest())
    return h.hexdigest()


def _npx() -> str:
    found = node.tool("npx")
    if found is None:
        raise DeployError("npx not found: install Node.js (https://nodejs.org) to deploy the site")
    return found


def _wrangler(ctx: Context, *args: str, cwd: Path | None = None,
              until: float | None = None) -> subprocess.CompletedProcess:
    """`npx wrangler@<pinned> <args>` within the deadline `until` (the full path's, D35)."""
    s = ctx.secrets
    if not s.cloudflare_api_token or not s.cloudflare_account_id:
        raise DeployError("CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID are not set (see .env.example)")
    env = {"CLOUDFLARE_API_TOKEN": s.cloudflare_api_token,
           "CLOUDFLARE_ACCOUNT_ID": s.cloudflare_account_id, "WRANGLER_SEND_METRICS": "false"}
    cmd = [_npx(), "--yes", f"wrangler@{ctx.config.site.wrangler_version}", *args]
    # Run inside web/ (wrangler compiles <cwd>/functions), never the repository root, where
    # `pages project create` once mistook content/ + config.yaml for a Hugo project (D15).
    return node.run(cmd, cwd=cwd or node.web_dir(ctx), env=env,
                    until=node.deadline() if until is None else until, error=DeployError,
                    what=f"wrangler {' '.join(args[:2])}")


def _last_deploy(ctx: Context, conn: sqlite3.Connection) -> dict:
    """{hash, url} of the last deployment, from the database (synced to R2, D25); before D25
    it was data/site_deploy.json, still read when the database has none."""
    from escapadinha.pipeline import legacy_json
    return db.get_meta_json(conn, DEPLOYED) or legacy_json(ctx, "site_deploy.json")


def create_project(ctx: Context, client: httpx.Client | None = None) -> str:
    """One-time: create the Cloudflare Pages project through the REST API.

    Not `wrangler pages project create`: since 4.x it delegates missing projects to the
    Workers flow, which auto-detects a framework from the current folder.
    """
    s = ctx.secrets
    if not s.cloudflare_api_token or not s.cloudflare_account_id:
        raise DeployError("CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID are not set (see .env.example)")
    name = ctx.config.site.cloudflare_project
    http = client or httpx.Client(timeout=30)
    url = f"{API}/accounts/{s.cloudflare_account_id}/pages/projects"
    headers = {"Authorization": f"Bearer {s.cloudflare_api_token}"}
    existing = http.get(f"{url}/{name}", headers=headers)
    if existing.status_code == 200:
        return f"Pages project '{name}' already exists: https://{existing.json()['result']['subdomain']}"
    response = http.post(url, headers=headers, json={"name": name, "production_branch": "main"})
    body = response.json() if response.content else {}
    if response.status_code != 200 or not body.get("success"):
        errors = "; ".join(e.get("message", "") for e in body.get("errors", [])) or response.text[:300]
        raise DeployError(f"Could not create Pages project '{name}': {errors}")
    return f"Created Pages project '{name}': https://{body['result']['subdomain']}"


def fixture_pages(site_dir: Path) -> list[str]:
    """Pages of a build made from the committed fixtures (`<html data-fixture="true">`)."""
    return sorted(p.relative_to(site_dir).as_posix() for p in site_dir.rglob("*.html")
                  if FIXTURE in p.read_bytes())


def deploy(ctx: Context, conn: sqlite3.Connection, force: bool = False, *,
           until: float | None = None) -> tuple[bool, str]:
    """Upload web/dist and the review Function if either changed. Returns (deployed, message).
    `until`: the full path's deadline (`node.deadline()`), shared with the build (D35)."""
    web, site_dir = node.web_dir(ctx), node.dist_dir(ctx)
    if not (site_dir / "index.html").exists():
        raise DeployError(f"{site_dir} is empty: run `escapadinha site build` first")
    fixtures = fixture_pages(site_dir)
    if fixtures:
        raise DeployError(f"{site_dir} is a fixture build (test data, data-fixture=\"true\" on "
                          f"{len(fixtures)} pages, e.g. {fixtures[0]}): never deployed. Export the "
                          "real data and run `escapadinha site build`.")
    functions = function_files(web)          # refuses a package import; hashed with the site
    digest = deploy_hash(site_dir, web, functions)
    from escapadinha.website import routing
    if not force and _last_deploy(ctx, conn).get("hash") == digest:
        routing.commit(conn)                 # the live site is this build: its paths are live
        return False, "site unchanged since last deploy, skipped"
    result = _wrangler(ctx, "pages", "deploy", str(site_dir.resolve()),
                       "--project-name", ctx.config.site.cloudflare_project,
                       "--branch", "main", "--commit-dirty=true", cwd=web, until=until)
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        hint = (" (run `escapadinha site setup` once to create the project)"
                if "not found" in output.lower() else "")
        raise DeployError(f"wrangler deploy failed{hint}:\n{output[-1500:]}")
    urls = re.findall(r"https://\S+\.pages\.dev\S*", output)
    db.set_meta(conn, DEPLOYED, json.dumps({"hash": digest, "url": urls[-1] if urls else None}))
    routing.commit(conn)                     # only now are the build's paths live (D35)
    return True, urls[-1] if urls else "deployed"
