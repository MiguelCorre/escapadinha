"""Website data contract v1 (D27): the JSON files the Astro site (#13) is built from.

The schemas live in `contract/site/v1/*.schema.json`; this module writes data that
matches them, from the same database queries and detector rules as the Jinja site:

    meta.json            build metadata (contract version, generated_at, run id, settings)
    labels.json          pt-PT names the site cannot derive (airlines, airports, disclosure)
    origins.json         Portuguese departure airports
    routes.json          every route: rules, status, monthly typical lows and averages, cheapest
    destinations.json    destination hubs (city, airports, routes from Portugal, photo credit)
    promotions.json      approved deals, live and recently expired (paths, images, links)
    low-prices/XXX.json  one origin's low prices at date level, compact rows (explorer)
    pontes.json          upcoming Portuguese long weekends (holiday calendar, D31), page paths

Values are raw (ISO dates, UTC timestamps, euros as numbers); pt-PT formatting stays on
the site, from `labels.json`. Every price sits next to what it traces to: an observation
id, a route key (typical lows, recomputable from stored observations) or a deal id (D2).
Booking links only come from the partner links API (`pipeline.low_price_links`,
`pipeline.website_links`); the export never builds a URL itself.

Files are deterministic (sorted keys and rows, one array element per line, no other
whitespace): stable diffs, gzip-friendly. `generate_fixtures` derives the committed
fixtures from a read-only copy of the real database.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from escapadinha import detector, i18n_pt, pipeline, pontes, routes
from escapadinha.config import Context
from escapadinha.models import Deal, Observation, Route
from escapadinha.presentation import DISCLOSURE, SITE_DISCLOSURE
from escapadinha.storage import db
from escapadinha.website import (
    LIVE, deal_image_paths, ponte_path, promo_slug, public_deal_rows, route_slug, slugify,
)

VERSION = 1
TOP_FILES = ("meta.json", "labels.json", "origins.json", "routes.json", "destinations.json",
             "promotions.json", "pontes.json")
HOLIDAYS_SOURCE = ("Código do Trabalho, art. 234.º (feriados obrigatórios) e art. 235.º "
                   "(Terça-Feira de Carnaval, facultativo), na redação da Lei n.º 8/2016")
LOW_COLS = ["obs", "dest", "price", "dep", "ret", "found", "fetched", "airline", "stops",
            "airport", "typical", "link"]
ROW_BUDGET_BYTES = 160        # average bytes per low-price row (D27); tested
FIXTURE_LINK = "https://example.com/parceiro/"   # fixtures never hold a real partner link
FIXTURE_PHOTOGRAPHER = "Fotógrafo de exemplo"     # nor a person's name


# --- serialisation ----------------------------------------------------------------------

def _compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def dumps(doc: dict) -> str:
    """Compact JSON with sorted keys; each element of a top-level list on its own line."""
    parts = []
    for key in sorted(doc):
        value = doc[key]
        if isinstance(value, list) and value and isinstance(value[0], (dict, list)):
            body = "[\n" + ",\n".join(_compact(v) for v in value) + "\n]"
        else:
            body = _compact(value)
        parts.append(f"{_compact(key)}:{body}")
    return "{" + ",".join(parts) + "}\n"


def _eur(value: float) -> float | int:
    value = float(value)
    return int(value) if value.is_integer() else round(value, 2)


def _day(d) -> str | None:
    return d.isoformat() if d else None


def _code(value: str | None) -> str | None:
    return value.upper() if value else None


# --- the export ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Export:
    files: dict[str, dict]       # relative path -> document

    def write(self, out: Path) -> None:
        """Replace the contract's files in `out` (other files there are left alone)."""
        out.mkdir(parents=True, exist_ok=True)
        stale = [out / name for name in TOP_FILES] + list(out.glob("low-prices/*.json"))
        for old in stale:
            old.unlink(missing_ok=True)
        for rel, doc in sorted(self.files.items()):
            path = out / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(dumps(doc), encoding="utf-8", newline="\n")

    @property
    def counts(self) -> dict:
        return self.files["meta.json"]["counts"]


def default_dir(ctx: Context) -> Path:
    return ctx.root / ctx.config.site.data_dir


def export_site_data(ctx: Context, conn: sqlite3.Connection, out: Path | None = None,
                     now: datetime | None = None, *, new_links: bool = True) -> Export:
    """Export the website data into `out` (default `site.data_dir`).

    `new_links=False`: only links already stored are used (no partner API request).
    """
    export = build_export(ctx, conn, now, new_links=new_links)
    export.write(out or default_dir(ctx))
    return export


def build_export(ctx: Context, conn: sqlite3.Connection, now: datetime | None = None, *,
                 new_links: bool = True, only_routes: set[str] | None = None,
                 fixture: bool = False) -> Export:
    """Every contract file as a document. Creates missing partner links when `new_links`
    (from the run's link budget, `pipeline.link_budget`, D24); writes nothing else."""
    now = now or db.utcnow()
    cfg = ctx.config
    run_id = db.latest_completed_run_id(conn)
    run_offers = db.observations_seen_since(conn, run_id) if run_id else []
    by_route: dict[str, list[Observation]] = defaultdict(list)
    for o in run_offers:
        by_route[o.route_key].append(o)
    all_routes = sorted((r for r in routes.all_routes(conn, cfg.routes)
                         if only_routes is None or r.key in only_routes), key=lambda r: r.key)
    keys = {r.key for r in all_routes}
    observed = db.observation_counts(conn)

    # Typical lows, low prices and the cheapest fresh offer per route.
    months: dict[str, list[dict]] = {}
    cheapest: dict[str, Observation | None] = {}
    lows: dict[str, list[detector.LowPrice]] = defaultdict(list)    # origin -> low prices
    for route in all_routes:
        history = pipeline.route_history(ctx, conn, route, now)
        baselines = detector.month_baselines(history, cfg.detector, now, route.rules)
        months[route.key] = [_month(m, b, cfg.detector) for m, b in sorted(baselines.items())]
        offers = by_route.get(route.key, [])
        fresh = [o for o in detector.eligible(offers, route.rules)
                 if detector.is_fresh(o, cfg.detector, now)]
        cheapest[route.key] = min(fresh, key=lambda o: (o.price, o.departure_date, o.id),
                                  default=None)
        lows[route.origin] += detector.low_prices(offers, history, cfg.detector, now,
                                                  route.rules, baselines)

    # Per-origin row cap (size budget): biggest discounts kept.
    cap = cfg.site.max_low_prices_per_origin
    kept: dict[str, list[detector.LowPrice]] = {}
    truncated: dict[str, int] = {}
    for origin, items in lows.items():
        items = sorted(items, key=lambda lp: (-lp.discount_pct, lp.observation.price,
                                              lp.observation.id))
        kept[origin], truncated[origin] = items[:cap], max(0, len(items) - cap)
    low_links = pipeline.low_price_links(ctx, conn, [lp for v in kept.values() for lp in v],
                                         now, create=new_links).urls

    deals = [(d, o) for d, o in public_deal_rows(conn)
             if o.route_key in keys and _in_window(d, now, cfg.site.expired_promotions_days)]
    live = [(d, o) for d, o in deals if d.status in LIVE]
    deal_links = pipeline.website_links(ctx, conn, live, create=new_links) if live else {}

    route_by_key = {r.key: r for r in all_routes}
    low_count = defaultdict(int)
    for items in kept.values():
        for lp in items:
            low_count[lp.observation.route_key] += 1
    promo_count = defaultdict(lambda: [0, 0])
    for d, o in deals:
        promo_count[o.route_key][0 if d.status in LIVE else 1] += 1

    origin_codes = list(dict.fromkeys(
        [o for o in cfg.routes.origins if any(r.origin == o for r in all_routes)]
        + sorted({r.origin for r in all_routes})))
    files: dict[str, dict] = {}
    files["routes.json"] = {"version": VERSION, "routes": [
        _route(ctx, r, months[r.key], cheapest[r.key], observed.get(r.key, 0),
               low_count[r.key], *promo_count[r.key]) for r in all_routes]}
    files["origins.json"] = {"version": VERSION, "origins": [
        _origin(ctx, code, all_routes, low_count, promo_count) for code in origin_codes]}
    files["destinations.json"] = {"version": VERSION,
                                  "destinations": _destinations(conn, all_routes)}
    promotions = sorted(deals, key=lambda p: (p[0].detected_at, p[0].id), reverse=True)
    files["promotions.json"] = {"version": VERSION, "promotions": [
        _promotion(ctx, conn, d, o, route_by_key[o.route_key], deal_links.get(d.id))
        for d, o in promotions]}
    for code in origin_codes:
        files[f"low-prices/{code}.json"] = {
            "version": VERSION, "origin": code, "generated_at": db.utc_iso(now), "run": run_id,
            "cols": LOW_COLS, "truncated": truncated.get(code, 0),
            "rows": [_low_row(lp, low_links.get(lp.observation.id))
                     for lp in sorted(kept.get(code, []), key=_row_order)]}
    files["labels.json"] = _labels()
    files["pontes.json"] = _pontes(ctx, now, origin_codes)
    files["meta.json"] = _meta(ctx, conn, now, run_id, fixture, origin_codes, files)
    return Export(files)


# --- committed fixtures ---------------------------------------------------------------------

def fixtures_dir(ctx: Context) -> Path:
    return ctx.root / "contract" / "site" / "v1" / "fixtures"


def generate_fixtures(ctx: Context, db_path: Path, out: Path | None = None) -> Export:
    """The committed fixture set: a small, anonymous export of the real database.

    The database file is opened read-only and copied into memory; nothing is written to it
    and no API is called. On that copy only: when no human approved a deal yet, the newest
    deal is marked live and another expired one as approved before it expired, so the site
    can test both states (prices stay the deals' real observations). The windows are those
    of the latest run (`now` = when it finished). A few routes are kept (`fixture_routes`)
    and every booking link becomes a placeholder (`anonymize`).
    """
    source = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    conn = sqlite3.connect(":memory:")
    source.backup(conn)
    source.close()
    conn.row_factory = sqlite3.Row
    db.init(conn)                                    # migrate the copy, never the file
    routes.sync(conn, ctx.config.routes, db.utcnow())
    _fixture_promotions(conn)
    run_id = db.latest_completed_run_id(conn)
    now = (db.run_finished_at(conn, run_id) if run_id else None) or db.utcnow()
    full = build_export(ctx, conn, now, new_links=False, fixture=True)
    export = anonymize(build_export(ctx, conn, now, new_links=False, fixture=True,
                                    only_routes=fixture_routes(full)))
    export.write(out or fixtures_dir(ctx))
    return export


def _fixture_promotions(conn: sqlite3.Connection) -> None:
    public = public_deal_rows(conn)
    newest_first = [(deal_id, status) for deal_id, status, _ in reversed(db.deal_states(conn))]
    used = {d.id for d, _ in public}
    if newest_first and not any(d.status in LIVE for d, _ in public):
        pick = next((i for i, _ in newest_first if i not in used), None)
        if pick:
            db.fixture_mark_live(conn, pick)
            used.add(pick)
    if not any(d.status == "expired" for d, _ in public):
        pick = next((i for i, s in newest_first if i not in used and s == "expired"), None)
        if pick:
            db.fixture_mark_reviewed(conn, pick)


def fixture_routes(export: Export, origins: int = 3, per_origin: int = 3) -> set[str]:
    """A few routes that show every state: the busiest origins' routes with promotions, low
    prices and prices first, plus a long-haul, a domestic, a dormant route and one without
    a typical low yet, when the data has them."""
    files = export.files
    all_routes = files["routes.json"]["routes"]
    promoted = {p["route"] for p in files["promotions.json"]["promotions"]}

    def score(r: dict):
        return (r["key"] in promoted, r["counts"]["low_prices"], r["cheapest"] is not None,
                r["counts"]["observations"], r["key"])

    totals = defaultdict(int)
    for r in all_routes:
        totals[r["origin"]] += r["counts"]["observations"]
    busiest = sorted(totals, key=lambda o: (-totals[o], o))[:origins]
    keys = set(promoted)
    for origin in busiest:
        mine = sorted((r for r in all_routes if r["origin"] == origin), key=score, reverse=True)
        keys |= {r["key"] for r in mine[:per_origin]}
    extras = [
        lambda r: r["kind"] == "long_haul", lambda r: r["kind"] == "domestic",
        lambda r: r["status"] == "dormant",
        lambda r: not any(m["typical_low"] for m in r["months"]),
    ]
    for wanted in extras:
        if not any(wanted(r) for r in all_routes if r["key"] in keys):
            found = sorted((r for r in all_routes if wanted(r)), key=score, reverse=True)
            keys |= {r["key"] for r in found[:1]}
    return keys


def anonymize(export: Export) -> Export:
    """Placeholder links (`FIXTURE_LINK` + the sub_id the pipeline would use) in place of real
    partner links, on every live promotion and every low price, so the fixtures show the
    tracked-link state without account data; photographers' names become a placeholder."""
    files = json.loads(json.dumps(export.files))
    for p in files["promotions.json"]["promotions"]:
        p["booking_link"] = f"{FIXTURE_LINK}site-deal-{p['id']}" if p["live"] else None
    for d in files["destinations.json"]["destinations"]:
        if d["photo"]:
            d["photo"] |= {"photographer": FIXTURE_PHOTOGRAPHER,
                           "photographer_url": "https://pixabay.com/users/exemplo/"}
    link = LOW_COLS.index("link")
    for rel, doc in files.items():
        if rel.startswith("low-prices/"):
            for row in doc["rows"]:
                row[link] = f"{FIXTURE_LINK}site-low-{row[0]}"
    return Export(files)


# --- documents ---------------------------------------------------------------------------

def _month(month: detector.Month, base: detector.Baseline, cfg) -> dict:
    mature = detector.is_mature(base, cfg)
    return {"month": f"{month[0]:04d}-{month[1]:02d}", "days": base.sample_size,
            "typical_low": _eur(base.median) if mature else None,
            "average": _eur(base.mean) if mature else None}


def _offer(o: Observation) -> dict:
    return {"obs": o.id, "route": o.route_key, "price": _eur(o.price),
            "departure": _day(o.departure_date), "return": _day(o.return_date),
            "nights": o.nights, "airline": _code(o.airline), "transfers": o.transfers,
            "return_transfers": o.return_transfers,
            "arrival_airport": _code(o.destination_airport),
            "found_date": _day(o.found_date), "fetched_at": db.utc_iso(o.fetched_at)}


def _route(ctx: Context, r: Route, months: list[dict], cheapest: Observation | None,
           observations: int, low_prices: int, live: int, expired: int) -> dict:
    origin_city = ctx.config.origin_name(r.origin)
    return {
        "key": r.key, "origin": r.origin, "destination": r.destination, "city": r.city_pt,
        "city_en": r.city_en, "kind": r.kind, "status": r.status,
        "airports": sorted(a for a in (r.destination_airports or "").split(",") if a),
        "rules": r.rules.to_json(),
        "path": f"/voos/{route_slug(origin_city, r.city_pt)}/", "months": months,
        "cheapest": _offer(cheapest) if cheapest else None,
        "counts": {"observations": observations, "low_prices": low_prices,
                   "promotions_live": live, "promotions_expired": expired},
        "discovered_at": db.utc_iso(r.discovered_at), "last_observed_at": db.utc_iso(r.last_observed_at),
    }


def _origin(ctx: Context, code: str, all_routes: list[Route], low_count, promo_count) -> dict:
    mine = [r for r in all_routes if r.origin == code]
    name = ctx.config.origin_name(code)
    return {"iata": code, "name": name, "slug": slugify(name),
            "routes": {"active": sum(r.status == "active" for r in mine),
                       "dormant": sum(r.status == "dormant" for r in mine)},
            "low_prices": sum(low_count[r.key] for r in mine),
            "promotions_live": sum(promo_count[r.key][0] for r in mine)}


def _destinations(conn: sqlite3.Connection, all_routes: list[Route]) -> list[dict]:
    grouped: dict[str, list[Route]] = defaultdict(list)
    for r in all_routes:
        grouped[r.destination].append(r)
    out = []
    for code, rs in sorted(grouped.items()):
        first = rs[0]
        photo = db.get_photo(conn, code)
        out.append({
            "code": code, "city": first.city_pt,
            "city_en": next((r.city_en for r in rs if r.city_en), None),
            "slug": slugify(first.city_pt), "kinds": sorted({r.kind for r in rs}),
            "airports": sorted({a for r in rs for a in (r.destination_airports or "").split(",")
                                if a}),
            "routes": sorted(r.key for r in rs),
            "photo": None if photo is None else {
                "file": photo.file_path, "photographer": photo.photographer,
                "photographer_url": photo.photographer_url, "source": photo.source.capitalize(),
                "source_url": photo.source_url, "license": photo.license},
        })
    return out


def _in_window(deal: Deal, now: datetime, days: int) -> bool:
    """Live promotions always; expired ones until `days` after they expired (the recheck that
    expired them is their last check)."""
    if deal.status in LIVE:
        return True
    expired_at = deal.last_checked_at or deal.detected_at
    return now - expired_at <= timedelta(days=days)


def _latest_seen(conn: sqlite3.Connection, deal: Deal, o: Observation) -> dict | None:
    """The recheck's price with the stored observation of the same trip that has it."""
    if deal.last_seen_price is None:
        return None
    seen = db.trip_observation_at(conn, o, deal.last_seen_price)
    return {"obs": seen.id, "price": _eur(seen.price)} if seen else None


def _promotion(ctx: Context, conn: sqlite3.Connection, d: Deal, o: Observation, route: Route,
               link: str | None) -> dict:
    live = d.status in LIVE
    images = deal_image_paths(ctx, d)
    return {
        "id": d.id, "route": o.route_key, "status": d.status, "live": live,
        "path": f"/promos/{promo_slug(d.id, ctx.config.origin_name(o.origin), route.city_pt)}/",
        "offer": _offer(o),
        "typical_low": None if d.baseline_median is None else _eur(d.baseline_median),
        "baseline_days": d.sample_size, "rule": d.rule,
        "discount_pct": None if d.discount_pct is None else round(d.discount_pct, 4),
        "detected_at": db.utc_iso(d.detected_at), "approved_at": db.utc_iso(d.reviewed_at),
        "published_at": db.utc_iso(d.published_at),
        "checked_at": db.utc_iso(d.last_checked_at or o.fetched_at),
        "booking_link": link if live else None,
        "expired": None if live else {"reason": d.expired_reason,
                                      "latest": _latest_seen(conn, d, o)},
        "images": None if images is None else dict(zip(("slides", "thumb", "og"), images)),
    }


def _row_order(lp: detector.LowPrice):
    o = lp.observation
    return (o.departure_date, o.return_date, o.destination, o.price, o.id)


def _stops(o: Observation) -> int | None:
    if o.transfers is None or o.return_transfers is None:
        return None
    return max(o.transfers, o.return_transfers)


def _low_row(lp: detector.LowPrice, link: str | None) -> list:
    o = lp.observation
    return [o.id, o.destination, _eur(o.price), _day(o.departure_date), _day(o.return_date),
            _day(o.found_date), db.utc_iso(o.fetched_at, minutes=True), _code(o.airline), _stops(o),
            _code(o.destination_airport), _eur(lp.baseline.median), link]


def _labels() -> dict:
    return {
        "version": VERSION, "airlines": dict(i18n_pt.AIRLINES),
        "airports": {code: {"name": name, "remote": code in i18n_pt.REMOTE_AIRPORTS}
                     for code, name in i18n_pt.AIRPORTS.items()},
        "kinds": dict(i18n_pt.ROUTE_KIND), "route_status": dict(i18n_pt.ROUTE_STATUS),
        "months": list(i18n_pt.MONTHS), "months_short": list(i18n_pt.MONTHS_SHORT),
        "weekdays_short": list(i18n_pt.WEEKDAYS_SHORT),
        "disclosure": {"site": SITE_DISCLOSURE, "post": DISCLOSURE},
    }


def _pontes(ctx: Context, now: datetime, origin_codes: list[str]) -> dict:
    """Long weekends whose travel window has not ended (Lisbon date), with one page per origin."""
    today = now.astimezone(i18n_pt.LISBON).date()
    items = []
    for p in pontes.pontes(pontes.load_calendar(ctx.holidays_file)):
        if p.end < today:
            continue
        h = p.holiday
        items.append({
            "slug": p.slug, "name": p.name,
            "holiday": {"date": _day(h.day), "name": h.name, "optional": h.optional},
            "days_off": {"first": _day(p.first_off), "last": _day(p.last_off)},
            "bridge": _day(p.bridge), "window": {"start": _day(p.start), "end": _day(p.end)},
            "origins": [{"iata": code, "path": ponte_path(p.slug, ctx.config.origin_name(code)),
                         "title": f"{p.name} {i18n_pt.from_place(ctx.config.origin_name(code))}"}
                        for code in origin_codes],
        })
    return {"version": VERSION, "source": HOLIDAYS_SOURCE, "pontes": items}


def _meta(ctx: Context, conn: sqlite3.Connection, now: datetime, run_id: int | None,
          fixture: bool, origin_codes: list[str], files: dict[str, dict]) -> dict:
    det = ctx.config.detector
    run = None
    if run_id is not None:
        run = {"id": run_id, "finished_at": db.utc_iso(db.run_finished_at(conn, run_id))}
    promotions = files["promotions.json"]["promotions"]
    return {
        "version": VERSION, "generated_at": db.utc_iso(now), "fixture": fixture, "run": run,
        "currency": "EUR", "base_url": ctx.config.site.base_url,
        "detector": {"low_threshold": det.low_threshold, "threshold": det.threshold,
                     "min_saving_eur": det.min_saving_eur,
                     "min_baseline_days": det.min_baseline_days,
                     "max_offer_age_days": det.max_offer_age_days,
                     "lookback_days": det.lookback_days},
        "files": {"origins": "origins.json", "routes": "routes.json",
                  "destinations": "destinations.json", "promotions": "promotions.json",
                  "labels": "labels.json", "pontes": "pontes.json",
                  "low_prices": {c: f"low-prices/{c}.json" for c in origin_codes}},
        "counts": {"origins": len(origin_codes),
                   "routes": len(files["routes.json"]["routes"]),
                   "destinations": len(files["destinations.json"]["destinations"]),
                   "promotions_live": sum(p["live"] for p in promotions),
                   "promotions_expired": sum(not p["live"] for p in promotions),
                   "low_prices": sum(len(files[f"low-prices/{c}.json"]["rows"])
                                     for c in origin_codes)},
    }
