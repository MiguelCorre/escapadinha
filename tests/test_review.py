"""Approval queue: transitions, live price check before approval, and the local web page."""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from escapadinha import pipeline
from escapadinha.collector.travelpayouts import API_URL
from escapadinha.review import ReviewError, ensure_transition
from escapadinha.storage import db
from escapadinha.web import create_app
from test_pipeline import EMPTY, _fixture_with, ctx, mock_api, mock_links, seed_history  # noqa: F401

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def price_api(price):
    """LIS-LON trip repriced; other routes empty."""
    respx.get(API_URL).mock(side_effect=lambda r: httpx.Response(
        200, json=_fixture_with(price) if r.url.params["destination"] == "LON" else EMPTY))


def rendered_deal(ctx, conn, *, with_link=True):
    """A detected LIS-LON deal (58 €), marked rendered with fake slides (no browser)."""
    seed_history(conn, days=25, price=100)
    mock_api()
    pipeline.run_collect(ctx, conn)
    _, results = pipeline.run_detect(ctx, conn)
    deal_id = {r.route: r for r in results}["LIS-LON"].deal_ids[0]
    if with_link:
        mock_links()
        pipeline.ensure_affiliate_links(ctx, conn, [db.get_deal(conn, deal_id)])
    folder = ctx.output_dir / "2026-10-12" / f"deal-LIS-LON-{deal_id}"
    folder.mkdir(parents=True)
    for n in (1, 2, 3):
        (folder / f"slide_{n:02d}.png").write_bytes(PNG)
    (folder / "caption.txt").write_text("legenda de teste", "utf-8")
    db.set_deal_output_path(conn, deal_id, str(folder))
    db.set_deal_status(conn, deal_id, "rendered")
    return deal_id


# --- rules ---------------------------------------------------------------------------

@pytest.mark.parametrize("current, target, ok", [
    ("rendered", "approved", True), ("approved", "published", True), ("new", "rejected", True),
    ("rendered", "published", False), ("expired", "approved", False),
    ("published", "rejected", False), ("rejected", "approved", False),
])
def test_transitions(current, target, ok):
    if ok:
        ensure_transition(current, target)
    else:
        with pytest.raises(ReviewError):
            ensure_transition(current, target)


# --- pipeline actions --------------------------------------------------------------------

@respx.mock
def test_approve_after_live_check_confirms_price(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    runs = conn.execute("SELECT COUNT(*) FROM fetch_runs").fetchone()[0]
    price_api(58)
    decision = pipeline.approve(ctx, conn, deal_id, note="bom deal", actor="test")
    deal = decision.deal
    assert decision.check.valid and deal.status == "approved" and deal.review_note == "bom deal"
    assert deal.reviewed_at == decision.event.created_at
    # The approval's live check is a gate only (D26): no run stored, like the review Function.
    assert conn.execute("SELECT COUNT(*) FROM fetch_runs").fetchone()[0] == runs


@respx.mock
def test_deal_check_expires_deal_when_price_moved(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    full_run = db.latest_completed_run_id(conn)
    price_api(80)
    deal, check = pipeline.live_check(ctx, conn, deal_id)
    assert not check.valid and deal.status == "expired" and deal.expired_reason == "o preço subiu para 80 €"
    assert (ctx.output_dir / "2026-10-12" / f"deal-LIS-LON-{deal_id}" / "EXPIRADO.txt").exists()
    # The check is stored as its own run but never becomes the "latest" full collection.
    scope = conn.execute("SELECT scope, n_requests FROM fetch_runs ORDER BY id DESC LIMIT 1").fetchone()
    assert tuple(scope) == ("live_check", 1)
    assert db.latest_completed_run_id(conn) == full_run


@respx.mock
def test_cannot_approve_without_affiliate_link(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn, with_link=False)
    with pytest.raises(ReviewError, match="link de afiliado"):
        pipeline.approve(ctx, conn, deal_id, actor="test")


@respx.mock
def test_live_check_api_failure_leaves_deal_untouched(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    respx.get(API_URL).mock(return_value=httpx.Response(401, text="bad token"))
    with pytest.raises(ReviewError, match="Não foi possível verificar"):
        pipeline.approve(ctx, conn, deal_id, actor="test")
    deal, _ = db.get_deal(conn, deal_id)
    assert deal.status == "rendered" and deal.last_checked_at is None
    assert ctx.object_store.list("review/") == []


@respx.mock
def test_reject_and_publish(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    with pytest.raises(ReviewError):
        pipeline.mark_published(ctx, conn, deal_id, actor="test")   # must be approved first
    price_api(58)
    pipeline.approve(ctx, conn, deal_id, actor="test")
    with pytest.raises(ReviewError, match="https"):
        pipeline.mark_published(ctx, conn, deal_id, "instagram.com/p/x", actor="test")
    deal = pipeline.mark_published(ctx, conn, deal_id, "https://www.instagram.com/p/abc/",
                                   actor="test").deal
    assert deal.status == "published" and deal.post_url.endswith("/p/abc/")
    with pytest.raises(ReviewError):
        pipeline.reject(ctx, conn, deal_id, actor="test")      # published is final


@respx.mock
def test_approved_deals_are_still_rechecked(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    price_api(58)
    pipeline.approve(ctx, conn, deal_id, actor="test")
    price_api(90)
    pipeline.run_collect(ctx, conn)
    [(deal, _, check)] = pipeline.run_recheck(ctx, conn)
    assert deal.id == deal_id and deal.status == "expired"


# --- web page ----------------------------------------------------------------------------

@pytest.fixture
def web(ctx):
    conn = pipeline.open_db(ctx)
    return TestClient(create_app(ctx)), conn


@respx.mock
def test_page_and_queue(web, ctx):
    client, conn = web
    deal_id = rendered_deal(ctx, conn)
    assert "Fila de aprovação" in client.get("/").text
    data = client.get("/api/deals", params={"tab": "queue"}).json()
    assert data["counts"] == {"queue": 1, "approved": 0, "published": 0, "closed": 0}
    [d] = data["deals"]
    assert d["id"] == deal_id and d["headline"] == "Lisboa → Londres" and d["price"] == "58 €"
    assert d["caption"] == "legenda de teste" and len(d["slides"]) == 3
    assert d["affiliate_url"].startswith("https://aviasales.tpo.lu/")
    slide = client.get(d["slides"][0])
    assert slide.status_code == 200 and slide.content == PNG


@respx.mock
def test_web_approve_then_conflict(web, ctx):
    client, conn = web
    deal_id = rendered_deal(ctx, conn)
    price_api(58)
    r = client.post(f"/api/deals/{deal_id}/approve", json={"note": None})
    assert r.status_code == 200 and r.json()["check"]["valid"] and r.json()["deal"]["status"] == "approved"
    again = client.post(f"/api/deals/{deal_id}/approve", json={})
    assert again.status_code == 409 and "aprovado" in again.json()["detail"]
    r = client.post(f"/api/deals/{deal_id}/published", json={"post_url": "https://www.instagram.com/p/x/"})
    assert r.json()["deal"]["status"] == "published"


def test_web_rejects_bad_input(web):
    client, _ = web
    assert client.get("/api/deals", params={"tab": "nope"}).status_code == 400
    assert client.get("/deals/1/slides/..%2Fmeta.json").status_code == 404
    assert client.get("/deals/999/slides/slide_01.png").status_code == 404
    assert client.post("/api/deals/999/reject", json={}).status_code == 404
