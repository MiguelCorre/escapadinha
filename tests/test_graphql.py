"""The Aviasales GraphQL client and the offer match (D39): parsing and matching are pure, the
request carries the token and the trip window, the per-minute limiter holds under concurrent
callers, a 429 waits. HTTP only through respx: never a real call."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

import httpx
import pytest
import respx

from escapadinha.collector import graphql
from escapadinha.collector.graphql import (
    API_URL, NO_MATCH, GraphQLClient, GraphQLError, match, parse_response, price_matches,
    ticket_token, variables,
)
from escapadinha.collector.travelpayouts import RateLimiter
from escapadinha.models import Observation

FETCHED = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)
# The probe of 2026-10-15 (LIS-PAR, 10–12 Nov): the REST item said MW, 93 €; the GraphQL row
# FR, 92.5 €, sold by City.Travel; both links carry this `t=` token.
TOKEN = "FR17943243001794336900000150LISBVA17944932001794498900000155BVALIS_3c1739fab94f6a4b54a76aa80d3cf2cd_8657"
FOUND_AT = 1791955403                      # 2026-10-14T05:23:23Z


def row(**over) -> dict:
    base = {
        "departure_at": "2026-11-10T15:25:00Z", "return_at": "2026-11-12T15:55:00Z",
        "origin_airport_iata": "LIS", "destination_airport_iata": "BVA", "value": 92.5,
        "currency": "eur", "number_of_changes": 0, "main_airline": "FR", "found_at": FOUND_AT,
        "with_baggage": False, "baggage_code": "0PC", "gate": "City.Travel",
        "ticket_link": f"/LIS1011PAR12111?t={TOKEN}&search_date=14102026&expected_price=93",
    }
    return base | over


def payload(*rows: dict) -> dict:
    return {"data": {"prices_round_trip": list(rows)}}


def observation(**over) -> Observation:
    fields = dict(
        id=5, source="travelpayouts", origin="LIS", destination="PAR", origin_airport="LIS",
        destination_airport="BVA", departure_date=date(2026, 11, 10), return_date=date(2026, 11, 12),
        price=93.0, currency="EUR", airline="MW", flight_number="1", transfers=0,
        return_transfers=0, fetched_at=FETCHED,
        deep_link=f"https://www.aviasales.pt/search/LIS1011PAR12111?t={TOKEN}&search_date=14102026",
    )
    return Observation(**(fields | over))


# --- the request ---------------------------------------------------------------------------

def test_variables_window_the_trip_dates_and_ask_direct_only_when_the_route_does():
    v = variables("LIS", "PAR", date(2026, 11, 10), date(2026, 11, 12), direct=True,
                  currency="EUR", market="pt")
    assert v["params"] == {"origin": "LIS", "destination": "PAR", "direct": True,
                           "depart_date_min": "2026-11-09", "depart_date_max": "2026-11-10",
                           "return_date_min": "2026-11-11", "return_date_max": "2026-11-13"}
    assert v["paging"] == {"limit": 400, "offset": 0} and v["currency"] == "eur" and v["market"] == "pt"
    loose = variables("LIS", "JFK", date(2026, 11, 10), date(2026, 11, 20), direct=False,
                      currency="eur", market=None)
    assert "direct" not in loose["params"] and loose["market"] is None


def test_ticket_token_is_the_links_t_parameter():
    assert ticket_token(observation().deep_link) == TOKEN
    assert ticket_token(row()["ticket_link"]) == TOKEN
    assert ticket_token(None) is None and ticket_token("/search/LIS1011PAR12111") is None


# --- parsing -------------------------------------------------------------------------------

def test_parse_reads_the_fields_and_the_unix_found_time():
    [o] = parse_response(payload(row(main_airline="fr")))
    assert (o.value, o.currency, o.airline, o.transfers) == (92.5, "EUR", "FR", 0)
    assert o.found_at == datetime(2026, 10, 14, 5, 23, 23, tzinfo=timezone.utc)
    assert (o.with_baggage, o.baggage_code, o.gate) == (False, "0PC", "City.Travel")
    assert o.ticket == TOKEN and o.trip_dates == (date(2026, 11, 10), date(2026, 11, 12))
    assert o.destination_airport == "BVA"


def test_parse_drops_rows_it_cannot_read_and_raises_on_graphql_errors():
    rows = [row(value=0), row(found_at=None), {"value": 10}, row(return_at=None), row()]
    kept = parse_response(payload(*rows))
    assert [o.return_at for o in kept] == [None, "2026-11-12T15:55:00Z"]
    assert kept[0].trip_dates is None
    with pytest.raises(GraphQLError, match="limit must be") as info:
        parse_response({"errors": [{"message": "limit must be equal or less than 400"}], "data": None})
    assert info.value.kind == "api"
    with pytest.raises(GraphQLError, match="no prices_round_trip"):
        parse_response({"data": {}})


# --- matching ------------------------------------------------------------------------------

@pytest.mark.parametrize("value, price, ok", [
    (92.5, 93.0, True),      # the REST API rounds to the euro (half up)
    (92.49, 93.0, False),
    (93.004, 93.0, True),
    (92.5, 92.0, False),
    (58.3, 58.3, True),
    (58.32, 58.3, False),    # a price with cents must match to the cent
])
def test_price_matches_to_the_cent_or_to_the_rounded_euro(value, price, ok):
    assert price_matches(value, price) is ok


def test_match_by_ticket_token_even_when_rest_rounded_the_price_and_named_another_airline():
    found = match(observation(), parse_response(payload(row(), row(value=120, ticket_link="/x?t=other"))))
    assert found.how == "ticket" and found.found
    assert (found.with_baggage, found.baggage_code, found.gate) == (False, "0PC", "City.Travel")
    assert found.found_at == datetime(2026, 10, 14, 5, 23, 23, tzinfo=timezone.utc)


def test_match_without_a_link_falls_back_to_airline_dates_and_rounded_price():
    rows = parse_response(payload(row(), row(value=92.5, gate="Kiwi.com", with_baggage=False,
                                                ticket_link="/LIS1011PAR12111?t=another")))
    obs = observation(deep_link=None, airline="FR")
    found = match(obs, rows)
    assert found.how == "offer" and found.with_baggage is False and found.gate is None   # two gates
    assert match(observation(deep_link=None, airline="MW"), rows) == NO_MATCH     # airline differs
    assert match(observation(deep_link=None, airline="FR", price=92.0), rows) == NO_MATCH
    assert match(observation(deep_link=None, airline="FR", return_date=date(2026, 11, 13)),
                 rows) == NO_MATCH


def test_rows_that_disagree_leave_the_field_unknown_never_guessed():
    rows = parse_response(payload(row(), row(with_baggage=True, baggage_code="1PC20", found_at=FOUND_AT + 5)))
    found = match(observation(), rows)
    assert found.how == "ticket"
    assert (found.with_baggage, found.baggage_code, found.found_at) == (None, None, None)
    assert found.gate == "City.Travel"                                       # they agree on that


def test_no_row_means_no_match():
    assert match(observation(), []) == NO_MATCH and not NO_MATCH.found
    assert match(observation(), parse_response(payload(row(ticket_link="/x?t=other", value=80)))) == NO_MATCH


# --- the client ----------------------------------------------------------------------------

@respx.mock
def test_client_posts_the_query_with_the_token_and_keeps_the_answer_for_the_archive():
    route = respx.post(API_URL).mock(return_value=httpx.Response(200, json=payload(row())))
    client = GraphQLClient("tok", currency="EUR", market="pt", now=lambda: FETCHED)
    answer = client.prices_round_trip("LIS", "PAR", date(2026, 11, 10), date(2026, 11, 12), direct=True)
    request = route.calls.last.request
    body = json.loads(request.content)
    assert request.headers["X-Access-Token"] == "tok"
    assert body["query"].startswith("query PricesRoundTrip") and "prices_round_trip" in body["query"]
    assert body["variables"]["params"]["direct"] is True and body["variables"]["currency"] == "eur"
    assert [o.gate for o in answer.offers] == ["City.Travel"]
    assert answer.response["payload"] == payload(row()) and answer.response["source"] == graphql.SOURCE
    assert answer.response["fetched_at"] == FETCHED.isoformat()
    assert "tok" not in json.dumps(answer.response)


@respx.mock
def test_a_429_waits_for_the_limits_reset_then_retry_after_then_a_minute():
    respx.post(API_URL).mock(side_effect=[
        httpx.Response(429, headers={"X-Rate-Limit-Reset": "19"}),
        httpx.Response(429, headers={"Retry-After": "3"}),
        httpx.Response(429),
        httpx.Response(200, json=payload(row()))])
    sleeps = []
    client = GraphQLClient("tok", currency="eur", sleep=sleeps.append, max_attempts=4)
    answer = client.prices_round_trip("LIS", "PAR", date(2026, 11, 10), date(2026, 11, 12), direct=True)
    assert len(answer.offers) == 1 and sleeps == [19.0, 3.0, 60.0]


@respx.mock
def test_gives_up_after_max_attempts_with_an_http_error():
    respx.post(API_URL).mock(return_value=httpx.Response(429))
    client = GraphQLClient("tok", currency="eur", sleep=lambda s: None, max_attempts=2)
    with pytest.raises(GraphQLError, match="429") as info:
        client.prices_round_trip("LIS", "PAR", date(2026, 11, 10), date(2026, 11, 12), direct=True)
    assert (info.value.kind, info.value.status) == ("http", 429)


@respx.mock
def test_graphql_errors_and_non_json_answers_raise_api_errors():
    respx.post(API_URL).mock(return_value=httpx.Response(
        200, json={"errors": [{"message": "limit must be equal or less than 400"}], "data": None}))
    client = GraphQLClient("tok", currency="eur")
    with pytest.raises(GraphQLError, match="limit must be"):
        client.prices_round_trip("LIS", "PAR", date(2026, 11, 10), date(2026, 11, 12), direct=True)
    respx.post(API_URL).mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(GraphQLError, match="not JSON"):
        client.prices_round_trip("LIS", "PAR", date(2026, 11, 10), date(2026, 11, 12), direct=True)


def test_missing_token_fails_fast():
    with pytest.raises(GraphQLError, match="TRAVELPAYOUTS_TOKEN") as info:
        GraphQLClient("", currency="eur")
    assert info.value.kind == "token"


class Recording(RateLimiter):
    """Records each call's time as the limiter saw it (under its lock)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.stamps: list[float] = []

    def _wait(self) -> None:
        super()._wait()
        self.stamps.append(self._calls[-1])


@respx.mock
def test_the_per_minute_limit_holds_under_eight_workers():
    respx.post(API_URL).mock(return_value=httpx.Response(200, json=payload()))
    clock = [0.0]
    limiter = Recording(55, clock=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s))
    client = GraphQLClient("tok", currency="eur", limiter=limiter)

    def ask(i):
        return client.prices_round_trip("LIS", "PAR", date(2026, 11, 1 + i % 20), date(2026, 11, 25),
                                        direct=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        answers = list(pool.map(ask, range(120)))
    assert len(answers) == 120 and len(respx.calls) == 120
    stamps = sorted(limiter.stamps)
    assert len(stamps) == 120
    for t in stamps:
        assert sum(t <= s < t + 60 for s in stamps) <= 55
    assert stamps[-1] >= 120                      # 120 calls at 55/min take two waits
