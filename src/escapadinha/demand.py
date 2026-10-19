"""Route demand from Eurostat `avia_par_pt` (D45): passengers carried per month on each airport
pair with a Portuguese airport, read from the dataset's JSON-stat answer. Pure: no I/O, no clock.

- `parse_jsonstat` turns the answer into `{(reporting ICAO, partner ICAO, month): passengers}`;
  suppressed or empty cells (":" in Eurostat's tables, absent from the JSON) are left out.
- `route_demand` maps ICAO codes to IATA (`ICAO_IATA`), partner airports to our city codes
  through the provider's `airports.json` (`city_code`), sums the partner airports of a city and
  gives each route the last 12 months the dataset has and their mean.
- `rank_routes` orders routes by that mean (1 = the busiest).

A passenger count is demand, never a price: nothing here produces an amount in euros.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from escapadinha.models import Route

DATASET = "avia_par_pt"
# The dataset reports the airport pair as `<country>_<ICAO>_<country>_<ICAO>` (reporting
# Portuguese airport first), e.g. PT_LPPT_ES_LEMD.
PAIR_DIMENSION = "airp_pr"
TIME_DIMENSION = "time"
WINDOW_MONTHS = 12

# ICAO location indicator -> IATA code, for the Portuguese airports and the partner airports the
# dataset lists (Eurostat labels its pairs by ICAO; the provider's catalogues carry IATA only).
# Source: the airports' published ICAO/IATA codes (ICAO Doc 7910 location indicators, IATA
# airport codes), each entry checked on 2026-10-19 against the Travelpayouts `airports.json`
# name and city. A partner missing here contributes nothing (its route shows no figure); add
# it when the dataset gains a pair we watch.
ICAO_IATA: dict[str, str] = {
    # Portugal (reporting airports and domestic partners)
    "LPPT": "LIS", "LPPR": "OPO", "LPFR": "FAO", "LPMA": "FNC", "LPPS": "PXO", "LPPD": "PDL",
    "LPLA": "TER", "LPHR": "HOR", "LPPI": "PIX", "LPSJ": "SJZ", "LPGR": "GRW", "LPFL": "FLW",
    "LPAZ": "SMA",
    # Spain
    "LEMD": "MAD", "LEBL": "BCN", "LEMG": "AGP", "LEPA": "PMI", "LEVC": "VLC", "LEZL": "SVQ",
    "LEAL": "ALC", "LEBB": "BIO", "LEGE": "GRO", "LEIB": "IBZ", "LEJR": "XRY", "GCLP": "LPA",
    "GCRR": "ACE", "GCTS": "TFS",
    # France
    "LFPO": "ORY", "LFPG": "CDG", "LFOB": "BVA", "LFLL": "LYS", "LFML": "MRS", "LFMN": "NCE",
    "LFBO": "TLS", "LFBD": "BOD", "LFRS": "NTE", "LFQQ": "LIL", "LFSB": "BSL", "LFOK": "XCR",
    # United Kingdom and Ireland
    "EGLL": "LHR", "EGKK": "LGW", "EGSS": "STN", "EGGW": "LTN", "EGLC": "LCY", "EGMC": "SEN",
    "EGCC": "MAN", "EGBB": "BHX", "EGGD": "BRS", "EGPH": "EDI", "EGPF": "GLA", "EGPK": "PIK",
    "EGNM": "LBA", "EGNT": "NCL", "EGGP": "LPL", "EGNX": "EMA", "EGBN": "NQT", "EGCN": "DSA",
    "EGHH": "BOH", "EGTE": "EXT", "EGFF": "CWL", "EGBE": "CVT", "EGAA": "BFS", "EGAC": "BHD",
    "EIDW": "DUB", "EICK": "ORK", "EINN": "SNN",
    # Germany, Austria, Switzerland, Benelux
    "EDDF": "FRA", "EDFH": "HHN", "EDDM": "MUC", "EDDB": "BER", "EDDT": "TXL", "EDDH": "HAM",
    "EDDL": "DUS", "EDLV": "NRN", "EDDK": "CGN", "EDDS": "STR", "EDDV": "HAJ", "EDDN": "NUE",
    "EDDP": "LEJ", "EDDW": "BRE", "EDDC": "DRS", "EDDG": "FMO", "EDDR": "SCN", "EDJA": "FMM",
    "EDLP": "PAD", "EDLW": "DTM", "EDSB": "FKB",
    "LOWW": "VIE", "LSZH": "ZRH", "LSGG": "GVA",
    "EHAM": "AMS", "EHEH": "EIN", "EHRD": "RTM", "EHBK": "MST", "EBBR": "BRU", "EBCI": "CRL",
    "ELLX": "LUX",
    # Italy
    "LIRF": "FCO", "LIRA": "CIA", "LIMC": "MXP", "LIML": "LIN", "LIME": "BGY", "LIPZ": "VCE",
    "LIPE": "BLQ", "LIRN": "NAP", "LIRP": "PSA", "LIRQ": "FLR",
    # Nordics, Central and Eastern Europe, Turkey, Israel
    "EKCH": "CPH", "EKBI": "BLL", "ESSA": "ARN", "ESGG": "GOT", "ENGM": "OSL", "EFHK": "HEL",
    "BIKF": "KEF", "EPWA": "WAW", "EPKT": "KTW", "LKPR": "PRG", "LHBP": "BUD", "LROP": "OTP",
    "EYVI": "VNO", "LGAV": "ATH", "LTFM": "IST", "LTBA": "ISL", "LLBG": "TLV",
    # Africa and the Middle East
    "GMMN": "CMN", "GMMX": "RAK", "GOBD": "DSS", "GVAC": "SID", "GVNP": "RAI", "GVSV": "VXE",
    "FNLU": "LAD", "FQMA": "MPM", "FAJS": "JNB", "OMDB": "DXB", "OMAA": "AUH", "OTHH": "DOH",
    # Americas
    "KJFK": "JFK", "KEWR": "EWR", "KBOS": "BOS", "KIAD": "IAD", "KMIA": "MIA", "KORD": "ORD",
    "KPHL": "PHL", "KSFO": "SFO", "CYYZ": "YYZ", "CYUL": "YUL", "CYMX": "YMX", "MMUN": "CUN",
    "MDPC": "PUJ", "SVMI": "CCS",
    "SBGR": "GRU", "SBKP": "VCP", "SBGL": "GIG", "SBBR": "BSB", "SBCF": "CNF", "SBSV": "SSA",
    "SBRF": "REC", "SBFZ": "FOR", "SBSG": "NAT", "SBPA": "POA",
    # Russia (closed airspace since 2022; kept so the history parses)
    "UUEE": "SVO", "UUDD": "DME",
}

Cell = tuple[str, str, str]      # (reporting airport ICAO, partner airport ICAO, month "YYYY-MM")


class DemandError(ValueError):
    """The answer is not the JSON-stat document the parser expects."""


def parse_jsonstat(doc: Mapping) -> dict[Cell, int]:
    """`avia_par_pt` as the Eurostat API serves it (`format=JSON`: JSON-stat 2.0, one
    dataset): the `value` object maps a cell's flattened position (row-major over `size`, the
    dimensions in `id` order) to its number. Cells with no value (suppressed or not reported)
    are simply absent, or null: left out. Any other dimension (unit, measure, frequency) is
    ignored; the request fixes them to one category each."""
    try:
        ids: list[str] = list(doc["id"])
        sizes: list[int] = [int(s) for s in doc["size"]]
        pairs = _positions(doc["dimension"][PAIR_DIMENSION])
        months = _positions(doc["dimension"][TIME_DIMENSION])
        values = doc["value"]
    except (KeyError, TypeError) as exc:
        raise DemandError(f"not a JSON-stat dataset with {PAIR_DIMENSION} and time: {exc}") from exc
    if len(ids) != len(sizes) or PAIR_DIMENSION not in ids or TIME_DIMENSION not in ids:
        raise DemandError("the dataset's dimensions do not match its sizes")
    strides = _strides(sizes)
    pair_at = ids.index(PAIR_DIMENSION)
    time_at = ids.index(TIME_DIMENSION)
    items = values.items() if isinstance(values, Mapping) else enumerate(values)
    cells: dict[Cell, int] = {}
    for key, value in items:
        if value is None:
            continue
        position = int(key)
        pair = pairs[(position // strides[pair_at]) % sizes[pair_at]]
        month = months[(position // strides[time_at]) % sizes[time_at]]
        parts = pair.split("_")
        if len(parts) != 4:
            raise DemandError(f"unexpected airport pair code {pair!r}")
        cells[(parts[1], parts[3], month)] = int(round(float(value)))
    return cells


def _positions(dimension: Mapping) -> dict[int, str]:
    """A dimension's categories by position (JSON-stat `index`: code -> position, or a list)."""
    index = dimension["category"]["index"]
    if isinstance(index, Mapping):
        return {int(position): str(code) for code, position in index.items()}
    return dict(enumerate(str(code) for code in index))


def _strides(sizes: list[int]) -> list[int]:
    strides = [1] * len(sizes)
    for i in range(len(sizes) - 2, -1, -1):
        strides[i] = strides[i + 1] * sizes[i + 1]
    return strides


def months_available(cells: Mapping[Cell, int]) -> list[str]:
    """Every month with at least one value, ascending."""
    return sorted({month for _, _, month in cells})


@dataclass(frozen=True)
class Demand:
    """A route's passengers over the dataset's last `WINDOW_MONTHS` months."""

    pax_month: float                        # mean over the window; months without a value count 0
    period: str                             # the window's last month, "YYYY-MM"
    months: tuple[tuple[str, int], ...]     # (month, passengers) for every month of the window

    @property
    def zero_months(self) -> tuple[str, ...]:
        """Months the dataset shows without passengers: a seasonal route (or one that ended)."""
        return tuple(month for month, pax in self.months if pax == 0)

    @property
    def seasonal(self) -> bool:
        return bool(self.zero_months)

    def to_json(self) -> dict:
        """As the site contract carries it (routes.json `demand`, D45)."""
        return {"pax_month": int(round(self.pax_month)), "period": self.period,
                "months": [{"month": month, "pax": pax} for month, pax in self.months]}


def airport_cities(airports: Iterable[Mapping]) -> dict[str, str]:
    """Airport IATA -> city code from the provider's `airports.json` rows (a code without a
    city, or one the catalogue doesn't know, maps to itself: the Azores' small airports are
    their own city)."""
    return {a["code"]: a.get("city_code") or a["code"] for a in airports if a.get("code")}


def route_demand(cells: Mapping[Cell, int], airports: Iterable[Mapping],
                 pairs: Iterable[tuple[str, str]], *, window: int = WINDOW_MONTHS) -> dict[str, Demand]:
    """Passengers per route key ("LIS-PAR") for `pairs` (origin airport IATA, destination city
    code): the reporting airport is the origin, the partner airports of the destination city are
    summed (Orly + Charles de Gaulle + Beauvais = PAR). The window is the dataset's last
    `window` months with any value; a route with no value in it gets nothing (null stays
    null: Eurostat does not disseminate small routes, and a new route has no history yet)."""
    months = months_available(cells)
    if not months:
        return {}
    window_months = months[-window:]
    cities = airport_cities(airports)
    by_route: dict[tuple[str, str, str], int] = defaultdict(int)
    for (reporting, partner, month), pax in cells.items():
        origin = ICAO_IATA.get(reporting)
        arrival = ICAO_IATA.get(partner)
        if origin is None or arrival is None:
            continue
        by_route[(origin, cities.get(arrival, arrival), month)] += pax
    out: dict[str, Demand] = {}
    for origin, destination in pairs:
        values = [by_route.get((origin, destination, m)) for m in window_months]
        if all(v is None for v in values):
            continue
        counted = tuple((m, v or 0) for m, v in zip(window_months, values))
        out[f"{origin}-{destination}"] = Demand(sum(v for _, v in counted) / len(counted),
                                                window_months[-1], counted)
    return out


def rank_routes(routes: Iterable[Route]) -> dict[str, int]:
    """Route key -> rank by `demand_pax_month` (1 = the most passengers; ties by key). Routes
    without a figure have no rank."""
    ranked = sorted((r for r in routes if r.demand_pax_month is not None),
                    key=lambda r: (-r.demand_pax_month, r.key))
    return {r.key: i + 1 for i, r in enumerate(ranked)}
