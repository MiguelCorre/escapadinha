"""Travelpayouts sources for route discovery (network only; the logic is in discovery.py).

- Static catalogues, public, no token: `data/routes.json` (airline routes with `transfers`),
  `data/airports.json` (airport -> city, country) and `data/pt/cities.json` (city names in
  Portuguese, `name_translations.en` in English). The routes catalogue is not kept current
  (it still lists airlines that stopped flying years ago), hence the two supplements.
- `v1/city-directions` (token): the popular directions from a city, ~30 per origin.
- `aviasales/v3/prices_for_dates` with an origin and no destination, `direct=true` (token):
  nonstop fares travellers found recently, per departure month. Only the destinations are
  used; these prices are never stored (the collector stores prices, per route).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import httpx

from escapadinha.collector.travelpayouts import API_URL as PRICES_URL
from escapadinha.collector.travelpayouts import TravelpayoutsError

DATA_URL = "https://api.travelpayouts.com/data"
ROUTES_URL = f"{DATA_URL}/routes.json"
AIRPORTS_URL = f"{DATA_URL}/airports.json"
CITIES_PT_URL = f"{DATA_URL}/pt/cities.json"
DIRECTIONS_URL = "https://api.travelpayouts.com/v1/city-directions"


@dataclass(frozen=True)
class CataloguePayloads:
    routes: list[dict]
    airports: list[dict]
    cities_pt: list[dict]


class TravelpayoutsCatalogue:
    def __init__(self, token: str, *, currency: str = "eur", market: str | None = None,
                 client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=120, follow_redirects=True)
        self._token = token
        self._currency = currency.lower()
        self._market = market

    def static(self) -> CataloguePayloads:
        """The three public catalogues (routes.json is ~14 MB, served gzipped)."""
        return CataloguePayloads(self._json(ROUTES_URL), self._json(AIRPORTS_URL),
                                 self._json(CITIES_PT_URL))

    def popular_directions(self, origin: str) -> dict:
        return self._json(DIRECTIONS_URL, {"origin": origin, "currency": self._currency},
                          token=True)

    def recent_direct(self, origin: str, month: date) -> dict:
        params = {"origin": origin, "departure_at": month.strftime("%Y-%m"), "one_way": "true",
                  "direct": "true", "currency": self._currency, "sorting": "price",
                  "unique": "true", "limit": 1000}
        if self._market:
            params["market"] = self._market
        return self._json(PRICES_URL, params, token=True)

    def _json(self, url: str, params: dict | None = None, token: bool = False):
        if token and not self._token:
            raise TravelpayoutsError("TRAVELPAYOUTS_TOKEN is not set (see .env.example)")
        headers = {"X-Access-Token": self._token} if token else {}
        response = self._client.get(url, params=params, headers=headers)
        if response.status_code != 200:
            raise TravelpayoutsError(f"{url}: HTTP {response.status_code}: {response.text[:200]}")
        return response.json()
