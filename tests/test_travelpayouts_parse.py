import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

from escapadinha.collector.travelpayouts import (
    API_URL, TravelpayoutsError, TravelpayoutsSource, found_date, local_dates, parse_response,
    request_params,
)
from escapadinha.models import RouteRules

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "prices_for_dates_LIS_LON.json")
                     .read_text("utf-8"))
FETCHED = datetime(2026, 10, 12, 9, 14, tzinfo=timezone.utc)


def parse(payload=FIXTURE, min_nights=2, max_nights=10):
    return parse_response(payload, origin="LIS", destination="LON", fetched_at=FETCHED,
                          min_nights=min_nights, max_nights=max_nights)


def test_parse_keeps_valid_round_trips_within_nights_range():
    result = parse()
    # dropped: 14 nights, missing return_at, 1 night, price 0
    assert [(o.price, o.nights) for o in result] == [(58.0, 3), (89.0, 7)]


def test_parse_maps_fields_and_keeps_raw_payload():
    first = parse()[0]
    assert first.source == "travelpayouts"
    assert (first.origin, first.destination, first.destination_airport) == ("LIS", "LON", "LGW")
    assert (first.departure_date, first.return_date) == (date(2026, 11, 6), date(2026, 11, 9))
    assert first.currency == "EUR" and first.airline == "U2" and first.flight_number == "8540"
    assert first.transfers == 0
    assert first.fetched_at == FETCHED
    assert first.deep_link.startswith("https://www.aviasales.pt/search/LIS0611LON09111")
    assert json.loads(first.raw_json)["price"] == 58


def test_parse_nights_range_is_configurable():
    assert {o.nights for o in parse(min_nights=1, max_nights=14)} == {3, 14, 1, 7}


NIGHTS = {"rules": RouteRules(min_nights=2, max_nights=10)}


def test_parse_raises_on_api_error():
    with pytest.raises(TravelpayoutsError, match="bad token"):
        parse({"success": False, "data": [], "error": "bad token"})


@respx.mock
def test_source_sends_token_and_month_params():
    route = respx.get(API_URL).mock(return_value=httpx.Response(200, json=FIXTURE))
    source = TravelpayoutsSource("tok", currency="eur", limit=50,
                                 now=lambda: FETCHED)
    result = source.fetch_round_trips("LIS", "LON", date(2026, 11, 1), **NIGHTS)
    request = route.calls.last.request
    assert request.headers["X-Access-Token"] == "tok"
    assert request.url.params["departure_at"] == "2026-11"
    assert request.url.params["one_way"] == "false"
    assert "market" not in request.url.params


@respx.mock
def test_source_sends_market_and_uses_booking_base():
    route = respx.get(API_URL).mock(return_value=httpx.Response(200, json=FIXTURE))
    source = TravelpayoutsSource("tok", currency="eur", limit=50,
                                 market="pt", booking_base="https://www.aviasales.pt/",
                                 now=lambda: FETCHED)
    result = source.fetch_round_trips("LIS", "LON", date(2026, 11, 1), **NIGHTS)
    assert route.calls.last.request.url.params["market"] == "pt"
    assert result[0].deep_link.startswith("https://www.aviasales.pt/search/")
    assert len(result) == 2


@respx.mock
def test_source_retries_after_rate_limit():
    respx.get(API_URL).mock(side_effect=[httpx.Response(429), httpx.Response(200, json=FIXTURE)])
    sleeps = []
    source = TravelpayoutsSource("tok", currency="eur", limit=50,
                                 now=lambda: FETCHED, sleep=sleeps.append)
    assert len(source.fetch_round_trips("LIS", "LON", date(2026, 11, 1), **NIGHTS)) == 2
    assert sleeps == [60.0]


@respx.mock
def test_source_gives_up_after_max_attempts():
    respx.get(API_URL).mock(return_value=httpx.Response(429))
    source = TravelpayoutsSource("tok", currency="eur", limit=50,
                                 sleep=lambda s: None, max_attempts=2)
    with pytest.raises(TravelpayoutsError, match="429"):
        source.fetch_round_trips("LIS", "LON", date(2026, 11, 1), **NIGHTS)


TODAYS_CALL = {"origin": "LIS", "destination": "LON", "departure_at": "2026-11", "one_way": "false",
               "currency": "eur", "sorting": "price", "unique": "false", "limit": 1000,
               "market": "pt"}


def test_a_nonstop_only_route_asks_the_cache_for_nonstop_fares():
    """D39: the cache keeps one offer per date pair, the cheapest; on a route that discards
    every offer with a stop, ask for the cheapest nonstop one instead."""
    def query(rules):
        return request_params("LIS", "LON", date(2026, 11, 1), rules, currency="EUR",
                              limit=1000, market="pt")
    assert query(RouteRules()) == {**TODAYS_CALL, "direct": "true"}             # europe, domestic
    assert query(RouteRules(direct_only=False, max_transfers=0)) == {**TODAYS_CALL,
                                                                     "direct": "true"}
    long_haul = RouteRules(direct_only=False, min_nights=7, max_nights=21, max_transfers=1)
    assert query(long_haul) == TODAYS_CALL                                       # unchanged
    assert query(RouteRules(direct_only=False, max_transfers=None)) == TODAYS_CALL


def test_missing_token_fails_fast():
    with pytest.raises(TravelpayoutsError, match="TRAVELPAYOUTS_TOKEN"):
        TravelpayoutsSource("", currency="eur", limit=50)


@respx.mock
def test_source_applies_the_nights_range_of_each_call():
    respx.get(API_URL).mock(return_value=httpx.Response(200, json=FIXTURE))
    source = TravelpayoutsSource("tok", currency="eur", limit=50, now=lambda: FETCHED)
    trips = source.fetch_round_trips("LIS", "LON", date(2026, 11, 1), **NIGHTS)
    assert trips and all(2 <= o.nights <= 10 for o in trips)
    assert source.fetch_round_trips("LIS", "LON", date(2026, 11, 1),
                                    rules=RouteRules(min_nights=30, max_nights=40)) == []


# --- found date and local dates -------------------------------------------------

RECORDED = json.loads((Path(__file__).parent / "fixtures" /
                       "recorded_prices_for_dates_LIS_LON_2026-11.json").read_text("utf-8"))


def test_found_date_comes_from_link_search_date():
    assert parse()[0].found_date == date(2026, 10, 12)
    assert found_date("/search/LIS1811LON22111?t=x&search_date=07102026") == date(2026, 10, 7)
    assert found_date("/search/x?t=1") is None
    assert found_date("/search/x?search_date=garbage") is None
    assert found_date(None) is None


def test_local_dates_fix_utc_midnight_shift():
    # A 00:30 departure in Lisbon summer time is 23:30Z the day before; the link has the local date.
    assert local_dates("/search/LIS1911LON22111?t=x", date(2026, 11, 18), date(2026, 11, 22)) == \
        (date(2026, 11, 19), date(2026, 11, 22))


def test_local_dates_across_new_year_and_fallbacks():
    assert local_dates("/search/LIS0101LON05011", date(2026, 12, 31), date(2027, 1, 5)) == \
        (date(2027, 1, 1), date(2027, 1, 5))
    # Link dates far from the UTC dates are not trusted.
    assert local_dates("/search/LIS0103LON05031", date(2026, 11, 18), date(2026, 11, 22)) == \
        (date(2026, 11, 18), date(2026, 11, 22))
    assert local_dates(None, date(2026, 11, 18), date(2026, 11, 22)) == \
        (date(2026, 11, 18), date(2026, 11, 22))


def test_parses_recorded_real_response():
    """Recorded from the live API on 2026-10-12 (LIS→LON, November departures)."""
    result = parse(RECORDED, min_nights=1, max_nights=30)
    assert len(result) == len(RECORDED["data"])
    assert all(o.found_date and o.found_date <= date(2026, 10, 12) for o in result)
    assert all(o.deep_link.startswith("https://www.aviasales.pt/search/LIS") for o in result)
    assert all(o.currency == "EUR" and o.price > 0 for o in result)
