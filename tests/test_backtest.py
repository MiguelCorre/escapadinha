"""The detector backtest (D44): a replay over a synthetic database, run by run, judged by the
detector and the recheck themselves, never writing the file it reads."""

from datetime import date, datetime, timedelta, timezone

import pytest

from escapadinha import backtest, routes
from escapadinha.config import DetectorConfig
from escapadinha.models import Observation
from escapadinha.storage import db
from test_pipeline import ctx  # noqa: F401

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
DEC = date(2026, 12, 1)


def offer(route: str, dep: date, price: float, *, found: date, nights: int = 4) -> Observation:
    origin, destination = route.split("-")
    return Observation(source="test", origin=origin, destination=destination,
                       origin_airport=origin, destination_airport=destination,
                       departure_date=dep, return_date=dep + timedelta(days=nights), price=price,
                       currency="EUR", airline="TP", flight_number="1", transfers=0,
                       return_transfers=0, deep_link=None, fetched_at=T0, raw_json="{}",
                       found_date=found)


def run(conn, at: datetime, offers: list[Observation]) -> int:
    """One completed collection run at `at` that returned `offers` (repeats bump last_run_id)."""
    run_id = db.start_run(conn, "test")
    conn.execute("UPDATE fetch_runs SET started_at = ? WHERE id = ?", (db._ts(at), run_id))
    db.insert_observations(conn, run_id, offers)
    db.finish_run(conn, run_id, status="ok", n_requests=1, n_observations=len(offers), error=None)
    return run_id


def baseline_offers(route: str, days: int, price: float, *, before: date) -> list[Observation]:
    """`days` daily lows at `price`, two departure dates a day, found on the days before `before`."""
    return [offer(route, DEC + timedelta(days=i + k), price + 20 * k,
                  found=before - timedelta(days=i + 1))
            for i in range(days) for k in (0, 1)]


@pytest.fixture
def copy(ctx, tmp_path):
    """A database with 12 baseline days for LIS-LON and OPO-PAR, then three runs on 14/10:
    run A finds a 60 € new low on LIS-LON (held) and a 65 € OPO-PAR fare that is cheap but not a
    new low; run B (2 h later) still has them; run C (6 h later) no longer offers the LIS-LON
    trip at 60 €."""
    import escapadinha.pipeline as pipeline
    conn = pipeline.open_db(ctx)
    day = date(2026, 10, 14)
    history = (baseline_offers("LIS-LON", 12, 100, before=day - timedelta(days=3))
               + baseline_offers("OPO-PAR", 12, 100, before=day - timedelta(days=3))
               + [offer("OPO-PAR", DEC + timedelta(days=20), 62, found=day - timedelta(days=8))])
    at = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)
    run(conn, at, history)                                             # run 1: the history
    cheap_lon = offer("LIS-LON", DEC + timedelta(days=10), 60, found=day)
    cheap_par = offer("OPO-PAR", DEC + timedelta(days=11), 65, found=day)
    a = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
    run(conn, a, history + [cheap_lon, cheap_par])                     # run 2
    run(conn, a + timedelta(hours=2), history + [cheap_lon, cheap_par])  # run 3
    run(conn, a + timedelta(hours=6), history + [cheap_par])           # run 4: 60 € gone
    conn.commit()
    conn.close()
    return backtest.open_copy(ctx.db_path), ctx


def test_the_copy_is_read_only_and_migrated_in_memory(copy):
    conn, ctx = copy
    import hashlib
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    # The file is untouched: opening a copy, replaying and migrating leave its bytes as they were.
    before = hashlib.sha256(ctx.db_path.read_bytes()).hexdigest()
    again = backtest.open_copy(ctx.db_path)
    again.execute("UPDATE fetch_runs SET status = 'failed'")           # only the copy changes
    again.commit()
    assert hashlib.sha256(ctx.db_path.read_bytes()).hexdigest() == before
    assert len(backtest.completed_runs(backtest.open_copy(ctx.db_path))) == 4


def test_runs_are_selected_by_id_or_by_the_days_before_the_latest(copy):
    conn, _ = copy
    runs = backtest.completed_runs(conn)
    assert [r.id for r in runs] == [1, 2, 3, 4]
    assert [r.id for r in backtest.select_runs(runs, ids=(2, 3))] == [2, 3]
    # The latest run's day (14/10) is never complete: `days` reaches back from the day before.
    assert backtest.select_runs(runs, days=3) == []
    assert [r.id for r in backtest.select_runs(runs, days=4)] == [1]


def replay(copy, cfg: DetectorConfig, runs=(2, 3, 4)):
    conn, ctx = copy
    watched = routes.all_routes(conn, ctx.config.routes)
    all_runs = backtest.completed_runs(conn)
    chosen = backtest.select_runs(all_runs, ids=(runs[0], runs[-1]))
    return backtest.replay(conn, watched, [backtest.RuleSet("test", cfg)], chosen,
                           all_runs=all_runs)[0]


def test_replay_flags_each_candidate_once_and_judges_its_next_24_hours(copy):
    lax = DetectorConfig(require_new_low=False)
    out = replay(copy, lax)
    assert [(c.run_id, c.route, c.price) for c in out.candidates] == [
        (2, "LIS-LON", 60.0), (2, "OPO-PAR", 65.0)]                  # never flagged twice
    lon, par = out.candidates
    assert (lon.days, lon.typical_low, lon.confidence, lon.new_low) == (12, 100, "medium", True)
    assert lon.discount == pytest.approx(0.4)
    # Run 4 (6 h later) offers the trip only at the baseline's 100 €: the recheck expires it.
    assert lon.expired_within_24h is True and lon.expiry == "run 4: o preço subiu para 100 €"
    assert par.new_low is False                                        # 62 € was seen before
    assert par.expired_within_24h is False and par.expiry is None
    s = out.summary()
    assert (s["candidates"], s["routes"], s["expired_24h"], s["judged"]) == (2, 2, 1, 2)
    assert (s["new_lows"], s["new_low_known"], s["days"]) == (1, 2, 1)
    assert s["confidence"] == {"medium": 2}
    assert s["low_prices_per_run"] == pytest.approx((2 + 2 + 1) / 3)
    assert s["distinct_low_prices"] == 2 and out.summary("europe")["candidates"] == 2
    # Hindsight: against everything stored, without the candidate's own found day, both hold.
    assert (lon.typical_low_today, lon.holds_today) == (100, True)
    assert par.holds_today is True and par.discount_today == pytest.approx(0.35)


def test_the_new_low_rule_drops_the_cheap_day_that_was_seen_cheaper_before(copy):
    out = replay(copy, DetectorConfig(require_new_low=True))
    assert [(c.route, c.new_low) for c in out.candidates] == [("LIS-LON", True)]
    nothing = replay(copy, DetectorConfig(), runs=(4, 4))               # 60 € gone, 65 € taken? no:
    assert nothing.candidates == [] or all(c.route == "OPO-PAR" for c in nothing.candidates)


def test_a_run_with_no_later_run_within_24_hours_is_not_judged(copy):
    out = replay(copy, DetectorConfig(require_new_low=False), runs=(4, 4))
    [par] = out.candidates
    assert (par.route, par.expired_within_24h, par.expiry) == ("OPO-PAR", None, None)
    assert out.summary()["judged"] == 0


def test_rule_set_presets_and_the_report(copy):
    base = DetectorConfig()
    names = [rs.name for rs in backtest.rule_sets(base, "data-reliability")]
    assert names[:2] == ["before (D3/D24)", "min 7 days"] and len(names) == 5
    d44 = backtest.rule_sets(base, "d44")
    assert [rs.name for rs in d44][-2:] == ["D44 (configured)", "D44, high confidence for low prices"]
    assert d44[-2].cfg == base
    before = backtest.rule_sets(base, "data-reliability")[0].cfg
    assert (before.min_dates_per_day, before.min_baseline_days, before.require_new_low) == (1, 4, False)
    with pytest.raises(ValueError):
        backtest.rule_sets(base, "nope")
    out = replay(copy, DetectorConfig(require_new_low=False))
    text = backtest.markdown([out], candidates=True)
    assert "| test | 2 (2) | 2.00 | 1/2 (50%) | 2/2 (100%) | 1/2 (50%) | medium 2 |" in text
    assert "| test | europe | 2 |" in text
    assert "| 2 (14/10 09:00) | LIS-LON | 11/12–15/12 | 60 € | 100 € (12 d, CV 0.00) | 40% | medium | yes | expired: run 4:" in text
    data = backtest.to_json([out])
    assert data["rule_sets"][0]["summary"]["candidates"] == 2
    assert data["rule_sets"][0]["candidates"][0]["departure_date"] == "2026-12-11"
    assert backtest.markdown([]) == "No runs to replay.\n"


def test_the_state_of_every_route_month(copy):
    conn, ctx = copy
    watched = routes.all_routes(conn, ctx.config.routes)
    data = backtest.state(conn, watched, DetectorConfig())
    months = {(m["route"], m["month"]): m for m in data["route_months"]}
    lon = months[("LIS-LON", "2026-12")]
    assert (lon["days"], lon["median"], lon["mature"], lon["mature_promo"]) == (12, 100, True, True)
    assert lon["confidence"] == "medium" and lon["days_without_lead_filter"] == 12
    text = backtest.state_markdown(data, DetectorConfig())
    assert "| >= 10 days | 2 | 2 |" in text and "| LIS-LON | 2026-12 | 12 (12) | 100 € | 0.00 |" in text


def test_the_script_runs_on_a_copy(copy, capsys):
    import importlib.util
    from pathlib import Path
    conn, ctx = copy
    spec = importlib.util.spec_from_file_location(
        "backtest_detector", Path(__file__).parent.parent / "scripts" / "backtest_detector.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.REPO = ctx.root                                              # the test's config.yaml
    assert module.main([str(ctx.db_path), "--runs", "2-4", "--preset", "d44", "--state"]) == 0
    out = capsys.readouterr().out
    assert "| D44 (configured) (new low + lead time, as config.yaml) | 1 (1) |" in out
    assert "Route-months at" in out
    assert module.main([str(ctx.db_path), "--runs", "9-9"]) == 1
