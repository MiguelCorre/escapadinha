"""Deploy the built site to Cloudflare Pages with wrangler (Direct Upload).

Skips the upload when the content did not change since the last deploy. The footer's
"Atualizado a ..." timestamp is ignored for that comparison, so a rebuild with the same
deals doesn't create a new deployment every 2 hours.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from escapadinha.config import Context

BUILT_AT = re.compile(rb"Atualizado a [^<]*")
NODE_DIRS = [Path(r"C:\Program Files\nodejs")]


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


def _npx() -> str:
    found = shutil.which("npx")
    if found:
        return found
    for d in NODE_DIRS:
        candidate = d / "npx.cmd"
        if candidate.exists():
            return str(candidate)
    raise DeployError("npx not found: install Node.js (https://nodejs.org) to deploy the site")


def _wrangler(ctx: Context, *args: str) -> subprocess.CompletedProcess:
    s = ctx.secrets
    if not s.cloudflare_api_token or not s.cloudflare_account_id:
        raise DeployError("CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID are not set (see .env.example)")
    env = os.environ | {"CLOUDFLARE_API_TOKEN": s.cloudflare_api_token,
                        "CLOUDFLARE_ACCOUNT_ID": s.cloudflare_account_id,
                        "WRANGLER_SEND_METRICS": "false"}
    npx = _npx()
    env["PATH"] = str(Path(npx).parent) + os.pathsep + env.get("PATH", "")
    cmd = [npx, "--yes", f"wrangler@{ctx.config.site.wrangler_version}", *args]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=600)


def _state_file(ctx: Context) -> Path:
    return ctx.db_path.parent / "site_deploy.json"


def create_project(ctx: Context) -> str:
    """One-time: create the Cloudflare Pages project (production branch: main)."""
    result = _wrangler(ctx, "pages", "project", "create", ctx.config.site.cloudflare_project,
                       "--production-branch", "main")
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0 and "already exists" not in output:
        raise DeployError(f"wrangler project create failed:\n{output[-1500:]}")
    return output


def deploy(ctx: Context, force: bool = False) -> tuple[bool, str]:
    """Upload site/ if its content changed. Returns (deployed, message)."""
    site_dir = ctx.site_dir
    if not (site_dir / "index.html").exists():
        raise DeployError("site/ is empty: run `escapadinha site build` first")
    digest = content_hash(site_dir)
    state_file = _state_file(ctx)
    state = json.loads(state_file.read_text("utf-8")) if state_file.exists() else {}
    if not force and state.get("hash") == digest:
        return False, "site unchanged since last deploy, skipped"
    result = _wrangler(ctx, "pages", "deploy", str(site_dir),
                       "--project-name", ctx.config.site.cloudflare_project,
                       "--branch", "main", "--commit-dirty=true")
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        hint = (" (run `escapadinha site setup` once to create the project)"
                if "not found" in output.lower() else "")
        raise DeployError(f"wrangler deploy failed{hint}:\n{output[-1500:]}")
    urls = re.findall(r"https://\S+\.pages\.dev\S*", output)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"hash": digest, "url": urls[-1] if urls else None}, indent=2),
                          encoding="utf-8")
    return True, urls[-1] if urls else "deployed"
