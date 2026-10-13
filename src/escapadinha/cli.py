"""`escapadinha` command line. Every step can run on its own; `run` chains them."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.table import Table

from escapadinha import i18n_pt as pt
from escapadinha import pipeline, routes
from escapadinha.affiliate import AffiliateError
from escapadinha.collector.travelpayouts import TravelpayoutsError
from escapadinha.photos import PhotoSourceError
from escapadinha.review import ReviewError
from escapadinha.website.deploy import DeployError
from escapadinha.config import Context
from escapadinha.storage import db, sync
from escapadinha.storage.objects import LockHeld

app =typer.Typer(help="Travel deals from Portugal: collect → detect → render (no publishing).",
                  no_args_is_help=True, pretty_exceptions_enable=False)
photos_app = typer.Typer(help="Destination photo cache (Pixabay).", no_args_is_help=True)
render_app = typer.Typer(help="Render Instagram slides + captions into ./output/<date>/.",
                         no_args_is_help=True)
site_app = typer.Typer(help="Public website: build, preview, deploy (Cloudflare Pages).",
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
    ctx, conn = _ctx()
    summary = pipeline.run_collect(ctx, conn)
    console.print(f"Run #{summary.run_id}: [bold]{summary.status}[/] · "
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
    if summary.status == "failed":
        raise typer.Exit(1)


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
    need = ctx.config.detector.min_baseline_days
    for r in results:
        best = "–" if r.best is None else f"{r.best.price:g} € ({r.best.departure_date:%d/%m})"
        low = "–" if r.baseline is None or r.baseline.median is None else f"{r.baseline.median:g} €"
        days = "–" if r.baseline is None else f"{r.baseline.sample_size}/{need} days"
        table.add_row(r.route, str(r.fresh), best, low, days, labels.get(r.status, r.status),
                      str(r.low_prices or "–"), ", ".join(map(str, r.deal_ids)) or "–")
    console.print(table)
    console.print(f"{sum(r.low_prices for r in results)} low prices, "
                  f"{sum(len(r.deal_ids) for r in results)} new promotion candidates.")


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
    console.print(f"Typical low per departure month (median of daily lows, "
                  f"needs {ctx.config.detector.min_baseline_days} days):")
    for (year, month), base in sorted(pipeline.current_baselines(ctx, conn, r).items()):
        low = "–" if base.median is None else f"{base.median:g} €"
        console.print(f"  {year}-{month:02d}: {low} from {base.sample_size} days")


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
    mark = "[green]✓ preço confirmado[/]" if check.valid else "[red]✗ expirado[/]"
    console.print(f"  deal {deal.id}: {mark} ({check.reason}) → status {deal.status}")


@deal_app.command("check")
def deal_check(deal_id: int) -> None:
    """Fetch this deal's prices now and recheck it."""
    ctx, conn = _ctx()
    _print_check(*pipeline.live_check(ctx, conn, deal_id))


@deal_app.command("approve")
def deal_approve(deal_id: int, note: Annotated[str | None, typer.Option()] = None) -> None:
    """Approve after a live price check (expires the deal if the price moved)."""
    ctx, conn = _ctx()
    _print_check(*pipeline.approve(ctx, conn, deal_id, note))


@deal_app.command("reject")
def deal_reject(deal_id: int, note: Annotated[str | None, typer.Option()] = None) -> None:
    """Reject a deal (final)."""
    _, conn = _ctx()
    deal = pipeline.reject(conn, deal_id, note)
    console.print(f"  deal {deal.id}: {deal.status}")


@deal_app.command("published")
def deal_published(deal_id: int, url: Annotated[str | None, typer.Option(help="Post URL")] = None) -> None:
    """Mark an approved deal as published."""
    _, conn = _ctx()
    deal = pipeline.mark_published(conn, deal_id, url)
    console.print(f"  deal {deal.id}: {deal.status}")


@site_app.command("build")
def site_build() -> None:
    """Generate the static site into ./site from the database."""
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
    from escapadinha import site_data

    ctx, conn = _ctx()
    out = out or site_data.default_dir(ctx)
    counts = site_data.export_site_data(ctx, conn, out, new_links=new_links).counts
    console.print(f"Site data written to [bold]{out}[/]: {counts['routes']} routes, "
                  f"{counts['origins']} origins, {counts['destinations']} destinations, "
                  f"{counts['promotions_live']} live + {counts['promotions_expired']} expired "
                  f"promotions, {counts['low_prices']} low prices")


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
    """Serve ./site locally (http://127.0.0.1:PORT)."""
    import functools
    import http.server

    ctx = Context()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ctx.site_dir))
    console.print(f"Site preview at [bold]http://127.0.0.1:{port}[/] (Ctrl+C to stop)")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()


@site_app.command("setup")
def site_setup() -> None:
    """One-time: create the Cloudflare Pages project."""
    from escapadinha.website.deploy import create_project

    console.print(create_project(Context()))


@site_app.command("deploy")
def site_deploy(force: Annotated[bool, typer.Option(help="Deploy even if unchanged")] = False) -> None:
    """Upload ./site to Cloudflare Pages if it changed since the last deploy."""
    from escapadinha.website.deploy import deploy

    deployed, message = deploy(Context(), force=force)
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
    A failure here is reported and never stops the collection."""
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
    except (TravelpayoutsError, PhotoSourceError, httpx.HTTPError, ValueError) as exc:
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


def _run_steps(render: bool) -> None:
    routes_upkeep()
    collect()
    recheck_cmd()
    detect()
    if render:
        render_deals()
    export_site_data(out=None, new_links=True)
    site_build()
    if _site_configured(Context()):
        site_deploy()
    else:
        console.print("[dim]Site not deployed: Cloudflare keys not set in .env[/]")


@app.command()
def run(render: Annotated[bool, typer.Option(help="Also render new deals")] = True) -> None:
    """(monthly route discovery) → collect → recheck open deals → detect → render new deals →
    export the site data (D27) → build (and deploy) the site. What the scheduler runs.

    With R2 keys in .env: lock → pull the database → daily backup → steps → push → unlock.
    Another run holding the lock makes this one exit 0 without touching anything.
    """
    ctx = Context()
    if not ctx.remote_store:
        _run_steps(render)
        return
    try:
        with sync.run_session(ctx.object_store, ctx.db_path, ctx.sync_state_path,
                              owner=sync.owner_id("run"), log=console.print):
            _run_steps(render)
    except LockHeld as exc:
        console.print(f"Another run is in progress ({exc}): nothing done.")
        raise typer.Exit(0) from None


def main() -> None:
    try:
        app()
    except (TravelpayoutsError, PhotoSourceError, AffiliateError, ReviewError, DeployError,
            sync.SyncError, FileNotFoundError, KeyError) as exc:
        console.print(f"[red]Error:[/] {exc}")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
