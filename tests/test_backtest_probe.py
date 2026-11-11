"""The probe against the cache's deals (backtest, 2026-11-11): the truth at a moment, the rules'
first firing, the grid with its control set, and the loader over a database copy. The rules
and the truth are pure over `CacheDeal`s built here; one test loads them from a small database."""

from datetime import date, datetime, timedelta, timezone

from escapadinha import backtest
from escapadinha.backtest import CacheDeal, ProbeRule, Seen
from escapadinha.models import Observation
from escapadinha.storage import db
from test_pipeline import ctx  # noqa: F401

DET = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)      # detection, at the pinned clock
H = timedelta(hours=1)
TOL = 0.05


def seen(source: str, price: float, at: datetime, *, last: datetime | None = None,
         airline: str = "FR", airport: str = "STN", found: datetime | None = None,
         oid: int = 0) -> Seen:
    last = last or at
    return Seen(source=source, price=price, first=at, last=last, first_usable=at + 0.5 * H,
                last_usable=last + 0.5 * H, observation_id=oid, airline=airline, airport=airport,
                nonstop=True, found=found)


def deal(*, probe=(), airline_seen=(), cache_seen=(), price: float = 50.0,
         expired_at: datetime | None = None, kind: str | None = None,
         last_seen_price: float | None = None, found: datetime | None = None,
         approved: bool = True, deal_id: int = 1) -> CacheDeal:
    end = expired_at or DET + 72 * H
    return CacheDeal(
        deal_id=deal_id, route="LIS-LON", airport="STN", departure_date=date(2026, 11, 20),
        return_date=date(2026, 11, 23), price=price, airline="FR", seller="Kiwi.com",
        nonstop=True, with_baggage=False, source="travelpayouts", found=found or DET - 2 * H,
        detected_at=DET, approved_at=DET if approved else None,
        approver="rules" if approved else "none", status="expired" if expired_at else "approved",
        expired_at=expired_at, expired_kind=kind, last_seen_price=last_seen_price,
        approximate=False, end=end, rechecks=0, probe=tuple(probe),
        airline_seen=tuple(airline_seen), cache_seen=tuple(cache_seen))


GF, KAYAK = "google_flights", "kayak"


def test_each_engine_search_is_its_cheapest_option_and_a_row_seen_twice_is_two_searches():
    d = deal(probe=[seen(GF, 60, DET + H, oid=1), seen(GF, 58, DET + H, oid=2),
                    seen(KAYAK, 59, DET + H, last=DET + 9 * H, oid=3)])
    assert [(x.engine, x.price, x.observation_id) for x in d.searches()] == [
        (GF, 58, 2), (KAYAK, 59, 3), (KAYAK, 59, 3)]
    assert [x.at for x in d.searches(KAYAK)] == [DET + H, DET + 9 * H]
    assert d.compared and d.searches(KAYAK)[1].usable_at == DET + 9.5 * H


def test_the_truth_prefers_the_airline_then_the_cache_then_the_expiry():
    ryanair = [seen("ryanair", 51, DET, last=DET + 10 * H, oid=7),
               seen("ryanair", 70, DET + 20 * H, oid=8),
               seen("ryanair", 40, DET, airport="LTN", oid=9)]                 # another airport
    d = deal(airline_seen=ryanair)
    assert backtest.truth_at(d, DET + 5 * H, TOL).label == "real (airline)"   # 51 within 5 %
    t = backtest.truth_at(d, DET + 22 * H, TOL)                                 # 2 h from the 70
    assert (t.verdict, t.basis, t.detail) == ("stale", "airline", "ryanair 70 € (obs 8)")
    assert backtest.truth_at(d, DET + 15 * H, TOL).verdict is None              # nothing near
    refound = deal(cache_seen=[seen("travelpayouts", 52, DET, found=DET + 6 * H, oid=5)])
    assert backtest.truth_at(refound, DET + 3 * H, TOL).label == "real (cache)"
    assert backtest.truth_at(refound, DET + 7 * H, TOL).verdict is None         # found before
    rose = deal(expired_at=DET + 30 * H, kind="gone", last_seen_price=60)
    assert backtest.truth_at(rose, DET + 10 * H, TOL).label == "stale (rose)"
    assert backtest.truth_at(rose, DET + 2 * H, TOL).verdict is None            # 28 h before
    timer = deal(expired_at=DET + 30 * H, kind="gone", last_seen_price=50)
    assert backtest.truth_at(timer, DET + 10 * H, TOL).label == "stale (timer)"
    superseded = deal(expired_at=DET + 30 * H, kind="superseded")
    assert backtest.truth_at(superseded, DET + 10 * H, TOL).verdict is None


def test_a_rule_fires_at_the_first_import_where_its_engines_are_fresh_and_higher():
    probe = [seen(GF, 52, DET + 2 * H), seen(KAYAK, 51, DET + 2 * H),          # +4 %, +2 %
             seen(GF, 60, DET + 10 * H), seen(KAYAK, 54, DET + 10 * H),        # +20 %, +8 %
             seen(KAYAK, 58, DET + 20 * H)]                                     # +16 %
    d = deal(probe=probe, airline_seen=[seen("ryanair", 59, DET + 9 * H, last=DET + 30 * H)])
    gf = backtest.first_fire(d, ProbeRule(0.10, 5, 12, GF), TOL)
    assert (gf.at, gf.hours_early, gf.truth.label) == (DET + 10.5 * H, 61.5, "stale (airline)")
    assert gf.approved and gf.open and [x.price for x in gf.searches] == [60]   # open: to the end
    both = backtest.first_fire(d, ProbeRule(0.10, 5, 12, "both"), TOL)
    assert both.at == DET + 20.5 * H and [x.price for x in both.searches] == [60, 58]
    assert backtest.first_fire(d, ProbeRule(0.10, 5, 6, "both"), TOL) is None   # GF too old by then
    assert backtest.first_fire(d, ProbeRule(0.10, 15, 48, "any"), TOL) is None  # never 15 € above
    anyone = backtest.first_fire(d, ProbeRule(0.05, 0, 12, "any"), TOL)
    assert anyone.at == DET + 10.5 * H and [x.engine for x in anyone.searches] == [GF, KAYAK]


def test_searches_older_than_the_price_or_at_another_airport_do_not_count_unless_asked():
    probe = [seen(GF, 70, DET - 4 * H), seen(KAYAK, 70, DET - 4 * H),           # before the price
             seen(GF, 65, DET + 2 * H, airport="LTN"), seen(KAYAK, 66, DET + 2 * H, airport="LTN")]
    d = deal(probe=probe, found=DET - 2 * H)
    assert backtest.decision_times(d) == [DET, DET + 2.5 * H]
    assert backtest.first_fire(d, ProbeRule(0.10, 5, 12, "both"), TOL).at == DET + 2.5 * H
    assert backtest.first_fire(d, ProbeRule(0.10, 5, 12, "both", same_airport=True), TOL) is None
    old = backtest.first_fire(d, ProbeRule(0.10, 5, 12, "both", newer_than_price=False,
                                           same_airport=True), TOL)
    assert old.at == DET and [x.price for x in old.searches] == [70, 70]


def test_the_grid_counts_false_positives_on_the_cache_deals_and_on_the_control_set():
    real = deal(deal_id=1, probe=[seen(GF, 60, DET + H), seen(KAYAK, 60, DET + H)],
                cache_seen=[seen("travelpayouts", 50, DET, found=DET + 3 * H)])
    stale = deal(deal_id=2, probe=[seen(GF, 70, DET + H), seen(KAYAK, 69, DET + H)],
                 airline_seen=[seen("ryanair", 69, DET, last=DET + 5 * H)])
    unknown = deal(deal_id=3, probe=[seen(GF, 52, DET + H), seen(KAYAK, 50, DET + H)])
    live = deal(deal_id=9, probe=[seen(GF, 60, DET + H), seen(KAYAK, 60, DET + H)],
                expired_at=DET + 20 * H, kind="gone")                       # fired 18.5 h early
    concordant = deal(deal_id=10, probe=[seen(GF, 60, DET + H), seen(KAYAK, 60, DET + H)],
                      expired_at=DET + 2 * H, kind="gone")                  # its source agreed
    rules = [ProbeRule(0.10, 5, 12, "both"), ProbeRule(0.03, 0, 12, GF)]
    tight, loose = backtest.probe_grid([real, stale, unknown], rules, TOL, [live, concordant])
    s = tight.summary({2})
    assert (s["fired_ids"], s["real"], s["stale_airline"], s["unknown"]) == ([1, 2], [1], [2], [])
    assert s["control_fired"] == [9, 10] and s["control_false"] == [9]
    assert s["caught_stale_known"] == [2] and s["approved_when_fired"] == 2
    assert loose.summary(set())["unknown"] == [3]
    assert backtest.stale_known([real, stale, unknown], TOL) == {2}
    assert len(backtest.grid_rules()) == 5 * 4 * 4 * 3 * 2
    assert len(backtest.default_rules()) == 480 + 5 * 4 * 2 * 3


def test_the_report_pairs_the_engines_and_prints_every_part():
    d = deal(probe=[seen(GF, 60, DET + H), seen(KAYAK, 57, DET + 1.2 * H)],
             airline_seen=[seen("ryanair", 59, DET, last=DET + 5 * H)])
    control = deal(deal_id=5, probe=[seen(GF, 50, DET + H)])
    data = backtest.probe_report([d, deal(deal_id=2)], [ProbeRule(0.10, 5, 12, GF)], TOL,
                                 controls=[control])
    assert (data["deals"], data["compared"], data["stale_known"]) == (2, 1, [1])
    assert [(p["google_flights"], p["kayak"]) for p in data["pairs"]] == [(60, 57)]
    assert data["control"]["searches"] == 1 and data["control"]["at_least_5"] == 0
    row = data["deal_rows"][0]
    assert row["searches"] == {GF: 1, KAYAK: 1} and row["airline_prices"] == [59]
    text = backtest.probe_markdown(data)
    assert "compared (a probe search of the trip while the deal was open): 1" in text
    assert "| 1 | google_flights | – | FR, STN | 60 € | +10 € (+20%) |" in text
    assert "| trip | google_flights | 12 | ≥10%, ≥5 € | 1 | 1 | 1 |" in text
    assert "Control: 1 deals from `travelpayouts`" in text


def _observation(source: str, price: float, at: datetime, *, airport: str = "STN",
                 gate: str | None = None, found_at: datetime | None = None) -> Observation:
    return Observation(source=source, origin="LIS", destination="LON", origin_airport="LIS",
                       destination_airport=airport, departure_date=date(2026, 11, 20),
                       return_date=date(2026, 11, 23), price=price, currency="EUR", airline="FR",
                       flight_number=None, transfers=0, return_transfers=0, deep_link=None,
                       fetched_at=at, raw_json="{}", found_date=at.date(), gate=gate,
                       found_at=found_at)


def _run(conn, source: str, scope: str, at: datetime, offers: list[Observation]) -> int:
    run_id = db.start_run(conn, source, scope)
    conn.execute("UPDATE fetch_runs SET started_at = ? WHERE id = ?", (db._ts(at), run_id))
    db.insert_observations(conn, run_id, offers)
    db.finish_run(conn, run_id, status="ok", n_requests=1, n_observations=len(offers), error=None)
    return run_id


def test_the_loader_reads_a_cache_deal_and_its_trip_at_every_source(ctx, capsys):  # noqa: F811
    import escapadinha.pipeline as pipeline
    conn = pipeline.open_db(ctx)
    cached = _observation("travelpayouts", 50, DET - H, gate="Kiwi.com", found_at=DET - 2 * H)
    _run(conn, "travelpayouts", "full", DET - H, [cached])
    _run(conn, "travelpayouts", "full", DET + 10 * H, [cached])
    _run(conn, "ryanair", "airlines", DET + 3 * H, [_observation("ryanair", 64.98, DET + 3 * H)])
    _run(conn, "probe", "probe", DET + 4 * H,
         [_observation("google_flights", 65, DET + 3.5 * H, gate="Ryanair"),
          _observation("kayak", 64, DET + 3.6 * H)])
    obs_id = conn.execute("SELECT id FROM price_observations WHERE source = 'travelpayouts'").fetchone()[0]
    deal_id = db.insert_deal(conn, observation_id=obs_id, rule="median", baseline_median=80,
                             sample_size=12, discount_pct=0.375, threshold=0.3, confidence="high")
    conn.execute("UPDATE deals SET detected_at = ?, status = 'approved', reviewed_at = ?, review_note = ? "
                 "WHERE id = ?", (db._ts(DET), db._ts(DET), "aprovação automática (D46)", deal_id))
    conn.commit()
    conn.close()
    copy = backtest.open_copy(ctx.db_path)
    (d,) = backtest.cache_deals(copy)
    assert (d.deal_id, d.route, d.airport, d.price, d.seller, d.approver) == (
        deal_id, "LIS-LON", "STN", 50, "Kiwi.com", "rules")
    assert d.found == DET - 2 * H and d.end == DET + 10 * H and d.rechecks == 1 and d.open
    assert [(x.engine, x.price, x.usable_at) for x in d.searches()] == [
        ("google_flights", 65, DET + 4 * H), ("kayak", 64, DET + 4 * H)]
    assert [s.price for s in d.airline_seen] == [64.98] and d.cache_seen == ()
    fire = backtest.first_fire(d, ProbeRule(0.10, 5, 12, "both"), TOL)
    assert fire.at == DET + 4 * H and fire.truth.label == "stale (airline)"
    assert backtest.cache_deals(copy, source="ryanair") == []

    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "backtest_detector", Path(__file__).parent.parent / "scripts" / "backtest_detector.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.REPO = ctx.root
    assert module.main([str(ctx.db_path), "--preset", "probe"]) == 0
    out = capsys.readouterr().out
    assert "Cache deals (source `travelpayouts`): 1; compared" in out
    assert "| trip | both | 12 | ≥10%, ≥5 € | 1 | 1 | 1 |" in out
