"""Destination photos from the Pixabay API, downloaded once and cached with their credit.

Pixabay Content License: free commercial use and modification, no attribution required.
The API forbids permanent hotlinking (images must be downloaded) and asks for responses
to be cached for 24 h; we download one photo per destination and keep it. Credit is
stored anyway and printed in every caption ("📷 Foto: <nome> / Pixabay").
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import httpx

from escapadinha.models import Photo
from escapadinha.storage.db import utcnow

SEARCH_URL = "https://pixabay.com/api/"
SOURCE = "pixabay"
LICENSE = "Pixabay Content License (https://pixabay.com/service/license-summary/)"

# Searched in this order. A bare city name with no category returns whatever is popular for
# the word ("Brussels" -> sprouts, "Bristol" -> Bristol, Maine), so travel photos come first.
CATEGORIES = ("travel", "places", "buildings", None)


class PhotoSourceError(RuntimeError):
    pass


class PixabayClient:
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        if not api_key:
            raise PhotoSourceError("PIXABAY_API_KEY is not set (see .env.example)")
        self._client = client or httpx.Client(timeout=60, follow_redirects=True)
        self._key = api_key

    def search_portrait(self, query: str, per_page: int = 20,
                        category: str | None = None) -> list[dict]:
        params = {"key": self._key, "q": query, "image_type": "photo", "orientation": "vertical",
                  "safesearch": "true", "order": "popular", "per_page": per_page}
        if category:
            params["category"] = category
        response = self._client.get(SEARCH_URL, params=params)
        if response.status_code != 200:
            # Pixabay returns a plain-text error body; never echo the request URL (holds the key).
            raise PhotoSourceError(f"Pixabay HTTP {response.status_code}: {response.text[:200]}")
        return response.json().get("hits", [])

    def download(self, url: str) -> bytes:
        response = self._client.get(url)
        response.raise_for_status()
        return response.content


def best_url(hit: dict) -> str:
    """Largest size the account may use: fullHDURL needs approved full access."""
    return hit.get("fullHDURL") or hit["largeImageURL"]


def user_profile_url(hit: dict) -> str:
    return f"https://pixabay.com/users/{hit['user']}-{hit['user_id']}/"


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def search(client: PixabayClient, query: str, must: str | None = None) -> list[dict]:
    """Hits for `query`, travel categories first. With `must` (the city name), only photos
    tagged with it count; if no category has one, the first travel-like results are used."""
    fallback: list[dict] = []
    for category in CATEGORIES:
        hits = client.search_portrait(query, category=category)
        if must is None:
            if hits:
                return hits
            continue
        tagged = [h for h in hits if _fold(must) in _fold(h.get("tags", ""))]
        if tagged:
            return tagged
        fallback = fallback or hits
    return fallback


def fetch_photo(client: PixabayClient, destination: str, query: str, photos_dir: Path,
                pick: int = 0, must: str | None = None) -> Photo:
    """`must`: a word the photo's tags must contain (the city name) when the query is automatic."""
    results = search(client, query, must)
    if not results:
        raise PhotoSourceError(f"No Pixabay results for '{query}'")
    if pick >= len(results):
        raise PhotoSourceError(f"Only {len(results)} results for '{query}', cannot pick #{pick}")
    chosen = results[pick]
    photos_dir.mkdir(parents=True, exist_ok=True)
    path = photos_dir / f"{destination}.jpg"
    path.write_bytes(client.download(best_url(chosen)))
    return Photo(
        destination=destination,
        file_path=path.name,  # relative to the photos cache dir
        source=SOURCE,
        source_url=chosen["pageURL"],
        photographer=chosen["user"],
        photographer_url=user_profile_url(chosen),
        license=LICENSE,
        fetched_at=utcnow(),
    )
