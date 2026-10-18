"""Re-verify open deals against the newest collection run. Pure functions, no I/O.

A deal stays valid only while the newest run still offers the same trip (same departure
and return dates) at the deal price or lower, found by travellers recently. Otherwise it
expires and must not be published: the source is a cache and prices move fast.

A deal no human approved yet must also still be a promotion against its month's current
typical low (`promotion_expiry`, D40): the detector's own rule, judged again on every run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from escapadinha import i18n_pt as pt
from escapadinha.config import DetectorConfig
from escapadinha.detector import DIRECT, EPS, Baseline, eligible, evaluate, is_fresh
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


def promotion_expiry(deal_obs: Observation, rule: str, base: Baseline, cfg: DetectorConfig,
                     price_cap: float | None) -> str | None:
    """Why a deal awaiting review is no longer a promotion against `base`, its departure
    month's current typical low (D40), in pt-PT; None while it still is.

    The detector's own rule (`evaluate`), so a deal stays exactly when it would be detected now:
    a typical low mature for promotions, `threshold` AND `min_saving_eur` below it and, with
    `require_new_low`, still a new low (D44). The route's `price_cap` keeps only the deals it
    made (rule `price_cap`), and only while the typical low is not mature for promotions; a deal
    of the median rule never survives on it."""
    decision = evaluate(deal_obs, base, cfg, price_cap if rule == "price_cap" else None)
    if decision.kind == "deal":
        return None
    if decision.kind == "insufficient_history":
        need = cfg.min_baseline_days_promo
        why = (f"{base.sample_size} de {need} dias" if base.sample_size < need else
               f"{base.sample_size} dias, mas do primeiro ao último só {base.span_days} de "
               f"{cfg.min_baseline_span_days}")
        return f"preço habitual ainda sem dados suficientes ({why})"
    below = 1 - deal_obs.price / base.median
    limit = base.median * (1 - cfg.threshold)
    if deal_obs.price <= limit + EPS and base.median - deal_obs.price >= cfg.min_saving_eur - EPS:
        # Only the new-low rule failed: a cheaper offer joined the window since detection.
        return (f"já não é um novo mínimo: entretanto vimos {pt.eur(base.min_low.price)} para "
                f"este mês, e {pt.eur(deal_obs.price)} teria de ficar "
                f"{round(cfg.new_low_margin * 100)}% abaixo disso")
    where = f"{round(abs(below) * 100)}% {'abaixo' if below >= 0 else 'acima'}"
    return (f"já não é promoção face ao preço habitual atual ({pt.eur(base.median)}): "
            f"{pt.eur(deal_obs.price)} fica {where}; são precisos {round(cfg.threshold * 100)}% e "
            f"{pt.eur(cfg.min_saving_eur)}")
