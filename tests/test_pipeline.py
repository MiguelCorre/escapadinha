"""End-to-end: mocked API → SQLite → detector → slides/captions, in a temp project root."""

import json
import shutil
import struct
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
import respx
import yaml

from escapadinha import pipeline
from escapadinha.affiliate import API_URL as LINKS_URL
from escapadinha.collector.travelpayouts import API_URL
from escapadinha.config import Context
from escapadinha.models import Observation
from escapadinha.presentation import DISCLOSURE
from escapadinha.storage import db

REPO = Path(__file__).parent.parent


def found_yesterday(text: str) -> dict:
    """The synthetic LIS-LON offers as found yesterday (UTC). Detection and rechecks only take
    prices found in the last `max_offer_age_days` (3), so the file's fixed found date
    (12/10/2026) made every test that needs a fresh offer fail from 2026-10-16 on."""
    day = (db.utcnow() - timedelta(days=1)).strftime("%d%m%Y")
    return json.loads(text.replace("search_date=12102026", f"search_date={day}"))


FIXTURE = found_yesterday((REPO / "tests" / "fixtures" / "prices_for_dates_LIS_LON.json")
                          .read_text("utf-8"))
EMPTY = {"success": True, "currency": "eur", "data": []}


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    # The real config, minus the curated long-haul list: tests that need long-haul routes
    # add their own, so route counts here stay the 10 seeded routes. No website Project either:
    # tests that need one set it, so link assertions don't follow the repo's real Project id
    # (nor the search widget, which must carry that Project). The day's pass asks the same months
    # as every run, so a run here is routes × 3 requests (the far months: test_daily_pass.py).
    config = yaml.safe_load((REPO / "config.yaml").read_text("utf-8"))
    config["routes"]["long_haul"] = []
    config["collector"]["daily_months_ahead"] = config["collector"]["months_ahead"]
    config["affiliate"]["projects"]["website"] = None
    config["site"]["search_widget"] = None   # the real widget carries the real Project
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config, allow_unicode=True), "utf-8")
    shutil.copytree(REPO / "assets", tmp_path / "assets",
                    ignore=shutil.ignore_patterns("photos"))   # logos + self-hosted fonts
    shutil.copytree(REPO / "content", tmp_path / "content")
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "test-token")
    monkeypatch.setenv("TRAVELPAYOUTS_MARKER", "424242")
    for name in ("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_ACCOUNT_ID",    # publishers wait unless
                 "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL"):           # a test sets them
        monkeypatch.delenv(name, raising=False)
    return Context(root=tmp_path)


def seed_history(conn, *, days: int, price: float):
    """Synthetic past observations for LIS-LON (test data only): one per day at the day's
    low (`price` + 0..2) and a dearer one on the next departure date, so every day counts
    towards the typical low (two departure dates, D40)."""
    run_id = db.start_run(conn, "test")
    now = db.utcnow()
    db.insert_observations(conn, run_id, [
        Observation(source="test", origin="LIS", destination="LON", origin_airport="LIS",
                    destination_airport="LGW",
                    departure_date=date(2026, 11, 1) + timedelta(days=i + k),
                    return_date=date(2026, 11, 5) + timedelta(days=i + k),
                    price=price + i % 3 + 20 * k, currency="EUR", airline="TP",
                    flight_number="1", transfers=0, return_transfers=0, deep_link=None,
                    fetched_at=now - timedelta(days=i + 1), raw_json="{}")
        for i in range(days) for k in (0, 1)
    ])
    db.finish_run(conn, run_id, status="ok", n_requests=0, n_observations=2 * days, error=None)


def mock_api():
    def respond(request):
        lis_lon = request.url.params["origin"] == "LIS" and request.url.params["destination"] == "LON"
        return httpx.Response(200, json=FIXTURE if lis_lon else EMPTY)
    respx.get(API_URL).mock(side_effect=respond)


def mock_links(ok=True):
    def respond(request):
        body = json.loads(request.content)
        links = [{"url": l["url"], "code": "success" if ok else "failed",
                  "partner_url": f"https://aviasales.tpo.lu/{l.get('sub_id')}" if ok else "",
                  "message": None if ok else "trs is not subscribed for brand"}
                 for l in body["links"]]
        return httpx.Response(200, json={"result": {**body, "links": links}, "code": "success"})
    return respx.post(LINKS_URL).mock(side_effect=respond)


def png_size(path: Path) -> tuple[int, int]:
    return struct.unpack(">II", path.read_bytes()[16:24])


@respx.mock
def test_collect_and_detect(ctx):
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    mock_api()

    summary = pipeline.run_collect(ctx, conn)
    assert summary.status == "ok" and summary.n_requests == 30 and summary.n_observations == 6

    run_id, results = pipeline.run_detect(ctx, conn)
    by_route = {r.route: r for r in results}
    assert run_id == summary.run_id
    assert by_route["LIS-LON"].status == "deals" and len(by_route["LIS-LON"].deal_ids) == 1
    assert by_route["LIS-LON"].low_prices == 1          # the same 58 € offer is also a low price
    assert by_route["OPO-BCN"].status == "no_data"
    assert by_route["LIS-LON"].baseline.median == 101

    deal, obs = db.get_deal(conn, by_route["LIS-LON"].deal_ids[0])
    assert obs.price == 58 and obs.run_id == summary.run_id     # traceable to this run
    assert deal.rule == "median" and deal.sample_size == 22   # seeded days older than 3 days
    # What the reviewer sees (D40): the days' span and the extreme daily lows, by observation.
    lowest, highest = (db.get_observation(conn, i)
                       for i in (deal.baseline_lowest_obs_id, deal.baseline_highest_obs_id))
    assert (deal.baseline_span_days, lowest.price, highest.price) == (21, 100, 102)
    assert lowest.route_key == highest.route_key == "LIS-LON"

    # Running detection again on the same run must not flag the same trip twice.
    _, again = pipeline.run_detect(ctx, conn, run_id)
    assert {r.route: r for r in again}["LIS-LON"].deal_ids == []


@respx.mock
def test_cold_start_flags_nothing(ctx):
    conn = pipeline.open_db(ctx)
    mock_api()
    pipeline.run_collect(ctx, conn)
    _, results = pipeline.run_detect(ctx, conn)
    assert {r.route: r.status for r in results}["LIS-LON"] == "insufficient_history"
    assert all(not r.deal_ids for r in results)


@pytest.mark.browser
@respx.mock
def test_render_deal_and_guide(ctx):
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    mock_api()
    pipeline.run_collect(ctx, conn)
    pipeline.run_detect(ctx, conn)

    links = mock_links()
    [(out, deal)] = pipeline.run_render_deals(ctx, conn)
    sent = json.loads(links.calls.last.request.content)
    assert sent["trs"] == 584711 and sent["marker"] == 424242
    assert deal.affiliate_url == f"https://aviasales.tpo.lu/deal-{deal.id}"
    slides = sorted(out.glob("slide_*.png"))
    assert [png_size(p) for p in slides] == [(1080, 1350)] * 3
    caption = (out / "caption.txt").read_text("utf-8")
    assert DISCLOSURE in caption and "58 €" in caption
    meta = json.loads((out / "meta.json").read_text("utf-8"))
    assert meta["source"] == "travelpayouts" and meta["observation_id"]
    assert meta["affiliate_url"] == deal.affiliate_url
    assert meta["booking_url"].startswith("https://www.aviasales.pt/search/")
    sent_url = sent["links"][0]["url"]
    assert sent_url.startswith("https://www.aviasales.pt/search/")
    assert pipeline.run_render_deals(ctx, conn) == []      # status moved to 'rendered'
    # The link is generated once and reused on re-render.
    pipeline.run_render_deals(ctx, conn, status="rendered")
    assert links.call_count == 1

    guide_dir, reviewed = pipeline.run_render_guide(ctx, conn, "voos-baratos-dicas")
    assert len(list(guide_dir.glob("slide_*.png"))) == 7 and reviewed is False
    assert (guide_dir / "caption.txt").exists()


def test_migrates_v1_database(tmp_path):
    """A v1 database is upgraded in place through every migration, keeping its rows."""
    import sqlite3
    path = tmp_path / "v1.db"
    raw = sqlite3.connect(path)
    raw.executescript("""
        CREATE TABLE fetch_runs (id INTEGER PRIMARY KEY, source TEXT NOT NULL, started_at TEXT NOT NULL,
            finished_at TEXT, status TEXT NOT NULL DEFAULT 'running', n_requests INTEGER NOT NULL DEFAULT 0,
            n_observations INTEGER NOT NULL DEFAULT 0, error TEXT);
        CREATE TABLE price_observations (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, source TEXT NOT NULL,
            origin TEXT NOT NULL, destination TEXT NOT NULL, origin_airport TEXT, destination_airport TEXT,
            departure_date TEXT NOT NULL, return_date TEXT NOT NULL, nights INTEGER NOT NULL,
            price NUMERIC NOT NULL, currency TEXT NOT NULL, airline TEXT, flight_number TEXT, transfers INTEGER,
            return_transfers INTEGER, deep_link TEXT, fetched_at TEXT NOT NULL, raw_json TEXT NOT NULL);
        CREATE TABLE deals (id INTEGER PRIMARY KEY, observation_id INTEGER NOT NULL UNIQUE,
            rule TEXT NOT NULL, baseline_median NUMERIC, sample_size INTEGER NOT NULL,
            discount_pct NUMERIC, threshold NUMERIC NOT NULL, detected_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new');
        CREATE TABLE photos (destination TEXT PRIMARY KEY, file_path TEXT NOT NULL, source TEXT NOT NULL,
            source_url TEXT NOT NULL, photographer TEXT NOT NULL, photographer_url TEXT NOT NULL,
            license TEXT NOT NULL, fetched_at TEXT NOT NULL);
        INSERT INTO fetch_runs (id, source, started_at, status) VALUES (1, 'test', '2026-10-01T00:00:00+00:00', 'ok');
        INSERT INTO price_observations VALUES (1, 1, 'test', 'LIS', 'LON', 'LIS', 'LGW', '2026-11-01',
            '2026-11-05', 4, 80, 'EUR', 'TP', '1', 0, 0, NULL, '2026-10-01T00:00:00+00:00', '{}');
        INSERT INTO deals VALUES (1, 1, 'median', 100, 5, 0.2, 0.3, '2026-10-01T00:00:00+00:00', 'new');
        PRAGMA user_version = 1;
    """)
    raw.close()
    conn = db.connect(path)
    db.init(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    obs = db.get_observation(conn, 1)
    assert obs.price == 80 and obs.found_date is None
    deal, _ = db.get_deal(conn, 1)
    assert deal.status == "new" and deal.affiliate_url is None
    # v13 (D40): an old deal has no stored baseline range; the columns match a fresh install.
    assert (deal.baseline_span_days, deal.baseline_lowest_obs_id,
            deal.baseline_highest_obs_id) == (None, None, None)
    fresh = db.connect(tmp_path / "fresh.db")
    db.init(fresh)
    columns = lambda c: {r[1] for r in c.execute("PRAGMA table_info(deals)")}  # noqa: E731
    assert columns(conn) == columns(fresh)


def _deal_columns(conn) -> dict[str, tuple]:
    """name -> (type, not null, default, primary key) of `deals`, and its foreign keys."""
    columns = {r[1]: tuple(r)[2:] for r in conn.execute("PRAGMA table_info(deals)")}
    keys = sorted((r[3], r[2], r[4]) for r in conn.execute("PRAGMA foreign_key_list(deals)"))
    return {**columns, "foreign keys": tuple(keys)}


@pytest.mark.parametrize("fixture, version", [("schema_v5.sql", 5), ("schema_v7.sql", 7)])
def test_upgrade_from_real_old_schemas_gives_deals_the_baseline_columns(tmp_path, fixture, version):
    """v13 (D40) on the real old schemas: a deal detected before keeps its row with no stored
    baseline range, and `deals` ends up as a fresh install has it (types, keys)."""
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript((REPO / "tests" / "fixtures" / fixture).read_text("utf-8"))
    old.execute("INSERT INTO fetch_runs (id, source, started_at, status) "
                "VALUES (1, 'test', '2026-10-14T01:00:00+00:00', 'ok')")
    seen = "2026-10-14T01:00:00+00:00"
    row = {"id": 1, "run_id": 1, "source": "test", "origin": "LIS", "destination": "BCN",
           "departure_date": "2026-11-18", "return_date": "2026-11-25", "nights": 7,
           "price": 51, "currency": "EUR", "fetched_at": seen,
           **({"raw_json": "{}"} if version < 7 else
              {"last_run_id": 1, "last_seen_at": seen, "dedup_key": "k"})}
    old.execute(f"INSERT INTO price_observations ({', '.join(row)}) "
                f"VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
    old.execute("INSERT INTO deals (id, observation_id, rule, baseline_median, sample_size, "
                "discount_pct, threshold, detected_at, status) VALUES (4, 1, 'median', 76, 6, "
                "0.33, 0.3, '2026-10-14T01:01:35+00:00', 'rendered')")
    old.execute(f"PRAGMA user_version = {version}")
    old.commit()
    old.close()

    conn = db.connect(path)
    db.init(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 13
    fresh = db.connect(tmp_path / "fresh.db")
    db.init(fresh)
    assert _deal_columns(conn) == _deal_columns(fresh)
    deal, obs = db.get_deal(conn, 4)
    assert (deal.status, deal.baseline_median, deal.sample_size, obs.price) == ("rendered", 76, 6, 51)
    assert (deal.baseline_span_days, deal.baseline_lowest_obs_id,
            deal.baseline_highest_obs_id) == (None, None, None)
    assert pipeline.baseline_range(conn, deal) is None      # the review shows the days only


@respx.mock
def test_failed_affiliate_link_is_recorded_without_fallback(ctx):
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    mock_api()
    pipeline.run_collect(ctx, conn)
    _, results = pipeline.run_detect(ctx, conn)
    deal_id = {r.route: r for r in results}["LIS-LON"].deal_ids[0]
    mock_links(ok=False)
    deal, obs = db.get_deal(conn, deal_id)
    [(deal, _)] = pipeline.ensure_affiliate_links(ctx, conn, [(deal, obs)])
    assert deal.affiliate_url is None
    assert deal.affiliate_error == "trs is not subscribed for brand"


def _fixture_with(price):
    """The synthetic fixture with the 58 € LIS-LON trip repriced (and no stale search_date)."""
    data = json.loads(json.dumps(FIXTURE))
    first = data["data"][0]
    first["price"] = price
    first["link"] = first["link"].split("&search_date=")[0]
    return data


@respx.mock
def test_recheck_expires_deal_when_price_rises(ctx):
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    mock_api()
    pipeline.run_collect(ctx, conn)
    _, results = pipeline.run_detect(ctx, conn)
    deal_id = {r.route: r for r in results}["LIS-LON"].deal_ids[0]
    folder = ctx.output_dir / "2026-10-12" / f"deal-LIS-LON-{deal_id}"
    folder.mkdir(parents=True)                       # as if already rendered

    # Same price on the next run: still valid.
    respx.get(API_URL).mock(side_effect=lambda r: httpx.Response(
        200, json=_fixture_with(58) if r.url.params["destination"] == "LON" else EMPTY))
    pipeline.run_collect(ctx, conn)
    [(deal, _, check)] = pipeline.run_recheck(ctx, conn)
    assert check.valid and deal.status == "new" and deal.last_seen_price == 58

    # Price rises: expired, with a note in the rendered folder.
    respx.get(API_URL).mock(side_effect=lambda r: httpx.Response(
        200, json=_fixture_with(75) if r.url.params["destination"] == "LON" else EMPTY))
    pipeline.run_collect(ctx, conn)
    [(deal, _, check)] = pipeline.run_recheck(ctx, conn)
    assert not check.valid and deal.status == "expired" and deal.expired_reason == "o preço subiu para 75 €"
    assert "NÃO PUBLICAR" in (folder / "EXPIRADO.txt").read_text("utf-8")
    assert pipeline.run_recheck(ctx, conn) == []     # expired deals are not rechecked again


@respx.mock
def test_recheck_skips_routes_without_data(ctx):
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    mock_api()
    pipeline.run_collect(ctx, conn)
    pipeline.run_detect(ctx, conn)
    respx.get(API_URL).mock(return_value=httpx.Response(200, json=EMPTY))   # e.g. API hiccup
    pipeline.run_collect(ctx, conn)
    assert pipeline.run_recheck(ctx, conn) == []
