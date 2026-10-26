"""Google Flights read like a person (D48): one round-trip search per trip through the public
`q=` URL, the cheapest nonstop outbound, the cheapest return, then the booking options of that
itinerary (which sellers offer it, at what price). English UI (`hl=en`) so the texts parsed here
are stable; euros (`curr=EUR`), Portugal (`gl=PT`).

The pure parts (URL, the parsers over the page's own texts, the wall detector) are tested
without a browser. `ChromeFlights` drives the probe's one Chrome window (`browser.ChromeSession`:
the PC's own Chrome, a profile of the probe's own, headed by default). No stealth, no proxy, no
captcha solving: a wall ends this engine's run (`Wall`), and the runner pauses the engine (D49).
"""

from __future__ import annotations

import random
import re
import time
from datetime import date
from typing import TYPE_CHECKING, Protocol
from urllib.parse import quote

from escapadinha.probe.engine import (  # noqa: F401  (re-exported: the engines share them)
    Option, Result, Search, View, Wall, airline_code, price_of,
)

if TYPE_CHECKING:
    from escapadinha.probe.browser import ChromeSession

ENGINE = "google_flights"
SOURCE = "google_flights"
LABEL = "Google Flights"
HOME = "https://www.google.com/travel/flights?hl=en&gl=PT&curr=EUR"

# The texts the page shows a person. English UI only (the URL asks for it).
_DURATION = re.compile(r"^\d+\s*hr(\s*\d+\s*min)?$|^\d+\s*min$")
_TIME = re.compile(r"^\d{1,2}:\d{2}\s*[AP]M", re.I)
_BOOK = re.compile(r"book with (?P<seller>.+?) (?P<kind>airline|online travel agency|travel agency)"
                   r" for (?P<price>[\d.,]+) euros", re.I)


def search_url(origin: str, airport: str, departure: date, ret: date) -> str:
    """The public search URL: a natural-language query Google Flights understands."""
    q = (f"Flights from {origin} to {airport} on {departure.isoformat()} returning "
         f"{ret.isoformat()} nonstop one adult economy")
    return f"https://www.google.com/travel/flights?q={quote(q)}&hl=en&gl=PT&curr=EUR"


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


class Flights(Protocol):
    """What the search needs from a browser; `ChromeFlights` does it with Playwright, tests
    fake it."""

    def open(self, url: str) -> View: ...
    def rows(self) -> list[str]: ...
    def click_row(self, index: int) -> View: ...
    def expand_options(self) -> None: ...
    def booking_labels(self) -> list[str]: ...
    def pause(self, seconds: float) -> None: ...


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
    if not any(parse_result(r) for r in rows):     # the page's other lists (passengers) are not results
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
    """Google Flights' adapter over the probe's Chrome window (`ChromeSession`): what the search
    needs, read from the page as a person sees it. Nothing is hidden or spoofed; a wall is
    reported, never worked around."""

    ROWS = "[role=list] li"
    RESULTS_WAIT_S = 30.0           # results stream in after the page: wait for a priced row
    STEP_WAIT_S = 20.0              # the return list, after choosing the outbound
    LABELS_WAIT_S = 15.0            # the booking options, after choosing the return

    def __init__(self, session: ChromeSession):
        self._s = session
        self._page = session.page

    def _settle(self, max_s: float) -> None:
        """Wait until a row parses (a price on it) or `max_s` passes: `[role=list] li` also
        matches the passenger picker, which is there before any result (the 2026-10-26 misses:
        18 of 50 searches read the list too early and saw no priced row)."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < max_s:
            if any(parse_result(r) for r in self.rows()):
                return
            time.sleep(1.0)

    def open(self, url: str) -> View:
        self._s.goto(url, wait_for=self.ROWS)
        self._settle(self.RESULTS_WAIT_S)
        return self._s.view()

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
        self._settle(self.STEP_WAIT_S)
        return self._s.view()

    def expand_options(self) -> None:
        more = self._page.get_by_role("button", name=re.compile(r"view (more )?options", re.I))
        try:
            if more.count():
                more.first.click(timeout=5000)
                time.sleep(2)
        except Exception:
            pass

    def booking_labels(self) -> list[str]:
        t0 = time.monotonic()
        while True:
            out = []
            links = self._page.locator("a[aria-label], button[aria-label]")
            for i in range(links.count()):
                try:
                    lab = links.nth(i).get_attribute("aria-label") or ""
                except Exception:
                    continue
                if "book with" in lab.lower():
                    out.append(lab)
            if out or time.monotonic() - t0 >= self.LABELS_WAIT_S:
                return out
            time.sleep(1.0)

    def pause(self, seconds: float) -> None:
        self._s.pause(seconds)

    def decline_consent(self) -> str:
        """`probe setup`: open the home page and, if the consent page shows, choose the most
        privacy-preserving answer (reject all). Returns what happened, for the terminal."""
        self._page.goto(HOME, wait_until="domcontentloaded", timeout=self._s.timeout_ms)
        time.sleep(3)
        if "consent.google" not in self._page.url:
            return "Google Flights: no consent page: the profile is ready"
        for label in ("Reject all", "Rejeitar tudo", "Recusar tudo"):
            btn = self._page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=10_000)
                time.sleep(3)
                return f"Google Flights: consent declined ({label})" if "consent.google" not in self._page.url \
                    else "Google Flights: consent page still shown: answer it in the window, then close it"
        return "Google Flights: consent page without a reject button: answer it in the window, then close it"
