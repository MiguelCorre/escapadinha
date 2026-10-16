"""Observation deduplication and the per-run raw archive, through the pipeline seam."""

import json
import sqlite3
from pathlib import Path

import httpx
import respx
from typer.testing import CliRunner

from escapadinha import archive, cli, pipeline
from escapadinha.collector.travelpayouts import API_URL
from escapadinha.storage import db
from test_pipeline import EMPTY, FIXTURE, ctx, mock_api, seed_history  # noqa: F401 (fixture)
from test_review import price_api
from test_routes import v5_database

RECORDED = json.loads((Path(__file__).parent / "fixtures" /
                       "recorded_prices_for_dates_LIS_LON_2026-11.json").read_text("utf-8"))


def mock_recorded():
    respx.get(API_URL).mock(side_effect=lambda r: httpx.Response(
        200, json=RECORDED if r.url.params["destination"] == "LON"
        and r.url.params["origin"] == "LIS" else EMPTY))


def count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0]


@respx.mock
def test_recorded_fixture_collected_twice_stores_nothing_new(ctx):
    conn = pipeline.open_db(ctx)
    mock_recorded()
    first = pipeline.run_collect(ctx, conn)
    rows = count(conn)
    assert first.n_new == rows > 0
    assert first.n_repeated == first.n_observations - rows     # same payload for 3 months

    second = pipeline.run_collect(ctx, conn)
    assert second.n_new == 0 and second.n_repeated == second.n_observations == first.n_observations
    assert count(conn) == rows
    stats = conn.execute("""SELECT MIN(run_id), MAX(run_id), MIN(last_run_id), MIN(seen_count),
                                   MAX(seen_count) FROM price_observations""").fetchone()
    assert tuple(stats) == (first.run_id, first.run_id, second.run_id, 2, 2)  # first run kept
    run = conn.execute("SELECT n_observations, n_new FROM fetch_runs WHERE id = ?",
                       (second.run_id,)).fetchone()
    assert tuple(run) == (second.n_observations, 0)


@respx.mock
def test_each_run_archives_its_raw_responses_verbatim(ctx):
    conn = pipeline.open_db(ctx)
    mock_recorded()
    summary = pipeline.run_collect(ctx, conn)
    assert summary.archive_key == archive.run_key(summary.run_id)
    assert db.run_archive_key(conn, summary.run_id) == summary.archive_key
    stored = archive.read(ctx.object_store, summary.archive_key)
    assert stored["run_id"] == summary.run_id and not stored["reconstructed"]
    assert len(stored["responses"]) == summary.n_requests == 30
    lis_lon = [r for r in stored["responses"] if (r["origin"], r["destination"]) == ("LIS", "LON")]
    assert all(r["payload"] == RECORDED for r in lis_lon)
    assert "X-Access-Token" not in json.dumps(stored) and "test-token" not in json.dumps(stored)
    assert "raw_json" not in [c[1] for c in conn.execute("PRAGMA table_info(price_observations)")]


@respx.mock
def test_promotion_traces_back_to_the_archived_payload(ctx):
    """price → deal → observation → first run → archive object → the API item."""
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    mock_api()
    pipeline.run_collect(ctx, conn)
    _, results = pipeline.run_detect(ctx, conn)
    _, obs = db.get_deal(conn, {r.route: r for r in results}["LIS-LON"].deal_ids[0])
    stored = archive.read(ctx.object_store, db.run_archive_key(conn, obs.run_id))
    matches = [i for i in archive.items(stored)
               if i["price"] == obs.price and i["departure_at"] == obs.departure_at]
    assert matches and matches[0]["return_at"] == obs.return_at


@respx.mock
def test_offer_seen_again_after_its_deal_expired_is_not_flagged_twice(ctx):
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    mock_api()
    pipeline.run_collect(ctx, conn)
    _, results = pipeline.run_detect(ctx, conn)
    deal_id = {r.route: r for r in results}["LIS-LON"].deal_ids[0]
    db.set_deal_status(conn, deal_id, "expired")      # e.g. the trip vanished for one run

    pipeline.run_collect(ctx, conn)                   # the very same offer comes back
    _, again = pipeline.run_detect(ctx, conn)         # same row: must not crash on UNIQUE
    assert {r.route: r for r in again}["LIS-LON"].deal_ids == []


@respx.mock
def test_live_check_run_is_archived_and_counts_as_a_sighting(ctx):
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    mock_api()
    pipeline.run_collect(ctx, conn)
    _, results = pipeline.run_detect(ctx, conn)
    deal_id = {r.route: r for r in results}["LIS-LON"].deal_ids[0]
    price_api(58)
    deal, check = pipeline.live_check(ctx, conn, deal_id)
    assert check.valid
    live_run = conn.execute("SELECT MAX(id) FROM fetch_runs WHERE scope = 'live_check'").fetchone()[0]
    assert archive.read(ctx.object_store, db.run_archive_key(conn, live_run))["responses"]
    # The recheck against the latest full run still sees the offer (last_run_id moved on).
    assert [o.price for o in db.observations_seen_since(conn, db.latest_completed_run_id(conn))
            if o.route_key == "LIS-LON"]


def test_stats_shows_seen_counts(ctx, monkeypatch):
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=3, price=100)
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    out = CliRunner().invoke(cli.app, ["stats", "LIS-LON"]).output
    assert "6 distinct offers, seen 6 times in total (most repeated: 1 runs)" in out   # 2 a day


# --- migration 7 ------------------------------------------------------------------------

def _item(price, dep="2026-11-01T07:00:00+00:00", ret="2026-11-05T19:00:00+00:00"):
    return json.dumps({"price": price, "departure_at": dep, "return_at": ret, "airline": "TP",
                       "flight_number": 1})


def test_upgrade_collapses_duplicates_keeps_deals_and_archives_raw_json(ctx):
    conn = v5_database(ctx.db_path)
    for run in (1, 2, 3):
        conn.execute("INSERT INTO fetch_runs (id, source, started_at, status) VALUES (?, 'test', ?, 'ok')",
                     (run, f"2026-10-0{run}T00:00:00+00:00"))
    obs_sql = """INSERT INTO price_observations (id, run_id, source, origin, destination,
                     departure_date, return_date, nights, price, currency, airline, flight_number,
                     fetched_at, found_date, raw_json)
                 VALUES (?, ?, 'travelpayouts', 'LIS', 'LON', '2026-11-01', '2026-11-05', 4, ?, 'EUR',
                         'TP', '1', ?, '2026-10-01', ?)"""
    conn.execute(obs_sql, (1, 1, 80, "2026-10-01T00:00:00+00:00", _item(80)))
    conn.execute(obs_sql, (2, 2, 80, "2026-10-02T00:00:00+00:00", _item(80)))   # repeat
    conn.execute(obs_sql, (3, 3, 80, "2026-10-03T00:00:00+00:00", _item(80)))   # repeat
    conn.execute(obs_sql, (4, 3, 95, "2026-10-03T00:00:00+00:00", _item(95)))   # other offer
    conn.execute("""INSERT INTO deals (id, observation_id, rule, sample_size, threshold, detected_at, status)
                    VALUES (7, 2, 'median', 5, 0.3, '2026-10-02T00:00:00+00:00', 'expired')""")
    conn.commit()
    conn.close()

    conn = pipeline.open_db(ctx)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert [r[0] for r in conn.execute("SELECT id FROM price_observations ORDER BY id")] == [2, 4]
    deal, obs = db.get_deal(conn, 7)                                 # the deal still resolves
    assert obs.id == 2 and obs.price == 80
    assert (obs.run_id, obs.last_run_id, obs.seen_count) == (1, 3, 3)
    assert obs.fetched_at.isoformat() == "2026-10-01T00:00:00+00:00"
    assert obs.last_seen_at.isoformat() == "2026-10-03T00:00:00+00:00"
    assert obs.departure_at == "2026-11-01T07:00:00+00:00"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'raw_pending'").fetchone()

    # Nothing lost: every run's raw items are in its archive object.
    for run, prices in ((1, [80]), (2, [80]), (3, [80, 95])):
        stored = archive.read(ctx.object_store, db.run_archive_key(conn, run))
        assert stored["reconstructed"] and sorted(i["price"] for i in archive.items(stored)) == prices

    # The next collection of the same offer is a repeat, not a new row.
    again = db.insert_observations(conn, db.start_run(conn, "travelpayouts"), [obs])
    assert (again.new, again.repeated) == (0, 1)


def test_fresh_install_has_no_pending_archive_work(ctx):
    conn = pipeline.open_db(ctx)
    assert ctx.object_store.list() == []
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert isinstance(conn, sqlite3.Connection)
