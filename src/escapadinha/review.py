"""Approval queue rules: which status changes a reviewer may make. Pure, no I/O.

    new ──render──▶ rendered ──approve (live price check)──▶ approved ──▶ published
      │                │                                        │
      └────────────────┴──── reject / expire (recheck) ─────────┘

`expired` is only set by price rechecks; `rejected`, `expired` and `published` are final.
`render` (new → rendered) and rechecks belong to the pipeline; approve / reject / published are
review decisions, written as events and applied by the pipeline (review_events.py, D26).
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


class UnknownDeal(ReviewError):
    """The deal is not in this database (the review page answers 404)."""


STATUS_PT = {"new": "novo", "rendered": "por rever", "approved": "aprovado",
             "published": "publicado", "rejected": "rejeitado", "expired": "expirado"}


def ensure_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, set()):
        raise ReviewError(f"Não é possível passar de '{STATUS_PT.get(current, current)}' "
                          f"para '{STATUS_PT.get(target, target)}'.")


# Review decisions (D26): the event type a reviewer writes -> the status it moves the deal to.
DECISIONS: dict[str, str] = {"approve": "approved", "reject": "rejected", "published": "published"}
DECISION_PT = {"approve": "aprovar", "reject": "rejeitar", "published": "marcar como publicado"}


def check_decision(kind: str, status: str, *, affiliate_url: str | None,
                   post_url: str | None = None) -> str:
    """The status a decision moves a deal to, or ReviewError (pt-PT) when it isn't allowed now.

    The same rules run before an event is written (CLI, review page) and again when the
    pipeline applies it, against the status the deal has by then.
    """
    if kind not in DECISIONS:
        raise ReviewError(f"Decisão desconhecida: '{kind}'.")
    target = DECISIONS[kind]
    ensure_transition(status, target)
    if kind == "approve" and not affiliate_url:
        raise ReviewError("Este deal ainda não tem link de afiliado. Volta a renderizar.")
    if kind == "published" and post_url and not post_url.startswith(("https://", "http://")):
        raise ReviewError("O link do post tem de começar por https://")
    return target
