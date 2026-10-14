"""Portuguese public holidays and their long weekends ("pontes", D31).

The calendar is a committed file (`content/holidays.yaml`, with its legal source); everything
else here is pure. A holiday next to a weekend gives a long weekend: Monday or Friday adds a day
to the weekend, Tuesday or Thursday adds two with the working day in between taken off (the
bridge, "ponte"). A holiday on a Wednesday, Saturday or Sunday gives none.

The travel window follows the weekend rule (out Friday or Saturday, back Sunday or Monday):
leave at the earliest the evening before the first day off, come back at the latest the day
after the last one. Which trips fit a window is the site's job (web/src/lib/explorer.ts),
from the dates exported in `pontes.json`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

ONE_DAY = timedelta(days=1)

# weekday (Monday = 0) -> (first day off, last day off, bridge) as offsets from the holiday
_SHAPES = {
    0: (-2, 0, None),    # Monday: Saturday to Monday
    1: (-3, 0, -1),      # Tuesday: Saturday to Tuesday, Monday bridged
    3: (0, 3, 1),        # Thursday: Thursday to Sunday, Friday bridged
    4: (0, 2, None),     # Friday: Friday to Sunday
}


@dataclass(frozen=True)
class Holiday:
    day: date
    slug: str          # "1-dezembro" (without the year)
    name: str          # official name
    ponte: str         # page title: "Ponte de 1 de dezembro"
    optional: bool     # Carnaval (Código do Trabalho art. 235): not every employer gives it


@dataclass(frozen=True)
class Ponte:
    holiday: Holiday
    first_off: date
    last_off: date
    bridge: date | None

    @property
    def slug(self) -> str:
        return f"{self.holiday.slug}-{self.holiday.day.year}"

    @property
    def name(self) -> str:
        return self.holiday.ponte

    @property
    def start(self) -> date:
        """Earliest departure: the evening before the first day off."""
        return self.first_off - ONE_DAY

    @property
    def end(self) -> date:
        """Latest return: the day after the last day off."""
        return self.last_off + ONE_DAY


def long_weekend(holiday: Holiday) -> Ponte | None:
    """The long weekend a holiday gives, or None (Wednesday, Saturday, Sunday)."""
    shape = _SHAPES.get(holiday.day.weekday())
    if shape is None:
        return None
    first, last, bridge = shape
    day = holiday.day
    return Ponte(holiday=holiday, first_off=day + first * ONE_DAY, last_off=day + last * ONE_DAY,
                 bridge=None if bridge is None else day + bridge * ONE_DAY)


def pontes(holidays: list[Holiday]) -> list[Ponte]:
    """Every long weekend of the calendar, by date."""
    found = (long_weekend(h) for h in sorted(holidays, key=lambda h: h.day))
    return [p for p in found if p is not None]


def load_calendar(path: Path) -> list[Holiday]:
    """The holidays in a calendar file, by date. A day listed twice is an error."""
    doc = yaml.safe_load(path.read_text("utf-8"))
    out: list[Holiday] = []
    for entry in doc["holidays"]:
        for day in entry["dates"]:
            out.append(Holiday(day=day if isinstance(day, date) else date.fromisoformat(day),
                               slug=entry["slug"], name=entry["name"], ponte=entry["ponte"],
                               optional=bool(entry.get("optional", False))))
    out.sort(key=lambda h: h.day)
    for a, b in zip(out, out[1:]):
        if a.day == b.day:
            raise ValueError(f"{path}: {a.day.isoformat()} is listed twice ({a.slug}, {b.slug})")
    return out
