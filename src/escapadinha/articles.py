"""Itineraries and tips (D33) as the pipeline sees them: which affiliate blocks they use (D37).

The articles are MDX files in the web package (`web/src/content/<kind>/<slug>.mdx`; test-only
ones under `web/test/fixtures/content/`), written by hand and gated by `reviewed:` on the site
(`web/src/collections.ts`). The pipeline reads only their front matter, to create one tracked
link per affiliate programme an article lists in `affiliates:`. The same gate applies here:
only articles the site builds get links.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

CONTENT = "src/content"                  # under the web package
FIXTURE_CONTENT = "test/fixtures/content"
# Collection -> the article's sub_id prefix (the page section is the site's: /roteiros/, /dicas/).
KINDS: dict[str, str] = {"itineraries": "roteiro", "tips": "dica"}
_FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)


@dataclass(frozen=True)
class Article:
    kind: str                       # "itineraries" | "tips"
    slug: str                       # the file name
    destination: str | None         # an itinerary's city code
    affiliates: tuple[str, ...]     # programmes listed in the front matter
    reviewed: bool
    fixture: bool

    @property
    def key(self) -> str:
        """`<collection>/<slug>`: how the site finds the article's links in the contract."""
        return f"{self.kind}/{self.slug}"

    @property
    def sub_id(self) -> str:
        """The tracked links' sub_id: one per article, so the dashboard shows what each earns."""
        return f"{KINDS[self.kind]}-{self.slug}"


def read(path: Path, kind: str) -> Article:
    match = _FRONT.match(path.read_text("utf-8"))
    front = (yaml.safe_load(match.group(1)) if match else None) or {}
    return Article(kind=kind, slug=path.stem, destination=front.get("destination"),
                   affiliates=tuple(front.get("affiliates") or ()),
                   reviewed=front.get("reviewed") is True, fixture=front.get("fixture") is True)


def load(folder: Path) -> list[Article]:
    """Every article under `folder` (`<kind>/*.mdx`), drafts included, sorted by key."""
    return sorted((read(p, kind) for kind in KINDS for p in (folder / kind).glob("*.mdx")),
                  key=lambda a: a.key)


def published(web: Path, *, fixture: bool) -> list[Article]:
    """The articles a site build shows (the review gate, `content.isVisible`): reviewed ones,
    and the test-only ones (`fixture: true`) only when the site is built from fixture data."""
    found = load(web / CONTENT) + (load(web / FIXTURE_CONTENT) if fixture else [])
    return [a for a in found if a.reviewed and (fixture or not a.fixture)]
