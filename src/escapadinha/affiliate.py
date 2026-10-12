"""Travelpayouts partner links API: turns brand URLs into tracked affiliate links.

Program terms (Aviasales 1.4) allow only the network's own promo tools, so posts use
links generated here for our Project (`trs`), never a hand-built `marker=` URL.
Limits: 100 requests/min per marker, at most 10 links per request.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

API_URL = "https://api.travelpayouts.com/links/v1/create"
MAX_LINKS_PER_REQUEST = 10


class AffiliateError(RuntimeError):
    pass


@dataclass(frozen=True)
class PartnerLink:
    url: str                    # original brand URL
    partner_url: str | None     # tracked link, None when conversion failed
    error: str | None = None


class PartnerLinksClient:
    def __init__(self, token: str, *, marker: str, project_id: int, shorten: bool = True,
                 client: httpx.Client | None = None):
        if not token:
            raise AffiliateError("TRAVELPAYOUTS_TOKEN is not set (see .env.example)")
        if not marker or not marker.isdigit():
            raise AffiliateError("TRAVELPAYOUTS_MARKER must be your numeric partner id")
        self._client = client or httpx.Client(timeout=30)
        self._headers = {"X-Access-Token": token}
        self._marker, self._project_id, self._shorten = int(marker), project_id, shorten

    def create(self, links: list[tuple[str, str | None]]) -> dict[str, PartnerLink]:
        """Convert (url, sub_id) pairs; result keyed by original url."""
        results: dict[str, PartnerLink] = {}
        for start in range(0, len(links), MAX_LINKS_PER_REQUEST):
            batch = links[start:start + MAX_LINKS_PER_REQUEST]
            body = {
                "trs": self._project_id, "marker": self._marker, "shorten": self._shorten,
                "links": [{"url": url, **({"sub_id": sub_id} if sub_id else {})}
                          for url, sub_id in batch],
            }
            response = self._client.post(API_URL, json=body, headers=self._headers)
            if response.status_code == 401:
                raise AffiliateError("Partner links API: invalid token (HTTP 401)")
            payload = response.json() if response.content else {}
            if response.status_code != 200 or payload.get("code") != "success":
                raise AffiliateError(f"Partner links API HTTP {response.status_code}: "
                                     f"{payload.get('error') or payload.get('code') or 'unknown'}")
            for item in payload["result"]["links"]:
                ok = item.get("code") == "success" and item.get("partner_url")
                results[item["url"]] = PartnerLink(
                    url=item["url"],
                    partner_url=item["partner_url"] if ok else None,
                    error=None if ok else item.get("message") or "conversion failed",
                )
        return results
