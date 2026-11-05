"""Portuguese school holidays ("férias escolares", D61, #49), per network: continente, Madeira,
Açores.

The calendar is a committed file (`content/school-holidays.yaml`, each network with its official
source); everything else here is pure. A break is the first and last day without lessons; the
travel window adds a day on each side (leave the evening before, come back the day after), and a
trip fits when its departure and return both fall inside it: the same rule as the pontes (D31),
applied on the site (web/src/lib/explorer.ts). The file carries a review gate like the articles
(D33): only a human sets `reviewed: true`, after checking every date on the official text; until
then the export writes no break and the site builds no page and offers no filter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class Network:
    key: str            # "continente", "madeira", "acores"
    name: str           # "Continente", "Madeira", "Açores"
    source: str         # the official text, https
    source_name: str    # how to cite it


@dataclass(frozen=True)
class Break:
    network: Network
    slug: str           # "natal-2026" (within the network)
    name: str           # "Férias de Natal"
    start: date         # first day without lessons
    end: date           # last day without lessons, inclusive

    @property
    def page_slug(self) -> str:
        """The address: natal-2026-continente."""
        return f"{self.slug}-{self.network.key}"

    @property
    def window_start(self) -> date:
        """Earliest departure: the evening before the first day off."""
        return self.start - ONE_DAY

    @property
    def window_end(self) -> date:
        """Latest return: the day after the last day off."""
        return self.end + ONE_DAY


@dataclass(frozen=True)
class Calendar:
    reviewed: bool
    last_checked: date | None
    networks: tuple[Network, ...]
    breaks: tuple[Break, ...]      # by start, then network order

    @property
    def published(self) -> tuple[Break, ...]:
        """What the site may show: every break once reviewed, nothing before."""
        return self.breaks if self.reviewed else ()


def _day(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def load_calendar(path: Path) -> Calendar:
    """The calendar file. A break whose end precedes its start, a slug listed twice in a network
    or a source that is not https is an error."""
    doc = yaml.safe_load(path.read_text("utf-8"))
    networks: list[Network] = []
    breaks: list[Break] = []
    for n in doc["networks"]:
        if not str(n["source"]).startswith("https://"):
            raise ValueError(f"{path}: network {n['key']}: source must be https")
        network = Network(key=n["key"], name=n["name"], source=n["source"],
                          source_name=n["source_name"])
        networks.append(network)
        seen: set[str] = set()
        for b in n.get("breaks", []):
            if b["slug"] in seen:
                raise ValueError(f"{path}: network {n['key']}: {b['slug']} is listed twice")
            seen.add(b["slug"])
            start, end = _day(b["start"]), _day(b["end"])
            if end < start:
                raise ValueError(f"{path}: {n['key']} {b['slug']}: ends before it starts")
            breaks.append(Break(network=network, slug=b["slug"], name=b["name"], start=start, end=end))
    order = {n.key: i for i, n in enumerate(networks)}
    breaks.sort(key=lambda b: (b.start, order[b.network.key]))
    checked = doc.get("last_checked")
    return Calendar(reviewed=bool(doc.get("reviewed", False)),
                    last_checked=_day(checked) if checked else None,
                    networks=tuple(networks), breaks=tuple(breaks))
