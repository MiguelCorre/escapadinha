"""Every URL of the old site keeps working on the Astro site (D35): a page, or one 301 to a page.

`website.crawl` checks a sitemap against a build (`_redirects` applied like Pages does) or
against the live site (`escapadinha site crawl`, crawled daily in the cutover week). The
integration test builds the real Astro site (npm, `web/`) from a database whose redirect history
is the one the old Jinja site left, and crawls the old URLs: those of the committed sitemap the
Jinja site served on 2026-10-14 (`docs/cutover/`), plus the pages it published outside it.
"""

from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from escapadinha import cli, pipeline, routes, site_data
from escapadinha.storage import db
from escapadinha.website import astro, crawl, route_slug
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
def test_a_sitemap_url_is_fetched_with_a_client_that_is_closed_afterwards(monkeypatch):
    respx.get("https://pontonomada.pt/sitemap.xml").respond(
        200, text="<urlset><url><loc>https://pontonomada.pt/</loc></url></urlset>")
    made = []
    real = httpx.Client

    def tracked(*args, **kwargs):
        made.append(real(*args, **kwargs))
        return made[-1]

    monkeypatch.setattr(crawl.httpx, "Client", tracked)
    assert crawl.sitemap_urls("https://pontonomada.pt/sitemap.xml") == ["https://pontonomada.pt/"]
    assert len(made) == 1 and made[0].is_closed
    with real() as mine:                                   # the caller's client stays open
        assert crawl.sitemap_urls("https://pontonomada.pt/sitemap.xml", mine)
        assert not mine.is_closed


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


OLD_SITEMAP = REPO / "docs" / "cutover" / "jinja-sitemap-2026-10-14.xml"


def test_the_old_sitemap_lists_only_pages_the_astro_site_still_builds():
    """The Jinja site's sitemap on cutover day: the home page, /sobre/, /privacidade/ and one
    page per route (/voos/<origem>-<destino>/), all of which the Astro site builds at the same
    path (route slugs are stable, `website.route_slug`)."""
    urls = crawl.sitemap_urls(str(OLD_SITEMAP))
    paths = {"/" + u.split("/", 3)[3] for u in urls}
    assert len(urls) == len(paths) == 363
    assert {"/", "/sobre/", "/privacidade/"} <= paths
    assert all(p.startswith("/voos/") and p.count("/") == 3
               for p in paths - {"/", "/sobre/", "/privacidade/"})


@needs_web
@respx.mock
def test_every_url_of_the_old_site_resolves_on_the_astro_build(ctx, tmp_path):
    """The old sitemap's URLs of this database's routes and static pages, plus what the Jinja
    site published outside its sitemap: a promotion that expired long ago (the Jinja site kept
    its page, the contract dropped it), its short alias and a Jinja guide."""
    conn = pipeline.open_db(ctx)
    deal_id = approved_deal(ctx, conn)
    db.set_deal_status(conn, deal_id, "expired")
    conn.execute("UPDATE deals SET last_checked_at = ? WHERE id = ?",
                 ((db.utcnow() - timedelta(days=40)).isoformat(), deal_id))
    conn.commit()
    route_paths = {f"route:{r.key}": f"/voos/{route_slug(ctx.config.origin_name(r.origin), r.city_pt)}/"
                   for r in routes.all_routes(conn, ctx.config.routes)}
    old_promo = f"/promos/{deal_id}-lisboa-londres/"
    pipeline.save_site_paths(conn, {                        # the history the Jinja builds left
        **{f"page:{p}": [p] for p in ("/", "/sobre/", "/privacidade/")},
        **{key: [path] for key, path in route_paths.items()},
        f"deal:{deal_id}": [old_promo], "guide:voos-baratos-dicas": ["/guias/voos-baratos-dicas/"]})

    base = "https://pontonomada.pt"
    known = {"/", "/sobre/", "/privacidade/", *route_paths.values()}
    urls = [u for u in crawl.sitemap_urls(str(OLD_SITEMAP)) if u.removeprefix(base) in known]
    assert len(urls) == len(known)                          # every route here was on the old site
    urls += [f"{base}{old_promo}", f"{base}/promos/{deal_id}", f"{base}/guias/voos-baratos-dicas/"]

    data = tmp_path / "data"
    site_data.export_site_data(ctx, conn, data, new_links=False)
    dist = tmp_path / "dist"
    astro.astro_build(WEB, data, dist)                      # the real build (npm, web/)
    astro.finish(ctx, conn, data, dist, content=WEB / "src" / "content")

    results = crawl.check_build(urls, dist)
    broken = [f"{r.path} {r.status} {r.detail}" for r in results if not r.ok]
    assert broken == [] and len(results) == len(urls) >= 15
    redirected = {r.path: r.target for r in results if r.status == 301}
    assert redirected[old_promo] == "/voos/lisboa-londres/"
    assert redirected["/guias/voos-baratos-dicas/"] == "/dicas/voos-baratos/"   # approved 2026-10-15
