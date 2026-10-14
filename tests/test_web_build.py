"""The Astro site built by the pipeline (D35): npm ci only when needed, `npm run build` on the
exported contract, the promotion images the contract names, `_redirects` and `_headers`."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
import respx

from escapadinha import i18n_pt, pipeline, run_path, site_data
from escapadinha.storage import db
from escapadinha.website import astro, node
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

    def __call__(self, web: Path, *args: str, env: dict[str, str], until: float) -> None:
        self.calls.append({"args": args, "env": env, "until": until})
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
    monkeypatch.setattr(astro, "runtime", lambda web, until: "v22.0.0 linux x64")
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


def test_npm_ci_runs_again_for_another_node_version_or_platform(tmp_path, npm, monkeypatch):
    """Native packages (esbuild's binary) are installed per Node, platform and architecture: a
    node_modules made by another Node is installed again (D35)."""
    web = web_package(tmp_path)
    assert astro.ensure_dependencies(web) is True
    assert "v22.0.0 linux x64" in (web / "node_modules" / astro.STAMP).read_text("utf-8")
    assert astro.ensure_dependencies(web) is False
    monkeypatch.setattr(astro, "runtime", lambda web, until: "v24.1.0 linux x64")
    assert astro.ensure_dependencies(web) is True
    monkeypatch.setattr(astro, "runtime", lambda web, until: "v24.1.0 win32 x64")
    assert astro.ensure_dependencies(web) is True
    assert astro.ensure_dependencies(web) is False
    assert npm.ran("ci") == 3


def test_npm_is_found_on_windows_without_it_on_the_path(tmp_path, monkeypatch):
    """The PC's scheduled task may run without Node on its PATH: npm.cmd in the install dir."""
    monkeypatch.setattr(node.shutil, "which", lambda name: None)
    monkeypatch.setattr(node, "NODE_DIRS", [tmp_path])
    (tmp_path / "npm.cmd").write_text("@echo off\n", "utf-8")
    (tmp_path / "node.exe").write_text("", "utf-8")
    assert astro.npm() == str(tmp_path / "npm.cmd")
    assert node.tool("node") == str(tmp_path / "node.exe")
    (tmp_path / "npm.cmd").unlink()
    with pytest.raises(astro.BuildError, match="npm not found"):
        astro.npm()


# --- one time budget for the full path's Node commands (D35) ---------------------------------

class FakeProcess:
    """Stands in for subprocess.run under `node.run`: records each command's timeout, and can
    hang (TimeoutExpired, with the output so far) or fail to start (OSError)."""

    def __init__(self, clock: list[float], takes: float = 0.0, hang: bool = False,
                 missing: bool = False):
        self.clock, self.takes, self.hang, self.missing = clock, takes, hang, missing
        self.timeouts: list[float] = []

    def __call__(self, cmd, *, timeout, **kwargs):
        import subprocess
        self.timeouts.append(timeout)
        if self.missing:
            raise FileNotFoundError(2, "No such file or directory", cmd[0])
        if self.hang:
            self.clock[0] += timeout
            raise subprocess.TimeoutExpired(cmd, timeout, output=b"x" * 5000 + b"building pages",
                                            stderr=None)
        self.clock[0] += self.takes
        return subprocess.CompletedProcess(cmd, 0, "ok", "")


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(node.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(node, "tool", lambda name: f"/usr/bin/{name}")
    return now


def test_each_node_command_gets_what_is_left_of_the_one_budget(tmp_path, clock, monkeypatch):
    fake = FakeProcess(clock, takes=300)
    monkeypatch.setattr(node.subprocess, "run", fake)
    until = node.deadline()                                     # 20 minutes from now
    astro._run_npm(tmp_path, "ci", env={}, until=until)
    astro._run_npm(tmp_path, "run", "build", env={}, until=until)
    assert fake.timeouts == [node.FULL_PATH_SECONDS, node.FULL_PATH_SECONDS - 300]
    clock[0] = until + 1                                        # the budget is used up
    with pytest.raises(astro.BuildError, match="no time left"):
        astro._run_npm(tmp_path, "run", "build", env={}, until=until)
    assert len(fake.timeouts) == 2                              # nothing started


def test_a_hanging_npm_command_is_a_build_error_with_the_end_of_its_output(tmp_path, clock,
                                                                           monkeypatch):
    monkeypatch.setattr(node.subprocess, "run", FakeProcess(clock, hang=True))
    with pytest.raises(astro.BuildError, match="npm run build timed out") as raised:
        astro._run_npm(tmp_path, "run", "build", env={}, until=node.deadline())
    message = str(raised.value)
    assert message.endswith("building pages") and len(message) < node.OUTPUT_TAIL + 200


def test_a_node_tool_that_cannot_start_is_a_build_or_deploy_error(tmp_path, clock, monkeypatch, ctx):
    monkeypatch.setattr(node.subprocess, "run", FakeProcess(clock, missing=True))
    with pytest.raises(astro.BuildError, match="npm ci could not start"):
        astro._run_npm(tmp_path, "ci", env={}, until=node.deadline())
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acc")
    with pytest.raises(site_deploy.DeployError, match="wrangler pages deploy could not start"):
        site_deploy._wrangler(ctx, "pages", "deploy", until=node.deadline())


def test_a_hanging_wrangler_is_a_deploy_error(ctx, clock, monkeypatch):
    monkeypatch.setattr(node.subprocess, "run", FakeProcess(clock, hang=True))
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acc")
    with pytest.raises(site_deploy.DeployError, match="wrangler pages deploy timed out"):
        site_deploy._wrangler(ctx, "pages", "deploy", until=node.deadline(60))


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

    def failing(web, *args, env, until):
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
def test_old_promotion_links_and_renamed_slugs_redirect_to_the_current_pages(ctx, npm, wrangler):
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
    # The current paths join the history (stable keys), so a later rename gets its 301, once
    # the build is live: not before the deploy.
    assert promo not in pipeline.site_paths(ctx, conn)[f"deal:{deal_id}"]
    assert site_deploy.deploy(ctx, conn)[0]
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


@respx.mock
def test_a_gone_promotion_folds_into_its_route_history_and_chains_collapse(ctx, npm, wrangler):
    """Once live, a gone promotion's history entry becomes old paths of its route page (no
    `deal:` key left to grow), the same rules come out of the next build, and a later route
    rename sends them straight to the new page. A config rule to a path that now redirects
    points at the final page (no chain)."""
    web = web_package(ctx.root)
    conn = pipeline.open_db(ctx)
    deal_id = approved_deal(ctx, conn)
    old = f"/promos/{deal_id}-lisboa-londres/"
    pipeline.save_site_paths(conn, {f"deal:{deal_id}": [old]})
    db.set_deal_status(conn, deal_id, "expired")
    conn.execute("UPDATE deals SET last_checked_at = ? WHERE id = ?",
                 ((db.utcnow() - timedelta(days=40)).isoformat(), deal_id))
    conn.commit()
    ctx.config.site.redirects = {"/promo-antiga/": old}      # → a path that itself redirects
    export = site_data.export_site_data(ctx, conn, site_data.default_dir(ctx), new_links=False)
    assert export.files["promotions.json"]["promotions"] == []
    astro.build(ctx, conn)
    first = rules(web)
    assert first["/promo-antiga/"] == "/voos/lisboa-londres/"   # collapsed, not → old → route
    assert all(target not in first for target in first.values())  # no rule targets a rule
    assert site_deploy.deploy(ctx, conn)[0]
    history = pipeline.site_paths(ctx, conn)
    assert f"deal:{deal_id}" not in history
    assert {old, f"/promos/{deal_id}"} <= set(history["route:LIS-LON"])
    astro.build(ctx, conn)                                       # the next build: same rules
    assert rules(web) == first
    # The route is renamed later: the promotion's old links go straight to the new page.
    conn.execute("UPDATE routes SET city_pt = 'Londres Centro' "
                 "WHERE origin = 'LIS' AND destination = 'LON'")
    conn.commit()
    site_data.export_site_data(ctx, conn, site_data.default_dir(ctx), new_links=False)
    astro.build(ctx, conn)
    renamed = rules(web)
    new_route = renamed["/voos/lisboa-londres/"]
    assert new_route != "/voos/lisboa-londres/" and new_route.startswith("/voos/")
    for source in (old, f"/promos/{deal_id}", "/promo-antiga/"):
        assert renamed[source] == new_route, source


def test_plan_collapses_chains_and_leaves_loops_and_unbuilt_targets_out():
    from escapadinha.website import redirects
    pages = {"route:A": "/voos/a/"}
    history = {"route:A": ["/voos/a-velho/"]}
    extra = {"/x/": "/voos/a-velho/", "/y/": "/z/", "/z/": "/y/", "/w/": "/nao-existe/"}
    plan = redirects.plan_redirects(pages, history, extra=extra, aliases={},
                                    serves={"/voos/a/"}.__contains__, limit=None)
    assert dict(plan.rules) == {"/x/": "/voos/a/", "/voos/a-velho": "/voos/a/",
                                "/voos/a-velho/": "/voos/a/"}
    assert sorted(s.split(":")[-1].strip() for s in plan.skipped) == [
        "/nao-existe/ is not a page of the build", "a redirect loop", "a redirect loop"]


def test_unbuilt_targets_are_left_out_before_the_limit_counts(ctx, npm, monkeypatch):
    """Rules to pages the build doesn't have never take a place under Cloudflare's limit."""
    from escapadinha.website import redirects
    web = web_package(ctx.root)
    monkeypatch.setattr(redirects, "MAX_STATIC_REDIRECTS", 30)
    ctx.config.site.redirects = {f"/morto-{i}/": f"/nao-existe-{i}/" for i in range(40)}
    ctx.config.site.redirects |= {"/antigo/": "/explorar/"}
    conn = pipeline.open_db(ctx)
    site_data.export_site_data(ctx, conn, site_data.default_dir(ctx), new_links=False)
    summary = astro.build(ctx, conn)
    assert rules(web) == {"/antigo/": "/explorar/"} and summary.redirects == 1
    assert len(summary.skipped_redirects) == 40 and summary.warnings == []


def test_redirects_near_the_limit_warn_and_over_it_fail_the_build(ctx, npm, monkeypatch):
    from escapadinha.website import redirects
    web_package(ctx.root)
    conn = pipeline.open_db(ctx)
    site_data.export_site_data(ctx, conn, site_data.default_dir(ctx), new_links=False)
    monkeypatch.setattr(redirects, "MAX_STATIC_REDIRECTS", 20)
    ctx.config.site.redirects = {f"/antigo-{i}/": "/explorar/" for i in range(19)}
    summary = astro.build(ctx, conn)                              # 19 of 20: within 10 %
    assert summary.redirects == 19
    assert summary.warnings == ["19 redirects, within 10% of Cloudflare Pages' limit of 20: "
                                "the build fails above it (D35)"]
    ctx.config.site.redirects = {f"/antigo-{i}/": "/explorar/" for i in range(21)}
    with pytest.raises(astro.BuildError, match="21 redirects, over Cloudflare Pages' limit of 20"):
        astro.build(ctx, conn)


def test_a_failed_deploy_records_no_path(ctx, npm, monkeypatch):
    """The path history (`site.paths`) only learns a build's paths once that build is live:
    a deploy that fails leaves it as it was, so no 301 ever points at a page that never went
    out; the next successful deploy records them."""
    web_package(ctx.root)
    conn = pipeline.open_db(ctx)
    pipeline.save_site_paths(conn, {"route:LIS-LON": ["/voos/lisboa-londres-antigo/"]})
    site_data.export_site_data(ctx, conn, site_data.default_dir(ctx), new_links=False)
    before = pipeline.site_paths(ctx, conn)
    astro.build(ctx, conn)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acc")

    class Failed:
        returncode, stdout, stderr = 1, "", "Authentication error"

    monkeypatch.setattr(site_deploy, "_wrangler", lambda c, *a, cwd=None, until=None: Failed())
    with pytest.raises(site_deploy.DeployError, match="Authentication"):
        site_deploy.deploy(ctx, conn)
    assert pipeline.site_paths(ctx, conn) == before

    class Done:
        returncode, stdout, stderr = 0, "https://abc.ondestaanocas.pages.dev", ""

    monkeypatch.setattr(site_deploy, "_wrangler", lambda c, *a, cwd=None, until=None: Done())
    assert site_deploy.deploy(ctx, conn)[0]
    after = pipeline.site_paths(ctx, conn)
    assert after["route:LIS-LON"] == ["/voos/lisboa-londres-antigo/", "/voos/lisboa-londres/"]
    assert "/partidas/lisboa/" in after["origin:LIS"]
    assert db.get_meta(conn, "site.paths.pending") is None


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


# --- the run's full path (run_path fingerprint) -------------------------------------------------

def test_a_change_to_the_web_package_takes_the_full_path(ctx):
    web = web_package(ctx.root)
    files = {"src/pages/index.astro": "<p>a</p>", "src/content/tips/dica.mdx": "---\n---\n",
             "astro.config.ts": "export default {};", "public/favicon.svg": "<svg/>",
             "package.json": "{}", "src/data/meta.json": "{}", "node_modules/x/index.js": "",
             "dist/index.html": "<p>built</p>"}
    for rel, text in files.items():
        (web / rel).parent.mkdir(parents=True, exist_ok=True)
        (web / rel).write_text(text, "utf-8")
    conn = pipeline.open_db(ctx)
    record(ctx, conn)
    assert not run_path.decide(ctx, conn).full
    for rel in ("src/pages/index.astro", "src/content/tips/dica.mdx", "astro.config.ts",
                "public/favicon.svg", "package-lock.json"):
        (web / rel).write_text((web / rel).read_text("utf-8") + "\n// changed\n", "utf-8")
        decision = run_path.decide(ctx, conn)
        assert decision.full and "code" in decision.reason, rel
        record(ctx, conn)
    # The export's output, installed packages and the build are not sources.
    for rel in ("src/data/meta.json", "node_modules/x/index.js", "dist/index.html"):
        (web / rel).write_text("changed", "utf-8")
    assert not run_path.decide(ctx, conn).full


def record(ctx, conn, now=None) -> site_data.Export:
    """A successful full path: the export it wrote and deployed is what gets recorded."""
    export = site_data.build_export(ctx, conn, now, new_links=False)
    run_path.record_full_path(ctx, conn, export)
    return export


def store_offer(conn, price: float, departure) -> None:
    """A new completed collection run with one LIS-LON offer (test data only)."""
    from escapadinha.models import Observation
    run_id = db.start_run(conn, "test")
    db.insert_observations(conn, run_id, [Observation(
        source="test", origin="LIS", destination="LON", origin_airport="LIS",
        destination_airport="LGW", departure_date=departure,
        return_date=departure + timedelta(days=3), price=price, currency="EUR", airline="TP",
        flight_number="1", transfers=0, return_transfers=0, deep_link=None,
        fetched_at=db.utcnow(), raw_json="{}")])
    db.finish_run(conn, run_id, status="ok", n_requests=1, n_observations=1, error=None)


def test_what_the_exported_data_shows_decides_the_path_not_the_run_bookkeeping(ctx):
    """A new run that finds the same offers changes generated_at, the run id, the routes'
    observation counts and last-seen times: none is on the site, so the path stays fast. A
    new cheapest price is (route, origin and hub pages, calendar): full path."""
    from datetime import date
    conn = pipeline.open_db(ctx)
    store_offer(conn, 120, date(2026, 12, 4))
    record(ctx, conn)
    store_offer(conn, 120, date(2026, 12, 4))              # the same offer seen again
    assert run_path.decide(ctx, conn) == run_path.PathDecision(False, "nothing the site shows changed")
    store_offer(conn, 99, date(2026, 12, 4))               # a cheaper one: the site changes
    decision = run_path.decide(ctx, conn)
    assert decision.full and decision.reason == "changed: site data"


def test_a_full_path_records_the_export_it_deployed_not_a_later_state(ctx):
    """The fingerprint stored after a full path is the export that was built and deployed (its
    data and its day), not the database re-read later: an offer that went stale between the
    export and the record must still take the next run's full path, or the site would keep
    showing it."""
    from datetime import date
    conn = pipeline.open_db(ctx)
    store_offer(conn, 99, date.today() + timedelta(days=50))
    exported_at = db.utcnow()
    export = site_data.build_export(ctx, conn, exported_at, new_links=False)
    [route] = [r for r in export.files["routes.json"]["routes"] if r["key"] == "LIS-LON"]
    assert route["cheapest"] is not None                         # the page shows the 99 € offer
    stale = exported_at + timedelta(days=ctx.config.detector.max_offer_age_days + 1)
    later = site_data.build_export(ctx, conn, stale, new_links=False)
    [route] = [r for r in later.files["routes.json"]["routes"] if r["key"] == "LIS-LON"]
    assert route["cheapest"] is None                             # no longer fresh by then
    run_path.record_full_path(ctx, conn, export)                 # recorded after a long deploy
    stored = json.loads(db.get_meta(conn, run_path.FINGERPRINT))
    assert stored["site_data"] == site_data.shown_digest(export)
    assert stored["day"] == exported_at.astimezone(i18n_pt.LISBON).date().isoformat()
    decision = run_path.decide(ctx, conn, now=stale)
    assert decision.full and "site data" in decision.reason      # the stale offer goes away
    assert not run_path.decide(ctx, conn, now=exported_at).full  # nothing else moved


def test_the_site_never_shows_what_the_fingerprint_leaves_out():
    """`site_data.PER_RUN` (left out of the fingerprint by `shown_digest`) lists the run id,
    routes' observation counts and their last-seen time beyond the day: a page that started
    showing one would not be refreshed by a routine run."""
    import re
    for path in (REPO / "web" / "src").rglob("*"):
        if path.suffix not in (".astro", ".ts") or path.name == "contract.ts":
            continue
        text = path.read_text("utf-8")
        assert "counts.observations" not in text and not re.search(r"meta\.run\b", text), path
        for m in re.finditer(r"last_observed_at", text):
            assert text[m.end():].startswith((" ?", ".slice(0, 10)")), path


# --- deploy ------------------------------------------------------------------------------------

@pytest.fixture
def wrangler(monkeypatch):
    calls = []

    class Done:
        returncode, stderr = 0, ""
        stdout = "Deployment complete! https://abc123.ondestaanocas.pages.dev"

    def fake(ctx, *args, cwd=None, until=None):
        calls.append({"args": args, "cwd": cwd, "until": until})
        return Done()

    monkeypatch.setattr(site_deploy, "_wrangler", fake)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acc")
    return calls


def built(ctx, conn, npm) -> Path:
    web_package(ctx.root)
    site_data.export_site_data(ctx, conn, site_data.default_dir(ctx), new_links=False)
    astro.build(ctx, conn)
    return node.dist_dir(ctx)


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
    dados = node.dist_dir(ctx) / "explorar" / "dados" / "LIS.json"
    dados.parent.mkdir(parents=True)
    dados.write_text('{"origin":"LIS","generated_at":"2026-10-14T09:01:47Z","rows":[]}', "utf-8")
    first = site_deploy.content_hash(node.dist_dir(ctx))
    dados.write_text('{"origin":"LIS","generated_at":"2026-10-14T11:01:47Z","rows":[]}', "utf-8")
    assert site_deploy.content_hash(node.dist_dir(ctx)) == first
    page = node.dist_dir(ctx) / "index.html"
    page.write_text(page.read_text("utf-8").replace("</footer>", "</footer><p>novo</p>"), "utf-8")
    assert site_deploy.content_hash(node.dist_dir(ctx)) != first


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
