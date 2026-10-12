"""'Guia rápido' content: hand-written YAML, reviewed by a human. Never generated prices."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Tip(BaseModel):
    title: str
    body: str


class Guide(BaseModel):
    slug: str
    kicker: str = "GUIA RÁPIDO"
    title: str
    subtitle: str = ""
    photo_destination: str | None = None   # IATA key into the photo cache
    tips: list[Tip] = Field(min_length=3, max_length=8)   # carousel max is 10 slides
    cta: str
    caption: str
    hashtags: list[str] = []
    affiliate: bool = False
    reviewed: bool = False                  # set true once facts were checked by a human
    sources: list[str] = []


def load_guide(guides_dir: Path, slug: str) -> Guide:
    path = guides_dir / f"{slug}.yaml"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in guides_dir.glob("*.yaml"))) or "none"
        raise FileNotFoundError(f"No guide '{slug}' in {guides_dir} (available: {available})")
    with open(path, encoding="utf-8") as f:
        return Guide.model_validate(yaml.safe_load(f))
