"""What every probe engine shares (D48, D49): the shapes a search produces (`Result`, `Option`,
`Search`), the browser's `View`, the `Wall` that ends a run, the carrier-name lookup, and the
`Engine` protocol the runner drives. An engine module (`google_flights`, `kayak`) names itself
(`ENGINE`, `SOURCE`, `LABEL`), parses its own page's texts, and exposes `search(browser, …)`;
`Bound` ties a module to the browser adapter the runner opened for it. Pure: no I/O here."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import date
from types import ModuleType
from typing import Any, Protocol

from escapadinha import i18n_pt

_NAME_TO_CODE = {name.lower(): code for code, name in reversed(list(i18n_pt.AIRLINES.items()))}
_PRICE = re.compile(r"€\s?([\d.,]+)")


def price_of(text: str) -> float | None:
    """The first "€65" / "€1,062" in a text (Google Flights' English UI), or None. Never
    guesses; Kayak's pt-PT amounts have their own parser (`kayak.price_of`)."""
    m = _PRICE.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def airline_code(name: str | None) -> str | None:
    """IATA code for a carrier name a page shows, from the pt-PT airline table; None when
    unknown (never guessed)."""
    return _NAME_TO_CODE.get(name.strip().lower()) if name else None


@dataclass(frozen=True)
class Result:
    """One row of a results list, as the page shows it."""

    price: float                    # the round-trip total shown on the row, euros
    airline: str | None             # the row's carrier name ("Ryanair"), operating carrier dropped
    nonstop: bool
    departs: str | None             # "3:10 PM" / "06:20", as shown
    arrives: str | None
    text: str                       # the row's text, kept for the record


@dataclass(frozen=True)
class Option:
    seller: str | None              # "Ryanair", "eDreams"; None when the page names no seller
    kind: str                       # airline | online travel agency | metasearch
    price: float


class Wall(RuntimeError):
    """The site asked for proof of humanity or stopped serving us: the run ends here for this
    engine, which pauses. `reason`: consent | unusual_traffic | captcha | press_and_hold |
    blocked."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass(frozen=True)
class View:
    url: str
    title: str
    body: str


@dataclass(frozen=True)
class Search:
    """What one trip's search found, as the record keeps it."""

    url: str
    outbound: Result | None
    inbound: Result | None
    options: tuple[Option, ...]
    outcome: str                    # ok | no_results | no_nonstop | no_return | no_options

    @property
    def price(self) -> float | None:
        return self.inbound.price if self.inbound else None


class Engine(Protocol):
    """One engine ready to search: what the runner needs per trip."""

    @property
    def name(self) -> str: ...
    def search(self, origin: str, airport: str, departure: date, ret: date, *,
               rng: random.Random | None = None) -> Search: ...
    def pause(self, seconds: float) -> None: ...


@dataclass(frozen=True)
class Bound:
    """An engine module (`search`, `ENGINE`) bound to the browser adapter it drives."""

    module: ModuleType
    browser: Any

    @property
    def name(self) -> str:
        return self.module.ENGINE

    def search(self, origin: str, airport: str, departure: date, ret: date, *,
               rng: random.Random | None = None) -> Search:
        return self.module.search(self.browser, origin, airport, departure, ret, rng=rng)

    def pause(self, seconds: float) -> None:
        self.browser.pause(seconds)


class Session(Protocol):
    """What `probe run` opens once: the engines, in the order they search each trip (Google
    Flights then Kayak, never two browsers at once), and one `close()` for the browser."""

    @property
    def engines(self) -> list[Engine]: ...
    def close(self) -> None: ...
