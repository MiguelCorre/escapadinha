"""The browser probe on Miguel's own PC (D48, phase 2 of D47): Google Flights' prices for the
trips the pipeline asks about, read like a person comparing fares, written to the object store
as a comparison source (`google_flights`). Pure parts (`wanted`, `google_flights` parsers,
`results`) are tested without a browser; `runner` drives a `Flights` implementation
(`ChromeFlights` is Playwright over the PC's own Chrome)."""
