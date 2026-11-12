"""Airline and airport names (D66): no visitor reads a bare IATA code where a name belongs.
Every airline and arrival airport of the committed fixtures has a name: the map's, or (for an
airport) the city's when it is its route's only airport. An unknown code still shows as itself."""

import json
from pathlib import Path

import pytest

from escapadinha import i18n_pt as pt
from escapadinha.presentation import PhotoCredit, build_deal_view
from test_captions import deal, observation

FIXTURES = Path(__file__).resolve().parents[1] / "contract" / "site" / "v1" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text("utf-8"))


def fixture_airlines() -> set[str]:
    codes = {p["offer"].get("airline") for p in _load("promotions.json")["promotions"]}
    codes |= {(r.get("cheapest") or {}).get("airline") for r in _load("routes.json")["routes"]}
    for path in (FIXTURES / "low-prices").glob("*.json"):
        doc = json.loads(path.read_text("utf-8"))
        codes |= {row[doc["cols"].index("airline")] for row in doc["rows"]}
    return codes - {None}


def fixture_arrivals() -> set[tuple[str, tuple[str, ...], str]]:
    """(arrival code, its route's airports, the city) of every route and offer in the fixtures."""
    routes = {r["key"]: r for r in _load("routes.json")["routes"]}
    out = {(a, tuple(r["airports"]), r["city"]) for r in routes.values() for a in r["airports"]}
    offers = [p["offer"] for p in _load("promotions.json")["promotions"]]
    offers += [r["cheapest"] for r in routes.values() if r.get("cheapest")]
    for o in offers:
        if o.get("arrival_airport") and o["route"] in routes:
            r = routes[o["route"]]
            out.add((o["arrival_airport"], tuple(r["airports"]), r["city"]))
    for path in (FIXTURES / "low-prices").glob("*.json"):
        doc = json.loads(path.read_text("utf-8"))
        dest, airport = doc["cols"].index("dest"), doc["cols"].index("airport")
        for row in doc["rows"]:
            r = routes.get(f"{path.stem}-{row[dest]}")
            if r and row[airport]:
                out.add((row[airport], tuple(r["airports"]), r["city"]))
    return out


def test_every_fixture_airline_has_a_name():
    missing = sorted(c for c in fixture_airlines() if c.upper() not in pt.AIRLINES)
    assert missing == [], f"airlines without a name in i18n_pt.AIRLINES: {missing}"


def test_every_fixture_arrival_airport_shows_a_name_never_a_bare_code():
    bare = sorted({code for code, airports, city in fixture_arrivals()
                   if pt.airport_label(code, sole_of=pt.sole_city(code, airports, city)) == code})
    assert bare == [], f"arrival airports shown as a bare code: {bare}"


def test_every_airport_of_a_multi_airport_destination_is_in_the_map():
    for d in _load("destinations.json")["destinations"]:
        if len(d["airports"]) > 1:
            assert [a for a in d["airports"] if a not in pt.AIRPORTS] == [], d["code"]


@pytest.mark.parametrize("code, name", [("QS", "Smartwings"), ("AD", "Azul"), ("FR", "Ryanair")])
def test_airlines_seen_on_the_site_are_named(code, name):
    assert pt.airline_name(code) == name


def test_an_airport_is_named_by_the_map_else_by_its_city_when_it_is_the_routes_only_one():
    assert pt.airport_label("BVA") == "Beauvais (BVA)"
    assert pt.airport_label("PRG", sole_of=pt.sole_city("PRG", ["PRG"], "Praga")) == "Praga (PRG)"
    assert pt.sole_city("PRG", ["PRG", "XYZ"], "Praga") is None     # not its only airport
    assert pt.sole_city("CRL", ["BRU"], "Bruxelas") is None         # landed somewhere else
    assert pt.airport_label("XYZ") == "XYZ" and pt.airport_label(None) is None


def test_the_slides_and_captions_name_a_single_airport_city_by_its_city():
    v = build_deal_view(deal(), observation(destination="PRG", destination_airport="PRG"),
                        origin_city="Lisboa", destination_city="Praga",
                        photo=PhotoCredit.from_photo(None, None), route_airports=("PRG",))
    assert v.arrival_airport == "Praga (PRG)"
