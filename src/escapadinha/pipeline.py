"""Wires storage to collector, detector, photos, renderer and captions. One function per CLI step."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from escapadinha import detector, i18n_pt
from escapadinha.captions import deal_caption, guide_caption
from escapadinha.collector.runner import RunSummary, collect
from escapadinha.collector.travelpayouts import TravelpayoutsSource
from escapadinha.config import Context, Route
from escapadinha.guides import load_guide
from escapadinha.photos import PixabayClient, fetch_photo
from escapadinha.presentation import PhotoCredit, build_deal_view
from escapadinha.renderer import SlideRenderer
from escapadinha.storage import db


def open_db(ctx: Context) -> sqlite3.Connection:
    conn = db.connect(ctx.db_path)
    db.init(conn)
    return conn


def lisbon_today() -> date:
    return db.utcnow().astimezone(i18n_pt.LISBON).date()


# --- collect ------------------------------------------------------------------

def run_collect(ctx: Context, conn: sqlite3.Connection) -> RunSummary:
    c = ctx.config.collector
    source = TravelpayoutsSource(ctx.secrets.travelpayouts_token, currency=c.currency,
                                 min_nights=c.min_nights, max_nights=c.max_nights,
                                 limit=c.limit_per_request)
    return collect(conn, source, ctx.config.routes, today=lisbon_today(), months_ahead=c.months_ahead)


# --- detect -------------------------------------------------------------------

@dataclass(frozen=True)
class RouteDetection:
    route: str
    candidates: int
    baseline: detector.Baseline
    status: str                 # deals | no_deal | insufficient_history | no_data
    deal_ids: list[int]
    note: str


def run_detect(ctx: Context, conn: sqlite3.Connection, run_id: int | None = None,
               now: datetime | None = None) -> tuple[int | None, list[RouteDetection]]:
    """Evaluate the given (default: latest completed) run against each route's history."""
    cfg = ctx.config.detector
    now = now or db.utcnow()
    run_id = run_id or db.latest_completed_run_id(conn)
    if run_id is None:
        return None, []
    fresh = db.observations_for_run(conn, run_id)

    results = []
    for route in ctx.config.routes:
        candidates = [o for o in fresh if o.route_key == route.key]
        history = db.route_history(conn, route.origin, route.destination,
                                   since=now - timedelta(days=cfg.lookback_days),
                                   exclude_run_id=run_id)
        base = detector.route_baseline(history, cfg, now)
        if not candidates:
            results.append(RouteDetection(route.key, 0, base, "no_data", [], "no prices this run"))
            continue
        recent = db.recently_flagged_offers(conn, route.origin, route.destination,
                                            since=now - timedelta(days=cfg.dedupe_days))
        flagged = detector.detect_route(candidates, history, recent, cfg, route.price_cap_eur,
                                        now, cfg.max_deals_per_route)
        deal_ids = [
            db.insert_deal(conn, observation_id=o.id, rule=d.rule,
                           baseline_median=base.median, sample_size=base.sample_size,
                           discount_pct=d.discount_pct, threshold=cfg.threshold)
            for o, d in flagged
        ]
        cheapest = min(candidates, key=lambda o: o.price)
        sample = detector.evaluate(cheapest, base, cfg, route.price_cap_eur)
        status = "deals" if deal_ids else sample.kind
        results.append(RouteDetection(route.key, len(candidates), base, status, deal_ids,
                                      f"cheapest: {sample.reason}"))
    return run_id, results


def current_baseline(ctx: Context, conn: sqlite3.Connection, route: Route) -> detector.Baseline:
    """Baseline over all stored history in the lookback window (for `stats`)."""
    cfg, now = ctx.config.detector, db.utcnow()
    history = db.route_history(conn, route.origin, route.destination,
                               since=now - timedelta(days=cfg.lookback_days), exclude_run_id=None)
    return detector.route_baseline(history, cfg, now)


# --- photos -------------------------------------------------------------------

def photo_targets(ctx: Context) -> dict[str, str]:
    """Destination key -> Pixabay search query, for every route destination plus extra config keys."""
    cfg = ctx.config
    targets = {r.destination: cfg.photos.queries.get(r.destination, r.city_pt) for r in cfg.routes}
    for key, query in cfg.photos.queries.items():
        targets.setdefault(key, query)
    return targets


def run_fetch_photos(ctx: Context, conn: sqlite3.Connection, dest: str | None, force: bool,
                     pick: int) -> list[tuple[str, str]]:
    targets = photo_targets(ctx)
    if dest:
        dest = dest.upper()
        targets = {dest: targets.get(dest) or ctx.config.origin_name(dest)}
    client = PixabayClient(ctx.secrets.pixabay_api_key)
    done = []
    for key, query in targets.items():
        if not force and db.get_photo(conn, key) is not None:
            done.append((key, "cached"))
            continue
        photo = fetch_photo(client, key, query, ctx.photos_dir, pick=pick)
        db.upsert_photo(conn, photo)
        done.append((key, f"{photo.photographer} ({photo.source_url})"))
    return done


def _photo(ctx: Context, conn: sqlite3.Connection, key: str | None) -> tuple[PhotoCredit, Path | None]:
    photo = db.get_photo(conn, key) if key else None
    if photo is None:
        return PhotoCredit.from_photo(None, None), None
    path = ctx.photos_dir / photo.file_path
    return PhotoCredit.from_photo(photo, path.as_uri()), path


# --- render -------------------------------------------------------------------

def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def run_render_deals(ctx: Context, conn: sqlite3.Connection, status: str = "new",
                     deal_id: int | None = None) -> list[Path]:
    pairs = [db.get_deal(conn, deal_id)] if deal_id else db.deals_with_status(conn, status)
    if not pairs:
        return []
    out_root = ctx.output_dir / lisbon_today().isoformat()
    written = []
    with SlideRenderer(ctx.assets_dir, ctx.config.brand) as renderer:
        for deal, obs in pairs:
            route = ctx.config.route(obs.route_key)
            credit, photo_path = _photo(ctx, conn, obs.destination)
            view = build_deal_view(deal, obs, origin_city=ctx.config.origin_name(obs.origin),
                                   destination_city=route.city_pt,
                                   marker=ctx.secrets.travelpayouts_marker, photo=credit)
            out_dir = out_root / f"deal-{obs.origin}-{obs.destination}-{deal.id}"
            renderer.render_deal(view, photo_path, out_dir)
            _write_text(out_dir / "caption.txt", deal_caption(
                view, brand_name=ctx.config.brand.name,
                lookback_days=ctx.config.detector.lookback_days))
            _write_text(out_dir / "meta.json",
                        json.dumps(view.meta(deal, obs), ensure_ascii=False, indent=2))
            if deal.status == "new":
                db.set_deal_status(conn, deal.id, "rendered")
            written.append(out_dir)
    return written


def run_render_guide(ctx: Context, conn: sqlite3.Connection, slug: str) -> tuple[Path, bool]:
    guide = load_guide(ctx.guides_dir, slug)
    credit, photo_path = _photo(ctx, conn, guide.photo_destination)
    out_dir = ctx.output_dir / lisbon_today().isoformat() / f"guia-{guide.slug}"
    with SlideRenderer(ctx.assets_dir, ctx.config.brand) as renderer:
        renderer.render_guide(guide, credit, photo_path, out_dir)
    _write_text(out_dir / "caption.txt", guide_caption(guide, credit))
    _write_text(out_dir / "meta.json", json.dumps(
        {"guide": guide.slug, "reviewed": guide.reviewed, "sources": guide.sources,
         "photo": None if credit.photographer is None else asdict(credit)},
        ensure_ascii=False, indent=2))
    return out_dir, guide.reviewed
