"""The suite's clock (D54): `db.utcnow()` reads ANCHOR at the start of the session plus the real
time elapsed since, so it still moves. Tests and fixtures carry fixed trip dates (LIS-LON
departures in November 2026); on the real clock they aged out of the baseline's minimum lead
(D44) and would fall into the past."""

import sys
import time
from datetime import datetime, timedelta, timezone

from escapadinha.storage import db

# The whole suite passes for anchors from 2026-10-22 to 10-28 (noon UTC); this one is
# test_auto_review's `NOW`, two days inside either end.
ANCHOR = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
REAL = db.utcnow
_started = time.monotonic()


def pinned() -> datetime:
    return (ANCHOR + timedelta(seconds=time.monotonic() - _started)).replace(microsecond=0)


def _swap(old, new) -> None:
    """Every module that took `utcnow` by name (`from escapadinha.storage.db import utcnow`)
    holds its own reference; modules imported later read the swapped one from `db`."""
    for name, module in list(sys.modules.items()):
        if name.split(".")[0] == "escapadinha" and getattr(module, "utcnow", None) is old:
            module.utcnow = new


def pin() -> None:
    global _started
    _started = time.monotonic()
    _swap(REAL, pinned)


def unpin() -> None:
    _swap(pinned, REAL)
