"""Promotion outcomes (#74): what happened to deals after detection. Pure functions, no I/O.

Every expiry records when and why in a closed set of kinds (`EXPIRY_KINDS`, set by the code path
that expires the deal, never parsed from its pt-PT reason at run time), so the survival report
can tell a fare that went away from one that was only replaced by a better date.
"""

from __future__ import annotations

from datetime import datetime

# gone: the fare is no longer there at its source (price rose beyond the tolerance, trip
# vanished, price stale); superseded: still there, but no longer a promotion by our rules
# because of other data (a cheaper date is now the new low, the typical low moved or lost its
# maturity); rules: the deal breaks a route rule (nights range, D52; nonstop or stop limit).
EXPIRY_KINDS = ("gone", "superseded", "rules")

EXPIRY_KIND_PT = {"gone": "desaparecida", "superseded": "ultrapassada",
                  "rules": "fora das regras da rota"}


def approximate(expired_at: datetime | None, backfilled_before: datetime | None) -> bool:
    """An expiry time the v19 backfill wrote (`db.expiries_backfilled_before`): the deal's last
    check before the upgrade, not the moment it expired."""
    return (expired_at is not None and backfilled_before is not None
            and expired_at <= backfilled_before)
