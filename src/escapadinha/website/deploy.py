"""Deploy the built site to Cloudflare Pages with wrangler (Direct Upload).

Skips the upload when the content did not change since the last deploy. The footer's
"Atualizado a ..." timestamp is ignored for that comparison, so a rebuild with the same
deals doesn't create a new deployment every 2 hours.

The review Function (D29) ships in the same deployment: wrangler compiles `<cwd>/functions`,
so it runs in a temporary staging folder holding `functions/` copied from `web/functions/`
plus the `web/src/lib/` modules they import (and nothing else: it never scans the repository,
D15). The deploy hash covers those files too, so a Function change redeploys an unchanged site.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

import httpx

from escapadinha.config import Context
from escapadinha.storage import db

BUILT_AT = re.compile(rb"Atualizado a [^<]*")
DEPLOYED = "site.deployed"   # meta: {hash, url} of the last deployment (D25)
NODE_DIRS = [Path(r"C:\Program Files\nodejs")]
API = "https://api.cloudflare.com/client/v4"
FUNCTIONS = "functions"          # under the web package (web/functions, D28/D29)
_IMPORT = re.compile(r"""^\s*(?:import|export)\b[^"']*?\bfrom\s+["']([^"']+)["']""", re.M)


class DeployError(RuntimeError):
    pass


def content_hash(site_dir: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in site_dir.rglob("*") if p.is_file() and p.name != "build.json"):
        data = path.read_bytes()
        if path.suffix == ".html":
            data = BUILT_AT.sub(b"", data)
        h.update(path.relative_to(site_dir).as_posix().encode())
        h.update(hashlib.sha256(data).digest())
    return h.hexdigest()


def web_dir(ctx: Context) -> Path:
    return ctx.root / "web"


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
        for spec in _IMPORT.findall(path.read_text("utf-8")):
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


def deploy_hash(site_dir: Path, web: Path) -> str:
    """The site's content hash plus the Function's sources (line endings normalised, so a
    Windows checkout and the runner's agree)."""
    files = function_files(web)
    if not files:
        return content_hash(site_dir)
    h = hashlib.sha256(content_hash(site_dir).encode())
    for path in files:
        h.update(path.relative_to(web).as_posix().encode())
        h.update(hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).digest())
    return h.hexdigest()


def _stage_functions(web: Path, files: list[Path], stage: Path) -> None:
    for path in files:
        target = stage / path.relative_to(web)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def _npx() -> str:
    found = shutil.which("npx")
    if found:
        return found
    for d in NODE_DIRS:
        candidate = d / "npx.cmd"
        if candidate.exists():
            return str(candidate)
    raise DeployError("npx not found: install Node.js (https://nodejs.org) to deploy the site")


def _wrangler(ctx: Context, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    s = ctx.secrets
    if not s.cloudflare_api_token or not s.cloudflare_account_id:
        raise DeployError("CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID are not set (see .env.example)")
    env = os.environ | {"CLOUDFLARE_API_TOKEN": s.cloudflare_api_token,
                        "CLOUDFLARE_ACCOUNT_ID": s.cloudflare_account_id,
                        "WRANGLER_SEND_METRICS": "false"}
    npx = _npx()
    env["PATH"] = str(Path(npx).parent) + os.pathsep + env.get("PATH", "")
    cmd = [npx, "--yes", f"wrangler@{ctx.config.site.wrangler_version}", *args]
    # Run inside site/ (or the functions staging folder): wrangler's framework auto-detection
    # must never scan the repo (it mistook content/ + config.yaml for a Hugo project).
    ctx.site_dir.mkdir(parents=True, exist_ok=True)
    return subprocess.run(cmd, env=env, cwd=cwd or ctx.site_dir, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)


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


def deploy(ctx: Context, conn: sqlite3.Connection, force: bool = False) -> tuple[bool, str]:
    """Upload site/ and the review Function if either changed. Returns (deployed, message)."""
    site_dir = ctx.site_dir
    if not (site_dir / "index.html").exists():
        raise DeployError("site/ is empty: run `escapadinha site build` first")
    web = web_dir(ctx)
    digest = deploy_hash(site_dir, web)
    if not force and _last_deploy(ctx, conn).get("hash") == digest:
        return False, "site unchanged since last deploy, skipped"
    args = ("pages", "deploy", str(site_dir.resolve()),
            "--project-name", ctx.config.site.cloudflare_project,
            "--branch", "main", "--commit-dirty=true")
    functions = function_files(web)
    if functions:
        with tempfile.TemporaryDirectory(prefix="pages-deploy-") as stage:
            _stage_functions(web, functions, Path(stage))
            result = _wrangler(ctx, *args, cwd=Path(stage))
    else:
        result = _wrangler(ctx, *args)
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        hint = (" (run `escapadinha site setup` once to create the project)"
                if "not found" in output.lower() else "")
        raise DeployError(f"wrangler deploy failed{hint}:\n{output[-1500:]}")
    urls = re.findall(r"https://\S+\.pages\.dev\S*", output)
    db.set_meta(conn, DEPLOYED, json.dumps({"hash": digest, "url": urls[-1] if urls else None}))
    return True, urls[-1] if urls else "deployed"
