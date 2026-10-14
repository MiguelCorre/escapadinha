"""Portuguese public holidays and their long weekends (pontes, D31): the committed calendar
(content/holidays.yaml) and the window each holiday gives a traveller."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from escapadinha import pontes
from escapadinha.pontes import Holiday

REPO = Path(__file__).resolve().parents[1]
CALENDAR = REPO / "content" / "holidays.yaml"


def holiday(day: str, slug: str = "feriado", optional: bool = False) -> Holiday:
    return Holiday(day=date.fromisoformat(day), slug=slug, name="Feriado",
                   ponte="Ponte do feriado", optional=optional)


@pytest.mark.parametrize("day, first_off, last_off, bridge", [
    ("2026-10-05", "2026-10-03", "2026-10-05", None),           # Monday: Sat-Mon
    ("2026-12-01", "2026-11-28", "2026-12-01", "2026-11-30"),   # Tuesday: Monday bridged
    ("2027-06-10", "2027-06-10", "2027-06-13", "2027-06-11"),   # Thursday: Friday bridged
    ("2026-12-25", "2026-12-25", "2026-12-27", None),           # Friday: Fri-Sun
])
def test_a_holiday_next_to_a_weekend_gives_a_long_weekend(day, first_off, last_off, bridge):
    p = pontes.long_weekend(holiday(day))
    assert (p.first_off.isoformat(), p.last_off.isoformat()) == (first_off, last_off)
    assert (p.bridge.isoformat() if p.bridge else None) == bridge


@pytest.mark.parametrize("day", ["2026-06-10", "2026-08-15", "2026-11-01"])   # Wed, Sat, Sun
def test_a_holiday_on_a_wednesday_or_a_weekend_gives_none(day):
    assert pontes.long_weekend(holiday(day)) is None


def test_the_travel_window_runs_from_the_evening_before_to_the_morning_after():
    """Like the weekend rule (out Fri/Sat, back Sun/Mon): leave the day before the first day
    off, come back at the latest the day after the last one."""
    p = pontes.long_weekend(holiday("2026-12-01", slug="1-dezembro"))
    assert (p.start, p.end) == (date(2026, 11, 27), date(2026, 12, 2))
    assert p.slug == "1-dezembro-2026" and p.name == "Ponte do feriado"


def test_the_committed_calendar_has_every_national_holiday_of_2026_and_2027():
    """Código do Trabalho art. 234 (13 obligatory holidays a year) plus Carnaval (art. 235,
    optional), with the movable feasts of each year's Easter (5 April 2026, 28 March 2027)."""
    calendar = pontes.load_calendar(CALENDAR)
    for year in (2026, 2027):
        mine = [h for h in calendar if h.day.year == year]
        assert len(mine) == 14
        assert [h.slug for h in mine if h.optional] == ["carnaval"]
    days = {h.day for h in calendar}
    assert {date(2026, 2, 17), date(2026, 4, 3), date(2026, 4, 5), date(2026, 6, 4),
            date(2027, 2, 9), date(2027, 3, 26), date(2027, 3, 28), date(2027, 5, 27)} <= days
    assert {date(y, m, d) for y in (2026, 2027) for m, d in [
        (1, 1), (4, 25), (5, 1), (6, 10), (8, 15), (10, 5), (11, 1), (12, 1), (12, 8),
        (12, 25)]} <= days


def test_the_calendars_pontes_from_october_2026():
    upcoming = [p for p in pontes.pontes(pontes.load_calendar(CALENDAR))
                if p.end >= date(2026, 10, 13)]
    assert [p.slug for p in upcoming] == [
        "1-dezembro-2026", "8-dezembro-2026", "natal-2026", "ano-novo-2027", "carnaval-2027",
        "sexta-feira-santa-2027", "corpo-de-deus-2027", "10-junho-2027", "5-outubro-2027",
        "1-novembro-2027"]
    carnaval = next(p for p in upcoming if p.slug == "carnaval-2027")
    assert carnaval.holiday.optional and carnaval.bridge == date(2027, 2, 8)
    windows = sorted((p.start, p.end) for p in pontes.pontes(pontes.load_calendar(CALENDAR)))
    assert all(a[1] < b[0] for a, b in zip(windows, windows[1:]))     # none overlap


def test_a_calendar_with_a_day_twice_is_refused(tmp_path):
    bad = tmp_path / "holidays.yaml"
    bad.write_text("holidays:\n  - {slug: a, name: A, ponte: P, dates: [2026-05-01]}\n"
                   "  - {slug: b, name: B, ponte: P, dates: [2026-05-01]}\n", "utf-8")
    with pytest.raises(ValueError, match="2026-05-01"):
        pontes.load_calendar(bad)
