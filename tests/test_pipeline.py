"""End-to-end: mocked API → SQLite → detector → slides/captions, in a temp project root."""

import json
import shutil
import struct
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from escapadinha import pipeline
from escapadinha.collector.travelpayouts import API_URL
from escapadinha.config import Context
from escapadinha.models import Observation
from escapadinha.presentation import DISCLOSURE
from escapadinha.storage import db

REPO = Path(__file__).parent.parent
FIXTURE = json.loads((REPO / "tests" / "fixtures" / "prices_for_dates_LIS_LON.json").read_text("utf-8"))
EMPTY = {"success": True, "currency": "eur", "data": []}


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    shutil.copy(REPO / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / "assets").mkdir()
    shutil.copy(REPO / "assets" / "logo.svg", tmp_path / "assets" / "logo.svg")
    shutil.copytree(REPO / "content", tmp_path / "content")
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "test-token")
    monkeypatch.setenv("TRAVELPAYOUTS_MARKER", "424242")
    return Context(root=tmp_path)


def seed_history(conn, *, days: int, price: float):
    """Synthetic past observations for LIS-LON (test data only)."""
    run_id = db.start_run(conn, "test")
    now = db.utcnow()
    db.insert_observations(conn, run_id, [
        Observation(source="test", origin="LIS", destination="LON", origin_airport="LIS",
                    destination_airport="LGW", departure_date=date(2026, 11, 1) + timedelta(days=i),
                    return_date=date(2026, 11, 5) + timedelta(days=i), price=price + i % 3,
                    currency="EUR", airline="TP", flight_number="1", transfers=0,
                    return_transfers=0, deep_link=None, fetched_at=now - timedelta(days=i + 1),
                    raw_json="{}")
        for i in range(days)
    ])
    db.finish_run(conn, run_id, status="ok", n_requests=0, n_observations=days, error=None)


def mock_api():
    def respond(request):
        lis_lon = request.url.params["origin"] == "LIS" and request.url.params["destination"] == "LON"
        return httpx.Response(200, json=FIXTURE if lis_lon else EMPTY)
    respx.get(API_URL).mock(side_effect=respond)


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
    assert by_route["OPO-BCN"].status == "no_data"
    assert by_route["LIS-LON"].baseline.median == 101

    deal, obs = db.get_deal(conn, by_route["LIS-LON"].deal_ids[0])
    assert obs.price == 58 and obs.run_id == summary.run_id     # traceable to this run
    assert deal.rule == "median" and deal.sample_size == 22   # seeded days older than 3 days

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

    [out] = pipeline.run_render_deals(ctx, conn)
    slides = sorted(out.glob("slide_*.png"))
    assert [png_size(p) for p in slides] == [(1080, 1350)] * 3
    caption = (out / "caption.txt").read_text("utf-8")
    assert DISCLOSURE in caption and "58 €" in caption
    meta = json.loads((out / "meta.json").read_text("utf-8"))
    assert meta["source"] == "travelpayouts" and meta["observation_id"]
    assert meta["affiliate_url"].endswith("marker=424242")
    assert pipeline.run_render_deals(ctx, conn) == []      # status moved to 'rendered'

    guide_dir, reviewed = pipeline.run_render_guide(ctx, conn, "voos-baratos-dicas")
    assert len(list(guide_dir.glob("slide_*.png"))) == 7 and reviewed is False
    assert (guide_dir / "caption.txt").exists()


def test_migrates_v1_database(tmp_path):
    """A v1 database (no found_date column) is upgraded in place, keeping its rows."""
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
        INSERT INTO fetch_runs (id, source, started_at, status) VALUES (1, 'test', '2026-10-01T00:00:00+00:00', 'ok');
        INSERT INTO price_observations VALUES (1, 1, 'test', 'LIS', 'LON', 'LIS', 'LGW', '2026-11-01',
            '2026-11-05', 4, 80, 'EUR', 'TP', '1', 0, 0, NULL, '2026-10-01T00:00:00+00:00', '{}');
        PRAGMA user_version = 1;
    """)
    raw.close()
    conn = db.connect(path)
    db.init(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    obs = db.get_observation(conn, 1)
    assert obs.price == 80 and obs.found_date is None
