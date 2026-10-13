"""The review snapshot (D26): what any review UI needs, exported to `review/snapshot.json` at the
end of every run. Contract: `contract/review/v1/snapshot.schema.json`.

Slides: a deal the site shows publicly (approved, published, expired after approval) links its
slides on the public site (`<base_url>/img/promos/<id>/slide_NN.webp`). A deal still open for
review (new, rendered, approved) also gets WebP copies in the store under `review/slides/<id>/`,
because a queue item is not on the public site and the review Function serves those keys behind
Access (smaller than the PNGs under `output/`, D25). Copies of deals that left review are deleted.
On a runner the rendered folders are not local: slide names come from the `output/` listing and
a folder is only downloaded to make missing review copies (D25).
"""

from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from PIL import Image

from escapadinha import pipeline, review_events
from escapadinha.collector.travelpayouts import request_params
from escapadinha.config import Context
from escapadinha.models import Deal, Observation
from escapadinha.presentation import PhotoCredit, build_deal_view
from escapadinha.review import STATUS_PT, TABS
from escapadinha.storage import db
from escapadinha.website import is_public, promo_images, promo_slug

VERSION = 1
KEY = "review/snapshot.json"
SLIDES = "review/slides/"
RECENT = 20          # published / closed deals listed (newest first)
REVIEWABLE = db.OPEN_STATUSES


def _iso(dt: datetime | None) -> str | None:
    return review_events.iso(dt) if dt else None


class _Rendered:
    """Rendered deal folders, local or in the object store (`output/`, D25), read lazily."""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.files = pipeline.output_files(ctx)
        self._stored: dict[str, set[str]] | None = None

    def stems(self, deal: Deal) -> set[str]:
        """'slide_01', ... of this deal, without downloading anything."""
        if not deal.output_path:
            return set()
        local = Path(deal.output_path)
        if local.is_dir():
            return {p.stem for p in local.glob("slide_*.png")}
        if self._stored is None:
            self._stored = {}
            for rel in self.files.keys():
                folder, _, name = rel.rpartition("/")
                if name.startswith("slide_") and name.endswith(".png"):
                    self._stored.setdefault(folder, set()).add(name.removesuffix(".png"))
        return self._stored.get(pipeline.deal_rel(deal.output_path), set())

    def caption(self, deal: Deal) -> str | None:
        if not deal.output_path:
            return None
        local = Path(deal.output_path) / "caption.txt"
        path = local if local.is_file() else self.files.file(
            f"{pipeline.deal_rel(deal.output_path)}/caption.txt")
        return path.read_text("utf-8") if path else None


def _sync_slides(ctx: Context, rendered: _Rendered, deals: list[Deal]) -> dict[int, list[str]]:
    """deal id -> store keys of its review copies; makes missing ones, deletes those of deals
    that left review."""
    store = ctx.object_store
    keys: dict[int, list[str]] = {}
    open_ids = {d.id for d in deals if d.status in REVIEWABLE}
    for key in store.list(SLIDES):
        deal_id = key.removeprefix(SLIDES).split("/", 1)[0]
        if not deal_id.isdigit() or int(deal_id) not in open_ids:
            store.delete(key)
        else:
            keys.setdefault(int(deal_id), []).append(key)
    for deal in deals:
        if deal.id not in open_ids:
            continue
        have = {Path(k).stem for k in keys.get(deal.id, [])}
        if not rendered.stems(deal) - have:
            continue
        folder = pipeline.deal_folder(ctx, deal)          # downloaded on a runner (D25)
        for png in sorted(folder.glob("slide_*.png")) if folder else []:
            if png.stem in have:
                continue
            try:
                with Image.open(png) as im:
                    buf = io.BytesIO()
                    im.convert("RGB").save(buf, "WEBP", quality=80, method=6)
            except OSError:
                continue                      # unreadable slide: the deal is listed without it
            key = f"{SLIDES}{deal.id}/{png.stem}.webp"
            store.put(key, buf.getvalue())
            keys.setdefault(deal.id, []).append(key)
    return {k: sorted(v) for k, v in keys.items()}


def _slides(ctx: Context, rendered: _Rendered, deal: Deal, store_keys: list[str]) -> list[dict]:
    by_stem = {Path(k).stem: k for k in store_keys}
    base = ctx.config.site.base_url
    public = is_public(deal)
    return [{"url": f"{base}/img/{promo_images(deal.id)}/{stem}.webp" if public else None,
             "key": by_stem.get(stem)}
            for stem in sorted(rendered.stems(deal) | set(by_stem))]


def _deal(ctx: Context, conn: sqlite3.Connection, rendered: _Rendered, deal: Deal,
          obs: Observation, store_keys: list[str]) -> dict:
    route = pipeline.route_for(ctx, conn, obs.route_key)
    view = build_deal_view(deal, obs, origin_city=ctx.config.origin_name(obs.origin),
                           destination_city=route.city_pt, photo=PhotoCredit.from_photo(None, None))
    rules = route.rules
    c = ctx.config.collector
    return {
        "id": deal.id,
        "status": deal.status,
        "status_pt": STATUS_PT[deal.status],
        "observation_id": obs.id,
        "route": obs.route_key,
        "origin": obs.origin,
        "destination": obs.destination,
        "origin_city": view.origin_city,
        "destination_city": view.destination_city,
        "headline": f"{view.origin_city} → {view.destination_headline}",
        "arrival_airport": view.arrival_airport,
        "price_eur": obs.price,
        "price": view.price,
        "departure_date": obs.departure_date.isoformat(),
        "return_date": obs.return_date.isoformat(),
        "dates": view.dates,
        "nights": view.nights,
        "airline": view.airline,
        "direct": view.direct,
        "rule": deal.rule,
        "discount_pct": view.discount_pct,
        "typical_low_eur": deal.baseline_median,
        "baseline_days": deal.sample_size,
        "found_date": obs.found_date.isoformat() if obs.found_date else None,
        "found_on": view.found_on,
        "fetched_at": _iso(obs.fetched_at),
        "checked_at": view.checked_at,
        "detected_at": _iso(deal.detected_at),
        "affiliate_url": deal.affiliate_url,
        "affiliate_error": deal.affiliate_error,
        "caption": rendered.caption(deal),
        "whatsapp_text": None,           # generated alongside the caption by a later ticket
        "page_url": (f"{ctx.config.site.base_url}/promos/"
                     f"{promo_slug(deal.id, view.origin_city, view.destination_city)}/"
                     if is_public(deal) else None),
        "slides": _slides(ctx, rendered, deal, store_keys),
        "live_check": {
            "last_checked_at": _iso(deal.last_checked_at),
            "last_seen_price_eur": deal.last_seen_price,
            "expired_reason": deal.expired_reason,
            "query": request_params(obs.origin, obs.destination, obs.departure_date.replace(day=1),
                                    currency=c.currency, limit=c.limit_per_request,
                                    market=c.market),
            "rules": {"direct_only": rules.direct_only, "max_transfers": rules.max_transfers,
                      "min_nights": rules.min_nights, "max_nights": rules.max_nights,
                      "max_offer_age_days": ctx.config.detector.max_offer_age_days},
        },
        "review_note": deal.review_note,
        "reviewed_at": _iso(deal.reviewed_at),
        "published_at": _iso(deal.published_at),
        "post_url": deal.post_url,
    }


def build(ctx: Context, conn: sqlite3.Connection, now: datetime) -> dict:
    tabs = {tab: sorted(db.deals_with_status(conn, *statuses), key=lambda p: -p[0].id)
            for tab, statuses in TABS.items()}
    tabs["published"] = tabs["published"][:RECENT]
    tabs["closed"] = tabs["closed"][:RECENT]
    rendered = _Rendered(ctx)
    store_keys = _sync_slides(ctx, rendered, [d for pairs in tabs.values() for d, _ in pairs])
    return {
        "version": VERSION,
        "generated_at": review_events.iso(now),
        "site_base_url": ctx.config.site.base_url,
        "review_rules": {"approve_max_age_hours": ctx.config.review.approve_max_age_hours},
        **{tab: [_deal(ctx, conn, rendered, d, o, store_keys.get(d.id, [])) for d, o in pairs]
           for tab, pairs in tabs.items()},
        "pending_events": [e.to_json() for e in review_events.pending(ctx.object_store, conn)],
        "recent_outcomes": [o.to_json() for o in review_events.recent_outcomes(conn, RECENT)],
    }


def export(ctx: Context, conn: sqlite3.Connection, now: datetime) -> dict:
    snapshot = build(ctx, conn, now)
    ctx.object_store.put(KEY, json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8"))
    return snapshot
