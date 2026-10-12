import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

from escapadinha.collector.travelpayouts import (
    API_URL, TravelpayoutsError, TravelpayoutsSource, parse_response,
)

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
    assert first.deep_link.startswith("https://www.aviasales.com/search/LIS0611LON09111")
    assert json.loads(first.raw_json)["price"] == 58


def test_parse_nights_range_is_configurable():
    assert {o.nights for o in parse(min_nights=1, max_nights=14)} == {3, 14, 1, 7}


def test_parse_raises_on_api_error():
    with pytest.raises(TravelpayoutsError, match="bad token"):
        parse({"success": False, "data": [], "error": "bad token"})


@respx.mock
def test_source_sends_token_and_month_params():
    route = respx.get(API_URL).mock(return_value=httpx.Response(200, json=FIXTURE))
    source = TravelpayoutsSource("tok", currency="eur", min_nights=2, max_nights=10, limit=50,
                                 now=lambda: FETCHED)
    result = source.fetch_round_trips("LIS", "LON", date(2026, 11, 1))
    request = route.calls.last.request
    assert request.headers["X-Access-Token"] == "tok"
    assert request.url.params["departure_at"] == "2026-11"
    assert request.url.params["one_way"] == "false"
    assert len(result) == 2


@respx.mock
def test_source_retries_after_rate_limit():
    respx.get(API_URL).mock(side_effect=[httpx.Response(429), httpx.Response(200, json=FIXTURE)])
    sleeps = []
    source = TravelpayoutsSource("tok", currency="eur", min_nights=2, max_nights=10, limit=50,
                                 now=lambda: FETCHED, sleep=sleeps.append)
    assert len(source.fetch_round_trips("LIS", "LON", date(2026, 11, 1))) == 2
    assert sleeps == [60.0]


@respx.mock
def test_source_gives_up_after_max_attempts():
    respx.get(API_URL).mock(return_value=httpx.Response(429))
    source = TravelpayoutsSource("tok", currency="eur", min_nights=2, max_nights=10, limit=50,
                                 sleep=lambda s: None, max_attempts=2)
    with pytest.raises(TravelpayoutsError, match="429"):
        source.fetch_round_trips("LIS", "LON", date(2026, 11, 1))


def test_missing_token_fails_fast():
    with pytest.raises(TravelpayoutsError, match="TRAVELPAYOUTS_TOKEN"):
        TravelpayoutsSource("", currency="eur", min_nights=2, max_nights=10, limit=50)
