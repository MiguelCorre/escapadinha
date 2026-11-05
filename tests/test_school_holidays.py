"""School holidays (D61, #49): the calendar file, its windows and its review gate, and the
export (`school-holidays.json`) with a page per break and origin."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from escapadinha import school_holidays
from escapadinha.storage import db
from test_pipeline import ctx  # noqa: F401

CALENDAR = Path(__file__).resolve().parents[1] / "content" / "school-holidays.yaml"


def test_a_break_travels_from_the_evening_before_to_the_day_after():
    net = school_holidays.Network("continente", "Continente", "https://x", "Despacho")
    b = school_holidays.Break(net, "natal-2026", "Férias de Natal", date(2026, 12, 16), date(2026, 12, 31))
    assert (b.window_start, b.window_end) == (date(2026, 12, 15), date(2027, 1, 1))
    assert b.page_slug == "natal-2026-continente"


def test_the_committed_calendar_has_the_three_networks_and_their_four_breaks_of_2026_2027():
    """The dates of docs/research/2026-11-05-ferias-escolares.md, one network per official text."""
    cal = school_holidays.load_calendar(CALENDAR)
    assert [n.key for n in cal.networks] == ["continente", "madeira", "acores"]
    assert all(n.source.startswith("https://") and n.source_name for n in cal.networks)
    by = {(b.network.key, b.slug): (b.start, b.end) for b in cal.breaks}
    assert by["continente", "natal-2026"] == (date(2026, 12, 16), date(2026, 12, 31))
    assert by["madeira", "natal-2026"] == (date(2026, 12, 17), date(2026, 12, 31))
    assert by["acores", "natal-2026"] == (date(2026, 12, 21), date(2026, 12, 31))
    for key in ("continente", "madeira", "acores"):
        assert by[key, "carnaval-2027"] == (date(2027, 2, 8), date(2027, 2, 10))
        assert by[key, "pascoa-2027"][0] == date(2027, 3, 22)
    # Summer: the day after the 1.º ciclo's last day (30 June; 18 to 25 June in the Açores'
    # referential calendar) to the eve of the next year's start.
    assert by["continente", "verao-2027"] == (date(2027, 7, 1), date(2027, 9, 12))
    assert by["madeira", "verao-2027"] == (date(2027, 7, 1), date(2027, 9, 9))
    assert by["acores", "verao-2027"] == (date(2027, 6, 26), date(2027, 9, 12))
    assert by["madeira", "pascoa-2027"][1] == date(2027, 4, 1)      # 2 April: Dia da Autonomia
    assert by["continente", "pascoa-2027"][1] == date(2027, 4, 2)
    assert [b.page_slug for b in cal.breaks][:3] == ["natal-2026-continente", "natal-2026-madeira",
                                                      "natal-2026-acores"]   # by start, then network
    assert cal.last_checked == date(2026, 11, 5)


def test_the_committed_calendar_is_reviewed_so_every_break_is_published():
    """Reviewed on 2026-11-05 on Miguel's instruction, after the dates were read on the three
    primary texts and re-checked independently (the file's header says so)."""
    cal = school_holidays.load_calendar(CALENDAR)
    assert cal.reviewed is True and cal.published == cal.breaks and len(cal.breaks) == 12
    assert "Revisto a 2026-11-05" in CALENDAR.read_text("utf-8")


def test_an_unreviewed_calendar_publishes_nothing(tmp_path):
    """The gate (D33's rule for data): without `reviewed: true` the breaks stay a draft."""
    draft = tmp_path / "school-holidays.yaml"
    draft.write_text(CALENDAR.read_text("utf-8").replace("reviewed: true", "reviewed: false", 1), "utf-8")
    cal = school_holidays.load_calendar(draft)
    assert cal.reviewed is False and cal.published == () and len(cal.breaks) == 12


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "school-holidays.yaml"
    p.write_text("reviewed: true\nnetworks:\n" + body, "utf-8")
    return p


def test_a_reviewed_calendar_publishes_its_breaks(tmp_path):
    p = _write(tmp_path, "  - {key: c, name: C, source: 'https://x', source_name: S, breaks: ["
               "{slug: a, name: A, start: 2027-01-10, end: 2027-01-12}]}\n")
    cal = school_holidays.load_calendar(p)
    assert cal.reviewed and [b.slug for b in cal.published] == ["a"] and cal.last_checked is None


@pytest.mark.parametrize("body, message", [
    ("  - {key: c, name: C, source: 'http://x', source_name: S, breaks: []}\n", "must be https"),
    ("  - {key: c, name: C, source: 'https://x', source_name: S, breaks: ["
     "{slug: a, name: A, start: 2027-01-10, end: 2027-01-12}, "
     "{slug: a, name: A, start: 2027-02-10, end: 2027-02-12}]}\n", "listed twice"),
    ("  - {key: c, name: C, source: 'https://x', source_name: S, breaks: ["
     "{slug: a, name: A, start: 2027-01-12, end: 2027-01-10}]}\n", "ends before it starts"),
])
def test_a_bad_calendar_is_refused(tmp_path, body, message):
    with pytest.raises(ValueError, match=message):
        school_holidays.load_calendar(_write(tmp_path, body))


# --- the export (school-holidays.json) --------------------------------------------------------

def test_the_committed_calendar_exports_its_twelve_breaks_and_an_unreviewed_copy_none(ctx, tmp_path):  # noqa: F811
    """The site gets the sources to cite always, and the breaks only with the review flag."""
    from escapadinha import pipeline, site_data
    from test_site_data import read, validation_errors
    conn = pipeline.open_db(ctx)
    out = tmp_path / "site-data"
    site_data.build_export(ctx, conn, db.utcnow(), new_links=False).write(out)
    assert validation_errors(out) == []
    assert read(out, "meta.json")["files"]["school_holidays"] == "school-holidays.json"
    doc = read(out, "school-holidays.json")
    assert doc["reviewed"] is True and len(doc["breaks"]) == 12 and doc["last_checked"] == "2026-11-05"
    assert [n["key"] for n in doc["networks"]] == ["continente", "madeira", "acores"]
    assert all(n["source"].startswith("https://") for n in doc["networks"])
    assert doc["breaks"][0]["slug"] == "natal-2026-continente"
    ctx.school_holidays_file.write_text(
        ctx.school_holidays_file.read_text("utf-8").replace("reviewed: true", "reviewed: false", 1), "utf-8")
    again = tmp_path / "again"
    site_data.build_export(ctx, conn, db.utcnow(), new_links=False).write(again)
    assert validation_errors(again) == []
    draft = read(again, "school-holidays.json")
    assert draft["reviewed"] is False and draft["breaks"] == [] and len(draft["networks"]) == 3


def test_a_reviewed_calendar_exports_every_break_with_its_window_and_a_page_per_origin(ctx, tmp_path):  # noqa: F811
    from escapadinha import pipeline, site_data
    from test_site_data import read, validation_errors
    ctx.school_holidays_file.write_text(
        "reviewed: true\nlast_checked: 2026-11-05\nnetworks:\n"
        "  - key: continente\n    name: Continente\n    source: https://example.com/despacho\n"
        "    source_name: Despacho de teste\n    breaks:\n"
        "      - {slug: natal-2026, name: Férias de Natal, start: 2026-12-16, end: 2026-12-31}\n"
        "  - key: madeira\n    name: Madeira\n    source: https://example.com/joram\n"
        "    source_name: Despacho da Madeira\n    breaks:\n"
        "      - {slug: natal-2026, name: Férias de Natal, start: 2026-12-17, end: 2026-12-31}\n",
        "utf-8")
    conn = pipeline.open_db(ctx)
    out = tmp_path / "site-data"
    site_data.build_export(ctx, conn, db.utcnow(), new_links=False).write(out)
    assert validation_errors(out) == []
    doc = read(out, "school-holidays.json")
    assert doc["reviewed"] is True
    assert [b["slug"] for b in doc["breaks"]] == ["natal-2026-continente", "natal-2026-madeira"]
    first = doc["breaks"][0]
    assert (first["network"], first["name"], first["start"], first["end"]) == (
        "continente", "Férias de Natal", "2026-12-16", "2026-12-31")
    assert first["window"] == {"start": "2026-12-15", "end": "2027-01-01"}
    assert [o["iata"] for o in first["origins"]] == [o["iata"] for o in read(out, "origins.json")["origins"]]
    assert first["origins"][0]["path"].startswith("/ferias-escolares/natal-2026-continente/")
    assert first["origins"][0]["path"].endswith("/")
    assert json.dumps(doc).count("€") == 0                         # dates and names only
