"""The scheduled run as GitHub Actions runs it (D25): fast or full path, a fresh runner
with only the bucket, one route failing, the workflow file itself."""

import json
import shutil
from pathlib import Path

import httpx
import pytest
import respx
import yaml
from PIL import Image
from typer.testing import CliRunner

from escapadinha import cli, pipeline, renderer, routes
from escapadinha.collector.travelpayouts import API_URL
from escapadinha.config import Context
from escapadinha.models import Photo
from escapadinha.storage import db, sync
from escapadinha.storage.objects import LocalObjectStore
from escapadinha.website import build_site
from escapadinha.website import astro, node
from escapadinha.website import deploy as site_deploy
from test_pipeline import REPO, EMPTY, ctx, mock_api, mock_links, seed_history  # noqa: F401
from test_web_build import npm, web_package  # noqa: F401
from test_website import approved_deal

UNSET = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "R2_ENDPOINT", "R2_ACCESS_KEY_ID",
         "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "GITHUB_STEP_SUMMARY", "PIXABAY_API_KEY")


class FakeRenderer:
    """Stands in for Chromium (the browser boundary): writes small real PNG slides."""

    def __init__(self, assets_dir, brand):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def render_deal(self, view, photo_path, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = [out_dir / f"slide_{n:02d}.png" for n in (1, 2, 3)]
        for p in paths:
            Image.new("RGB", (108, 135), (200, 80, 60)).save(p)
        return paths


@pytest.fixture
def home(ctx, monkeypatch, npm):
    """The CLI's project root is the test project with a web package (npm faked, D35);
    discovery already ran this month."""
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    for name in UNSET:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(pipeline, "SlideRenderer", FakeRenderer)
    web_package(ctx.root)
    conn = pipeline.open_db(ctx)
    db.set_meta(conn, pipeline.DISCOVERED_AT, db.utcnow().isoformat())
    conn.close()
    return ctx


def run_cli(*args, code=0):
    result = CliRunner().invoke(cli.app, ["run", *args])
    assert result.exit_code == code, result.output
    return result.output


@respx.mock
def test_routine_run_takes_the_fast_path_when_nothing_changed(home):
    mock_api()
    first = run_cli()
    assert "Path: full (first full path)" in first
    dist = node.dist_dir(home)
    assert (dist / "index.html").exists() and (dist / "_redirects").exists()
    assert not home.site_dir.exists()                      # the legacy Jinja site isn't built
    shutil.rmtree(dist)

    second = run_cli()
    assert "Path: fast (nothing the site shows changed)" in second
    assert not dist.exists()                               # no render, export, build or deploy

    forced = run_cli("--full")
    assert "Path: full (forced with --full)" in forced
    assert (dist / "index.html").exists()


@respx.mock
def test_the_full_path_shares_one_deadline_between_build_and_deploy(home, npm, monkeypatch):
    """npm ci, astro build and wrangler each get what is left of one budget (D35), so the full
    path ends with time for the review snapshot and the database push inside the job."""
    from escapadinha.website import node
    mock_api()
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acc")
    deploys = []

    class Done:
        returncode, stderr, stdout = 0, "", "Deployment complete! https://abc.ondestaanocas.pages.dev"

    monkeypatch.setattr(site_deploy, "_wrangler",
                        lambda c, *args, cwd=None, until=None: deploys.append(until) or Done())
    before = node.deadline()
    run_cli("--full")
    after = node.deadline()
    budgets = {c["until"] for c in npm.calls} | set(deploys)
    assert len(budgets) == 1 and len(deploys) == 1 and npm.ran("run", "build") == 1
    [until] = budgets
    assert before <= until <= after


@respx.mock
def test_only_a_full_path_that_ran_npm_ci_asks_the_workflow_to_save_npms_cache(home, monkeypatch,
                                                                               tmp_path):
    """`npm_ci=true` in $GITHUB_OUTPUT: the workflow's save step runs on it (D35)."""
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    mock_api()
    assert "Path: full" in run_cli()                      # npm ci ran (no node_modules yet)
    assert output.read_text("utf-8") == "npm_ci=true\n"
    output.write_text("", "utf-8")
    assert "Path: fast" in run_cli()
    assert run_cli("--full") and output.read_text("utf-8") == ""    # installed already


@respx.mock
def test_new_deals_and_review_decisions_take_the_full_path(home):
    conn = pipeline.open_db(home)
    seed_history(conn, days=25, price=100)
    conn.close()
    mock_api()
    mock_links()
    assert "Path: full (first full path)" in run_cli()
    conn = pipeline.open_db(home)
    [(deal, _)] = db.deals_with_status(conn, "rendered")    # rendered on the full path
    assert "Path: fast" in run_cli()

    pipeline.reject(home, conn, deal.id, "não", actor="test")   # Miguel's decision between runs
    conn.close()
    assert "Path: full (changed: promotions)" in run_cli()
    assert "Path: fast" in run_cli()


def api(failing: set[str]):
    """Every route answers with no offers, except `failing` destinations (an API error)."""
    def respond(request):
        if request.url.params["destination"] in failing:
            return httpx.Response(200, json={"success": False, "error": "boom"})
        return httpx.Response(200, json=EMPTY)
    respx.get(API_URL).mock(side_effect=respond)


@respx.mock
def test_a_failing_route_never_fails_the_run_and_the_summary_says_so(home, monkeypatch, tmp_path):
    summary = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    api(failing={"LON"})
    out = run_cli()                                           # exit 0
    assert "LIS-LON" in out and "boom" in out
    text = summary.read_text("utf-8")
    assert text.startswith("### Escapadinha run: ok")
    assert "- Collection: partial, 30 requests, 0 offers (0 new), 6 failed" in text   # LIS- and OPO-LON
    assert "- Path: full (first full path)" in text and "- Duration: " in text


@respx.mock
def test_a_collection_where_every_request_failed_fails_the_job(home, monkeypatch, tmp_path):
    summary = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    conn = pipeline.open_db(home)
    every = {r.destination for r in routes.active_routes(conn, home.config.routes)}
    conn.close()
    api(failing=every)
    out = run_cli(code=1)
    assert "Run failed in" in out
    text = summary.read_text("utf-8")
    assert text.startswith("### Escapadinha run: failed") and "Collection: failed" in text
    assert "Review snapshot:" in out                        # still exported (D26)
    assert json.loads(home.object_store.get("review/snapshot.json"))["version"] == 1


class PhotoUploadFails(LocalObjectStore):
    """A bucket whose first photo upload fails (an R2 hiccup); everything else works."""

    failed = False

    def put(self, key, data):
        if key.startswith("photos/") and not self.failed:
            from botocore.exceptions import EndpointConnectionError
            self.failed = True
            raise EndpointConnectionError(endpoint_url="https://r2.example/photos")
        super().put(key, data)


@respx.mock
def test_an_object_store_error_in_route_upkeep_never_stops_the_collection(home, monkeypatch,
                                                                          tmp_path):
    from escapadinha.photos import SEARCH_URL
    store = PhotoUploadFails(tmp_path / "bucket")
    monkeypatch.setattr(Context, "remote_store", property(lambda self: True))
    monkeypatch.setattr(Context, "object_store", property(lambda self: store))
    monkeypatch.setenv("PIXABAY_API_KEY", "pixabay-test")
    hit = {"id": 1, "pageURL": "https://pixabay.com/photos/x-1/", "user": "ana", "user_id": 42,
           "largeImageURL": "https://pixabay.com/get/x_1280.jpg"}
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [hit]}))
    respx.get(hit["largeImageURL"]).mock(return_value=httpx.Response(200, content=b"jpeg"))
    mock_api()
    out = run_cli()                                           # exit 0
    assert "a recolha continua" in out and "r2.example" in out
    assert "Run #" in out and "Path: full" in out             # collected, detected, built
    assert store.list("db/")                                  # and the database was pushed


def test_the_review_snapshot_never_hides_the_runs_own_failure(monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("detect broke")

    def snapshot_broken():
        raise OSError("store down")

    monkeypatch.setattr(cli, "apply_review_events", lambda: None)
    monkeypatch.setattr(cli, "_pipeline_steps", broken)
    monkeypatch.setattr(cli, "export_review_snapshot", snapshot_broken)
    report = []
    with pytest.raises(RuntimeError, match="detect broke"):
        cli._run_steps(render=True, full=False, report=report)
    assert report == ["Review snapshot failed: OSError"]


def test_chromium_is_installed_on_a_runner_only_when_slides_are_rendered(monkeypatch):
    calls = []
    monkeypatch.setattr(renderer, "_installed", False)
    monkeypatch.delenv(renderer.INSTALL_ENV, raising=False)
    assert renderer.ensure_browser(run=lambda cmd, check: calls.append(cmd)) is False   # the PC
    monkeypatch.setenv(renderer.INSTALL_ENV, "1")
    assert renderer.ensure_browser(run=lambda cmd, check: calls.append(cmd)) is True
    assert renderer.ensure_browser(run=lambda cmd, check: calls.append(cmd)) is False   # once
    assert [c[1:] for c in calls] == [["-m", "playwright", "install", "--with-deps", "chromium"]]


# --- a fresh runner has only the bucket (D21, D25) -------------------------------------------

NOW = db.utcnow()
GUIDE = "voos-baratos-dicas"


def project(root: Path) -> Context:
    """A checkout: config (with a website Project), assets without photos, a reviewed guide."""
    config = yaml.safe_load((REPO / "config.yaml").read_text("utf-8"))
    config["routes"]["long_haul"] = []
    config["affiliate"]["projects"]["website"] = 700001
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.yaml").write_text(yaml.safe_dump(config, allow_unicode=True), "utf-8")
    shutil.copytree(REPO / "assets", root / "assets", ignore=shutil.ignore_patterns("photos"))
    shutil.copytree(REPO / "content", root / "content")
    guide = root / "content" / "guides" / f"{GUIDE}.yaml"
    guide.write_text(guide.read_text("utf-8").replace("reviewed: false", "reviewed: true"), "utf-8")
    return Context(root=root)


def slide(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (108, 135), (40, 90, 160)).save(path)


@pytest.fixture
def bucket(tmp_path, monkeypatch):
    """R2 'configured' for every Context, the bucket being a local directory."""
    store = LocalObjectStore(tmp_path / "bucket")
    monkeypatch.setattr(Context, "remote_store", property(lambda self: True))
    monkeypatch.setattr(Context, "object_store", property(lambda self: store))
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "test-token")
    monkeypatch.setenv("TRAVELPAYOUTS_MARKER", "424242")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acc")
    return store


@pytest.fixture
def deployments(monkeypatch):
    calls = []

    class Done:
        returncode, stderr, stdout = 0, "", "Deployment complete! https://abc.ondestaanocas.pages.dev"

    monkeypatch.setattr(site_deploy, "_wrangler",
                        lambda c, *args, cwd=None, until=None: calls.append(args) or Done())
    return calls


@respx.mock
def test_a_fresh_runner_builds_the_same_site_as_the_pc(tmp_path, bucket, deployments, npm):
    """Export + Astro build (D35) on the PC, then on a runner that only has the bucket: the same
    site (redirect history, cached links, slides), no partner link made twice, no new deploy."""
    from escapadinha import site_data

    pc = project(tmp_path / "pc")
    web_package(pc.root)
    conn = pipeline.open_db(pc)
    deal_id = approved_deal(pc, conn)
    # What only the PC has: files written before D25, slides, a photo, a rendered guide.
    (pc.root / "data" / "site_paths.json").write_text(json.dumps(
        {f"deal:{deal_id}": [f"/promos/{deal_id}-lisboa-londres-antigo/"]}), "utf-8")
    (pc.root / "data" / "site_links.json").write_text(json.dumps(
        {"700001": {str(deal_id): {"url": f"https://aviasales.tpo.lu/site-old-{deal_id}",
                                   "error": None}}}), "utf-8")
    (pc.photos_dir).mkdir(parents=True)
    (pc.photos_dir / "LON.jpg").write_bytes(b"jpeg bytes of London")
    db.upsert_photo(conn, Photo("LON", "LON.jpg", "pixabay", "https://pixabay.com/p-1/", "Ana",
                                "https://pixabay.com/users/ana-1/", "Pixabay", NOW))
    slide(pc.output_dir / "2026-10-01" / f"guia-{GUIDE}" / "slide_01.png")

    uploaded = pipeline.mirror_local_files(pc, conn)
    assert len(uploaded) == 1 + 3 + 1 + 1     # photo, deal slides, deal caption, guide slide
    site_data.export_site_data(pc, conn, site_data.default_dir(pc), now=NOW)
    astro.build(pc, conn)
    assert site_deploy.deploy(pc, conn)[0]
    links_made = len(respx.calls)
    conn.close()
    sync.push(bucket, pc.db_path, pc.sync_state_path, owner="pc", log=lambda _: None)

    runner = project(tmp_path / "runner")
    web_package(runner.root)
    sync.pull(bucket, runner.db_path, runner.sync_state_path, log=lambda _: None)
    conn = pipeline.open_db(runner)
    export = site_data.export_site_data(runner, conn, site_data.default_dir(runner), now=NOW)
    astro.build(runner, conn)

    pc_dist, runner_dist = node.dist_dir(pc), node.dist_dir(runner)
    assert site_deploy.content_hash(runner_dist) == site_deploy.content_hash(pc_dist)
    redirects = (runner_dist / "_redirects").read_text("utf-8")
    assert (f"/promos/{deal_id}-lisboa-londres-antigo/ /promos/{deal_id}-lisboa-londres/ 301"
            in redirects)                                           # redirect history kept
    [promo] = export.files["promotions.json"]["promotions"]
    assert promo["booking_link"] == f"https://aviasales.tpo.lu/site-old-{deal_id}"  # cached link
    assert len(respx.calls) == links_made                           # no duplicate partner link
    assert (runner_dist / "img" / "promos" / str(deal_id) / "slide_01.webp").is_file()
    assert site_deploy.deploy(runner, conn) == (False, "site unchanged since last deploy, skipped")
    assert len(deployments) == 1

    deal, obs = db.get_deal(conn, deal_id)
    _, photo = pipeline.deal_view(runner, conn, deal, obs)          # rendering a slide needs it
    assert photo.read_bytes() == b"jpeg bytes of London"


@respx.mock
def test_a_fresh_runners_site_data_lists_the_slides_only_the_bucket_has(tmp_path, bucket):
    """The export runs before the site build on a runner without output/ (D25, D27)."""
    from escapadinha import site_data

    pc = project(tmp_path / "pc")
    conn = pipeline.open_db(pc)
    deal_id = approved_deal(pc, conn)
    pipeline.mirror_local_files(pc, conn)
    conn.close()
    sync.push(bucket, pc.db_path, pc.sync_state_path, owner="pc", log=lambda _: None)
    shutil.rmtree(pc.output_dir)          # the stored output_path points at another machine

    runner = project(tmp_path / "runner")
    sync.pull(bucket, runner.db_path, runner.sync_state_path, log=lambda _: None)
    conn = pipeline.open_db(runner)
    assert not runner.output_dir.exists()
    export = site_data.export_site_data(runner, conn, tmp_path / "data", now=NOW, new_links=False)
    [promo] = export.files["promotions.json"]["promotions"]
    assert promo["id"] == deal_id and promo["images"] is not None
    assert len(promo["images"]["slides"]) == 3 and promo["images"]["thumb"]


@respx.mock
def test_a_fresh_runners_full_path_downloads_each_slide_once_and_nothing_else(tmp_path, bucket):
    """Export then site build on a runner without output/ (D25 budget): the export reads the
    slide names from the listing, the build downloads each slide PNG once, and never the
    caption or meta.json it does not show."""
    from collections import Counter
    from escapadinha import site_data

    pc = project(tmp_path / "pc")
    conn = pipeline.open_db(pc)
    deal_id = approved_deal(pc, conn)
    pipeline.mirror_local_files(pc, conn)
    conn.close()
    sync.push(bucket, pc.db_path, pc.sync_state_path, owner="pc", log=lambda _: None)
    shutil.rmtree(pc.output_dir)

    runner = project(tmp_path / "runner")
    sync.pull(bucket, runner.db_path, runner.sync_state_path, log=lambda _: None)
    conn = pipeline.open_db(runner)
    gets = Counter()
    real_get = bucket.get
    bucket.get = lambda key: gets.update([key]) or real_get(key)
    export = site_data.export_site_data(runner, conn, tmp_path / "data", now=NOW, new_links=False)
    assert not [k for k in gets if k.startswith("output/")]          # names from the listing
    build_site(runner, conn, now=NOW)
    downloaded = {k: n for k, n in gets.items() if k.startswith("output/")}
    assert sorted(k.rsplit("/", 1)[1] for k in downloaded) == \
        ["slide_01.png", "slide_02.png", "slide_03.png"]
    assert set(downloaded.values()) == {1}
    [promo] = export.files["promotions.json"]["promotions"]
    for path in [*promo["images"]["slides"], promo["images"]["thumb"], promo["images"]["og"]]:
        assert (runner.site_dir / path.lstrip("/")).is_file(), path
    assert promo["id"] == deal_id


@respx.mock
def test_the_pcs_full_path_uploads_what_a_runner_will_need(home, bucket, monkeypatch):
    for name in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"):
        monkeypatch.delenv(name)
    home.photos_dir.mkdir(parents=True)
    (home.photos_dir / "LON.jpg").write_bytes(b"jpeg")
    mock_api()
    out = run_cli()
    assert "Path: full" in out and "1 local files uploaded" in out
    assert bucket.get("photos/LON.jpg") == b"jpeg" and bucket.list("db/")
