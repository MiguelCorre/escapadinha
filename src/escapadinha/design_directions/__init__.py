"""Three visual directions for Ponto Nómada (issue #11), built from the real database.

`build_directions` writes `output/directions/`: an index plus a home page and a promotion page
per direction (7 pages), with the destination photos copied next to them. Read-only on the DB.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, PackageLoader

from escapadinha.config import Context
from escapadinha.design_directions import data as direction_data
from escapadinha.design_directions.directions import DIRECTIONS, Direction
from escapadinha.presentation import DISCLOSURE

PAGES = ("index.html", "promocao.html")


def _env() -> Environment:
    env = Environment(loader=PackageLoader("escapadinha.design_directions", "templates"),
                      autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.globals.update(directions=DIRECTIONS, disclosure=DISCLOSURE)
    return env


def output_dir(ctx: Context) -> Path:
    return ctx.output_dir / "directions"


def build_directions(ctx: Context, conn: sqlite3.Connection, now: datetime | None = None,
                     deal_id: int | None = None) -> dict:
    """Generate the 7 pages. Returns {'index': path, 'pages': [...], 'photos': n}."""
    out = output_dir(ctx)
    if out.exists():
        shutil.rmtree(out)
    (out / "assets" / "photos").mkdir(parents=True)

    d = direction_data.load(conn, ctx.config, now, deal_id)
    copied = 0
    for photo in d.photos.values():
        src = ctx.photos_dir / photo.file_name
        if src.is_file():
            shutil.copy(src, out / "assets" / "photos" / photo.file_name)
            copied += 1
    available = {p.destination for p in d.photos.values()
                 if (out / "assets" / "photos" / p.file_name).is_file()}

    env = _env()
    def has_photo(trip) -> bool:
        return bool(trip and trip.photo and trip.photo.destination in available)

    common = dict(d=d, brand=ctx.config.brand, has_photo=has_photo,
                  min_days=ctx.config.detector.min_baseline_days)
    pages = []

    def write(rel: str, template: str, **extra) -> None:
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(env.get_template(template).render(**common, **extra),
                        encoding="utf-8", newline="\n")
        pages.append(path)

    write("index.html", "index.html.j2", root="")
    for direction in DIRECTIONS:
        for page in PAGES:
            kind = "home" if page == "index.html" else "promo"
            write(f"{direction.slug}/{page}", f"{direction.slug}/{kind}.html.j2",
                  root="../", direction=direction, page=kind)
    return {"index": out / "index.html", "pages": pages, "photos": copied,
            "promos": len(d.promos), "lows": len(d.lows)}


__all__ = ["build_directions", "output_dir", "Direction", "DIRECTIONS"]
