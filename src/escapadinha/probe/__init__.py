"""The browser probe on Miguel's own PC (D48, phase 2 of D47; D49 adds Kayak): the metasearch
pages' prices for the trips the pipeline asks about, read like a person comparing fares, written
to the object store as comparison sources (`google_flights`, `kayak`). Pure parts (`wanted`, the
engines' parsers, `results`) are tested without a browser; `runner` drives a `Session` whose
engines (`engine.Bound` over `google_flights.ChromeFlights` / `kayak.ChromeKayak`) share one
Chrome window (`browser.ChromeSession`), one search at a time."""

from escapadinha.probe import google_flights, kayak

ENGINES = {google_flights.ENGINE: google_flights, kayak.ENGINE: kayak}   # name → module
SOURCES = frozenset(m.SOURCE for m in ENGINES.values())                   # the comparison sources
