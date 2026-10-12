"""`escapadinha` command line. Every step can run on its own; `run` chains them."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from escapadinha import pipeline
from escapadinha.affiliate import AffiliateError
from escapadinha.collector.travelpayouts import TravelpayoutsError
from escapadinha.photos import PhotoSourceError
from escapadinha.config import Context
from escapadinha.storage import db

app = typer.Typer(help="Travel deals from Portugal: collect → detect → render (no publishing).",
                  no_args_is_help=True, pretty_exceptions_enable=False)
photos_app = typer.Typer(help="Destination photo cache (Pixabay).", no_args_is_help=True)
render_app = typer.Typer(help="Render Instagram slides + captions into ./output/<date>/.",
                         no_args_is_help=True)
app.add_typer(photos_app, name="photos")
app.add_typer(render_app, name="render")

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
    """Fetch round-trip prices for every configured route and store them."""
    ctx, conn = _ctx()
    summary = pipeline.run_collect(ctx, conn)
    console.print(f"Run #{summary.run_id}: [bold]{summary.status}[/] · "
                  f"{summary.n_requests} requests · {summary.n_observations} observations stored")
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
        mark = "[green]✓ valid[/]" if r.valid else "[red]✗ expired[/]"
        console.print(f"  deal {deal.id} {obs.route_key} {obs.departure_date:%d/%m}–"
                      f"{obs.return_date:%d/%m} @ {obs.price:g} €: {mark} ({r.reason})")


@app.command()
def stats(route: Annotated[str, typer.Argument(help="e.g. LIS-LON")]) -> None:
    """Price history summary for one route."""
    ctx, conn = _ctx()
    r = ctx.config.route(route)
    row = db.route_stats(conn, r.origin, r.destination)
    if not row["n"]:
        console.print(f"No observations for {r.key} yet.")
        return
    console.print(f"Typical low per departure month (median of daily lows, "
                  f"needs {ctx.config.detector.min_baseline_days} days):")
    for (year, month), base in sorted(pipeline.current_baselines(ctx, conn, r).items()):
        low = "–" if base.median is None else f"{base.median:g} €"
        console.print(f"  {year}-{month:02d}: {low} from {base.sample_size} days")


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
def run(render: Annotated[bool, typer.Option(help="Also render new deals")] = True) -> None:
    """collect → recheck open deals → detect → render new deals. What the scheduler runs."""
    collect()
    recheck_cmd()
    detect()
    if render:
        render_deals()


def main() -> None:
    try:
        app()
    except (TravelpayoutsError, PhotoSourceError, AffiliateError, FileNotFoundError, KeyError) as exc:
        console.print(f"[red]Error:[/] {exc}")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
