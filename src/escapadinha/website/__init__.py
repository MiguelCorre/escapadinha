"""What the Astro site (`web/`, D28), the site data export and the review snapshot share: which
deals are public, page slugs and paths, promotion image paths and the JPEGs the publishers hand
to Meta and Telegram (D36, D38). The build itself lives in `astro.py`, its routing in
`routing.py` and `redirects.py`.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import Counter

import httpx

from escapadinha import pipeline
from escapadinha.config import Context
from escapadinha.models import Deal, Observation
from escapadinha.storage import db

LIVE = ("approved", "published")


def slugify(text: str) -> str:
    """'Amesterdão' -> 'amesterdao', 'Onde está?' -> 'onde-esta'."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def route_slug(origin_city: str, city_pt: str) -> str:
    """A route page's slug: /voos/<slug>/ ('lisboa-londres')."""
    return f"{slugify(origin_city)}-{slugify(city_pt)}"


def origin_slug(origin_city: str) -> str:
    """An origin's slug in page paths ('Ponta Delgada' -> 'ponta-delgada'): its page
    /partidas/<slug>/ (D30) and its ponte pages /pontes/<feriado>/<slug>/ (D31)."""
    return slugify(origin_city)


def ponte_path(ponte_slug: str, origin_city: str) -> str:
    """A long weekend's page for one origin: /pontes/1-dezembro-2026/porto/ (D31)."""
    return f"/pontes/{ponte_slug}/{origin_slug(origin_city)}/"


DESTINATION_KEY = "destination:"   # site.paths key of a destination hub: "destination:SJO"
DESTINATIONS = "/destinos/"


def destination_path(slug: str) -> str:
    """A destination hub's page: /destinos/londres/ (D30)."""
    return f"{DESTINATIONS}{slug}/"


def destination_slugs(cities: dict[str, str],
                      published: dict[str, list[str]] | None = None) -> dict[str, str]:
    """Destination code -> its hub's slug, /destinos/<slug>/ ('londres'), from the Portuguese
    city name (D30). Stable once published: `published` (code -> slugs its hub was exported at,
    oldest first, from the `site.paths` history) keeps a hub at the latest of its slugs that
    still fits its name (the name's slug, or with its code), so a city discovered later never
    moves an existing hub. A newcomer whose name's slug is already a hub's, or another
    newcomer's, takes its code ('sao-jose-sjc'); newcomers that share a name all do, so their
    URLs don't depend on the order they were found in. A renamed city gets a new slug; its old
    path stays in the history for a 301."""
    published = published or {}
    out: dict[str, str] = {}
    for code, city in cities.items():
        fits = (slugify(city), f"{slugify(city)}-{code.lower()}")
        kept = [s for s in published.get(code, []) if s in fits]
        if kept:
            out[code] = kept[-1]
    taken = set(out.values()) | {slugify(cities[code]) for code in out}
    fresh = [code for code in cities if code not in out]
    shared = Counter(slugify(cities[code]) for code in fresh)
    for code in fresh:
        base = slugify(cities[code])
        out[code] = f"{base}-{code.lower()}" if base in taken or shared[base] > 1 else base
    return out


def promo_slug(deal_id: int, origin_city: str, city_pt: str) -> str:
    """A promotion page's slug: /promos/<slug>/ ('12-lisboa-londres')."""
    return f"{deal_id}-{slugify(origin_city)}-{slugify(city_pt)}"


def is_public(deal: Deal) -> bool:
    """Approved/published deals, plus expired ones a human had approved before. A deal that
    expired before anyone approved it is never public (site, site data, review snapshot)."""
    return deal.status in LIVE or (deal.status == "expired" and deal.reviewed_at is not None)


def public_deal_rows(conn: sqlite3.Connection) -> list[tuple[Deal, Observation]]:
    """Every public deal (`is_public`) with its observation."""
    return [(deal, obs)
            for deal, obs in db.deals_with_status(conn, "approved", "published", "expired")
            if is_public(deal)]


def promo_image_dir(deal_id: int) -> str:
    """Folder of a promotion's images on the site, under /img/ (slide_NN.webp, thumb, og)."""
    return f"promos/{deal_id}"


def deal_image_paths(ctx: Context, deal: Deal) -> tuple[list[str], str | None, str | None] | None:
    """(slides, thumb, og) site paths the build writes for a rendered deal, else None. The
    slide names come from `pipeline.deal_slide_names` (on a runner: the object store's listing,
    nothing downloaded; the build downloads the slides it converts, D25)."""
    names = pipeline.deal_slide_names(ctx, deal)
    if not names:
        return None
    base = f"/img/{promo_image_dir(deal.id)}"
    slides = [f"{base}/{name.removesuffix('.png')}.webp" for name in names]
    cover = "slide_01.png" in names
    return slides, f"{base}/thumb.webp" if cover else None, f"{base}/og.jpg" if cover else None


def deal_jpeg_paths(ctx: Context, deal: Deal) -> list[str]:
    """Site paths of a rendered deal's JPEG slides (`/img/promos/<id>/slide_NN.jpg`), in slide
    order, [] before rendering: the carousel and story images the Instagram publisher hands to
    Meta, which takes JPEG only (D36). Not in the contract: no page shows them."""
    base = f"/img/{promo_image_dir(deal.id)}"
    return [f"{base}/{name.removesuffix('.png')}.jpg"
            for name in pipeline.deal_slide_names(ctx, deal)]


def public_jpeg_urls(ctx: Context, deal: Deal) -> list[str]:
    """`deal_jpeg_paths` on the live site (`site.base_url`): what Meta and Telegram fetch
    (D36, D38)."""
    return [f"{ctx.config.site.base_url}{path}" for path in deal_jpeg_paths(ctx, deal)]


def image_problem(http: httpx.Client, url: str) -> str | None:
    """None when `url` is live for a publisher that fetches it (Meta, Telegram): a HEAD
    answers 200, following redirects but only over https; else what is wrong ('404',
    'redirecionado para http://…', 'sem resposta')."""
    try:
        response = http.head(url, follow_redirects=True)
    except httpx.HTTPError:
        return "sem resposta"
    if response.url.scheme != "https":
        return f"redirecionado para {response.url}"
    return None if response.status_code == 200 else str(response.status_code)
