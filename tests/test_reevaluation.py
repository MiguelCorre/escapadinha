"""Deals awaiting review judged again against their month's current typical low on every run
(D40): through `pipeline.run_reevaluate` and the run itself, on the local store."""

from datetime import date, timedelta

import respx
from typer.testing import CliRunner

from escapadinha import cli, pipeline
from escapadinha.models import Observation
from escapadinha.storage import db
from test_pipeline import ctx, mock_api, seed_history  # noqa: F401

NOW = db.utcnow()


def offer(route: str, departure: date, nights: int, price: float, *, ago: int) -> Observation:
    """A nonstop offer found `ago` days before NOW (test data only)."""
    origin, destination = route.split("-")
    return Observation(source="test", origin=origin, destination=destination,
                       origin_airport=origin, destination_airport=destination,
                       departure_date=departure, return_date=departure + timedelta(days=nights),
                       price=price, currency="EUR", airline="TP", flight_number="1", transfers=0,
                       return_transfers=0, deep_link=None, fetched_at=NOW - timedelta(days=ago),
                       raw_json="{}")


def history(conn, route: str, month: date, *, days: int, price: float) -> None:
    """`days` past daily lows of `route` for departures in `month`, two departure dates a day
    (so each day counts, D40), all older than the freshness window."""
    run_id = db.start_run(conn, "test")
    db.insert_observations(conn, run_id, [
        offer(route, month + timedelta(days=i + k), 4, price + i % 3 + 20 * k, ago=i + 4)
        for i in range(days) for k in (0, 1)])
    db.finish_run(conn, run_id, status="ok", n_requests=0, n_observations=2 * days, error=None)


def deal(conn, route: str, departure: date, price: float, *, status: str, days: int,
         median: float) -> int:
    """A deal on a fresh offer, stored as the detector of its day stored it (`days` daily lows,
    `median` their typical low)."""
    o = offer(route, departure, 5, price, ago=0)
    run_id = db.start_run(conn, "test")
    db.insert_observations(conn, run_id, [o])
    db.finish_run(conn, run_id, status="ok", n_requests=0, n_observations=1, error=None)
    obs_id = conn.execute("SELECT id FROM price_observations WHERE dedup_key = ?",
                          (o.dedup_key,)).fetchone()[0]
    deal_id = db.insert_deal(conn, observation_id=obs_id, rule="median", baseline_median=median,
                             sample_size=days, discount_pct=1 - price / median, threshold=0.3)
    db.set_deal_status(conn, deal_id, status)
    return deal_id


NOV, DEC = date(2026, 11, 1), date(2026, 12, 1)


def test_the_six_deals_detected_on_young_typical_lows_expire_and_an_approved_one_stays(ctx):
    """The queue on 2026-10-16: six deals (new or rendered) detected on 4-6-day typical lows,
    whose months still lack the 10 days spanning 9 a promotion needs. An approved deal is a
    human's decision: only the price recheck judges it."""
    conn = pipeline.open_db(ctx)
    young = {"LIS-BCN": 6, "LIS-ROM": 5, "LIS-PAR": 8, "OPO-BER": 7, "OPO-PAR": 9, "OPO-BCN": 3}
    for route, days in young.items():
        history(conn, route, NOV, days=days, price=90)
    waiting = {route: deal(conn, route, NOV + timedelta(days=17), 51,
                           status="rendered" if i % 2 else "new", days=4 + i % 3, median=76)
               for i, route in enumerate(young)}
    approved = deal(conn, "LIS-BCN", NOV + timedelta(days=9), 50, status="approved", days=6,
                    median=76)

    expired = pipeline.run_reevaluate(ctx, conn, NOW)

    assert sorted(d.id for d, _, _ in expired) == sorted(waiting.values())
    for route, deal_id in waiting.items():
        d = db.get_deal(conn, deal_id)[0]
        assert d.status == "expired", route
        assert d.expired_reason == \
            f"preço habitual ainda sem dados suficientes ({young[route]} de 10 dias)"
    assert db.get_deal(conn, approved)[0].status == "approved"
    assert pipeline.run_reevaluate(ctx, conn, NOW) == []     # expired deals are final


def test_a_deal_still_below_the_current_typical_low_stays_and_one_no_longer_below_expires(ctx):
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)                   # LIS-LON November: 22 days, 101 €
    keeps = deal(conn, "LIS-LON", NOV + timedelta(days=19), 58, status="rendered", days=5,
                 median=90)
    loses = deal(conn, "LIS-LON", NOV + timedelta(days=21), 80, status="new", days=5, median=120)
    approved = deal(conn, "LIS-LON", NOV + timedelta(days=23), 80, status="approved", days=5,
                    median=120)
    folder = ctx.output_dir / "2026-10-14" / f"deal-LIS-LON-{loses}"
    folder.mkdir(parents=True)                               # as if already rendered

    [(gone, obs, reason)] = pipeline.run_reevaluate(ctx, conn, NOW)

    assert (gone.id, gone.status, obs.price) == (loses, "expired", 80)
    assert reason == gone.expired_reason == (
        "já não é promoção face ao preço habitual atual (101 €): 80 € fica 21% abaixo; "
        "são precisos 30% e 15 €")
    assert "NÃO PUBLICAR" in (folder / "EXPIRADO.txt").read_text("utf-8")
    assert db.get_deal(conn, keeps)[0].status == "rendered"
    assert db.get_deal(conn, approved)[0].status == "approved"
    # The price recheck's figures are its own: the re-evaluation sets no price.
    assert (gone.last_checked_at, gone.last_seen_price) == (None, None)


@respx.mock
def test_every_run_judges_the_queue_again_after_detection(ctx, monkeypatch):
    """`detect` (a step of every run) re-evaluates the queue, so a deal from a young typical low
    never stays open until a human approves it."""
    conn = pipeline.open_db(ctx)
    history(conn, "LIS-PAR", NOV, days=4, price=90)
    deal_id = deal(conn, "LIS-PAR", NOV + timedelta(days=17), 51, status="rendered", days=4,
                   median=76)
    mock_api()
    pipeline.run_collect(ctx, conn)
    conn.close()
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    out = CliRunner().invoke(cli.app, ["detect"], catch_exceptions=False).output
    conn = pipeline.open_db(ctx)
    d = db.get_deal(conn, deal_id)[0]
    assert d.status == "expired" and d.expired_reason.startswith("preço habitual ainda sem dados")
    assert f"deal {deal_id} LIS-PAR" in out and "expirado" in out
