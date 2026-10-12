"""Destination photos from the Pexels API, downloaded once and cached with their credit.

Pexels License: free commercial use and modification. Photos are used only as slide
backgrounds under text, never redistributed standalone. Credit is stored and printed
in every caption ("📷 Foto: <nome> / Pexels").
"""

from __future__ import annotations

from pathlib import Path

import httpx

from escapadinha.models import Photo
from escapadinha.storage.db import utcnow

SEARCH_URL = "https://api.pexels.com/v1/search"
LICENSE = "Pexels License (https://www.pexels.com/license/)"


class PexelsError(RuntimeError):
    pass


class PexelsClient:
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        if not api_key:
            raise PexelsError("PEXELS_API_KEY is not set (see .env.example)")
        self._client = client or httpx.Client(timeout=60, follow_redirects=True)
        self._headers = {"Authorization": api_key}

    def search_portrait(self, query: str, per_page: int = 10) -> list[dict]:
        response = self._client.get(
            SEARCH_URL, headers=self._headers,
            params={"query": query, "orientation": "portrait", "per_page": per_page},
        )
        if response.status_code != 200:
            raise PexelsError(f"Pexels HTTP {response.status_code}: {response.text[:200]}")
        return response.json().get("photos", [])

    def download(self, url: str) -> bytes:
        response = self._client.get(url)
        response.raise_for_status()
        return response.content


def slide_sized_url(original: str) -> str:
    """Pexels image CDN crops server-side; ask for exactly the 4:5 slide size."""
    return f"{original}?auto=compress&cs=tinysrgb&fit=crop&w=1080&h=1350"


def fetch_photo(client: PexelsClient, destination: str, query: str, photos_dir: Path,
                pick: int = 0) -> Photo:
    results = client.search_portrait(query)
    if not results:
        raise PexelsError(f"No Pexels results for '{query}'")
    if pick >= len(results):
        raise PexelsError(f"Only {len(results)} results for '{query}', cannot pick #{pick}")
    chosen = results[pick]
    photos_dir.mkdir(parents=True, exist_ok=True)
    path = photos_dir / f"{destination}.jpg"
    path.write_bytes(client.download(slide_sized_url(chosen["src"]["original"])))
    return Photo(
        destination=destination,
        file_path=path.name,  # relative to the photos cache dir
        source="pexels",
        source_url=chosen["url"],
        photographer=chosen["photographer"],
        photographer_url=chosen["photographer_url"],
        license=LICENSE,
        fetched_at=utcnow(),
    )
