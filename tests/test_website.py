"""Public website: only approved deals go public, expired pages stay but say so, links resolve."""

import json
import re
import shutil
from datetime import timedelta
from pathlib import Path

import pytest
import respx
from PIL import Image

from escapadinha import i18n_pt as pt
from escapadinha import pipeline
from escapadinha.presentation import SITE_DISCLOSURE
from escapadinha.storage import db
from escapadinha.website import build_site, slugify
from escapadinha.website import deploy as site_deploy
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


def html(ctx, rel):
    return (ctx.site_dir / rel).read_text("utf-8")


def internal_links_resolve(site_dir: Path) -> list[str]:
    broken = []
    for page in site_dir.rglob("*.html"):
        for href in re.findall(r'(?:href|src)="(/[^"#?]*)', page.read_text("utf-8")):
            target = site_dir / href.lstrip("/")
            if not (target.is_file() or (target / "index.html").is_file()):
                broken.append(f"{page.relative_to(site_dir)} -> {href}")
    return broken


def test_slugify():
    assert slugify("Amesterdão") == "amesterdao"
    assert slugify("Onde está a Nocas?") == "onde-esta-a-nocas"


def test_empty_site_has_routes_and_static_pages(ctx):
    conn = pipeline.open_db(ctx)
    summary = build_site(ctx, conn)
    assert summary["live_deals"] == 0 and summary["routes"] == 10
    assert "Neste momento não há promoções ativas" in html(ctx, "index.html")
    for rel in ("sobre/index.html", "privacidade/index.html", "404.html", "robots.txt",
                "voos/lisboa-paris/index.html", "voos/porto-milao/index.html"):
        assert (ctx.site_dir / rel).exists(), rel
    sitemap = html(ctx, "sitemap.xml")
    assert f"{ctx.config.site.base_url}/voos/lisboa-londres/" in sitemap
    assert not internal_links_resolve(ctx.site_dir)


@respx.mock
def test_approved_deal_is_published_with_tracked_link(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = approved_deal(ctx, conn)
    summary = build_site(ctx, conn)
    assert summary["live_deals"] == 1
    deal, _ = db.get_deal(conn, deal_id)
    page_rel = f"promos/{deal_id}-lisboa-londres/index.html"
    page = html(ctx, page_rel)
    assert f'href="{deal.affiliate_url}" rel="sponsored nofollow noopener"' in page
    assert "58 €" in page and "noindex" not in page and "Publicidade" in page
    assert f"/promos/{deal_id}-lisboa-londres/" in html(ctx, "index.html")
    assert f"/promos/{deal_id}-lisboa-londres/" in html(ctx, "sitemap.xml")
    img = ctx.site_dir / "img" / "promos" / str(deal_id)
    assert {p.name for p in img.iterdir()} == {"slide_01.webp", "slide_02.webp", "slide_03.webp",
                                                "thumb.webp", "og.jpg"}
    assert 'property="og:image"' in page
    assert not internal_links_resolve(ctx.site_dir)


@respx.mock
def test_expired_after_approval_keeps_page_without_booking(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = approved_deal(ctx, conn)
    price_api(90)
    pipeline.live_check(ctx, conn, deal_id)                   # price moved -> expired
    build_site(ctx, conn)
    page = html(ctx, f"promos/{deal_id}-lisboa-londres/index.html")
    assert "Esta promoção já expirou" in page and '<meta name="robots" content="noindex">' in page
    assert "Ver voo e reservar" not in page and "o preço subiu para 90 €" in page
    assert f"/promos/{deal_id}-" not in html(ctx, "index.html")
    assert f"/promos/{deal_id}-" not in html(ctx, "sitemap.xml")
    assert f"/promos/{deal_id}-" in html(ctx, "voos/lisboa-londres/index.html")   # "recentes"


@respx.mock
def test_never_approved_deals_stay_private(ctx):
    conn = pipeline.open_db(ctx)
    rejected = rendered_deal(ctx, conn)
    pipeline.reject(ctx, conn, rejected, "datas fracas", actor="test")
    build_site(ctx, conn)
    assert not (ctx.site_dir / "promos").exists()


@respx.mock
def test_route_page_shows_typical_low_from_real_history(ctx):
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    build_site(ctx, conn)
    page = html(ctx, "voos/lisboa-londres/index.html")
    # seeded lows are 100/101/102 € on 22 days older than the freshness window
    assert '<td>novembro 2026</td><td class="num">101 €</td><td>22</td>' in page
    assert "Ainda estamos a recolher dados" in html(ctx, "voos/porto-berlim/index.html")


def test_guides_are_published_only_when_reviewed(ctx):
    conn = pipeline.open_db(ctx)
    build_site(ctx, conn)
    assert not (ctx.site_dir / "guias").exists()
    guide = ctx.guides_dir / "voos-baratos-dicas.yaml"
    guide.write_text(guide.read_text("utf-8").replace("reviewed: false", "reviewed: true"), "utf-8")
    build_site(ctx, conn)
    page = html(ctx, "guias/voos-baratos-dicas/index.html")
    assert "Compara Lisboa, Porto e Faro" in page
    assert "/guias/voos-baratos-dicas/" in html(ctx, "index.html")


# --- low prices on route pages (D24) ------------------------------------------------------

def low_rows(page: str) -> dict[int, str]:
    """observation id -> that low price's <li> markup."""
    return {int(oid): row for oid, row in
            re.findall(r'<li class="low" data-obs="(\d+)">(.*?)</li>', page, flags=re.S)}


@respx.mock
def test_route_page_lists_low_prices_with_found_date_and_tracked_link(ctx):
    links = mock_links()
    conn = pipeline.open_db(ctx)
    s = build_scenario(ctx, conn)
    summary = build_site(ctx, conn)
    page = html(ctx, "voos/lisboa-londres/index.html")
    rows = low_rows(page)
    assert set(rows) == set(s.low_only)               # the live promotion's offer isn't repeated
    obs = db.get_observation(conn, s.low_only[0])
    row = rows[obs.id]
    assert "80 €" in row and "−20% vs. habitual" in row and "Gatwick (LGW)" in row
    assert f"Encontrado a {obs.found_date:%d/%m/%Y}" in row                      # found date ...
    assert f"visto por nós a {pt.lisbon_timestamp(obs.fetched_at)}" in row      # ... vs fetched_at
    assert (f'href="https://aviasales.tpo.lu/site-low-{obs.id}" '
            'rel="sponsored nofollow noopener"') in row
    assert SITE_DISCLOSURE in page and "marker=" not in page
    sent = [l for call in links.calls for l in json.loads(call.request.content)["links"]]
    low_sent = [l for l in sent if l["sub_id"].startswith("site-low-")]
    assert all(l["url"].startswith("https://www.aviasales.pt/search/") for l in low_sent)
    assert "26 €" in html(ctx, "voos/lisboa-barcelona/index.html")   # low, never a promotion
    assert summary["low_prices"] == 4 and summary["low_prices_without_link"] == 0
    # Home unchanged: promotions only, no low prices.
    home = html(ctx, "index.html")
    assert 'class="low"' not in home and "Preços baixos" not in home and "80 €" not in home
    assert not internal_links_resolve(ctx.site_dir)


@respx.mock
def test_low_price_links_are_created_once_and_stored(ctx):
    links = mock_links()
    conn = pipeline.open_db(ctx)
    build_scenario(ctx, conn)
    before = links.call_count
    build_site(ctx, conn)
    made = links.call_count - before
    assert made == 1                                  # 4 low prices, one request (10 per request)
    stored = conn.execute("SELECT COUNT(*) FROM partner_links WHERE partner_url IS NOT NULL")
    assert stored.fetchone()[0] == 4
    summary = build_site(ctx, conn)
    assert links.call_count - before == made and summary["low_price_links_created"] == 0


@respx.mock
def test_new_links_per_build_are_capped_biggest_discounts_first(ctx):
    mock_links()
    conn = pipeline.open_db(ctx)
    s = build_scenario(ctx, conn)
    ctx.config.site.max_new_links_per_build = 1
    summary = build_site(ctx, conn)
    assert summary["low_price_links_created"] == 1 and summary["low_prices_without_link"] == 3
    # LIS-ROM 70 € is -42 %, the biggest discount: it gets the one link.
    assert "site-low-" in html(ctx, "voos/lisboa-roma/index.html")
    row = low_rows(html(ctx, "voos/lisboa-londres/index.html"))[s.low_only[0]]
    assert "Link de reserva indisponível" in row and "href" not in row
    assert build_site(ctx, conn)["low_price_links_created"] == 0    # the run's budget is spent
    for _ in range(2):                          # the next runs see the same offers again
        store_run(conn, db.observations_seen_since(conn, db.latest_completed_run_id(conn)))
        build_site(ctx, conn)
    row = low_rows(html(ctx, "voos/lisboa-londres/index.html"))[s.low_only[0]]
    assert f"site-low-{s.low_only[0]}" in row


@respx.mock
def test_failed_low_price_link_shows_no_button_and_is_retried(ctx):
    conn = pipeline.open_db(ctx)
    mock_links()
    s = build_scenario(ctx, conn)
    respx.routes.clear()
    mock_links(ok=False)
    build_site(ctx, conn)
    row = low_rows(html(ctx, "voos/lisboa-londres/index.html"))[s.low_only[0]]
    assert "Link de reserva indisponível" in row and "href" not in row
    assert "marker=" not in html(ctx, "voos/lisboa-londres/index.html")
    error = conn.execute("SELECT error FROM partner_links WHERE observation_id = ?",
                         (s.low_only[0],)).fetchone()[0]
    assert error == "trs is not subscribed for brand"
    respx.routes.clear()
    mock_links()
    build_site(ctx, conn)
    assert f"site-low-{s.low_only[0]}" in html(ctx, "voos/lisboa-londres/index.html")


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


@respx.mock
def test_low_prices_per_route_cap(ctx):
    mock_links()
    conn = pipeline.open_db(ctx)
    build_scenario(ctx, conn)
    ctx.config.site.low_prices_per_route = 1
    build_site(ctx, conn)
    assert len(low_rows(html(ctx, "voos/lisboa-londres/index.html"))) == 1
    ctx.config.site.low_prices_per_route = 0
    build_site(ctx, conn)
    assert "Não há preços baixos recentes" in html(ctx, "voos/lisboa-londres/index.html")


# --- deploy -------------------------------------------------------------------------

def test_content_hash_ignores_build_timestamp(tmp_path):
    (tmp_path / "index.html").write_text("<p>Atualizado a 13/10/2026 às 10:00</p><p>x</p>")
    first = site_deploy.content_hash(tmp_path)
    (tmp_path / "index.html").write_text("<p>Atualizado a 13/10/2026 às 12:00</p><p>x</p>")
    assert site_deploy.content_hash(tmp_path) == first
    (tmp_path / "index.html").write_text("<p>Atualizado a 13/10/2026 às 12:00</p><p>y</p>")
    assert site_deploy.content_hash(tmp_path) != first


def test_deploy_skips_unchanged_site(ctx, monkeypatch):
    conn = pipeline.open_db(ctx)
    build_site(ctx, conn)
    calls = []

    class Done:
        returncode, stderr = 0, ""
        stdout = "✨ Deployment complete! https://abc123.ondestaanocas.pages.dev"

    monkeypatch.setattr(site_deploy, "_wrangler", lambda c, *args: calls.append(args) or Done())
    assert site_deploy.deploy(ctx, conn) == (True, "https://abc123.ondestaanocas.pages.dev")
    assert site_deploy.deploy(ctx, conn) == (False, "site unchanged since last deploy, skipped")
    assert site_deploy.deploy(ctx, conn, force=True)[0]
    assert len(calls) == 2 and calls[0][:2] == ("pages", "deploy")


def test_deploy_requires_keys(ctx, monkeypatch):
    conn = pipeline.open_db(ctx)
    build_site(ctx, conn)
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
