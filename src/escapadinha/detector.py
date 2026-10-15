"""Deal detection. Pure functions: no I/O, no clock, so every rule is unit-testable.

Prices are measured against the route's *typical lowest price* for the same departure
month: the median of daily lows (for each day, the cheapest price travellers found for
that route and month). Each run yields two tiers (D24):

- **low prices**: fresh offers at least `low_threshold` below the typical low. Shown on
  the route pages automatically, never reviewed, so they need a mature baseline
  (`min_baseline_days` daily lows).
- **promotion candidates**: fresh offers at least `threshold` AND `min_saving_eur` below
  the typical low, one per route per run, deduplicated over `dedupe_days`. They become
  deals for human review, so they need a typical low mature for promotions
  (`min_baseline_days_promo` daily lows spanning `min_baseline_span_days`, D40). Until then
  only an explicit per-route `price_cap` can make a candidate.

Comparing against daily lows (not against all fares) matters: the cheapest dates of a
route are always far below the median of all fares, so that rule flags almost every
route on every run. Daily lows are keyed by the day a traveller found the price (from
the source cache), so a fresh install has about a week of baseline from its first run.
A day counts only if its offers have `min_dates_per_day` different departure dates: a
day with one searched date is three times as likely to be a high outlier (D40).

Days inside the freshness window (the last `max_offer_age_days`) are candidates, older
days form the baseline, so a candidate never pulls its own baseline down.

Each route has its own rules (direct only or a stop limit, nights range): offers outside
them count neither as candidates nor towards the baseline.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TypeVar

from escapadinha.config import DetectorConfig
from escapadinha.models import Observation, RouteRules

Month = tuple[int, int]
T = TypeVar("T")

DIRECT = RouteRules()   # Europe default: nonstop both ways, 2-10 nights
EPS = 1e-9


@dataclass(frozen=True)
class Baseline:
    median: float | None      # median of daily lowest prices
    sample_size: int          # number of days with a low (days that count, D40)
    span_days: int            # first to last baseline day
    mean: float | None = None  # plain average of the same daily lows: context only (D27)
    lowest: Observation | None = None    # the cheapest daily low (shown to the reviewer, D40)
    highest: Observation | None = None   # the dearest daily low


@dataclass(frozen=True)
class Decision:
    kind: str                    # deal | no_deal | insufficient_history
    rule: str | None             # median | price_cap (only for deals)
    discount_pct: float | None   # vs. the typical low, only for the median rule
    reason: str


@dataclass(frozen=True)
class Flag:
    """A promotion candidate: becomes a deal in status `new`."""

    observation: Observation
    decision: Decision
    baseline: Baseline


@dataclass(frozen=True)
class LowPrice:
    """A fresh offer at least `low_threshold` below its month's typical low."""

    observation: Observation
    baseline: Baseline
    discount_pct: float          # 0.2 = 20 % below the typical low


@dataclass(frozen=True)
class Detection:
    low_prices: list[LowPrice]   # every low price, biggest discount first, one per trip dates
    candidates: list[Flag]       # promotion candidates, at most `max_deals`


def day_key(o: Observation) -> date:
    """The day a price was seen: found date from the source, else the day we fetched it."""
    return o.found_date or o.fetched_at.date()


def is_direct(o: Observation) -> bool:
    """Nonstop both ways. Unknown transfer counts are not assumed direct."""
    return o.transfers == 0 and o.return_transfers == 0


def eligible(observations: list[Observation], rules: RouteRules) -> list[Observation]:
    """Offers that may be deals or baseline: within the route's stop limit and nights range."""
    return [o for o in observations if rules.allows(o)]


def month_key(o: Observation) -> Month:
    return (o.departure_date.year, o.departure_date.month)


def fresh_since(cfg: DetectorConfig, now: datetime) -> date:
    """First day of the freshness window: newer prices are candidates, older ones baseline."""
    return now.date() - timedelta(days=cfg.max_offer_age_days)


def is_fresh(o: Observation, cfg: DetectorConfig, now: datetime) -> bool:
    return day_key(o) >= fresh_since(cfg, now)


def baseline(history: list[Observation], *, since: date, before: date,
             min_dates: int = 1) -> Baseline:
    """Median of daily lows over days in [since, before). A day counts only when its offers
    have at least `min_dates` different departure dates (D40)."""
    by_day: dict[date, list[Observation]] = defaultdict(list)
    for o in history:
        if since <= day_key(o) < before:
            by_day[day_key(o)].append(o)
    lows = {day: min(offers, key=lambda o: (o.price, o.departure_date, o.id or 0))
            for day, offers in sorted(by_day.items())
            if len({o.departure_date for o in offers}) >= min_dates}
    if not lows:
        return Baseline(median=None, sample_size=0, span_days=0)
    prices = [o.price for o in lows.values()]
    return Baseline(median=statistics.median(prices), sample_size=len(lows),
                    span_days=(max(lows) - min(lows)).days, mean=statistics.fmean(prices),
                    lowest=min(lows.values(), key=lambda o: o.price),
                    highest=max(lows.values(), key=lambda o: o.price))


def month_baselines(history: list[Observation], cfg: DetectorConfig, now: datetime,
                    rules: RouteRules = DIRECT) -> dict[Month, Baseline]:
    by_month: dict[Month, list[Observation]] = defaultdict(list)
    for o in eligible(history, rules):
        by_month[month_key(o)].append(o)
    since = now.date() - timedelta(days=cfg.lookback_days)
    before = fresh_since(cfg, now)
    return {m: baseline(obs, since=since, before=before, min_dates=cfg.min_dates_per_day)
            for m, obs in by_month.items()}


def is_mature(base: Baseline, cfg: DetectorConfig) -> bool:
    """Enough daily lows to trust the typical low: low prices and the site's typical lows."""
    return base.median is not None and base.sample_size >= cfg.min_baseline_days


def is_mature_for_promotions(base: Baseline, cfg: DetectorConfig) -> bool:
    """Enough daily lows, spread over enough days, to propose a promotion (D40)."""
    return (base.median is not None and base.sample_size >= cfg.min_baseline_days_promo
            and base.span_days >= cfg.min_baseline_span_days)


def evaluate(candidate: Observation, base: Baseline, cfg: DetectorConfig,
             price_cap: float | None) -> Decision:
    """Promotion candidate or not: `threshold` and `min_saving_eur` below a typical low that
    is mature for promotions."""
    if not is_mature_for_promotions(base, cfg):
        why = (f"baseline {base.sample_size}/{cfg.min_baseline_days_promo} days, "
               f"span {base.span_days}/{cfg.min_baseline_span_days} days")
        if price_cap is not None and candidate.price <= price_cap:
            return Decision("deal", "price_cap", None, f"{why}; price <= cap {price_cap:g}")
        return Decision("insufficient_history", None, None, why)

    limit = base.median * (1 - cfg.threshold)
    saving = base.median - candidate.price
    discount = 1 - candidate.price / base.median
    if candidate.price > limit + EPS:
        return Decision("no_deal", None, None,
                        f"{candidate.price:g} vs limit {limit:.2f} (typical low {base.median:g})")
    if saving < cfg.min_saving_eur - EPS:
        return Decision("no_deal", None, None,
                        f"{candidate.price:g} is {discount:.0%} below typical low {base.median:g} "
                        f"but saves only {saving:.2f} (< {cfg.min_saving_eur:g})")
    return Decision("deal", "median", discount,
                    f"{candidate.price:g} is {discount:.0%} below typical low {base.median:g}")


def low_discount(o: Observation, base: Baseline, cfg: DetectorConfig) -> float | None:
    """Discount vs the typical low when `o` is a low price (mature baseline only), else None."""
    if not is_mature(base, cfg) or o.price > base.median * (1 - cfg.low_threshold) + EPS:
        return None
    return 1 - o.price / base.median


def _already_flagged(candidate: Observation, recent: list[Observation]) -> bool:
    """Same trip already posted at the same or a lower price."""
    return any(
        r.departure_date == candidate.departure_date
        and r.return_date == candidate.return_date
        and r.price <= candidate.price
        for r in recent
    )


def _one_per_trip(items: list[T], obs: Callable[[T], Observation]) -> list[T]:
    """Keep the first item per (departure, return) dates; `items` are sorted best first."""
    chosen, seen = [], set()
    for item in items:
        trip = (obs(item).departure_date, obs(item).return_date)
        if trip not in seen:
            seen.add(trip)
            chosen.append(item)
    return chosen


def low_prices(offers: list[Observation], history: list[Observation], cfg: DetectorConfig,
               now: datetime, rules: RouteRules = DIRECT,
               baselines: dict[Month, Baseline] | None = None) -> list[LowPrice]:
    """One route's low prices among `offers`: fresh, within the rules, at least
    `low_threshold` below a mature typical low. Biggest discount first, one per trip dates
    (the cheapest). Offers that already are deals still count: a low price is not a post.
    There is no price-cap path: without a mature baseline there is nothing to be low against.
    """
    baselines = month_baselines(history, cfg, now, rules) if baselines is None else baselines
    empty = Baseline(None, 0, 0)
    lows = []
    for o in eligible(offers, rules):
        if not is_fresh(o, cfg, now):
            continue
        base = baselines.get(month_key(o), empty)
        discount = low_discount(o, base, cfg)
        if discount is not None:
            lows.append(LowPrice(o, base, discount))
    lows.sort(key=lambda lp: (-lp.discount_pct, lp.observation.price,
                              lp.observation.departure_date, lp.observation.id or 0))
    return _one_per_trip(lows, lambda lp: lp.observation)


def detect_route(candidates: list[Observation], history: list[Observation],
                 recently_flagged: list[Observation], cfg: DetectorConfig,
                 price_cap: float | None, now: datetime, max_deals: int,
                 rules: RouteRules = DIRECT,
                 baselines: dict[Month, Baseline] | None = None) -> list[Flag]:
    """Promotion candidates among one route's offers, biggest discount first, at most
    `max_deals`.

    `history` may include the candidates' own run: only days before the freshness
    window count towards the baseline.
    """
    baselines = month_baselines(history, cfg, now, rules) if baselines is None else baselines
    dedupe_start = now - timedelta(days=cfg.dedupe_days)
    recent = [r for r in recently_flagged if r.fetched_at >= dedupe_start]
    empty = Baseline(None, 0, 0)

    flags = []
    for candidate in eligible(candidates, rules):
        if not is_fresh(candidate, cfg, now) or _already_flagged(candidate, recent):
            continue
        base = baselines.get(month_key(candidate), empty)
        decision = evaluate(candidate, base, cfg, price_cap)
        if decision.kind == "deal":
            flags.append(Flag(candidate, decision, base))

    # Median-rule deals by discount, then cap deals by price; one deal per trip dates.
    flags.sort(key=lambda f: (f.decision.rule != "median", -(f.decision.discount_pct or 0),
                              f.observation.price))
    return _one_per_trip(flags, lambda f: f.observation)[:max_deals]


def detect(offers: list[Observation], history: list[Observation],
           recently_flagged: list[Observation], cfg: DetectorConfig, price_cap: float | None,
           now: datetime, max_deals: int, rules: RouteRules = DIRECT,
           taken: Collection[int] = ()) -> Detection:
    """Both tiers for one route's offers in a run.

    `taken`: ids of observations that already are deals (any status). They can still be
    low prices but never become a second deal.
    """
    baselines = month_baselines(history, cfg, now, rules)
    lows = low_prices(offers, history, cfg, now, rules, baselines)
    open_offers = [o for o in offers if o.id is None or o.id not in taken]
    candidates = detect_route(open_offers, history, recently_flagged, cfg, price_cap, now,
                              max_deals, rules, baselines)
    return Detection(lows, candidates)
