"""Kayak read like a person (D49, the probe's second engine): one round-trip search per trip
through kayak.pt's public URL (nonstop filter, cheapest first), the cheapest nonstop result as
the page shows it. One page load per trip: Kayak's list names the airlines and the price of the
cheapest booking site for that itinerary, not the site itself (its "Selecionar" link goes
straight to the seller), so the seller stays unknown and the comparison reads "Kayak · 44 €".
pt-PT UI (kayak.pt is what a traveller in Portugal sees; euros, Portuguese texts).

The pure parts (URL, the parsers over the page's own texts, the wall detector) are tested
without a browser. `ChromeKayak` drives the probe's one Chrome window (`browser.ChromeSession`).
No stealth, no proxy, no captcha solving: a wall ends this engine's run (`Wall`) and the runner
pauses the engine.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Protocol

from escapadinha.probe.engine import Option, Result, Search, View, Wall, airline_code  # noqa: F401

if TYPE_CHECKING:
    from escapadinha.probe.browser import ChromeSession

ENGINE = "kayak"
SOURCE = "kayak"
LABEL = "Kayak"
HOME = "https://www.kayak.pt/"
CARDS = '[role=group][aria-label^="Resultado"]'    # "Resultado número 1": the numbered results

# The texts the page shows a person (pt-PT), read on 2026-10-26 from this PC.
_PRICE = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?\s?€")
_TIMES = re.compile(r"^(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})(\+\d)?$")
_STOPS = re.compile(r"^\d+\s+escalas?$", re.I)
_SEGMENT = re.compile(r"Segmento (\d+): (?P<airline>.+?), (?P<from>[A-Z]{3}) (?P<dep>\d{1,2}:\d{2})"
                      r" - (?P<to>[A-Z]{3}) (?P<arr>\d{1,2}:\d{2})")


def search_url(origin: str, airport: str, departure: date, ret: date) -> str:
    """The public search URL: airports, dates, one adult, nonstop only, cheapest first."""
    return (f"https://www.kayak.pt/flights/{origin}-{airport}/{departure.isoformat()}/"
            f"{ret.isoformat()}/1adults?sort=price_a&fs=stops=0")


def price_of(text: str) -> float | None:
    """The last euro amount in a card ("44 €", "1.062 €": the pt-PT thousands dot), or None."""
    found = _PRICE.findall(text)
    if not found:
        return None
    try:
        value = float(found[-1].replace(".", ""))
    except ValueError:
        return None
    return value if value > 0 else None


@dataclass(frozen=True)
class Card:
    """One numbered result as the browser hands it over: its text and its aria-labels (the
    segments' labels name the airline and times of each leg)."""

    text: str
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class Itinerary:
    """The cheapest-site price of one round trip, both legs as the page shows them."""

    price: float
    outbound: Result
    inbound: Result
    nonstop: bool


def parse_card(card: Card) -> Itinerary | None:
    """A results card from its text (lines: "6:30 – 8:30", airports, "direto" or "1 escala",
    "2h 00m", the same for the return, the airlines, bag counts, "44 €", the fare, "Selecionar")
    and the segment labels ("Segmento 1: Ryanair, OPO 6:30 - FNC 8:30."). None without a price
    or two legs. Never guesses: an airline the labels don't name stays None."""
    lines = [ln.strip() for ln in card.text.split("\n") if ln.strip()]
    price = price_of(card.text)
    if price is None:
        return None
    legs = [m for m in (_TIMES.match(ln) for ln in lines) if m]
    if len(legs) < 2:
        return None
    segments = {int(m.group(1)): m for m in (_SEGMENT.search(lb) for lb in card.labels) if m}
    nonstop = not any(_STOPS.match(ln) for ln in lines) and \
        sum(ln.lower() == "direto" for ln in lines) >= 2

    def leg(i: int) -> Result:
        seg = segments.get(i + 1)
        return Result(price, seg.group("airline").strip() if seg else None, nonstop,
                      legs[i].group(1), legs[i].group(2), card.text)
    return Itinerary(price, leg(0), leg(1), nonstop)


def cheapest_nonstop(cards: list[Card]) -> tuple[int, Itinerary] | None:
    """Index and parse of the cheapest nonstop card (ties: the first)."""
    best: tuple[int, Itinerary] | None = None
    for i, card in enumerate(cards):
        it = parse_card(card)
        if it is None or not it.nonstop:
            continue
        if best is None or it.price < best[1].price:
            best = (i, it)
    return best


def wall_reason(url: str, title: str, body: str) -> str | None:
    """Why a page is a wall, or None when it is a normal page. Kayak's bot check is a "press
    and hold" button; a block is a plain access-denied page."""
    low = (title + " " + body[:4000]).lower()
    if "press and hold" in low or "pressione e segure" in low or "prima e mantenha" in low \
            or "/security/" in url:
        return "press_and_hold"
    if "captcha" in low or "not a robot" in low or "és um robô" in low or "es un robot" in low:
        return "captcha"
    if "unusual activity" in low or "atividade incomum" in low or "atividade invulgar" in low:
        return "unusual_traffic"
    if "access denied" in low or "error 403" in low or "acesso negado" in low:
        return "blocked"
    return None


class Kayak(Protocol):
    """What the search needs from a browser; `ChromeKayak` does it with Playwright, tests
    fake it."""

    def open(self, url: str) -> View: ...
    def cards(self) -> list[Card]: ...
    def pause(self, seconds: float) -> None: ...


def search(kayak: Kayak, origin: str, airport: str, departure: date, ret: date, *,
           rng: random.Random | None = None) -> Search:
    """One trip: the results list → the cheapest nonstop itinerary. Raises `Wall` at a wall.
    The one option is the card's price with no seller (Kayak's list does not name it)."""
    url = search_url(origin, airport, departure, ret)
    view = kayak.open(url)
    reason = wall_reason(view.url, view.title, view.body)
    if reason:
        raise Wall(reason, view.url[:120])
    cards = kayak.cards()
    if not cards:
        return Search(url, None, None, (), "no_results")
    best = cheapest_nonstop(cards)
    if best is None:
        return Search(url, None, None, (), "no_nonstop")
    it = best[1]
    return Search(url, it.outbound, it.inbound, (Option(None, "metasearch", it.price),), "ok")


class ChromeKayak:
    """Kayak's adapter over the probe's Chrome window (`ChromeSession`). Results stream in for
    a while: `open` waits for the first numbered card, then for the count to settle. Nothing
    is hidden or spoofed; a wall is reported, never worked around."""

    def __init__(self, session: ChromeSession, *, settle_s: float = 5.0, settle_max_s: float = 45.0):
        self._s = session
        self._page = session.page
        self._settle, self._settle_max = settle_s, settle_max_s

    def open(self, url: str) -> View:
        view = self._s.goto(url, wait_for=CARDS, wait_ms=30_000)
        last, stable, t0 = -1, 0, time.monotonic()
        while time.monotonic() - t0 < self._settle_max:
            n = self._page.locator(CARDS).count()
            stable = stable + 1 if n == last else 0
            last = n
            if stable >= 2 or n == 0:
                break
            time.sleep(self._settle)
        return view if last == 0 else self._s.view()

    def cards(self) -> list[Card]:
        items = self._page.locator(CARDS)
        out = []
        for i in range(min(items.count(), 30)):
            item = items.nth(i)
            try:
                text = item.inner_text(timeout=3000)
                labels = tuple(lab for lab in (el.get_attribute("aria-label")
                                               for el in item.locator("[aria-label]").all()) if lab)
            except Exception:
                continue
            out.append(Card(text, labels))
        return out

    def pause(self, seconds: float) -> None:
        self._s.pause(seconds)

    def decline_consent(self) -> str:
        """`probe setup`: open the home page and, if the cookie dialog shows, choose the most
        privacy-preserving answer ("Recusar tudo"). Returns what happened, for the terminal."""
        self._page.goto(HOME, wait_until="domcontentloaded", timeout=self._s.timeout_ms)
        time.sleep(4)
        for label in ("Recusar tudo", "Rejeitar tudo", "Reject all", "Decline all"):
            btn = self._page.get_by_role("button", name=re.compile(label, re.I))
            try:
                if btn.count():
                    btn.first.click(timeout=10_000)
                    time.sleep(2)
                    return f"Kayak: consent declined ({label})"
            except Exception:
                continue
        return "Kayak: no consent dialog (already answered, or none shown): the profile is ready"
