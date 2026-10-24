"""The half-hourly schedule (D41, D46): the scheduler Worker's config against the workflows it
dispatches, the Actions fallback, the windows against the run log's 2 h warning, the Worker's
own tests (node:test), and that warning."""

import json
import re
import shutil
import subprocess
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from escapadinha import pipeline
from escapadinha.storage import db

REPO = Path(__file__).parent.parent
WORKER = REPO / "workers" / "scheduler"
WORKFLOWS = REPO / ".github" / "workflows"
EVERY = 30                        # minutes between two ticks (`17,47` minute field, D46)


def wrangler() -> dict:
    return tomllib.loads((WORKER / "wrangler.toml").read_text("utf-8"))


def workflow(name: str) -> dict:
    wf = yaml.safe_load((WORKFLOWS / name).read_text("utf-8"))
    wf["on"] = wf.pop(True, wf.get("on"))       # YAML 1.1 reads the key `on` as True
    return wf


def fallback_env() -> dict:
    [job] = workflow("pipeline-fallback.yml")["jobs"].values()
    [step] = [s for s in job["steps"] if "fallback.js" in s.get("run", "")]
    return step["env"]


# --- the Worker's configuration -------------------------------------------------------------

def test_the_worker_fires_every_thirty_minutes_and_has_no_url():
    config = wrangler()
    [cron] = config["triggers"]["crons"]
    minute, hour, *rest = cron.split()
    minutes = sorted(int(m) for m in minute.split(","))
    assert minutes == [17, 47] and hour == "*" and rest == ["*", "*", "*"]
    assert minutes[1] - minutes[0] == EVERY
    assert config["workers_dev"] is False and config["preview_urls"] is False
    assert "routes" not in config and "route" not in config
    assert config["main"] == "src/index.js" and (WORKER / config["main"]).is_file()
    assert config["observability"]["enabled"] is True        # failed dispatches in Workers Logs


def test_the_worker_dispatches_a_routine_run_of_the_pipeline_workflow():
    """Its vars name a workflow that exists and accepts the inputs the tick sends (a routine
    run: `full` false, run_path decides fast or full, D25), on the default branch."""
    vars_ = wrangler()["vars"]
    assert vars_["GITHUB_REPOSITORY"] == "MiguelCorre/escapadinha"
    assert vars_["REF"] == "master"
    on = workflow(vars_["WORKFLOW"])["on"]
    inputs = on["workflow_dispatch"]["inputs"]
    source = (WORKER / "src" / "schedule.js").read_text("utf-8")
    sent = re.search(r"INPUTS = Object\.freeze\((\{.*?\})\)", source).group(1)
    assert json.loads(re.sub(r"(\w+):", r'"\1":', sent)) == {"full": "false"}
    assert inputs["full"]["type"] == "boolean" and inputs["full"]["default"] is False


def test_the_token_is_only_a_secret():
    """Never a var in wrangler.toml (vars are plain text in the dashboard and the repository)."""
    config = wrangler()
    assert "GITHUB_ACTIONS_TOKEN" not in config.get("vars", {})
    text = (WORKER / "wrangler.toml").read_text("utf-8")
    assert "github_pat_" not in text and "ghp_" not in text


def test_the_worker_needs_no_package_and_deploys_with_the_pinned_wrangler():
    """Plain JavaScript, no dependencies: nothing to install before `wrangler deploy`, and the
    same wrangler version as the site's deploy (config `site.wrangler_version`)."""
    package = json.loads((WORKER / "package.json").read_text("utf-8"))
    assert not package.get("dependencies") and not package.get("devDependencies")
    pinned = yaml.safe_load((REPO / "config.yaml").read_text("utf-8"))["site"]["wrangler_version"]
    assert package["scripts"]["deploy"] == f"npx --yes wrangler@{pinned} deploy"
    for path in (WORKER / "src").glob("*.js"):
        for spec in re.findall(r"""^import .*?from\s+["']([^"']+)["']""",
                               path.read_text("utf-8"), re.M):
            assert spec.startswith("./") or (path.name == "fallback.js" and spec.startswith("node:")), \
                f"{path.name} imports {spec}"
    worker_imports = re.findall(r"""from\s+["']([^"']+)["']""",
                                (WORKER / "src" / "index.js").read_text("utf-8"))
    assert worker_imports == ["./schedule.js"]         # no node: module in the Worker's bundle


def test_every_wrangler_version_in_the_repository_is_the_configs():
    """One source of truth, config `site.wrangler_version` (the site's deploy reads it): the
    Worker's deploy script and every `wrangler@<version>` the docs tell Miguel to run must be
    that version, and so must `SiteConfig`'s default. Bump the config, then every place this
    lists."""
    from escapadinha.config import SiteConfig
    pinned = yaml.safe_load((REPO / "config.yaml").read_text("utf-8"))["site"]["wrangler_version"]
    assert SiteConfig().wrangler_version == pinned
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True,
                             check=True).stdout.decode("utf-8").split("\0")
    found: dict[str, set[str]] = {}
    for name in filter(None, tracked):
        try:
            text = (REPO / name).read_text("utf-8")
        except (UnicodeDecodeError, OSError):         # binary files, removed in the work tree
            continue
        for version in re.findall(r"wrangler@(\d[\w.+-]*)", text):
            found.setdefault(version, set()).add(name)
    assert found.keys() == {pinned}, found
    assert {"workers/scheduler/package.json", "docs/runbooks/agendamento.md"} <= found[pinned]


# --- the pipeline workflow and its fallback -------------------------------------------------

def test_every_run_of_the_pipeline_workflow_is_a_real_run():
    """No `schedule` on pipeline.yml: GitHub's best-effort cron moved to the fallback workflow,
    which dispatches. A skipped check never shows up as a pipeline run, so the Worker and the
    fallback can count every run in their window."""
    on = workflow("pipeline.yml")["on"]
    assert "schedule" not in on
    assert set(on) == {"workflow_dispatch", "repository_dispatch"}


def test_the_fallback_runs_the_workers_tick_with_its_own_token_and_window():
    wf = workflow("pipeline-fallback.yml")
    [schedule] = wf["on"]["schedule"]
    minute, hour, *rest = schedule["cron"].split()
    assert minute.isdigit() and re.fullmatch(r"\*/\d+", hour) and rest == ["*", "*", "*"]
    assert "workflow_dispatch" in wf["on"]
    assert wf["permissions"] == {"actions": "write", "contents": "read"}
    [job] = wf["jobs"].values()
    assert job["timeout-minutes"] <= 5
    uses = {s.get("uses", "").split("@")[0]: s for s in job["steps"]}
    assert uses["actions/checkout"]["with"]["sparse-checkout"] == "workers/scheduler"
    assert int(uses["actions/setup-node"]["with"]["node-version"]) >= 22
    env = fallback_env()
    assert env["GITHUB_ACTIONS_TOKEN"] == "${{ github.token }}"     # never a stored PAT
    vars_ = wrangler()["vars"]
    assert env["WORKFLOW"] == vars_["WORKFLOW"] and env["REF"] == vars_["REF"]
    text = (WORKFLOWS / "pipeline-fallback.yml").read_text("utf-8")
    assert "set -x" not in text and not re.search(r"\b(echo|printf|cat)\b.*TOKEN", text)


def test_a_healthy_schedule_never_warns_and_the_fallback_waits_for_the_warning():
    """The Worker skips a tick when a run started within its window: the longest gap that
    leaves is window + 30 min, which must stay below the run log's warning. The fallback only
    dispatches once that warning would be due, so with a working Worker it never does."""
    worker_window = int(wrangler()["vars"]["SKIP_IF_RUN_WITHIN_MINUTES"])
    fallback_window = int(fallback_env()["SKIP_IF_RUN_WITHIN_MINUTES"])
    warning = pipeline.RUN_GAP_WARNING / timedelta(minutes=1)
    assert worker_window + EVERY < warning <= fallback_window
    # A review decision's run spares the next tick; the scheduled run before a tick (EVERY
    # minutes old by then) never does, or every tick would skip.
    assert 10 <= worker_window < EVERY


# --- the Worker's own tests -----------------------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_the_workers_own_tests_pass():
    """`node --test` in workers/scheduler (dispatch request, skip rules, token never logged)."""
    result = subprocess.run(["node", "--test", "--test-reporter=tap"], cwd=WORKER,
                            capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
    passed = re.search(r"^# pass (\d+)$", result.stdout, re.M)
    assert passed and int(passed.group(1)) > 0 and re.search(r"^# fail 0$", result.stdout, re.M)


# --- the run log's warning --------------------------------------------------------------------

NOW = datetime(2026, 10, 16, 10, 20, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "escapadinha.db")
    db.init(connection)
    return connection


def started(conn, when: datetime, scope: str = "full", status: str = "ok") -> int:
    cur = conn.execute("INSERT INTO fetch_runs (source, started_at, scope, status) VALUES (?, ?, ?, ?)",
                       ("travelpayouts", when.isoformat(), scope, status))
    conn.commit()
    return cur.lastrowid


def test_no_warning_before_the_first_run_or_on_schedule(conn):
    assert pipeline.late_run_warning(conn, NOW) is None
    started(conn, NOW - timedelta(minutes=50))               # a skipped tick's longest gap
    assert pipeline.late_run_warning(conn, NOW) is None
    started(conn, NOW - timedelta(hours=2))
    assert pipeline.late_run_warning(conn, NOW - timedelta(seconds=1)) is None


def test_a_previous_run_more_than_two_hours_old_is_a_warning(conn):
    run_id = started(conn, NOW - timedelta(hours=5, minutes=7), status="failed")
    warning = pipeline.late_run_warning(conn, NOW)
    assert warning == (f"the previous run (#{run_id}) started 5 h 07 min ago, more than 2 h: the "
                       "half-hourly schedule missed runs. Check the scheduler Worker "
                       "(docs/runbooks/agendamento.md).")
    assert "3 h 01 min" in pipeline.late_run_warning(conn, NOW - timedelta(hours=2, minutes=6))


def test_a_live_check_is_not_a_run(conn):
    """The review's live check (D26) writes a `live_check` row: it says nothing about the
    schedule, so it neither hides nor causes the warning."""
    started(conn, NOW - timedelta(hours=6))
    started(conn, NOW - timedelta(minutes=10), scope="live_check")
    assert "6 h 00 min" in pipeline.late_run_warning(conn, NOW)
