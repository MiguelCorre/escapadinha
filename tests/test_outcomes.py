"""Promotion outcomes (#74): every expiry records when and why in a form code can read (#77),
and the survival report built on it (#78, below)."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

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
    schema = (Path(db.__file__).parent / "schema.sql").read_text("utf-8")
    for sql in (schema, " ".join(s for s in db.MIGRATIONS[19] if isinstance(s, str))):
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
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 19
    for reason, kind in REASONS.items():
        deal = db.get_deal(conn, ids[reason])[0]
        assert deal.expired_kind == kind, reason
        assert db._ts(deal.expired_at) == checked, reason
    deal = db.get_deal(conn, never_checked)[0]
    assert (deal.expired_kind, deal.expired_at) == ("gone", deal.detected_at)
    assert db.get_deal(conn, open_id)[0].expired_at is None
    assert db.expiries_backfilled_before(conn) is not None   # the report marks these approximate
