"""The Astro site built by the pipeline (D35): npm ci only when needed, `npm run build` on the
exported contract, the promotion images the contract names, `_redirects` and `_headers`."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
import respx

from escapadinha import pipeline, site_data
from escapadinha.storage import db
from escapadinha.website import astro
from escapadinha.website import deploy as site_deploy
from test_pipeline import REPO, ctx  # noqa: F401
from test_website import approved_deal

STATIC_PAGES = ("/", "/sobre/", "/privacidade/", "/partidas/", "/destinos/", "/explorar/",
                "/roteiros/", "/dicas/")


def contract_pages(data: Path) -> list[str]:
    """Every page path the contract names, plus the static pages: what `astro build` writes."""
    read = lambda name: json.loads((data / name).read_text("utf-8"))  # noqa: E731
    paths = list(STATIC_PAGES)
    paths += [o["path"] for o in read("origins.json")["origins"]]
    paths += [r["path"] for r in read("routes.json")["routes"]]
    paths += [d["path"] for d in read("destinations.json")["destinations"]]
    paths += [p["path"] for p in read("promotions.json")["promotions"]]
    paths += [o["path"] for p in read("pontes.json")["pontes"] for o in p["origins"]]
    return paths


class FakeNpm:
    """Stands in for npm (the Node boundary): `ci` makes node_modules, `run build` writes one
    page per contract path into web/dist, the way the Astro build lays them out."""

    def __init__(self):
        self.calls: list[dict] = []
        self.extra_pages: list[str] = []

    def __call__(self, web: Path, *args: str, env: dict[str, str]) -> None:
        self.calls.append({"args": args, "env": env})
        if args == ("ci",):
            (web / "node_modules").mkdir(parents=True, exist_ok=True)
        elif args == ("run", "build"):
            data = Path(env["SITE_DATA_DIR"])
            meta = json.loads((data / "meta.json").read_text("utf-8"))
            fixture = ' data-fixture="true"' if meta["fixture"] else ""
            dist = web / "dist"
            for path in contract_pages(data) + self.extra_pages:
                page = dist / path.strip("/") / "index.html"
                page.parent.mkdir(parents=True, exist_ok=True)
                page.write_text(f'<html lang="pt-PT"{fixture}><p>{path}</p><footer>Atualizado a '
                                f'<span class="num">{meta["generated_at"]}</span></footer></html>',
                                "utf-8")
            (dist / "404.html").write_text("<html><p>404</p></html>", "utf-8")
            (dist / "favicon.svg").write_text("<svg/>", "utf-8")

    def ran(self, *args: str) -> int:
        return sum(c["args"] == args for c in self.calls)


@pytest.fixture
def npm(monkeypatch):
    fake = FakeNpm()
    monkeypatch.setattr(astro, "_run_npm", fake)
    return fake


def web_package(root: Path) -> Path:
    web = root / "web"
    web.mkdir(parents=True, exist_ok=True)
    (web / "package-lock.json").write_text('{"lockfileVersion": 3}\n', "utf-8")
    return web


# --- npm -----------------------------------------------------------------------------------

def test_npm_ci_runs_only_when_node_modules_is_missing_or_the_lockfile_changed(tmp_path, npm):
    web = web_package(tmp_path)
    assert astro.ensure_dependencies(web) is True
    assert astro.ensure_dependencies(web) is False            # stamp matches: nothing to do
    (web / "package-lock.json").write_text('{"lockfileVersion": 3, "x": 1}\n', "utf-8")
    assert astro.ensure_dependencies(web) is True             # lockfile changed
    assert astro.ensure_dependencies(web) is False
    (web / "node_modules" / astro.STAMP).unlink()
    assert astro.ensure_dependencies(web) is True             # installed by hand: no stamp
    assert npm.ran("ci") == 3


def test_npm_is_found_on_windows_without_it_on_the_path(tmp_path, monkeypatch):
    """The PC's scheduled task may run without Node on its PATH: npm.cmd in the install dir."""
    from escapadinha.website import deploy as site_deploy
    monkeypatch.setattr(astro.shutil, "which", lambda name: None)
    monkeypatch.setattr(site_deploy, "NODE_DIRS", [tmp_path])
    (tmp_path / "npm.cmd").write_text("@echo off\n", "utf-8")
    assert astro.npm() == str(tmp_path / "npm.cmd")
    (tmp_path / "npm.cmd").unlink()
    with pytest.raises(astro.BuildError, match="npm not found"):
        astro.npm()


# --- the build -------------------------------------------------------------------------------

@respx.mock
def test_the_build_reads_the_export_and_adds_the_promotion_images(ctx, npm):
    web = web_package(ctx.root)
    conn = pipeline.open_db(ctx)
    deal_id = approved_deal(ctx, conn)
    data = site_data.default_dir(ctx)
    export = site_data.export_site_data(ctx, conn, data, new_links=False)
    summary = astro.build(ctx, conn)
    [build] = [c for c in npm.calls if c["args"] == ("run", "build")]
    assert Path(build["env"]["SITE_DATA_DIR"]) == data.resolve()
    assert build["env"]["ASTRO_TELEMETRY_DISABLED"] == "1"
    [promo] = export.files["promotions.json"]["promotions"]
    images = promo["images"]
    for path in [*images["slides"], images["thumb"], images["og"]]:
        assert (web / "dist" / path.lstrip("/")).is_file(), path
    assert promo["id"] == deal_id
    assert summary.pages["promos"] == 1 and summary.pages["voos"] == 10
    assert summary.images == 5 and summary.missing_images == []
    assert summary.size_bytes > 0


def test_the_build_needs_the_export_first(ctx, npm):
    web_package(ctx.root)
    conn = pipeline.open_db(ctx)
    with pytest.raises(astro.BuildError, match="export site-data"):
        astro.build(ctx, conn)
    assert not npm.calls


def test_a_failed_npm_build_stops_with_its_output(ctx, monkeypatch):
    web_package(ctx.root)
    conn = pipeline.open_db(ctx)
    site_data.export_site_data(ctx, conn, site_data.default_dir(ctx), new_links=False)

    def failing(web, *args, env):
        if args == ("ci",):
            (web / "node_modules").mkdir()
            return
        raise astro.BuildError("npm run build failed:\nsite data invalid: routes.json")

    monkeypatch.setattr(astro, "_run_npm", failing)
    with pytest.raises(astro.BuildError, match="routes.json"):
        astro.build(ctx, conn)


# --- _redirects and _headers -----------------------------------------------------------------

def rules(web: Path) -> dict[str, str]:
    lines = (web / "dist" / "_redirects").read_text("utf-8").splitlines()
    return {s: t for s, t, code in (line.split() for line in lines
                                    if line and not line.startswith("#")) if code == "301"}


@respx.mock
def test_old_promotion_links_and_renamed_slugs_redirect_to_the_current_pages(ctx, npm):
    web = web_package(ctx.root)
    conn = pipeline.open_db(ctx)
    deal_id = approved_deal(ctx, conn)
    pipeline.save_site_paths(conn, {
        f"deal:{deal_id}": [f"/promos/{deal_id}-lisboa-londres-antigo/"],
        "route:LIS-LON": ["/voos/lisboa-londres-antigo/"],
        "destination:LON": ["/destinos/londres-antigo/"],
        "route:LIS-XXX": ["/voos/lisboa-desaparecido/"],          # route gone: an honest 404
    })
    site_data.export_site_data(ctx, conn, site_data.default_dir(ctx), new_links=False)
    summary = astro.build(ctx, conn)
    r = rules(web)
    promo = f"/promos/{deal_id}-lisboa-londres/"
    assert r[f"/promos/{deal_id}"] == r[f"/promos/{deal_id}/"] == promo          # short alias
    assert r[f"/promos/{deal_id}-lisboa-londres-antigo/"] == promo
    assert r[f"/promos/{deal_id}-lisboa-londres-antigo"] == promo
    assert r["/voos/lisboa-londres-antigo/"] == "/voos/lisboa-londres/"
    assert r["/destinos/londres-antigo/"] == "/destinos/londres/"
    assert "/voos/lisboa-desaparecido/" not in r
    assert not any(source in (promo, "/voos/lisboa-londres/", "/") for source in r)  # never a page
    assert summary.redirects == len(r) and summary.skipped_redirects == []
    # The current paths join the history (stable keys), so a later rename gets its 301.
    history = pipeline.site_paths(ctx, conn)
    assert promo in history[f"deal:{deal_id}"] and "/partidas/lisboa/" in history["origin:LIS"]
    assert history["route:LIS-LON"][-1] == "/voos/lisboa-londres/"
    headers = (web / "dist" / "_headers").read_text("utf-8")
    assert "https://ondestaanocas.pages.dev/*\n  X-Robots-Tag: noindex" in headers


@respx.mock
def test_a_promotion_no_longer_in_the_export_redirects_to_its_route(ctx, npm):
    """The Jinja site kept expired promotions forever; the contract keeps them 30 days (D27).
    An older one's links go to its route page instead of a 404."""
    web = web_package(ctx.root)
    conn = pipeline.open_db(ctx)
    deal_id = approved_deal(ctx, conn)
    pipeline.save_site_paths(conn, {f"deal:{deal_id}": [f"/promos/{deal_id}-lisboa-londres/"]})
    db.set_deal_status(conn, deal_id, "expired")
    conn.execute("UPDATE deals SET last_checked_at = ? WHERE id = ?",
                 ((db.utcnow() - timedelta(days=40)).isoformat(), deal_id))
    conn.commit()
    export = site_data.export_site_data(ctx, conn, site_data.default_dir(ctx), new_links=False)
    assert export.files["promotions.json"]["promotions"] == []
    astro.build(ctx, conn)
    r = rules(web)
    assert r[f"/promos/{deal_id}-lisboa-londres/"] == "/voos/lisboa-londres/"
    assert r[f"/promos/{deal_id}"] == "/voos/lisboa-londres/"


def test_old_guides_go_to_the_tip_that_replaced_them_or_the_tips_index(ctx, npm):
    web = web_package(ctx.root)
    tips = web / "src" / "content" / "tips"
    tips.mkdir(parents=True)
    (tips / "voos-baratos.mdx").write_text(
        "---\ntitle: Voos baratos\nlegacy_path: /guias/voos-baratos-dicas/\nreviewed: true\n---\n\nTexto.\n",
        "utf-8")
    (tips / "rascunho.mdx").write_text(
        "---\ntitle: Rascunho\nlegacy_path: /guias/rascunho-antigo/\nreviewed: false\n---\n\nTexto.\n",
        "utf-8")
    npm.extra_pages = ["/dicas/voos-baratos/"]          # the reviewed tip is built, the draft isn't
    conn = pipeline.open_db(ctx)
    pipeline.save_site_paths(conn, {"guide:mala-de-cabine": ["/guias/mala-de-cabine/"]})
    site_data.export_site_data(ctx, conn, site_data.default_dir(ctx), new_links=False)
    astro.build(ctx, conn)
    r = rules(web)
    assert r["/guias/voos-baratos-dicas/"] == r["/guias/voos-baratos-dicas"] == "/dicas/voos-baratos/"
    assert r["/guias/rascunho-antigo/"] == "/dicas/"
    assert r["/guias/mala-de-cabine/"] == "/dicas/"


def test_config_redirects_are_kept_unless_they_would_hide_a_page(ctx, npm):
    web = web_package(ctx.root)
    ctx.config.site.redirects = {"/antigo/": "/explorar/", "/sobre/": "/"}
    conn = pipeline.open_db(ctx)
    site_data.export_site_data(ctx, conn, site_data.default_dir(ctx), new_links=False)
    summary = astro.build(ctx, conn)
    r = rules(web)
    assert r["/antigo/"] == "/explorar/" and "/sobre/" not in r
    assert summary.skipped_redirects == ["/sobre/ -> /: /sobre/ is a page of the site"]


# --- deploy ------------------------------------------------------------------------------------

@pytest.fixture
def wrangler(monkeypatch):
    calls = []

    class Done:
        returncode, stderr = 0, ""
        stdout = "Deployment complete! https://abc123.ondestaanocas.pages.dev"

    def fake(ctx, *args, cwd=None):
        calls.append({"args": args, "cwd": cwd})
        return Done()

    monkeypatch.setattr(site_deploy, "_wrangler", fake)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acc")
    return calls


def built(ctx, conn, npm) -> Path:
    web_package(ctx.root)
    site_data.export_site_data(ctx, conn, site_data.default_dir(ctx), new_links=False)
    astro.build(ctx, conn)
    return astro.dist_dir(ctx)


def test_deploy_uploads_the_astro_build_with_its_functions_from_the_web_package(ctx, npm, wrangler):
    conn = pipeline.open_db(ctx)
    dist = built(ctx, conn, npm)
    functions = ctx.root / "web" / "functions" / "review"
    functions.mkdir(parents=True)
    (functions / "index.ts").write_text("export const onRequest = () => new Response('x');\n", "utf-8")
    assert site_deploy.deploy(ctx, conn) == (True, "https://abc123.ondestaanocas.pages.dev")
    [call] = wrangler
    assert call["args"][:3] == ("pages", "deploy", str(dist.resolve()))
    assert "--project-name" in call["args"] and "main" in call["args"]
    # wrangler compiles <cwd>/functions: it runs in web/, where functions/ is (D35).
    assert call["cwd"] == ctx.root / "web"
    assert site_deploy.deploy(ctx, conn) == (False, "site unchanged since last deploy, skipped")
    (functions / "index.ts").write_text("export const onRequest = () => new Response('y');\n", "utf-8")
    assert site_deploy.deploy(ctx, conn)[0]                  # a Function change redeploys
    assert len(wrangler) == 2


def test_a_rebuild_with_only_a_newer_timestamp_is_not_deployed_again(ctx, npm, wrangler):
    conn = pipeline.open_db(ctx)
    built(ctx, conn, npm)
    assert site_deploy.deploy(ctx, conn)[0]
    built(ctx, conn, npm)                         # new generated_at: footer and explorer data
    assert site_deploy.deploy(ctx, conn) == (False, "site unchanged since last deploy, skipped")
    dados = astro.dist_dir(ctx) / "explorar" / "dados" / "LIS.json"
    dados.parent.mkdir(parents=True)
    dados.write_text('{"origin":"LIS","generated_at":"2026-10-14T09:01:47Z","rows":[]}', "utf-8")
    first = site_deploy.content_hash(astro.dist_dir(ctx))
    dados.write_text('{"origin":"LIS","generated_at":"2026-10-14T11:01:47Z","rows":[]}', "utf-8")
    assert site_deploy.content_hash(astro.dist_dir(ctx)) == first
    page = astro.dist_dir(ctx) / "index.html"
    page.write_text(page.read_text("utf-8").replace("</footer>", "</footer><p>novo</p>"), "utf-8")
    assert site_deploy.content_hash(astro.dist_dir(ctx)) != first


def test_the_footer_timestamp_of_an_astro_page_is_not_content(tmp_path):
    page = tmp_path / "index.html"
    page.write_text('<p>Atualizado a <span class="num">14/10/2026 às 10:01</span></p><p>x</p>', "utf-8")
    first = site_deploy.content_hash(tmp_path)
    page.write_text('<p>Atualizado a <span class="num">14/10/2026 às 12:01</span></p><p>x</p>', "utf-8")
    assert site_deploy.content_hash(tmp_path) == first


def test_a_fixture_build_is_never_deployed(ctx, npm, wrangler):
    conn = pipeline.open_db(ctx)
    dist = built(ctx, conn, npm)
    page = dist / "voos" / "lisboa-londres" / "index.html"
    page.write_text(page.read_text("utf-8").replace('<html lang="pt-PT"',
                                                    '<html lang="pt-PT" data-fixture="true"'), "utf-8")
    with pytest.raises(site_deploy.DeployError, match="fixture"):
        site_deploy.deploy(ctx, conn, force=True)
    assert not wrangler


def test_deploy_needs_a_build(ctx, wrangler):
    conn = pipeline.open_db(ctx)
    with pytest.raises(site_deploy.DeployError, match="site build"):
        site_deploy.deploy(ctx, conn)
