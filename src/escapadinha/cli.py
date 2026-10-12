"""`escapadinha` command line. Every step can run on its own; `run` chains them."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from escapadinha import pipeline
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
    for col in ("Route", "Offers", "History", "Median", "Result", "Deal ids", "Note"):
        table.add_column(col)
    for r in results:
        median = "–" if r.baseline.median is None else f"{r.baseline.median:g} €"
        history = f"{r.baseline.sample_size} / {r.baseline.span_days:.1f} d"
        colour = {"deals": "green", "insufficient_history": "yellow"}.get(r.status, "white")
        table.add_row(r.route, str(r.candidates), history, median, f"[{colour}]{r.status}[/]",
                      ", ".join(map(str, r.deal_ids)) or "–", r.note)
    console.print(table)


@app.command()
def stats(route: Annotated[str, typer.Argument(help="e.g. LIS-LON")]) -> None:
    """Price history summary for one route."""
    ctx, conn = _ctx()
    r = ctx.config.route(route)
    row = db.route_stats(conn, r.origin, r.destination)
    if not row["n"]:
        console.print(f"No observations for {r.key} yet.")
        return
    base = pipeline.current_baseline(ctx, conn, r)
    console.print(f"[bold]{r.key}[/] {r.city_pt}: {row['n']} observations in {row['runs']} runs, "
                  f"{row['min_price']:g}–{row['max_price']:g} €, first {row['first_seen']}, "
                  f"last {row['last_seen']}")
    console.print(f"Baseline ({ctx.config.detector.lookback_days} d): median "
                  f"{'–' if base.median is None else f'{base.median:g} €'}, "
                  f"{base.sample_size} samples over {base.span_days:.1f} days "
                  f"(needs {ctx.config.detector.min_samples} / {ctx.config.detector.min_history_days} d)")


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
    dirs = pipeline.run_render_deals(ctx, conn, status, deal_id)
    if not dirs:
        console.print(f"No deals with status '{status}'.")
    for d in dirs:
        console.print(f"  [green]✓[/] {d}")


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
    """collect → detect → render new deals. This is what the scheduler runs."""
    collect()
    detect()
    if render:
        render_deals()


def main() -> None:
    try:
        app()
    except (TravelpayoutsError, PhotoSourceError, FileNotFoundError, KeyError) as exc:
        console.print(f"[red]Error:[/] {exc}")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
