"""The probe may take a cache promotion down, never put one up (D65): the pure rule
(`recheck.probe_contradiction`), its config, and its wiring (`pipeline.run_probe_expiry`, the
`detect` step, the export's traceability guard, the posting queue)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import get_args

import pytest
import respx
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from escapadinha import cli, i18n_pt, pipeline, probe, run_path, site_data
from escapadinha.config import AppConfig, ProbeEngine, ProbeExpiryConfig
from escapadinha.models import Observation
from escapadinha.recheck import CACHE_SOURCES, probe_contradiction
from escapadinha.storage import db
from test_pipeline import REPO, ctx, mock_api, mock_links, seed_history, set_publishers  # noqa: F401

UTC = timezone.utc
NOW = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
H = timedelta(hours=1)
CFG = ProbeExpiryConfig()
GF, KAYAK = "google_flights", "kayak"
DEP, RET = date(2026, 12, 3), date(2026, 12, 6)


def trip_obs(source: str, price: float, at: datetime, *, oid: int = 0, airport: str | None = "BVA",
             last: datetime | None = None, seller: str | None = None,
             found_at: datetime | None = None, found_date: date | None = None) -> Observation:
    """OPO-PAR 03–06/12 at `source` (test data only)."""
    return Observation(source=source, origin="OPO", destination="PAR", origin_airport="OPO",
                       destination_airport=airport, departure_date=DEP, return_date=RET,
                       price=float(price), currency="EUR", airline="FR", flight_number=None,
                       transfers=0, return_transfers=0, deep_link=None, fetched_at=at,
                       last_seen_at=last or at, id=oid, gate=seller, found_at=found_at,
                       found_date=found_date)


def cache_deal(price: float = 50, *, source: str = "travelpayouts", airport: str | None = "BVA",
               found_at: datetime | None = NOW - 10 * H, found_date: date | None = None) -> Observation:
    return trip_obs(source, price, NOW - 10 * H, oid=1, airport=airport, found_at=found_at,
                    found_date=found_date)


def both(price_gf: float, price_kayak: float, at: datetime, **kw) -> list[Observation]:
    return [trip_obs(GF, price_gf, at, oid=101, **kw), trip_obs(KAYAK, price_kayak, at, oid=102, **kw)]


# --- the pure rule ----------------------------------------------------------------------------

def test_both_engines_well_above_the_cache_price_contradict_it():
    hit = probe_contradiction(cache_deal(50), both(62, 57, NOW - 2 * H), CFG, NOW)
    assert [(x.engine, x.observation_id, x.price, x.at) for x in hit.searches] == [
        (GF, 101, 62, NOW - 2 * H), (KAYAK, 102, 57, NOW - 2 * H)]
    assert hit.at == NOW - 2 * H
    # 13:00 UTC on 11/11 is 13:00 in Lisbon (winter time); no euro amount in the reason.
    assert hit.reason == ("o Google Flights e o Kayak mostraram esta viagem bem mais cara "
                          "(pesquisa de 11/11 às 13:00)")
    assert "€" not in hit.reason


def test_the_cheapest_option_of_a_search_decides_not_its_newest_row():
    """A search lists sellers: its price is the cheapest of them, whichever row came last."""
    readings = [trip_obs(GF, 54, NOW - 2 * H, oid=101, seller="Ryanair"),
                trip_obs(GF, 70, NOW - 2 * H, oid=103, seller="eDreams"),    # newest row, dearer
                trip_obs(KAYAK, 60, NOW - 2 * H, oid=102)]
    assert probe_contradiction(cache_deal(50), readings, CFG, NOW) is None   # 54: +8 %, +4 €


def test_a_row_seen_again_is_a_second_search_at_its_last_sighting():
    """The dedup keeps one row for the same price seen again the same day; its last sighting is
    the repeat's search time, so the newest search is that one."""
    old = NOW - 20 * H
    readings = [trip_obs(GF, 60, old, oid=101, last=NOW - H),
                trip_obs(KAYAK, 60, old, oid=102, last=NOW - H)]
    hit = probe_contradiction(cache_deal(50, found_at=NOW - 30 * H), readings, CFG, NOW)
    assert [x.at for x in hit.searches] == [NOW - H, NOW - H]


def test_the_newest_search_decides_an_older_dearer_one_does_not():
    readings = both(70, 70, NOW - 6 * H) + [trip_obs(GF, 52, NOW - H, oid=103)]
    assert probe_contradiction(cache_deal(50), readings, CFG, NOW) is None


@pytest.mark.parametrize("deal, readings", [
    pytest.param(cache_deal(50), [], id="no reading"),
    pytest.param(cache_deal(50), [trip_obs(GF, 70, NOW - H, oid=101)], id="one engine only"),
    pytest.param(cache_deal(50), [trip_obs(GF, 70, NOW - H, oid=101),
                                  trip_obs(KAYAK, 70, NOW - 13 * H, oid=102)], id="one engine too old"),
    pytest.param(cache_deal(50, found_at=NOW - H), both(70, 70, NOW - 2 * H),
                 id="searched before the price was found"),
    pytest.param(cache_deal(50, found_at=None, found_date=NOW.date()),
                 both(70, 70, NOW - 16 * H + timedelta(minutes=1)),
                 id="searched before the found day (no exact time)"),
    pytest.param(cache_deal(50, found_at=None), both(70, 70, NOW - H), id="found time unknown"),
    pytest.param(cache_deal(50), both(70, 70, NOW - H, airport="CDG"), id="another airport"),
    pytest.param(cache_deal(50, airport=None), both(70, 70, NOW - H, airport=None),
                 id="the deal's airport unknown"),
    pytest.param(cache_deal(50), both(54.9, 70, NOW - H), id="one engine below the % margin"),
    pytest.param(cache_deal(30), both(34, 40, NOW - H), id="one engine below the euro floor"),
    pytest.param(cache_deal(50, source="ryanair"), both(70, 70, NOW - H), id="an airline source"),
    pytest.param(cache_deal(50, source=GF), both(70, 70, NOW - H), id="a comparison source"),
    pytest.param(cache_deal(50), both(70, 70, NOW + H), id="a search after now"),
])
def test_the_rule_never_fires_without_fresh_dearer_searches_of_every_engine(deal, readings):
    assert probe_contradiction(deal, readings, CFG, NOW) is None


def test_the_margins_are_inclusive_and_the_found_day_counts_from_its_start():
    found_day = cache_deal(50, found_at=None, found_date=NOW.date())
    assert probe_contradiction(found_day, both(55, 55, NOW - H), CFG, NOW) is not None  # 10 %, 5 €
    assert probe_contradiction(cache_deal(50, found_at=NOW - 20 * H), both(70, 70, NOW - 12 * H),
                               CFG, NOW) is not None                    # exactly 12 h old


def test_disabled_or_a_single_engine_by_config():
    readings = [trip_obs(GF, 70, NOW - H, oid=101)]
    assert probe_contradiction(cache_deal(50), both(70, 70, NOW - H),
                               ProbeExpiryConfig(enabled=False), NOW) is None
    hit = probe_contradiction(cache_deal(50), readings, ProbeExpiryConfig(engines=[GF]), NOW)
    assert hit.reason.startswith("o Google Flights mostrou esta viagem bem mais cara")


def test_the_cache_is_the_only_source_the_probe_may_contradict():
    assert CACHE_SOURCES == {"travelpayouts"}
    assert not CACHE_SOURCES & (pipeline.COMPARISON_SOURCES | {"ryanair"})


def test_the_reason_names_the_engines_and_the_lisbon_search_time():
    summer = datetime(2026, 7, 1, 13, 39, tzinfo=UTC)          # 14:39 in Lisbon
    assert i18n_pt.probe_contradiction(["Google Flights", "Kayak"], summer) == (
        "o Google Flights e o Kayak mostraram esta viagem bem mais cara (pesquisa de 01/07 às 14:39)")
    assert i18n_pt.probe_contradiction(["Kayak"], summer) == (
        "o Kayak mostrou esta viagem bem mais cara (pesquisa de 01/07 às 14:39)")


# --- config -------------------------------------------------------------------------------

def test_the_config_block_and_its_validation():
    config = yaml.safe_load((REPO / "config.yaml").read_text("utf-8"))
    cfg = AppConfig.model_validate(config).detector.probe_expiry
    assert (cfg.enabled, cfg.min_rise_pct, cfg.min_rise_eur, cfg.max_age_hours, cfg.engines) == (
        True, 0.10, 5, 12, [GF, KAYAK])
    assert set(get_args(ProbeEngine)) == probe.SOURCES       # every engine name is a probe source
    for bad in ({"engines": []}, {"engines": [GF, GF]}, {"engines": ["skyscanner"]},
                {"min_rise_pct": 0}, {"min_rise_eur": -1}, {"max_age_hours": 0}):
        with pytest.raises(ValidationError):
            ProbeExpiryConfig(**bad)


# --- the pipeline -------------------------------------------------------------------------

def store(conn, source: str, rows: list[Observation], scope: str = "full") -> list[int]:
    """`rows` stored under one run row of `source`; their ids, in order."""
    run_id = db.start_run(conn, source, scope=scope)
    db.insert_observations(conn, run_id, rows)
    db.finish_run(conn, run_id, status="ok", n_requests=0, n_observations=len(rows), error=None)
    return [conn.execute("SELECT id FROM price_observations WHERE dedup_key = ?",
                         (r.dedup_key,)).fetchone()[0] for r in rows]


def on_trip(o: Observation, source: str, price: float, at: datetime, **kw) -> Observation:
    """Another source's offer of `o`'s trip, seen and found at `at` (test data only)."""
    return Observation(**{
        "source": source, "origin": o.origin, "destination": o.destination,
        "origin_airport": o.origin, "destination_airport": o.destination_airport,
        "departure_date": o.departure_date, "return_date": o.return_date, "price": float(price),
        "currency": "EUR", "airline": o.airline, "flight_number": None, "transfers": 0,
        "return_transfers": 0, "deep_link": None, "fetched_at": at, "found_date": at.date(),
        "found_at": at, **kw})


def probe_rows(conn, o: Observation, prices: dict[str, float], at: datetime) -> list[int]:
    """Each engine's search of `o`'s trip at `at`, as `run_probe_import` stores them."""
    return store(conn, "probe", [on_trip(o, engine, price, at) for engine, price in prices.items()],
                 scope="probe")


def deal_on(conn, observation_id: int, status: str) -> int:
    deal_id = db.insert_deal(conn, observation_id=observation_id, rule="median",
                             baseline_median=100, sample_size=25, discount_pct=0.4, threshold=0.3)
    db.set_deal_status(conn, deal_id, status)
    return deal_id


def detected_deal(ctx, conn) -> tuple[int, Observation]:
    """The 58 € LIS-LON cache offer (LGW, 06–09/11, found yesterday) detected as a promotion."""
    seed_history(conn, days=25, price=100)
    mock_api()
    pipeline.run_collect(ctx, conn)
    _, results = pipeline.run_detect(ctx, conn)
    [deal_id] = {r.route: r for r in results}["LIS-LON"].deal_ids
    return deal_id, db.get_deal(conn, deal_id)[1]


@respx.mock
def test_run_probe_expiry_takes_down_approved_and_waiting_cache_deals_only(ctx):
    conn = pipeline.open_db(ctx)
    approved, obs = detected_deal(ctx, conn)
    db.record_review(conn, approved, status="approved", note=None)     # on the site
    promotion = db.get_deal(conn, approved)[0].promotion_id
    now = db.utcnow()
    # Another cache offer of the trip (another carrier) awaiting review, and the airline's own
    # fare of it (D47), both at prices the probe contradicts as much.
    [cache_id] = store(conn, "travelpayouts", [
        on_trip(obs, "travelpayouts", 60, now - 5 * H, airline="TP", deep_link="https://x/tp")])
    [airline_id] = store(conn, "ryanair", [
        on_trip(obs, "ryanair", 58, now - 5 * H, flight_number="FR1",
                deep_link="https://www.ryanair.com/x")])
    waiting = deal_on(conn, cache_id, "rendered")
    airline = deal_on(conn, airline_id, "rendered")
    probe_rows(conn, obs, {GF: 75, KAYAK: 72}, now - 2 * H)
    before = run_path.fingerprint(ctx, conn, now)

    expired = pipeline.run_probe_expiry(ctx, conn, now)

    assert sorted(d.id for d, _, _ in expired) == sorted([approved, waiting])
    for deal_id in (approved, waiting):
        d = db.get_deal(conn, deal_id)[0]
        assert (d.status, d.expired_kind, d.expired_at) == ("expired", "contradicted", now)
        assert d.expired_reason.startswith("o Google Flights e o Kayak mostraram esta viagem")
    assert db.get_deal(conn, airline)[0].status == "rendered"   # the seller's own price stands
    closed = db.get_promotion(conn, promotion)
    assert closed.closed_at == now and closed.closed_reason.startswith("a data expirou: o Google")
    after = run_path.fingerprint(ctx, conn, now)
    assert before["promotions"] != after["promotions"] and before["site_data"] != after["site_data"]
    assert pipeline.run_probe_expiry(ctx, conn, now) == []      # an expiry is final


@respx.mock
def test_run_probe_expiry_needs_both_engines_and_the_config(ctx):
    conn = pipeline.open_db(ctx)
    deal_id, obs = detected_deal(ctx, conn)
    now = db.utcnow()
    probe_rows(conn, obs, {GF: 75}, now - H)                    # Kayak paused: no row of it
    assert pipeline.run_probe_expiry(ctx, conn, now) == []
    probe_rows(conn, obs, {KAYAK: 72}, now - H)
    ctx.config.detector.probe_expiry.enabled = False
    assert pipeline.run_probe_expiry(ctx, conn, now) == []
    ctx.config.detector.probe_expiry.enabled = True
    [(d, _, reason)] = pipeline.run_probe_expiry(ctx, conn, now)
    assert d.id == deal_id and d.status == "expired"


@respx.mock
def test_the_detect_step_expires_a_deal_it_just_detected_when_the_probe_contradicts_it(ctx, monkeypatch):
    """`detect` runs the rule after the re-evaluation, before the full path's automatic
    approval: a new deal the probe already saw dearer never reaches the site."""
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    mock_api()
    pipeline.run_collect(ctx, conn)
    offer = next(o for o in db.observations_seen_since(conn, db.latest_completed_run_id(conn))
                 if o.route_key == "LIS-LON" and o.price == 58)
    probe_rows(conn, offer, {GF: 80, KAYAK: 74}, db.utcnow() - H)
    conn.close()
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    out = CliRunner().invoke(cli.app, ["detect"], catch_exceptions=False).output
    conn = pipeline.open_db(ctx)
    [(deal, obs)] = db.deals_with_status(conn, *db.OPEN_STATUSES, "expired")
    assert obs.id == offer.id and (deal.status, deal.expired_kind) == ("expired", "contradicted")
    assert f"deal {deal.id} LIS-LON" in out and "desmentida pela sonda" in out


def test_an_exported_contradicted_promotion_passes_the_traceability_guard(ctx, tmp_path):
    from test_site_data import read, untraced_prices
    from test_traceability import build_scenario, prices_in
    with respx.mock:
        mock_links()
        conn = pipeline.open_db(ctx)
        s = build_scenario(ctx, conn)
        obs = db.get_deal(conn, s.live_deal)[1]
        probe_rows(conn, obs, {GF: 75, KAYAK: 70}, db.utcnow() - H)
        [(d, _, reason)] = pipeline.run_probe_expiry(ctx, conn)
        assert d.id == s.live_deal and prices_in(reason) == []
        out = tmp_path / "site-data"
        site_data.export_site_data(ctx, conn, out)
    promo = next(p for p in read(out, "promotions.json")["promotions"] if p["id"] == s.live_deal)
    assert not promo["live"] and promo["booking_link"] is None
    assert promo["expired"]["reason"] == reason
    assert promo["also_seen"] == []          # the comparison is a live page's only
    assert untraced_prices(ctx, conn, out) == []


@respx.mock
def test_a_queued_post_of_a_contradicted_promotion_is_cancelled(ctx):
    from test_posting import APPLIED, approved, publish
    set_publishers(ctx, instagram="dry-run", telegram="dry-run")
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    obs = db.get_deal(conn, deal_id)[1]
    probe_rows(conn, obs, {GF: 75, KAYAK: 72}, APPLIED - H)
    [(_, _, reason)] = pipeline.run_probe_expiry(ctx, conn, APPLIED)
    done, _ = publish(ctx, conn, APPLIED)
    assert sorted(done) == [(deal_id, "instagram", "cancelled"), (deal_id, "telegram", "cancelled")]
    assert {p.reason for p in db.posts(conn)} == {f"A promoção expirou: a data expirou: {reason}."}
