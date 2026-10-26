"""The one Chrome window the probe uses (D48, D49): Playwright over the PC's own Chrome
(`channel="chrome"`), a persistent profile of the probe's own, headed by default. Every engine's
adapter (`google_flights.ChromeFlights`, `kayak.ChromeKayak`) drives this same page in turn:
one search at a time, never two browsers. Nothing is hidden or spoofed; a wall is reported by the
engine, never worked around."""

from __future__ import annotations

import time
from pathlib import Path

from escapadinha.probe.engine import View


class ChromeSession:
    def __init__(self, profile_dir: Path, *, headless: bool = False, timeout_s: int = 60,
                 locale: str = "pt-PT"):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._ctx = self._pw.chromium.launch_persistent_context(
            str(profile_dir), channel="chrome", headless=headless,
            viewport={"width": 1280, "height": 900}, locale=locale,
            timezone_id="Europe/Lisbon")
        self.page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self.timeout_ms = timeout_s * 1000

    def close(self) -> None:
        try:
            self._ctx.close()
        finally:
            self._pw.stop()

    def view(self) -> View:
        body = ""
        try:
            body = self.page.inner_text("body", timeout=5000)
        except Exception:
            pass
        return View(self.page.url, self.page.title(), body)

    def goto(self, url: str, *, wait_for: str | None = None, wait_ms: int = 20_000) -> View:
        """Open a URL; wait for `wait_for` (a selector) a while, then read the page whatever it
        shows (no results, or a wall: the engine decides)."""
        self.page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        if wait_for:
            try:
                self.page.wait_for_selector(wait_for, timeout=wait_ms)
            except Exception:
                pass
        return self.view()

    def pause(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))
