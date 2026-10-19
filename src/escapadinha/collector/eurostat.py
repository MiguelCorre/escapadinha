"""Eurostat's dissemination API for `avia_par_pt` (route demand, D45): one GET per discovery, no
key, archived to the object store as it came. The parsing lives in `demand.py` (pure).

Reuse of Eurostat data is authorised with the source acknowledged (the site's "Como funciona"
page carries the line). The monthly series lags about 22 months, so the request asks for
`demand.since_months` (36) of history to be sure of twelve months with values.
"""

from __future__ import annotations

import gzip
import json
from datetime import date, datetime

import httpx

from escapadinha.demand import DATASET
from escapadinha.storage.objects import ObjectStore

URL = f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{DATASET}"
# Passengers carried (both directions), per airport pair, monthly.
PARAMS = {"format": "JSON", "lang": "EN", "unit": "PAS", "tra_meas": "PAS_CRD", "freq": "M"}


class EurostatError(Exception):
    """The API answered with an error, or with something that is not the dataset."""


def since_month(today: date, months: int) -> str:
    """`sinceTimePeriod`: the month `months` months before `today`'s, as "YYYY-MM"."""
    index = today.year * 12 + (today.month - 1) - months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def params(since: str) -> dict[str, str]:
    return {**PARAMS, "sinceTimePeriod": since}


class EurostatClient:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=120, follow_redirects=True)

    def passengers(self, since: str) -> dict:
        """The dataset from `since` on, as served (JSON-stat)."""
        response = self._client.get(URL, params=params(since))
        if response.status_code != 200:
            raise EurostatError(f"{URL}: HTTP {response.status_code}: {response.text[:200]}")
        try:
            doc = response.json()
        except ValueError as exc:
            raise EurostatError(f"{URL}: not JSON: {exc}") from exc
        if not isinstance(doc, dict) or "value" not in doc or "dimension" not in doc:
            raise EurostatError(f"{URL}: not a JSON-stat dataset")
        return doc


def archive_key(fetched: datetime) -> str:
    return f"archive/eurostat/{DATASET}-{fetched:%Y-%m-%dT%H%M%SZ}.json.gz"


def archive(store: ObjectStore, key: str, doc: dict) -> str:
    """Keep the answer as it came (gzip JSON), like the collection's run archives."""
    store.put(key, gzip.compress(json.dumps(doc, ensure_ascii=False).encode("utf-8"), mtime=0))
    return key


def read_archive(store: ObjectStore, key: str) -> dict:
    return json.loads(gzip.decompress(store.get(key)))
