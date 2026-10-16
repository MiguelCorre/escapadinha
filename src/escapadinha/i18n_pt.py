"""pt-PT formatting without relying on the OS locale (Windows locales are unreliable)."""

from __future__ import annotations

import unicodedata
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
}
REMOTE_AIRPORTS = {"BVA", "BGY", "GRO", "REU", "EIN", "CRL", "NYO", "TSF", "HHN", "WMI", "TRF", "SEN"}


def airport_label(code: str | None) -> str | None:
    """'Beauvais (BVA)'; unknown codes are shown as the bare code."""
    if not code:
        return None
    name = AIRPORTS.get(code.upper())
    return f"{name} ({code.upper()})" if name else code.upper()


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


def number(value: float) -> str:
    """24 -> '24', 1.5 -> '1,5' (pt-PT: comma decimals, no trailing zeros)."""
    return f"{value:g}".replace(".", ",")


def count(n: int, singular: str, plural: str) -> str:
    """(1, 'decisão pendente', 'decisões pendentes') -> '1 decisão pendente'; 0 and 2+ plural."""
    return f"{n} {singular if n == 1 else plural}"


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
