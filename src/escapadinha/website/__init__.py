"""Static public website built from the database: the Instagram "link na bio".

Only deals a human approved are published. Live deals (approved/published) carry the
tracked affiliate link; once a deal expires its page stays (shared links don't break)
but says so, drops the booking button and is hidden from search engines. Guides are
published only when `reviewed: true`. Everything shown is traceable to stored data.

Route pages also list the route's *low prices* from the latest run (D24): automatic, not
reviewed, each one observation with its found date and its own tracked link.

Booking links come from the website's Travelpayouts Project (`pipeline.website_links` for
deals, `pipeline.low_price_links` for low prices). Elements showing a price carry
`data-obs` / `data-deal` / `data-route` so tests can trace every price on a page (D2).
`_redirects`/`_headers` keep old URLs working and old hosts out of search (`redirects.py`).
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml
from jinja2 import Environment, PackageLoader
from PIL import Image

from escapadinha import detector, pipeline, routes
from escapadinha import i18n_pt as pt
from escapadinha.config import Context
from escapadinha.guides import Guide
from escapadinha.models import Deal, Observation, Route
from escapadinha.presentation import (
    SITE_DISCLOSURE, LowPriceView, PhotoCredit, build_deal_view, build_low_price_view,
)
from escapadinha.storage import db
from escapadinha.website import redirects

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


@dataclass
class SiteDeal:
    deal: Deal
    obs: Observation
    view: object
    live: bool
    slug: str
    images: list[str] = field(default_factory=list)   # site paths, slide order
    thumb: str | None = None
    og_image: str | None = None
    checked: str = ""
    booking_link: str | None = None   # tracked link for the website's Travelpayouts Project

    @property
    def url(self) -> str:
        return f"/promos/{self.slug}/"


@dataclass
class RoutePage:
    route: Route
    origin_city: str
    slug: str
    live: list[SiteDeal]
    recent: list[SiteDeal]
    months: list[tuple[str, str, int]]    # (month label, typical low, days)
    lows: list[detector.LowPrice] = field(default_factory=list)   # biggest discount first
    low_views: list[LowPriceView] = field(default_factory=list)   # shown, by departure date

    @property
    def url(self) -> str:
        return f"/voos/{self.slug}/"


@dataclass
class GuidePage:
    guide: Guide
    images: list[str]

    @property
    def url(self) -> str:
        return f"/guias/{self.guide.slug}/"


class SiteBuilder:
    def __init__(self, ctx: Context, conn: sqlite3.Connection, now: datetime | None = None):
        self.ctx, self.conn = ctx, conn
        self.now = now or db.utcnow()
        self.out = ctx.site_dir
        self.cfg = ctx.config
        self.env = Environment(loader=PackageLoader("escapadinha.website", "templates"),
                               autoescape=True, trim_blocks=True, lstrip_blocks=True)
        self.env.globals.update(brand=self.cfg.brand, site=self.cfg.site,
                                built_at=pt.lisbon_timestamp(self.now),
                                site_disclosure=SITE_DISCLOSURE, detector_cfg=self.cfg.detector)
        self.low_links: pipeline.LowLinks | None = None

    # --- data -----------------------------------------------------------------

    def public_deals(self) -> list[SiteDeal]:
        """Approved/published deals, plus expired ones a human had approved before."""
        deals = []
        for deal, obs in public_deal_rows(self.conn):
            route = routes.get_route(self.conn, self.cfg.routes, obs.route_key)
            view = build_deal_view(deal, obs, origin_city=self.cfg.origin_name(obs.origin),
                                   destination_city=route.city_pt,
                                   photo=PhotoCredit.from_photo(None, None))
            slug = promo_slug(deal.id, view.origin_city, view.destination_city)
            checked_at = deal.last_checked_at or obs.fetched_at
            deals.append(SiteDeal(deal, obs, view, deal.status in LIVE, slug,
                                  checked=pt.lisbon_timestamp(checked_at)))
        live = [d for d in deals if d.live]
        links = pipeline.website_links(self.ctx, self.conn, [(d.deal, d.obs) for d in live])
        for d in live:
            d.booking_link = links.get(d.deal.id)
        return deals

    def route_pages(self, deals: list[SiteDeal]) -> list[RoutePage]:
        run_id = db.latest_completed_run_id(self.conn)
        run_offers = db.observations_seen_since(self.conn, run_id) if run_id else []
        pages = []
        for route in routes.all_routes(self.conn, self.cfg.routes):
            history = pipeline.route_history(self.ctx, self.conn, route, self.now)
            baselines = detector.month_baselines(history, self.cfg.detector, self.now, route.rules)
            months = [(f"{pt.MONTHS[m - 1]} {y}", pt.eur(b.median), b.sample_size)
                      for (y, m), b in sorted(baselines.items())
                      if detector.is_mature(b, self.cfg.detector)]
            on_route = [d for d in deals if d.obs.route_key == route.key]
            live = [d for d in on_route if d.live]
            # Low prices (D24); a live promotion's own offer is already shown above them.
            lows = pipeline.shown_low_prices(self.ctx, self.conn, route, history, self.now,
                                             run_offers, promoted={d.obs.id for d in live})
            origin_city = self.cfg.origin_name(route.origin)
            pages.append(RoutePage(
                route, origin_city, route_slug(origin_city, route.city_pt),
                live=live, recent=[d for d in on_route if not d.live][: self.cfg.site.recent_expired],
                months=months, lows=lows))
        self._link_low_prices(pages)
        return pages

    def _link_low_prices(self, pages: list[RoutePage]) -> None:
        """Tracked links for every listed low price (created once, D24), then the views."""
        self.low_links = pipeline.low_price_links(self.ctx, self.conn,
                                                  [lp for p in pages for lp in p.lows], self.now)
        for p in pages:
            p.low_views = [
                build_low_price_view(lp.observation, typical_low=lp.baseline.median,
                                     discount_pct=lp.discount_pct,
                                     booking_link=self.low_links.urls.get(lp.observation.id))
                for lp in sorted(p.lows, key=lambda lp: (lp.observation.departure_date,
                                                         lp.observation.return_date))]

    def guide_pages(self) -> list[GuidePage]:
        pages = []
        for path in sorted(self.ctx.guides_dir.glob("*.yaml")):
            guide = Guide.model_validate(yaml.safe_load(path.read_text("utf-8")))
            if not guide.reviewed:
                continue
            rendered = pipeline.guide_folder(self.ctx, guide.slug, pipeline.SLIDES)
            images = self._images(rendered, f"guias/{guide.slug}") if rendered else []
            pages.append(GuidePage(guide, images))
        return pages

    # --- images -----------------------------------------------------------------

    def _images(self, folder: Path, dest: str) -> list[str]:
        """Slides as WebP (1080 wide) for the page; returns site paths."""
        paths = []
        for png in sorted(folder.glob("slide_*.png")):
            target = self.out / "img" / dest / f"{png.stem}.webp"
            target.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(png) as im:
                im.convert("RGB").save(target, "WEBP", quality=80, method=6)
            paths.append(f"/img/{dest}/{png.stem}.webp")
        return paths

    def _deal_images(self, d: SiteDeal) -> None:
        folder = pipeline.deal_folder(self.ctx, d.deal, pipeline.SLIDES)   # stored on a runner
        if folder is None:
            return
        dest = promo_image_dir(d.deal.id)
        d.images = self._images(folder, dest)
        cover = folder / "slide_01.png"
        if cover.exists():
            thumb = self.out / "img" / dest / "thumb.webp"
            og = self.out / "img" / dest / "og.jpg"
            with Image.open(cover) as im:
                rgb = im.convert("RGB")
                rgb.resize((540, 675), Image.LANCZOS).save(thumb, "WEBP", quality=78, method=6)
                rgb.save(og, "JPEG", quality=82, optimize=True, progressive=True)
            d.thumb = f"/img/{dest}/thumb.webp"
            d.og_image = f"/img/{dest}/og.jpg"

    # --- output -------------------------------------------------------------------

    def _write(self, rel: str, template: str, **ctx) -> str:
        path = self.out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.env.get_template(template).render(**ctx), encoding="utf-8", newline="\n")
        return rel

    def _write_routing(self, deals: list[SiteDeal], routes: list[RoutePage],
                       guides: list[GuidePage]) -> redirects.RedirectPlan:
        """Cloudflare Pages `_redirects` + `_headers` (D19); remembers every published path."""
        pages = {f"page:{p}": p for p in ("/", "/sobre/", "/privacidade/")}
        pages |= {f"deal:{d.deal.id}": d.url for d in deals}
        pages |= {f"route:{r.route.key}": r.url for r in routes}
        pages |= {f"guide:{g.guide.slug}": g.url for g in guides}
        history = pipeline.site_paths(self.ctx, self.conn)   # in the database (D25)
        aliases = {f"/promos/{d.deal.id}": d.url
                   for d in sorted(deals, key=lambda d: d.deal.id, reverse=True)}
        plan = redirects.plan_redirects(pages, history, extra=self.cfg.site.redirects,
                                        aliases=aliases)
        (self.out / "_redirects").write_text(plan.text(), encoding="utf-8", newline="\n")
        (self.out / "_headers").write_text(redirects.headers_text(self.cfg.site),
                                           encoding="utf-8", newline="\n")
        pipeline.save_site_paths(self.conn, redirects.update_history(history, pages))
        return plan

    def build(self) -> dict:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        shutil.copy(self.ctx.assets_dir / "logo-light.svg", self.out / "logo.svg")
        (self.out / "favicon.svg").write_text(_FAVICON, encoding="utf-8")

        deals = self.public_deals()
        for d in deals:
            self._deal_images(d)
        live = [d for d in deals if d.live]
        routes = self.route_pages(deals)
        guides = self.guide_pages()

        indexed = ["/", "/sobre/", "/privacidade/"]
        self._write("index.html", "index.html.j2", deals=live, routes=routes, guides=guides,
                    canonical="/")
        for d in deals:
            route = next(r for r in routes if r.route.key == d.obs.route_key)
            self._write(f"promos/{d.slug}/index.html", "deal.html.j2", d=d, route=route,
                        canonical=d.url)
            if d.live:
                indexed.append(d.url)
        for r in routes:
            self._write(f"voos/{r.slug}/index.html", "route.html.j2", r=r, canonical=r.url)
            indexed.append(r.url)
        for g in guides:
            self._write(f"guias/{g.guide.slug}/index.html", "guide.html.j2", g=g, canonical=g.url)
            indexed.append(g.url)
        self._write("sobre/index.html", "about.html.j2", canonical="/sobre/")
        self._write("privacidade/index.html", "privacy.html.j2", canonical="/privacidade/")
        self._write("404.html", "404.html.j2", canonical=None)
        self._write("sitemap.xml", "sitemap.xml.j2", urls=indexed)
        self._write("robots.txt", "robots.txt.j2")
        plan = self._write_routing(deals, routes, guides)
        links = self.low_links
        summary = {"live_deals": len(live), "expired_pages": len(deals) - len(live),
                   "routes": len(routes), "low_prices": sum(len(r.lows) for r in routes),
                   "low_price_links_created": links.created if links else 0,
                   "low_prices_without_link": links.pending if links else 0,
                   "guides": len(guides), "pages": len(indexed),
                   "redirects": len(plan.rules), "skipped_redirects": plan.skipped}
        (self.out / "build.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary


_FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<circle cx="32" cy="32" r="30" fill="#FF6B4A"/>
<path d="M14 36 L48 20 L44 26 L52 28 L46 32 L40 30 L26 42 L24 38 L20 40 Z" fill="#fff"/></svg>
"""


def build_site(ctx: Context, conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    return SiteBuilder(ctx, conn, now).build()
