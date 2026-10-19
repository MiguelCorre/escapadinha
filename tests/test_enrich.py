"""GraphQL enrichment in the pipeline (D43): after collection and detection, the run's low
prices and promotion candidates get baggage, agency and exact found time from the GraphQL rows
matched to them, nothing else changes, and an offer without a match keeps its fields unknown.
GraphQL mocked with respx, never a real call."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from escapadinha import archive, cli, pipeline, site_data
from escapadinha.collector.graphql import API_URL as GRAPHQL_URL
from escapadinha.collector.graphql import GraphQLClient
from escapadinha.config import Context
from escapadinha.storage import db
from test_pipeline import FIXTURE, ctx, mock_api, mock_links, seed_history  # noqa: F401

FOUND_AT = datetime(2026, 10, 12, 7, 20, tzinfo=timezone.utc)
# The fixture's 58 € easyJet trip (6–9 Nov, LGW): its REST link's `t=` token.
TOKEN = "U217624098001762410900000155LISLGW_test"


def gql_row(**over) -> dict:
    base = {
        "departure_at": "2026-11-06T06:15:00Z", "return_at": "2026-11-09T23:40:00Z",
        "origin_airport_iata": "LIS", "destination_airport_iata": "LGW", "value": 57.6,
        "currency": "eur", "number_of_changes": 0, "main_airline": "U2",
        "found_at": int(FOUND_AT.timestamp()), "with_baggage": False, "baggage_code": "0PC",
        "gate": "Kiwi.com", "ticket_link": f"/LIS0611LON09111?t={TOKEN}&search_date=12102026",
    }
    return base | over


def mock_graphql(rows=None, *, responses=None):
    """The GraphQL API: `rows` for the 6–9 Nov LIS-LON trip, nothing for any other query."""
    def respond(request):
        params = json.loads(request.content)["variables"]["params"]
        asked = (params["origin"], params["destination"], params["depart_date_max"],
                 params["return_date_min"])
        hit = asked == ("LIS", "LON", "2026-11-06", "2026-11-08")
        return httpx.Response(200, json={"data": {"prices_round_trip": list(rows or []) if hit else []}})
    return respx.post(GRAPHQL_URL).mock(side_effect=responses or respond)


def collected(ctx):
    """A collection with the fixture's prices and its detection: one LIS-LON deal (58 €),
    which is the route's one low price too."""
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    mock_api()
    pipeline.run_collect(ctx, conn)
    _, results = pipeline.run_detect(ctx, conn)
    [deal_id] = {r.route: r for r in results}["LIS-LON"].deal_ids
    return conn, deal_id


def prices(conn) -> list[tuple]:
    return conn.execute("SELECT id, price, airline, dedup_key FROM price_observations ORDER BY id").fetchall()


@respx.mock
def test_a_matched_row_fills_the_candidates_fields_and_touches_nothing_else(ctx):
    conn, deal_id = collected(ctx)
    before = prices(conn)
    mock_graphql([gql_row()])
    collection = db.latest_completed_run_id(conn)

    summary = pipeline.run_enrich(ctx, conn)
    assert (summary.offers, summary.queried, summary.matched, summary.skipped, summary.errors) \
        == (1, 1, 1, 0, [])
    deal, obs = db.get_deal(conn, deal_id)
    assert obs.price == 58 and obs.airline == "U2"                          # never changed
    assert (obs.with_baggage, obs.baggage_code, obs.gate) == (False, "0PC", "Kiwi.com")
    assert obs.found_at == FOUND_AT
    others = [db.get_observation(conn, r[0]) for r in before if r[0] != obs.id]
    assert all((o.with_baggage, o.baggage_code, o.gate, o.found_at) == (None,) * 4 for o in others)
    assert prices(conn) == before                                           # no price moved
    # Archived under its own run (D18), the collection run still the latest completed one.
    assert db.latest_completed_run_id(conn) == collection
    run = conn.execute("SELECT * FROM fetch_runs WHERE id = ?", (summary.run_id,)).fetchone()
    assert (run["source"], run["scope"], run["status"], run["n_requests"]) \
        == ("travelpayouts-graphql", "enrich", "ok", 1)
    stored = archive.read(ctx.object_store, db.run_archive_key(conn, summary.run_id))
    [response] = stored["responses"]
    assert response["payload"]["data"]["prices_round_trip"] == [gql_row()]
    assert response["variables"]["params"]["direct"] is True
    assert "test-token" not in json.dumps(stored)


@respx.mock
def test_captions_and_the_site_print_the_baggage_line_only_when_known(ctx):
    conn, deal_id = collected(ctx)
    deal, obs = db.get_deal(conn, deal_id)
    unknown = pipeline.deal_caption_text(ctx, pipeline.text_view(ctx, conn, deal, obs))
    assert "bagagem" not in unknown.lower() and "mala" not in unknown.lower()
    mock_graphql([gql_row()])
    pipeline.run_enrich(ctx, conn)
    deal, obs = db.get_deal(conn, deal_id)
    text = pipeline.deal_caption_text(ctx, pipeline.text_view(ctx, conn, deal, obs))
    assert "🛬 Chegada: aeroporto Gatwick (LGW)\n🧳 Só bagagem de mão\n" in text
    assert "Kiwi.com" not in text                      # the agency is for the reviewer only
    export = site_data.build_export(ctx, conn, new_links=False)
    rows = {r[0]: dict(zip(site_data.LOW_COLS, r))
            for r in export.files["low-prices/LIS.json"]["rows"]}
    assert rows[obs.id]["baggage"] is False
    assert all(r["baggage"] is None for i, r in rows.items() if i != obs.id)
    lon = next(r for r in export.files["routes.json"]["routes"] if r["key"] == "LIS-LON")
    assert lon["cheapest"]["obs"] == obs.id and lon["cheapest"]["baggage"] is False


@respx.mock
def test_no_matching_row_leaves_the_fields_unknown_and_asks_again_next_run(ctx):
    conn, deal_id = collected(ctx)
    mock_graphql([gql_row(ticket_link="/LIS0611LON09111?t=other", value=57.6, main_airline="FR"),
                  gql_row(ticket_link="/LIS0611LON09111?t=other2", value=70)])
    first = pipeline.run_enrich(ctx, conn)
    assert (first.queried, first.matched, first.errors) == (1, 0, [])
    _, obs = db.get_deal(conn, deal_id)
    assert (obs.with_baggage, obs.baggage_code, obs.gate, obs.found_at) == (None,) * 4
    again = pipeline.run_enrich(ctx, conn)
    assert again.queried == 1                                   # still unknown: asked again


@respx.mock
def test_a_matched_offer_is_not_asked_about_again(ctx):
    conn, _ = collected(ctx)
    route = mock_graphql([gql_row()])
    assert pipeline.run_enrich(ctx, conn).matched == 1
    summary = pipeline.run_enrich(ctx, conn)
    assert (summary.run_id, summary.offers, summary.queried) == (None, 0, 0)
    assert route.call_count == 1


@respx.mock
def test_a_rate_limited_api_waits_and_never_fails_the_run(ctx, monkeypatch):
    conn, deal_id = collected(ctx)
    mock_graphql(responses=[httpx.Response(429, headers={"X-Rate-Limit-Reset": "7"}),
                            httpx.Response(200, json={"data": {"prices_round_trip": [gql_row()]}})])
    sleeps = []
    monkeypatch.setattr(pipeline, "graphql_client",
                        lambda c: GraphQLClient("tok", currency="eur", sleep=sleeps.append))
    summary = pipeline.run_enrich(ctx, conn)
    assert (summary.matched, summary.errors, sleeps) == (1, [], [7.0])
    assert db.get_deal(conn, deal_id)[1].gate == "Kiwi.com"


@respx.mock
def test_a_failing_query_is_reported_and_the_run_goes_on(ctx, monkeypatch):
    conn, deal_id = collected(ctx)
    mock_graphql(responses=lambda r: httpx.Response(500))
    monkeypatch.setattr(pipeline, "graphql_client",
                        lambda c: GraphQLClient("tok", currency="eur", sleep=lambda s: None))
    summary = pipeline.run_enrich(ctx, conn)                    # no exception
    assert summary.matched == 0 and len(summary.errors) == 1 and "500" in summary.errors[0]
    assert conn.execute("SELECT status FROM fetch_runs WHERE id = ?",
                        (summary.run_id,)).fetchone()[0] == "failed"
    assert db.get_deal(conn, deal_id)[1].with_baggage is None


@respx.mock
def test_the_budget_caps_queries_per_run_one_per_trip(ctx, monkeypatch):
    conn, _ = collected(ctx)
    monkeypatch.setattr(ctx.config.collector, "enrich_per_run", 1)
    offers = db.observations_seen_since(conn, db.latest_completed_run_id(conn))
    trips = {(o.departure_date, o.return_date) for o in offers}
    assert len(trips) == 2 and len(offers) == 2                      # the fixture's two trips
    offers = offers + offers                                          # the same trip twice: one query
    route = mock_graphql()
    summary = pipeline.enrich_offers(ctx, conn, offers)
    assert summary.queried == route.call_count == 1 and summary.skipped == 2
    monkeypatch.setattr(ctx.config.collector, "enrich_per_run", 0)
    assert pipeline.enrich_offers(ctx, conn, offers).run_id is None
    assert route.call_count == 1


@respx.mock
def test_without_the_token_enrichment_is_skipped_with_the_reason(ctx, monkeypatch):
    conn, _ = collected(ctx)
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "")
    summary = pipeline.run_enrich(Context(root=ctx.root), conn)
    assert summary.run_id is None and summary.queried == 0
    assert any("TRAVELPAYOUTS_TOKEN" in e for e in summary.errors)


@respx.mock
def test_the_enrich_command_and_the_run_report_what_was_matched(ctx, monkeypatch):
    conn, _ = collected(ctx)
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    mock_graphql([gql_row()])
    result = CliRunner().invoke(cli.app, ["enrich"])
    assert result.exit_code == 0, result.output
    assert "Enrichment: 1 GraphQL requests, 1 of 1 offers matched" in result.output
    report: list[str] = []
    db.set_meta(conn, pipeline.DISCOVERED_AT, db.utcnow().isoformat())   # no discovery this run
    from types import SimpleNamespace
    monkeypatch.setattr(cli, "_collect", lambda: SimpleNamespace(
        status="ok", n_requests=0, n_observations=0, n_new=0, errors=[],
        plan=SimpleNamespace(describe=lambda: "routine")))
    monkeypatch.setattr(cli, "publish_due", lambda: None)
    monkeypatch.setattr(cli.run_path, "decide", lambda c, k, force=False: cli.run_path.PathDecision(False, "x"))
    cli._pipeline_steps(render=False, full=False, report=report)
    assert "Enrichment: nothing to ask (no new low prices or candidates)" in report


# --- schema v14 -------------------------------------------------------------------------------

def _observation_columns(conn) -> list[tuple]:
    return [tuple(r)[1:] for r in conn.execute("PRAGMA table_info(price_observations)")]


@pytest.mark.parametrize("fixture, version", [("schema_v5.sql", 5), ("schema_v7.sql", 7)])
def test_upgrade_from_real_old_schemas_adds_the_enrichment_columns(ctx, fixture, version):
    ctx.db_path.parent.mkdir(parents=True, exist_ok=True)
    old = sqlite3.connect(ctx.db_path)
    old.executescript((Path(__file__).parent / "fixtures" / fixture).read_text("utf-8"))
    old.execute(f"PRAGMA user_version = {version}")
    old.commit()
    old.close()
    conn = pipeline.open_db(ctx)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 16
    fresh = db.connect(ctx.root / "fresh.db")
    db.init(fresh)
    assert _observation_columns(conn) == _observation_columns(fresh)
    assert [c[0] for c in _observation_columns(conn)][-4:] == ["with_baggage", "baggage_code",
                                                               "gate", "found_at"]


def test_upgrade_from_v13_keeps_observations_with_unknown_baggage(ctx):
    """The real database is v13 (D40): its offers survive migration 14 with the four fields null."""
    ctx.db_path.parent.mkdir(parents=True, exist_ok=True)
    old = sqlite3.connect(ctx.db_path)
    old.executescript((Path(__file__).parent / "fixtures" / "schema_v7.sql").read_text("utf-8"))
    old.execute("PRAGMA user_version = 7")
    old.commit()
    old.close()
    conn = db.connect(ctx.db_path)
    for version in (8, 9, 10, 11, 12, 13):              # what a v13 database went through
        for step in db.MIGRATIONS[version]:
            conn.execute(step)
    conn.execute("PRAGMA user_version = 13")
    conn.execute("INSERT INTO fetch_runs (id, source, started_at, status) VALUES (3, 'travelpayouts', 'x', 'ok')")
    conn.execute("""INSERT INTO price_observations (id, run_id, last_run_id, source, origin, destination,
                    departure_date, return_date, nights, price, currency, airline, fetched_at,
                    last_seen_at, dedup_key) VALUES (9, 3, 3, 'travelpayouts', 'LIS', 'LON',
                    '2026-11-06', '2026-11-09', 3, 58, 'EUR', 'U2', '2026-10-12T09:00:00+00:00',
                    '2026-10-12T09:00:00+00:00', 'k')""")
    conn.commit()
    db.init(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    obs = db.get_observation(conn, 9)
    assert obs.price == 58 and (obs.with_baggage, obs.baggage_code, obs.gate, obs.found_at) == (None,) * 4
    db.set_enrichment(conn, 9, with_baggage=True, baggage_code="1PC20", gate="Trip.com",
                      found_at=FOUND_AT)
    obs = db.get_observation(conn, 9)
    assert (obs.with_baggage, obs.baggage_code, obs.gate, obs.found_at) == (True, "1PC20", "Trip.com", FOUND_AT)
    assert obs.price == 58
