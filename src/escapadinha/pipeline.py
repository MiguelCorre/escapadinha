"""Wires storage to collector, detector, photos, renderer and captions. One function per CLI step."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path, PureWindowsPath

import httpx

from escapadinha import (archive, detector, discovery, i18n_pt, instagram, posting, review_events,
                         routes, telegram)
from escapadinha.affiliate import AffiliateError, PartnerLinksClient
from escapadinha.articles import Article
from escapadinha.captions import deal_caption, guide_caption, whatsapp_text
from escapadinha.collector.runner import RunSummary, collect
from escapadinha.collector.base import Fetched, departure_months
from escapadinha.collector.catalogue import TravelpayoutsCatalogue
from escapadinha.collector.travelpayouts import RateLimiter, TravelpayoutsError, TravelpayoutsSource
from escapadinha.config import Context
from escapadinha.guides import load_guide
from escapadinha.models import Deal, Observation, Post, Route, RouteRules
from escapadinha.photos import PhotoSourceError, PixabayClient, fetch_photo
from escapadinha.presentation import DealView, PhotoCredit, booking_url, build_deal_view
from escapadinha.recheck import Recheck, recheck
from escapadinha.review import DECISION_PT, STATUS_PT, ReviewError, UnknownDeal, check_decision
from escapadinha.renderer import SlideRenderer
from escapadinha.storage import db, sync
from escapadinha.storage.mirror import Mirror


def open_db(ctx: Context) -> sqlite3.Connection:
    """Connect, migrate, archive payloads left by migration 7, apply config's route settings."""
    conn = db.connect(ctx.db_path)
    db.init(conn)
    archive.flush_legacy(conn, ctx.object_store)
    routes.sync(conn, ctx.config.routes, db.utcnow())
    return conn


def route_for(ctx: Context, conn: sqlite3.Connection, key: str) -> Route:
    return routes.get_route(conn, ctx.config.routes, key)


def lisbon_today() -> date:
    return db.utcnow().astimezone(i18n_pt.LISBON).date()


# --- collect ------------------------------------------------------------------

def run_collect(ctx: Context, conn: sqlite3.Connection) -> RunSummary:
    return collect(conn, price_source(ctx), routes.active_routes(conn, ctx.config.routes),
                   today=lisbon_today(), months_ahead=ctx.config.collector.months_ahead,
                   store=ctx.object_store, workers=ctx.config.collector.workers)


# The schedule dispatches a run every 2 h (D41); its skips leave at most 2 h 45 min between runs.
RUN_GAP_WARNING = timedelta(hours=3)


def late_run_warning(conn: sqlite3.Connection, now: datetime) -> str | None:
    """The run log's warning when the previous collection started more than `RUN_GAP_WARNING`
    before `now` (D41): the 2-hourly schedule missed at least one run. None on time or without
    a previous run. Live checks (scope `live_check`) are not runs."""
    previous = db.latest_collection_start(conn)
    if previous is None or now - previous[1] <= RUN_GAP_WARNING:
        return None
    run_id, started = previous
    hours, minutes = divmod(int((now - started).total_seconds() // 60), 60)
    return (f"the previous run (#{run_id}) started {hours} h {minutes:02d} min ago, more than "
            f"{RUN_GAP_WARNING.seconds // 3600} h: the 2-hourly schedule missed a run. Check the "
            "scheduler Worker (docs/runbooks/agendamento.md).")


def run_dormancy(ctx: Context, conn: sqlite3.Connection, summary: RunSummary,
                 now: datetime | None = None) -> list[Route]:
    """After a collection: routes without prices for `dormant_after_days` go dormant.

    Skipped when the whole run failed (an API outage must not put every route to sleep).
    """
    if summary.status == "failed":
        return []
    return routes.mark_dormant(conn, ctx.config.routes, now or db.utcnow())


# --- discover routes ------------------------------------------------------------

DISCOVERED_AT = "routes.discovered_at"     # meta key: last successful discovery (UTC ISO)


@dataclass(frozen=True)
class Discovery:
    applied: routes.Applied
    errors: list[str]                      # supplements that failed (a catalogue failure raises)
    photos: list[tuple[str, str]]          # (destination, result) for new photos
    photos_missing: int                    # destinations still without a photo


def last_discovery(conn: sqlite3.Connection) -> datetime | None:
    value = db.get_meta(conn, DISCOVERED_AT)
    return datetime.fromisoformat(value) if value else None


def discovery_due(ctx: Context, conn: sqlite3.Connection, now: datetime) -> bool:
    last = last_discovery(conn)
    return last is None or now - last >= timedelta(days=ctx.config.routes.discover_every_days)


def run_discover(ctx: Context, conn: sqlite3.Connection, now: datetime | None = None, *,
                 photos: bool = True, dry_run: bool = False) -> Discovery:
    """Fetch the catalogues, find every direct route from the configured origins, store it.

    The static catalogue is required (an error aborts before anything changes); the popular
    directions and the recent direct fares are supplements, so their errors are reported and
    the discovery goes on without them.
    """
    now = now or db.utcnow()
    cfg = ctx.config
    origins = cfg.routes.origins
    client = TravelpayoutsCatalogue(ctx.secrets.travelpayouts_token,
                                    currency=cfg.collector.currency, market=cfg.collector.market)
    payloads = client.static()
    catalogue = discovery.Catalogue.from_payloads(payloads.routes, payloads.airports,
                                                  payloads.cities_pt, origins)
    errors: list[str] = []
    popular: dict[str, dict] = {}
    recent: dict[str, list[dict]] = {}
    months = departure_months(now.astimezone(i18n_pt.LISBON).date(), cfg.collector.months_ahead)
    for origin in origins:
        try:
            popular[origin] = client.popular_directions(origin)
        except (TravelpayoutsError, httpx.HTTPError, ValueError) as exc:
            errors.append(f"popular directions {origin}: {exc}")
        for month in months:
            try:
                recent.setdefault(origin, []).append(client.recent_direct(origin, month))
            except (TravelpayoutsError, httpx.HTTPError, ValueError) as exc:
                errors.append(f"recent direct fares {origin} {month:%Y-%m}: {exc}")
    found = discovery.discover(catalogue, origins, popular=popular, recent=recent,
                               long_haul=routes.curated_long_haul(cfg.routes))
    applied = routes.apply_discovery(conn, cfg.routes, found, now, dry_run=dry_run)
    if dry_run:
        return Discovery(applied, errors, [], 0)
    db.set_meta(conn, DISCOVERED_AT, now.isoformat())
    done, missing = run_missing_photos(ctx, conn) if photos else ([], len(missing_photos(ctx, conn)))
    return Discovery(applied, errors, done, missing)


def run_discover_if_due(ctx: Context, conn: sqlite3.Connection,
                        now: datetime | None = None) -> Discovery | None:
    """The scheduled run's monthly discovery: runs when the last one is older than
    `routes.discover_every_days` (or never ran)."""
    now = now or db.utcnow()
    return run_discover(ctx, conn, now) if discovery_due(ctx, conn, now) else None


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
    low_prices: int = 0                 # low prices this run (shown on the route page, D24)


def run_detect(ctx: Context, conn: sqlite3.Connection, run_id: int | None = None,
               now: datetime | None = None) -> tuple[int | None, list[RouteDetection]]:
    """Evaluate the given (default: latest completed) run against each route's typical lows.

    Both tiers come from the offers seen in that run or later (D18, D24): low prices are
    counted (the website lists them, `route_low_prices`); promotion candidates, minus offers
    that already are a deal, become deals in status `new`.
    """
    cfg = ctx.config.detector
    now = now or db.utcnow()
    run_id = run_id or db.latest_completed_run_id(conn)
    if run_id is None:
        return None, []
    taken = db.deal_observation_ids(conn)
    run_obs = db.observations_seen_since(conn, run_id)

    results = []
    for route in routes.active_routes(conn, ctx.config.routes):
        offers = [o for o in run_obs if o.route_key == route.key]
        if not offers:
            results.append(RouteDetection(route.key, 0, None, None, "no_data", [], "no prices this run"))
            continue
        history = db.route_history(conn, route.origin, route.destination,
                                   since=now - timedelta(days=cfg.lookback_days), exclude_run_id=None)
        recent = db.recently_flagged_offers(conn, route.origin, route.destination,
                                            since=now - timedelta(days=cfg.dedupe_days))
        found = detector.detect(offers, history, recent, cfg, route.price_cap_eur, now,
                                cfg.max_deals_per_route, route.rules, taken=taken)
        deal_ids = [
            db.insert_deal(conn, observation_id=f.observation.id, rule=f.decision.rule,
                           baseline_median=f.baseline.median, sample_size=f.baseline.sample_size,
                           discount_pct=f.decision.discount_pct, threshold=cfg.threshold)
            for f in found.candidates
        ]
        open_offers = [o for o in offers if o.id not in taken]
        results.append(_summarise(route, open_offers, history, found, deal_ids, cfg, now))
    return run_id, results


def _summarise(route: Route, offers: list[Observation], history: list[Observation],
               found: detector.Detection, deal_ids: list[int], cfg, now: datetime) -> RouteDetection:
    flags, lows = found.candidates, len(found.low_prices)
    fresh = [o for o in detector.eligible(offers, route.rules) if detector.is_fresh(o, cfg, now)]
    if not fresh:
        kind = "direct " if route.rules.direct_only else ""
        return RouteDetection(route.key, 0, None, None, "no_fresh", [],
                              f"no {kind}price found in the last {cfg.max_offer_age_days} days",
                              lows)
    baselines = detector.month_baselines(history, cfg, now, route.rules)
    empty = detector.Baseline(None, 0, 0)

    def discount(o: Observation) -> float:
        base = baselines.get(detector.month_key(o), empty)
        return 1 - o.price / base.median if base.median else float("-inf")

    best = flags[0].observation if flags else max(fresh, key=lambda o: (discount(o), -o.price))
    base = baselines.get(detector.month_key(best), empty)
    decision = detector.evaluate(best, base, cfg, route.price_cap_eur)
    status = "deals" if deal_ids else decision.kind
    return RouteDetection(route.key, len(fresh), best, base, status, deal_ids, decision.reason,
                          lows)


def route_low_prices(ctx: Context, conn: sqlite3.Connection, route: Route,
                     history: list[Observation], now: datetime,
                     run_offers: list[Observation] | None = None) -> list[detector.LowPrice]:
    """The route's low prices in the latest completed run (D24), biggest discount first.

    `run_offers`: that run's offers (all routes) when the caller already loaded them.
    """
    if run_offers is None:
        run_id = db.latest_completed_run_id(conn)
        run_offers = db.observations_seen_since(conn, run_id) if run_id else []
    offers = [o for o in run_offers if o.route_key == route.key]
    return detector.low_prices(offers, history, ctx.config.detector, now, route.rules)


def route_history(ctx: Context, conn: sqlite3.Connection, route: Route,
                  now: datetime) -> list[Observation]:
    """The route's stored offers inside the typical low's lookback window."""
    return db.route_history(conn, route.origin, route.destination,
                            since=now - timedelta(days=ctx.config.detector.lookback_days),
                            exclude_run_id=None)

def shown_low_prices(ctx: Context, conn: sqlite3.Connection, route: Route,
                     history: list[Observation], now: datetime, run_offers: list[Observation],
                     promoted: set[int]) -> list[detector.LowPrice]:
    """The low prices a route page lists: the run's low prices minus the offers of live
    promotions (`promoted`, shown above them), at most `site.low_prices_per_route`."""
    lows = route_low_prices(ctx, conn, route, history, now, run_offers)
    shown = [lp for lp in lows if lp.observation.id not in promoted]
    return shown[: ctx.config.site.low_prices_per_route]


def current_baselines(ctx: Context, conn: sqlite3.Connection,
                      route: Route) -> dict[tuple[int, int], detector.Baseline]:
    """Typical low per departure month from all stored history (for `stats`)."""
    now = db.utcnow()
    return detector.month_baselines(route_history(ctx, conn, route, now), ctx.config.detector,
                                    now, route.rules)


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
    latest = db.observations_seen_since(conn, run_id)
    results = []
    for deal, obs in db.open_deals(conn):
        route_latest = [o for o in latest if o.route_key == obs.route_key]
        if obs.run_id >= run_id or not route_latest:
            continue
        rules = route_for(ctx, conn, obs.route_key).rules
        result = recheck(obs, route_latest, ctx.config.detector, now, rules=rules)
        db.record_recheck(conn, deal.id, valid=result.valid, latest_price=result.latest_price,
                          reason=result.reason, at=now)
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

def price_source(ctx: Context) -> TravelpayoutsSource:
    c = ctx.config.collector
    return TravelpayoutsSource(ctx.secrets.travelpayouts_token, currency=c.currency,
                               limit=c.limit_per_request, market=c.market,
                               booking_base=c.booking_base,
                               limiter=RateLimiter(c.requests_per_minute))


def _fetch_trip_month(ctx: Context, conn: sqlite3.Connection,
                      obs: Observation) -> tuple[Fetched, RouteRules]:
    """The deal's route and departure month, priced now (one request)."""
    rules = route_for(ctx, conn, obs.route_key).rules
    fetched = price_source(ctx).fetch(obs.origin, obs.destination,
                                      obs.departure_date.replace(day=1), rules=rules)
    return fetched, rules


CHECK_FAILED = "Não foi possível verificar o preço agora"


def check_failure(exc: Exception) -> str:
    """The reviewer's pt-PT reason when the provider couldn't price a deal: no English and no
    response text (that stays in the run's error / the log). The review Function says the same
    (web/functions/_lib/review/live-check.ts; cases in live-check-cases.json `failures`)."""
    if isinstance(exc, TravelpayoutsError) and exc.kind == "http" and exc.status == 429:
        why = "o Travelpayouts está a limitar os pedidos. Tenta daqui a um minuto"
    elif isinstance(exc, TravelpayoutsError) and exc.kind == "http":
        why = f"o Travelpayouts respondeu com o erro HTTP {exc.status}"
    elif isinstance(exc, TravelpayoutsError) and exc.kind == "api":
        why = "o Travelpayouts devolveu um erro"
    elif isinstance(exc, TravelpayoutsError) and exc.kind == "token":
        why = "falta o token do Travelpayouts (TRAVELPAYOUTS_TOKEN)"
    elif isinstance(exc, httpx.HTTPError):
        why = "o Travelpayouts não respondeu"
    else:
        why = "resposta inesperada do Travelpayouts"
    return f"{CHECK_FAILED}: {why}."


def live_check(ctx: Context, conn: sqlite3.Connection, deal_id: int,
               now: datetime | None = None) -> tuple[Deal, Recheck]:
    """Fetch this deal's route and departure month right now and recheck the price.

    Without R2 keys this database is the real one: the prices are stored as a `live_check` run
    (traceable like any other data) and a deal whose price moved expires immediately (a
    recheck, owned by the pipeline like `run_recheck`). With R2 keys it is a local copy a later
    pull sets aside, so the check only reports (`price_now`: nothing stored, no status change)
    and the next run's recheck expires the deal (D26).
    """
    try:
        deal, obs = db.get_deal(conn, deal_id)
    except KeyError:
        raise UnknownDeal(f"O deal {deal_id} não existe nesta base de dados.") from None
    if deal.status not in db.OPEN_STATUSES:
        raise ReviewError(f"O deal {deal_id} está '{STATUS_PT[deal.status]}' e já não é verificado.")
    if ctx.remote_store:
        return deal, price_now(ctx, conn, deal_id, now)
    run_id = db.start_run(conn, TravelpayoutsSource.name, scope="live_check")
    try:
        fetched, rules = _fetch_trip_month(ctx, conn, obs)
    except Exception as exc:
        db.finish_run(conn, run_id, status="failed", n_requests=1, n_observations=0, error=str(exc))
        raise ReviewError(check_failure(exc)) from exc
    fresh = fetched.observations
    stored = db.insert_observations(conn, run_id, fresh)
    archive.write_run(ctx.object_store, conn, run_id, [fetched.response])
    db.finish_run(conn, run_id, status="ok", n_requests=1, n_observations=len(fresh),
                  n_new=stored.new, error=None)
    now = now or db.utcnow()
    result = recheck(obs, fresh, ctx.config.detector, now, rules=rules)
    db.record_recheck(conn, deal_id, valid=result.valid, latest_price=result.latest_price,
                      reason=result.reason, at=now)
    if not result.valid:
        _mark_expired_outputs(ctx, deal_id, result.reason, now)
    return db.get_deal(conn, deal_id)[0], result


def price_now(ctx: Context, conn: sqlite3.Connection, deal_id: int,
              now: datetime | None = None) -> Recheck:
    """The approval gate: this deal's trip priced right now, same rule as the recheck.

    Stores nothing and changes no status, like the review Function (which has no database):
    a moved price refuses the approval, and the run's own recheck expires the deal (D26).
    """
    _, obs = db.get_deal(conn, deal_id)
    try:
        fetched, rules = _fetch_trip_month(ctx, conn, obs)
    except Exception as exc:
        raise ReviewError(check_failure(exc)) from exc
    return recheck(obs, fetched.observations, ctx.config.detector, now or db.utcnow(), rules=rules)


@dataclass(frozen=True)
class ReviewResult:
    """A review decision written as an event (D26)."""

    event: review_events.Event
    deal: Deal                                   # as the database has it now
    outcome: review_events.Outcome | None        # None: pending, applied by the next run (R2)
    check: Recheck | None = None                 # the live price check behind an approval


def pending_decisions(ctx: Context, conn: sqlite3.Connection) -> list[review_events.Event]:
    """Decisions written but not applied to this database yet, oldest first."""
    return review_events.pending(ctx.object_store, conn)


def ensure_current_copy(ctx: Context) -> None:
    """With R2 keys the bucket's database is the real one and this machine decides on a local
    copy: refuse (ReviewError) when the bucket has a newer generation than the copy came from,
    so a decision is never made on statuses a run has since changed (D26)."""
    if not ctx.remote_store:
        return
    remote = sync.remote_meta(ctx.object_store)
    if remote is None:
        return
    state = sync.read_state(ctx.sync_state_path)
    if state is None or remote.generation > state.generation:
        have = f"da geração {state.generation}" if state else "nunca sincronizada"
        raise ReviewError(f"A base de dados no bucket é mais recente (geração "
                          f"{remote.generation}; esta cópia é {have}): corre "
                          "`escapadinha store pull` primeiro.")


def _decidable(ctx: Context, conn: sqlite3.Connection, deal_id: int, kind: str,
               post_url: str | None = None) -> Deal:
    """Refuse up front what the applier would refuse now (same rules), so the reviewer hears
    it at once; the applier still re-checks against the status at application time."""
    ensure_current_copy(ctx)
    try:
        deal, _ = db.get_deal(conn, deal_id)
    except KeyError:
        raise UnknownDeal(f"O deal {deal_id} não existe nesta base de dados.") from None
    waiting = [e for e in pending_decisions(ctx, conn) if e.deal_id == deal_id]
    if waiting:
        e = waiting[-1]
        raise ReviewError(f"Já há uma decisão pendente para o deal {deal_id} "
                          f"({DECISION_PT[e.type]}, {e.actor}): é aplicada na próxima execução.")
    check_decision(kind, deal.status, affiliate_url=deal.affiliate_url, post_url=post_url)
    return deal


def _decide(ctx: Context, conn: sqlite3.Connection, event: review_events.Event,
            check: Recheck | None = None) -> ReviewResult:
    """Write the event. With a local database (no R2 keys) nothing else owns it, so apply at
    once; with R2 the next `run` applies it to the bucket's database."""
    review_events.write(ctx.object_store, event)
    outcome = None
    if not ctx.remote_store:
        outcome = next((o for o in apply_review_events(ctx, conn) if o.event_id == event.id), None)
    return ReviewResult(event, db.get_deal(conn, event.deal_id)[0], outcome, check)


def approve(ctx: Context, conn: sqlite3.Connection, deal_id: int, note: str | None = None, *,
            actor: str, now: datetime | None = None) -> ReviewResult:
    """Live price check, then an `approve` event carrying it. A moved price refuses (ReviewError
    with the reason) and writes nothing."""
    _decidable(ctx, conn, deal_id, "approve")
    now = now or db.utcnow()
    check = price_now(ctx, conn, deal_id, now)
    if not check.valid:
        raise ReviewError(f"O preço mudou ({check.reason}): não aprovado. "
                          "A próxima recolha expira o deal.")
    event = review_events.Event.new("approve", deal_id, actor=actor, now=now, note=note,
                                    live_check=review_events.LiveCheck.from_recheck(check, now))
    return _decide(ctx, conn, event, check)


def reject(ctx: Context, conn: sqlite3.Connection, deal_id: int, note: str | None = None, *,
           actor: str, now: datetime | None = None) -> ReviewResult:
    _decidable(ctx, conn, deal_id, "reject")
    event = review_events.Event.new("reject", deal_id, actor=actor, now=now or db.utcnow(),
                                    note=note)
    return _decide(ctx, conn, event)


def mark_published(ctx: Context, conn: sqlite3.Connection, deal_id: int,
                   post_url: str | None = None, *, actor: str,
                   now: datetime | None = None) -> ReviewResult:
    _decidable(ctx, conn, deal_id, "published", post_url)
    event = review_events.Event.new("published", deal_id, actor=actor, now=now or db.utcnow(),
                                    post_url=post_url)
    return _decide(ctx, conn, event)


def apply_review_events(ctx: Context, conn: sqlite3.Connection,
                        now: datetime | None = None) -> list[review_events.Outcome]:
    """First step of every run: apply pending review events (D26). Never raises for a bad event.
    Approve events older than `review.approve_max_age_hours` are refused."""
    max_age = timedelta(hours=ctx.config.review.approve_max_age_hours)
    return review_events.apply_pending(ctx.object_store, conn, now=now or db.utcnow(),
                                       durable=not ctx.remote_store, approve_max_age=max_age,
                                       plan_posts=_post_planner(ctx))


# --- posting queue (D32) --------------------------------------------------------

def _post_planner(ctx: Context) -> review_events.PlanPosts:
    """What an applied approval queues: Instagram at the next free daily slot, Telegram now."""
    cfg = ctx.config.posting

    def plan(conn: sqlite3.Connection, deal_id: int, now: datetime) -> list[tuple[str, datetime]]:
        due = {"instagram": posting.next_slot(now, db.post_due_times(conn, "instagram"),
                                              slots=cfg.slots, max_per_day=cfg.max_per_day),
               "telegram": now}
        return [(channel, due[channel]) for channel in posting.CHANNELS]
    return plan


@dataclass(frozen=True)
class PostResult:
    post: Post               # as stored after this step
    action: posting.PostAction
    reason: str | None = None


def _message(ctx: Context, conn: sqlite3.Connection, post: Post, deal: Deal,
             obs: Observation) -> posting.Message:
    view = text_view(ctx, conn, deal, obs)
    text = deal_caption_text(ctx, view) if post.channel == "instagram" else whatsapp_text(view)
    return posting.Message(post, deal, obs, f"{view.origin_city} → {view.destination_headline}",
                           view.price, text, deal.affiliate_url)


@dataclass(frozen=True)
class PublisherSetup:
    """What a publisher factory gets (`PUBLISHERS`): one run's context, database, HTTP client,
    clock, log and sleeper."""

    ctx: Context
    conn: sqlite3.Connection
    http: httpx.Client
    now: datetime
    log: Callable[[str], None]
    sleep: Callable[[float], None]


def _site_images(setup: PublisherSetup) -> dict:
    """The promotion's public JPEGs and their HEAD check, as both real publishers take them."""
    from escapadinha.website import image_problem, public_jpeg_urls   # imports this module
    return {"image_urls": lambda deal: public_jpeg_urls(setup.ctx, deal),
            "check_image": lambda url: image_problem(setup.http, url),
            "save": lambda post_id, **fields: db.save_post_progress(setup.conn, post_id, **fields)}


def _instagram_publisher(s: PublisherSetup) -> posting.Publisher:
    """Instagram (D36): needs both INSTAGRAM_* secrets and a usable token (refreshed here when
    due, every run, so a quiet week never lets it expire); else `Paused`."""
    secrets, api = s.ctx.secrets, s.ctx.config.instagram
    if not secrets.instagram_configured:
        return instagram.Paused("À espera do token: faltam INSTAGRAM_ACCESS_TOKEN e/ou "
                                f"INSTAGRAM_ACCOUNT_ID (.env ou secrets do GitHub, "
                                f"{instagram.RUNBOOK}).")
    try:
        token, problem = instagram.ensure_token(
            secrets.instagram_access_token.strip(), api, conn=s.conn, store=s.ctx.object_store,
            http=s.http, now=s.now, log=s.log)
    except Exception as exc:                # e.g. the store unreachable: never stops the run
        token, problem = None, (f"Não foi possível ler ou guardar o token do Instagram "
                                f"({type(exc).__name__}); as publicações esperam.")
    if token is None:
        s.log(f"Instagram: {problem}")
        return instagram.Paused(problem)
    return instagram.InstagramPublisher(
        instagram.Graph(s.http, api, token), secrets.instagram_account_id.strip(),
        **_site_images(s), now=s.now, images_wait=timedelta(hours=api.images_wait_hours),
        sleep=s.sleep, log=s.log, token_state=lambda problem: instagram.token_state(s.conn, problem))


def _telegram_publisher(s: PublisherSetup) -> posting.Publisher:
    """Telegram (D38): needs both TELEGRAM_* secrets, the channel an @handle or a numeric id;
    else `Paused` (posts wait, the run goes on)."""
    secrets = s.ctx.secrets
    if not secrets.telegram_configured:
        return posting.Paused("telegram", "À espera do bot: faltam TELEGRAM_BOT_TOKEN e/ou "
                                          "TELEGRAM_CHANNEL (.env ou secrets do GitHub, "
                                          f"{telegram.RUNBOOK}).")
    malformed = telegram.channel_problem(secrets.telegram_channel)
    if malformed:
        s.log(f"Telegram: {malformed}")
        return posting.Paused("telegram", malformed)
    return telegram.TelegramPublisher(
        telegram.BotApi(s.http, secrets.telegram_bot_token.strip()),
        secrets.telegram_channel.strip(),
        store=s.ctx.object_store, **_site_images(s), now=s.now,
        images_wait=timedelta(hours=s.ctx.config.telegram.images_wait_hours), log=s.log,
        problem=lambda reason: telegram.problem_state(s.conn, reason))


@dataclass(frozen=True)
class PublisherKind:
    """One publisher name of `posting.publishers` (config's `PublisherName`): how a run builds
    it, and what `queue list` says about it (pt-PT notices: a token, a channel, a send to
    confirm)."""

    build: Callable[[PublisherSetup], posting.Publisher]
    notices: Callable[[Context, sqlite3.Connection], list[str]] = lambda ctx, conn: []


# The one place a publisher is registered (a test checks config's `PublisherName` against it).
PUBLISHERS: dict[str, PublisherKind] = {
    "dry-run": PublisherKind(lambda s: posting.DryRunPublisher(s.log)),
    "instagram": PublisherKind(_instagram_publisher,
                               lambda ctx, conn: instagram.notices(conn)),
    "telegram": PublisherKind(_telegram_publisher,
                              lambda ctx, conn: telegram.notices(
                                  conn, ctx.object_store, ctx.secrets.telegram_channel)),
}


def publishers_for(ctx: Context, conn: sqlite3.Connection, http: httpx.Client, *,
                   now: datetime, log: Callable[[str], None],
                   sleep: Callable[[float], None]) -> dict[str, posting.Publisher]:
    """channel -> publisher, from `posting.publishers` in config, built by `PUBLISHERS`. A real
    publisher without its secrets (or token) is paused: its due posts wait, never settled by a
    dry run, so no post is lost (D36, D38)."""
    setup = PublisherSetup(ctx, conn, http, now, log, sleep)
    return {channel: PUBLISHERS[name].build(setup)
            for channel, name in ctx.config.posting.publishers.items()}


def publisher_notices(ctx: Context, conn: sqlite3.Connection) -> list[str]:
    """What `queue list` says about the configured publishers (pt-PT)."""
    names = dict.fromkeys(ctx.config.posting.publishers.values())
    return [notice for name in names for notice in PUBLISHERS[name].notices(ctx, conn)]


def retry_post(ctx: Context, conn: sqlite3.Connection, deal_id: int, channel: str, *,
               now: datetime | None = None) -> str:
    """`escapadinha queue retry`: Miguel checked the channel after a send whose answer was lost
    (D38) and the message isn't there: put the cancelled post back in the queue. Written to the
    object store; without R2 applied at once, with R2 by the next run (which owns the database).
    Raises `telegram.RetryRefused` (pt-PT) when there is nothing to put back."""
    now = now or db.utcnow()
    if channel != "telegram":
        raise telegram.RetryRefused("Só as publicações do Telegram voltam à fila assim (o "
                                    "Instagram encontra sozinho um post perdido).")
    deal, _ = db.get_deal(conn, deal_id)
    if deal.status not in WHATSAPP_STATUSES:
        raise telegram.RetryRefused(f"deal {deal_id}: a promoção já não está aprovada "
                                    f"({STATUS_PT[deal.status]}): não volta à fila.")
    telegram.request_retry(ctx.object_store, deal, now=now)
    if ctx.remote_store:
        return (f"deal {deal_id}: pedido registado; a próxima execução põe a publicação do "
                "Telegram de novo na fila.")
    telegram.apply_retries(conn, ctx.object_store, log=lambda line: None)
    return f"deal {deal_id}: a publicação do Telegram voltou à fila e sai na próxima execução."


def _run_stories(ctx: Context, conn: sqlite3.Connection, publishers: dict[str, posting.Publisher],
                 now: datetime, log: Callable[[str], None]) -> None:
    """Pending stories of published carousels (D36): skipped once `posting.story_verdict` says
    so or after `posting.max_attempts` errors; a wait counts nothing. Never touches the post."""
    cfg = ctx.config.posting
    max_check_age = timedelta(hours=cfg.max_check_age_hours)
    Story = posting.StoryStatus
    for post in db.posts(conn, "published"):
        publisher = publishers.get(post.channel)
        if post.story_status != Story.PENDING or not isinstance(publisher, posting.StoryPublisher):
            continue
        deal, _ = db.get_deal(conn, post.deal_id)
        what = f"Story Instagram deal {post.deal_id}"
        verdict = posting.story_verdict(post, deal, now=now, max_check_age=max_check_age)
        if verdict.action is posting.VerdictAction.CANCEL:
            db.save_post_progress(conn, post.id, story_status=Story.SKIPPED,
                                  story_note=verdict.reason)
            log(f"{what}: não sai ({verdict.reason})")
            continue
        done = posting.attempt(lambda: publisher.publish_story(post, deal))
        if done.wait:
            db.save_post_progress(conn, post.id, story_note=done.wait)
            log(f"{what}: à espera ({done.wait})")
        elif done.cancel:
            db.save_post_progress(conn, post.id, story_status=Story.SKIPPED,
                                  story_note=done.cancel)
            log(f"{what}: não sai ({done.cancel})")
        elif done.error:
            attempts = db.story_fails(conn, post.id, done.error)
            if attempts >= cfg.max_attempts:
                db.save_post_progress(conn, post.id, story_status=Story.SKIPPED,
                                      story_note=f"A story falhou {attempts} vezes: {done.error}")
                log(f"{what}: não sai (falhou {attempts} vezes: {done.error})")
            else:
                log(f"{what}: falhou ({done.error}), nova tentativa na próxima execução")
        else:
            db.save_post_progress(conn, post.id, story_status=Story.PUBLISHED,
                                  story_media_id=done.result, story_note=None)
            log(f"{what}: publicada")


def run_publish(ctx: Context, conn: sqlite3.Connection, now: datetime | None = None, *,
                log: Callable[[str], None] = print,
                publishers: dict[str, posting.Publisher] | None = None,
                sleep: Callable[[float], None] = time.sleep) -> list[PostResult]:
    """Every run, after `detect` and before `run_path.decide` (fast and full path, so after this
    run's recheck): cancel queued posts whose promotion can no longer go out, then publish the
    due ones whose price was verified recently (`posting.verdict`, D32). At most one Instagram
    post per run, so a backlog never goes out in a burst. A publisher error leaves the post
    queued; `posting.max_attempts` errors cancel it; a `PublishWait` (images not deployed yet,
    API limit, token, no secrets) waits without counting one. A real Instagram post writes a
    `published` decision and leaves its story pending, posted right after (`_run_stories`, D36);
    a Telegram message (D38) only settles its row (message link in `result_url`)."""
    now = now or db.utcnow()
    cfg = ctx.config.posting
    try:                              # Miguel's `queue retry` requests (D38) first
        telegram.apply_retries(conn, ctx.object_store, log=log)
    except Exception as exc:          # the store unreachable: never stops the run
        log(f"Telegram: os pedidos de `queue retry` não foram lidos ({type(exc).__name__}).")
    with httpx.Client(timeout=30) as http:
        publishers = publishers or publishers_for(ctx, conn, http, now=now, log=log, sleep=sleep)
        max_check_age = timedelta(hours=cfg.max_check_age_hours)
        results, instagram_done = [], False
        for post in db.posts(conn, "queued"):
            deal, obs = db.get_deal(conn, post.deal_id)
            verdict = posting.verdict(post, deal, now=now, max_check_age=max_check_age)
            if verdict.action is posting.VerdictAction.CANCEL:
                db.settle_post(conn, post.id, "cancelled", at=now, reason=verdict.reason)
                action, reason = posting.PostAction.CANCELLED, verdict.reason
            elif (verdict.action is posting.VerdictAction.LATER
                  or (post.channel == "instagram" and instagram_done)):
                continue
            elif verdict.action is posting.VerdictAction.WAIT:
                db.post_waits(conn, post.id, verdict.reason, failed=False)
                action, reason = posting.PostAction.WAITING, verdict.reason
            else:
                action, reason = _publish_one(ctx, conn, publishers[post.channel], post, deal,
                                              obs, now, log)
                instagram_done = instagram_done or (post.channel == "instagram" and action
                                                    is posting.PostAction.PUBLISHED)
            results.append(PostResult(db.get_post(conn, post.id), action, reason))
        _run_stories(ctx, conn, publishers, now, log)
    return results


def _publish_one(ctx: Context, conn: sqlite3.Connection, publisher: posting.Publisher,
                 post: Post, deal: Deal, obs: Observation, now: datetime,
                 log: Callable[[str], None]) -> tuple[posting.PostAction, str | None]:
    cfg = ctx.config.posting
    done = posting.attempt(lambda: publisher.publish(_message(ctx, conn, post, deal, obs)))
    if done.wait:
        db.post_waits(conn, post.id, done.wait, failed=False)
        return posting.PostAction.WAITING, done.wait
    if done.cancel:
        db.settle_post(conn, post.id, "cancelled", at=now, reason=done.cancel)
        return posting.PostAction.CANCELLED, done.cancel
    if done.error:                    # a channel being down never stops the run
        attempts = db.post_waits(conn, post.id, done.error, failed=True)
        if attempts >= cfg.max_attempts:
            reason = f"O publicador falhou {attempts} vezes: {done.error}"
            db.settle_post(conn, post.id, "cancelled", at=now, reason=reason)
            return posting.PostAction.CANCELLED, reason
        return posting.PostAction.FAILED, done.error
    published: posting.Published = done.result
    if published.marks_published:     # the promotion is out: a `published` decision (D26)
        try:
            mark_published(ctx, conn, deal.id, published.url,
                           actor=posting.publisher_actor(publisher.name), now=now)
        except Exception as exc:      # it is out: failing to record that never fails the post
            log(f"Deal {deal.id}: publicado, mas a decisão 'publicado' não foi escrita "
                f"({type(exc).__name__}: {exc}); marca-o com `escapadinha deal published`.")
    db.settle_post(conn, post.id, "published", at=now, publisher=publisher.name,
                   result_url=published.url)
    if published.story:
        db.save_post_progress(conn, post.id, story_status=posting.StoryStatus.PENDING)
    return posting.PostAction.PUBLISHED, None


def export_review_snapshot(ctx: Context, conn: sqlite3.Connection,
                           now: datetime | None = None) -> dict:
    """Last step of every run (fast or full): `review/snapshot.json` for any review UI (D26)."""
    from escapadinha import review_snapshot      # imports the site builder, which imports us
    return review_snapshot.export(ctx, conn, now or db.utcnow())


# --- photos -------------------------------------------------------------------

def photo_query(ctx: Context, route: Route) -> str:
    """`photos.queries` override, else the English city name (Pixabay tags are English),
    else the Portuguese name."""
    return ctx.config.photos.queries.get(route.destination) or route.city_en or route.city_pt


def photo_must(ctx: Context, route: Route) -> str | None:
    """City name the photo should be tagged with (also for `photos.queries` overrides: on
    2026-10-13 "Ankara Turkey" returned an Istanbul mosque)."""
    return route.city_en or route.city_pt


def photo_targets(ctx: Context, conn: sqlite3.Connection) -> dict[str, str]:
    """Destination key -> Pixabay search query, for every route destination plus extra config keys."""
    cfg = ctx.config
    targets = {r.destination: photo_query(ctx, r) for r in routes.all_routes(conn, cfg.routes)}
    for key, query in cfg.photos.queries.items():
        targets.setdefault(key, query)
    return targets


def missing_photos(ctx: Context, conn: sqlite3.Connection) -> dict[str, tuple[str, str | None]]:
    """Destinations of active routes without a cached photo -> (search query, must-tag)."""
    return {r.destination: (photo_query(ctx, r), photo_must(ctx, r))
            for r in routes.active_routes(conn, ctx.config.routes)
            if db.get_photo(conn, r.destination) is None}


def run_missing_photos(ctx: Context, conn: sqlite3.Connection,
                       limit: int | None = None) -> tuple[list[tuple[str, str]], int]:
    """Fetch a photo (with its credit) for up to `limit` destinations that have none.

    Returns (destination, result) per attempt and how many are still missing. A failure
    (no results, no key, HTTP error) is reported per destination and retried next time.
    """
    limit = ctx.config.photos.max_per_run if limit is None else limit
    targets = list(missing_photos(ctx, conn).items())
    if not targets or limit == 0:
        return [], len(targets)
    try:
        client = PixabayClient(ctx.secrets.pixabay_api_key)
    except PhotoSourceError as exc:                      # no key: one line, not one per destination
        return [(f"{len(targets)} destinos", f"skipped: {exc}")], len(targets)
    done = []
    for key, (query, must) in targets[:limit]:
        try:
            photo = fetch_photo(client, key, query, ctx.photos_dir, must=must)
        except (PhotoSourceError, httpx.HTTPError) as exc:
            done.append((key, f"failed ({query}): {exc}"))
            continue
        photo_files(ctx).put(ctx.photos_dir / photo.file_path)
        db.upsert_photo(conn, photo)
        done.append((key, f"{photo.photographer} ({photo.source_url})"))
    return done, len(missing_photos(ctx, conn))


def run_fetch_photos(ctx: Context, conn: sqlite3.Connection, dest: str | None, force: bool,
                     pick: int) -> list[tuple[str, str]]:
    targets = photo_targets(ctx, conn)
    if dest:
        dest = dest.upper()
        targets = {dest: targets.get(dest) or ctx.config.origin_name(dest)}
    musts = {r.destination: photo_must(ctx, r) for r in routes.all_routes(conn, ctx.config.routes)}
    client = PixabayClient(ctx.secrets.pixabay_api_key)
    done = []
    for key, query in targets.items():
        if not force and db.get_photo(conn, key) is not None:
            done.append((key, "cached"))
            continue
        photo = fetch_photo(client, key, query, ctx.photos_dir, pick=pick, must=musts.get(key))
        photo_files(ctx).put(ctx.photos_dir / photo.file_path)
        db.upsert_photo(conn, photo)
        done.append((key, f"{photo.photographer} ({photo.source_url})"))
    return done


def _photo(ctx: Context, conn: sqlite3.Connection, key: str | None) -> tuple[PhotoCredit, Path | None]:
    photo = db.get_photo(conn, key) if key else None
    if photo is None:
        return PhotoCredit.from_photo(None, None), None
    path = photo_files(ctx).file(photo.file_path) or ctx.photos_dir / photo.file_path
    return PhotoCredit.from_photo(photo, path.as_uri()), path


# --- files a fresh runner lacks (D25) -------------------------------------------------

def photo_files(ctx: Context) -> Mirror:
    """The Pixabay photo cache, also kept under `photos/` in the object store when R2 is set."""
    return Mirror(ctx.object_store if ctx.remote_store else None, ctx.photos_dir, "photos")


def output_files(ctx: Context) -> Mirror:
    """Rendered slides and captions, also kept under `output/` in the object store when R2 is set."""
    return Mirror(ctx.object_store if ctx.remote_store else None, ctx.output_dir, "output")


def deal_rel(output_path: str) -> str:
    """'<date>/deal-<O>-<D>-<id>' from a stored output path (absolute, written on any OS)."""
    return "/".join(PureWindowsPath(output_path).parts[-2:])


SLIDES = "slide_*.png"      # a rendered folder's slides (what the site and review pages show)


def deal_folder(ctx: Context, deal: Deal, files: str | None = "*") -> Path | None:
    """The deal's rendered folder. `files`: the glob of the files the caller reads; those only
    the object store has are downloaded first, each once per machine (D25). None: never
    download, only a folder this machine already has."""
    if not deal.output_path:
        return None
    local = Path(deal.output_path)
    if local.is_dir() and (files is None or any(local.glob(files))):
        return local
    rel = deal_rel(deal.output_path)
    if files is None:
        path = ctx.output_dir / rel
        return path if path.is_dir() else None
    return output_files(ctx).folder(rel, files)


def deal_slide_names(ctx: Context, deal: Deal) -> list[str]:
    """'slide_01.png', ... of the deal's rendered folder, local or listed in the object store,
    without downloading anything."""
    if not deal.output_path:
        return []
    local = deal_folder(ctx, deal, files=None)
    if local is not None:
        return sorted(p.name for p in local.glob(SLIDES))
    return output_files(ctx).names(deal_rel(deal.output_path), SLIDES)


def guide_folder(ctx: Context, slug: str, files: str = "*") -> Path | None:
    """The guide's latest rendered folder (`output/<date>/guia-<slug>`), local or stored
    (`files` as in `deal_folder`)."""
    name = f"guia-{slug}"
    local = sorted(ctx.output_dir.glob(f"*/{name}"))
    if local:
        return local[-1]
    mirror = output_files(ctx)
    dates = sorted({rel.split("/")[0] for rel in mirror.keys() if rel.split("/")[1:2] == [name]})
    return mirror.folder(f"{dates[-1]}/{name}", files) if dates else None


def mirror_local_files(ctx: Context, conn: sqlite3.Connection) -> list[str]:
    """Upload the photos and rendered folders this machine made before D25 that the object
    store lacks (a no-op without R2 keys or on a fresh runner). Returns the keys uploaded."""
    photos = {p.name: p for p in ctx.photos_dir.glob("*") if p.is_file()}
    outputs: dict[str, Path] = {}
    folders = [(deal_rel(d.output_path), Path(d.output_path))
               for d in db.deals_with_output(conn) if Path(d.output_path).is_dir()]
    folders += [(f.relative_to(ctx.output_dir).as_posix(), f)
                for f in ctx.output_dir.glob("*/guia-*") if f.is_dir()]
    for rel, folder in folders:
        outputs |= {f"{rel}/{p.relative_to(folder).as_posix()}": p
                    for p in folder.rglob("*") if p.is_file()}
    return photo_files(ctx).upload_missing(photos) + output_files(ctx).upload_missing(outputs)


# --- render -------------------------------------------------------------------

def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def ensure_affiliate_links(ctx: Context, conn: sqlite3.Connection,
                           pairs: list[tuple[Deal, Observation]]) -> list[tuple[Deal, Observation]]:
    """Generate (once) a tracked partner link per deal; failures are recorded, not hidden.

    Deals without a link are retried on every render. There is deliberately no fallback
    to a hand-built `marker=` URL: the program terms allow only network tools.
    """
    missing = [(d, o) for d, o in pairs if not d.affiliate_url and o.deep_link]
    if not missing:
        return pairs
    links = _partner_links(ctx, "instagram", [(d.id, o) for d, o in missing], sub_prefix="deal")
    for d, _ in missing:
        url, error = links[d.id]
        db.set_deal_affiliate(conn, d.id, url, error)
    return [db.get_deal(conn, d.id) for d, _ in pairs]


def _partner_links(ctx: Context, channel: str, items: list[tuple[int, Observation]],
                   sub_prefix: str) -> dict[int, tuple[str | None, str | None]]:
    """Tracked links for `channel`'s Travelpayouts Project: key -> (partner_url, error).

    `items` are (key, observation) pairs; the key (deal or observation id) also names the
    link's sub_id (`<sub_prefix>-<key>`). Always through `PartnerLinksClient`; a failure
    yields (None, reason), never a hand-built URL.
    """
    base = ctx.config.collector.booking_base
    made = _tracked_links(ctx, channel, [(booking_url(o.deep_link, base), f"{sub_prefix}-{key}")
                                         for key, o in items])
    return {key: made[booking_url(o.deep_link, base)] for key, o in items}


def _tracked_links(ctx: Context, channel: str, pairs: list[tuple[str, str]]
                   ) -> dict[str, tuple[str | None, str | None]]:
    """(brand url, sub_id) pairs -> url -> (partner_url, error), from `channel`'s Project.

    Always through `PartnerLinksClient`; a failure yields (None, reason), never a hand-built
    URL. Results are keyed by url, so one call must not ask for the same url twice.
    """
    project_id = ctx.config.affiliate.project_for(channel)
    if project_id is None:
        results, failure = {}, f"affiliate.projects.{channel} is not set in config.yaml"
    else:
        try:
            client = PartnerLinksClient(ctx.secrets.travelpayouts_token,
                                        marker=ctx.secrets.travelpayouts_marker,
                                        project_id=project_id, shorten=ctx.config.affiliate.shorten)
            results = client.create(pairs)
            failure = None
        except (AffiliateError, httpx.HTTPError) as exc:
            results, failure = {}, str(exc)
    out = {}
    for url, _ in pairs:
        link = results.get(url)
        out[url] = (link.partner_url if link else None, (link.error if link else failure) or None)
    return out


SITE_LINKS = "site.links"   # meta: website Project -> deal id -> {url, error} (D25)
SITE_PATHS = "site.paths"   # meta: stable page key -> every path it was published at (D19, D25)


def legacy_json(ctx: Context, name: str) -> dict:
    """A data/ file written before D25 (a CI runner has none; the PC keeps its last copy)."""
    path = ctx.db_path.parent / name
    return json.loads(path.read_text("utf-8")) if path.is_file() else {}


def site_links(ctx: Context, conn: sqlite3.Connection) -> dict[str, dict[str, dict]]:
    """Cached website links per Project and deal, from the database (synced to R2), with
    the entries of the old data/site_links.json it lacks merged in."""
    cache = db.get_meta_json(conn, SITE_LINKS)
    for project, entries in legacy_json(ctx, "site_links.json").items():
        for deal_id, entry in entries.items():
            cache.setdefault(project, {}).setdefault(deal_id, entry)
    return cache


def site_paths(ctx: Context, conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Redirect history from the database, with the old data/site_paths.json merged in
    (append-only, so merging it again changes nothing)."""
    history = db.get_meta_json(conn, SITE_PATHS)
    for key, paths in legacy_json(ctx, "site_paths.json").items():
        known = history.setdefault(key, [])
        known += [p for p in paths if p not in known]
    return history


def save_site_paths(conn: sqlite3.Connection, history: dict[str, list[str]]) -> None:
    db.set_meta(conn, SITE_PATHS, json.dumps(history, sort_keys=True))


def website_links(ctx: Context, conn: sqlite3.Connection, pairs: list[tuple[Deal, Observation]],
                  create: bool = True) -> dict[int, str | None]:
    """Booking link per deal for the website, from the website's Travelpayouts Project.

    Without a separate website Project (`affiliate.projects.website: null`) the site uses
    the deal's stored link, exactly as before. With one, a link per (Project, deal) is created
    once (sub_id `site-deal-<id>`) and cached in the database (`site_links`, D25); failures are
    retried on the next build and meanwhile fall back to the deal's own tracked link (also from
    the partner links API, only attributed to the Instagram Project). `create=False` only
    reads what is already cached (no API request, nothing written).
    """
    aff = ctx.config.affiliate
    project = aff.project_for("website")
    if project is None or project == aff.project_for("instagram"):
        return {d.id: d.affiliate_url for d, _ in pairs}
    cache = site_links(ctx, conn)
    known = cache.setdefault(str(project), {})
    missing = [(d, o) for d, o in pairs if o.deep_link and not known.get(str(d.id), {}).get("url")]
    if missing and create:
        made = _partner_links(ctx, "website", [(d.id, o) for d, o in missing], "site-deal")
        for deal_id, (url, error) in made.items():
            known[str(deal_id)] = {"url": url, "error": error}
    value = json.dumps(cache, sort_keys=True)
    if create and value != db.get_meta(conn, SITE_LINKS):   # new links, or the old file merged in
        db.set_meta(conn, SITE_LINKS, value)
    return {d.id: known.get(str(d.id), {}).get("url") or d.affiliate_url for d, _ in pairs}


ARTICLE_LINKS = "site.article_links"   # meta: website Project -> "<programme>:<article>" -> link (D37)


def block_targets(ctx: Context, published: list[Article]) -> dict[tuple[str, str], tuple[Article, str]]:
    """What gets an affiliate block link (D37): (article key, programme) -> (article, brand page)
    for every programme a published article lists that config.yaml configures. The page is
    `ProgrammeConfig.target`: the article's city page when config has one, else the brand's site."""
    aff = ctx.config.affiliate
    return {(a.key, name): (a, programme.target(a.destination))
            for a in published for name in a.affiliates
            if (programme := aff.programme(name)) is not None}


def article_links(ctx: Context, conn: sqlite3.Connection, published: list[Article],
                  create: bool = True) -> dict[tuple[str, str], str]:
    """Tracked link per `block_targets` pair of the published articles: (key, programme) ->
    partner link.

    Each link is created once through `PartnerLinksClient` for the website's Project, for the
    brand page with the article's sub_id (`roteiro-<slug>`, `dica-<slug>`), and stored in the
    database (meta `site.article_links`, D25: a CI runner keeps no files). A new page (config
    changed) gets a new link; failures are kept with their reason and retried by the next call
    that creates (the export of the next full path). Writing also forgets every other entry: of
    articles no longer published, programmes no longer listed or configured, other Projects. One
    API request per article (its programmes are different brands, and the client keys results
    by url). `create=False` only reads the stored links.
    """
    targets = block_targets(ctx, published)
    project = ctx.config.affiliate.project_for("website")
    if project is None:
        return {}
    known = db.get_meta_json(conn, ARTICLE_LINKS).get(str(project), {})

    def stored(key: str, programme: str) -> str | None:
        entry = known.get(f"{programme}:{key}", {})
        return entry.get("url") if entry.get("target") == targets[key, programme][1] else None

    if create:
        todo: dict[str, list[tuple[str, Article, str]]] = {}
        for (key, programme), (article, target) in targets.items():
            if not stored(key, programme):
                todo.setdefault(key, []).append((programme, article, target))
        for key, items in sorted(todo.items()):
            made = _tracked_links(ctx, "website", [(t, a.sub_id) for _, a, t in items])
            for programme, _, target in items:
                url, error = made[target]
                known[f"{programme}:{key}"] = {"target": target, "url": url, "error": error}
        kept = {f"{p}:{key}": known[f"{p}:{key}"] for key, p in targets if f"{p}:{key}" in known}
        value = json.dumps({str(project): kept} if kept else {}, sort_keys=True)
        if value != (db.get_meta(conn, ARTICLE_LINKS) or "{}"):
            db.set_meta(conn, ARTICLE_LINKS, value)
    return {(key, p): url for key, p in targets if (url := stored(key, p))}


LINK_RETENTION = timedelta(days=30)   # partner_links rows older than this are pruned


@dataclass(frozen=True)
class LowLinks:
    urls: dict[int, str]     # observation id -> tracked link (website Project)
    created: int             # links created in this call
    pending: int             # low prices still without a link (cap reached or API failure)


LINK_BUDGET = "site.link_budget"   # meta: {"run": collection run id, "used": links requested}


def _budget_used(conn: sqlite3.Connection) -> tuple[int | None, int]:
    """(latest completed run, new low-price links already requested against it)."""
    run_id = db.latest_completed_run_id(conn)
    spent = db.get_meta_json(conn, LINK_BUDGET)
    return run_id, spent.get("used", 0) if spent.get("run") == run_id else 0


def link_budget(ctx: Context, conn: sqlite3.Connection) -> int:
    """New low-price links still allowed for the latest collection run (D24, D27): the export
    spends first, the site build after it gets the rest; the next run starts a new budget."""
    return max(0, ctx.config.site.max_new_links_per_build - _budget_used(conn)[1])


def _spend_link_budget(conn: sqlite3.Connection, requested: int) -> None:
    run_id, used = _budget_used(conn)
    db.set_meta(conn, LINK_BUDGET, json.dumps({"run": run_id, "used": used + requested}))


def low_price_links(ctx: Context, conn: sqlite3.Connection, lows: list[detector.LowPrice],
                    now: datetime | None = None, create: bool = True) -> LowLinks:
    """A tracked booking link per low price, from the website's Travelpayouts Project (D24).

    Each link is created once per (observation, Project) through `PartnerLinksClient`
    (sub_id `site-low-<observation id>`) and stored in `partner_links`, so a build only asks
    the API for new low prices, biggest discounts first, within one budget per collection
    run: `site.max_new_links_per_build` links in all, shared by the run's site data export
    and site build (`link_budget`; 10 links per request, API limit 100 requests/min). Failed
    ones are retried on later runs. Low prices without a link are shown without a booking
    button; never a hand-built `marker=` URL. `create=False` only reads the stored links (no
    API request, nothing written).
    """
    now = now or db.utcnow()
    project = ctx.config.affiliate.project_for("website")
    usable = [lp.observation for lp in sorted(lows, key=lambda lp: -lp.discount_pct)
              if lp.observation.deep_link and lp.observation.id is not None]
    if project is None or not usable:
        return LowLinks({}, 0, len(lows))
    if create:
        db.prune_partner_links(conn, now - LINK_RETENTION)
    stored = db.partner_links(conn, project, [o.id for o in usable])
    todo = [o for o in usable if not stored.get(o.id, (None, None))[0]]
    todo = todo[: link_budget(ctx, conn)] if create else []
    if todo:
        made = _partner_links(ctx, "website", [(o.id, o) for o in todo], "site-low")
        db.save_partner_links(conn, project, made)
        _spend_link_budget(conn, len(todo))
        stored |= made
    urls = {oid: url for oid, (url, _) in stored.items() if url}
    return LowLinks(urls, sum(1 for o in todo if urls.get(o.id)),
                    sum(1 for lp in lows if lp.observation.id not in urls))


def deal_view(ctx: Context, conn: sqlite3.Connection, deal: Deal,
              obs: Observation) -> tuple[DealView, Path | None]:
    """What a deal's slides and caption show (with its destination photo, if cached)."""
    route = route_for(ctx, conn, obs.route_key)
    credit, photo_path = _photo(ctx, conn, obs.destination)
    view = build_deal_view(deal, obs, origin_city=ctx.config.origin_name(obs.origin),
                           destination_city=route.city_pt, photo=credit)
    return view, photo_path


def text_view(ctx: Context, conn: sqlite3.Connection, deal: Deal, obs: Observation) -> DealView:
    """`deal_view` for texts only (caption, WhatsApp, posts): the photo's credit without its
    file, so a runner downloads nothing (D25)."""
    route = route_for(ctx, conn, obs.route_key)
    return build_deal_view(deal, obs, origin_city=ctx.config.origin_name(obs.origin),
                           destination_city=route.city_pt,
                           photo=PhotoCredit.from_photo(db.get_photo(conn, obs.destination), None))


def deal_caption_text(ctx: Context, view: DealView) -> str:
    """A deal's Instagram caption, exactly as `render deals` writes it to caption.txt."""
    return deal_caption(view, brand_name=ctx.config.brand.handle.lstrip("@"))


WHATSAPP_STATUSES = ("approved", "published")   # a human approved it and it never expired


def whatsapp_for(deal: Deal, view: DealView) -> str | None:
    """The WhatsApp text of an approved (or published) promotion with a stored partner link,
    else None: an open, rejected or expired deal gets none (D32)."""
    if deal.status not in WHATSAPP_STATUSES or not deal.affiliate_url:
        return None
    return whatsapp_text(view)


def deal_whatsapp_text(ctx: Context, conn: sqlite3.Connection, deal: Deal,
                       obs: Observation) -> str | None:
    return whatsapp_for(deal, text_view(ctx, conn, deal, obs))


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
            view, photo_path = deal_view(ctx, conn, deal, obs)
            out_dir = out_root / f"deal-{obs.origin}-{obs.destination}-{deal.id}"
            renderer.render_deal(view, photo_path, out_dir)
            _write_text(out_dir / "caption.txt", deal_caption_text(ctx, view))
            meta = view.meta(deal, obs, ctx.config.collector.booking_base)
            meta["archive_key"] = db.run_archive_key(conn, obs.run_id)   # raw payload of run_id
            _write_text(out_dir / "meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
            output_files(ctx).put_tree(out_dir)            # the site build may run elsewhere
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
    output_files(ctx).put_tree(out_dir)
    return out_dir, guide.reviewed
