"""Approval queue rules: which status changes a reviewer may make. Pure, no I/O.

    new ──render──▶ rendered ──approve (live price check)──▶ approved ──▶ published
      │                │                                        │
      └────────────────┴──── reject / expire (recheck) ─────────┘

`expired` is only set by price rechecks; `rejected`, `expired` and `published` are final.
"""

from __future__ import annotations

TRANSITIONS: dict[str, set[str]] = {
    "new": {"rendered", "rejected", "expired"},
    "rendered": {"approved", "rejected", "expired"},
    "approved": {"published", "rejected", "expired"},
    "rejected": set(),
    "expired": set(),
    "published": set(),
}

# Tabs of the review page -> statuses shown.
TABS: dict[str, tuple[str, ...]] = {
    "queue": ("rendered", "new"),
    "approved": ("approved",),
    "published": ("published",),
    "closed": ("expired", "rejected"),
}


class ReviewError(RuntimeError):
    """A review action that is not allowed; the message is shown to the reviewer (pt-PT)."""


STATUS_PT = {"new": "novo", "rendered": "por rever", "approved": "aprovado",
             "published": "publicado", "rejected": "rejeitado", "expired": "expirado"}


def ensure_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, set()):
        raise ReviewError(f"Não é possível passar de '{STATUS_PT.get(current, current)}' "
                          f"para '{STATUS_PT.get(target, target)}'.")
