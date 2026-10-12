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


def nights(n: int) -> str:
    return "1 noite" if n == 1 else f"{n} noites"


def airline_name(code: str | None) -> str | None:
    if not code:
        return None
    return AIRLINES.get(code.upper(), code.upper())


def hashtag(text: str) -> str:
    """'Amesterdão' -> '#amesterdao'."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "#" + "".join(ch for ch in ascii_text.lower() if ch.isalnum())
