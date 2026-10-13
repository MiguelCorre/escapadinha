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


def test_triggers_every_two_hours_and_on_demand():
    on = load()["on"]
    [schedule] = on["schedule"]
    minute, hour, *rest = schedule["cron"].split()
    assert minute.isdigit() and hour == "*/2" and rest == ["*", "*", "*"]
    assert on["workflow_dispatch"]["inputs"]["full"]["type"] == "boolean"
    assert set(on["repository_dispatch"]["types"]) >= {"review-decision", "full-run"}


def test_runs_never_overlap_and_end_before_the_lock_expires():
    wf = load()
    assert wf["concurrency"]["cancel-in-progress"] is False and wf["concurrency"]["group"]
    [job] = wf["jobs"].values()
    assert job["timeout-minutes"] < sync.LOCK_TTL.total_seconds() / 60


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
    assert "repository_dispatch" in step["env"]["FULL"] and "inputs.full" in step["env"]["FULL"]
    assert "--full" in step["run"]


def test_uv_and_the_browser_download_are_cached():
    [job] = load()["jobs"].values()
    uses = {s.get("uses", "").split("@")[0]: s for s in job["steps"]}
    assert uses["astral-sh/setup-uv"]["with"]["enable-cache"] is True
    assert "ms-playwright" in uses["actions/cache"]["with"]["path"]
    assert job["env"]["ESCAPADINHA_INSTALL_BROWSER"] == "1"
