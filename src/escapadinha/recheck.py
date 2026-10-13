"""Re-verify open deals against the newest collection run. Pure functions, no I/O.

A deal stays valid only while the newest run still offers the same trip (same departure
and return dates) at the deal price or lower, found by travellers recently. Otherwise it
expires and must not be published: the source is a cache and prices move fast.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from escapadinha import i18n_pt as pt
from escapadinha.config import DetectorConfig
from escapadinha.detector import DIRECT, eligible, is_fresh
from escapadinha.models import Observation, RouteRules


@dataclass(frozen=True)
class Recheck:
    valid: bool
    latest_price: float | None
    reason: str


def recheck(deal_obs: Observation, latest: list[Observation], cfg: DetectorConfig,
            now: datetime, tolerance_eur: float = 0.0, rules: RouteRules = DIRECT) -> Recheck:
    """`latest`: the newest run's observations for the deal's route; `rules`: that route's."""
    if not rules.allows(deal_obs):
        return Recheck(False, None, _rule_broken(deal_obs, rules))
    same_trip = [o for o in eligible(latest, rules)
                 if o.departure_date == deal_obs.departure_date
                 and o.return_date == deal_obs.return_date]
    if not same_trip:
        return Recheck(False, None, "a viagem já não aparece nos preços mais recentes")
    best = min(same_trip, key=lambda o: o.price)
    if best.price > deal_obs.price + tolerance_eur:
        return Recheck(False, best.price, f"o preço subiu para {pt.eur(best.price)}")
    if not is_fresh(best, cfg, now):
        return Recheck(False, best.price,
                       f"o preço foi visto pela última vez a {best.found_date:%d/%m}, há mais "
                       f"de {cfg.max_offer_age_days} dias")
    return Recheck(True, best.price, f"continua a {pt.eur(best.price)}")


def _rule_broken(deal_obs: Observation, rules: RouteRules) -> str:
    if not rules.min_nights <= deal_obs.nights <= rules.max_nights:
        return f"fora do intervalo de {rules.min_nights}–{rules.max_nights} noites da rota"
    if rules.direct_only:
        return "não é ida e volta com voos diretos (regra direct_only)"
    return f"tem mais de {rules.max_transfers} escala(s) num dos sentidos (regra max_transfers)"
