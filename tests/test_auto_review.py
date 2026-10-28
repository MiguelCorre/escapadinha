"""Automatic approval for the website (D46): the pure rules, the run step that writes and applies
an approve event for a qualifying rendered candidate (live price check as the gate), no daily
cap (D51), and the paused publishers that keep every post waiting meanwhile. HTTP mocked with respx."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import respx

from escapadinha import auto_review, pipeline, posting, review_events
from escapadinha.config import AutoApproveConfig, PostingConfig
from escapadinha.models import Deal, Observation
from escapadinha.storage import db
from escapadinha.website import is_public
from test_pipeline import ctx  # noqa: F401
from test_posting import approved, by_channel, cli, publish, APPLIED
from test_review import price_api, rendered_deal

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
CFG = AutoApproveConfig(enabled=True)


def deal(**over) -> Deal:
    base = dict(id=1, observation_id=10, rule="median", baseline_median=100, sample_size=20,
                discount_pct=0.4, threshold=0.3, detected_at=NOW, status="rendered",
                affiliate_url="https://aviasales.tpo.lu/x", confidence="high", new_low=True)
    return Deal(**(base | over))


def offer(**over) -> Observation:
    base = dict(source="test", origin="LIS", destination="LON", origin_airport="LIS",
                destination_airport="LGW", departure_date=NOW.date() + timedelta(days=30),
                return_date=NOW.date() + timedelta(days=33), price=58, currency="EUR",
                airline="U2", flight_number="1", transfers=0, return_transfers=0,
                deep_link=None, fetched_at=NOW, raw_json="{}")
    return Observation(**(base | over))


# --- the rules (pure) -----------------------------------------------------------------------

def test_a_high_confidence_new_low_nonstop_fresh_candidate_qualifies():
    assert auto_review.disqualified(deal(), offer(), CFG, now=NOW) is None
    fresh = offer(found_at=NOW - timedelta(hours=47))
    assert auto_review.disqualified(deal(), fresh, CFG, now=NOW) is None
    assert auto_review.summary(deal(), offer()) == "confiança alta, novo mínimo, voos diretos"


@pytest.mark.parametrize("d, o, cfg, why", [
    (deal(), offer(), AutoApproveConfig(enabled=False), "aprovação automática desligada"),
    (deal(status="new"), offer(), CFG, "estado 'new' (só 'por rever')"),
    (deal(rule="price_cap", confidence=None), offer(), CFG, "regra 'price_cap' (só o mínimo habitual)"),
    (deal(confidence="medium"), offer(), CFG, "confiança média (precisa de alta)"),
    (deal(confidence=None), offer(), CFG, "confiança desconhecida (precisa de alta)"),
    (deal(new_low=False), offer(), CFG, "não é um novo mínimo"),
    (deal(new_low=None), offer(), CFG, "não é um novo mínimo"),
    (deal(), offer(return_transfers=1), CFG, "não é ida e volta com voos diretos"),
    (deal(), offer(transfers=None), CFG, "não é ida e volta com voos diretos"),
    (deal(), offer(found_at=NOW - timedelta(hours=49)), CFG, "visto há 49 h (máximo 48 h)"),
])
def test_everything_else_is_left_to_a_human_with_the_reason(d, o, cfg, why):
    assert auto_review.disqualified(d, o, cfg, now=NOW) == why


def test_looser_rules_are_a_config_change():
    loose = AutoApproveConfig(enabled=True, min_confidence="medium", require_new_low=False,
                              direct_only=False)
    assert auto_review.disqualified(deal(confidence="medium", new_low=False),
                                    offer(transfers=1, return_transfers=1), loose,
                                    now=NOW) is None


# --- the run step -----------------------------------------------------------------------------

def clone_candidate(conn, deal_id: int, n: int) -> int:
    """Another rendered candidate for the same trip (its own observation row, since a deal's
    observation is unique), so the run step has several to approve."""
    def row(table, key):
        cur = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (key,))
        return dict(zip([c[0] for c in cur.description], cur.fetchone()))

    def insert(table, values):
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        return conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})",
                            list(values.values())).lastrowid

    deal = row("deals", deal_id)
    obs = row("price_observations", deal.pop("observation_id"))
    obs.pop("id")
    obs["dedup_key"] = f"{obs['dedup_key']}-clone-{n}"
    deal.pop("id")
    deal["observation_id"] = insert("price_observations", obs)
    new_id = insert("deals", deal)
    conn.commit()
    return new_id


@respx.mock
def test_a_qualifying_candidate_goes_live_by_itself_after_a_passing_live_check(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)            # 58 €, high confidence, new low, nonstop
    price_api(58)
    [result] = pipeline.run_auto_approve(ctx, conn, NOW)
    assert (result.deal_id, result.approved, result.reason) == (
        deal_id, True, "confiança alta, novo mínimo, voos diretos")
    d, _ = db.get_deal(conn, deal_id)
    assert d.status == "approved" and is_public(d) and d.review_note == auto_review.NOTE
    [outcome] = review_events.recent_outcomes(conn)
    assert (outcome.actor, outcome.type, outcome.applied) == (auto_review.ACTOR, "approve", True)
    # Posts are queued as for any approval (D32), and wait: both publishers are paused (D46).
    assert {p.channel for p in db.posts(conn, "queued")} == {"instagram", "telegram"}
    # A second pass has nothing left to decide.
    assert pipeline.run_auto_approve(ctx, conn, NOW) == []


@respx.mock
def test_a_moved_price_refuses_the_approval_and_writes_nothing(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    price_api(70)
    [result] = pipeline.run_auto_approve(ctx, conn, NOW)
    assert not result.approved and "O preço mudou" in result.reason
    assert db.get_deal(conn, deal_id)[0].status == "rendered"
    assert review_events.pending(ctx.object_store, conn) == []
    assert review_events.recent_outcomes(conn) == []


@respx.mock
def test_a_candidate_outside_the_rules_waits_for_miguel(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    conn.execute("UPDATE deals SET confidence = 'low' WHERE id = ?", (deal_id,))
    conn.commit()
    price_api(58)
    [result] = pipeline.run_auto_approve(ctx, conn, NOW)
    assert (result.approved, result.reason) == (False, "confiança baixa (precisa de média)")
    assert db.get_deal(conn, deal_id)[0].status == "rendered"


@respx.mock
def test_no_daily_cap_every_qualifying_candidate_goes_live(ctx):
    conn = pipeline.open_db(ctx)
    ids = [rendered_deal(ctx, conn)]
    ids += [clone_candidate(conn, ids[0], n) for n in (1, 2, 3)]   # one more than the old cap
    price_api(58)
    results = pipeline.run_auto_approve(ctx, conn, NOW)
    assert sorted((r.deal_id, r.approved) for r in results) == [(i, True) for i in ids]
    assert all(db.get_deal(conn, i)[0].status == "approved" for i in ids)
    assert not hasattr(ctx.config.review.auto_approve, "max_per_day")


@respx.mock
def test_the_switch(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    price_api(58)
    ctx.config.review.auto_approve.enabled = False
    assert pipeline.run_auto_approve(ctx, conn, NOW) == []
    assert db.get_deal(conn, deal_id)[0].status == "rendered"


@respx.mock
def test_the_command_and_the_run_report_the_decision(ctx, monkeypatch):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    conn.close()
    price_api(58)
    out = cli(ctx, monkeypatch, "auto-approve")
    assert f"deal {deal_id} LIS-LON: ✓ aprovado automaticamente" in out
    assert "No rendered candidates." in cli(ctx, monkeypatch, "auto-approve")


# --- publishers paused (D46) -----------------------------------------------------------------

def test_the_repository_config_pauses_instagram_and_telegram(ctx):
    assert ctx.config.posting.publishers == {"instagram": "paused", "telegram": "paused"}
    assert ctx.config.review.auto_approve.enabled is True
    assert "paused" in pipeline.PUBLISHERS
    assert PostingConfig(publishers={"instagram": "paused"}).publishers["instagram"] == "paused"


@respx.mock          # any HTTP request would fail: a paused channel sends nothing
def test_paused_publishers_keep_every_due_post_waiting(ctx, monkeypatch):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    done, lines = publish(ctx, conn, APPLIED + timedelta(hours=3))   # past the 09:00 slot
    assert sorted(done) == [(deal_id, "instagram", "waiting"), (deal_id, "telegram", "waiting")]
    for post in by_channel(conn).values():
        assert (post.status, post.attempts, post.last_error) == ("queued", 0, pipeline.PAUSED_REASON)
    assert not any("[dry-run]" in line for line in lines)
    assert "Em pausa por decisão do Miguel" in cli(ctx, monkeypatch, "queue", "list")
    assert isinstance(pipeline.PUBLISHERS["paused"].build(None), posting.Paused)
