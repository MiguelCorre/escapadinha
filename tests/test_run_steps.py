"""The run's own-row steps that never fail the run (D63): the airlines (D47), the probe's
import and list (D48), the enrichment (D43) and Aviasales' special offers (D46). Each gives
the run's report one line (its summary's `line()`), prints its errors under it, and an
unexpected error becomes a "failed" line, never a stopped run."""

from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from escapadinha import cli, pipeline
from escapadinha.collector import hotlist
from escapadinha.storage import db
from test_pipeline import ctx  # noqa: F401

PLAN = hotlist.HotPlan(tasks=(), cursor=0, n_deal_tasks=0, n_pairs=2, n_months=3)


@pytest.fixture
def steps(ctx, monkeypatch):
    """`cli._pipeline_steps` with its other steps stubbed: what remains is the five steps'
    report lines, on the fast path."""
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    conn = pipeline.open_db(ctx)
    db.set_meta(conn, pipeline.DISCOVERED_AT, db.utcnow().isoformat())   # no discovery this run
    conn.close()
    monkeypatch.setattr(cli, "_collect", lambda: SimpleNamespace(
        status="ok", n_requests=0, n_observations=0, n_new=0, errors=[],
        plan=SimpleNamespace(describe=lambda: "routine")))
    for name in ("recheck_cmd", "detect", "publish_due"):
        monkeypatch.setattr(cli, name, lambda: None)
    monkeypatch.setattr(cli.run_path, "decide",
                        lambda c, k, force=False: cli.run_path.PathDecision(False, "x"))

    def run(**summaries) -> list[str]:
        for name, summary in summaries.items():
            monkeypatch.setattr(pipeline, name, lambda ctx, conn, s=summary: s)
        report: list[str] = []
        cli._pipeline_steps(render=False, full=False, report=report)
        assert report[0] == "Collection: ok, routine, 0 requests, 0 offers (0 new)"
        assert report[-1] == "Path: fast (x)"
        return report[1:-1]
    return run


def test_each_step_gives_the_report_one_line_and_prints_its_errors(steps, capsys):
    lines = steps(
        run_airlines=pipeline.AirlinesSummary("ryanair", 7, "partial", 3, 2, 1,
                                              ["LIS-LON/STN 2026-11: down"], PLAN),
        run_probe_import=pipeline.ProbeImport(5, 2, 3, 2, 4, 1, ["probe/results/a.json: bad"]),
        run_probe_wanted=pipeline.WantedSummary(3, 1, "probe/wanted.json"),
        run_enrich=pipeline.EnrichSummary(9, 5, 3, 2, 1, ["LIS-LON 2026-11-06 2026-11-09: 500"]),
        run_special_offers=pipeline.SpecialOffersSummary(9, 3, 2, 1, ["OPO: 502"]))
    assert lines == [
        "Airlines: Ryanair: partial, 0 of 6 pair-months in rotation, 3 requests, 2 offers "
        "(1 new), 1 failed",
        "Probe results: 2 files, 2 of 3 searches with booking options, 4 offers (1 new), 1 failed",
        "Probe list: 3 trips (1 open promotions first) → probe/wanted.json",
        "Enrichment: 3 GraphQL requests, 2 of 5 offers matched, 1 left for the next run, 1 failed",
        "Special offers: 2 GraphQL requests, 1 of 3 open deals on Aviasales' list, 1 failed",
    ]
    out = capsys.readouterr().out
    for err in ("LIS-LON/STN 2026-11: down", "probe/results/a.json: bad",
                "LIS-LON 2026-11-06 2026-11-09: 500", "OPO: 502"):
        assert f"✗ {err}" in out


def test_a_step_with_nothing_to_ask_says_so(steps):
    lines = steps(
        run_airlines=pipeline.AirlinesSummary("ryanair", None, "disabled", 0, 0, 0, []),
        run_probe_import=pipeline.ProbeImport(None, 0, 0, 0, 0, 0, []),
        run_enrich=pipeline.EnrichSummary(None, 0, 0, 0, 0, []),
        run_special_offers=pipeline.SpecialOffersSummary(None, 0, 0, 0, []))
    assert lines[:2] == ["Airlines: Ryanair: off (airlines.ryanair.enabled)",
                         "Probe results: none waiting"]
    assert lines[3:] == ["Enrichment: nothing to ask (no new low prices or candidates)",
                         "Special offers: nothing to ask (no open deals)"]


def test_a_step_that_could_not_start_says_it_skipped(steps):
    lines = steps(
        run_airlines=pipeline.AirlinesSummary("ryanair", None, "disabled", 0, 0, 0, []),
        run_probe_import=pipeline.ProbeImport(None, 0, 0, 0, 0, 0, []),
        run_enrich=pipeline.EnrichSummary(None, 4, 0, 0, 4, ["TRAVELPAYOUTS_TOKEN missing"]),
        run_special_offers=pipeline.SpecialOffersSummary(None, 2, 0, 0, ["TRAVELPAYOUTS_TOKEN missing"]))
    assert lines[3:] == ["Enrichment: skipped (4 offers)", "Special offers: skipped (2 open deals)"]


class Broken:
    """A module whose every attribute raises: the step fails inside, before its run row."""

    def __init__(self, message: str):
        self.message = message

    def __getattr__(self, name):
        raise RuntimeError(self.message)


def test_an_unexpected_error_is_a_failed_line_never_a_stopped_run(steps, monkeypatch):
    def broken(message):
        def fail(*args, **kwargs):
            raise RuntimeError(message)
        return fail
    monkeypatch.setattr(pipeline, "airline_pause", broken("pause broke"))
    monkeypatch.setattr(pipeline, "probe_results", Broken("results broke"))
    monkeypatch.setattr(pipeline, "latest_offers", broken("list broke"))
    lines = steps(run_enrich=pipeline.EnrichSummary(None, 0, 0, 0, 0, []),
                  run_special_offers=pipeline.SpecialOffersSummary(None, 0, 0, 0, []))
    assert lines[:3] == ["Airlines: failed (RuntimeError: pause broke)",
                         "Probe results: failed (RuntimeError: results broke)",
                         "Probe list: failed (RuntimeError: list broke)"]


def test_enrichment_and_special_offers_never_fail_the_run_either(ctx, steps, monkeypatch):
    conn = pipeline.open_db(ctx)
    db.finish_run(conn, db.start_run(conn, "travelpayouts"), status="ok", n_requests=0,
                  n_observations=0, error=None)          # a completed run to enrich
    conn.close()

    def broken(message):
        def fail(*args, **kwargs):
            raise RuntimeError(message)
        return fail
    monkeypatch.setattr(pipeline, "enrich_targets", broken("targets broke"))
    monkeypatch.setattr(pipeline.db, "open_deals", broken("deals broke"))
    lines = steps(run_airlines=pipeline.AirlinesSummary("ryanair", None, "disabled", 0, 0, 0, []),
                  run_probe_import=pipeline.ProbeImport(None, 0, 0, 0, 0, 0, []),
                  run_probe_wanted=pipeline.WantedSummary(0, 0, "probe/wanted.json"))
    assert lines[3:] == ["Enrichment: failed (RuntimeError: targets broke)",
                         "Special offers: failed (RuntimeError: deals broke)"]
    result = CliRunner().invoke(cli.app, ["special-offers"])
    assert result.exit_code == 1 and "Special offers: failed (RuntimeError: deals broke)" in result.output


# --- the seam itself: `pipeline.run_step` ---------------------------------------------------

class Step(pipeline.RunStep):
    """A run step over fixed items: a number is an answer with that many rows, an exception a
    failed item; `boom` raises in the middle of the items."""

    name = "test-source"
    scope = "test"
    label = "Test step"

    def __init__(self, items, boom=False):
        self.items, self.boom = items, boom

    def run(self, ctx, conn, run, now):
        for n, item in enumerate(self.items):
            run.n_requests += 1
            if self.boom and n == 1:
                raise RuntimeError("step broke")
            if isinstance(item, Exception):
                run.fail(f"item {n}", item)
                continue
            run.answer({"payload": {"rows": item}}, observations=item, new=1)

    def finish(self, ctx, conn, run, status, now):
        return pipeline.EnrichSummary(run.run_id, len(self.items), run.n_requests, run.n_new, 0,
                                      run.errors)


def fetch_run(conn, run_id):
    return conn.execute("SELECT source, scope, status, n_requests, n_observations, n_new, error, "
                        "archive_key FROM fetch_runs WHERE id = ?", (run_id,)).fetchone()


@pytest.mark.parametrize("items, status", [
    ([2, 3], "ok"), ([2, ValueError("down")], "partial"), ([ValueError("down")], "failed")])
def test_a_step_gets_its_own_archived_run_row_with_the_items_counts(ctx, items, status):
    conn = pipeline.open_db(ctx)
    summary = pipeline.run_step(ctx, conn, Step(items))
    row = fetch_run(conn, summary.run_id)
    answered = [i for i in items if not isinstance(i, Exception)]
    assert tuple(row)[:6] == ("test-source", "test", status, len(items), sum(answered), len(answered))
    assert row["archive_key"] and (row["error"] is None) == (status == "ok")
    assert summary.errors == [f"item {n}: down" for n, i in enumerate(items) if isinstance(i, Exception)]


def test_a_step_that_raises_closes_its_row_as_failed_and_never_raises(ctx):
    conn = pipeline.open_db(ctx)
    summary = pipeline.run_step(ctx, conn, Step([2, 3, 4], boom=True))
    assert summary == pipeline.StepFailed("Test step", "RuntimeError: step broke")
    assert summary.line() == "Test step: failed (RuntimeError: step broke)" and summary.errors == []
    [row] = conn.execute("SELECT status, n_requests, n_observations, error FROM fetch_runs "
                         "WHERE source = 'test-source'").fetchall()
    assert tuple(row) == ("failed", 2, 2, "RuntimeError: step broke")


def test_an_archive_failure_is_listed_and_makes_the_row_partial(ctx, monkeypatch):
    conn = pipeline.open_db(ctx)

    def no_archive(*args):
        raise OSError("bucket down")
    monkeypatch.setattr(pipeline.archive, "write_run", no_archive)
    summary = pipeline.run_step(ctx, conn, Step([2]))
    assert summary.errors == ["archive: bucket down"]
    assert fetch_run(conn, summary.run_id)["status"] == "partial"
