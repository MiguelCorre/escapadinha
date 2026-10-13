"""Deal detection. Pure functions: no I/O, no clock, so every rule is unit-testable.

A deal is a fresh price well below the route's *typical lowest price* for the same
departure month. The typical lowest price is the median of daily lows: for each day,
the cheapest price travellers found for that route and month.

Comparing against daily lows (not against all fares) matters: the cheapest dates of a
route are always far below the median of all fares, so that rule flags almost every
route on every run. Daily lows are keyed by the day a traveller found the price (from
the source cache), so a fresh install has about a week of baseline from its first run.

Days inside the freshness window (the last `max_offer_age_days`) are candidates, older
days form the baseline, so a candidate never pulls its own baseline down.

Each route has its own rules (direct only or a stop limit, nights range): offers outside
them count neither as candidates nor towards the baseline.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from escapadinha.config import DetectorConfig
from escapadinha.models import Observation, RouteRules

Month = tuple[int, int]

DIRECT = RouteRules()   # Europe default: nonstop both ways, 2-10 nights


@dataclass(frozen=True)
class Baseline:
    median: float | None      # median of daily lowest prices
    sample_size: int          # number of days with a low
    span_days: int            # first to last baseline day


@dataclass(frozen=True)
class Decision:
    kind: str                    # deal | no_deal | insufficient_history
    rule: str | None             # median | price_cap (only for deals)
    discount_pct: float | None   # vs. the typical low, only for the median rule
    reason: str


@dataclass(frozen=True)
class Flag:
    observation: Observation
    decision: Decision
    baseline: Baseline


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


def baseline(history: list[Observation], *, since: date, before: date) -> Baseline:
    """Median of daily lows over days in [since, before)."""
    lows: dict[date, float] = {}
    for o in history:
        day = day_key(o)
        if since <= day < before:
            lows[day] = min(o.price, lows.get(day, o.price))
    if not lows:
        return Baseline(median=None, sample_size=0, span_days=0)
    return Baseline(median=statistics.median(lows.values()), sample_size=len(lows),
                    span_days=(max(lows) - min(lows)).days)


def month_baselines(history: list[Observation], cfg: DetectorConfig, now: datetime,
                    rules: RouteRules = DIRECT) -> dict[Month, Baseline]:
    by_month: dict[Month, list[Observation]] = defaultdict(list)
    for o in eligible(history, rules):
        by_month[month_key(o)].append(o)
    since = now.date() - timedelta(days=cfg.lookback_days)
    before = fresh_since(cfg, now)
    return {m: baseline(obs, since=since, before=before) for m, obs in by_month.items()}


def evaluate(candidate: Observation, base: Baseline, cfg: DetectorConfig,
             price_cap: float | None) -> Decision:
    if base.sample_size < cfg.min_baseline_days:
        why = f"baseline {base.sample_size}/{cfg.min_baseline_days} days"
        if price_cap is not None and candidate.price <= price_cap:
            return Decision("deal", "price_cap", None, f"{why}; price <= cap {price_cap:g}")
        return Decision("insufficient_history", None, None, why)

    limit = base.median * (1 - cfg.threshold)
    discount = 1 - candidate.price / base.median
    if candidate.price <= limit + 1e-9:
        return Decision("deal", "median", discount,
                        f"{candidate.price:g} is {discount:.0%} below typical low {base.median:g}")
    return Decision("no_deal", None, None,
                    f"{candidate.price:g} vs limit {limit:.2f} (typical low {base.median:g})")


def _already_flagged(candidate: Observation, recent: list[Observation]) -> bool:
    """Same trip already posted at the same or a lower price."""
    return any(
        r.departure_date == candidate.departure_date
        and r.return_date == candidate.return_date
        and r.price <= candidate.price
        for r in recent
    )


def detect_route(candidates: list[Observation], history: list[Observation],
                 recently_flagged: list[Observation], cfg: DetectorConfig,
                 price_cap: float | None, now: datetime, max_deals: int,
                 rules: RouteRules = DIRECT) -> list[Flag]:
    """Deals among one route's candidates, biggest discount first, at most `max_deals`.

    `history` may include the candidates' own run: only days before the freshness
    window count towards the baseline.
    """
    baselines = month_baselines(history, cfg, now, rules)
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
    chosen, seen = [], set()
    for f in flags:
        trip = (f.observation.departure_date, f.observation.return_date)
        if trip in seen:
            continue
        seen.add(trip)
        chosen.append(f)
        if len(chosen) >= max_deals:
            break
    return chosen
