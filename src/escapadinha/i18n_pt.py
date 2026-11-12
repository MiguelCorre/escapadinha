"""pt-PT formatting without relying on the OS locale (Windows locales are unreliable)."""

from __future__ import annotations

import unicodedata
from collections.abc import Collection
from datetime import date, datetime
from zoneinfo import ZoneInfo

LISBON = ZoneInfo("Europe/Lisbon")

MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro"]
MONTHS_SHORT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
WEEKDAYS_SHORT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

AIRLINES = {
    "TP": "TAP Air Portugal", "FR": "Ryanair", "U2": "easyJet", "EC": "easyJet",
    "VY": "Vueling", "W6": "Wizz Air", "W4": "Wizz Air", "HV": "Transavia", "TO": "Transavia",
    "BA": "British Airways", "IB": "Iberia", "UX": "Air Europa", "AF": "Air France",
    "KL": "KLM", "LH": "Lufthansa", "LX": "Swiss", "AZ": "ITA Airways", "EW": "Eurowings",
    "SN": "Brussels Airlines", "OS": "Austrian", "EI": "Aer Lingus", "FI": "Icelandair",
    "S4": "Azores Airlines", "SP": "SATA Air Açores", "NI": "Portugália", "BT": "airBaltic",
    "DY": "Norwegian", "D8": "Norwegian", "V7": "Volotea", "LS": "Jet2",
    # D66: every airline the site met on 2026-11-12, each code checked against the provider's
    # catalogue (api.travelpayouts.com/data/airlines.json), named as the airline sells itself.
    "2L": "Helvetic Airways", "4Y": "Discover Airlines", "5F": "FlyOne", "A0": "BA Euroflyer",
    "A3": "Aegean Airlines", "AA": "American Airlines", "AC": "Air Canada", "AD": "Azul",
    "AH": "Air Algérie", "AL": "Alpavia", "AT": "Royal Air Maroc", "AY": "Finnair",
    "DE": "Condor", "DI": "Marabu", "DS": "easyJet", "DT": "TAAG", "E4": "Enter Air",
    "ET": "Ethiopian Airlines", "EY": "Etihad Airways", "G3": "GOL", "GQ": "Sky Express",
    "JJ": "LATAM", "JU": "Air Serbia", "KE": "Korean Air", "LA": "LATAM", "LG": "Luxair",
    "LO": "LOT", "LW": "Lauda Europe", "MW": "Malta Air", "NT": "Binter", "PC": "Pegasus",
    "QR": "Qatar Airways", "QS": "Smartwings", "RK": "Ryanair", "RR": "Buzz",
    "SA": "South African Airways", "SK": "SAS", "TS": "Air Transat", "UA": "United Airlines",
    "VR": "Cabo Verde Airlines", "VS": "Virgin Atlantic", "W9": "Wizz Air", "WK": "Edelweiss",
    "X3": "TUI fly", "X5": "Air Europa", "YU": "EuroAtlantic Airways", "YW": "Air Nostrum",
}


# Arrival airport names. REMOTE airports are far from the city they are sold under
# (e.g. Paris-Beauvais is ~80 km from Paris); deals there name the airport in the headline.
AIRPORTS = {
    "LHR": "Heathrow", "LGW": "Gatwick", "STN": "Stansted", "LTN": "Luton", "LCY": "London City",
    "SEN": "Southend", "CDG": "Charles de Gaulle", "ORY": "Orly", "BVA": "Beauvais",
    "FCO": "Fiumicino", "CIA": "Ciampino", "BCN": "El Prat", "GRO": "Girona", "REU": "Reus",
    "AMS": "Schiphol", "EIN": "Eindhoven", "MXP": "Malpensa", "LIN": "Linate", "BGY": "Bérgamo",
    "BER": "Brandenburg", "CRL": "Charleroi", "BRU": "Bruxelas", "NYO": "Skavsta",
    "TSF": "Treviso", "HHN": "Hahn", "WMI": "Modlin", "TRF": "Torp",
    # D66: every airport of a destination with two or more (routes on 2026-11-12), each code
    # checked against the provider's catalogue (api.travelpayouts.com/data/airports.json).
    "SXF": "Schönefeld", "TXL": "Tegel", "DUS": "Düsseldorf", "NRN": "Weeze",
    "FRA": "Frankfurt", "GLA": "Glasgow", "PIK": "Prestwick", "OSL": "Gardermoen",
    "RYG": "Rygge", "KIV": "Chisinau", "RMO": "Chisinau", "GRU": "Guarulhos",
    "VCP": "Viracopos", "ARN": "Arlanda", "TFN": "Tenerife Norte", "TFS": "Tenerife Sul",
    "VCE": "Marco Polo", "WAW": "Chopin",
}
REMOTE_AIRPORTS = {"BVA", "BGY", "GRO", "REU", "EIN", "CRL", "NYO", "TSF", "HHN", "WMI", "TRF", "SEN",
                   "NRN", "PIK", "RYG", "VCP"}


def airport_label(code: str | None, *, sole_of: str | None = None) -> str | None:
    """'Beauvais (BVA)'. `sole_of`: the city the airport is the only one of (its route's single
    arrival airport, D66), whose name stands in when the map has none: 'Praga (PRG)'. Any
    other unknown code is shown as the bare code. The site's twin is `place` in promotion.ts."""
    if not code:
        return None
    name = AIRPORTS.get(code.upper()) or sole_of
    return f"{name} ({code.upper()})" if name else code.upper()


def sole_city(code: str | None, route_airports: Collection[str], city: str) -> str | None:
    """`city` when `code` is the route's only arrival airport, else None (D66)."""
    if code and {a.upper() for a in route_airports} == {code.upper()}:
        return city
    return None


def eur(amount: float) -> str:
    """49 -> '49 €', 49.5 -> '49,50 €', 1299 -> '1299 €' (pt-PT: comma decimals)."""
    if float(amount).is_integer():
        return f"{int(amount)} €"
    return f"{amount:.2f}".replace(".", ",") + " €"


def eur_compact(amount: float) -> str:
    """Slide headline style: '49€'."""
    return eur(amount).replace(" €", "€")


def day_month(d: date) -> str:
    return f"{d.day} de {MONTHS[d.month - 1]}"


def date_range(start: date, end: date) -> str:
    """'6 a 9 de novembro', '27 de novembro a 4 de dezembro', crosses years with the year."""
    if start.year != end.year:
        return f"{day_month(start)} de {start.year} a {day_month(end)} de {end.year}"
    if start.month == end.month:
        return f"{start.day} a {day_month(end)}"
    return f"{day_month(start)} a {day_month(end)}"


def short_date(d: date) -> str:
    """'sex, 6 nov'."""
    return f"{WEEKDAYS_SHORT[d.weekday()]}, {d.day} {MONTHS_SHORT[d.month - 1]}"


def numeric_date(d: date) -> str:
    """'07/10/2026'."""
    return f"{d:%d/%m/%Y}"


def lisbon_timestamp(dt: datetime) -> str:
    """'12/10/2026 às 10:14' in Lisbon local time."""
    local = dt.astimezone(LISBON)
    return f"{local:%d/%m/%Y} às {local:%H:%M}"


def time_ago(dt: datetime, now: datetime) -> str:
    """'há 20 min', 'há 1 h 05', 'há 3 dias' (the same rule as the site's `format.timeAgo`);
    never negative."""
    minutes = max(0, int((now - dt).total_seconds() // 60))
    if minutes < 60:
        return f"há {minutes} min"
    hours = minutes // 60
    if hours < 48:
        return f"há {hours} h {minutes % 60:02d}"
    return f"há {hours // 24} dias"


def number(value: float) -> str:
    """24 -> '24', 1.5 -> '1,5' (pt-PT: comma decimals, no trailing zeros)."""
    return f"{value:g}".replace(".", ",")


def integer(n: int) -> str:
    """141591 -> '141 591' (pt-PT groups thousands with a space; never used for prices)."""
    return f"{n:,}".replace(",", " ")


def count(n: int, singular: str, plural: str) -> str:
    """(1, 'decisão pendente', 'decisões pendentes') -> '1 decisão pendente'; 0 and 2+ plural."""
    return f"{n} {singular if n == 1 else plural}"


def survival_line(source_label: str, confidence_pt: str | None, gone_pct: int, days: int,
                  n: int) -> str:
    """The review pages' line (#79, D56): 'Destas promoções (Ryanair, confiança média), 83%
    desapareceram em 24 h (últimos 14 dias, 342)'; the Function's `format.survivalText` is the
    same rule. A rate and a count, never a price."""
    group = f"{source_label}, confiança {confidence_pt}" if confidence_pt else source_label
    return (f"Destas promoções ({group}), {gone_pct}% desapareceram em 24 h "
            f"(últimos {days} dias, {integer(n)})")


def probe_contradiction(engines: list[str], searched_at: datetime) -> str:
    """Why the probe took a cache promotion down (D65): 'o Google Flights e o Kayak mostraram
    esta viagem bem mais cara (pesquisa de 11/11 às 14:39)', the newest deciding search in
    Lisbon time. Never a euro amount: the reason is exported to the expired promotion's page,
    where no price may appear without its observation; the probe's prices show only where each
    sits on its own (`also_seen`: the review pages, a live promotion's page)."""
    named = [f"o {name}" for name in engines]
    names = named[0] if len(named) == 1 else f"{', '.join(named[:-1])} e {named[-1]}"
    verb = "mostrou" if len(engines) == 1 else "mostraram"
    local = searched_at.astimezone(LISBON)
    return f"{names} {verb} esta viagem bem mais cara (pesquisa de {local:%d/%m} às {local:%H:%M})"


def nights(n: int) -> str:
    return count(n, "noite", "noites")


# The baggage line (D43): printed only when the GraphQL match said so; unknown prints nothing.
BAGGAGE = {True: "com mala de porão incluída", False: "só bagagem de mão"}


def baggage_line(with_baggage: bool | None) -> str | None:
    """True -> 'com mala de porão incluída', False -> 'só bagagem de mão', None -> None."""
    return None if with_baggage is None else BAGGAGE[with_baggage]


def airline_name(code: str | None) -> str | None:
    if not code:
        return None
    return AIRLINES.get(code.upper(), code.upper())


def hashtag(text: str) -> str:
    """'Amesterdão' -> '#amesterdao'."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "#" + "".join(ch for ch in ascii_text.lower() if ch.isalnum())


ROUTE_KIND = {"europe": "Europa", "long_haul": "Longo curso", "domestic": "Portugal"}
ROUTE_STATUS = {"active": "ativa", "dormant": "adormecida"}


def nights_range(lo: int, hi: int) -> str:
    """(2, 10) -> '2–10 noites'."""
    return nights(lo) if lo == hi else f"{lo}–{hi} noites"


def stops_rule(direct_only: bool, max_transfers: int | None) -> str:
    """The route's stop limit per direction, in words."""
    if direct_only or max_transfers == 0:
        return "só diretos"
    if max_transfers is None:
        return "qualquer"
    return "até 1 escala" if max_transfers == 1 else f"até {max_transfers} escalas"
