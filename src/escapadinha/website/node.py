"""Node.js for the website (D35): where the web package and its build are, finding `npm`,
`npx` and `node`, and running them inside one time budget.

Kept light on purpose (no pipeline, site data or PIL imports): `cli.py` imports `BuildError`
at the top level, and both the build (`astro.py`) and the deploy (`deploy.py`) run their Node
commands through `run`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from escapadinha.config import Context

WEB = "web"       # the Astro package, under the project root (D28)
DIST = "dist"     # its build, under WEB: what `site deploy` uploads
NODE_DIRS = [Path(r"C:\Program Files\nodejs")]
# One budget for every Node command of a full path (npm ci, astro build, wrangler deploy): each
# command gets what is left of it (D35). 20 minutes leave the rest of the 45-minute job (D25:
# collection before, the review snapshot and the database push after) well inside the run
# lock's 60 minutes (D21).
FULL_PATH_SECONDS = 20 * 60
OUTPUT_TAIL = 3000   # characters of a failed command's output kept in the error


class BuildError(RuntimeError):
    """The site build failed (npm, astro, the pipeline's additions)."""


def web_dir(ctx: Context) -> Path:
    return ctx.root / WEB


def dist_dir(ctx: Context) -> Path:
    return web_dir(ctx) / DIST


def tool(name: str) -> str | None:
    """`npm`, `npx` or `node` on the PATH (on Windows `which` finds `npm.cmd` / `node.exe`
    through PATHEXT), else in Node's default Windows install folder: the PC's scheduled task
    may run with a PATH that lacks it. None when Node isn't installed."""
    found = shutil.which(name)
    if found:
        return found
    for d in NODE_DIRS:
        for candidate in (d / f"{name}.cmd", d / f"{name}.exe"):
            if candidate.exists():
                return str(candidate)
    return None


def deadline(seconds: float = FULL_PATH_SECONDS) -> float:
    """A `time.monotonic()` deadline `seconds` from now: the budget `run` shares out."""
    return time.monotonic() + seconds


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


def run(cmd: list[str], *, cwd: Path, env: dict[str, str], until: float,
        error: type[Exception], what: str) -> subprocess.CompletedProcess:
    """Run a Node command in `cwd` with `env` added and the tool's folder first on the PATH
    (npm's scripts call `node`), timing out at the monotonic deadline `until`. A timeout, a
    command that can't start, or no time left raises `error` (with the end of the output);
    the caller checks the return code."""
    remaining = until - time.monotonic()
    if remaining <= 0:
        raise error(f"{what}: no time left in the full path's budget "
                    f"({FULL_PATH_SECONDS // 60} min, D35)")
    full_env = os.environ | env
    full_env["PATH"] = str(Path(cmd[0]).parent) + os.pathsep + full_env.get("PATH", "")
    try:
        return subprocess.run(cmd, cwd=cwd, env=full_env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=remaining)
    except subprocess.TimeoutExpired as exc:
        output = (_text(exc.stdout) + _text(exc.stderr)).strip()
        raise error(f"{what} timed out after {remaining:.0f} s (the full path's budget is "
                    f"{FULL_PATH_SECONDS // 60} min, D35):\n{output[-OUTPUT_TAIL:]}") from None
    except OSError as exc:
        raise error(f"{what} could not start: {exc}") from None


def failed(result: subprocess.CompletedProcess) -> str:
    """The end of a finished command's output, for its error message."""
    return (_text(result.stdout) + _text(result.stderr)).strip()[-OUTPUT_TAIL:]
