"""Promotion outcomes (#74): every expiry records when and why in a form code can read (#77),
and the survival report built on it (#78, below)."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import respx

from escapadinha import outcomes, pipeline
from escapadinha.config import DetectorConfig
from escapadinha.models import RouteRules
from escapadinha.recheck import recheck
from escapadinha.storage import db
from test_pipeline import ctx  # noqa: F401
from test_recheck import CFG, DEAL, NOW, obs
from test_reevaluation import NOV, deal as insert_deal, history


# --- #77: expiry time and kind ---------------------------------------------------------------

def test_the_recheck_names_the_kind_of_every_expiry():
    assert recheck(DEAL, [obs(60)], CFG, NOW).kind is None                      # still valid
    assert recheck(DEAL, [obs(70)], CFG, NOW).kind == "gone"                    # price rose
    assert recheck(DEAL, [obs(60, dep=NOW.date() + timedelta(days=50))], CFG, NOW).kind == "gone"
    assert recheck(DEAL, [obs(60, found_ago=5)], CFG, NOW).kind == "gone"       # stale
    tolerant = DetectorConfig(max_offer_age_days=3, recheck_tolerance_pct=0.05)
    rose = recheck(DEAL, [obs(62)], tolerant, NOW, typical_low=80)              # within 5 %, no
    assert (rose.valid, rose.kind) == (False, "gone")                          # longer a promotion
    short = recheck(DEAL, [obs(60)], CFG, NOW, rules=RouteRules(min_nights=4, max_nights=7))
    assert (short.valid, short.kind) == (False, "rules")                      # 3 nights


def test_an_expiring_recheck_stores_its_time_and_kind_and_a_valid_one_neither(ctx):  # noqa: F811
    conn = pipeline.open_db(ctx)
    gone = insert_deal(conn, "LIS-LON", NOV + timedelta(days=10), 50, status="approved",
                       days=12, median=100)
    kept = insert_deal(conn, "LIS-LON", NOV + timedelta(days=12), 52, status="approved",
                       days=12, median=100)
    at = db.utcnow()
    db.record_recheck(conn, gone, valid=False, latest_price=70, reason="o preço subiu para 70 €",
                      kind="gone", at=at)
    db.record_recheck(conn, kept, valid=True, latest_price=52, reason="continua a 52 €", at=at)
    deal = db.get_deal(conn, gone)[0]
    assert (deal.status, deal.expired_at, deal.expired_kind) == ("expired", at, "gone")
    deal = db.get_deal(conn, kept)[0]
    assert (deal.status, deal.expired_at, deal.expired_kind) == ("approved", None, None)


def test_a_reevaluation_expiry_stores_its_own_time_not_the_previous_rechecks(ctx):  # noqa: F811
    conn = pipeline.open_db(ctx)
    history(conn, "LIS-BCN", NOV, days=5, price=90)          # young: no promotion today (D40)
    deal_id = insert_deal(conn, "LIS-BCN", NOV + timedelta(days=17), 51, status="rendered",
                          days=5, median=76)
    earlier = NOW - timedelta(hours=3)
    db.record_recheck(conn, deal_id, valid=True, latest_price=51, reason="continua a 51 €",
                      at=earlier)
    later = db.utcnow()
    [(deal, _, reason)] = pipeline.run_reevaluate(ctx, conn, later)
    assert reason.startswith("preço habitual ainda sem dados suficientes")
    assert (deal.status, deal.expired_kind, deal.expired_at) == ("expired", "superseded", later)
    assert deal.last_checked_at == earlier                   # the recheck's own time stays


def test_the_kind_check_in_sql_is_expiry_kinds():
    """Fresh installs (schema.sql) and the newest migration that defines the CHECK (v20's
    rebuilt table, D65): a new kind needs both, and a migration of its own."""
    schema = (Path(db.__file__).parent / "schema.sql").read_text("utf-8")
    for sql in (schema, db.DEALS_V20):
        listed = re.search(r"expired_kind\s+TEXT\s+CHECK \(expired_kind IN \(([^)]*)\)\)", sql).group(1)
        assert tuple(re.findall(r"'([a-z]+)'", listed)) == outcomes.EXPIRY_KINDS


REASONS = {
    "o preço subiu para 39,98 €": "gone",
    "o preço subiu para 62 € e já não é promoção face ao preço habitual (80 €)": "gone",
    "a viagem já não aparece nos preços mais recentes": "gone",
    "o preço foi visto pela última vez a 11/10, há mais de 3 dias": "gone",
    "já não é um novo mínimo: entretanto vimos 54,98 € para este mês, e 56 € teria de …": "superseded",
    "já não é promoção face ao preço habitual atual (71 €): 60 € fica 15% abaixo; …": "superseded",
    "preço habitual ainda sem dados suficientes (1 de 10 dias)": "superseded",
    "fora do intervalo de 2–5 noites da rota": "rules",
    "não é ida e volta com voos diretos (regra direct_only)": "rules",
    "tem mais de 1 escala(s) num dos sentidos (regra max_transfers)": "rules",
    "uma razão de outra versão": None,
}


def test_upgrading_a_v18_database_backfills_time_and_kind_from_the_old_reasons(ctx):  # noqa: F811
    conn = pipeline.open_db(ctx)
    checked = "2026-10-20T08:00:00+00:00"
    ids = {}
    for i, reason in enumerate(REASONS):
        ids[reason] = insert_deal(conn, "LIS-LON", NOV + timedelta(days=i), 50 + i,
                                  status="expired", days=12, median=100)
        conn.execute("UPDATE deals SET expired_reason = ?, last_checked_at = ? WHERE id = ?",
                     (reason, checked, ids[reason]))
    never_checked = insert_deal(conn, "LIS-LON", NOV + timedelta(days=20), 40, status="expired",
                                days=12, median=100)
    conn.execute("UPDATE deals SET expired_reason = 'o preço subiu para 45 €' WHERE id = ?",
                 (never_checked,))
    open_id = insert_deal(conn, "LIS-LON", NOV + timedelta(days=21), 41, status="rendered",
                          days=12, median=100)
    conn.execute("ALTER TABLE deals DROP COLUMN expired_at")
    conn.execute("ALTER TABLE deals DROP COLUMN expired_kind")
    conn.execute("PRAGMA user_version = 18")
    conn.commit()
    conn.close()

    conn = pipeline.open_db(ctx)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 20
    for reason, kind in REASONS.items():
        deal = db.get_deal(conn, ids[reason])[0]
        assert deal.expired_kind == kind, reason
        assert db._ts(deal.expired_at) == checked, reason
    deal = db.get_deal(conn, never_checked)[0]
    assert (deal.expired_kind, deal.expired_at) == ("gone", deal.detected_at)
    assert db.get_deal(conn, open_id)[0].expired_at is None
    assert db.expiries_backfilled_before(conn) is not None   # the report marks these approximate


def test_the_backfill_marks_its_newest_expiry_so_a_later_one_is_never_approximate(ctx):  # noqa: F811
    """The marker is the newest backfilled expiry, not the migration's clock: a deal expired by
    the first run after the upgrade (at that run's `now`, which may precede the migration's own
    time) is exact."""
    conn = pipeline.open_db(ctx)
    old = insert_deal(conn, "LIS-LON", NOV, 50, status="expired", days=12, median=100)
    conn.execute("UPDATE deals SET expired_reason = 'o preço subiu para 70 €', "
                 "last_checked_at = '2026-10-20T08:00:00+00:00' WHERE id = ?", (old,))
    conn.execute("ALTER TABLE deals DROP COLUMN expired_at")
    conn.execute("ALTER TABLE deals DROP COLUMN expired_kind")
    conn.execute("PRAGMA user_version = 18")
    conn.commit()
    conn.close()
    conn = pipeline.open_db(ctx)
    assert db._ts(db.expiries_backfilled_before(conn)) == "2026-10-20T08:00:00+00:00"


def test_a_fresh_database_has_no_backfilled_expiries(ctx):  # noqa: F811
    assert db.expiries_backfilled_before(pipeline.open_db(ctx)) is None


def _cli(ctx, monkeypatch, *args) -> str:
    from typer.testing import CliRunner
    from escapadinha import cli
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    result = CliRunner().invoke(cli.app, list(args))
    assert result.exit_code == 0, result.output
    return " ".join(result.output.split())


def test_deal_check_on_an_expired_deal_says_when_and_why_without_fetching(ctx, monkeypatch):  # noqa: F811
    conn = pipeline.open_db(ctx)
    deal_id = insert_deal(conn, "LIS-LON", NOV + timedelta(days=10), 50, status="approved",
                          days=12, median=100)
    at = datetime(2026, 10, 24, 13, 5, tzinfo=timezone.utc)
    db.record_recheck(conn, deal_id, valid=False, latest_price=70,
                      reason="o preço subiu para 70 €", kind="gone", at=at)
    out = _cli(ctx, monkeypatch, "deal", "check", str(deal_id))      # no HTTP mock: no fetch
    assert f"deal {deal_id}: ✗ expirado (o preço subiu para 70 €)" in out
    assert "expirou a 24/10/2026 às 14:05 (desaparecida)" in out


def test_deal_check_marks_a_backfilled_expiry_time_approximate(ctx, monkeypatch):  # noqa: F811
    conn = pipeline.open_db(ctx)
    deal_id = insert_deal(conn, "LIS-LON", NOV, 50, status="expired", days=12, median=100)
    conn.execute("UPDATE deals SET expired_reason = 'já não é um novo mínimo: …', "
                 "last_checked_at = '2026-10-20T08:00:00+00:00' WHERE id = ?", (deal_id,))
    conn.execute("ALTER TABLE deals DROP COLUMN expired_at")
    conn.execute("ALTER TABLE deals DROP COLUMN expired_kind")
    conn.execute("PRAGMA user_version = 18")
    conn.commit()
    conn.close()
    out = _cli(ctx, monkeypatch, "deal", "check", str(deal_id))
    assert "expirou a 20/10/2026 às 09:00 (ultrapassada, hora aproximada)" in out


# --- #78: the survival report ----------------------------------------------------------------

T0 = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)


def h(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


def row(deal_id: int, **kw) -> outcomes.Outcome:
    base = dict(deal_id=deal_id, detected_at=T0, last_checked_at=None, expired_at=None,
                expired_kind=None, approximate=False, approved_at=None, approver="none",
                source="ryanair", confidence="medium", lead_days=40, found_age_h=1.0,
                route_kind="europe", breadth=3)
    return outcomes.Outcome(**{**base, **kw})


ROWS = [
    row(1, last_checked_at=h(30)),                                            # open, watched 30 h
    row(2, last_checked_at=h(2), expired_at=h(3), expired_kind="superseded"),  # censored at 2 h
    row(3, last_checked_at=h(3), expired_at=h(3), expired_kind="gone",         # gone at 3 h,
        approved_at=h(1), approver="rules", source="travelpayouts"),            # 2 h after approval
    row(4, last_checked_at=h(30), expired_at=h(30), expired_kind="gone",       # gone at 30 h
        approved_at=h(0.5), approver="human", found_age_h=None, approximate=True),
]


def shares(clock: outcomes.Clock) -> list[tuple[int, int]]:
    return [(x.gone, x.judged) for x in clock.horizons]


def test_survival_counts_open_and_superseded_deals_as_surviving_until_their_last_check():
    [everyone] = outcomes.survival(ROWS, by=outcomes.ALL)
    assert (everyone.deals, everyone.approximate) == (4, 1)
    #                                  2 h     6 h     24 h    48 h
    assert shares(everyone.detection) == [(0, 4), (1, 3), (1, 3), (2, 2)]
    assert everyone.detection.median_life_h == 16.5          # 30, 3 (its expiry), 3, 30
    assert everyone.approval.deals == 2                      # approved ones, from approval
    assert shares(everyone.approval) == [(1, 2), (1, 2), (1, 2), (2, 2)]
    assert everyone.approval.median_life_h == 15.75          # 2 and 29.5


def test_survival_groups_by_a_slice_in_its_order_and_keeps_empty_groups():
    by = {g.name: g for g in outcomes.survival(ROWS, by=outcomes.slice_named("approved by"))}
    assert list(by) == ["rules", "human", "none"]
    assert shares(by["rules"].detection) == [(0, 1), (1, 1), (1, 1), (1, 1)]
    assert by["none"].approval.deals == 0 and by["none"].approval.horizons[0].share is None
    lead = outcomes.survival(ROWS, by=outcomes.slice_named("lead time (days)"))
    assert [(g.name, g.deals) for g in lead] == [("< 14", 0), ("14–29", 0), ("30–59", 4), ("60+", 0)]
    assert lead[0].detection.horizons[2].share is None and lead[0].detection.median_life_h is None
    found = {g.name: g.deals for g in outcomes.survival(ROWS, by=outcomes.slice_named("found age (h)"))}
    assert found == {"< 2": 3, "2–12": 0, "12+": 0, "unknown": 1}


def test_bands():
    assert [outcomes.band(n, outcomes.LEAD_DAYS) for n in (0, 13, 14, 29, 30, 59, 60, 400)] == [
        "< 14", "< 14", "14–29", "14–29", "30–59", "30–59", "60+", "60+"]
    assert [outcomes.band(n, outcomes.BREADTH) for n in (0, 1, 2, 3, 4, 7, 8)] == [
        "0–1", "0–1", "2–3", "2–3", "4–7", "4–7", "8+"]
    assert [outcomes.band(x, outcomes.FOUND_AGE_H) for x in (0.5, 2.0, 11.9, 12.0)] == [
        "< 2", "2–12", "2–12", "12+"]


def test_the_markdown_prints_dashes_for_empty_groups_and_the_cache_caveat_by_its_source():
    report = outcomes.report(ROWS, since=T0 - timedelta(days=14), now=h(50))
    text = outcomes.markdown(report)
    assert "| All | 4 | 0% of 4 | 33% of 3 | 33% of 3 | 100% of 2 | 16.5 |" in text
    assert "| 60+ | 0 | — | — | — | — | — |" in text
    tp = next(line for line in text.splitlines() if line.startswith("| travelpayouts"))
    assert tp.startswith("| travelpayouts ¹ |")
    assert "¹ The Travelpayouts source is a cache" in text
    assert "1 of 4 expiry times are approximate" in text
    data = outcomes.to_json(report)
    assert data["all"]["detection"]["horizons"][1] == {"hours": 6, "judged": 3, "gone": 1,
                                                       "share": 1 / 3}
    assert [g["name"] for g in data["slices"]["source"]] == ["ryanair", "travelpayouts"]


def test_breadth_counts_the_other_cheap_dates_of_the_route_month_and_source_seen_before():
    at = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)
    deal_obs = obs(60, dep=date(2026, 11, 25))
    near = [obs(60, dep=date(2026, 11, 25)),                     # the deal's own date
            obs(66, dep=date(2026, 11, 3)),                      # +10 %: counts
            obs(66, dep=date(2026, 11, 3)),                      # the same date again
            obs(64, dep=date(2026, 11, 4)),
            obs(67, dep=date(2026, 11, 5)),                      # dearer than +10 %
            obs(55, dep=date(2026, 12, 1)),                      # another month
            replace(obs(55, dep=date(2026, 11, 6)), source="ryanair"),   # another source
            replace(obs(55, dep=date(2026, 11, 7)), last_seen_at=at - timedelta(hours=7)),
            replace(obs(55, dep=date(2026, 11, 8)), fetched_at=at + timedelta(minutes=1))]
    assert outcomes.breadth(deal_obs, near, at) == 3             # 25, 3 and 4 November


def test_deal_outcomes_reads_each_deal_with_its_approver_lead_time_and_breadth(ctx):  # noqa: F811
    from escapadinha import auto_review
    conn = pipeline.open_db(ctx)
    since = db.utcnow() - timedelta(minutes=1)
    auto = insert_deal(conn, "LIS-LON", NOV + timedelta(days=10), 50, status="rendered",
                       days=12, median=100)
    db.record_review(conn, auto, status="approved", note=auto_review.NOTE)
    human = insert_deal(conn, "LIS-LON", NOV + timedelta(days=12), 54, status="rendered",
                        days=12, median=100)
    db.record_review(conn, human, status="approved", note="bom deal")
    rejected = insert_deal(conn, "LIS-LON", NOV + timedelta(days=14), 56, status="rendered",
                           days=12, median=100)
    db.record_review(conn, rejected, status="rejected", note="datas fracas")
    rows = {o.deal_id: o for o in pipeline.deal_outcomes(ctx, conn, since=since)}
    assert [rows[i].approver for i in (auto, human, rejected)] == ["rules", "human", "none"]
    assert rows[auto].approved_at is not None and rows[rejected].approved_at is None
    assert (rows[auto].route_kind, rows[auto].source, rows[auto].found_age_h) == ("europe", "test", None)
    assert rows[auto].lead_days == (NOV + timedelta(days=10) - db.utcnow().date()).days
    # 50 €: its own date and 54 € (within +10 %), not 56 €; 54 €: all three (59,40 € limit)
    assert (rows[auto].breadth, rows[human].breadth) == (2, 3)
    assert pipeline.deal_outcomes(ctx, conn, since=db.utcnow() + timedelta(minutes=1)) == []


def test_the_outcomes_command_reads_a_copy_in_memory_and_never_writes_the_file(ctx, monkeypatch, tmp_path):  # noqa: F811
    import hashlib
    import json
    conn = pipeline.open_db(ctx)
    deal_id = insert_deal(conn, "LIS-LON", NOV + timedelta(days=10), 50, status="approved",
                          days=12, median=100)
    db.record_recheck(conn, deal_id, valid=False, latest_price=70,
                      reason="o preço subiu para 70 €", kind="gone", at=db.utcnow())
    conn.execute("ALTER TABLE deals DROP COLUMN expired_at")       # a v18 file: the upgrade
    conn.execute("ALTER TABLE deals DROP COLUMN expired_kind")     # happens in memory only
    conn.execute("PRAGMA user_version = 18")
    conn.commit()
    conn.close()
    before = hashlib.sha256(ctx.db_path.read_bytes()).hexdigest()
    out = tmp_path / "outcomes.json"
    text = _cli(ctx, monkeypatch, "outcomes", "--days", "14", "--json", str(out))
    assert hashlib.sha256(ctx.db_path.read_bytes()).hexdigest() == before
    assert "| All | 1 |" in text and "1 of 1 expiry times are approximate" in text
    assert json.loads(out.read_text("utf-8"))["all"]["deals"] == 1


# --- #79: the line on the review pages ------------------------------------------------------

def test_the_24_h_mark_per_source_and_confidence():
    marks = outcomes.by_source_and_confidence(ROWS, 24)
    assert {k: (x.gone, x.judged) for k, x in marks.items()} == {
        ("ryanair", "medium"): (0, 2), ("travelpayouts", "medium"): (1, 1)}


def test_what_visitors_may_know_about_the_approved_promotions():
    """#79 (Miguel, 2026-11-05): the approval clock's 24 h mark over the approved deals,
    censored like the report; nothing below `min_n` judged, nothing without a judged deal."""
    # Deal 3: approved at 1 h, gone 2 h later; deal 4: approved at 0.5 h, gone 29.5 h later.
    assert outcomes.published(ROWS, min_n=2) == outcomes.Published(2, 50, 24)
    assert outcomes.published(ROWS, hours=48, min_n=2) == outcomes.Published(2, 0, 48)
    assert outcomes.published(ROWS, hours=2, min_n=1) == outcomes.Published(2, 50, 2)
    assert outcomes.published(ROWS, min_n=3) is None
    assert outcomes.published([], min_n=0) is None
    assert outcomes.PUBLISHED_HOURS == 24


def test_the_survival_line_in_pt_pt():
    from escapadinha import i18n_pt
    assert i18n_pt.survival_line("Ryanair", "média", 83, 14, 342) == (
        "Destas promoções (Ryanair, confiança média), 83% desapareceram em 24 h "
        "(últimos 14 dias, 342)")
    assert i18n_pt.survival_line("Aviasales", None, 5, 7, 1200) == (
        "Destas promoções (Aviasales), 5% desapareceram em 24 h (últimos 7 dias, 1 200)")


def _past_deals(conn, like, fates):
    """Deals detected two days before `like`'s, of its source and confidence, each gone at 3 h
    (True) or superseded at 30 h (False)."""
    deal, obs = like
    at = deal.detected_at - timedelta(days=2)
    for i, gone in enumerate(fates):
        past = insert_deal(conn, "LIS-LON", NOV + timedelta(days=i), 40 + i, status="expired",
                           days=12, median=100)
        end = at + timedelta(hours=3 if gone else 30)
        conn.execute("UPDATE deals SET detected_at = ?, confidence = ?, last_checked_at = ?, "
                     "expired_at = ?, expired_kind = ? WHERE id = ?",
                     (db._ts(at), deal.confidence, db._ts(end), db._ts(end),
                      "gone" if gone else "superseded", past))
        conn.execute("UPDATE price_observations SET source = ? WHERE id = "
                     "(SELECT observation_id FROM deals WHERE id = ?)", (obs.source, past))
    conn.commit()


@respx.mock
def test_queue_items_carry_how_often_promotions_like_them_vanished_on_both_pages(ctx):  # noqa: F811
    from fastapi.testclient import TestClient
    from escapadinha import review_snapshot
    from escapadinha.web import create_app
    from test_review import rendered_deal
    from test_review_events import validate
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    deal, obs = db.get_deal(conn, deal_id)
    _past_deals(conn, (deal, obs), [True, True, True, False])
    now = db.utcnow()
    ctx.config.review.outcomes_min_n = 4
    snap = review_snapshot.build(ctx, conn, now)
    validate("snapshot", snap)
    [d] = snap["queue"]
    assert d["survival"] == {"gone_24h_pct": 75, "n": 4, "days": 14, "source": obs.source,
                             "confidence": deal.confidence}
    assert all(x["survival"] is None for x in snap["closed"])        # queue items only
    [d] = TestClient(create_app(ctx)).get("/api/deals", params={"tab": "queue"}).json()["deals"]
    confidence = {"high": ", confiança alta", "medium": ", confiança média"}.get(deal.confidence, "")
    assert d["survival_pt"] == (f"Destas promoções (Aviasales{confidence}), 75% desapareceram "
                                "em 24 h (últimos 14 dias, 4)")
    ctx.config.review.outcomes_min_n = 5                          # too few judged: nothing
    assert review_snapshot.build(ctx, conn, now)["queue"][0]["survival"] is None
    [d] = TestClient(create_app(ctx)).get("/api/deals", params={"tab": "queue"}).json()["deals"]
    assert d["survival_pt"] is None


def test_the_outcomes_command_refuses_a_missing_file(ctx, monkeypatch, tmp_path):  # noqa: F811
    from typer.testing import CliRunner
    from escapadinha import cli
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    result = CliRunner().invoke(cli.app, ["outcomes", "--db", str(tmp_path / "nope.db")])
    assert result.exit_code == 1 and "nope.db" in " ".join(result.output.split())
    assert not (tmp_path / "nope.db").exists()


# --- D65: contradicted, the fourth kind, and schema v20 ---------------------------------------

def test_a_contradicted_deal_counts_as_gone_at_its_expiry_and_is_labelled():
    """The probe's two engines saw the trip clearly dearer: the price was not bookable, so the
    report counts it as gone (censoring it would flatter "still valid"), as its own kind."""
    contradicted = [row(1, last_checked_at=h(3), expired_at=h(3), expired_kind="contradicted",
                        approved_at=h(1), approver="rules"),
                    row(2, last_checked_at=h(30))]
    [everyone] = outcomes.survival(contradicted, by=outcomes.ALL)
    #                                  2 h     6 h     24 h    48 h
    assert shares(everyone.detection) == [(0, 2), (1, 2), (1, 2), (1, 1)]
    assert outcomes.published(contradicted, min_n=1) == outcomes.Published(1, 0, 24)
    assert outcomes.EXPIRY_KINDS == ("gone", "superseded", "rules", "contradicted")
    assert outcomes.EXPIRY_KIND_PT["contradicted"] == "desmentida pela sonda"
    assert outcomes.GONE_KINDS == {"gone", "contradicted"}


def test_expire_deal_leaves_an_approved_deal_alone_unless_asked_for_every_open_status(ctx):  # noqa: F811
    conn = pipeline.open_db(ctx)
    approved = insert_deal(conn, "LIS-LON", NOV + timedelta(days=10), 50, status="approved",
                           days=12, median=100)
    at = db.utcnow()
    db.expire_deal(conn, approved, "desmentida", kind="contradicted", at=at)
    assert db.get_deal(conn, approved)[0].status == "approved"      # the default: D40's queue
    db.expire_deal(conn, approved, "desmentida", kind="contradicted", at=at,
                   statuses=db.OPEN_STATUSES)
    deal = db.get_deal(conn, approved)[0]
    assert (deal.status, deal.expired_kind, deal.expired_at) == ("expired", "contradicted", at)
    with pytest.raises(ValueError, match="nonsense"):
        db.expire_deal(conn, approved, "x", kind="nonsense")


TS = "2026-10-20T08:00:00+00:00"
# An expired, approved, grouped deal as v19 stored it: every column set.
V19_DEAL = dict(
    id=3, observation_id=1, rule="median", baseline_median=100, sample_size=12, discount_pct=0.5,
    threshold=0.3, detected_at=TS, status="expired", affiliate_url="https://example.test/a",
    affiliate_error="none", last_checked_at=TS, last_seen_price=70,
    expired_reason="o preço subiu para 70 €", output_path="output/deals/3", reviewed_at=TS,
    review_note="bom deal", published_at=TS, post_url="https://example.test/p",
    baseline_span_days=11, baseline_lowest_obs_id=1, baseline_highest_obs_id=1,
    confidence="high", new_low=1, partner_discount_pct=12, partner_offer_at=TS, promotion_id=7,
    expired_at=TS, expired_kind="gone")


def v19_database(path: Path) -> None:
    """A file as schema v19 left it: the v7 schema and every step since, never today's tables
    with `ALTER TABLE ... DROP COLUMN` (D64). One deal with its observation, its promotion and
    a queued post that references it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    old.executescript((Path(__file__).parent / "fixtures" / "schema_v7.sql").read_text("utf-8"))
    for version in range(8, 20):
        for step in db.MIGRATIONS[version]:
            step(old) if callable(step) else old.execute(step)
    old.execute("INSERT INTO fetch_runs (id, source, started_at) VALUES (1, 'test', ?)", (TS,))
    old.execute("""INSERT INTO price_observations (id, run_id, last_run_id, source, origin,
                       destination, departure_date, return_date, nights, price, currency,
                       fetched_at, last_seen_at, dedup_key)
                   VALUES (1, 1, 1, 'test', 'LIS', 'LON', '2026-11-10', '2026-11-13', 3, 50,
                           'EUR', ?, ?, 'k1')""", (TS, TS))
    old.execute("INSERT INTO promotions (id, origin, destination, opened_at) "
                "VALUES (7, 'LIS', 'LON', ?)", (TS,))
    columns = [r["name"] for r in old.execute("PRAGMA table_info(deals)")]
    assert set(columns) == set(V19_DEAL)
    old.execute(f"INSERT INTO deals ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                [V19_DEAL[c] for c in columns])
    old.execute("""INSERT INTO posting_queue (id, deal_id, channel, due_at, created_at, promotion_id)
                   VALUES (5, 3, 'telegram', ?, ?, 7)""", (TS, TS))
    old.execute("PRAGMA user_version = 19")
    old.commit()
    old.close()


def test_upgrading_a_v19_database_rebuilds_deals_so_the_check_takes_contradicted(ctx):  # noqa: F811
    v19_database(ctx.db_path)
    conn = db.connect(ctx.db_path)                          # foreign keys on, as every run
    db.init(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 20
    assert dict(conn.execute("SELECT * FROM deals WHERE id = 3").fetchone()) == V19_DEAL
    fresh = db.connect(ctx.root / "fresh.db")
    db.init(fresh)
    for pragma in ("table_info", "foreign_key_list", "index_list"):
        assert ([tuple(r) for r in conn.execute(f"PRAGMA {pragma}(deals)")]
                == [tuple(r) for r in fresh.execute(f"PRAGMA {pragma}(deals)")]), pragma
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("SELECT d.id FROM posting_queue q JOIN deals d ON d.id = q.deal_id "
                        "WHERE q.id = 5").fetchone()[0] == 3
    with pytest.raises(sqlite3.IntegrityError):              # the reference is still enforced
        conn.execute("INSERT INTO posting_queue (deal_id, channel, due_at, created_at) "
                     "VALUES (99, 'instagram', ?, ?)", (TS, TS))
    conn.execute("UPDATE deals SET expired_kind = 'contradicted' WHERE id = 3")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE deals SET expired_kind = 'nonsense' WHERE id = 3")
