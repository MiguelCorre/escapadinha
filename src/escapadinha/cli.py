"""`escapadinha` command line. Every step can run on its own; `run` chains them."""

from __future__ import annotations

from typing import Annotated

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
from escapadinha.storage import db

app = typer.Typer(help="Travel deals from Portugal: collect → detect → render (no publishing).",
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
    if summary.status == "failed":
        raise typer.Exit(1)


@app.command()
def detect(run_id: Annotated[int | None, typer.Option(help="Run to evaluate (default: latest)")] = None) -> None:
    """Flag deals in a collection run against each route's price history."""
    ctx, conn = _ctx()
    run_id, results = pipeline.run_detect(ctx, conn, run_id)
    if run_id is None:
        console.print("No completed collection run yet. Run [bold]escapadinha collect[/] first.")
        raise typer.Exit(1)
    table = Table(title=f"Detection for run #{run_id}")
    for col in ("Route", "Fresh", "Best offer", "Typical low", "Baseline", "Result", "Deals"):
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
                      ", ".join(map(str, r.deal_ids)) or "–")
    console.print(table)


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
    active = len(routes.active_routes(conn, cfg))
    console.print(f"{len(all_routes)} rotas, {active} ativas.")


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
                  f"{summary['guides']} guides")


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


def _site_configured(ctx: Context) -> bool:
    return bool(ctx.secrets.cloudflare_api_token and ctx.secrets.cloudflare_account_id)


@app.command()
def run(render: Annotated[bool, typer.Option(help="Also render new deals")] = True) -> None:
    """collect → recheck open deals → detect → render new deals. What the scheduler runs."""
    collect()
    recheck_cmd()
    detect()
    if render:
        render_deals()
    site_build()
    if _site_configured(Context()):
        site_deploy()
    else:
        console.print("[dim]Site not deployed: Cloudflare keys not set in .env[/]")


def main() -> None:
    try:
        app()
    except (TravelpayoutsError, PhotoSourceError, AffiliateError, ReviewError, DeployError,
            FileNotFoundError, KeyError) as exc:
        console.print(f"[red]Error:[/] {exc}")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
