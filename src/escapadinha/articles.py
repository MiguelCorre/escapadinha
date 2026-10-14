"""Itineraries and tips (D33) as the pipeline sees them: which affiliate blocks they use (D37).

The articles are MDX files in the web package (`web/src/content/<kind>/<slug>.mdx`; test-only
ones under `web/test/fixtures/content/`), written by hand and gated by `reviewed:` on the site
(`web/src/lib/content.ts`, `isVisible`). The pipeline reads only their front matter, to create
one tracked link per affiliate programme an article lists in `affiliates:`, and reads it the way
the site does: YAML 1.2 booleans (Astro's parser: `yes`/`on` are strings), `reviewed`/`fixture`
real booleans, `affiliates` a list of known programmes; anything else raises, as the site's
build fails on it. `web/test/fixtures/content-gate-cases.json` holds the cases both sides check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from escapadinha.config import PROGRAMMES

CONTENT = "src/content"                  # under the web package
FIXTURE_CONTENT = "test/fixtures/content"
# Collection -> the article's sub_id prefix (the page section is the site's: /roteiros/, /dicas/).
KINDS: dict[str, str] = {"itineraries": "roteiro", "tips": "dica"}
_FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)


class ArticleError(ValueError):
    pass


class _Yaml12Loader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 core booleans (true/false only), as js-yaml in Astro reads them:
    PyYAML's YAML 1.1 would turn `reviewed: yes` into True where the site refuses it."""


_Yaml12Loader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Yaml12Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF"))


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
        """`<collection>/<slug>`: how affiliates.json names the article (the site's
        `content.articleKey`)."""
        return f"{self.kind}/{self.slug}"

    @property
    def sub_id(self) -> str:
        """The tracked links' sub_id: one per article, so the dashboard shows what each earns."""
        return f"{KINDS[self.kind]}-{self.slug}"


def _flag(front: dict, name: str, where: str) -> bool:
    value = front.get(name, False)
    if not isinstance(value, bool):
        raise ArticleError(f"{where}: {name} must be true or false, not {value!r}")
    return value


def read(path: Path, kind: str) -> Article:
    where = f"{kind}/{path.stem}"
    match = _FRONT.match(path.read_text("utf-8"))
    front = (yaml.load(match.group(1), Loader=_Yaml12Loader) if match else None) or {}
    listed = front.get("affiliates", [])
    if not isinstance(listed, list) or any(p not in PROGRAMMES for p in listed):
        raise ArticleError(f"{where}: affiliates must be a list of {list(PROGRAMMES)}, "
                           f"not {listed!r}")
    return Article(kind=kind, slug=path.stem, destination=front.get("destination"),
                   affiliates=tuple(listed), reviewed=_flag(front, "reviewed", where),
                   fixture=_flag(front, "fixture", where))


def load(folder: Path) -> list[Article]:
    """Every article under `folder` (`<kind>/*.mdx`), drafts included, sorted by key."""
    return sorted((read(p, kind) for kind in KINDS for p in (folder / kind).glob("*.mdx")),
                  key=lambda a: a.key)


def published(web: Path, *, fixture: bool) -> list[Article]:
    """The articles a site build shows (the review gate, `content.isVisible`): reviewed ones,
    and the test-only ones (`fixture: true`) only when the site is built from fixture data."""
    found = load(web / CONTENT) + (load(web / FIXTURE_CONTENT) if fixture else [])
    return [a for a in found if a.reviewed and (fixture or not a.fixture)]
