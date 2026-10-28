"""One promotion per route (D53): detection groups a route's deals (dates) into its open
promotion, the lead is the cheapest live date, a promotion closes when no date is left open
(expired or rejected), and the v18 backfill groups the deals a database already has."""

from __future__ import annotations

from datetime import timedelta

import httpx
import respx

from escapadinha import pipeline
from escapadinha.collector.travelpayouts import API_URL
from escapadinha.storage import db
from test_pipeline import EMPTY, _fixture_with, ctx, mock_api, seed_history  # noqa: F401
from test_reevaluation import NOV, deal as insert_deal

NOW = db.utcnow()


def price_api(price):
    respx.get(API_URL).mock(side_effect=lambda r: httpx.Response(
        200, json=_fixture_with(price) if r.url.params["destination"] == "LON" else EMPTY))


def detect(ctx, conn, price):
    """A collection where the LIS-LON trip costs `price`, then detection; the new deal ids."""
    price_api(price)
    pipeline.run_collect(ctx, conn)
    _, results = pipeline.run_detect(ctx, conn)
    return {r.route: r for r in results}["LIS-LON"].deal_ids


@respx.mock
def test_a_cheaper_price_for_the_same_trip_joins_the_routes_open_promotion(ctx):
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    [first] = detect(ctx, conn, 58)                        # opens the promotion
    assert detect(ctx, conn, 57) == []                     # 1.7 % cheaper: the same deal (D53)
    [second] = detect(ctx, conn, 50)                       # 14 % cheaper: a new date, same group
    a, b = db.get_deal(conn, first)[0], db.get_deal(conn, second)[0]
    assert a.promotion_id == b.promotion_id is not None
    promotion = db.get_promotion(conn, a.promotion_id)
    assert (promotion.route_key, promotion.closed_at) == ("LIS-LON", None)
    assert db.open_promotion(conn, "LIS", "LON").id == promotion.id
    assert [d.id for d, _ in db.promotion_deals(conn, promotion.id)] == [first, second]
    # The lead is the cheapest live date: none yet (both await review), then the 50 € one.
    assert pipeline.promotion_lead(conn, a) is None
    db.set_deal_status(conn, first, "approved")
    db.set_deal_status(conn, second, "approved")
    lead, lead_obs = pipeline.promotion_lead(conn, a)
    assert (lead.id, lead_obs.price) == (second, 50)
    # The same trip twice: the site and the posts see it once (the cheapest), the reviewer both.
    assert [o.price for _, o in pipeline.promotion_dates(conn, promotion.id)] == [50]
    assert [o.price for _, o in pipeline.promotion_dates(conn, promotion.id, one_per_trip=False)] == [50, 58]


@respx.mock
def test_the_promotion_closes_when_its_last_date_expires_and_a_new_one_opens_another(ctx):
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    [first] = detect(ctx, conn, 58)
    [second] = detect(ctx, conn, 50)
    pid = db.get_deal(conn, first)[0].promotion_id
    db.set_deal_status(conn, first, "approved")
    db.set_deal_status(conn, second, "approved")
    # 59 €: the 58 € date holds within the tolerance (and is still a promotion), the 50 € one
    # rose 18 % and expires; the promotion stays open.
    price_api(59)
    pipeline.run_collect(ctx, conn)
    results = {d.id: r for d, _, r in pipeline.run_recheck(ctx, conn, now=NOW)}
    assert results[first].valid and results[first].reason == "subiu para 59 €, dentro da tolerância de 5%"
    assert not results[second].valid and results[second].reason == "o preço subiu para 59 €"
    assert db.get_promotion(conn, pid).closed_at is None
    assert pipeline.promotion_lead(conn, db.get_deal(conn, first)[0])[0].id == first
    # 80 €: the last date expires and the promotion closes with its reason.
    price_api(80)
    pipeline.run_collect(ctx, conn)
    pipeline.run_recheck(ctx, conn, now=NOW + timedelta(hours=1))
    closed = db.get_promotion(conn, pid)
    assert closed.closed_at is not None
    assert closed.closed_reason == "todas as datas expiraram; última: o preço subiu para 80 €"
    assert db.open_promotion(conn, "LIS", "LON") is None
    # A new cheap date later opens a new promotion (the old page stays, D35).
    [third] = detect(ctx, conn, 40)
    assert db.get_deal(conn, third)[0].promotion_id not in (None, pid)


@respx.mock
def test_rejecting_every_date_closes_the_promotion(ctx):
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    [first] = detect(ctx, conn, 58)
    pid = db.get_deal(conn, first)[0].promotion_id
    pipeline.reject(ctx, conn, first, "não", actor="test")
    pipeline.close_empty_promotions(conn, NOW)
    assert db.get_promotion(conn, pid).closed_reason == "todas as datas foram rejeitadas"


def test_dates_inserted_by_hand_without_a_promotion_stay_ungrouped_and_close_nothing(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = insert_deal(conn, "LIS-LON", NOV + timedelta(days=10), 50, status="approved",
                          days=12, median=100)
    assert db.get_deal(conn, deal_id)[0].promotion_id is None
    assert pipeline.promotion_lead(conn, db.get_deal(conn, deal_id)[0]) is None
    assert pipeline.close_empty_promotions(conn, NOW) == []


def test_the_v18_backfill_groups_the_deals_a_database_already_has(ctx):
    """Open deals of a route share one promotion; an expired deal a human approved gets a closed
    one of its own; expired-unreviewed and rejected deals stay ungrouped."""
    conn = pipeline.open_db(ctx)
    ids = {}
    for name, (route, day, price, status) in {
        "lon_new": ("LIS-LON", 10, 50, "new"), "lon_approved": ("LIS-LON", 12, 55, "approved"),
        "par_rendered": ("LIS-PAR", 10, 60, "rendered"),
        "par_public_expired": ("LIS-PAR", 11, 61, "expired"),
        "par_unreviewed_expired": ("LIS-PAR", 12, 62, "expired"),
        "bcn_rejected": ("LIS-BCN", 10, 70, "rejected"),
    }.items():
        ids[name] = insert_deal(conn, route, NOV + timedelta(days=day), price, status=status,
                                days=12, median=100)
    conn.execute("UPDATE deals SET reviewed_at = ?, expired_reason = 'o preço subiu para 70 €' "
                 "WHERE id = ?", (db._ts(NOW), ids["par_public_expired"]))
    conn.execute("UPDATE deals SET promotion_id = NULL")
    conn.commit()
    db._backfill_promotions(conn)
    deal = lambda name: db.get_deal(conn, ids[name])[0]      # noqa: E731
    assert deal("lon_new").promotion_id == deal("lon_approved").promotion_id is not None
    assert deal("par_rendered").promotion_id not in (None, deal("lon_new").promotion_id)
    public = db.get_promotion(conn, deal("par_public_expired").promotion_id)
    assert public.closed_at is not None and public.closed_reason == "o preço subiu para 70 €"
    assert public.id != deal("par_rendered").promotion_id
    assert deal("par_unreviewed_expired").promotion_id is None
    assert deal("bcn_rejected").promotion_id is None
    assert {p.route_key for p in db.open_promotions(conn)} == {"LIS-LON", "LIS-PAR"}
    db._backfill_promotions(conn)                              # idempotent: nothing regrouped
    assert len(db.open_promotions(conn)) == 2
