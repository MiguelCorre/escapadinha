"""Route demand from Eurostat `avia_par_pt` (D45): the JSON-stat parser on a saved real answer,
the ICAO -> IATA -> city mapping, the twelve-month window, the ranking, the Eurostat client, the
discovery that fetches and stores it (failure reported, never fatal), the day's pass narrowed to
the busiest routes, the schema upgrade and the site export. A passenger count is never a price.
"""

import gzip
import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from escapadinha import cli, demand, i18n_pt, pipeline, routes, site_data
from escapadinha.collector import eurostat
from escapadinha.collector import plan as collector_plan
from escapadinha.models import Route, RouteRules
from escapadinha.storage import db
from escapadinha.storage.objects import LocalObjectStore
from test_daily_pass import api, configure, utc
from test_discovery import T0, dctx, mock_catalogue, mock_pixabay  # noqa: F401 (fixture)
from test_pipeline import ctx  # noqa: F401 (fixture)
from test_site_data import read, validation_errors

FIXTURES = Path(__file__).parent / "fixtures"
# The real answer to the request `collector/eurostat.py` makes, saved on 2026-10-19 (36 months
# asked: 2023-10 on; the dataset's monthly series ended at 2024-12 that day).
SAMPLE = json.loads((FIXTURES / "eurostat_avia_par_pt.json").read_text("utf-8"))
AIRPORTS = json.loads((FIXTURES / "discovery" / "airports.json").read_text("utf-8"))
MONTHS_2024 = [f"2024-{m:02d}" for m in range(1, 13)]


def route(key: str, pax: float | None = None, seen: bool = True) -> Route:
    origin, destination = key.split("-")
    return Route(origin=origin, destination=destination, city_pt=destination, kind="europe",
                 rules=RouteRules(), last_observed_at=utc(10, 1, 0) if seen else None,
                 demand_pax_month=pax, demand_period=None if pax is None else "2024-12")


# --- parsing -------------------------------------------------------------------------------

def test_parse_reads_every_cell_by_its_flattened_position_and_skips_the_missing_ones():
    cells = demand.parse_jsonstat(SAMPLE)
    assert len(cells) == len(SAMPLE["value"]) == 4051           # one cell per value, no more
    assert cells[("LPPT", "LEMD", "2024-12")] == 141591          # Lisbon-Madrid, as the research read it
    assert cells[("LPPR", "LFPO", "2024-12")] == 94280           # Porto-Orly
    assert demand.months_available(cells) == [f"2023-{m}" for m in ("10", "11", "12")] + MONTHS_2024
    # A pair that is only reported for part of the period has no cell for the other months.
    assert ("LPFR", "LEBL", "2023-12") in cells and ("LPFR", "LEBL", "2024-01") not in cells
    assert all(isinstance(v, int) and v >= 0 for v in cells.values())
    # Nothing in the dataset is a price: it carries passengers only.
    assert SAMPLE["dimension"]["unit"]["category"]["index"] == {"PAS": 0}


def test_parse_follows_the_dimension_order_and_accepts_a_value_list_with_nulls():
    doc = {"id": ["time", "airp_pr"], "size": [2, 2],
           "dimension": {"time": {"category": {"index": ["2024-11", "2024-12"]}},
                         "airp_pr": {"category": {"index": {"PT_LPPT_ES_LEMD": 0, "PT_LPPR_FR_LFPO": 1}}}},
           "value": [10, None, 30, 40.0]}
    assert demand.parse_jsonstat(doc) == {("LPPT", "LEMD", "2024-11"): 10,
                                          ("LPPT", "LEMD", "2024-12"): 30,
                                          ("LPPR", "LFPO", "2024-12"): 40}


def test_parse_refuses_what_is_not_the_dataset():
    with pytest.raises(demand.DemandError):
        demand.parse_jsonstat({"hello": 1})
    bad = {"id": ["airp_pr", "time"], "size": [1, 1],
           "dimension": {"airp_pr": {"category": {"index": {"LPPT-LEMD": 0}}},
                         "time": {"category": {"index": {"2024-12": 0}}}},
           "value": {"0": 1}}
    with pytest.raises(demand.DemandError, match="airport pair"):
        demand.parse_jsonstat(bad)


# --- routes ----------------------------------------------------------------------------------

def test_partner_airports_sum_into_our_city_and_a_month_without_a_value_counts_zero():
    cells = {("LPPT", "LFPO", "2024-11"): 100, ("LPPT", "LFPG", "2024-11"): 50,
             ("LPPT", "LFOB", "2024-12"): 30, ("LPPT", "LEMD", "2024-12"): 7,
             ("LPPT", "XXXX", "2024-12"): 999,            # an ICAO code we don't map: ignored
             ("LPPR", "LFPO", "2024-10"): 1}
    airports = [{"code": "ORY", "city_code": "PAR"}, {"code": "CDG", "city_code": "PAR"},
                {"code": "BVA", "city_code": "PAR"}, {"code": "MAD", "city_code": "MAD"}]
    out = demand.route_demand(cells, airports, [("LIS", "PAR"), ("LIS", "MAD"), ("OPO", "PAR"),
                                                ("LIS", "LON")], window=3)
    paris = out["LIS-PAR"]
    assert paris.months == (("2024-10", 0), ("2024-11", 150), ("2024-12", 30))
    assert paris.pax_month == 60 and paris.period == "2024-12"
    assert paris.seasonal and paris.zero_months == ("2024-10",)
    assert paris.to_json() == {"pax_month": 60, "period": "2024-12", "months": [
        {"month": "2024-10", "pax": 0}, {"month": "2024-11", "pax": 150}, {"month": "2024-12", "pax": 30}]}
    assert out["LIS-MAD"].pax_month == pytest.approx(7 / 3)
    assert out["OPO-PAR"].months == (("2024-10", 1), ("2024-11", 0), ("2024-12", 0))
    assert "LIS-LON" not in out                             # no series: no figure (null stays null)
    assert demand.route_demand({}, airports, [("LIS", "PAR")]) == {}


def test_the_window_is_the_datasets_last_twelve_months():
    """On the real sample (15 months) every route gets 2024 only; London sums its airports."""
    cells = demand.parse_jsonstat(SAMPLE)
    out = demand.route_demand(cells, AIRPORTS, [("LIS", "MAD"), ("LIS", "LON"), ("LIS", "TYO")])
    madrid = out["LIS-MAD"]
    assert [m for m, _ in madrid.months] == MONTHS_2024 and madrid.period == "2024-12"
    assert madrid.pax_month == pytest.approx(sum(cells[("LPPT", "LEMD", m)] for m in MONTHS_2024) / 12)
    assert not madrid.seasonal
    london = out["LIS-LON"]
    heathrow_december = cells[("LPPT", "EGLL", "2024-12")]
    assert dict(london.months)["2024-12"] > heathrow_december        # Gatwick, Luton, Stansted too
    assert "LIS-TYO" not in out                                      # no Tokyo pair in the dataset


def test_rank_routes_orders_by_passengers_with_ties_by_key_and_leaves_out_routes_without():
    ranked = demand.rank_routes([route("LIS-AMS", 10), route("OPO-BCN", 30), route("LIS-TYO"),
                                 route("LIS-BCN", 30)])
    assert ranked == {"LIS-BCN": 1, "OPO-BCN": 2, "LIS-AMS": 3}
    assert demand.rank_routes([route("LIS-TYO")]) == {}


def test_passenger_counts_print_with_the_pt_thousands_separator_and_no_currency():
    assert i18n_pt.integer(141591) == "141 591"
    assert i18n_pt.integer(0) == "0" and i18n_pt.integer(999) == "999"
    assert "€" not in i18n_pt.integer(1_234_567)


# --- the Eurostat client ---------------------------------------------------------------------

def test_since_month_counts_whole_months_back():
    assert eurostat.since_month(date(2026, 10, 19), 36) == "2023-10"
    assert eurostat.since_month(date(2026, 1, 5), 24) == "2024-01"
    assert eurostat.since_month(date(2026, 3, 1), 3) == "2025-12"


@respx.mock
def test_the_client_asks_for_monthly_passengers_carried_and_refuses_other_answers():
    mock = respx.get(eurostat.URL).mock(return_value=httpx.Response(200, json=SAMPLE))
    client = eurostat.EurostatClient()
    assert client.passengers("2023-10")["value"] == SAMPLE["value"]
    params = mock.calls.last.request.url.params
    assert dict(params) == {"format": "JSON", "lang": "EN", "unit": "PAS", "tra_meas": "PAS_CRD",
                            "freq": "M", "sinceTimePeriod": "2023-10"}
    for response in (httpx.Response(503, text="maintenance"), httpx.Response(200, json={"error": 1}),
                     httpx.Response(200, text="<html>")):
        mock.return_value = response
        with pytest.raises(eurostat.EurostatError):
            client.passengers("2023-10")


def test_the_answer_is_archived_as_it_came(tmp_path):
    store = LocalObjectStore(tmp_path)
    key = eurostat.archive_key(datetime(2026, 10, 19, 6, 5, 9, tzinfo=timezone.utc))
    assert key == "archive/eurostat/avia_par_pt-2026-10-19T060509Z.json.gz"
    eurostat.archive(store, key, SAMPLE)
    assert json.loads(gzip.decompress(store.get(key))) == SAMPLE
    assert eurostat.read_archive(store, key)["value"] == SAMPLE["value"]


# --- with the discovery (pipeline seam) -------------------------------------------------------

@respx.mock
def test_discovery_stores_every_routes_demand_and_archives_the_dataset(dctx):  # noqa: F811
    conn = pipeline.open_db(dctx)
    mock_catalogue()
    mock_pixabay()
    result = pipeline.run_discover(dctx, conn, T0, photos=False)
    assert result.errors == []
    update = result.demand
    assert update.period == "2024-12" and update.routes == len(routes.all_routes(conn, dctx.config.routes))
    assert 0 < update.with_figure < update.routes
    assert update.top[0][0] == "LIS-LON" and len(update.top) == pipeline.TOP_DEMAND
    stored = {r.key: r for r in routes.all_routes(conn, dctx.config.routes)}
    london = stored["LIS-LON"]
    assert london.demand_period == "2024-12" and london.demand_pax_month > 100_000
    assert stored["LIS-TYO"].demand_pax_month is None and stored["LIS-TYO"].demand_period is None
    months = db.route_demand_months(conn)
    assert [m for m, _ in months["LIS-LON"]] == MONTHS_2024 and "LIS-TYO" not in months
    # The answer is kept as it came, under its own prefix (not a collection run's archive).
    keys = dctx.object_store.list("archive/eurostat/")
    assert keys == [update.archive_key] and update.archive_key.startswith("archive/eurostat/avia_par_pt-2026-10-13")
    assert eurostat.read_archive(dctx.object_store, update.archive_key)["value"] == SAMPLE["value"]


@respx.mock
def test_a_dry_run_reports_demand_but_stores_nothing(dctx):  # noqa: F811
    conn = pipeline.open_db(dctx)
    mock_catalogue()
    result = pipeline.run_discover(dctx, conn, T0, dry_run=True)
    assert result.demand is not None and result.demand.with_figure > 0
    assert all(r.demand_pax_month is None for r in routes.all_routes(conn, dctx.config.routes))
    assert db.route_demand_months(conn) == {}


@respx.mock
def test_a_failed_eurostat_fetch_is_reported_and_keeps_the_previous_figures(dctx):  # noqa: F811
    conn = pipeline.open_db(dctx)
    mock_catalogue()
    mock_pixabay()
    pipeline.run_discover(dctx, conn, T0, photos=False)
    before = pipeline.route_for(dctx, conn, "LIS-LON").demand_pax_month
    mock_catalogue(eurostat_status=503)
    result = pipeline.run_discover(dctx, conn, T0, photos=False)
    assert result.demand is None
    assert result.errors == [f"route demand (Eurostat avia_par_pt): {eurostat.URL}: HTTP 503: unavailable"]
    assert pipeline.last_discovery(conn) == T0                      # the discovery itself went on
    assert pipeline.route_for(dctx, conn, "LIS-LON").demand_pax_month == before


@respx.mock
def test_a_pair_the_dataset_no_longer_has_loses_its_figure(dctx):  # noqa: F811
    conn = pipeline.open_db(dctx)
    mock_catalogue()
    pipeline.run_discover(dctx, conn, T0, photos=False)
    trimmed = {**SAMPLE, "value": {k: v for k, v in SAMPLE["value"].items()
                                   if not _is_lisbon_london(int(k))}}
    respx.get(eurostat.URL).mock(return_value=httpx.Response(200, json=trimmed))
    pipeline.run_discover(dctx, conn, T0, photos=False)
    assert pipeline.route_for(dctx, conn, "LIS-LON").demand_pax_month is None
    assert pipeline.route_for(dctx, conn, "LIS-PAR").demand_pax_month is not None
    assert "LIS-LON" not in db.route_demand_months(conn)


def _is_lisbon_london(position: int) -> bool:
    pairs = SAMPLE["dimension"]["airp_pr"]["category"]["index"]
    n_months = SAMPLE["size"][-1]
    code = next(c for c, i in pairs.items() if i == position // n_months)
    return code.startswith("PT_LPPT_UK_EG")


@respx.mock
def test_routes_discover_prints_the_demand_summary(dctx, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ESCAPADINHA_HOME", str(dctx.root))
    monkeypatch.setenv("COLUMNS", "300")
    mock_catalogue()
    out = CliRunner().invoke(cli.app, ["routes", "discover", "--no-photos"]).output
    line = next(l for l in out.splitlines() if "Procura (Eurostat avia_par_pt" in l)
    assert "dados até 2024-12" in line and "mais procuradas: LIS-LON " in line
    assert "€" not in line


# --- the day's pass narrowed to the busiest routes (D42 + D45) ----------------------------------

def test_the_daily_pass_asks_the_far_months_only_of_the_busiest_routes():
    fleet = [route("LIS-AMS", 100), route("LIS-BCN", 50), route("LIS-TYO"), route("OPO-PAR", 70),
             route("OPO-LON", 10)]
    daily = collector_plan.plan(fleet, today=date(2026, 10, 16), daily=True, months_ahead=3,
                                daily_months_ahead=6, deep_routes=2)
    assert daily.deep == {"LIS-AMS", "OPO-PAR"}
    assert daily.months == tuple(date(2026, m, 1) for m in (10, 11, 12))
    assert daily.far_months == (date(2027, 1, 1), date(2027, 2, 1), date(2027, 3, 1))
    assert len(daily.tasks) == 2 * 6 + 3 * 3
    assert [m for r, m in daily.tasks if r.key == "OPO-LON"] == list(daily.months)
    assert daily.describe() == "daily pass: months 1–6 of 2 routes, months 1–3 of 3 routes"
    # An open promotion in a far month is still asked on a route outside the deep set.
    with_deal = collector_plan.plan(fleet, today=date(2026, 10, 16), daily=True, months_ahead=3,
                                    daily_months_ahead=6, deep_routes=2,
                                    deal_months=[("OPO-LON", date(2027, 2, 1)), ("LIS-AMS", date(2027, 2, 1))])
    assert len(with_deal.tasks) == 2 * 6 + 3 * 3 + 1 and with_deal.n_far_deal_months == 1
    assert with_deal.describe().endswith("+ 1 far month of open promotions")
    # Without any demand figure, or without a limit, every route gets the far months (D42).
    for fleet_, limit in (([route("LIS-AMS"), route("OPO-PAR")], 1), (fleet, None)):
        wide = collector_plan.plan(fleet_, today=date(2026, 10, 16), daily=True, months_ahead=3,
                                   daily_months_ahead=6, deep_routes=limit)
        assert not wide.deep and len(wide.tasks) == 6 * len(fleet_)
        assert wide.describe() == f"daily pass: months 1–6 of {len(fleet_)} routes"
    # A regular run never narrows: it asks the near months of every seen route, as before.
    regular = collector_plan.plan(fleet, today=date(2026, 10, 16), daily=False, months_ahead=3,
                                  daily_months_ahead=6, deep_routes=2)
    assert not regular.deep and len(regular.tasks) == 5 * 3
    assert regular.describe() == "regular pass: months 1–3 of 5 routes"


@respx.mock
def test_run_collect_narrows_the_daily_pass_by_demand_rank(ctx):  # noqa: F811
    """Through the pipeline seam: `collector.deep_routes` and the stored figures decide the
    request count of the day's pass; without figures the pass asks every route (test_daily_pass)."""
    ctx = configure(ctx, months_ahead=3, daily_months_ahead=6, daily_pass_hour=6, deep_routes=3)
    conn = pipeline.open_db(ctx)
    figures = {key: demand.Demand(pax, "2024-12", tuple((m, int(pax)) for m in MONTHS_2024))
               for key, pax in (("LIS-LON", 200_000.0), ("LIS-PAR", 190_000.0),
                                ("OPO-PAR", 140_000.0), ("LIS-AMS", 80_000.0))}
    db.set_route_demand(conn, figures)
    api()
    summary = pipeline.run_collect(ctx, conn, now=utc(10, 15, 3))
    assert summary.plan.daily and summary.plan.deep == {"LIS-LON", "LIS-PAR", "OPO-PAR"}
    assert summary.n_requests == 3 * 6 + 7 * 3
    assert summary.plan.describe() == "daily pass: months 1–6 of 3 routes, months 1–3 of 7 routes"
    regular = pipeline.run_collect(ctx, conn, now=utc(10, 15, 7))
    assert regular.n_requests == 10 * 3


# --- schema v16 ----------------------------------------------------------------------------

def test_upgrade_from_a_v15_database_adds_the_demand_columns_and_keeps_the_routes(ctx):  # noqa: F811
    conn = pipeline.open_db(ctx)                      # a fresh v16 database with the seeded routes
    n_routes = len(routes.all_routes(conn, ctx.config.routes))
    conn.execute("DROP TABLE route_demand")
    conn.execute("ALTER TABLE routes DROP COLUMN demand_pax_month")
    conn.execute("ALTER TABLE routes DROP COLUMN demand_period")
    conn.execute("PRAGMA user_version = 15")
    conn.commit()
    conn.close()

    conn = pipeline.open_db(ctx)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 16
    columns = {r[1] for r in conn.execute("PRAGMA table_info(routes)")}
    assert {"demand_pax_month", "demand_period"} <= columns
    fresh = db.connect(ctx.root / "fresh.db")
    db.init(fresh)
    assert columns == {r[1] for r in fresh.execute("PRAGMA table_info(routes)")}
    assert ({r[1] for r in conn.execute("PRAGMA table_info(route_demand)")}
            == {r[1] for r in fresh.execute("PRAGMA table_info(route_demand)")} == {"origin", "destination", "month", "pax"})
    kept = routes.all_routes(conn, ctx.config.routes)
    assert len(kept) == n_routes and all(r.demand_pax_month is None for r in kept)
    db.set_route_demand(conn, {"LIS-LON": demand.Demand(5.0, "2024-12", (("2024-12", 5),))})
    assert db.route_demand_months(conn) == {"LIS-LON": [("2024-12", 5)]}
    with pytest.raises(sqlite3.IntegrityError):              # months belong to a stored route
        conn.execute("INSERT INTO route_demand VALUES ('XXX', 'YYY', '2024-12', 1)")


# --- the site contract -------------------------------------------------------------------------

def test_the_export_carries_each_routes_demand_and_the_thin_threshold(ctx, tmp_path):  # noqa: F811
    conn = pipeline.open_db(ctx)
    months = tuple((m, 0 if m == "2024-02" else 12_000) for m in MONTHS_2024)
    db.set_route_demand(conn, {"LIS-LON": demand.Demand(11_000.0, "2024-12", months)})
    out = tmp_path / "site-data"
    site_data.export_site_data(ctx, conn, out, new_links=False)
    assert validation_errors(out) == []
    by_key = {r["key"]: r for r in read(out, "routes.json")["routes"]}
    assert by_key["LIS-LON"]["demand"] == {
        "pax_month": 11_000, "period": "2024-12",
        "months": [{"month": m, "pax": pax} for m, pax in months]}
    assert by_key["LIS-PAR"]["demand"] is None
    assert read(out, "meta.json")["demand"] == {"thin_pax_month": ctx.config.demand.thin_pax_month == 5000 and 5000}
    # The committed fixtures were hand-edited to the value a regeneration writes (D45).
    fixtures = Path(__file__).resolve().parents[1] / "contract" / "site" / "v1" / "fixtures"
    assert all("demand" in r and r["demand"] is None
               for r in json.loads((fixtures / "routes.json").read_text("utf-8"))["routes"])
    assert json.loads((fixtures / "meta.json").read_text("utf-8"))["demand"] == {"thin_pax_month": 5000}
