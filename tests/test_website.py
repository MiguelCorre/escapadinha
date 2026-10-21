"""What the website shares with the pipeline (slugs, partner links) and the deploy of the Astro
build (D35). The pages themselves are tested in `web/test/` and `tests/test_web_build.py`."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
import respx
from PIL import Image

from escapadinha import pipeline, site_data
from escapadinha.storage import db
from escapadinha.website import deploy as site_deploy
from escapadinha.website import node, slugify
from test_pipeline import ctx, mock_links, seed_history  # noqa: F401
from test_review import price_api, rendered_deal
from test_traceability import build_scenario, store_run


def real_slides(conn, deal_id):
    """Replace the fake PNG bytes from rendered_deal with small real images."""
    deal, _ = db.get_deal(conn, deal_id)
    for png in Path(deal.output_path).glob("slide_*.png"):
        Image.new("RGB", (108, 135), (200, 80, 60)).save(png)


def approved_deal(ctx, conn):
    deal_id = rendered_deal(ctx, conn)
    real_slides(conn, deal_id)
    price_api(58)
    decision = pipeline.approve(ctx, conn, deal_id, actor="test")
    pipeline.apply_review_events(ctx, conn)     # already applied without R2; with R2, as a run would
    assert decision.check.valid and db.get_deal(conn, deal_id)[0].status == "approved"
    return deal_id


def test_slugify():
    assert slugify("Amesterdão") == "amesterdao"
    assert slugify("Onde está a Nocas?") == "onde-esta-a-nocas"


# --- partner links for low prices (D24) ------------------------------------------------

@respx.mock
def test_a_failed_low_price_link_exports_no_link_and_is_retried(ctx, tmp_path):
    conn = pipeline.open_db(ctx)
    mock_links()
    s = build_scenario(ctx, conn)
    respx.routes.clear()
    mock_links(ok=False)
    site_data.export_site_data(ctx, conn, tmp_path / "data")

    def link(oid: int) -> str | None:
        doc = json.loads((tmp_path / "data" / "low-prices" / "LIS.json").read_text("utf-8"))
        return {r[0]: r[doc["cols"].index("link")] for r in doc["rows"]}[oid]

    assert link(s.low_only[0]) is None
    error = conn.execute("SELECT error FROM partner_links WHERE observation_id = ?",
                         (s.low_only[0],)).fetchone()[0]
    assert error == "trs is not subscribed for brand"
    respx.routes.clear()
    mock_links()
    store_run(conn, db.observations_seen_since(conn, db.latest_completed_run_id(conn)))
    site_data.export_site_data(ctx, conn, tmp_path / "data")      # the next run retries it
    assert link(s.low_only[0]) == f"https://aviasales.tpo.lu/site-low-{s.low_only[0]}"


def test_partner_links_upsert_and_prune(ctx):
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=2, price=100)
    ids = [r[0] for r in conn.execute("SELECT id FROM price_observations ORDER BY id")]
    db.save_partner_links(conn, 7, {ids[0]: (None, "failed"), ids[1]: ("https://x/1", None)})
    db.save_partner_links(conn, 7, {ids[0]: ("https://x/0", None)})          # retry succeeded
    assert db.partner_links(conn, 7, ids) == {ids[0]: ("https://x/0", None),
                                              ids[1]: ("https://x/1", None)}
    assert db.partner_links(conn, 8, ids) == {}                              # per Project
    assert db.prune_partner_links(conn, db.utcnow() - timedelta(days=1)) == 0
    assert db.prune_partner_links(conn, db.utcnow() + timedelta(seconds=1)) == 2


# --- deploy -------------------------------------------------------------------------

def test_content_hash_ignores_build_timestamp(tmp_path):
    (tmp_path / "index.html").write_text("<p>Atualizado a 13/10/2026 às 10:00</p><p>x</p>")
    first = site_deploy.content_hash(tmp_path)
    (tmp_path / "index.html").write_text("<p>Atualizado a 13/10/2026 às 12:00</p><p>x</p>")
    assert site_deploy.content_hash(tmp_path) == first
    (tmp_path / "index.html").write_text("<p>Atualizado a 13/10/2026 às 12:00</p><p>y</p>")
    assert site_deploy.content_hash(tmp_path) != first


def test_deploy_skips_unchanged_site(ctx, monkeypatch):
    """The deploy uploads the Astro build (web/dist, D35), and only when it changed."""
    conn = pipeline.open_db(ctx)
    dist = node.dist_dir(ctx)
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<p>Atualizado a 13/10/2026 às 10:00</p><p>x</p>", "utf-8")
    calls = []

    class Done:
        returncode, stderr = 0, ""
        stdout = "✨ Deployment complete! https://abc123.ondestaanocas.pages.dev"

    monkeypatch.setattr(site_deploy, "_wrangler",
                        lambda c, *args, cwd=None, until=None: calls.append(args) or Done())
    assert site_deploy.deploy(ctx, conn) == (True, "https://abc123.ondestaanocas.pages.dev")
    assert site_deploy.deploy(ctx, conn) == (False, "site unchanged since last deploy, skipped")
    assert site_deploy.deploy(ctx, conn, force=True)[0]
    assert len(calls) == 2 and calls[0][:3] == ("pages", "deploy", str(dist.resolve()))


def test_deploy_requires_keys(ctx, monkeypatch):
    conn = pipeline.open_db(ctx)
    dist = node.dist_dir(ctx)
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<p>x</p>", "utf-8")
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    with pytest.raises(site_deploy.DeployError, match="CLOUDFLARE_API_TOKEN"):
        site_deploy.deploy(ctx, conn)


@respx.mock
def test_create_project_uses_rest_api(ctx, monkeypatch):
    import httpx
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acc")
    base = "https://api.cloudflare.com/client/v4/accounts/acc/pages/projects"
    respx.get(f"{base}/ondestaanocas").mock(return_value=httpx.Response(404, json={"success": False}))
    created = respx.post(base).mock(return_value=httpx.Response(200, json={
        "success": True, "result": {"subdomain": "ondestaanocas.pages.dev"}}))
    assert site_deploy.create_project(ctx).endswith("https://ondestaanocas.pages.dev")
    assert created.calls.last.request.headers["Authorization"] == "Bearer tok"
    assert b'"production_branch":"main"' in created.calls.last.request.content.replace(b" ", b"")
    respx.get(f"{base}/ondestaanocas").mock(return_value=httpx.Response(200, json={
        "success": True, "result": {"subdomain": "ondestaanocas.pages.dev"}}))
    assert "already exists" in site_deploy.create_project(ctx)
