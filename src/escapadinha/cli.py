"""`escapadinha` command line. Every step can run on its own; `run` chains them."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from escapadinha import i18n_pt as pt
from escapadinha import pipeline, posting, review_events, routes, run_path
from escapadinha.affiliate import AffiliateError
from escapadinha.collector.travelpayouts import TravelpayoutsError
from escapadinha.photos import PhotoSourceError
from escapadinha.review import DECISION_PT, STATUS_PT, ReviewError
from escapadinha.website import node
from escapadinha.website.node import BuildError
from escapadinha.website.deploy import DeployError
from escapadinha.config import ConfigError, Context
from escapadinha.storage import db, sync
from escapadinha.storage.objects import LockHeld
from escapadinha.storage.s3 import STORE_ERRORS

app =typer.Typer(help="Travel deals from Portugal: collect → detect → render → post (Instagram "
                       "via the Graph API, Telegram via the Bot API, once their secrets are set).",
                  no_args_is_help=True, pretty_exceptions_enable=False)
photos_app = typer.Typer(help="Destination photo cache (Pixabay).", no_args_is_help=True)
render_app = typer.Typer(help="Render Instagram slides + captions into ./output/<date>/.",
                         no_args_is_help=True)
site_app = typer.Typer(help="Public website (the Astro package in web/): build, preview, deploy "
                            "(Cloudflare Pages), crawl.",
                       no_args_is_help=True)
deal_app = typer.Typer(help="Approval queue actions (same rules as the review page).",
                       no_args_is_help=True)
routes_app = typer.Typer(help="Watched routes (stored in the database).", no_args_is_help=True)
app.add_typer(photos_app, name="photos")
app.add_typer(routes_app, name="routes")
app.add_typer(render_app, name="render")
app.add_typer(deal_app, name="deal")
app.add_typer(site_app, name="site")
design_app = typer.Typer(help="Design exploration pages built from real data (M2).",
                         no_args_is_help=True)
app.add_typer(design_app, name="design")
store_app = typer.Typer(help="Database sync with the R2 bucket (pull, push, status, check).",
                        no_args_is_help=True)
app.add_typer(store_app, name="store")
export_app = typer.Typer(help="Website data contract v1 (contract/site/v1): JSON for the Astro site.",
                         no_args_is_help=True)
app.add_typer(export_app, name="export")
queue_app = typer.Typer(help="Posting queue (D32): Instagram slots and Telegram posts after approval.",
                        no_args_is_help=True)
app.add_typer(queue_app, name="queue")
instagram_app = typer.Typer(help="Instagram publisher (D36): the refreshed token.",
                            no_args_is_help=True)
app.add_typer(instagram_app, name="instagram")

console = Console()


def _ctx():
    ctx = Context()
    return ctx, pipeline.open_db(ctx)


@app.command("init-db")
def init_db() -> None:
    """Create (or migrate) the SQLite database."""
    ctx, conn = _ctx()
    console.print(f"Database ready at [bold]{ctx.db_path}[/] (schema v{db.SCHEMA_VERSION})")


@app.command()
def collect() -> None:
    """Fetch round-trip prices for every active route and store them."""
    if _collect().status == "failed":
        raise typer.Exit(1)


def _collect():
    """Collect and report; a request that fails is listed and the others go on (D25)."""
    ctx, conn = _ctx()
    summary = pipeline.run_collect(ctx, conn)
    console.print(f"Run #{summary.run_id}: [bold]{summary.status}[/] · {summary.plan.describe()} · "
                  f"{summary.n_requests} requests · {summary.n_observations} offers "
                  f"({summary.n_new} new, {summary.n_repeated} seen before) · "
                  f"archive {summary.archive_key or '[red]missing[/]'}")
    for err in summary.errors:
        console.print(f"  [red]✗[/] {err}")
    dormant = pipeline.run_dormancy(ctx, conn, summary)
    if dormant:
        days = ctx.config.routes.dormant_after_days
        console.print(f"{len(dormant)} rotas adormecidas (sem preços há {days} dias): "
                      + ", ".join(r.key for r in dormant))
    return summary


@app.command()
def detect(run_id: Annotated[int | None, typer.Option(help="Run to evaluate (default: latest)")] = None) -> None:
    """Two tiers per route: low prices (counted; route pages list them) and promotion
    candidates (become deals for review)."""
    ctx, conn = _ctx()
    run_id, results = pipeline.run_detect(ctx, conn, run_id)
    if run_id is None:
        console.print("No completed collection run yet. Run [bold]escapadinha collect[/] first.")
        raise typer.Exit(1)
    table = Table(title=f"Detection for run #{run_id}")
    for col in ("Route", "Fresh", "Best offer", "Typical low", "Baseline", "Result", "Lows", "Deals"):
        table.add_column(col, no_wrap=True)
    labels = {"deals": "[green]deal[/]", "no_deal": "no deal",
              "insufficient_history": "[yellow]warming up[/]", "no_data": "[dim]no data[/]",
              "no_fresh": "[dim]no fresh[/]"}
    need = ctx.config.detector.min_baseline_days_promo     # promotions' maturity (D40)
    for r in results:
        best = "–" if r.best is None else f"{r.best.price:g} € ({r.best.departure_date:%d/%m})"
        low = "–" if r.baseline is None or r.baseline.median is None else f"{r.baseline.median:g} €"
        days = ("–" if r.baseline is None
                else f"{r.baseline.sample_size}/{need} days, span {r.baseline.span_days}")
        table.add_row(r.route, str(r.fresh), best, low, days, labels.get(r.status, r.status),
                      str(r.low_prices or "–"), ", ".join(map(str, r.deal_ids)) or "–")
    console.print(table)
    console.print(f"{sum(r.low_prices for r in results)} low prices, "
                  f"{sum(len(r.deal_ids) for r in results)} new promotion candidates.")
    # The queue against today's typical lows (D40): a deal that would not be detected now expires.
    for deal, obs, reason in pipeline.run_reevaluate(ctx, conn):
        console.print(f"  deal {deal.id} {obs.route_key} {obs.departure_date:%d/%m}–"
                      f"{obs.return_date:%d/%m} @ {obs.price:g} €: [red]✗ expirado[/] "
                      f"({escape(reason)})")


@app.command("recheck")
def recheck_cmd() -> None:
    """Re-verify open deals against the latest run; expire those whose price moved."""
    ctx, conn = _ctx()
    results = pipeline.run_recheck(ctx, conn)
    if not results:
        console.print("No open deals to recheck against a newer run.")
        return
    for deal, obs, r in results:
        mark = "[green]✓ válido[/]" if r.valid else "[red]✗ expirado[/]"
        console.print(f"  deal {deal.id} {obs.route_key} {obs.departure_date:%d/%m}–"
                      f"{obs.return_date:%d/%m} @ {obs.price:g} €: {mark} ({r.reason})")


@app.command()
def stats(route: Annotated[str, typer.Argument(help="e.g. LIS-LON")]) -> None:
    """Price history summary for one route."""
    ctx, conn = _ctx()
    r = pipeline.route_for(ctx, conn, route)
    row = db.route_stats(conn, r.origin, r.destination)
    if not row["n"]:
        console.print(f"No observations for {r.key} yet.")
        return
    console.print(f"{r.key}: {row['n']} distinct offers, seen {row['sightings']} times in total "
                  f"(most repeated: {row['max_seen']} runs), "
                  f"{row['min_price']:g}–{row['max_price']:g} €")
    det = ctx.config.detector
    console.print(f"Typical low per departure month (median of daily lows; a day counts with "
                  f"{det.min_dates_per_day}+ departure dates; low prices need "
                  f"{det.min_baseline_days} days, promotions {det.min_baseline_days_promo} "
                  f"spanning {det.min_baseline_span_days}):")
    for (year, month), base in sorted(pipeline.current_baselines(ctx, conn, r).items()):
        low = "–" if base.median is None else f"{base.median:g} €"
        spread = (f", daily lows {base.lowest.price:g}–{base.highest.price:g} €"
                  if base.lowest and base.highest else "")
        console.print(f"  {year}-{month:02d}: {low} from {base.sample_size} days "
                      f"(span {base.span_days}){spread}")


@routes_app.command("list")
def routes_list() -> None:
    """Every route with its kind, effective rules, status and last observation (pt-PT)."""
    ctx, conn = _ctx()
    cfg = ctx.config.routes
    table = Table(title="Rotas")
    for col in ("Rota", "Destino", "Tipo", "Escalas", "Noites", "Estado", "Última observação"):
        table.add_column(col, no_wrap=True)
    all_routes = routes.all_routes(conn, cfg)
    for r in all_routes:
        status = pt.ROUTE_STATUS[r.status]
        if cfg.excluded(r.origin, r.destination):
            status += " (excluída)"
        seen = pt.lisbon_timestamp(r.last_observed_at) if r.last_observed_at else "nunca"
        table.add_row(f"{r.origin} → {r.destination}", r.city_pt, pt.ROUTE_KIND[r.kind],
                      pt.stops_rule(r.rules.direct_only, r.rules.max_transfers),
                      pt.nights_range(r.rules.min_nights, r.rules.max_nights), status, seen)
    console.print(table)
    counts = routes.per_origin(all_routes, cfg)
    by_origin = Table(title="Rotas por origem")
    for col in ("Origem", "Ativas", "Adormecidas", "Excluídas", "Total"):
        by_origin.add_column(col, no_wrap=True)
    for origin, c in counts.items():
        by_origin.add_row(f"{origin} ({ctx.config.origin_name(origin)})", str(c["active"]),
                          str(c["dormant"]), str(c["excluded"]), str(sum(c.values())))
    console.print(by_origin)
    active = len(routes.active_routes(conn, cfg))
    dormant = sum(c["dormant"] for c in counts.values())
    last = pipeline.last_discovery(conn)
    console.print(f"{len(all_routes)} rotas, {active} ativas, {dormant} adormecidas. "
                  f"Última descoberta: {pt.lisbon_timestamp(last) if last else 'nunca'}.")


@routes_app.command("discover")
def routes_discover(
    photos: Annotated[bool, typer.Option("--photos/--no-photos",
                                         help="Fetch Pixabay photos for destinations without one")] = True,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would change, store nothing")] = False,
) -> None:
    """Discover direct routes from the configured origins (provider catalogues) and store them."""
    ctx, conn = _ctx()
    _print_discovery(ctx, pipeline.run_discover(ctx, conn, photos=photos, dry_run=dry_run), dry_run)


def _print_discovery(ctx, result: pipeline.Discovery, dry_run: bool = False) -> None:
    applied = result.applied
    origins = ctx.config.routes.origins
    found = {o: sum(1 for f in applied.found if f.origin == o) for o in origins}
    console.print(("[yellow]Simulação, nada foi guardado.[/] " if dry_run else "")
                  + "Rotas encontradas: " + " · ".join(f"{o} {n}" for o, n in found.items())
                  + f" (total {len(applied.found)})")
    for label, items in (("novas", applied.added), ("reativadas", applied.reactivated),
                         ("excluídas na config", applied.excluded)):
        if items:
            console.print(f"  {len(items)} {label}: "
                          + ", ".join(f"{f.key} {f.city_pt}" for f in items))
    for err in result.errors:
        console.print(f"  [yellow]![/] {err}")
    for key, outcome in result.photos:
        console.print(f"  foto {key}: {outcome}")
    if result.photos_missing:
        console.print(f"  [dim]{result.photos_missing} destinos ainda sem foto "
                      f"(cada recolha busca até {ctx.config.photos.max_per_run}).[/]")


@photos_app.command("fetch")
def photos_fetch(
    dest: Annotated[str | None, typer.Option(help="Only this destination key, e.g. LON")] = None,
    force: Annotated[bool, typer.Option(help="Replace an already cached photo")] = False,
    pick: Annotated[int, typer.Option(help="Use the N-th search result (0 = first)")] = 0,
) -> None:
    """Download and cache one photo per destination with its photographer credit."""
    ctx, conn = _ctx()
    for key, result in pipeline.run_fetch_photos(ctx, conn, dest, force, pick):
        console.print(f"  {key}: {result}")


@render_app.command("deals")
def render_deals(
    status: Annotated[str, typer.Option(help="Render deals with this status")] = "new",
    deal_id: Annotated[int | None, typer.Option(help="Render one deal by id")] = None,
) -> None:
    """Render deal carousels (3 slides) + caption.txt + meta.json."""
    ctx, conn = _ctx()
    rendered = pipeline.run_render_deals(ctx, conn, status, deal_id)
    if not rendered:
        console.print(f"No deals with status '{status}'.")
    for folder, deal in rendered:
        if deal.affiliate_url:
            console.print(f"  [green]✓[/] {folder}  [dim]{deal.affiliate_url}[/]")
        else:
            console.print(f"  [yellow]![/] {folder}  [yellow]no affiliate link: "
                          f"{deal.affiliate_error}[/] (retried on next render)")


@render_app.command("guide")
def render_guide(slug: Annotated[str, typer.Argument(help="File name in content/guides/ without .yaml")]) -> None:
    """Render a 'guia rápido' carousel from hand-written YAML content."""
    ctx, conn = _ctx()
    out_dir, reviewed = pipeline.run_render_guide(ctx, conn, slug)
    console.print(f"  [green]✓[/] {out_dir}")
    if not reviewed:
        console.print("  [yellow]![/] Guide is not marked reviewed: check the facts, then set "
                      "`reviewed: true` in the YAML.")


@app.command()
def review(
    port: Annotated[int, typer.Option(help="Local port")] = 8765,
    open_browser: Annotated[bool, typer.Option("--open/--no-open", help="Open the page")] = True,
) -> None:
    """Open the local approval queue (http://127.0.0.1:PORT). Ctrl+C to stop."""
    import threading
    import webbrowser

    import uvicorn

    from escapadinha.web import create_app

    url = f"http://127.0.0.1:{port}"
    console.print(f"Fila de aprovação em [bold]{url}[/] (Ctrl+C para parar)")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    uvicorn.run(create_app(Context()), host="127.0.0.1", port=port, log_level="warning")


def _print_check(deal, check) -> None:
    if check.valid:
        mark = "[green]✓ preço confirmado[/]"
    elif deal.status == "expired":
        mark = "[red]✗ expirado[/]"
    else:                                   # R2: report only, the run's recheck expires it (D26)
        mark = "[red]✗ o preço mudou[/]"
    console.print(f"  deal {deal.id}: {mark} ({check.reason}) → status {deal.status}")
    if not check.valid and deal.status != "expired":
        console.print("  Não guardado: a próxima recolha expira o deal (`escapadinha run`).")


@deal_app.command("check")
def deal_check(deal_id: int) -> None:
    """Fetch this deal's prices now and recheck it (with R2 keys: report only, the next run's
    recheck expires a deal whose price moved)."""
    ctx, conn = _ctx()
    _print_check(*pipeline.live_check(ctx, conn, deal_id))
    _print_posts(conn, deal_id)


def _print_decision(ctx, conn, decision: pipeline.ReviewResult) -> None:
    """What happened to the event just written, then every decision still pending (D26)."""
    o, deal = decision.outcome, decision.deal
    if o is None:
        console.print(f"  Decisão registada ({DECISION_PT[decision.event.type]}): aplicada na "
                      "próxima execução (`escapadinha run`).")
    elif o.applied:
        console.print(f"  deal {deal.id}: {STATUS_PT[deal.status]}")
    else:
        console.print(f"  [red]Decisão recusada:[/] {o.reason}")
    waiting = pipeline.pending_decisions(ctx, conn)
    if not waiting:
        console.print("Nenhuma decisão pendente.")
        return
    pending = pt.count(len(waiting), "decisão pendente", "decisões pendentes")
    console.print(f"{pending}: " + "; ".join(
        f"deal {e.deal_id}: {DECISION_PT[e.type]} ({e.actor}, {pt.lisbon_timestamp(e.created_at)})"
        for e in waiting))


@deal_app.command("approve")
def deal_approve(deal_id: int, note: Annotated[str | None, typer.Option()] = None) -> None:
    """Live price check, then an approval event (refused, writing nothing, if the price moved)."""
    ctx, conn = _ctx()
    decision = pipeline.approve(ctx, conn, deal_id, note, actor=review_events.local_actor("cli"))
    console.print(f"  deal {deal_id}: [green]✓ preço confirmado[/] ({decision.check.reason})")
    _print_decision(ctx, conn, decision)


@deal_app.command("reject")
def deal_reject(deal_id: int, note: Annotated[str | None, typer.Option()] = None) -> None:
    """Reject a deal (final): writes a reject event."""
    ctx, conn = _ctx()
    _print_decision(ctx, conn, pipeline.reject(ctx, conn, deal_id, note,
                                               actor=review_events.local_actor("cli")))


@deal_app.command("published")
def deal_published(deal_id: int, url: Annotated[str | None, typer.Option(help="Post URL")] = None) -> None:
    """Mark an approved deal as published: writes a published event."""
    ctx, conn = _ctx()
    _print_decision(ctx, conn, pipeline.mark_published(ctx, conn, deal_id, url,
                                                       actor=review_events.local_actor("cli")))


@site_app.command("build")
def site_build() -> None:
    """Build the website (web/dist) from the exported data: npm ci when needed, astro build,
    promotion images, _redirects and _headers. Run `export site-data` first."""
    _site_build(until=None)


def _site_build(until: float | None):
    """`site build` within the deadline `until` (the full path's, D35; None: a budget of its own).
    Returns the `astro.BuildSummary`."""
    from escapadinha.website import astro

    ctx, conn = _ctx()
    summary = astro.build(ctx, conn, until=until)
    pages = ", ".join(f"{n} {kind}" for kind, n in sorted(summary.pages.items()))
    console.print(f"Site built in [bold]{node.dist_dir(ctx)}[/] in {summary.seconds} s"
                  + (" (npm ci ran)" if summary.installed else "") + f": {pages}; "
                  f"{summary.images} promotion images, {summary.redirects} redirects, "
                  f"{summary.size_bytes / 1_000_000:.1f} MB")
    for skipped in summary.skipped_redirects:
        console.print(f"  [yellow]![/] redirect left out: {escape(skipped)}")
    for warning in summary.warnings:
        console.print(f"  [yellow]![/] {escape(warning)}")
    for path in summary.missing_images:
        console.print(f"  [yellow]![/] image missing (slides not rendered or stored): {path}")
    site = ctx.config.site
    if not site.on_final_domain:
        console.print(f"  [dim]Served at {site.base_url}; final domain {site.domain} not "
                      f"connected yet (docs/runbooks/brand-switch.md)[/]")
    return summary


@site_app.command("build-jinja")
def site_build_jinja() -> None:
    """Legacy (until #23 phase 2): the old Jinja site into ./site. Never deployed any more."""
    from escapadinha.website import build_site

    ctx, conn = _ctx()
    summary = build_site(ctx, conn)
    console.print(f"Site built in [bold]{ctx.site_dir}[/]: {summary['live_deals']} live deals, "
                  f"{summary['expired_pages']} expired pages, {summary['routes']} routes, "
                  f"{summary['guides']} guides, {summary['redirects']} redirects")
    console.print(f"  {summary['low_prices']} low prices on route pages: "
                  f"{summary['low_price_links_created']} new partner links, "
                  f"{summary['low_prices_without_link']} without a link yet")
    for skipped in summary["skipped_redirects"]:
        console.print(f"  [yellow]![/] redirect left out: {skipped}")
    site = ctx.config.site
    if not site.on_final_domain:
        console.print(f"  [dim]Served at {site.base_url}; final domain {site.domain} not "
                      f"connected yet (docs/runbooks/brand-switch.md)[/]")


@export_app.command("site-data")
def export_site_data(
    out: Annotated[Path | None, typer.Option(help="Directory (default: site.data_dir)")] = None,
    new_links: Annotated[bool, typer.Option(help="Create missing partner links (API)")] = True,
) -> None:
    """Write the website's JSON data (origins, routes, promotions, low prices per origin, ...)."""
    _export_site_data(out, new_links)


def _export_site_data(out: Path | None, new_links: bool):
    """`export site-data`; returns the `site_data.Export` written (the full path records it)."""
    from escapadinha import site_data

    ctx, conn = _ctx()
    out = out or site_data.default_dir(ctx)
    export = site_data.export_site_data(ctx, conn, out, new_links=new_links)
    counts = export.counts
    console.print(f"Site data written to [bold]{out}[/]: {counts['routes']} routes, "
                  f"{counts['origins']} origins, {counts['destinations']} destinations, "
                  f"{counts['promotions_live']} live + {counts['promotions_expired']} expired "
                  f"promotions, {counts['low_prices']} low prices, "
                  f"{len(export.files['affiliates.json']['links'])} affiliate block links")
    return export


@export_app.command("fixtures")
def export_fixtures(
    db_file: Annotated[Path | None, typer.Option("--db", help="Database to read (read-only)")] = None,
    out: Annotated[Path | None, typer.Option(help="Default: contract/site/v1/fixtures")] = None,
) -> None:
    """Regenerate the committed fixtures: a few routes of the real data, anonymous, no API calls."""
    from escapadinha import site_data

    ctx = Context()
    out = out or site_data.fixtures_dir(ctx)
    counts = site_data.generate_fixtures(ctx, db_file or ctx.db_path, out).counts
    console.print(f"Fixtures written to [bold]{out}[/]: {counts['routes']} routes, "
                  f"{counts['origins']} origins, {counts['promotions_live']} live + "
                  f"{counts['promotions_expired']} expired promotions, "
                  f"{counts['low_prices']} low prices")


@site_app.command("preview")
def site_preview(port: Annotated[int, typer.Option()] = 8766) -> None:
    """Serve the built site (web/dist) locally (http://127.0.0.1:PORT); _redirects not applied."""
    import functools
    import http.server

    ctx = Context()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(node.dist_dir(ctx)))
    console.print(f"Site preview at [bold]http://127.0.0.1:{port}[/] (Ctrl+C to stop)")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()


@site_app.command("crawl")
def site_crawl(
    sitemap: Annotated[str, typer.Option(help="Old sitemap: URL or file "
                                              "(e.g. a copy of the Jinja site's sitemap.xml)")],
    base: Annotated[str | None, typer.Option(help="Crawl this host instead of the sitemap's "
                                                  "(e.g. a preview deployment)")] = None,
    dist: Annotated[Path | None, typer.Option(help="Check a local build (its _redirects) "
                                                   "instead of the live site")] = None,
    pause: Annotated[float, typer.Option(help="Seconds between live requests")] = 0.2,
) -> None:
    """Every URL of a sitemap must answer 200, or 301 to a page that answers 200 (D35). Exits 1
    and lists the others."""
    from escapadinha.website import crawl

    with httpx.Client(timeout=30, headers={"User-Agent": "escapadinha-crawl"}) as client:
        urls = crawl.sitemap_urls(sitemap, client)
        results = (crawl.check_build(urls, dist) if dist
                   else crawl.check_live(urls, client, base=base, pause=pause))
    bad = [r for r in results if not r.ok]
    redirected = sum(r.ok and r.status == 301 for r in results)
    console.print(f"{len(results)} URLs: {len(results) - len(bad)} ok "
                  f"({redirected} by a 301), {len(bad)} broken")
    for r in bad:
        console.print(f"  [red]✗[/] {escape(r.path)} {r.status} {escape(r.detail)}")
    if bad:
        raise typer.Exit(1)


@site_app.command("setup")
def site_setup() -> None:
    """One-time: create the Cloudflare Pages project."""
    from escapadinha.website.deploy import create_project

    console.print(create_project(Context()))


@site_app.command("deploy")
def site_deploy(force: Annotated[bool, typer.Option(help="Deploy even if unchanged")] = False) -> None:
    """Upload web/dist and the review Function to Cloudflare Pages if they changed since the
    last deploy (a fixture build is refused)."""
    _site_deploy(force=force, until=None)


def _site_deploy(force: bool, until: float | None) -> None:
    from escapadinha.website.deploy import deploy

    ctx, conn = _ctx()
    deployed, message = deploy(ctx, conn, force=force, until=until)
    console.print(("[green]Deployed:[/] " if deployed else "") + message)


@design_app.command("directions")
def design_directions(
    deal_id: Annotated[int | None, typer.Option(help="Promotion shown on the promotion pages")] = None,
) -> None:
    """Three visual directions (home + promotion page each) into ./output/directions/."""
    import sqlite3

    from escapadinha.design_directions import build_directions

    ctx = Context()
    if not ctx.db_path.exists():
        console.print(f"No database at {ctx.db_path}. Run [bold]escapadinha collect[/] first.")
        raise typer.Exit(1)
    pipeline.open_db(ctx).close()             # migrate + sync routes first, then read only
    conn = sqlite3.connect(f"{ctx.db_path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    summary = build_directions(ctx, conn, deal_id=deal_id)
    console.print(f"{len(summary['pages'])} pages, {summary['promos']} promotions, "
                  f"{summary['lows']} low prices, {summary['photos']} photos")
    console.print(f"Open [bold]{summary['index']}[/]")


def routes_upkeep() -> None:
    """Monthly discovery when due, else photos for destinations still without one.
    A failure here (an API, or the object store a new photo is mirrored to) is reported and
    never stops the collection."""
    ctx, conn = _ctx()
    try:
        result = pipeline.run_discover_if_due(ctx, conn)
        if result is not None:
            _print_discovery(ctx, result)
            return
        done, missing = pipeline.run_missing_photos(ctx, conn)
        for key, outcome in done:
            console.print(f"  foto {key}: {outcome}")
        if done and missing:
            console.print(f"  [dim]{missing} destinos ainda sem foto.[/]")
    except (TravelpayoutsError, PhotoSourceError, httpx.HTTPError, ValueError,
            *STORE_ERRORS) as exc:
        console.print(f"[yellow]Descoberta de rotas falhou, a recolha continua:[/] {exc}")


def _site_configured(ctx: Context) -> bool:
    return bool(ctx.secrets.cloudflare_api_token and ctx.secrets.cloudflare_account_id)


def _remote(ctx: Context) -> None:
    if not ctx.remote_store:
        console.print("R2 keys not set in .env: the database stays at "
                      f"[bold]{ctx.db_path}[/] and objects under data/objects/ (nothing to sync).")
        raise typer.Exit(1)


@store_app.command("status")
def store_status() -> None:
    """Bucket database generation, lock, backups and whether the local copy changed."""
    ctx = Context()
    if not ctx.remote_store:
        console.print(f"Local store only (no R2 keys in .env): database at [bold]{ctx.db_path}[/].")
        return
    s = sync.status(ctx.object_store, ctx.db_path, ctx.sync_state_path)
    console.print(f"Bucket [bold]{ctx.secrets.r2_bucket}[/]")
    remote, lock, backups, state = s["remote"], s["lock"], s["backups"], s["state"]
    database = f"{remote.describe()}, {remote.size / 1e6:.2f} MB" if remote else "none yet"
    console.print(f"  database: {database}")
    if lock:
        until = pt.lisbon_timestamp(datetime.fromisoformat(lock["expires_at"]))
        console.print(f"  lock: held by {lock.get('owner')} until {until}")
    else:
        console.print("  lock: free")
    span = f", {backups[0]} … {backups[-1]}" if backups else ""
    console.print(f"  daily backups: {len(backups)}{span}")
    if not s["local_exists"]:
        local = "none (run `escapadinha store pull`)"
    elif state is None:
        local = "never synced"
    else:
        changed = "changed since" if s["local_changed"] else "unchanged"
        local = f"from generation {state.generation}, {changed}"
    console.print(f"Local [bold]{ctx.db_path}[/]: {local}")
    if remote and state and remote.generation > state.generation:
        console.print("  [yellow]![/] the bucket is newer: `escapadinha store pull`")


@store_app.command("pull")
def store_pull(force: Annotated[bool, typer.Option(help="Discard local changes (a copy is kept)")] = False) -> None:
    """Download the bucket's database over the local one."""
    ctx = Context()
    _remote(ctx)
    try:
        lock = json.loads(ctx.object_store.get(f"locks/{sync.LOCK}"))
        console.print(f"[yellow]![/] A run is in progress ({lock.get('owner')}): this copy will be "
                      "outdated when it finishes.")
    except KeyError:
        pass
    try:
        sync.pull(ctx.object_store, ctx.db_path, ctx.sync_state_path, force=force, log=console.print)
    except sync.SyncError as exc:
        console.print(f"[red]Not pulled:[/] {exc}")
        raise typer.Exit(1) from None


@store_app.command("push")
def store_push(force: Annotated[bool, typer.Option(help="Overwrite a newer bucket database")] = False) -> None:
    """Upload the local database (takes the run lock; refuses while a run holds it)."""
    ctx = Context()
    _remote(ctx)
    owner = sync.owner_id("store-push")
    try:
        with ctx.object_store.lock(sync.LOCK, owner=owner, ttl=sync.LOCK_TTL):
            sync.push(ctx.object_store, ctx.db_path, ctx.sync_state_path, owner=owner,
                      force=force, log=console.print)
    except LockHeld as exc:
        console.print(f"[red]Not pushed:[/] a run is in progress ({exc}). Try again when it ends.")
        raise typer.Exit(1) from None
    except sync.SyncError as exc:
        console.print(f"[red]Not pushed:[/] {exc}")
        raise typer.Exit(1) from None


@store_app.command("restore")
def store_restore(day: Annotated[str, typer.Argument(help="Backup date, YYYY-MM-DD (see `store status`)")]) -> None:
    """Replace the local database with a daily backup (then `store push` to put it live)."""
    ctx = Context()
    _remote(ctx)
    try:
        sync.restore(ctx.object_store, ctx.db_path, ctx.sync_state_path, day, log=console.print)
    except KeyError:
        console.print(f"[red]No backup for {day}.[/] Available: "
                      f"{', '.join(sync.status(ctx.object_store, ctx.db_path, ctx.sync_state_path)['backups']) or 'none'}")
        raise typer.Exit(1) from None


@store_app.command("upload-archives")
def store_upload_archives() -> None:
    """One-off: copy raw archives from data/objects/ that the bucket does not have yet."""
    from escapadinha.storage.objects import LocalObjectStore

    ctx = Context()
    _remote(ctx)
    copied = sync.upload_missing(LocalObjectStore(ctx.local_objects_dir), ctx.object_store)
    console.print(f"{len(copied)} archive objects uploaded"
                  + (f" ({copied[0]} … {copied[-1]})" if copied else "") + ".")


@store_app.command("check")
def store_check() -> None:
    """Round trip on the real bucket (throwaway keys): read/write/list/delete and the lock."""
    ctx = Context()
    _remote(ctx)
    results = sync.check(ctx.object_store)
    for name, ok in results:
        console.print(f"  {'[green]✓[/]' if ok else '[red]✗[/]'} {name}")
    if not all(ok for _, ok in results):
        raise typer.Exit(1)
    console.print(f"Bucket [bold]{ctx.secrets.r2_bucket}[/] OK.")


def apply_review_events() -> None:
    """Pending review decisions (CLI, review page, review Function) applied to the database."""
    ctx, conn = _ctx()
    for o in pipeline.apply_review_events(ctx, conn):
        what = f"{DECISION_PT.get(o.type, '?')} deal {o.deal_id}" if o.type else o.event_id
        console.print(f"  decisão {what}: " + ("[green]aplicada[/]" if o.applied
                                               else f"[yellow]recusada[/] ({o.reason})"))


def export_review_snapshot() -> None:
    ctx, conn = _ctx()
    snap = pipeline.export_review_snapshot(ctx, conn)
    console.print(f"Review snapshot: {len(snap['queue'])} por rever, {len(snap['approved'])} "
                  f"aprovados, {len(snap['pending_events'])} decisões pendentes.")


def _post_state(post) -> str:
    """A queue row in pt-PT: status, publisher, why it waits or was cancelled, the story, the
    post's link."""
    state = posting.STATUS_PT_POST[post.status]
    if post.publisher:
        state += f" ({post.publisher})"
    if post.status == "cancelled":
        state += f": {post.reason}"
    elif post.status == "queued" and post.last_error:
        state += f": {post.last_error}"
    if post.story_status:                    # Instagram (D36): the story after the carousel
        story = {"pending": "por publicar", "published": "publicada",
                 "skipped": "não sai"}[post.story_status]
        state += f" · story {story}" + (f": {post.story_note}" if post.story_note
                                        and post.story_status != "published" else "")
    if post.result_url:
        state += f" · {post.result_url}"
    return state


def _other_links(conn, post) -> str:
    """The links of the promotion's posts already out on its other channels."""
    return "".join(f" · {posting.CHANNEL_PT[p.channel]}: {p.result_url}"
                   for p in db.deal_posts(conn, post.deal_id) if p.id != post.id and p.result_url)


def _print_posts(conn, deal_id: int) -> None:
    """A promotion's posts (D32): when each goes out, or how it went, with its link."""
    for post in db.deal_posts(conn, deal_id):
        state = (f"agendada para {pt.lisbon_timestamp(post.due_at)}"
                 + (f": {post.last_error}" if post.last_error else "")
                 if post.status == "queued" else _post_state(post))
        console.print(f"  {posting.CHANNEL_PT[post.channel]}: {escape(state)}")


@queue_app.command("list")
def queue_list(show_all: Annotated[bool, typer.Option("--all", help="Also published and cancelled posts")] = False) -> None:
    """Upcoming posts (Lisbon time), and why a due one waits."""
    ctx, conn = _ctx()
    # Instagram's token; Telegram's channel or token refused, sends to confirm (D36, D38).
    for notice in pipeline.publisher_notices(ctx, conn):
        console.print(f"[yellow]![/] {escape(notice)}")
    queued = db.posts(conn, "queued")
    shown = db.posts(conn) if show_all else queued
    if not queued:
        console.print("Nenhuma publicação agendada.")
    else:
        console.print(pt.count(len(queued), "publicação agendada", "publicações agendadas") + ":")
    for post in shown:
        deal, obs = db.get_deal(conn, post.deal_id)
        view = pipeline.text_view(ctx, conn, deal, obs)
        state = escape(_post_state(post) + _other_links(conn, post))
        console.print(f"  {posting.CHANNEL_PT[post.channel]:<9} deal {post.deal_id} "
                      f"{view.origin_city} → {view.destination_headline} {view.price} "
                      f"{pt.lisbon_timestamp(post.due_at)} · {state}")


@queue_app.command("retry")
def queue_retry(deal_id: int, channel: Annotated[str, typer.Argument(help="telegram")]) -> None:
    """Put back a Telegram post cancelled because Telegram's answer was lost (D38), once you
    checked the channel and the message isn't there."""
    from escapadinha import telegram

    ctx, conn = _ctx()
    try:
        console.print(pipeline.retry_post(ctx, conn, deal_id, channel))
    except telegram.RetryRefused as exc:
        console.print(f"[red]Não reposta:[/] {escape(str(exc))}")
        raise typer.Exit(1) from None


@instagram_app.command("token")
def instagram_token() -> None:
    """Print the Instagram token the pipeline refreshed (D36), to copy into the
    INSTAGRAM_ACCESS_TOKEN secret (GitHub) and .env. On this PC only: refused on CI, where
    the log would keep it."""
    from escapadinha import instagram

    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        console.print("[red]Recusado:[/] o token só é mostrado no teu PC, nunca no CI.")
        raise typer.Exit(1)
    ctx = Context()
    stored = instagram.stored_token(ctx.object_store)
    if stored is None:
        where = "no bucket" if ctx.remote_store else "em data/objects/"
        console.print(f"Nenhum token renovado {where}: o secret INSTAGRAM_ACCESS_TOKEN é o atual.")
        raise typer.Exit(1)
    expires = datetime.fromisoformat(stored["expires_at"])
    current = instagram.fingerprint(ctx.secrets.instagram_access_token.strip()) == stored["fingerprint"]
    console.print(f"Token renovado a {pt.lisbon_timestamp(datetime.fromisoformat(stored['refreshed_at']))}, "
                  f"válido até {pt.lisbon_timestamp(expires)}"
                  + (" (o .env já o tem)." if current else ": copia-o para o secret "
                     "INSTAGRAM_ACCESS_TOKEN no GitHub e para o .env (README §Instagram)."))
    console.print(stored["token"], markup=False, highlight=False, soft_wrap=True)


def publish_due() -> None:
    """Due posts of approved promotions, after re-verifying them (D32)."""
    ctx, conn = _ctx()

    def log(line: str) -> None:                  # publisher output is text, not Rich markup
        console.print(line, markup=False, highlight=False)

    Did = posting.PostAction
    for r in pipeline.run_publish(ctx, conn, log=log):
        what = f"publicação {posting.CHANNEL_PT[r.post.channel]} deal {r.post.deal_id}"
        match r.action:
            case Did.PUBLISHED:
                console.print(f"  {what}: [green]publicada[/] ({r.post.publisher})")
            case Did.CANCELLED:
                console.print(f"  {what}: [yellow]cancelada[/] ({escape(r.reason)})")
            case Did.FAILED:
                console.print(f"  {what}: [red]falhou[/] ({escape(r.reason)}), nova tentativa na "
                              "próxima execução")
            case Did.WAITING:
                console.print(f"  {what}: à espera ({escape(r.reason)})")


def _run_steps(render: bool, full: bool, report: list[str]) -> None:
    apply_review_events()                       # first: the run sees the reviewer's decisions
    try:
        _pipeline_steps(render, full, report)
    except BaseException:                       # failed collection (Exit 1) or an error
        try:                                    # the reviewer still sees the applied decisions
            export_review_snapshot()
        except Exception as exc:                # never hides the run's own failure
            console.print(f"[red]Review snapshot failed:[/] {exc}")
            report.append(f"Review snapshot failed: {type(exc).__name__}")
        raise
    export_review_snapshot()                    # last, on the fast and the full path (D26)


def _warn(warning: str | None, report: list[str]) -> None:
    """A warning in the run log and the run's summary."""
    if warning:
        console.print(f"[yellow]Warning:[/] {escape(warning)}")
        report.append(f"Warning: {warning}")


def _warn_if_late(report: list[str]) -> None:
    """The previous run more than 3 h before this one: the schedule missed a run (D41)."""
    _, conn = _ctx()
    _warn(pipeline.late_run_warning(conn, db.utcnow()), report)


def _warn_if_daily_pass_missed(report: list[str]) -> None:
    """The last recorded daily pass more than 30 h ago (D42); after this run's collection."""
    ctx, conn = _ctx()
    _warn(pipeline.missed_daily_pass_warning(ctx, conn, db.utcnow()), report)


def _pipeline_steps(render: bool, full: bool, report: list[str]) -> None:
    _warn_if_late(report)                    # before this run's collection adds its own row
    routes_upkeep()
    summary = _collect()
    report.append(f"Collection: {summary.status}, {summary.plan.describe()}, "
                  f"{summary.n_requests} requests, "
                  f"{summary.n_observations} offers ({summary.n_new} new)"
                  + (f", {len(summary.errors)} failed" if summary.errors else ""))
    _warn_if_daily_pass_missed(report)
    if summary.status == "failed":           # every request failed: the run fails (exit 1)
        raise typer.Exit(1)
    recheck_cmd()
    detect()
    publish_due()                            # every run: posting never waits for a full path (D32)
    ctx, conn = _ctx()
    decision = run_path.decide(ctx, conn, force=full)
    console.print(f"Path: {decision.name} ({decision.reason})")
    report.append(f"Path: {decision.name} ({decision.reason})")
    if not decision.full:
        return
    until = node.deadline()                  # one budget for the full path's Node commands (D35)
    uploaded = pipeline.mirror_local_files(ctx, conn)     # what a runner lacks (D25)
    if uploaded:
        console.print(f"{len(uploaded)} local files uploaded to the object store.")
    if render:
        render_deals()
    export = _export_site_data(None, new_links=True)   # → web/src/data (site.data_dir)
    if _site_build(until).installed:             # the Astro site → web/dist (D35)
        _github_output("npm_ci", "true")         # the workflow saves npm's cache (D35)
    if _site_configured(ctx):
        _site_deploy(force=False, until=until)
    else:
        console.print("[dim]Site not deployed: Cloudflare keys not set in .env[/]")
    run_path.record_full_path(ctx, conn, export)   # what was exported, built and deployed


def _duration(seconds: float) -> str:
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes} min {secs} s" if minutes else f"{secs} s"


def _github_output(name: str, value: str) -> None:
    """A step output for the workflow (only when Actions sets the file)."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def _step_summary(status: str, took: str, report: list[str]) -> None:
    """The run's outcome on the GitHub Actions run page (only when Actions sets the file)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [f"### Escapadinha run: {status}", "", f"- Duration: {took}",
             *(f"- {line}" for line in report)]
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


@app.command()
def run(render: Annotated[bool, typer.Option(help="Also render new deals")] = True,
        full: Annotated[bool, typer.Option(
            "--full", help="Render, build and deploy even if nothing the site shows changed")] = False,
        ) -> None:
    """Review events → (monthly route discovery) → collect → recheck open deals → detect →
    publish due posts (D32), then the full path (render new deals → export the site data →
    build the Astro site → deploy) only when something it shows changed → review snapshot. What the scheduler runs (GitHub Actions, D25).

    With R2 keys in .env: lock → pull the database → daily backup → steps → push → unlock.
    Another run holding the lock makes this one exit 0 without touching anything.
    """
    started, report, status = time.monotonic(), [], "failed"
    try:
        ctx = Context()
        if not ctx.remote_store:
            _run_steps(render, full, report)
        else:
            try:
                with sync.run_session(ctx.object_store, ctx.db_path, ctx.sync_state_path,
                                      owner=sync.owner_id("run"), log=console.print):
                    _run_steps(render, full, report)
            except LockHeld as exc:
                console.print(f"Another run is in progress ({exc}): nothing done.")
                status = "skipped (another run holds the lock)"
                raise typer.Exit(0) from None
        status = "ok"
    except typer.Exit:                    # status already says why (lock held or collection failed)
        raise
    except Exception as exc:
        first_line = next(iter(str(exc).splitlines()), "")
        report.append(f"Error: {type(exc).__name__}: {first_line[:300]}")
        raise
    finally:
        took = _duration(time.monotonic() - started)
        console.print(f"Run {status} in {took}.")
        _step_summary(status, took, report)


def main() -> None:
    try:
        app()
    except (TravelpayoutsError, PhotoSourceError, AffiliateError, ReviewError, DeployError,
            BuildError, ConfigError, sync.SyncError, FileNotFoundError, KeyError) as exc:
        console.print(f"[red]Error:[/] {exc}")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
