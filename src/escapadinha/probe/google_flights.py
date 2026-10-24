"""Google Flights read like a person (D48): one round-trip search per trip through the public
`q=` URL, the cheapest nonstop outbound, the cheapest return, then the booking options of that
itinerary (which sellers offer it, at what price). English UI (`hl=en`) so the texts parsed here
are stable; euros (`curr=EUR`), Portugal (`gl=PT`).

The pure parts (URL, the parsers over the page's own texts, the wall detector) are tested
without a browser. `ChromeFlights` is the only Playwright code: the PC's own Chrome, a profile
of the probe's own, headed by default. No stealth, no proxy, no captcha solving: a wall ends
the run (`Wall`), and the runner pauses the probe.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from escapadinha import i18n_pt

ENGINE = "google_flights"
SOURCE = "google_flights"
LABEL = "Google Flights"
HOME = "https://www.google.com/travel/flights?hl=en&gl=PT&curr=EUR"

# The texts the page shows a person. English UI only (the URL asks for it).
_PRICE = re.compile(r"€\s?([\d.,]+)")
_DURATION = re.compile(r"^\d+\s*hr(\s*\d+\s*min)?$|^\d+\s*min$")
_TIME = re.compile(r"^\d{1,2}:\d{2}\s*[AP]M", re.I)
_BOOK = re.compile(r"book with (?P<seller>.+?) (?P<kind>airline|online travel agency|travel agency)"
                   r" for (?P<price>[\d.,]+) euros", re.I)
_NAME_TO_CODE = {name.lower(): code for code, name in reversed(list(i18n_pt.AIRLINES.items()))}


def search_url(origin: str, airport: str, departure: date, ret: date) -> str:
    """The public search URL: a natural-language query Google Flights understands."""
    q = (f"Flights from {origin} to {airport} on {departure.isoformat()} returning "
         f"{ret.isoformat()} nonstop one adult economy")
    return f"https://www.google.com/travel/flights?q={quote(q)}&hl=en&gl=PT&curr=EUR"


def price_of(text: str) -> float | None:
    m = _PRICE.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


@dataclass(frozen=True)
class Result:
    """One row of a results list, as the page shows it."""

    price: float                    # the round-trip total shown on the row, euros
    airline: str | None             # the row's carrier name ("Ryanair"), operating carrier dropped
    nonstop: bool
    departs: str | None             # "3:10 PM", as shown
    arrives: str | None
    text: str                       # the row's text, kept for the record


def parse_result(text: str) -> Result | None:
    """A results row from its text (lines: times, airline, duration, airports, stops, emissions,
    price, "round trip"). None without a price. Never guesses: unknown fields stay None."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    price = price_of(text)
    if price is None:
        return None
    times = [ln for ln in lines if _TIME.match(ln)]
    airline = None
    for i, ln in enumerate(lines):
        if _DURATION.match(ln) and i > 0:
            airline = re.split(r"Operated by", lines[i - 1])[0].strip() or None
            break
    nonstop = any(ln.lower() == "nonstop" for ln in lines)
    return Result(price, airline, nonstop, times[0] if times else None,
                  times[1] if len(times) > 1 else None, text)


def cheapest_nonstop(rows: list[str]) -> tuple[int, Result] | None:
    """Index and parse of the cheapest nonstop row (ties: the first)."""
    best: tuple[int, Result] | None = None
    for i, text in enumerate(rows):
        r = parse_result(text)
        if r is None or not r.nonstop:
            continue
        if best is None or r.price < best[1].price:
            best = (i, r)
    return best


@dataclass(frozen=True)
class Option:
    seller: str                     # "Ryanair", "eDreams"
    kind: str                       # airline | online travel agency
    price: float


def parse_booking(label: str) -> Option | None:
    """"Continue to book with Ryanair airline for 65 euros" → Option."""
    m = _BOOK.search(label)
    if not m:
        return None
    try:
        price = float(m.group("price").replace(",", ""))
    except ValueError:
        return None
    if price <= 0:
        return None
    return Option(m.group("seller").strip(), m.group("kind").lower(), price)


def airline_code(name: str | None) -> str | None:
    """IATA code for a carrier name the page shows, from the pt-PT airline table; None when
    unknown (never guessed)."""
    return _NAME_TO_CODE.get(name.strip().lower()) if name else None


class Wall(RuntimeError):
    """The site asked for proof of humanity or stopped serving us: the run ends here, the
    probe pauses. `reason`: consent | unusual_traffic | captcha | blocked."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def wall_reason(url: str, title: str, body: str) -> str | None:
    """Why a page is a wall, or None when it is a normal page."""
    low = (title + " " + body[:4000]).lower()
    if "consent.google" in url:
        return "consent"
    if "/sorry/" in url or "unusual traffic" in low:
        return "unusual_traffic"
    if "recaptcha" in low or "i'm not a robot" in low or "not a robot" in low:
        return "captcha"
    if "access denied" in low or "error 403" in low:
        return "blocked"
    return None


@dataclass(frozen=True)
class View:
    url: str
    title: str
    body: str


class Flights(Protocol):
    """What the search needs from a browser; `ChromeFlights` does it with Playwright, tests
    fake it."""

    def open(self, url: str) -> View: ...
    def rows(self) -> list[str]: ...
    def click_row(self, index: int) -> View: ...
    def expand_options(self) -> None: ...
    def booking_labels(self) -> list[str]: ...
    def pause(self, seconds: float) -> None: ...


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


def _check(view: View) -> View:
    reason = wall_reason(view.url, view.title, view.body)
    if reason:
        raise Wall(reason, view.url[:120])
    return view


def search(flights: Flights, origin: str, airport: str, departure: date, ret: date, *,
           step_pause: tuple[float, float] = (2.0, 5.0),
           rng: random.Random | None = None) -> Search:
    """One trip: results → cheapest nonstop outbound → cheapest return → booking options.
    Raises `Wall` at the first wall. Pauses a few seconds between steps like a reader would."""
    rng = rng or random.Random()
    url = search_url(origin, airport, departure, ret)
    _check(flights.open(url))
    rows = flights.rows()
    if not rows:
        return Search(url, None, None, (), "no_results")
    best = cheapest_nonstop(rows)
    if best is None:
        return Search(url, None, None, (), "no_nonstop")
    flights.pause(rng.uniform(*step_pause))
    _check(flights.click_row(best[0]))
    back = cheapest_nonstop(flights.rows())
    if back is None:
        return Search(url, best[1], None, (), "no_return")
    flights.pause(rng.uniform(*step_pause))
    _check(flights.click_row(back[0]))
    flights.pause(rng.uniform(*step_pause))
    flights.expand_options()
    options = tuple(o for o in (parse_booking(lbl) for lbl in flights.booking_labels()) if o)
    return Search(url, best[1], back[1], options, "ok" if options else "no_options")


class ChromeFlights:
    """Playwright over the PC's own Chrome (`channel="chrome"`), a persistent profile of the
    probe's own, headed by default: what Google Flights expects from a person at home. Nothing
    is hidden or spoofed; a wall is reported, never worked around."""

    ROWS = "[role=list] li"

    def __init__(self, profile_dir: Path, *, headless: bool = False, timeout_s: int = 60):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._ctx = self._pw.chromium.launch_persistent_context(
            str(profile_dir), channel="chrome", headless=headless,
            viewport={"width": 1280, "height": 900}, locale="en-GB",
            timezone_id="Europe/Lisbon")
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._timeout_ms = timeout_s * 1000

    def close(self) -> None:
        try:
            self._ctx.close()
        finally:
            self._pw.stop()

    def _view(self) -> View:
        body = ""
        try:
            body = self._page.inner_text("body", timeout=5000)
        except Exception:
            pass
        return View(self._page.url, self._page.title(), body)

    def open(self, url: str) -> View:
        self._page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
        try:
            self._page.wait_for_selector(self.ROWS, timeout=20_000)
        except Exception:
            pass                        # no results (or a wall): the caller reads the view
        return self._view()

    def rows(self) -> list[str]:
        items = self._page.locator(self.ROWS)
        out = []
        for i in range(min(items.count(), 40)):
            try:
                out.append(items.nth(i).inner_text(timeout=3000))
            except Exception:
                out.append("")
        return out

    def click_row(self, index: int) -> View:
        self._page.locator(self.ROWS).nth(index).click(timeout=10_000)
        try:
            self._page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        time.sleep(2)
        return self._view()

    def expand_options(self) -> None:
        more = self._page.get_by_role("button", name=re.compile(r"view (more )?options", re.I))
        try:
            if more.count():
                more.first.click(timeout=5000)
                time.sleep(2)
        except Exception:
            pass

    def booking_labels(self) -> list[str]:
        out = []
        links = self._page.locator("a[aria-label], button[aria-label]")
        for i in range(links.count()):
            try:
                lab = links.nth(i).get_attribute("aria-label") or ""
            except Exception:
                continue
            if "book with" in lab.lower():
                out.append(lab)
        return out

    def pause(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))

    def decline_consent(self) -> str:
        """`probe setup`: open the home page and, if the consent page shows, choose the most
        privacy-preserving answer (reject all). Returns what happened, for the terminal."""
        self._page.goto(HOME, wait_until="domcontentloaded", timeout=self._timeout_ms)
        time.sleep(3)
        if "consent.google" not in self._page.url:
            return "no consent page: the profile is ready"
        for label in ("Reject all", "Rejeitar tudo", "Recusar tudo"):
            btn = self._page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=10_000)
                time.sleep(3)
                return f"consent declined ({label})" if "consent.google" not in self._page.url \
                    else "consent page still shown: answer it in the window, then close it"
        return "consent page without a reject button: answer it in the window, then close it"
