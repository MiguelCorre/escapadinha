"""The suite's pinned clock (D54, `clock.py`) and the one wall clock the code and tests read."""

import re
from datetime import timedelta
from pathlib import Path

import clock
from escapadinha.collector import travelpayouts
from escapadinha.storage import db, objects

REPO = Path(__file__).parent.parent


def test_the_suite_runs_on_the_pinned_clock():
    """Modules that took `utcnow` by name read the pinned clock too."""
    assert clock.ANCHOR <= db.utcnow() < clock.ANCHOR + timedelta(hours=6)
    assert travelpayouts.utcnow is objects.utcnow is db.utcnow is clock.pinned


def test_the_wall_clock_is_read_only_through_db_utcnow():
    """Any other read of today's date escapes the pin, and a test built on it fails by date."""
    read = re.compile(r"\b(?:datetime|date)\.(?:now|utcnow|today)\(")
    found = [f"{path.relative_to(REPO).as_posix()}: {line.strip()}"
             for folder in ("src", "tests") for path in sorted((REPO / folder).rglob("*.py"))
             if path != Path(__file__)
             for line in path.read_text("utf-8").splitlines() if read.search(line)]
    assert found == ["src/escapadinha/storage/db.py: "
                     "return datetime.now(timezone.utc).replace(microsecond=0)"]
