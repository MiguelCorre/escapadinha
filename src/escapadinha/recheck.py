"""Re-verify open deals against the newest collection run. Pure functions, no I/O.

A deal stays valid only while the newest run still offers the same trip (same departure
and return dates) at the deal price or lower, found by travellers recently. Otherwise it
expires and must not be published: the source is a cache and prices move fast.

A deal no human approved yet must also still be a promotion against its month's current
typical low (`promotion_expiry`, D40): the detector's own rule, judged again on every run.

A deal from the cache may also be contradicted by the probe (`probe_contradiction`, D65): the
comparison sources only ever take a promotion down, never confirm or make one.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, TypeVar

from escapadinha import i18n_pt as pt
from escapadinha.collector import travelpayouts
from escapadinha.config import DetectorConfig, ProbeExpiryConfig
from escapadinha.detector import DIRECT, EPS, Baseline, eligible, evaluate, is_fresh
from escapadinha.models import Observation, RouteRules
from escapadinha.presentation import source_label


@dataclass(frozen=True)
class Recheck:
    valid: bool
    latest_price: float | None
    reason: str
    kind: str | None = None     # an invalid verdict's `outcomes.EXPIRY_KINDS` (#77); None: valid


def recheck(deal_obs: Observation, latest: list[Observation], cfg: DetectorConfig,
            now: datetime, tolerance_eur: float = 0.0, rules: RouteRules = DIRECT,
            typical_low: float | None = None) -> Recheck:
    """`latest`: the newest run's observations for the deal's route; `rules`: that route's.

    A risen price (D53) stays valid while it is at most `cfg.recheck_tolerance_pct` (plus
    `tolerance_eur`) above the deal's price and, with `typical_low` (the deal's stored typical
    low), still a promotion against it (`threshold` and `min_saving_eur`); the pages then show
    the latest price on its own observation. The review Function ports this rule
    (`live-check.ts`), the shared cases keep both sides equal."""
    if not rules.allows(deal_obs):
        return Recheck(False, None, _rule_broken(deal_obs, rules), "rules")
    same_trip = [o for o in eligible(latest, rules)
                 if o.departure_date == deal_obs.departure_date
                 and o.return_date == deal_obs.return_date]
    if not same_trip:
        return Recheck(False, None, "a viagem já não aparece nos preços mais recentes", "gone")
    best = min(same_trip, key=lambda o: o.price)
    rose = best.price > deal_obs.price + EPS
    if best.price > deal_obs.price * (1 + cfg.recheck_tolerance_pct) + tolerance_eur + EPS:
        return Recheck(False, best.price, f"o preço subiu para {pt.eur(best.price)}", "gone")
    if rose and typical_low is not None and not still_promotion(best.price, typical_low, cfg):
        return Recheck(False, best.price,
                       f"o preço subiu para {pt.eur(best.price)} e já não é promoção face ao "
                       f"preço habitual ({pt.eur(typical_low)})", "gone")
    if not is_fresh(best, cfg, now):
        return Recheck(False, best.price,
                       f"o preço foi visto pela última vez a {best.found_date:%d/%m}, há mais "
                       f"de {cfg.max_offer_age_days} dias", "gone")
    if rose:
        return Recheck(True, best.price, f"subiu para {pt.eur(best.price)}, dentro da tolerância "
                                         f"de {round(cfg.recheck_tolerance_pct * 100)}%")
    return Recheck(True, best.price, f"continua a {pt.eur(best.price)}")


def still_promotion(price: float, typical_low: float, cfg: DetectorConfig) -> bool:
    """`threshold` and `min_saving_eur` below `typical_low` (the detector's promotion rule on a
    price that moved after detection, D53)."""
    return (price <= typical_low * (1 - cfg.threshold) + EPS
            and typical_low - price >= cfg.min_saving_eur - EPS)


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


# --- the probe against the cache (D65) --------------------------------------------------------
#
# The cache can keep a price for days after it stopped being bookable, and its deals are
# rechecked only at the cache (D47). The probe's engines (D48, D49) are comparison sources: they
# never confirm a price, but when every configured engine recently saw the same trip, at the
# same airport, clearly dearer than the cache's price, the deal expires. The backtest's `probe`
# preset (docs/research/2026-11-11-probe-expiry.md) measures rules with these same functions
# (`cheapest_per_search`, `newest_search`, `rises_above`, `found_moment`, `contradicting`).

# The sources whose deals the probe may contradict: the cache's. An airline source's price is
# the seller's own, rechecked there every run (D47); a comparison source never makes a deal.
CACHE_SOURCES = frozenset({travelpayouts.SOURCE})


class Search(Protocol):
    """One engine's search of a trip, as far as the rule needs it."""

    engine: str
    at: datetime                 # the probe's search time
    price: float
    observation_id: int
    airport: str | None


S = TypeVar("S", bound=Search)


@dataclass(frozen=True)
class ProbeSearch:
    """One engine's search of a trip at its cheapest option (the probe reads the cheapest
    nonstop itinerary, then its booking options: one stored row per option)."""

    engine: str
    at: datetime
    price: float
    observation_id: int
    airport: str | None
    seller: str | None = None


def cheapest_per_search(searches: Iterable[S]) -> list[S]:
    """One per (engine, search time): the cheapest, the first given on a tie; oldest first."""
    best: dict[tuple[str, datetime], S] = {}
    for x in searches:
        key = (x.engine, x.at)
        if key not in best or x.price < best[key].price:
            best[key] = x
    return sorted(best.values(), key=lambda x: (x.at, x.engine))


def _sightings(o: Observation) -> tuple[datetime, ...]:
    later = o.last_seen_at is not None and o.last_seen_at > o.fetched_at
    return (o.fetched_at, o.last_seen_at) if later else (o.fetched_at,)


def probe_sightings(readings: Iterable[Observation]) -> list[ProbeSearch]:
    """Every sighting in a trip's stored probe rows, in row order (not yet one per search:
    `contradicting` takes each search's cheapest option at the deal's airport). A row is a
    search at `fetched_at` and, when later, another at `last_seen_at`: the dedup keeps one row
    for an option seen again at the same price on the same found day, and `last_seen_at` is
    that repeat's own search time (`results.to_observations` sets `fetched_at` to the search
    time; `db.insert_observations` moves `last_seen_at` to a repeat's `fetched_at`), never the
    import's."""
    rows = sorted(readings, key=lambda o: o.id or 0)
    return [ProbeSearch(o.source, at, o.price, o.id, o.destination_airport, o.gate)
            for o in rows for at in _sightings(o)]


def found_moment(found_at: datetime | None, fetched_at: datetime | None) -> datetime | None:
    """When a price was found, as far as the probe rule may assume: the exact time a traveller
    found it (`found_at`, from the enrichment or the airline), else the first time the
    pipeline fetched it, which is never earlier than the real find. Not the found day's start:
    a deal detected this run has no `found_at` yet (the enrichment runs after `detect`), and a
    price that appeared at 14:00 must not be contradicted by a search at 06:00."""
    return found_at if found_at is not None else fetched_at


def is_nonstop(o: Observation) -> bool:
    """Nonstop both ways, known: the only itineraries the probe reads (D48, D49)."""
    return o.transfers == 0 and o.return_transfers == 0


def newest_search(searches: Sequence[S], engine: str, now: datetime, max_age: timedelta, *,
                  since: datetime | None = None) -> S | None:
    """The engine's newest search made by `now` (and, with `since`, at or after it), if no older
    than `max_age`."""
    usable = [x for x in searches if x.engine == engine and x.at <= now
              and (since is None or x.at >= since)]
    if not usable:
        return None
    newest = max(usable, key=lambda x: x.at)
    return newest if now - newest.at <= max_age else None


def rises_above(price: float, other: float, pct: float, eur: float) -> bool:
    """`other` is at least `pct` and `eur` above `price`."""
    return other / price - 1 >= pct - EPS and other - price >= eur - EPS


def contradicting(price: float, airport: str | None, found: datetime | None, nonstop: bool,
                  sightings: Sequence[S], *, engines: Sequence[str], pct: float, eur: float,
                  max_age: timedelta, now: datetime) -> tuple[S, ...] | None:
    """The searches that contradict a price, one per engine in `engines`' order, or None.

    Only a nonstop price (the probe reads nonstop itineraries only). The sightings at
    `airport` give each search's cheapest option there (`cheapest_per_search`, so an option at
    another airport neither hides nor stands in); each engine's newest search made at or after
    `found` and by `now` must be no older than `max_age` and `pct` and `eur` above `price`. No
    airport or found time known, or an engine without such a search (paused, walled, not
    searched yet): None."""
    if not (nonstop and engines) or airport is None or found is None:
        return None
    here = cheapest_per_search(x for x in sightings if x.airport == airport)
    fresh = [newest_search(here, engine, now, max_age, since=found) for engine in engines]
    if all(x is not None and rises_above(price, x.price, pct, eur) for x in fresh):
        return tuple(fresh)
    return None


@dataclass(frozen=True)
class Contradiction:
    """The probe's searches that take a cache deal down (D65), one per configured engine."""

    searches: tuple[ProbeSearch, ...]

    @property
    def at(self) -> datetime:
        return max(x.at for x in self.searches)

    @property
    def reason(self) -> str:
        """pt-PT, without a euro amount (`i18n_pt.probe_contradiction`)."""
        return pt.probe_contradiction([source_label(x.engine) for x in self.searches], self.at)


def probe_contradiction(deal_obs: Observation, readings: Iterable[Observation],
                        cfg: ProbeExpiryConfig, now: datetime) -> Contradiction | None:
    """Whether the probe contradicts an open deal's price (D65); None while it does not.

    `readings`: the stored probe rows of the deal's trip (every row, any engine; a row of
    another trip is ignored). Only a deal from `CACHE_SOURCES`, only with `cfg.enabled`: every
    engine of `cfg.engines` searched the trip at the deal's arrival airport after its price was
    found (`found_moment`: `found_at`, else the first fetch), the deal is nonstop both ways
    (`is_nonstop`), the newest such search is no older than
    `cfg.max_age_hours`, and its cheapest option is `cfg.min_rise_pct` and `cfg.min_rise_eur`
    above the deal's price (`contradicting`)."""
    if not cfg.enabled or deal_obs.source not in CACHE_SOURCES:
        return None
    key = (deal_obs.origin, deal_obs.destination, deal_obs.departure_date, deal_obs.return_date)
    trip = [o for o in readings if (o.origin, o.destination, o.departure_date, o.return_date) == key]
    hit = contradicting(deal_obs.price, deal_obs.destination_airport,
                        found_moment(deal_obs.found_at, deal_obs.fetched_at), is_nonstop(deal_obs),
                        probe_sightings(trip),
                        engines=cfg.engines, pct=cfg.min_rise_pct, eur=cfg.min_rise_eur,
                        max_age=timedelta(hours=cfg.max_age_hours), now=now)
    return None if hit is None else Contradiction(hit)
