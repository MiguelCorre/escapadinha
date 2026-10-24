import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from escapadinha.collector.ryanair import (
    API_URL, RyanairError, RyanairSource, booking_url, parse_fares, request_params, user_agent,
)
from escapadinha.models import RouteRules

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "ryanair_roundTripFares_LIS_STN.json")
                     .read_text("utf-8"))
FETCHED = datetime(2026, 10, 24, 14, 30, tzinfo=timezone.utc)
RULES = RouteRules(direct_only=True, min_nights=2, max_nights=7)


def parse(payload=FIXTURE, rules=RULES):
    return parse_fares(payload, origin="LIS", destination="LON", airport="STN",
                       fetched_at=FETCHED, rules=rules)


def test_parse_keeps_priced_round_trips_within_the_nights_range():
    # dropped: the zero-price copy and the 28-night one
    assert [(o.departure_date, o.return_date, o.price) for o in parse()] == [
        (date(2026, 11, 19), date(2026, 11, 22), 59.39),
        (date(2026, 11, 2), date(2026, 11, 7), 316.98),
        (date(2026, 11, 1), date(2026, 11, 3), 446.66),
    ]


def test_parse_maps_the_fare_to_an_observation_of_the_route():
    first = parse()[0]
    assert first.source == "ryanair" and first.airline == "FR" and first.gate == "Ryanair"
    assert (first.origin, first.destination) == ("LIS", "LON")       # the route key, not the airport
    assert (first.origin_airport, first.destination_airport) == ("LIS", "STN")
    assert first.currency == "EUR" and first.flight_number == "1081"
    assert (first.transfers, first.return_transfers) == (0, 0)          # the fare finder is nonstop
    assert first.nights == 3 and first.fetched_at == FETCHED
    assert first.departure_at == "2026-11-19T10:25:00" and first.return_at == "2026-11-22T06:20:00"
    assert json.loads(first.raw_json)["summary"]["price"]["value"] == 59.39


def test_found_at_is_the_newer_price_update_of_the_two_legs():
    first = parse()[0]
    # outbound priceUpdated 1792850752000, inbound 1792833979000 (ms): the outbound one wins
    assert first.found_at == datetime.fromtimestamp(1792850752, tz=timezone.utc)
    assert first.found_date == first.found_at.date()


def test_link_goes_to_ryanair_for_the_same_dates_without_tracking():
    link = parse()[0].deep_link
    assert link.startswith("https://www.ryanair.com/pt/pt/trip/flights/select?")
    q = parse_qs(urlsplit(link).query)
    assert q["originIata"] == ["LIS"] and q["destinationIata"] == ["STN"]
    assert q["dateOut"] == ["2026-11-19"] and q["dateIn"] == ["2026-11-22"]
    assert "marker" not in q and "utm_source" not in q
    assert link == booking_url("LIS", "STN", date(2026, 11, 19), date(2026, 11, 22))


def test_dedup_key_separates_sources_and_price_days():
    first = parse()[0]
    assert first.dedup_key.startswith("ryanair|LIS|LON|2026-11-19T10:25:00|2026-11-22T06:20:00|FR|1081|59.39|")


def test_parse_refuses_a_payload_without_fares():
    with pytest.raises(RyanairError) as exc:
        parse({"error": "x"})
    assert exc.value.kind == "api"


def test_request_asks_the_whole_month_within_the_route_nights():
    p = request_params("OPO", "BGY", date(2026, 12, 1), RouteRules(min_nights=3, max_nights=10))
    assert (p["departureAirportIataCode"], p["arrivalAirportIataCode"]) == ("OPO", "BGY")
    assert (p["outboundDepartureDateFrom"], p["outboundDepartureDateTo"]) == ("2026-12-01", "2026-12-31")
    assert (p["inboundDepartureDateFrom"], p["inboundDepartureDateTo"]) == ("2026-12-04", "2027-01-10")
    assert (p["durationFrom"], p["durationTo"]) == (3, 10)
    assert p["market"] == "pt-pt" and p["currency"] == "EUR" and p["adultPaxCount"] == 1


def test_user_agent_names_the_site():
    assert user_agent("https://pontonomada.pt/") == "pontonomada.pt price check (+https://pontonomada.pt/sobre/)"


def source(now=lambda: FETCHED):
    return RyanairSource(user_agent=user_agent("https://pontonomada.pt"), now=now)


@respx.mock
def test_fetch_sends_the_identifying_headers_and_archives_the_payload():
    route = respx.get(API_URL).mock(return_value=httpx.Response(
        200, json=FIXTURE, headers={"content-type": "application/json;charset=UTF-8"}))
    fetched = source().fetch_fares("LIS", "LON", "STN", date(2026, 11, 1), rules=RULES)
    request = route.calls.last.request
    assert request.headers["user-agent"].startswith("pontonomada.pt price check (+https://")
    assert request.headers["accept"] == "application/json"
    assert request.url.params["arrivalAirportIataCode"] == "STN"
    assert [o.price for o in fetched.observations] == [59.39, 316.98, 446.66]
    assert fetched.response["payload"] == FIXTURE and fetched.response["source"] == "ryanair"
    assert fetched.response["airport"] == "STN" and fetched.response["month"] == "2026-11"


@respx.mock
@pytest.mark.parametrize("status, body, content_type", [
    (403, "Access Denied", "text/html"),
    (429, "{}", "application/json"),
    (200, "<html><title>Human Verification</title></html>", "text/html"),
])
def test_a_wall_is_reported_as_blocked_without_a_retry(status, body, content_type):
    route = respx.get(API_URL).mock(return_value=httpx.Response(
        status, text=body, headers={"content-type": content_type}))
    with pytest.raises(RyanairError) as exc:
        source().fetch_fares("LIS", "LON", "STN", date(2026, 11, 1), rules=RULES)
    assert exc.value.kind == "blocked" and exc.value.status == status
    assert route.call_count == 1


@respx.mock
def test_other_errors_are_http_or_api_and_never_retried():
    route = respx.get(API_URL).mock(return_value=httpx.Response(
        500, text="boom", headers={"content-type": "application/json"}))
    with pytest.raises(RyanairError) as exc:
        source().fetch_fares("LIS", "LON", "STN", date(2026, 11, 1), rules=RULES)
    assert exc.value.kind == "http" and exc.value.status == 500 and route.call_count == 1
    respx.get(API_URL).mock(return_value=httpx.Response(
        200, text="[]", headers={"content-type": "application/json"}))
    with pytest.raises(RyanairError) as exc:
        source().fetch_fares("LIS", "LON", "STN", date(2026, 11, 1), rules=RULES)
    assert exc.value.kind == "api"
