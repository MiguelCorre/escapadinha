"""The GitHub Actions workflow (D25): triggers, overlap, timeout below the lock TTL, secrets."""

import re
from pathlib import Path

import yaml

from escapadinha.config import Secrets
from escapadinha.storage import sync

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "pipeline.yml"


def load() -> dict:
    wf = yaml.safe_load(WORKFLOW.read_text("utf-8"))
    wf["on"] = wf.pop(True, wf.get("on"))       # YAML 1.1 reads the key `on` as True
    return wf


def test_triggers_on_demand_only():
    """The half-hourly runs are dispatches from the scheduler Worker and its Actions fallback (D41,
    tests/test_scheduler.py); GitHub's own cron no longer starts this workflow."""
    on = load()["on"]
    assert "schedule" not in on
    assert on["workflow_dispatch"]["inputs"]["full"]["type"] == "boolean"
    # D62: the review Function dispatches this workflow too (`full: true`), so the only trigger
    # is workflow_dispatch and no token with write access to the repository's contents exists.
    assert set(on) == {"workflow_dispatch"}


def test_runs_never_overlap_and_end_before_the_lock_expires():
    wf = load()
    assert wf["concurrency"]["cancel-in-progress"] is False and wf["concurrency"]["group"]
    [job] = wf["jobs"].values()
    assert job["timeout-minutes"] < sync.LOCK_TTL.total_seconds() / 60


def test_the_full_paths_node_budget_leaves_room_in_the_job():
    """The full path's Node commands share one budget (D35); the rest of the job (collection
    before, review snapshot and database push after) keeps at least 20 minutes."""
    from escapadinha.website import node
    [job] = load()["jobs"].values()
    assert node.FULL_PATH_SECONDS / 60 <= job["timeout-minutes"] - 20


def test_every_secret_comes_from_actions_secrets_and_none_is_printed():
    [job] = load()["jobs"].values()
    expected = {name.upper() for name in Secrets.model_fields}
    assert {k: v for k, v in job["env"].items() if k in expected} == {
        name: f"${{{{ secrets.{name} }}}}" for name in expected}
    text = WORKFLOW.read_text("utf-8")
    assert "set -x" not in text
    for line in text.splitlines():
        if re.search(r"\b(echo|printf|cat)\b", line):
            assert not any(name in line for name in expected), line


def test_dispatch_forces_the_full_path_and_the_rest_decides_in_python():
    [job] = load()["jobs"].values()
    run_steps = [s for s in job["steps"] if "escapadinha run" in s.get("run", "")]
    assert len(run_steps) == 1
    step = run_steps[0]
    assert "inputs.full" in step["env"]["FULL"] and "repository_dispatch" not in step["env"]["FULL"]
    assert "--full" in step["run"]


def test_uv_and_the_browser_download_are_cached():
    [job] = load()["jobs"].values()
    uses = {s.get("uses", "").split("@")[0]: s for s in job["steps"]}
    assert uses["astral-sh/setup-uv"]["with"]["enable-cache"] is True
    assert "ms-playwright" in uses["actions/cache"]["with"]["path"]
    assert job["env"]["ESCAPADINHA_INSTALL_BROWSER"] == "1"


def test_the_full_path_can_build_and_deploy_the_astro_site_on_a_fresh_runner():
    """Node 22; the full path's `site build` runs `npm ci` itself (only when it builds, D35), so
    a fast path never installs anything. npm's download cache is restored (keyed on the web
    lockfile) and saved only after a full path's npm ci on a miss, never by a fast path.
    wrangler (npx) bundles web/functions; the Function imports no npm package (D29)."""
    from escapadinha.website import deploy as site_deploy
    [job] = load()["jobs"].values()
    uses = {s.get("uses", "").split("@")[0]: s for s in job["steps"]}
    node = uses["actions/setup-node"]["with"]
    assert int(node["node-version"]) >= 22
    assert "cache" not in node                       # its post step would save on any miss
    restore, save = uses["actions/cache/restore"], uses["actions/cache/save"]
    assert restore["with"]["path"] == save["with"]["path"] == "~/.npm"
    assert "hashFiles('web/package-lock.json')" in restore["with"]["key"]
    assert save["with"]["key"] == f"${{{{ steps.{restore['id']}.outputs.cache-primary-key }}}}"
    [run] = [s for s in job["steps"] if "escapadinha run" in s.get("run", "")]
    assert f"steps.{run['id']}.outputs.npm_ci == 'true'" in save["if"]
    assert f"steps.{restore['id']}.outputs.cache-hit != 'true'" in save["if"]
    steps = job["steps"]
    assert steps.index(restore) < steps.index(run) < steps.index(save)
    assert "sparse-checkout" not in (uses["actions/checkout"].get("with") or {})
    assert not any("npm ci" in s.get("run", "") for s in job["steps"])   # Python decides
    repo_web = WORKFLOW.parent.parent.parent / "web"
    assert site_deploy.function_files(repo_web)      # raises on a package import


# --- the tests' own workflow (D64) -----------------------------------------------------------

TESTS = WORKFLOW.parent / "tests.yml"


def python_workflow() -> dict:
    wf = yaml.safe_load(TESTS.read_text("utf-8"))
    wf["on"] = wf.pop(True, wf.get("on"))
    return wf


def test_every_pull_request_runs_the_python_tests():
    """D64: `web.yml` starts only for the web package and the contract, so PR #96 (src/ and
    tests/ only) merged with no check at all, onto the branch the pipeline deploys every 30
    minutes. Every pull request runs pytest, whatever it touches (docs and config have tests
    too), and nothing is deselected or skipped for a missing tool."""
    wf = python_workflow()
    assert set(wf["on"]) == {"pull_request"} and not wf["on"]["pull_request"]     # no path filter
    [job] = wf["jobs"].values()
    assert job["timeout-minutes"] <= 20
    runs = [s.get("run", "") for s in job["steps"]]
    [pytest_run] = [r for r in runs if "pytest" in r]
    assert pytest_run.strip() == "uv run --no-sync pytest"       # the browser test too
    assert any("uv sync --frozen" in r and "--no-dev" not in r for r in runs)
    uses = {s.get("uses", "").split("@")[0]: s for s in job["steps"]}
    assert int(uses["actions/setup-node"]["with"]["node-version"]) >= 22   # the Worker's tests
    assert any("npm ci" in r for r in runs)                      # test_crawl builds the real site
    # Chromium comes from `renderer.ensure_browser`, the pipeline's own install (and fallback).
    assert job["env"]["ESCAPADINHA_INSTALL_BROWSER"] == "1"
    assert not any("playwright install" in r for r in runs)


def test_the_tests_workflow_holds_no_secret():
    """The repository is public: a pull request from a fork runs this workflow."""
    wf = python_workflow()
    assert wf["permissions"] == {"contents": "read"}
    text = TESTS.read_text("utf-8")
    assert "secrets." not in text and "pull_request_target" not in text
