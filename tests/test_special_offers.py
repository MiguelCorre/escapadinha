"""Aviasales' special offers as the reviewer's second opinion (D46): the GraphQL query and its
parsing, the pure match of a deal's trip to their list, the run step that stores their discount
(a percentage, never a price) on open deals and archives the answers, the snapshot and the local
review page showing it next to the exact found time. HTTP mocked with respx, never a real call."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import httpx
import respx
from fastapi.testclient import TestClient

from escapadinha import archive, i18n_pt, pipeline, review_snapshot
from escapadinha.collector import graphql
from escapadinha.collector.graphql import API_URL as GRAPHQL_URL
from escapadinha.models import Observation
from escapadinha.storage import db
from escapadinha.web import create_app
from test_pipeline import ctx  # noqa: F401
from test_review import rendered_deal
from test_review_events import validate

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
SEEN = int(NOW.timestamp()) - 3600                     # found an hour before NOW


def special_row(**over) -> dict:
    """A row of `special_offers_round_trip` as the API answered on 2026-10-24 (LIS-FNC)."""
    base = {
        "departure_at": "2026-11-16T06:10:00Z", "return_at": "2026-11-21T22:30:00Z",
        "origin_airport_iata": "LIS", "destination_airport_iata": "FNC",
        "destination_city_iata": "FNC", "value": 53.04, "currency": "eur",
        "number_of_changes": 0, "main_airline": "FR", "found_at": SEEN, "with_baggage": False,
        "baggage_code": "0PC", "gate": "Kiwi.com",
        "ticket_link": "/LIS1611FNC21111?t=FR_test&search_date=23102026",
        "discount": 59.303165435791016,
    }
    return base | over


def fixture_row() -> dict:
    """The fixture's 58 € easyJet LIS-LGW trip (6–9 Nov) on the special-offers list."""
    return special_row(departure_at="2026-11-06T06:15:00Z", return_at="2026-11-09T23:40:00Z",
                       destination_airport_iata="LGW", destination_city_iata="LON", value=57.6,
                       main_airline="U2", ticket_link="/LIS0611LON09111?t=U2_test&search_date=23102026",
                       discount=48.2)


def obs(**over) -> Observation:
    base = dict(source="test", origin="LIS", destination="FNC", origin_airport="LIS",
                destination_airport="FNC", departure_date=date(2026, 11, 16),
                return_date=date(2026, 11, 21), price=53, currency="EUR", airline="FR",
                flight_number="1", transfers=0, return_transfers=0, deep_link=None,
                fetched_at=NOW, raw_json="{}")
    return Observation(**(base | over))


# --- query and parsing (pure) ---------------------------------------------------------------

def test_the_query_asks_one_origin_for_its_whole_list_with_the_discount():
    assert graphql.special_offers_variables("OPO", currency="EUR", market="pt", limit=50) == {
        "params": {"origin": "OPO"}, "paging": {"limit": 50, "offset": 0},
        "currency": "eur", "market": "pt"}
    assert "special_offers_round_trip(params: $params" in graphql.SPECIAL_OFFERS_QUERY
    assert graphql.SPECIAL_OFFERS_QUERY.rstrip().endswith("discount\n  }\n}")


def test_parse_reads_the_discount_and_city_and_keeps_the_prices_query_untouched():
    [o] = graphql.parse_response({"data": {"special_offers_round_trip": [special_row()]}},
                                 graphql.SPECIAL_OFFERS_FIELD)
    assert (o.value, o.discount, o.destination_city, o.airline) == (53.04, 59.303165435791016, "FNC", "FR")
    assert o.found_at == datetime.fromtimestamp(SEEN, timezone.utc)
    [plain] = graphql.parse_response({"data": {"prices_round_trip": [
        {k: v for k, v in special_row().items() if k not in ("discount", "destination_city_iata")}]}})
    assert (plain.discount, plain.destination_city) == (None, None)
    # Their discount is a number or nothing: a string, a boolean or NaN is unknown.
    for bad in ("59", True, float("nan")):
        [o] = graphql.parse_response({"data": {"special_offers_round_trip": [special_row(discount=bad)]}},
                                     graphql.SPECIAL_OFFERS_FIELD)
        assert o.discount is None


def test_a_deal_is_on_the_list_when_city_or_airport_dates_and_price_agree():
    offers = graphql.parse_response({"data": {"special_offers_round_trip": [
        special_row(), special_row(discount=20.0),                      # the same trip twice
        special_row(departure_at="2026-11-17T06:10:00Z"),               # another day
        special_row(value=70.0),                                        # another fare
        special_row(destination_airport_iata="PXO", destination_city_iata="PXO"),  # another city
    ]}}, graphql.SPECIAL_OFFERS_FIELD)
    hit = graphql.special_offer_for(obs(), offers)
    assert hit is not None and hit.discount == 59.303165435791016     # the largest of the two
    assert graphql.special_offer_for(obs(price=53.04), offers) is not None   # to the cent
    assert graphql.special_offer_for(obs(price=54), offers) is None          # 53.04 rounds to 53
    assert graphql.special_offer_for(obs(destination="PXO", destination_airport=None), offers) is not None
    assert graphql.special_offer_for(obs(return_date=date(2026, 11, 22)), offers) is None
    assert graphql.special_offer_for(obs(), []) is None


# --- the run step -----------------------------------------------------------------------------

def mock_special(rows_by_origin: dict[str, list[dict]]):
    def respond(request):
        body = json.loads(request.content)
        if "special_offers_round_trip" not in body["query"]:
            return httpx.Response(200, json={"data": {"prices_round_trip": []}})
        origin = body["variables"]["params"]["origin"]
        return httpx.Response(200, json={"data": {"special_offers_round_trip": rows_by_origin.get(origin, [])}})
    return respx.post(GRAPHQL_URL).mock(side_effect=respond)


@respx.mock
def test_an_open_deal_on_their_list_stores_their_discount_never_a_price(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    prices = conn.execute("SELECT id, price FROM price_observations ORDER BY id").fetchall()
    route = mock_special({"LIS": [fixture_row(), special_row()]})
    summary = pipeline.run_special_offers(ctx, conn, NOW)
    assert (summary.deals, summary.queried, summary.flagged, summary.errors) == (1, 1, 1, [])
    deal, _ = db.get_deal(conn, deal_id)
    assert (deal.partner_discount_pct, deal.partner_offer_at) == (48.2, NOW)
    assert deal.status == "rendered"                                  # a note for the reviewer only
    assert conn.execute("SELECT id, price FROM price_observations ORDER BY id").fetchall() == prices
    # One request per origin with an open deal (not per deal), its answer archived under its run.
    assert route.call_count == 1
    row = conn.execute("SELECT scope, source, status, n_requests, n_observations, n_new FROM fetch_runs "
                       "WHERE id = ?", (summary.run_id,)).fetchone()
    assert tuple(row) == ("special_offers", graphql.SOURCE, "ok", 1, 2, 1)
    [archived] = archive.read(ctx.object_store, db.run_archive_key(conn, summary.run_id))["responses"]
    assert archived["query"] == "special_offers_round_trip" and archived["origin"] == "LIS"
    assert "test-token" not in json.dumps(archived)

    # Off their list on the next run: the note goes (their current list, not a memory).
    mock_special({"LIS": [special_row()]})
    pipeline.run_special_offers(ctx, conn, NOW + timedelta(hours=1))
    deal, _ = db.get_deal(conn, deal_id)
    assert (deal.partner_discount_pct, deal.partner_offer_at) == (None, None)


@respx.mock
def test_a_failing_origin_is_reported_and_leaves_its_deals_as_they_were(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    db.set_partner_offer(conn, deal_id, 33.0, NOW - timedelta(hours=1))
    respx.post(GRAPHQL_URL).mock(return_value=httpx.Response(200, json={"errors": [{"message": "boom"}]}))
    summary = pipeline.run_special_offers(ctx, conn, NOW)
    assert summary.flagged == 0 and summary.errors == ["LIS: GraphQL error: boom"]
    deal, _ = db.get_deal(conn, deal_id)
    assert (deal.partner_discount_pct, deal.partner_offer_at) == (33.0, NOW - timedelta(hours=1))
    assert conn.execute("SELECT status FROM fetch_runs WHERE id = ?", (summary.run_id,)).fetchone()[0] == "failed"


def test_without_open_deals_or_a_token_nothing_is_asked(ctx, monkeypatch):
    conn = pipeline.open_db(ctx)
    assert pipeline.run_special_offers(ctx, conn, NOW) == pipeline.SpecialOffersSummary(None, 0, 0, 0, [])


# --- the snapshot and the review pages ------------------------------------------------------

@respx.mock
def test_the_snapshot_carries_the_exact_found_time_and_their_opinion(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    obs_id = db.get_deal(conn, deal_id)[1].id
    db.set_enrichment(conn, obs_id, with_baggage=False, baggage_code="0PC", gate="Kiwi.com",
                      found_at=NOW - timedelta(hours=1, minutes=5))
    db.set_partner_offer(conn, deal_id, 48.2, NOW)
    snap = review_snapshot.build(ctx, conn, NOW)
    validate("snapshot", snap)
    [d] = snap["queue"]
    assert d["found_at"] == "2026-10-24T10:55:00Z"
    assert d["partner_offer"] == {"discount_pct": 48.2, "seen_at": "2026-10-24T12:00:00Z"}
    db.set_partner_offer(conn, deal_id, None, None)
    [d] = review_snapshot.build(ctx, conn, NOW)["queue"]
    assert d["partner_offer"] is None


@respx.mock
def test_the_local_page_says_how_long_ago_and_what_aviasales_thinks(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    obs_id = db.get_deal(conn, deal_id)[1].id
    found = db.utcnow() - timedelta(hours=1, minutes=5)
    db.set_enrichment(conn, obs_id, with_baggage=None, baggage_code=None, gate=None, found_at=found)
    db.set_partner_offer(conn, deal_id, 48.2, db.utcnow())
    client = TestClient(create_app(ctx))
    [d] = client.get("/api/deals", params={"tab": "queue"}).json()["deals"]
    assert d["found_at_pt"] == i18n_pt.lisbon_timestamp(found)
    assert d["found_ago"].startswith("há 1 h 0") and d["found_fresh"] is True
    assert d["partner_offer_pt"].startswith("oferta especial do Aviasales: −48% face à média deles (visto a ")


def test_time_ago_in_pt_pt():
    ago = i18n_pt.time_ago
    assert ago(NOW - timedelta(minutes=20), NOW) == "há 20 min"
    assert ago(NOW - timedelta(hours=1, minutes=5), NOW) == "há 1 h 05"
    assert ago(NOW - timedelta(hours=47, minutes=59), NOW) == "há 47 h 59"
    assert ago(NOW - timedelta(days=3, hours=2), NOW) == "há 3 dias"
    assert ago(NOW + timedelta(minutes=5), NOW) == "há 0 min"
