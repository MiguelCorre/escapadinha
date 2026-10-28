"""Automatic approval for the website (D46): the rules a rendered promotion candidate must pass
for the pipeline to approve it itself. Pure: the deal, its offer, the config and `now` are
passed in; nothing is read or written here. No daily cap (D51): every candidate that passes
the rules and the live price check goes live.

An automatic approval is an ordinary review decision (D26): `pipeline.run_auto_approve` writes an
approve event with actor `ACTOR` through `pipeline.approve` (so the live price check is the gate,
exactly as for a human), then applies pending events, and the run's deploy puts the promotion on
the site. The human review page shows it under "Aprovadas" with the note `NOTE`; a reject there
expires the page like any other.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from escapadinha import detector
from escapadinha.config import AutoApproveConfig
from escapadinha.models import Deal, Observation
from escapadinha.review import CONFIDENCE_PT

ACTOR = "auto:regras"                  # the event's actor; `auto:` marks it in every listing
NOTE = "aprovação automática (D46)"    # the event's note, shown by both review pages


def disqualified(deal: Deal, obs: Observation, cfg: AutoApproveConfig, *,
                 now: datetime) -> str | None:
    """Why this candidate is left for a human (pt-PT), or None when every rule passes.

    The status transition and the affiliate link are checked by `review.check_decision` when
    the event is written, and the price by the live check: this only decides whether to try."""
    if not cfg.enabled:
        return "aprovação automática desligada"
    if deal.status != "rendered":
        return f"estado '{deal.status}' (só 'por rever')"
    if deal.rule != "median":
        return f"regra '{deal.rule}' (só o mínimo habitual)"
    if deal.confidence is None or not detector.at_least(deal.confidence, cfg.min_confidence):
        have = "desconhecida" if deal.confidence is None else CONFIDENCE_PT[deal.confidence]
        return f"confiança {have} (precisa de {CONFIDENCE_PT[cfg.min_confidence]})"
    if cfg.require_new_low and not deal.new_low:
        return "não é um novo mínimo"
    if cfg.direct_only and not detector.is_direct(obs):
        return "não é ida e volta com voos diretos"
    if obs.found_at is not None:
        age = now - obs.found_at
        if age > timedelta(hours=cfg.max_found_age_hours):
            hours = int(age.total_seconds() // 3600)
            return f"visto há {hours} h (máximo {cfg.max_found_age_hours:g} h)"
    return None


def summary(deal: Deal, obs: Observation) -> str:
    """One line for the run log: what passed."""
    bits = [f"confiança {CONFIDENCE_PT.get(deal.confidence or '', deal.confidence)}"]
    if deal.new_low:
        bits.append("novo mínimo")
    if detector.is_direct(obs):
        bits.append("voos diretos")
    return ", ".join(bits)
