"""Every URL of the old site keeps working on the Astro site (D35): a page, or one 301 to a page.

`website.crawl` checks a sitemap against a build (`_redirects` applied like Pages does) or
against the live site (`escapadinha site crawl`, for the week before the Jinja code is deleted).
The integration test builds the legacy Jinja site and the real Astro site (npm, `web/`) from the
same database and crawls every page the old one published.
"""

import shutil
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from escapadinha import cli, pipeline, site_data
from escapadinha.storage import db
from escapadinha.website import astro, build_site, crawl
from test_pipeline import REPO, ctx  # noqa: F401
from test_website import approved_deal


def dist_with(tmp_path: Path, pages: list[str], redirects: str = "") -> Path:
    dist = tmp_path / "dist"
    for path in pages:
        page = dist / path.strip("/") / "index.html" if path.endswith("/") else dist / path.strip("/")
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("<p>x</p>", "utf-8")
    (dist / "_redirects").write_text("# generated\n" + redirects, "utf-8")
    return dist


def sitemap(tmp_path: Path, urls: list[str]) -> Path:
    path = tmp_path / "sitemap.xml"
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org'
                    '/schemas/sitemap/0.9">\n' + "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls)
                    + "</urlset>\n", "utf-8")
    return path


def test_a_build_resolves_pages_and_redirects_and_reports_what_it_cannot(tmp_path):
    dist = dist_with(tmp_path, ["/", "/voos/lisboa-paris/", "/dicas/"],
                     "/guias/velho/ /dicas/ 301\n/promos/1 /promos/1-lisboa-paris/ 301\n")
    base = "https://pontonomada.pt"
    urls = crawl.sitemap_urls(str(sitemap(tmp_path, [
        f"{base}/", f"{base}/voos/lisboa-paris/", f"{base}/guias/velho/", f"{base}/voos/sumiu/",
        f"{base}/promos/1"])))
    results = crawl.check_build(urls, dist)
    by_path = {r.path: r for r in results}
    assert by_path["/"].ok and by_path["/"].status == 200
    assert by_path["/guias/velho/"].ok and by_path["/guias/velho/"].status == 301
    assert by_path["/guias/velho/"].target == "/dicas/"
    assert not by_path["/voos/sumiu/"].ok and by_path["/voos/sumiu/"].status == 404
    # A redirect to a page that isn't there is as broken as a missing page.
    assert not by_path["/promos/1"].ok and "/promos/1-lisboa-paris/" in by_path["/promos/1"].detail


@respx.mock
def test_the_live_crawl_reports_anything_but_200_or_a_301_to_a_200(tmp_path):
    base = "https://pontonomada.pt"
    respx.get(f"{base}/").mock(return_value=httpx.Response(200))
    respx.get(f"{base}/promos/1").mock(return_value=httpx.Response(
        301, headers={"location": "/promos/1-lisboa-paris/"}))
    respx.get(f"{base}/promos/1-lisboa-paris/").mock(return_value=httpx.Response(200))
    respx.get(f"{base}/guias/x/").mock(return_value=httpx.Response(301, headers={"location": "/dicas/"}))
    respx.get(f"{base}/dicas/").mock(return_value=httpx.Response(404))
    respx.get(f"{base}/voos/sumiu/").mock(return_value=httpx.Response(404))
    urls = [f"{base}/", f"{base}/promos/1", f"{base}/guias/x/", f"{base}/voos/sumiu/"]
    with httpx.Client() as client:
        results = crawl.check_live(urls, client)
    assert [r.ok for r in results] == [True, True, False, False]
    assert results[2].status == 301 and "404" in results[2].detail


@respx.mock
def test_site_crawl_reads_a_sitemap_url_and_can_crawl_another_host(tmp_path, monkeypatch):
    monkeypatch.setenv("ESCAPADINHA_HOME", str(REPO))
    respx.get("https://pontonomada.pt/sitemap.xml").mock(return_value=httpx.Response(
        200, text=sitemap(tmp_path, ["https://pontonomada.pt/", "https://pontonomada.pt/sobre/"])
        .read_text("utf-8")))
    respx.get("https://preview.ondestaanocas.pages.dev/").mock(return_value=httpx.Response(200))
    respx.get("https://preview.ondestaanocas.pages.dev/sobre/").mock(return_value=httpx.Response(500))
    result = CliRunner().invoke(cli.app, ["site", "crawl", "--sitemap",
                                          "https://pontonomada.pt/sitemap.xml",
                                          "--base", "https://preview.ondestaanocas.pages.dev"])
    assert result.exit_code == 1, result.output
    out = " ".join(result.output.split())
    assert "2 URLs: 1 ok" in out and "/sobre/ 500" in out


def test_site_crawl_checks_a_local_build(tmp_path, monkeypatch):
    monkeypatch.setenv("ESCAPADINHA_HOME", str(REPO))
    dist = dist_with(tmp_path, ["/", "/sobre/"])
    result = CliRunner().invoke(cli.app, ["site", "crawl", "--sitemap", str(sitemap(
        tmp_path, ["https://pontonomada.pt/", "https://pontonomada.pt/sobre/"])), "--dist", str(dist)])
    assert result.exit_code == 0, result.output
    assert "2 URLs: 2 ok" in " ".join(result.output.split())


# --- the old site against the real Astro build ---------------------------------------------------

WEB = REPO / "web"
needs_web = pytest.mark.skipif(not (WEB / "node_modules" / "astro").is_dir(),
                               reason="web/node_modules missing: run `npm ci` in web/")


def jinja_urls(site: Path) -> list[str]:
    """Every URL the old site served: its sitemap, every page (expired promotions and guides
    included, which the sitemap leaves out) and the sources of its _redirects."""
    urls = crawl.sitemap_urls(str(site / "sitemap.xml"))
    base = urls[0].split("/", 3)[:3]
    for page in site.rglob("index.html"):
        rel = page.parent.relative_to(site).as_posix()
        urls.append("/".join(base) + ("/" if rel == "." else f"/{rel}/"))
    urls += ["/".join(base) + source for source in crawl.parse_redirects(
        (site / "_redirects").read_text("utf-8"))]
    return sorted(set(urls))


@needs_web
@respx.mock
def test_every_url_of_the_old_site_resolves_on_the_astro_build(ctx, tmp_path):
    """The Jinja site (still buildable until #23 phase 2) and the Astro site from one database:
    a promotion that expired long ago (the Jinja site kept its page, the contract dropped it)
    and a reviewed Jinja guide, besides the routes and static pages."""
    guide = ctx.guides_dir / "voos-baratos-dicas.yaml"
    guide.write_text(guide.read_text("utf-8").replace("reviewed: false", "reviewed: true"), "utf-8")
    conn = pipeline.open_db(ctx)
    deal_id = approved_deal(ctx, conn)
    build_site(ctx, conn)                                   # the old site, while it was live
    db.set_deal_status(conn, deal_id, "expired")
    conn.execute("UPDATE deals SET last_checked_at = ? WHERE id = ?",
                 ((db.utcnow() - timedelta(days=40)).isoformat(), deal_id))
    conn.commit()
    old = ctx.root / "old-site"
    shutil.copytree(ctx.site_dir, old)
    build_site(ctx, conn)                                   # its last build: the expired page
    urls = sorted(set(jinja_urls(old)) | set(jinja_urls(ctx.site_dir)))
    assert any(f"/promos/{deal_id}-lisboa-londres/" in u for u in urls)
    assert any("/guias/voos-baratos-dicas/" in u for u in urls)

    data = tmp_path / "data"
    site_data.export_site_data(ctx, conn, data, new_links=False)
    dist = tmp_path / "dist"
    astro.astro_build(WEB, data, dist)                      # the real build (npm, web/)
    astro.finish(ctx, conn, data, dist, content=WEB / "src" / "content")

    results = crawl.check_build(urls, dist)
    broken = [f"{r.path} {r.status} {r.detail}" for r in results if not r.ok]
    assert broken == [] and len(results) == len(urls) >= 15
    redirected = {r.path: r.target for r in results if r.status == 301}
    assert redirected[f"/promos/{deal_id}-lisboa-londres/"] == "/voos/lisboa-londres/"
    assert redirected["/guias/voos-baratos-dicas/"] == "/dicas/"     # the tip is still a draft
