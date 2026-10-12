"""Deal detection. Pure functions: no I/O, no clock, so every rule is unit-testable.

A price is a deal when it is at least `threshold` below the route's historical median.
While a route has too little history the median is not trusted; only an explicit
per-route `price_cap_eur` can flag a deal then, otherwise nothing is flagged.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

from escapadinha.config import DetectorConfig
from escapadinha.models import Observation


@dataclass(frozen=True)
class Baseline:
    median: float | None
    sample_size: int
    span_days: float


@dataclass(frozen=True)
class Decision:
    kind: str                    # deal | no_deal | insufficient_history
    rule: str | None             # median | price_cap (only for deals)
    discount_pct: float | None   # vs. median, only for the median rule
    reason: str


def baseline(history: list[Observation]) -> Baseline:
    """Median over history, counting each offer at most once per calendar day.

    The source is a cache, so consecutive runs return the same offers; without this
    the most frequently re-fetched offers would dominate the median.
    """
    samples: dict[tuple, Observation] = {}
    for o in history:
        samples.setdefault((o.offer_key, o.fetched_at.date()), o)
    if not samples:
        return Baseline(median=None, sample_size=0, span_days=0)
    times = [o.fetched_at for o in samples.values()]
    span = (max(times) - min(times)).total_seconds() / 86400
    return Baseline(median=statistics.median(o.price for o in samples.values()),
                    sample_size=len(samples), span_days=span)


def evaluate(candidate: Observation, base: Baseline, cfg: DetectorConfig,
             price_cap: float | None) -> Decision:
    if base.sample_size < cfg.min_samples or base.span_days < cfg.min_history_days:
        why = (f"history {base.sample_size}/{cfg.min_samples} samples over "
               f"{base.span_days:.1f}/{cfg.min_history_days} days")
        if price_cap is not None and candidate.price <= price_cap:
            return Decision("deal", "price_cap", None, f"{why}; price <= cap {price_cap:g}")
        return Decision("insufficient_history", None, None, why)

    limit = base.median * (1 - cfg.threshold)
    discount = 1 - candidate.price / base.median
    if candidate.price <= limit + 1e-9:
        return Decision("deal", "median", discount,
                        f"{candidate.price:g} is {discount:.0%} below median {base.median:g}")
    return Decision("no_deal", None, None,
                    f"{candidate.price:g} vs limit {limit:.2f} (median {base.median:g})")


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
                 price_cap: float | None, now: datetime, max_deals: int
                 ) -> list[tuple[Observation, Decision]]:
    """Deals among one route's fresh candidates, cheapest first, at most `max_deals`."""
    base = route_baseline(history, cfg, now)
    dedupe_start = now - timedelta(days=cfg.dedupe_days)
    recent = [r for r in recently_flagged if r.fetched_at >= dedupe_start]

    deals = []
    for candidate in sorted(candidates, key=lambda o: o.price):
        decision = evaluate(candidate, base, cfg, price_cap)
        if decision.kind != "deal" or _already_flagged(candidate, recent):
            continue
        deals.append((candidate, decision))
        if len(deals) >= max_deals:
            break
    return deals


def route_baseline(history: list[Observation], cfg: DetectorConfig, now: datetime) -> Baseline:
    """Baseline restricted to the configured lookback window."""
    return baseline([o for o in history if o.fetched_at >= now - timedelta(days=cfg.lookback_days)])
