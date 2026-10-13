"""Route discovery: which direct routes leave the Portuguese airports (pure, no I/O).

Inputs are the provider's public catalogues (airline routes, airports, cities with their
Portuguese names) plus two token endpoints that show current service: the popular
directions from a city and recent direct fares from the origin. `discover` turns them into
`Found` routes with a kind; `routes.apply_discovery` stores them. Nothing here touches the
network, the clock or the database.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

# Destinations classified as kind `europe`: geographic Europe (EU, EEA, UK, Switzerland,
# micro-states, Balkans, Turkey, Cyprus, Ukraine/Moldova/Belarus/Russia: the last ones are
# excluded in config while their airspace is closed) plus North Africa. Portugal is `domestic`.
EUROPE = frozenset("""
    AD AL AT BA BE BG BY CH CY CZ DE DK EE ES FI FO FR GB GG GI GR HR HU IE IM IS IT JE LI LT
    LU LV MC MD ME MK MT NL NO PL RO RS RU SE SI SK SM TR UA VA XK
""".split())
NORTH_AFRICA = frozenset({"MA", "DZ", "TN", "LY", "EG"})
DOMESTIC = "PT"


@dataclass(frozen=True)
class City:
    code: str
    country: str
    name_en: str
    name_pt: str | None      # None when the catalogue has no Portuguese name


@dataclass(frozen=True)
class Catalogue:
    """The provider's static catalogues, reduced to what discovery needs."""

    airport_city: Mapping[str, str]         # airport IATA -> city code
    cities: Mapping[str, City]              # city code -> City
    direct: Mapping[str, frozenset[str]]    # origin airport -> arrival airports, nonstop

    @classmethod
    def from_payloads(cls, routes: Iterable[dict], airports: Iterable[dict],
                      cities_pt: Iterable[dict], origins: Iterable[str]) -> Catalogue:
        """`routes.json`, `airports.json` and `pt/cities.json` exactly as served."""
        wanted = set(origins)
        direct: dict[str, set[str]] = {o: set() for o in wanted}
        for r in routes:
            if r.get("departure_airport_iata") in wanted and r.get("transfers") == 0 \
                    and r.get("arrival_airport_iata"):
                direct[r["departure_airport_iata"]].add(r["arrival_airport_iata"])
        airport_city = {a["code"]: a["city_code"] for a in airports
                        if a.get("code") and a.get("city_code")}
        cities = {}
        for c in cities_pt:
            en = (c.get("name_translations") or {}).get("en") or c.get("name")
            if c.get("code") and c.get("country_code") and en:
                cities[c["code"]] = City(c["code"], c["country_code"], en, c.get("name") or None)
        return cls(airport_city, cities, {o: frozenset(a) for o, a in direct.items()})


@dataclass(frozen=True)
class Found:
    """A direct (or curated long-haul) route the sources say exists."""

    origin: str                       # airport IATA
    destination: str                  # provider city code
    kind: str                         # europe | domestic | long_haul
    city_pt: str                      # Portuguese name, English when the catalogue has none
    city_en: str | None
    airports: frozenset[str] = field(default_factory=frozenset)   # arrival airports, if known
    sources: frozenset[str] = field(default_factory=frozenset)

    @property
    def key(self) -> str:
        return f"{self.origin}-{self.destination}"


@dataclass(frozen=True)
class LongHaul:
    destination: str
    city_pt: str
    origins: tuple[str, ...]


def kind_of(country: str) -> str | None:
    """`domestic` for Portugal, `europe` for Europe and North Africa, None for the rest."""
    if country == DOMESTIC:
        return "domestic"
    if country in EUROPE or country in NORTH_AFRICA:
        return "europe"
    return None


def popular_direct(payload: Mapping) -> set[str]:
    """City codes from a `v1/city-directions` payload whose cheapest fare was nonstop."""
    data = payload.get("data") if payload.get("success") else None
    return {code for code, item in (data or {}).items()
            if isinstance(item, Mapping) and item.get("transfers") == 0}


def recent_direct(payload: Mapping) -> tuple[set[str], dict[str, set[str]]]:
    """City codes (and their arrival airports) from a `v3/prices_for_dates` payload asked with
    an origin only and `direct=true`. Items that are not nonstop are ignored."""
    cities: set[str] = set()
    airports: dict[str, set[str]] = {}
    for item in (payload.get("data") or []) if payload.get("success") else []:
        if item.get("transfers") != 0 or not item.get("destination"):
            continue
        cities.add(item["destination"])
        if item.get("destination_airport"):
            airports.setdefault(item["destination"], set()).add(item["destination_airport"])
    return cities, airports


def discover(catalogue: Catalogue, origins: Sequence[str], *,
             popular: Mapping[str, Mapping] | None = None,
             recent: Mapping[str, Iterable[Mapping]] | None = None,
             long_haul: Iterable[LongHaul] = ()) -> list[Found]:
    """Every route from `origins`, sorted by origin then destination.

    - catalogue: nonstop airline routes, arrival airports mapped to their city;
    - popular / recent (per origin, optional): destinations reached nonstop recently;
    - long_haul: the curated list, always included for its listed origins.
    A destination outside Portugal, Europe and North Africa is kept only when it is on the
    curated long-haul list for that origin (then kind `long_haul`). Unknown cities are skipped.
    """
    popular, recent = popular or {}, recent or {}
    curated = {(o, lh.destination): lh for lh in long_haul for o in lh.origins}
    found: dict[tuple[str, str], tuple[set[str], set[str]]] = {}

    def add(origin: str, city: str, source: str, airports: Iterable[str] = ()) -> None:
        sources, aps = found.setdefault((origin, city), (set(), set()))
        sources.add(source)
        aps.update(airports)

    for origin in origins:
        origin_city = catalogue.airport_city.get(origin, origin)
        by_city: dict[str, set[str]] = {}
        for airport in catalogue.direct.get(origin, ()):
            city = catalogue.airport_city.get(airport)
            if city:
                by_city.setdefault(city, set()).add(airport)
        for city, airports in by_city.items():
            add(origin, city, "catalogue", airports)
        for city in popular_direct(popular.get(origin, {})):
            add(origin, city, "popular")
        for payload in recent.get(origin, ()):
            cities, airports = recent_direct(payload)
            for city in cities:
                add(origin, city, "recent", airports.get(city, ()))
        for (o, city), lh in curated.items():
            if o == origin:
                add(origin, city, "curated")
        for key in [k for k in found if k[0] == origin and k[1] == origin_city]:
            del found[key]                     # same city as the origin (e.g. a second airport)

    out = []
    for (origin, code), (sources, airports) in found.items():
        city = catalogue.cities.get(code)
        lh = curated.get((origin, code))
        if lh is not None:
            kind, name = "long_haul", lh.city_pt
        elif city is None:
            continue
        else:
            kind = kind_of(city.country)
            if kind is None:
                continue
            name = city.name_pt or city.name_en
        out.append(Found(origin, code, kind, name, city.name_en if city else None,
                         frozenset(airports), frozenset(sources)))
    order = {o: i for i, o in enumerate(origins)}
    return sorted(out, key=lambda f: (order.get(f.origin, len(order)), f.destination))
