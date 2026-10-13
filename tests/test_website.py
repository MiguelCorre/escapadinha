"""Public website: only approved deals go public, expired pages stay but say so, links resolve."""

import re
import shutil
from datetime import timedelta
from pathlib import Path

import pytest
import respx
from PIL import Image

from escapadinha import pipeline
from escapadinha.storage import db
from escapadinha.website import build_site, slugify
from escapadinha.website import deploy as site_deploy
from test_pipeline import ctx, seed_history  # noqa: F401
from test_review import price_api, rendered_deal


def real_slides(conn, deal_id):
    """Replace the fake PNG bytes from rendered_deal with small real images."""
    deal, _ = db.get_deal(conn, deal_id)
    for png in Path(deal.output_path).glob("slide_*.png"):
        Image.new("RGB", (108, 135), (200, 80, 60)).save(png)


def approved_deal(ctx, conn):
    deal_id = rendered_deal(ctx, conn)
    real_slides(conn, deal_id)
    price_api(58)
    deal, check = pipeline.approve(ctx, conn, deal_id)
    assert check.valid and deal.status == "approved"
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
    assert "https://ondestaanocas.pages.dev/voos/lisboa-londres/" in sitemap
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
    pipeline.reject(conn, rejected, "datas fracas")
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
    assert site_deploy.deploy(ctx) == (True, "https://abc123.ondestaanocas.pages.dev")
    assert site_deploy.deploy(ctx) == (False, "site unchanged since last deploy, skipped")
    assert site_deploy.deploy(ctx, force=True)[0]
    assert len(calls) == 2 and calls[0][:2] == ("pages", "deploy")


def test_deploy_requires_keys(ctx, monkeypatch):
    conn = pipeline.open_db(ctx)
    build_site(ctx, conn)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    with pytest.raises(site_deploy.DeployError, match="CLOUDFLARE_API_TOKEN"):
        site_deploy.deploy(ctx)


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
