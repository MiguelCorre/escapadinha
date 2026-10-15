"""Routes as data: seeding, migration, per-kind rules and overrides through the pipeline seam."""

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import httpx
import respx
import yaml
from typer.testing import CliRunner

from escapadinha import cli, pipeline, routes
from escapadinha.collector.travelpayouts import API_URL
from escapadinha.config import Context
from escapadinha.models import Observation
from escapadinha.storage import db
from test_pipeline import EMPTY, FIXTURE, ctx, mock_api, seed_history  # noqa: F401 (fixture)

SEEDED = ["LIS-LON", "LIS-PAR", "LIS-ROM", "LIS-BCN", "LIS-AMS",
          "OPO-LON", "OPO-PAR", "OPO-BCN", "OPO-MIL", "OPO-BER"]


def v5_database(path) -> sqlite3.Connection:
    """An empty database exactly as schema v5 created it (before routes and dedup)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript((Path(__file__).parent / "fixtures" / "schema_v5.sql").read_text("utf-8"))
    conn.execute("PRAGMA user_version = 5")
    conn.commit()
    return conn


def configure(ctx: Context, **routes_cfg) -> Context:
    """Rewrite the temp project's config.yaml `routes` section; returns a fresh Context."""
    path = ctx.root / "config.yaml"
    data = yaml.safe_load(path.read_text("utf-8"))
    data["routes"].update(routes_cfg)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), "utf-8")
    return Context(root=ctx.root)


def test_fresh_database_is_seeded_once_as_europe(ctx):
    conn = pipeline.open_db(ctx)
    stored = routes.all_routes(conn, ctx.config.routes)
    assert [r.key for r in stored] == SEEDED
    assert {r.kind for r in stored} == {"europe"} and {r.status for r in stored} == {"active"}
    lis_lon = stored[0]
    assert lis_lon.city_pt == "Londres" and lis_lon.last_observed_at is None
    assert (lis_lon.rules.direct_only, lis_lon.rules.min_nights, lis_lon.rules.max_nights) == (True, 2, 10)

    # A non-empty table is never re-seeded: config's seed is a bootstrap, not the source of truth.
    ctx2 = configure(ctx, seed=[{"origin": "FAO", "destination": "LON", "city_pt": "Londres"}])
    conn2 = pipeline.open_db(ctx2)
    assert [r.key for r in routes.all_routes(conn2, ctx2.config.routes)] == SEEDED


def test_upgrade_from_v5_seeds_routes_and_backfills_last_observed(ctx):
    conn = v5_database(ctx.db_path)
    conn.executescript("""
        INSERT INTO fetch_runs (id, source, started_at, status) VALUES (1, 'test', '2026-10-01T00:00:00+00:00', 'ok');
        INSERT INTO price_observations (run_id, source, origin, destination, departure_date, return_date,
            nights, price, currency, fetched_at, raw_json)
        VALUES (1, 'test', 'LIS', 'LON', '2026-11-01', '2026-11-05', 4, 80, 'EUR', '2026-10-01T00:00:00+00:00', '{}'),
               (1, 'test', 'LIS', 'LON', '2026-11-02', '2026-11-06', 4, 90, 'EUR', '2026-10-02T00:00:00+00:00', '{}');
    """)
    newest = "2026-10-02T00:00:00+00:00"
    conn.close()

    conn = pipeline.open_db(ctx)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    lis_lon = pipeline.route_for(ctx, conn, "lis-lon")
    assert lis_lon.last_observed_at.isoformat() == newest
    assert pipeline.route_for(ctx, conn, "OPO-BER").last_observed_at is None


@respx.mock
def test_collect_updates_last_observed_only_for_routes_with_prices(ctx):
    conn = pipeline.open_db(ctx)
    mock_api()
    summary = pipeline.run_collect(ctx, conn)
    assert pipeline.route_for(ctx, conn, "LIS-LON").last_observed_at is not None
    assert pipeline.route_for(ctx, conn, "OPO-BER").last_observed_at is None
    assert summary.n_observations == 6        # 3 months x the two 2-10 night trips


@respx.mock
def test_override_widens_one_routes_nights_range(ctx):
    ctx = configure(ctx, overrides={"LIS-LON": {"max_nights": 14}})
    conn = pipeline.open_db(ctx)
    lis_lon = pipeline.route_for(ctx, conn, "LIS-LON")
    assert (lis_lon.rules.min_nights, lis_lon.rules.max_nights) == (2, 14)
    assert pipeline.route_for(ctx, conn, "OPO-LON").rules.max_nights == 10   # only that route
    mock_api()
    assert pipeline.run_collect(ctx, conn).n_observations == 9            # + the 14-night trip

    # Removing the override restores the kind default.
    ctx = configure(ctx, overrides={})
    conn = pipeline.open_db(ctx)
    assert pipeline.route_for(ctx, conn, "LIS-LON").rules.max_nights == 10


@respx.mock
def test_excluded_and_dormant_routes_are_not_collected(ctx):
    ctx = configure(ctx, exclusions=["PAR", "OPO-BER"])
    conn = pipeline.open_db(ctx)
    assert "OPO-BER" not in [r.key for r in routes.all_routes(conn, ctx.config.routes)]  # not seeded
    conn.execute("UPDATE routes SET status = 'dormant' WHERE origin = 'LIS' AND destination = 'ROM'")
    conn.commit()
    active = [r.key for r in routes.active_routes(conn, ctx.config.routes)]
    assert active == ["LIS-LON", "LIS-BCN", "LIS-AMS", "OPO-LON", "OPO-BCN", "OPO-MIL"]
    mock_api()
    assert pipeline.run_collect(ctx, conn).n_requests == 6 * 3
    _, results = pipeline.run_detect(ctx, conn)
    assert [r.route for r in results] == active


# --- long haul: one stop each way, 7-21 nights -------------------------------------------

def _tyo_payload(*trips):
    """API-shaped payload for LIS-TYO (synthetic, test data only)."""
    return {"success": True, "currency": "eur", "data": [
        {"price": price, "departure_at": f"{dep}T10:00:00+00:00", "return_at": f"{ret}T10:00:00+00:00",
         "transfers": out, "return_transfers": back, "airline": "TP", "flight_number": "1",
         "origin_airport": "LIS", "destination_airport": "NRT",
         "link": f"/search/LIS{dep[8:10]}{dep[5:7]}TYO{ret[8:10]}{ret[5:7]}1?t=test"}
        for price, dep, ret, out, back in trips]}


def _seed_tyo(conn, *, days: int, price: float):
    run_id = db.start_run(conn, "test")
    now = db.utcnow()
    db.insert_observations(conn, run_id, [
        Observation(source="test", origin="LIS", destination="TYO", origin_airport="LIS",
                    destination_airport="NRT",
                    departure_date=date(2026, 11, 1) + timedelta(days=i + k),
                    return_date=date(2026, 11, 11) + timedelta(days=i + k),
                    price=price + 50 * k, currency="EUR", airline="TP", flight_number="1",
                    transfers=1, return_transfers=1, deep_link=None,
                    fetched_at=now - timedelta(days=i + 4), raw_json="{}")
        for i in range(days) for k in (0, 1)])                    # 2 departure dates a day (D40)
    db.finish_run(conn, run_id, status="ok", n_requests=0, n_observations=2 * days, error=None)


@respx.mock
def test_long_haul_route_uses_its_kind_rules_end_to_end(ctx):
    ctx = configure(ctx, long_haul=[{"destination": "TYO", "city_pt": "Tóquio", "origins": ["LIS"]}])
    conn = pipeline.open_db(ctx)
    tyo = pipeline.route_for(ctx, conn, "LIS-TYO")
    assert tyo.kind == "long_haul" and tyo.city_pt == "Tóquio"
    assert (tyo.rules.direct_only, tyo.rules.max_transfers, tyo.rules.min_nights,
            tyo.rules.max_nights) == (False, 1, 7, 21)

    _seed_tyo(conn, days=10, price=800)                    # mature for promotions (D40)
    payload = _tyo_payload((520, "2026-11-10", "2026-11-20", 1, 1),    # one stop each way: ok
                           (400, "2026-11-12", "2026-11-22", 2, 1),    # two stops out: never
                           (300, "2026-11-14", "2026-11-18", 0, 0))    # 4 nights: not collected
    respx.get(API_URL).mock(side_effect=lambda r: httpx.Response(
        200, json=payload if r.url.params["destination"] == "TYO" else EMPTY))
    summary = pipeline.run_collect(ctx, conn)
    stored = [o.price for o in db.observations_seen_since(conn, summary.run_id)]
    assert sorted(stored) == [400, 520]     # stored once (3 identical months); 4-night trip dropped

    _, results = pipeline.run_detect(ctx, conn)
    tyo_result = {r.route: r for r in results}["LIS-TYO"]
    assert tyo_result.status == "deals" and tyo_result.baseline.median == 800
    _, obs = db.get_deal(conn, tyo_result.deal_ids[0])
    assert obs.price == 520 and obs.transfers == 1      # the two-stop 400 € never qualifies


@respx.mock
def test_collect_asks_for_nonstop_fares_only_on_routes_that_take_nothing_else(ctx):
    """D39: europe and domestic routes ask the cache with direct=true; a long-haul route,
    which allows a stop, keeps today's call. Same number of requests."""
    ctx = configure(ctx, long_haul=[{"destination": "TYO", "city_pt": "Tóquio", "origins": ["LIS"]}])
    conn = pipeline.open_db(ctx)
    api = respx.get(API_URL).mock(return_value=httpx.Response(200, json=EMPTY))
    summary = pipeline.run_collect(ctx, conn)

    asked = {}
    for call in api.calls:
        params = call.request.url.params
        asked.setdefault(f"{params['origin']}-{params['destination']}", set()).add(
            params.get("direct"))
    assert summary.n_requests == len(api.calls) == 33          # 11 routes × 3 months
    assert asked.pop("LIS-TYO") == {None}
    assert sorted(asked) == sorted(SEEDED) and all(v == {"true"} for v in asked.values())
    # The run archive keeps how each price was asked.
    from escapadinha import archive
    responses = archive.read(ctx.object_store, summary.archive_key)["responses"]
    assert {r["params"].get("direct") for r in responses if r["destination"] == "LON"} == {"true"}


def test_routes_list_prints_kind_rules_status_and_last_observed(ctx, monkeypatch):
    pipeline.open_db(ctx)                                    # seeded before the exclusion
    ctx = configure(ctx, long_haul=[{"destination": "TYO", "city_pt": "Tóquio", "origins": ["LIS"]}],
                    exclusions=["OPO-BER"])
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=2, price=100)
    db.touch_routes_observed(conn, conn.execute("SELECT MAX(id) FROM fetch_runs").fetchone()[0])
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    monkeypatch.setenv("COLUMNS", "200")
    out = CliRunner().invoke(cli.app, ["routes", "list"]).output
    lines = {line.split("│")[1].strip(): line for line in out.splitlines() if "→" in line}
    assert "Europa" in lines["LIS → LON"] and "só diretos" in lines["LIS → LON"]
    assert "2–10 noites" in lines["LIS → LON"] and "ativa" in lines["LIS → LON"]
    assert " às " in lines["LIS → LON"] and "nunca" in lines["LIS → PAR"]
    assert "Longo curso" in lines["LIS → TYO"] and "até 1 escala" in lines["LIS → TYO"]
    assert "7–21 noites" in lines["LIS → TYO"]
    assert "excluída" in lines["OPO → BER"]
    assert "11 rotas, 10 ativas, 0 adormecidas." in out


def test_unknown_route_kind_is_rejected_by_the_database(ctx):
    conn = pipeline.open_db(ctx)
    try:
        conn.execute("INSERT INTO routes (origin, destination, city_pt, kind, discovered_at) "
                     "VALUES ('LIS', 'XXX', 'X', 'mars', '2026-10-13T00:00:00+00:00')")
    except sqlite3.IntegrityError:
        return
    raise AssertionError("CHECK constraint on kind did not fire")


def test_collect_runs_requests_concurrently_and_stores_in_request_order(ctx):
    """Option a) for the Actions budget: 8 requests in flight, same results as one at a time."""
    import threading
    import time

    from escapadinha.collector.base import Fetched
    from escapadinha.collector.plan import plan
    from escapadinha.collector.runner import collect

    class SlowSource:
        name = "test"

        def __init__(self):
            self.active = self.peak = 0
            self.lock = threading.Lock()

        def fetch(self, origin, destination, month, *, rules):
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            time.sleep(0.02)
            with self.lock:
                self.active -= 1
            if destination == "PAR":
                raise RuntimeError("boom")
            return Fetched([], {"origin": origin, "destination": destination,
                                "month": f"{month:%Y-%m}", "payload": {"data": []}})

    conn = pipeline.open_db(ctx)
    active = routes.active_routes(conn, ctx.config.routes)
    source = SlowSource()
    asked = plan(active, today=date(2026, 10, 13), daily=True, months_ahead=3, daily_months_ahead=3)
    summary = collect(conn, source, asked, store=ctx.object_store, workers=8)
    assert source.peak > 1 and summary.n_requests == 30 and summary.status == "partial"
    assert len(summary.errors) == 6 and all("PAR" in e for e in summary.errors)
    from escapadinha import archive
    stored = archive.read(ctx.object_store, summary.archive_key)["responses"]
    expected = [(r.origin, r.destination) for r in active if r.destination != "PAR" for _ in range(3)]
    assert [(r["origin"], r["destination"]) for r in stored] == expected     # request order kept


def test_rate_limiter_is_shared_safely_between_threads():
    import threading

    from escapadinha.collector.travelpayouts import RateLimiter

    clock = {"t": 0.0}
    slept = []

    def sleep(s):
        slept.append(s)
        clock["t"] += s

    limiter = RateLimiter(10, clock=lambda: clock["t"], sleep=sleep)
    threads = [threading.Thread(target=limiter.wait) for _ in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(limiter._calls) <= 10 and len(slept) == 2      # 25 calls: two full-minute waits
