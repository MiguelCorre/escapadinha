"""Promotion outcomes (#74, D56): what happened to deals after detection. Pure functions, no I/O.

Every expiry records when and why in a closed set of kinds (`EXPIRY_KINDS`, set by the code path
that expires the deal, never parsed from its pt-PT reason at run time), so the survival report
can tell a fare that went away from one that was only replaced by a better date.

The survival report (#78): of the deals judged at 2, 6, 24 and 48 hours after detection (and
after approval), the share the recheck found gone by then. Open deals and `superseded`/`rules`
expiries count as surviving until their last check (censored), never as gone, so the numbers
never overstate how fast fares vanish. Rows come from `pipeline.deal_outcomes`.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import NamedTuple

from escapadinha import auto_review
from escapadinha.detector import EPS, lead_days
from escapadinha.models import Deal, Observation

# gone: the fare is no longer there at its source (price rose beyond the tolerance, trip
# vanished, price stale); superseded: still there, but no longer a promotion by our rules
# because of other data (a cheaper date is now the new low, the typical low moved or lost its
# maturity); rules: the deal breaks a route rule (nights range, D52; nonstop or stop limit).
EXPIRY_KINDS = ("gone", "superseded", "rules")

EXPIRY_KIND_PT = {"gone": "desaparecida", "superseded": "ultrapassada",
                  "rules": "fora das regras da rota"}

HORIZONS_H = (2, 6, 24, 48)
PUBLISHED_HOURS = 24                       # the visitors' sentence judges approvals at this mark
APPROVERS = ("rules", "human", "none")     # the automatic approval (D46), anyone else, nobody
# Bands as (upper bound, exclusive; None = no bound, label), in order.
LEAD_DAYS = ((14, "< 14"), (30, "14–29"), (60, "30–59"), (None, "60+"))   # found → departure
FOUND_AGE_H = ((2, "< 2"), (12, "2–12"), (None, "12+"))     # exact found time → detection
BREADTH = ((2, "0–1"), (4, "2–3"), (8, "4–7"), (None, "8+"))  # dates, the deal's own included
# Breadth (the research note's §2.3, Going's "many dates" rule): distinct departure dates on the
# deal's route, departure month and source, at most this much above its price, seen in this
# window before detection.
BREADTH_MARGIN = 0.10
BREADTH_WINDOW = timedelta(hours=6)
UNKNOWN = "unknown"
# Printed next to that source's row: why its deals look longer-lived than they were bookable.
CACHE_SOURCE = "travelpayouts"
CACHE_CAVEAT = ("The Travelpayouts source is a cache: it keeps prices travellers found earlier, "
                "which may already be gone at the airline, so its deals look longer-lived than "
                "they were bookable (research note 2026-11-03, finding 2).")


def approximate(expired_at: datetime | None, backfilled_before: datetime | None) -> bool:
    """An expiry time the v19 backfill wrote (`db.expiries_backfilled_before`): the deal's last
    check before the upgrade, not the moment it expired."""
    return (expired_at is not None and backfilled_before is not None
            and expired_at <= backfilled_before)


@dataclass(frozen=True)
class Outcome:
    """One deal as the report reads it (`outcome` builds it from the database's rows)."""
    deal_id: int
    detected_at: datetime
    last_checked_at: datetime | None
    expired_at: datetime | None
    expired_kind: str | None        # EXPIRY_KINDS; None while open, or an unknown old reason
    approximate: bool               # expired_at written by the v19 backfill
    approved_at: datetime | None    # None: never approved (or rejected afterwards)
    approver: str                   # APPROVERS
    source: str
    confidence: str | None
    lead_days: int
    found_age_h: float | None       # None: the exact found time is unknown
    route_kind: str
    breadth: int


def breadth(deal: Observation, seen: Iterable[Observation], at: datetime) -> int:
    """Distinct departure dates of the deal's route, departure month and source with a price at
    most `BREADTH_MARGIN` above the deal's, seen in the `BREADTH_WINDOW` before `at`; the
    deal's own date always counts."""
    since = at - BREADTH_WINDOW
    month = (deal.departure_date.year, deal.departure_date.month)
    limit = deal.price * (1 + BREADTH_MARGIN) + EPS
    return len({deal.departure_date} | {
        o.departure_date for o in seen
        if o.source == deal.source and o.route_key == deal.route_key
        and (o.departure_date.year, o.departure_date.month) == month and o.price <= limit
        and o.fetched_at <= at and (o.last_seen_at or o.fetched_at) >= since})


def outcome(deal: Deal, obs: Observation, *, route_kind: str, seen: Iterable[Observation],
            backfilled_before: datetime | None) -> Outcome:
    """`seen`: observations of the deal's route-month and source around its detection
    (`db.month_observations`). A rejected deal counts as never approved, even when the rules
    approved it first: its review time is the rejection's."""
    approved = deal.reviewed_at is not None and deal.status != "rejected"
    return Outcome(
        deal_id=deal.id, detected_at=deal.detected_at, last_checked_at=deal.last_checked_at,
        expired_at=deal.expired_at, expired_kind=deal.expired_kind,
        approximate=approximate(deal.expired_at, backfilled_before),
        approved_at=deal.reviewed_at if approved else None,
        approver=("none" if not approved else
                  "rules" if deal.review_note == auto_review.NOTE else "human"),
        source=obs.source, confidence=deal.confidence, lead_days=lead_days(obs),
        found_age_h=None if obs.found_at is None else _hours(obs.found_at, deal.detected_at),
        route_kind=route_kind, breadth=breadth(obs, seen, deal.detected_at))


def band(value: float, bands: tuple[tuple[float | None, str], ...]) -> str:
    return next(label for upper, label in bands if upper is None or value < upper)


@dataclass(frozen=True)
class Slice:
    """A way to group the deals; `order` lists its groups first (empty ones too), in order."""
    name: str
    key: Callable[[Outcome], str]
    order: tuple[str, ...] = ()


def _labels(bands: tuple[tuple[float | None, str], ...]) -> tuple[str, ...]:
    return tuple(label for _, label in bands)


ALL = Slice("all", lambda o: "All")
SLICES = (
    Slice("source", lambda o: o.source),
    Slice("confidence", lambda o: o.confidence or UNKNOWN, ("high", "medium", "low")),
    Slice("approved by", lambda o: o.approver, APPROVERS),
    Slice("lead time (days)", lambda o: band(o.lead_days, LEAD_DAYS), _labels(LEAD_DAYS)),
    Slice("found age (h)",
          lambda o: UNKNOWN if o.found_age_h is None else band(o.found_age_h, FOUND_AGE_H),
          _labels(FOUND_AGE_H) + (UNKNOWN,)),
    Slice("route kind", lambda o: o.route_kind),
    Slice("breadth (dates)", lambda o: band(o.breadth, BREADTH), _labels(BREADTH)),
)
APPROVAL_SLICES = ("approved by", "source")     # the approval clock's tables


def slice_named(name: str) -> Slice:
    return next(s for s in SLICES if s.name == name)


@dataclass(frozen=True)
class Horizon:
    hours: int
    judged: int     # gone within `hours`, or watched at least that long
    gone: int

    @property
    def share(self) -> float | None:
        return self.gone / self.judged if self.judged else None


@dataclass(frozen=True)
class Clock:
    """Survival from one start (detection, or approval for the approved deals)."""
    deals: int
    horizons: tuple[Horizon, ...]
    median_life_h: float | None     # start → expiry, or → last check while open


@dataclass(frozen=True)
class Group:
    name: str
    deals: int
    approximate: int
    detection: Clock
    approval: Clock


class _Watch(NamedTuple):
    watched: float      # hours the survival count may use
    gone: bool
    life: float         # hours to expiry, or to the last check while open


def _hours(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 3600)


def _watch(o: Outcome, start: datetime) -> _Watch:
    checked = o.last_checked_at or start
    gone = o.expired_kind == "gone" and o.expired_at is not None
    return _Watch(_hours(start, o.expired_at if gone else checked), gone,
                  _hours(start, o.expired_at or checked))


def _clock(rows: list[Outcome], start: Callable[[Outcome], datetime | None]) -> Clock:
    watches = [_watch(o, s) for o in rows if (s := start(o)) is not None]
    horizons = tuple(
        Horizon(h, judged=sum(1 for w in watches if w.watched >= h or w.gone and w.watched <= h),
                gone=sum(1 for w in watches if w.gone and w.watched <= h))
        for h in HORIZONS_H)
    life = statistics.median(w.life for w in watches) if watches else None
    return Clock(len(watches), horizons, life)


def survival(rows: Iterable[Outcome], *, by: Slice) -> list[Group]:
    """One group per value of `by` (its `order` first, then the others by name)."""
    groups: dict[str, list[Outcome]] = {name: [] for name in by.order}
    for o in rows:
        groups.setdefault(by.key(o), []).append(o)
    names = [*by.order, *sorted(set(groups) - set(by.order))]
    return [Group(n, len(groups[n]), sum(o.approximate for o in groups[n]),
                  _clock(groups[n], lambda o: o.detected_at),
                  _clock(groups[n], lambda o: o.approved_at)) for n in names]


def by_source_and_confidence(rows: Iterable[Outcome],
                             hours: int) -> dict[tuple[str, str | None], Horizon]:
    """The detection clock's `hours` mark per (source, confidence): how often promotions like a
    queue item were gone (the review pages' line, #79)."""
    groups: dict[tuple[str, str | None], list[Outcome]] = {}
    for o in rows:
        groups.setdefault((o.source, o.confidence), []).append(o)
    mark = HORIZONS_H.index(hours)
    return {k: _clock(g, lambda o: o.detected_at).horizons[mark] for k, g in groups.items()}


@dataclass(frozen=True)
class Published:
    """What a live promotion page tells visitors (#79, Miguel 2026-11-05): of the last
    `approved_n` promotions judged `hours` after their approval, `still_valid_pct` were still
    bookable then. A rate, a count and hours: never a price."""
    approved_n: int
    still_valid_pct: int
    hours: int


def published(rows: Iterable[Outcome], *, hours: int = PUBLISHED_HOURS,
              min_n: int) -> Published | None:
    """The approval clock's `hours` mark over every approved deal, censored like the report
    (open or superseded deals survive until their last check); None below `min_n` judged."""
    mark = _clock(list(rows), lambda o: o.approved_at).horizons[HORIZONS_H.index(hours)]
    if mark.judged < min_n or mark.share is None:
        return None
    return Published(mark.judged, round(100 * (1 - mark.share)), hours)


@dataclass(frozen=True)
class Report:
    since: datetime
    now: datetime
    open: int
    all: Group
    slices: tuple[tuple[Slice, tuple[Group, ...]], ...]


def report(rows: Iterable[Outcome], *, since: datetime, now: datetime) -> Report:
    """The deals detected from `since` to `now`, overall and by every slice."""
    rows = [o for o in rows if since <= o.detected_at <= now]
    [everyone] = survival(rows, by=ALL)
    return Report(since, now, sum(1 for o in rows if o.expired_at is None), everyone,
                  tuple((s, tuple(survival(rows, by=s))) for s in SLICES))


def _cell(x: Horizon) -> str:
    return "—" if x.share is None else f"{x.share:.0%} of {x.judged}"


def _row(name: str, clock: Clock) -> str:
    life = "—" if clock.median_life_h is None else f"{clock.median_life_h:.1f}"
    return f"| {name} | {clock.deals} | {' | '.join(_cell(x) for x in clock.horizons)} | {life} |"


def _table(title: str, rows: list[str]) -> list[str]:
    head = " | ".join(f"Gone ≤ {h} h" for h in HORIZONS_H)
    return [f"| {title} | Deals | {head} | Median life (h) |",
            "|" + "---|" * (3 + len(HORIZONS_H)), *rows]


def _slice_table(s: Slice, groups: tuple[Group, ...], clock: str) -> list[str]:
    """A slice's groups on one clock ("detection", or "approval": groups with approved deals
    only); the cache source's row carries its caveat."""
    shown = [(g.name, getattr(g, clock)) for g in groups]
    shown = [(n, c) for n, c in shown if clock == "detection" or c.deals]
    cached = s.name == "source" and any(n == CACHE_SOURCE for n, _ in shown)
    lines = _table(s.name.capitalize(), [_row(f"{n} ¹" if cached and n == CACHE_SOURCE else n, c)
                                         for n, c in shown])
    return lines + (["", f"¹ {CACHE_CAVEAT}"] if cached else [])


def markdown(r: Report) -> str:
    """The report as Markdown tables, like the backtest's (`backtest.markdown`)."""
    a = r.all
    bands = "; ".join(f"{name} {', '.join(_labels(b))}" for name, b in (
        ("lead time (found → departure, days)", LEAD_DAYS),
        ("found age (exact found time → detection, h)", FOUND_AGE_H),
        ("breadth (dates)", BREADTH)))
    lines = [
        f"Deals detected {r.since:%Y-%m-%d %H:%M} – {r.now:%Y-%m-%d %H:%M} UTC: {a.deals}, "
        f"{r.open} still open. {a.approximate} of {a.deals} expiry times are approximate "
        "(backfilled at schema v19 from the deal's last check).", "",
        "\"Gone ≤ x h\": of the deals judged at x h, the share the recheck found gone (the price "
        "rose beyond the tolerance, the trip vanished, the price went stale) within x h; judged "
        "= gone by then, or watched at least x h. Open deals and superseded or rules expiries "
        "count as surviving until their last check, never as gone. \"Median life\": detection "
        "(or approval) to expiry, or to the last check while open.", "",
        f"Bands: {bands}. Breadth: distinct departure dates on the deal's route, departure month "
        f"and source at most {BREADTH_MARGIN:.0%} above its price, seen in the "
        f"{BREADTH_WINDOW.total_seconds() / 3600:g} h before detection, its own date included.",
        "", "## From detection", "", *_table("Group", [_row("All", a.detection)])]
    for s, groups in r.slices:
        lines += ["", f"### By {s.name}", "", *_slice_table(s, groups, "detection")]
    lines += ["", "## From approval (approved deals only)", "",
              *_table("Group", [_row("All approved", a.approval)])]
    for s, groups in r.slices:
        if s.name in APPROVAL_SLICES:
            lines += ["", f"### By {s.name}", "", *_slice_table(s, groups, "approval")]
    return "\n".join(lines) + "\n"


def _clock_json(c: Clock) -> dict:
    return {"deals": c.deals, "median_life_h": c.median_life_h,
            "horizons": [{"hours": x.hours, "judged": x.judged, "gone": x.gone, "share": x.share}
                         for x in c.horizons]}


def _group_json(g: Group) -> dict:
    return {"name": g.name, "deals": g.deals, "approximate": g.approximate,
            "detection": _clock_json(g.detection), "approval": _clock_json(g.approval)}


def to_json(r: Report) -> dict:
    return {"since": r.since.isoformat(), "now": r.now.isoformat(), "open": r.open,
            "horizons_h": list(HORIZONS_H),
            "bands": {"lead_days": _labels(LEAD_DAYS), "found_age_h": _labels(FOUND_AGE_H),
                      "breadth": _labels(BREADTH)},
            "breadth": {"margin": BREADTH_MARGIN,
                        "window_h": BREADTH_WINDOW.total_seconds() / 3600},
            "all": _group_json(r.all),
            "slices": {s.name: [_group_json(g) for g in groups] for s, groups in r.slices}}
