"""Wires storage to collector, detector, photos, renderer and captions. One function per CLI step."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from escapadinha import detector, i18n_pt
from escapadinha.affiliate import AffiliateError, PartnerLinksClient
from escapadinha.captions import deal_caption, guide_caption
from escapadinha.collector.runner import RunSummary, collect
from escapadinha.collector.travelpayouts import TravelpayoutsSource
from escapadinha.config import Context, Route
from escapadinha.guides import load_guide
from escapadinha.models import Deal, Observation
from escapadinha.photos import PixabayClient, fetch_photo
from escapadinha.presentation import PhotoCredit, booking_url, build_deal_view
from escapadinha.recheck import Recheck, recheck
from escapadinha.review import STATUS_PT, ReviewError, ensure_transition
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
    return collect(conn, _source(ctx), ctx.config.routes, today=lisbon_today(),
                   months_ahead=ctx.config.collector.months_ahead)


# --- detect -------------------------------------------------------------------

@dataclass(frozen=True)
class RouteDetection:
    route: str
    fresh: int                          # offers found within the freshness window
    best: Observation | None            # biggest discount vs its month's typical low (or cheapest)
    baseline: detector.Baseline | None  # typical low for `best`'s departure month
    status: str                         # deals | no_deal | insufficient_history | no_fresh | no_data
    deal_ids: list[int]
    note: str


def run_detect(ctx: Context, conn: sqlite3.Connection, run_id: int | None = None,
               now: datetime | None = None) -> tuple[int | None, list[RouteDetection]]:
    """Evaluate the given (default: latest completed) run against each route's typical lows."""
    cfg = ctx.config.detector
    now = now or db.utcnow()
    run_id = run_id or db.latest_completed_run_id(conn)
    if run_id is None:
        return None, []
    run_obs = db.observations_for_run(conn, run_id)

    results = []
    for route in ctx.config.routes:
        offers = [o for o in run_obs if o.route_key == route.key]
        if not offers:
            results.append(RouteDetection(route.key, 0, None, None, "no_data", [], "no prices this run"))
            continue
        history = db.route_history(conn, route.origin, route.destination,
                                   since=now - timedelta(days=cfg.lookback_days), exclude_run_id=None)
        recent = db.recently_flagged_offers(conn, route.origin, route.destination,
                                            since=now - timedelta(days=cfg.dedupe_days))
        flags = detector.detect_route(offers, history, recent, cfg, route.price_cap_eur,
                                      now, cfg.max_deals_per_route)
        deal_ids = [
            db.insert_deal(conn, observation_id=f.observation.id, rule=f.decision.rule,
                           baseline_median=f.baseline.median, sample_size=f.baseline.sample_size,
                           discount_pct=f.decision.discount_pct, threshold=cfg.threshold)
            for f in flags
        ]
        results.append(_summarise(route, offers, history, flags, deal_ids, cfg, now))
    return run_id, results


def _summarise(route: Route, offers: list[Observation], history: list[Observation],
               flags: list[detector.Flag], deal_ids: list[int], cfg, now: datetime) -> RouteDetection:
    fresh = [o for o in detector.eligible(offers, cfg) if detector.is_fresh(o, cfg, now)]
    if not fresh:
        kind = "direct " if cfg.direct_only else ""
        return RouteDetection(route.key, 0, None, None, "no_fresh", [],
                              f"no {kind}price found in the last {cfg.max_offer_age_days} days")
    baselines = detector.month_baselines(history, cfg, now)
    empty = detector.Baseline(None, 0, 0)

    def discount(o: Observation) -> float:
        base = baselines.get(detector.month_key(o), empty)
        return 1 - o.price / base.median if base.median else float("-inf")

    best = flags[0].observation if flags else max(fresh, key=lambda o: (discount(o), -o.price))
    base = baselines.get(detector.month_key(best), empty)
    decision = detector.evaluate(best, base, cfg, route.price_cap_eur)
    status = "deals" if deal_ids else decision.kind
    return RouteDetection(route.key, len(fresh), best, base, status, deal_ids, decision.reason)


def current_baselines(ctx: Context, conn: sqlite3.Connection,
                      route: Route) -> dict[tuple[int, int], detector.Baseline]:
    """Typical low per departure month from all stored history (for `stats`)."""
    cfg, now = ctx.config.detector, db.utcnow()
    history = db.route_history(conn, route.origin, route.destination,
                               since=now - timedelta(days=cfg.lookback_days), exclude_run_id=None)
    return detector.month_baselines(history, cfg, now)


# --- recheck ------------------------------------------------------------------

def run_recheck(ctx: Context, conn: sqlite3.Connection, run_id: int | None = None,
                now: datetime | None = None) -> list[tuple[Deal, Observation, Recheck]]:
    """Re-verify every open deal against the newest run; expire the ones that moved.

    A deal is only judged when the run is newer than the deal's own data and the run
    returned prices for that route (a failed request must not expire anything).
    """
    now = now or db.utcnow()
    run_id = run_id or db.latest_completed_run_id(conn)
    if run_id is None:
        return []
    latest = db.observations_for_run(conn, run_id)
    results = []
    for deal, obs in db.open_deals(conn):
        route_latest = [o for o in latest if o.route_key == obs.route_key]
        if obs.run_id >= run_id or not route_latest:
            continue
        result = recheck(obs, route_latest, ctx.config.detector, now)
        db.record_recheck(conn, deal.id, valid=result.valid, latest_price=result.latest_price,
                          reason=result.reason)
        if not result.valid:
            _mark_expired_outputs(ctx, deal.id, result.reason, now)
        results.append((db.get_deal(conn, deal.id)[0], obs, result))
    return results


def _mark_expired_outputs(ctx: Context, deal_id: int, reason: str, now: datetime) -> None:
    """Drop a NÃO PUBLICAR note into any already-rendered folder of this deal."""
    for folder in ctx.output_dir.glob(f"*/deal-*-{deal_id}"):
        _write_text(folder / "EXPIRADO.txt",
                    f"NÃO PUBLICAR: deal expirado a {i18n_pt.lisbon_timestamp(now)}.\n"
                    f"Motivo: {reason}\n")


# --- review (approval queue) ---------------------------------------------------

def _source(ctx: Context) -> TravelpayoutsSource:
    c = ctx.config.collector
    return TravelpayoutsSource(ctx.secrets.travelpayouts_token, currency=c.currency,
                               min_nights=c.min_nights, max_nights=c.max_nights,
                               limit=c.limit_per_request, market=c.market,
                               booking_base=c.booking_base)


def live_check(ctx: Context, conn: sqlite3.Connection, deal_id: int,
               now: datetime | None = None) -> tuple[Deal, Recheck]:
    """Fetch this deal's route and departure month right now and recheck the price.

    The prices are stored as a `live_check` run (traceable like any other data). A deal
    whose price moved expires immediately.
    """
    deal, obs = db.get_deal(conn, deal_id)
    if deal.status not in db.OPEN_STATUSES:
        raise ReviewError(f"O deal {deal_id} está '{STATUS_PT[deal.status]}' e já não é verificado.")
    source = _source(ctx)
    run_id = db.start_run(conn, source.name, scope="live_check")
    try:
        fresh = source.fetch_round_trips(obs.origin, obs.destination,
                                         obs.departure_date.replace(day=1))
    except Exception as exc:
        db.finish_run(conn, run_id, status="failed", n_requests=1, n_observations=0, error=str(exc))
        raise ReviewError(f"Não foi possível verificar o preço agora: {exc}") from exc
    db.insert_observations(conn, run_id, fresh)
    db.finish_run(conn, run_id, status="ok", n_requests=1, n_observations=len(fresh), error=None)
    now = now or db.utcnow()
    result = recheck(obs, fresh, ctx.config.detector, now)
    db.record_recheck(conn, deal_id, valid=result.valid, latest_price=result.latest_price,
                      reason=result.reason)
    if not result.valid:
        _mark_expired_outputs(ctx, deal_id, result.reason, now)
    return db.get_deal(conn, deal_id)[0], result


def approve(ctx: Context, conn: sqlite3.Connection, deal_id: int,
            note: str | None = None) -> tuple[Deal, Recheck]:
    """Approve only after a live price check passes; a moved price expires the deal instead."""
    deal, _ = db.get_deal(conn, deal_id)
    ensure_transition(deal.status, "approved")
    if not deal.affiliate_url:
        raise ReviewError("Este deal ainda não tem link de afiliado. Volta a renderizar "
                          f"({deal.affiliate_error or 'sem erro registado'}).")
    deal, result = live_check(ctx, conn, deal_id)
    if result.valid:
        db.record_review(conn, deal_id, status="approved", note=note)
        deal = db.get_deal(conn, deal_id)[0]
    return deal, result


def reject(conn: sqlite3.Connection, deal_id: int, note: str | None = None) -> Deal:
    deal, _ = db.get_deal(conn, deal_id)
    ensure_transition(deal.status, "rejected")
    db.record_review(conn, deal_id, status="rejected", note=note)
    return db.get_deal(conn, deal_id)[0]


def mark_published(conn: sqlite3.Connection, deal_id: int, post_url: str | None = None) -> Deal:
    deal, _ = db.get_deal(conn, deal_id)
    ensure_transition(deal.status, "published")
    if post_url and not post_url.startswith(("https://", "http://")):
        raise ReviewError("O link do post tem de começar por https://")
    db.record_published(conn, deal_id, post_url or None)
    return db.get_deal(conn, deal_id)[0]


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


def ensure_affiliate_links(ctx: Context, conn: sqlite3.Connection,
                           pairs: list[tuple[Deal, Observation]]) -> list[tuple[Deal, Observation]]:
    """Generate (once) a tracked partner link per deal; failures are recorded, not hidden.

    Deals without a link are retried on every render. There is deliberately no fallback
    to a hand-built `marker=` URL: the program terms allow only network tools.
    """
    base = ctx.config.collector.booking_base
    missing = [(d, o) for d, o in pairs if not d.affiliate_url and o.deep_link]
    if not missing:
        return pairs
    project_id = ctx.config.affiliate.project_id
    if project_id is None:
        results, failure = {}, "affiliate.project_id is not set in config.yaml"
    else:
        try:
            client = PartnerLinksClient(ctx.secrets.travelpayouts_token,
                                        marker=ctx.secrets.travelpayouts_marker,
                                        project_id=project_id, shorten=ctx.config.affiliate.shorten)
            results = client.create([(booking_url(o.deep_link, base), f"deal-{d.id}")
                                     for d, o in missing])
            failure = None
        except (AffiliateError, httpx.HTTPError) as exc:
            results, failure = {}, str(exc)
    for d, o in missing:
        link = results.get(booking_url(o.deep_link, base))
        db.set_deal_affiliate(conn, d.id, link.partner_url if link else None,
                              (link.error if link else failure) or None)
    return [db.get_deal(conn, d.id) for d, _ in pairs]


def run_render_deals(ctx: Context, conn: sqlite3.Connection, status: str = "new",
                     deal_id: int | None = None) -> list[tuple[Path, Deal]]:
    """Render slides + caption + meta per deal. Returns (folder, deal) to report link status."""
    pairs = [db.get_deal(conn, deal_id)] if deal_id else db.deals_with_status(conn, status)
    pairs = [db.get_deal(conn, d.id) for d, _ in pairs]   # fresh rows (status may have moved)
    if not pairs:
        return []
    pairs = ensure_affiliate_links(ctx, conn, pairs)
    out_root = ctx.output_dir / lisbon_today().isoformat()
    written = []
    with SlideRenderer(ctx.assets_dir, ctx.config.brand) as renderer:
        for deal, obs in pairs:
            route = ctx.config.route(obs.route_key)
            credit, photo_path = _photo(ctx, conn, obs.destination)
            view = build_deal_view(deal, obs, origin_city=ctx.config.origin_name(obs.origin),
                                   destination_city=route.city_pt, photo=credit)
            out_dir = out_root / f"deal-{obs.origin}-{obs.destination}-{deal.id}"
            renderer.render_deal(view, photo_path, out_dir)
            _write_text(out_dir / "caption.txt",
                        deal_caption(view, brand_name=ctx.config.brand.name))
            _write_text(out_dir / "meta.json",
                        json.dumps(view.meta(deal, obs, ctx.config.collector.booking_base),
                                   ensure_ascii=False, indent=2))
            db.set_deal_output_path(conn, deal.id, str(out_dir))
            if deal.status == "new":
                db.set_deal_status(conn, deal.id, "rendered")
            written.append((out_dir, deal))
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
