"""Route discovery (#5): recorded catalogue fixtures → routes table, dormancy, monthly schedule,
photos for new destinations. Every payload here is a trimmed real response (fixtures/discovery)."""

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx
import yaml
from typer.testing import CliRunner

from escapadinha import cli, discovery, pipeline, routes
from escapadinha.collector import catalogue
from escapadinha.collector.travelpayouts import API_URL, RateLimiter
from escapadinha.config import AppConfig, Context
from escapadinha.models import Observation
from escapadinha.photos import SEARCH_URL
from escapadinha.storage import db
from test_pipeline import EMPTY, FIXTURE, REPO, ctx  # noqa: F401 (fixture)
from test_routes import configure, v5_database

FIX = Path(__file__).parent / "fixtures" / "discovery"
ORIGINS = ["LIS", "OPO", "FAO", "FNC", "PDL", "TER"]
LONG_HAUL = [{"destination": "NYC", "city_pt": "Nova Iorque", "origins": ["LIS", "OPO"]},
             {"destination": "TYO", "city_pt": "Tóquio", "origins": ["LIS"]}]
T0 = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def load(name: str):
    return json.loads((FIX / name).read_text("utf-8"))


def fixture_discovery() -> list[discovery.Found]:
    cat = discovery.Catalogue.from_payloads(load("routes.json"), load("airports.json"),
                                            load("pt_cities.json"), ORIGINS)
    return discovery.discover(
        cat, ORIGINS,
        popular={"LIS": load("city_directions_LIS.json"), "OPO": load("city_directions_OPO.json")},
        recent={"FAO": [load("prices_for_dates_FAO_direct_2026-11.json")]},
        long_haul=[discovery.LongHaul(d["destination"], d["city_pt"], tuple(d["origins"]))
                   for d in LONG_HAUL])


# --- pure discovery ---------------------------------------------------------------------

def test_fixture_yields_the_direct_routes_of_all_six_origins_with_pt_names():
    found = {f.key: (f.kind, f.city_pt) for f in fixture_discovery()}
    assert found == {
        "LIS-FNC": ("domestic", "Madeira"), "LIS-HAJ": ("europe", "Hanôver"),
        "LIS-IEV": ("europe", "Kiev"), "LIS-LON": ("europe", "Londres"),
        "LIS-MAD": ("europe", "Madrid"), "LIS-MOW": ("europe", "Moscovo"),
        "LIS-NYC": ("long_haul", "Nova Iorque"), "LIS-PAR": ("europe", "Paris"),
        "LIS-RAK": ("europe", "Marraqueche Menara"), "LIS-TYO": ("long_haul", "Tóquio"),
        "OPO-BER": ("europe", "Berlim"), "OPO-LON": ("europe", "Londres"),
        "OPO-NYC": ("long_haul", "Nova Iorque"), "OPO-TCI": ("europe", "Tenerife"),
        "FAO-DUB": ("europe", "Dublin"), "FAO-FMM": ("europe", "Memmingen"),
        "FAO-LON": ("europe", "Londres"), "FAO-OPO": ("domestic", "Porto"),
        "FAO-ZRH": ("europe", "Zurique"),
        "FNC-LPA": ("europe", "Gran Canária"), "FNC-PXO": ("domestic", "Porto Santo"),
        "PDL-HOR": ("domestic", "Horta"), "PDL-LIS": ("domestic", "Lisboa"),
        "TER-FLW": ("domestic", "Ilha das Flores"), "TER-LIS": ("domestic", "Lisboa"),
    }
    # Not routes: LIS-LAD (Angola) and PDL-BOS (USA) are outside Europe and not curated for
    # that origin; LIS-AMS, LIS-RIO and OPO-PAR were popular only with a stop.


def test_airports_map_to_city_codes_and_sources_merge():
    by_key = {f.key: f for f in fixture_discovery()}
    assert by_key["LIS-LON"].airports == {"LGW", "LHR", "LTN"}
    assert by_key["LIS-PAR"].airports == {"CDG", "ORY"}
    assert by_key["LIS-LON"].city_en == "London"
    assert by_key["OPO-NYC"].sources == {"catalogue", "popular", "curated"}
    assert by_key["FAO-ZRH"].sources == {"catalogue", "recent"}     # a codeshare row counts
    assert by_key["LIS-HAJ"].airports == frozenset()                # popular gives cities only


def test_only_nonstop_catalogue_rows_from_the_origins_count():
    rows = load("routes.json")
    with_stops = [r for r in rows if r["departure_airport_iata"] == "DAR" and r["transfers"] > 0]
    assert {r["transfers"] for r in with_stops} == {1, 2}
    cat = discovery.Catalogue.from_payloads(with_stops, [], [], ["DAR"])
    assert cat.direct["DAR"] == frozenset()          # one or two stops: not a direct route
    cat = discovery.Catalogue.from_payloads(rows, [], [], ["DAR", "AER"])
    assert cat.direct["DAR"] == {"ZNZ"}              # the same pair also has a nonstop row
    assert cat.direct["AER"] == {"DME"}
    ours = discovery.Catalogue.from_payloads(rows, [], [], ORIGINS)
    assert set(ours.direct) == set(ORIGINS) and "ZNZ" not in set().union(*ours.direct.values())


def test_kind_follows_the_destination_country():
    assert discovery.kind_of("PT") == "domestic"
    assert discovery.kind_of("ES") == discovery.kind_of("MA") == discovery.kind_of("TR") == "europe"
    assert discovery.kind_of("US") is None and discovery.kind_of("CV") is None


def test_failed_supplement_payloads_add_nothing():
    assert discovery.popular_direct({"success": False, "data": {"MAD": {"transfers": 0}}}) == set()
    assert discovery.recent_direct({"success": False, "data": [{"destination": "MAD", "transfers": 0}]}) \
        == (set(), {})


# --- through the pipeline seam (catalogue + Pixabay mocked with the recorded payloads) ---------

PIXABAY_HIT = {"id": 1, "pageURL": "https://pixabay.com/photos/x-1/", "user": "ana", "user_id": 42,
               "largeImageURL": "https://pixabay.com/get/x_1280.jpg"}


def mock_catalogue(*, popular_status: int = 200):
    respx.get(catalogue.ROUTES_URL).mock(return_value=httpx.Response(200, json=load("routes.json")))
    respx.get(catalogue.AIRPORTS_URL).mock(return_value=httpx.Response(200, json=load("airports.json")))
    respx.get(catalogue.CITIES_PT_URL).mock(return_value=httpx.Response(200, json=load("pt_cities.json")))
    popular = {"LIS": load("city_directions_LIS.json"), "OPO": load("city_directions_OPO.json")}

    def directions(request):
        if popular_status != 200:
            return httpx.Response(popular_status, text="unavailable")
        return httpx.Response(200, json=popular.get(request.url.params["origin"],
                                                    {"success": True, "currency": "eur", "data": {}}))

    def prices(request):
        p = request.url.params
        if "destination" not in p and p["origin"] == "FAO" and p["direct"] == "true":
            return httpx.Response(200, json=load("prices_for_dates_FAO_direct_2026-11.json"))
        return httpx.Response(200, json=FIXTURE if p.get("destination") == "LON" and p["origin"] == "LIS"
                              else EMPTY)

    respx.get(catalogue.DIRECTIONS_URL).mock(side_effect=directions)
    respx.get(API_URL).mock(side_effect=prices)


def mock_pixabay():
    search = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [PIXABAY_HIT]}))
    respx.get(PIXABAY_HIT["largeImageURL"]).mock(return_value=httpx.Response(200, content=b"jpeg"))
    return search


@pytest.fixture
def dctx(ctx, monkeypatch):
    """The test project with the curated long-haul list of these tests and a Pixabay key."""
    monkeypatch.setenv("PIXABAY_API_KEY", "test-key")
    return configure(ctx, long_haul=LONG_HAUL)


@respx.mock
def test_discover_stores_routes_honours_exclusions_and_keeps_existing_names(dctx):
    conn = pipeline.open_db(dctx)
    mock_catalogue()
    mock_pixabay()
    result = pipeline.run_discover(dctx, conn, T0)

    stored = {r.key: r for r in routes.all_routes(conn, dctx.config.routes)}
    assert {f.key for f in result.applied.excluded} == {"LIS-MOW", "LIS-IEV"}   # config: MOW, IEV
    assert "LIS-MOW" not in stored and "LIS-IEV" not in stored
    for key in ("FAO-FMM", "TER-FLW", "PDL-LIS", "FNC-PXO", "OPO-BER", "LIS-HAJ"):
        assert key in stored and stored[key].status == "active"
    assert stored["TER-FLW"].kind == "domestic" and stored["TER-FLW"].city_pt == "Ilha das Flores"
    assert stored["FAO-FMM"].discovered_at == T0
    # Long-haul routes come with their kind's rules (one stop each way, 7-21 nights).
    nyc = stored["OPO-NYC"]
    assert nyc.kind == "long_haul" and nyc.destination_airports == "EWR"
    assert (nyc.rules.direct_only, nyc.rules.max_transfers, nyc.rules.min_nights,
            nyc.rules.max_nights) == (False, 1, 7, 21)
    # A seeded route keeps its hand-written name and rules, and learns airports + English name.
    lis_lon = stored["LIS-LON"]
    assert (lis_lon.city_pt, lis_lon.kind, lis_lon.destination_airports, lis_lon.city_en) == \
        ("Londres", "europe", "LGW,LHR,LTN", "London")
    assert {f.key for f in result.applied.added} == set(stored) - {
        "LIS-LON", "LIS-PAR", "LIS-ROM", "LIS-BCN", "LIS-AMS", "OPO-LON", "OPO-PAR", "OPO-BCN",
        "OPO-MIL", "OPO-BER", "LIS-NYC", "OPO-NYC", "LIS-TYO"}
    assert result.errors == []
    assert pipeline.last_discovery(conn) == T0

    # Running it again changes nothing.
    again = pipeline.run_discover(dctx, conn, T0 + timedelta(days=1), photos=False)
    assert again.applied.added == [] and again.applied.reactivated == []
    assert len(routes.all_routes(conn, dctx.config.routes)) == len(stored)


@respx.mock
def test_city_names_in_config_beat_the_catalogue(dctx):
    ctx = configure(dctx, city_names={"RAK": "Marraquexe", "LON": "Londres (todos)"})
    conn = pipeline.open_db(ctx)
    mock_catalogue()
    pipeline.run_discover(ctx, conn, T0, photos=False)
    assert pipeline.route_for(ctx, conn, "LIS-RAK").city_pt == "Marraquexe"
    assert pipeline.route_for(ctx, conn, "OPO-LON").city_pt == "Londres (todos)"   # existing too


@respx.mock
def test_dry_run_and_failed_supplement(dctx):
    conn = pipeline.open_db(dctx)
    before = len(routes.all_routes(conn, dctx.config.routes))
    mock_catalogue(popular_status=503)
    result = pipeline.run_discover(dctx, conn, T0, dry_run=True)
    assert len(routes.all_routes(conn, dctx.config.routes)) == before
    assert pipeline.last_discovery(conn) is None
    assert len(result.errors) == 6 and all("popular directions" in e for e in result.errors)
    # Without the popular directions, LIS-HAJ (popular only) is not found; the rest still is.
    keys = {f.key for f in result.applied.found}
    assert "LIS-HAJ" not in keys and "FAO-FMM" in keys


@respx.mock
def test_new_destinations_get_a_photo_with_english_query_and_overrides(dctx):
    data = yaml.safe_load((dctx.root / "config.yaml").read_text("utf-8"))
    data["photos"]["max_per_run"] = 45                      # all fixture destinations at once
    (dctx.root / "config.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), "utf-8")
    dctx = Context(root=dctx.root)
    conn = pipeline.open_db(dctx)
    mock_catalogue()
    search = mock_pixabay()
    result = pipeline.run_discover(dctx, conn, T0)

    queries = {call.request.url.params["q"] for call in search.calls}
    assert "Memmingen" in queries and "Hannover" in queries          # English catalogue names
    assert "Flores Azores" in queries and "Flores Island (Azores)" not in queries   # override
    assert "London skyline" in queries and "Londres" not in queries     # photos.queries override
    photo = db.get_photo(conn, "FMM")
    assert photo.photographer == "ana" and photo.source == "pixabay"
    assert (dctx.photos_dir / "FMM.jpg").read_bytes() == b"jpeg"
    assert result.photos_missing == 0
    # Nothing left to fetch: the next run makes no Pixabay call.
    calls = search.call_count
    assert pipeline.run_missing_photos(dctx, conn) == ([], 0) and search.call_count == calls


@respx.mock
def test_photos_are_capped_per_run_and_failures_retried(dctx):
    data = yaml.safe_load((dctx.root / "config.yaml").read_text("utf-8"))
    data["photos"]["max_per_run"] = 3
    (dctx.root / "config.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), "utf-8")
    ctx = Context(root=dctx.root)
    conn = pipeline.open_db(ctx)
    mock_catalogue()
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": []}))
    result = pipeline.run_discover(ctx, conn, T0)
    assert len(result.photos) == 3 and all("No Pixabay results" in r for _, r in result.photos)
    assert result.photos_missing == len(pipeline.missing_photos(ctx, conn)) > 3


# --- monthly schedule -------------------------------------------------------------------

@respx.mock
def test_discovery_runs_monthly(dctx):
    conn = pipeline.open_db(dctx)
    mock_catalogue()
    mock_pixabay()
    assert pipeline.discovery_due(dctx, conn, T0)                  # never ran
    assert pipeline.run_discover_if_due(dctx, conn, T0) is not None
    assert pipeline.run_discover_if_due(dctx, conn, T0 + timedelta(days=29)) is None
    assert pipeline.run_discover_if_due(dctx, conn, T0 + timedelta(days=30)) is not None
    assert pipeline.last_discovery(conn) == T0 + timedelta(days=30)


@respx.mock
def test_scheduled_run_survives_a_failed_discovery(dctx, monkeypatch, capsys):
    monkeypatch.setenv("ESCAPADINHA_HOME", str(dctx.root))
    respx.get(catalogue.ROUTES_URL).mock(return_value=httpx.Response(502, text="bad gateway"))
    cli.routes_upkeep()                                   # what `run` calls before collecting
    assert "Descoberta de rotas falhou, a recolha continua" in capsys.readouterr().out
    conn = pipeline.open_db(dctx)
    assert pipeline.last_discovery(conn) is None          # retried by the next run


@respx.mock
def test_routes_discover_cli_and_list_counts_per_origin(dctx, monkeypatch):
    monkeypatch.setenv("ESCAPADINHA_HOME", str(dctx.root))
    monkeypatch.setenv("COLUMNS", "200")
    mock_catalogue()
    out = CliRunner().invoke(cli.app, ["routes", "discover", "--no-photos"]).output
    assert "Rotas encontradas: LIS 10 · OPO 4 · FAO 5 · FNC 2 · PDL 2 · TER 2 (total 25)" in out
    assert "2 excluídas na config: LIS-IEV Kiev, LIS-MOW Moscovo" in out

    conn = pipeline.open_db(dctx)
    conn.execute("UPDATE routes SET status = 'dormant' WHERE origin = 'TER' AND destination = 'FLW'")
    conn.commit()
    out = CliRunner().invoke(cli.app, ["routes", "list"]).output
    per_origin = {line.split("│")[1].strip().split()[0]: [c.strip() for c in line.split("│")[2:6]]
                  for line in out.split("Rotas por origem")[1].splitlines() if line.startswith("│")}
    assert per_origin["TER"] == ["1", "1", "0", "2"]               # active, dormant, excluded, total
    assert per_origin["LIS"][0] == "11"                            # 5 seeded + 4 new + NYC + TYO
    assert "Última descoberta: " in out and "nunca" not in out.split("Última descoberta: ")[1]


# --- dormancy and reactivation ------------------------------------------------------------

def _observe(conn, origin: str, destination: str, at: datetime) -> None:
    """A sighting at `at` of one fixed offer (synthetic, test data only), as the collector would."""
    run_id = db.start_run(conn, "test")
    db.insert_observations(conn, run_id, [Observation(
        source="test", origin=origin, destination=destination, origin_airport=origin,
        destination_airport=destination, departure_date=date(2027, 3, 1),
        return_date=date(2027, 3, 5), price=99, currency="EUR", airline="TP",
        flight_number="1", transfers=0, return_transfers=0, deep_link=None, fetched_at=at)])
    db.finish_run(conn, run_id, status="ok", n_requests=1, n_observations=1, error=None)
    db.touch_routes_observed(conn, run_id)


def test_repeated_sightings_keep_a_route_observed(ctx):
    conn = pipeline.open_db(ctx)
    _observe(conn, "LIS", "LON", T0 - timedelta(days=40))
    _observe(conn, "LIS", "LON", T0 - timedelta(days=2))     # the same offer, seen again
    assert db.route_stats(conn, "LIS", "LON")["n"] == 1
    assert pipeline.route_for(ctx, conn, "LIS-LON").last_observed_at == T0 - timedelta(days=2)


@respx.mock
def test_dormant_after_30_days_without_prices_then_reactivated_by_discovery(dctx):
    t0 = db.utcnow()                  # seeded routes are stamped with the real clock
    conn = pipeline.open_db(dctx)
    mock_catalogue()
    pipeline.run_discover(dctx, conn, t0, photos=False)
    total = len(routes.all_routes(conn, dctx.config.routes))
    _observe(conn, "LIS", "LON", t0 + timedelta(days=10))

    # 29 days after discovery nothing sleeps; a never-observed route counts from discovered_at.
    assert routes.mark_dormant(conn, dctx.config.routes, t0 + timedelta(days=29)) == []
    slept = {r.key for r in routes.mark_dormant(conn, dctx.config.routes, t0 + timedelta(days=31))}
    assert "FAO-FMM" in slept and "LIS-LON" not in slept      # LIS-LON observed 21 days ago
    assert {r.key for r in routes.mark_dormant(conn, dctx.config.routes, t0 + timedelta(days=41))} \
        == {"LIS-LON"}

    # The collector skips dormant routes; nothing was deleted.
    assert routes.active_routes(conn, dctx.config.routes) == []
    assert pipeline.run_collect(dctx, conn).n_requests == 0
    assert len(routes.all_routes(conn, dctx.config.routes)) == total

    # The next discovery finds them again: active, and collected by the next run.
    later = t0 + timedelta(days=45)
    result = pipeline.run_discover(dctx, conn, later, photos=False)
    assert {"FAO-FMM", "LIS-LON"} <= {f.key for f in result.applied.reactivated}
    assert pipeline.route_for(dctx, conn, "FAO-FMM").status == "active"
    # Seeded routes no source returns this time (e.g. LIS-ROM) stay dormant.
    assert pipeline.route_for(dctx, conn, "LIS-ROM").status == "dormant"
    active = routes.active_routes(conn, dctx.config.routes)
    summary = pipeline.run_collect(dctx, conn)
    assert summary.n_requests == 3 * len(active)

    # That run is the probe: a route that got prices stays, one without goes back to sleep.
    _observe(conn, "LIS", "LON", later + timedelta(minutes=30))
    probed = {r.key for r in pipeline.run_dormancy(dctx, conn, summary, later + timedelta(hours=1))}
    assert "FAO-FMM" in probed and "LIS-LON" not in probed
    assert len(routes.all_routes(conn, dctx.config.routes)) == total


def test_failed_collection_puts_nothing_to_sleep(ctx):
    conn = pipeline.open_db(ctx)
    failed = pipeline.RunSummary(1, "failed", 30, 0, 0, 0, None, ["down"])
    assert pipeline.run_dormancy(ctx, conn, failed, db.utcnow() + timedelta(days=400)) == []


def test_excluded_routes_are_left_alone_by_dormancy(ctx):
    pipeline.open_db(ctx)                                    # seeded before the exclusion
    ctx = configure(ctx, exclusions=["LIS-LON"])
    conn = pipeline.open_db(ctx)
    assert routes.mark_dormant(conn, ctx.config.routes, db.utcnow() + timedelta(days=400)) != []
    assert pipeline.route_for(ctx, conn, "LIS-LON").status == "active"


# --- schema upgrades ----------------------------------------------------------------------

def _columns(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_upgrade_from_v7_adds_city_en_and_meta_and_keeps_routes(ctx):
    ctx.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ctx.db_path)
    conn.executescript((Path(__file__).parent / "fixtures" / "schema_v7.sql").read_text("utf-8"))
    conn.execute("""INSERT INTO routes (origin, destination, city_pt, kind, status, discovered_at)
                    VALUES ('FAO', 'DUB', 'Dublin', 'europe', 'dormant', '2026-09-01T00:00:00+00:00')""")
    conn.execute("PRAGMA user_version = 7")
    conn.commit()
    conn.close()

    conn = pipeline.open_db(ctx)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 8
    dub = pipeline.route_for(ctx, conn, "FAO-DUB")
    assert (dub.status, dub.city_pt, dub.city_en) == ("dormant", "Dublin", None)
    assert db.get_meta(conn, pipeline.DISCOVERED_AT) is None
    fresh = db.connect(ctx.root / "fresh.db")
    db.init(fresh)
    for table in ("routes", "meta", "price_observations", "deals", "fetch_runs", "photos"):
        assert _columns(conn, table) == _columns(fresh, table), table


def test_upgrade_from_v5_reaches_v8(ctx):
    v5_database(ctx.db_path).close()
    conn = pipeline.open_db(ctx)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 8
    assert "city_en" in _columns(conn, "routes")
    db.set_meta(conn, "k", "v")
    db.set_meta(conn, "k", "w")
    assert db.get_meta(conn, "k") == "w"


# --- collection budget -------------------------------------------------------------------

def test_rate_limiter_waits_only_when_the_minute_is_full():
    clock, slept = [0.0], []

    def sleep(s):
        slept.append(s)
        clock[0] += s

    limiter = RateLimiter(3, clock=lambda: clock[0], sleep=sleep)
    for t in (0.0, 1.0, 2.0):
        clock[0] = t
        limiter.wait()
    assert slept == []
    clock[0] = 10.0
    limiter.wait()                       # 4th call within the minute: waits until t=60
    assert slept == [50.0]
    clock[0] = 61.5
    limiter.wait()                       # the t=1 call has left the window: room for one more
    assert slept == [50.0]
    limiter.wait()                       # full again (t=2, 60, 61.5): waits for t=2 to expire
    assert slept == [50.0, 0.5]


def test_config_long_haul_list_is_curated_for_lisbon_and_porto():
    cfg = AppConfig.model_validate(yaml.safe_load((REPO / "config.yaml").read_text("utf-8")))
    dests = [d.destination for d in cfg.routes.long_haul]
    assert 15 <= len(dests) <= 25 and len(set(dests)) == len(dests)
    assert all(d.origins == ["LIS", "OPO"] and d.city_pt for d in cfg.routes.long_haul)
    assert cfg.routes.origins == ORIGINS
    assert cfg.routes.kinds["long_haul"].max_transfers == 1
