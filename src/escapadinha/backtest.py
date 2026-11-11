"""Backtest of the detector over the stored history (D44, #47). Read-only.

Replays the detector run by run on a copy of the database, with one `DetectorConfig` per rule
set, and reports per set what each would have done: promotion candidates (per day, per route
kind), low prices, how many candidates the price recheck would have expired within 24 h (a
proxy for "not really bookable"), how many were new lows and how much the typical low behind
them was trusted. `detector.py` and `recheck.py` stay the judges: this module only feeds them
what the database held at each run, so thresholds are measured choices as the history grows
(`scripts/backtest_detector.py`, report `docs/research/2026-10-18-detector-backtest.md`).

Approximation (the data-reliability research's, D40): offers are stored once (D18), so "the
offers present at run r" are the rows with `run_id <= r <= last_run_id`, and the history known
at run r the rows first seen at or before r. A fare that left the cache and came back counts as
present in between; the run archives (archive.py) would settle that, at a cost the replay does
not need yet.

The database is never written: the file is opened read-only, copied into memory and migrated
there, so the real file keeps its schema version.
"""

from __future__ import annotations

import sqlite3
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path

from escapadinha import auto_review, detector, i18n_pt, outcomes, routes
from escapadinha.collector import ryanair, travelpayouts
from escapadinha.config import DetectorConfig, ProbeExpiryConfig, RoutesConfig
from escapadinha.probe import google_flights as gf_engine
from escapadinha.probe import kayak as kayak_engine
from escapadinha.models import Observation, Route, RouteRules
from escapadinha.recheck import (cheapest_per_search, contradicting, found_moment, newest_search,
                                 recheck, rises_above)
from escapadinha.storage import db

EXPIRY_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class RuleSet:
    name: str
    cfg: DetectorConfig
    note: str = ""
    rules: dict[str, RouteRules] | None = None   # route key -> its rules under this set (D52)

    def for_route(self, route: Route) -> Route:
        """`route` with the rules this set gives it (its own when the set names none)."""
        if self.rules and route.key in self.rules:
            return replace(route, rules=self.rules[route.key])
        return route


@dataclass(frozen=True)
class Run:
    id: int
    at: datetime            # when it started (UTC): the detector's `now` for that run

    @property
    def day(self) -> date:
        return self.at.astimezone(i18n_pt.LISBON).date()


@dataclass(frozen=True)
class Candidate:
    """One promotion candidate a rule set would have made, and what happened to it."""

    rule_set: str
    run_id: int
    at: datetime
    route: str
    kind: str
    observation_id: int | None
    price: float
    departure_date: date
    return_date: date
    rule: str                        # median | price_cap
    discount: float | None
    typical_low: float | None
    days: int                        # daily lows behind the typical low
    span_days: int
    cv: float | None
    confidence: str
    new_low: bool | None
    expired_within_24h: bool | None  # None: no later run within 24 h to judge it
    expiry: str | None               # the recheck's reason, with the run that expired it
    # Hindsight: against the route-month's typical low from everything stored by the latest
    # run, without the candidate's own found day (the data-reliability research's check).
    typical_low_today: float | None = None
    discount_today: float | None = None
    holds_today: bool | None = None  # still `threshold` and `min_saving_eur` below it

    @property
    def nights(self) -> int:
        return (self.return_date - self.departure_date).days


@dataclass
class Replay:
    """What one rule set would have done over the replayed runs."""

    rule_set: RuleSet
    runs: list[Run]
    candidates: list[Candidate] = field(default_factory=list)
    low_prices_per_run: list[int] = field(default_factory=list)
    low_price_ids: dict[str, set[int]] = field(default_factory=lambda: defaultdict(set))  # kind ->

    @property
    def days(self) -> int:
        return len({r.day for r in self.runs})

    def summary(self, kind: str | None = None) -> dict:
        cands = [c for c in self.candidates if kind is None or c.kind == kind]
        judged = [c for c in cands if c.expired_within_24h is not None]
        lows = (set().union(*self.low_price_ids.values()) if kind is None
                else self.low_price_ids.get(kind, set()))
        return {
            "rule_set": self.rule_set.name, "kind": kind, "runs": len(self.runs), "days": self.days,
            "candidates": len(cands),
            "candidates_per_day": len(cands) / self.days if self.days else 0.0,
            "routes": len({c.route for c in cands}),
            "expired_24h": sum(1 for c in judged if c.expired_within_24h), "judged": len(judged),
            "new_lows": sum(1 for c in cands if c.new_low),
            "new_low_known": sum(1 for c in cands if c.new_low is not None),
            "holds_today": sum(1 for c in cands if c.holds_today),
            "hindsight_known": sum(1 for c in cands if c.holds_today is not None),
            "confidence": dict(Counter(c.confidence for c in cands)),
            "low_prices_per_run": (statistics.fmean(self.low_prices_per_run)
                                   if kind is None and self.low_prices_per_run else None),
            "distinct_low_prices": len(lows),
            "nights_median": statistics.median(c.nights for c in cands) if cands else None,
            "nights_max": max((c.nights for c in cands), default=None),
        }


# --- the database copy -------------------------------------------------------------------

def open_copy(path: Path) -> sqlite3.Connection:
    """The database read-only, copied into memory and migrated there (the file is untouched)."""
    source = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    source.backup(conn)
    source.close()
    db.init(conn)
    return conn


def completed_runs(conn: sqlite3.Connection) -> list[Run]:
    """Every completed collection run, oldest first (live checks and enrichment are not runs)."""
    rows = conn.execute("""SELECT id, started_at FROM fetch_runs
                           WHERE scope = 'full' AND status IN ('ok', 'partial') ORDER BY id""")
    return [Run(r["id"], datetime.fromisoformat(r["started_at"])) for r in rows]


def select_runs(runs: list[Run], *, ids: tuple[int, int] | None = None,
                days: int | None = None) -> list[Run]:
    """The runs to replay: those with ids in `ids` (inclusive), else those on the `days` Lisbon
    days before the latest run's day (D-days ... D-1: the latest day is never complete)."""
    if ids is not None:
        first, last = ids
        return [r for r in runs if first <= r.id <= last]
    if not runs:
        return []
    today = runs[-1].day
    since = today - timedelta(days=days or 14)
    return [r for r in runs if since <= r.day < today]


def observations_by_route(conn: sqlite3.Connection) -> dict[str, list[Observation]]:
    rows = conn.execute("SELECT * FROM price_observations ORDER BY id")
    by_route: dict[str, list[Observation]] = defaultdict(list)
    for row in rows:
        o = db._row_to_observation(row)
        by_route[o.route_key].append(o)
    return by_route


# --- the replay ---------------------------------------------------------------------------

def present_at(rows: list[Observation], run: Run) -> list[Observation]:
    """The offers the run returned (approximation: first seen at or before it, last seen at or
    after it)."""
    return [o for o in rows if o.run_id <= run.id <= o.last_run_id]


def known_at(rows: list[Observation], run: Run) -> list[Observation]:
    """The history stored when the run ran: every offer first seen at or before it."""
    return [o for o in rows if o.run_id <= run.id]


def expiry_within(o: Observation, rows: list[Observation], route: Route, cfg: DetectorConfig,
                  run: Run, all_runs: list[Run],
                  typical_low: float | None = None) -> tuple[bool | None, str | None]:
    """Whether the price recheck (`recheck.recheck`, the pipeline's own) would have expired the
    candidate at a run within `EXPIRY_WINDOW` after `run`, and why. None when no run followed
    inside the window."""
    later = [x for x in all_runs if run.at < x.at <= run.at + EXPIRY_WINDOW]
    if not later:
        return None, None
    for x in later:
        result = recheck(o, present_at(rows, x), cfg, x.at, rules=route.rules,
                         typical_low=typical_low)
        if not result.valid:
            return True, f"run {x.id}: {result.reason}"
    return False, None


def hindsight(o: Observation, rows: list[Observation], route: Route, cfg: DetectorConfig,
              now: datetime) -> tuple[float | None, float | None, bool | None]:
    """The candidate against its route-month's typical low from everything stored by `now`,
    its own found day left out: (typical low, discount, still a promotion by `cfg`'s percentage
    and euro floor). The research's "holds against today's median"; maturity is not asked
    again, the question is whether the price was really that far below."""
    others = [r for r in rows if detector.day_key(r) != detector.day_key(o)]
    base = detector.month_baselines(others, cfg, now, route.rules).get(detector.month_key(o))
    if base is None or base.median is None:
        return None, None, None
    discount = 1 - o.price / base.median
    holds = (o.price <= base.median * (1 - cfg.threshold) + detector.EPS
             and base.median - o.price >= cfg.min_saving_eur - detector.EPS)
    return base.median, discount, holds


@dataclass
class _State:
    """What the pipeline would remember between runs under one rule set."""

    taken: set[int] = field(default_factory=set)                      # observation ids of deals
    flagged: dict[str, list[tuple[Observation, datetime]]] = field(default_factory=lambda: defaultdict(list))


def replay(conn: sqlite3.Connection, routes: list[Route], rule_sets: list[RuleSet],
           runs: list[Run], *, all_runs: list[Run] | None = None) -> list[Replay]:
    """Run every rule set over `runs` (oldest first) and judge each candidate's next 24 h
    against `all_runs` (default: every completed run)."""
    all_runs = completed_runs(conn) if all_runs is None else all_runs
    today = max(all_runs, key=lambda r: r.id).at
    by_route = observations_by_route(conn)
    replays = {rs.name: Replay(rs, list(runs)) for rs in rule_sets}
    states = {rs.name: _State() for rs in rule_sets}
    for run in sorted(runs, key=lambda r: r.id):
        lows_this_run = Counter()
        for base_route in routes:
            rows = by_route.get(base_route.key, [])
            offers = present_at(rows, run)
            if not offers:
                continue
            history = known_at(rows, run)
            for rs in rule_sets:
                state, out = states[rs.name], replays[rs.name]
                route = rs.for_route(base_route)
                dedupe_start = run.at - timedelta(days=rs.cfg.dedupe_days)
                recent = [o for o, at in state.flagged[route.key] if at >= dedupe_start]
                found = detector.detect(offers, history, recent, rs.cfg, route.price_cap_eur,
                                        run.at, rs.cfg.max_deals_per_route, route.rules,
                                        taken=state.taken)
                lows_this_run[rs.name] += len(found.low_prices)
                out.low_price_ids[route.kind] |= {lp.observation.id for lp in found.low_prices
                                                   if lp.observation.id is not None}
                for flag in found.candidates:
                    o, base = flag.observation, flag.baseline
                    if o.id is not None:
                        state.taken.add(o.id)
                    state.flagged[route.key].append((o, run.at))
                    expired, why = expiry_within(o, rows, route, rs.cfg, run, all_runs,
                                                 typical_low=base.median)
                    out.candidates.append(Candidate(
                        rs.name, run.id, run.at, route.key, route.kind, o.id, o.price,
                        o.departure_date, o.return_date, flag.decision.rule or "median",
                        flag.decision.discount_pct, base.median, base.sample_size,
                        base.span_days, base.cv, detector.confidence(base, rs.cfg),
                        flag.decision.new_low, expired, why,
                        *hindsight(o, rows, route, rs.cfg, today)))
        for rs in rule_sets:
            replays[rs.name].low_prices_per_run.append(lows_this_run[rs.name])
    return [replays[rs.name] for rs in rule_sets]


# --- rule sets ----------------------------------------------------------------------------

def _variant(base: DetectorConfig, name: str, note: str = "", **over) -> RuleSet:
    return RuleSet(name, base.model_copy(update=over), note)


# The rules before D40: 4 daily lows for both tiers, every day counts, nothing else.
BEFORE_D40 = dict(min_dates_per_day=1, min_baseline_days=4, min_baseline_days_promo=4,
                  min_baseline_span_days=0, require_new_low=False, baseline_min_lead_days=0,
                  low_confidence="medium")
# D40 as shipped (#42): two dates a day, 7 / 10 spanning 9, none of D44's rules.
D40 = dict(require_new_low=False, baseline_min_lead_days=0, low_confidence="medium")


def rule_sets(base: DetectorConfig, preset: str, *, routes_cfg: RoutesConfig | None = None,
              watched: list[Route] | None = None) -> list[RuleSet]:
    """The rule sets a preset compares. `data-reliability` reproduces the replay table of
    `docs/research/2026-10-15-data-reliability.md` §3 (runs 19–57); `d44` compares the shipped
    D40 gate with each of D44's rules and with `base` (the configured detector); `stays` (D52)
    keeps the detector and compares the kinds' nights ranges alone with the ranges
    `routes_cfg`'s overrides give the `watched` routes; `churn` (D53) compares the recheck
    tolerance and the re-flag margin with none."""
    v = lambda name, note="", **over: _variant(base, name, note, **over)   # noqa: E731
    if preset == "churn":
        return [v("no tolerance, no margin", "every rise expires, any cheaper price re-flags (before D53)",
                  recheck_tolerance_pct=0.0, reflag_margin_pct=0.0, reflag_margin_eur=0.0),
                v("tolerance only", f"rises up to {base.recheck_tolerance_pct:.0%} hold",
                  reflag_margin_pct=0.0, reflag_margin_eur=0.0),
                RuleSet("D53 (configured)", base,
                        f"tolerance {base.recheck_tolerance_pct:.0%}, re-flag margin "
                        f"{base.reflag_margin_pct:.0%} and {base.reflag_margin_eur:g} €")]
    if preset == "stays":
        if routes_cfg is None or watched is None:
            raise ValueError("the 'stays' preset needs the routes config and the routes")
        kinds = {r.key: RouteRules(**routes_cfg.kinds[r.kind].model_dump()) for r in watched}
        stays = {r.key: routes.resolve_rules(routes_cfg, r.kind, r.origin, r.destination)
                 for r in watched}
        changed = sum(1 for k in kinds if kinds[k] != stays[k])
        return [RuleSet("kinds only", base, "the kind's nights range on every route", kinds),
                RuleSet("destination stays (D52)", base,
                        f"config overrides: {changed} of {len(watched)} routes differ", stays)]
    if preset == "data-reliability":
        return [
            v("before (D3/D24)", "4 days, every day counts", **BEFORE_D40),
            v("min 7 days", "every day counts", **{**BEFORE_D40, "min_baseline_days": 7,
                                                  "min_baseline_days_promo": 7}),
            v("min 5 days, span >= 4", **{**BEFORE_D40, "min_baseline_days": 5,
                                          "min_baseline_days_promo": 5, "min_baseline_span_days": 4}),
            v("threshold 0.35", **{**BEFORE_D40, "threshold": 0.35}),
            v("below every baseline day", "new low, no margin",
              **{**BEFORE_D40, "require_new_low": True, "new_low_margin": 0.0}),
        ]
    if preset == "d44":
        return [
            v("before (D3/D24)", "4 days, every day counts", **BEFORE_D40),
            # D44's rules on the permissive gate: the only place with candidates to measure
            # them on while no route-month is mature for promotions.
            v("before + new low", f"<= {1 - base.new_low_margin:.2f} x cheapest seen",
              **{**BEFORE_D40, "require_new_low": True}),
            v("before + lead time", f"baseline from offers >= {base.baseline_min_lead_days} days ahead",
              **{**BEFORE_D40, "baseline_min_lead_days": base.baseline_min_lead_days}),
            v("before + new low + lead time",
              **{**BEFORE_D40, "require_new_low": True,
                 "baseline_min_lead_days": base.baseline_min_lead_days}),
            v("D40", "2 dates/day, 7 / 10 spanning 9", **D40),
            v("D40 + new low", f"<= {1 - base.new_low_margin:.2f} x cheapest seen",
              **{**D40, "require_new_low": True}),
            v("D40 + lead time", f"baseline from offers >= {base.baseline_min_lead_days} days ahead",
              **{**D40, "baseline_min_lead_days": base.baseline_min_lead_days}),
            v("D40 + threshold 0.35", **{**D40, "threshold": 0.35}),
            RuleSet("D44 (configured)", base, "new low + lead time, as config.yaml"),
            v("D44, high confidence for low prices", "low prices need >= 14 days and CV <= 0.25",
              low_confidence="high"),
        ]
    raise ValueError(f"unknown preset {preset!r}")


PRESETS = ("data-reliability", "d44", "stays", "churn")
PROBE_PRESET = "probe"     # not a rule set: `probe_report` (the probe against cache deals)


# --- the report ---------------------------------------------------------------------------

def _nights(s: dict) -> str:
    if s["nights_median"] is None:
        return "–"
    return f"{s['nights_median']:g}, {s['nights_max']}"


def _pct(part: int, whole: int) -> str:
    return "–" if not whole else f"{part}/{whole} ({part / whole:.0%})"


def markdown(replays: list[Replay], *, candidates: bool = False) -> str:
    """The comparison as Markdown: one row per rule set, then per route kind, then (with
    `candidates`) every candidate with its outcome."""
    if not replays:
        return "No runs to replay.\n"
    first = replays[0]
    lines = [f"Runs {first.runs[0].id}–{first.runs[-1].id} ({len(first.runs)} runs, "
             f"{first.days} days, {first.runs[0].day:%d/%m}–{first.runs[-1].day:%d/%m}). "
             f"\"Expired <= 24 h\": the price recheck at the runs that followed within 24 h expired "
             f"the candidate (one with no later run inside 24 h is not judged). \"Holds today\": "
             f"still `threshold` and `min_saving_eur` below the route-month's typical low from "
             f"everything stored by the latest run, the candidate's own found day left out.", "",
             "| Rule set | Candidates (routes) | Per day | Expired <= 24 h | Holds today | "
             "New lows | Confidence | Low prices / run | Distinct low prices | Nights (median, max) |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for rp in replays:
        s = rp.summary()
        conf = ", ".join(f"{k} {n}" for k, n in sorted(s["confidence"].items())) or "–"
        note = f" ({rp.rule_set.note})" if rp.rule_set.note else ""
        lines.append(f"| {rp.rule_set.name}{note} | {s['candidates']} ({s['routes']}) | "
                     f"{s['candidates_per_day']:.2f} | {_pct(s['expired_24h'], s['judged'])} | "
                     f"{_pct(s['holds_today'], s['hindsight_known'])} | "
                     f"{_pct(s['new_lows'], s['new_low_known'])} | {conf} | "
                     f"{s['low_prices_per_run']:.1f} | {s['distinct_low_prices']} | "
                     f"{_nights(s)} |")
    kinds = sorted({c.kind for rp in replays for c in rp.candidates}
                   | {k for rp in replays for k in rp.low_price_ids})
    if kinds:
        lines += ["", "| Rule set | Kind | Candidates | Expired <= 24 h | Holds today | New lows | "
                  "Distinct low prices |", "|---|---|---|---|---|---|---|"]
        for rp in replays:
            for kind in kinds:
                s = rp.summary(kind)
                if not s["candidates"] and not s["distinct_low_prices"]:
                    continue
                lines.append(f"| {rp.rule_set.name} | {kind} | {s['candidates']} | "
                             f"{_pct(s['expired_24h'], s['judged'])} | "
                             f"{_pct(s['holds_today'], s['hindsight_known'])} | "
                             f"{_pct(s['new_lows'], s['new_low_known'])} | {s['distinct_low_prices']} |")
    if candidates:
        for rp in replays:
            if not rp.candidates:
                continue
            lines += ["", f"### {rp.rule_set.name}", "",
                      "| Run | Route | Trip | Price | Typical low (days, CV) | Discount | "
                      "Confidence | New low | Within 24 h | Today |",
                      "|---|---|---|---|---|---|---|---|---|---|"]
            for c in rp.candidates:
                typical = ("–" if c.typical_low is None else
                           f"{c.typical_low:g} € ({c.days} d" + (f", CV {c.cv:.2f})" if c.cv is not None else ")"))
                discount = "–" if c.discount is None else f"{c.discount:.0%}"
                fate = {True: f"expired: {c.expiry}", False: "held", None: "not judged"}[c.expired_within_24h]
                new_low = {True: "yes", False: "no", None: "–"}[c.new_low]
                today = ("–" if c.typical_low_today is None else
                         f"{c.typical_low_today:g} €, {c.discount_today:.0%}"
                         f"{' ✓' if c.holds_today else ' ✗'}")
                lines.append(f"| {c.run_id} ({c.at:%d/%m %H:%M}) | {c.route} | "
                             f"{c.departure_date:%d/%m}–{c.return_date:%d/%m} | {c.price:g} € | "
                             f"{typical} | {discount} | {c.confidence} | {new_low} | {fate} | {today} |")
    return "\n".join(lines) + "\n"


# --- where the data stands ----------------------------------------------------------------

def state(conn: sqlite3.Connection, routes: list[Route], cfg: DetectorConfig,
          now: datetime | None = None) -> dict:
    """Every route-month's typical low at `now` (default: the latest run) under `cfg`, and
    under `cfg` without the lead-time filter, so the report can say what the filter costs and
    changes: counted days, maturity for low prices and promotions, CV and confidence, and the
    shift the filter makes to the median."""
    runs = completed_runs(conn)
    now = now or runs[-1].at
    by_route = observations_by_route(conn)
    mixed = cfg.model_copy(update={"baseline_min_lead_days": 0})
    months = []
    for route in routes:
        rows = by_route.get(route.key)
        if not rows:
            continue
        with_lead = detector.month_baselines(rows, cfg, now, route.rules)
        without = detector.month_baselines(rows, mixed, now, route.rules)
        for month, base in with_lead.items():
            plain = without[month]
            months.append({
                "route": route.key, "kind": route.kind, "month": f"{month[0]}-{month[1]:02d}",
                "days": base.sample_size, "span_days": base.span_days, "median": base.median,
                "cv": base.cv, "median_lead_days": base.median_lead_days,
                "confidence": detector.confidence(base, cfg),
                "mature": detector.is_mature(base, cfg),
                "mature_promo": detector.is_mature_for_promotions(base, cfg),
                "days_without_lead_filter": plain.sample_size, "median_without_lead_filter": plain.median,
                "mature_without_lead_filter": detector.is_mature(plain, cfg),
                "mature_promo_without_lead_filter": detector.is_mature_for_promotions(plain, cfg),
            })
    return {"at": now.isoformat(), "route_months": months}


def state_markdown(data: dict, cfg: DetectorConfig) -> str:
    months = data["route_months"]
    with_rows = [m for m in months if m["days_without_lead_filter"] or m["days"]]
    lines = [f"Route-months at {data['at'][:16]} UTC: {len(months)} with usable offers.", "",
             "| | Counted days (no lead filter) | Counted days (lead >= "
             f"{cfg.baseline_min_lead_days} d) |", "|---|---|---|"]
    for label, test in [(">= 1 day", lambda d: d >= 1), (">= 4 days", lambda d: d >= 4),
                        (f">= {cfg.min_baseline_days} days (low prices)", lambda d: d >= cfg.min_baseline_days),
                        (f">= {cfg.min_baseline_days_promo} days", lambda d: d >= cfg.min_baseline_days_promo),
                        (f">= {cfg.confidence.high_days} days", lambda d: d >= cfg.confidence.high_days)]:
        lines.append(f"| {label} | {sum(1 for m in with_rows if test(m['days_without_lead_filter']))} | "
                     f"{sum(1 for m in with_rows if test(m['days']))} |")
    lines.append(f"| mature for promotions | {sum(m['mature_promo_without_lead_filter'] for m in with_rows)} | "
                 f"{sum(m['mature_promo'] for m in with_rows)} |")
    mature = [m for m in with_rows if m["mature"]]
    if mature:
        cvs = sorted(m["cv"] for m in mature if m["cv"] is not None)
        q = lambda p: cvs[min(len(cvs) - 1, int(p * len(cvs)))]   # noqa: E731
        lines += ["", f"Mature route-months (>= {cfg.min_baseline_days} counted days, lead filter on): "
                  f"{len(mature)}; CV of their daily lows: median {statistics.median(cvs):.2f}, "
                  f"p10 {q(0.1):.2f}, p90 {q(0.9):.2f}; {sum(1 for c in cvs if c <= cfg.confidence.high_max_cv)} "
                  f"of {len(cvs)} at or under {cfg.confidence.high_max_cv}; confidence: "
                  + ", ".join(f"{k} {n}" for k, n in sorted(Counter(m['confidence'] for m in mature).items())) + ".",
                  "", "| Route | Month | Days (without filter) | Typical low (without filter) | CV | "
                  "Median lead (days) | Confidence |", "|---|---|---|---|---|---|---|"]
        for m in sorted(mature, key=lambda m: (-m["days"], m["route"], m["month"])):
            shift = (f"{m['median']:g} € ({m['median_without_lead_filter']:g} €)"
                     if m["median_without_lead_filter"] != m["median"] else f"{m['median']:g} €")
            lines.append(f"| {m['route']} | {m['month']} | {m['days']} ({m['days_without_lead_filter']}) | "
                         f"{shift} | {m['cv']:.2f} | {m['median_lead_days']} | {m['confidence']} |")
    shifted = [m for m in with_rows if m["median"] is not None and m["median_without_lead_filter"] is not None
               and m["median"] != m["median_without_lead_filter"]]
    lost = [m for m in with_rows if m["mature_without_lead_filter"] and not m["mature"]]
    lines += ["", f"The lead-time filter changes the typical low of {len(shifted)} route-months "
              f"(median shift {statistics.median(m['median'] / m['median_without_lead_filter'] - 1 for m in shifted):+.1%}"
              if shifted else "The lead-time filter changes no typical low",
              f"and takes {len(lost)} route-months below the low-price maturity"
              + (": " + ", ".join(f"{m['route']} {m['month']}" for m in lost) if lost else "") + "."]
    return "\n".join(lines) + "\n"


def to_json(replays: list[Replay]) -> dict:
    """The same figures as data: per rule set, the summary, the per-kind summaries and the
    candidates."""
    def plain(c: Candidate) -> dict:
        return {**c.__dict__, "at": c.at.isoformat(), "departure_date": c.departure_date.isoformat(),
                "return_date": c.return_date.isoformat()}
    kinds = sorted({c.kind for rp in replays for c in rp.candidates})
    return {
        "runs": [{"id": r.id, "at": r.at.isoformat()} for r in replays[0].runs] if replays else [],
        "rule_sets": [{
            "name": rp.rule_set.name, "note": rp.rule_set.note,
            "config": rp.rule_set.cfg.model_dump(),
            "summary": rp.summary(),
            "by_kind": {k: rp.summary(k) for k in kinds},
            "candidates": [plain(c) for c in rp.candidates],
        } for rp in replays],
    }


# --- the probe against the cache's deals (2026-11-11) -----------------------------------
#
# Question: should a deal whose own source is the Travelpayouts cache expire when a probe
# engine (D48, D49: comparison sources) saw the same trip recently at a clearly higher price?
# The cache can keep a stale price for days, and the recheck only asks the cache (D47). The
# measure: every cache deal, every probe reading of its trip (`also_seen`'s match: route and
# dates, `db.trip_observations_by_source`'s WHERE), a ground truth at each moment from the best
# signal the data has, and a grid of candidate rules replayed over the deals' lives.
# Report: docs/research/2026-11-11-probe-expiry.md; `scripts/backtest_detector.py --preset probe`.

PROBE_ENGINES = (gf_engine.SOURCE, kayak_engine.SOURCE)    # every comparison source, in search order
TRUTH_WINDOW = timedelta(hours=24)       # a later fact this close to a moment judges it
AIRLINE_SLACK = timedelta(hours=3)       # an airline price this close to a moment, if none covers it
PAIR_WINDOW = timedelta(hours=1)         # a Google Flights and a Kayak search of the same trip


@dataclass(frozen=True)
class Seen:
    """One stored row of the deal's trip at another source: the price it showed from `first` to
    `last` (first and last sighting; a probe row is one search, or two on the same Lisbon day at
    the same price), and when the pipeline had each sighting (`*_usable`: the import's run for
    the probe; the collection's for the others)."""

    source: str
    price: float
    first: datetime
    last: datetime
    first_usable: datetime
    last_usable: datetime
    observation_id: int
    seller: str | None = None
    airline: str | None = None
    airport: str | None = None
    nonstop: bool | None = None
    with_baggage: bool | None = None
    found: datetime | None = None    # when a traveller found it: exact, else the found day's start

    def sightings(self) -> list[tuple[datetime, datetime]]:
        """(seen at, usable at) for the first sighting and, when later, the last."""
        out = [(self.first, self.first_usable)]
        if self.last > self.first:
            out.append((self.last, self.last_usable))
        return out


@dataclass(frozen=True)
class ProbeSearch:
    """One engine's search of the trip: its cheapest option (the probe reads the cheapest
    nonstop itinerary, then its booking options)."""

    engine: str
    at: datetime                 # the probe's search time
    usable_at: datetime          # the import's run: the first recheck that could use it
    price: float
    observation_id: int
    seller: str | None
    airline: str | None
    airport: str | None


@dataclass(frozen=True)
class CacheDeal:
    """A deal from the cache source and everything else stored about its trip."""

    deal_id: int
    route: str
    airport: str | None
    departure_date: date
    return_date: date
    price: float
    airline: str | None
    seller: str | None
    nonstop: bool
    with_baggage: bool | None
    source: str
    found: datetime | None
    detected_at: datetime
    approved_at: datetime | None     # the rules' or a human's approval (None: rejected or never)
    approver: str                    # rules | human | none
    status: str
    expired_at: datetime | None
    expired_kind: str | None
    last_seen_price: float | None
    approximate: bool                # the expiry time is the v19 backfill's (`outcomes.approximate`)
    end: datetime                    # the expiry, else the copy's last run
    rechecks: int                    # collection runs inside its life (each rechecks it)
    probe: tuple[Seen, ...] = ()
    airline_seen: tuple[Seen, ...] = ()
    cache_seen: tuple[Seen, ...] = ()   # the cache's other rows of the trip

    @property
    def life_hours(self) -> float:
        return (self.end - self.detected_at).total_seconds() / 3600

    @property
    def open(self) -> bool:
        return self.expired_at is None

    @property
    def rose(self) -> bool:
        """The recheck's last price was above the deal's (a price rise, not the stale timer)."""
        return self.last_seen_price is not None and self.last_seen_price > self.price + detector.EPS

    def searches(self, engine: str | None = None) -> list[ProbeSearch]:
        """Every probe search of the trip (each engine's cheapest option per search), oldest first."""
        return cheapest_per_search(
            ProbeSearch(s.source, at, usable, s.price, s.observation_id, s.seller, s.airline,
                        s.airport)
            for s in self.probe if engine is None or s.source == engine
            for at, usable in s.sightings())

    def searches_in_life(self, engine: str | None = None) -> list[ProbeSearch]:
        return [x for x in self.searches(engine) if self.detected_at <= x.at < self.end]

    @property
    def compared(self) -> bool:
        """The probe read the trip while the deal was open."""
        return bool(self.searches_in_life())


def _hours(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 3600


def gap(deal: CacheDeal, price: float) -> tuple[float, float]:
    """(€, share) by which `price` is above the deal's."""
    return price - deal.price, price / deal.price - 1


# --- ground truth ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Truth:
    """Whether the deal's price was still real at a moment, and on what evidence: `airline`
    (strong: the carrier's own price for the same flight pair, D47), `cache` (medium: the cache
    re-found the same itinerary at the deal's price, within the recheck tolerance, after the
    moment), `rose` (weak: the recheck expired the deal as gone within `TRUTH_WINDOW` after it,
    the cache's own price having risen) and `timer` (weakest: the same, by the stale-price timer:
    only that nobody re-found the price for three days)."""

    verdict: str | None              # stale | real | None (unknown)
    basis: str                       # airline | cache | rose | timer | none
    detail: str = ""

    @property
    def label(self) -> str:
        return "unknown" if self.verdict is None else f"{self.verdict} ({self.basis})"


def airline_price_at(deal: CacheDeal, t: datetime) -> Seen | None:
    """The carrier's own price for the deal's trip at `t`: the cheapest airline-source row of
    the same carrier and arrival airport whose sightings cover `t`, else the row seen nearest to
    `t` within `AIRLINE_SLACK`."""
    rows = [s for s in deal.airline_seen if s.airline == deal.airline and s.airport == deal.airport]
    covering = [s for s in rows if s.first <= t <= s.last]
    if covering:
        return min(covering, key=lambda s: (s.price, s.observation_id))
    def distance(s: Seen) -> float:
        return min(abs((s.first - t).total_seconds()), abs((s.last - t).total_seconds()))
    near = [s for s in rows if distance(s) <= AIRLINE_SLACK.total_seconds()]
    return min(near, key=lambda s: (distance(s), s.price)) if near else None


def truth_at(deal: CacheDeal, t: datetime, tolerance: float) -> Truth:
    """The best evidence on whether the deal's price was real at `t` (`Truth`); `tolerance`
    is the recheck's (D53): a price within it still counts as the deal's."""
    limit = deal.price * (1 + tolerance) + detector.EPS
    own = airline_price_at(deal, t)
    if own is not None:
        verdict = "real" if own.price <= limit else "stale"
        return Truth(verdict, "airline", f"{own.source} {own.price:g} € (obs {own.observation_id})")
    refound = [s for s in deal.cache_seen
               if s.found is not None and t < s.found <= t + TRUTH_WINDOW and s.price <= limit
               and s.airline == deal.airline and s.airport == deal.airport]
    if refound:
        s = min(refound, key=lambda s: s.found)
        return Truth("real", "cache", f"cache re-found {s.price:g} € (obs {s.observation_id})")
    # The cache's own recheck only, never `contradicted` (D65): that expiry is the probe rule
    # this backtest measures, so it can't be the evidence it is measured against.
    if deal.expired_kind == "gone" and deal.expired_at is not None and t < deal.expired_at <= t + TRUTH_WINDOW:
        return Truth("stale", "rose" if deal.rose else "timer",
                     f"gone {_hours(t, deal.expired_at):.0f} h later")
    return Truth(None, "none")


# --- the rules -------------------------------------------------------------------------------

ENGINE_MODES = ("any", "both", gf_engine.SOURCE)


@dataclass(frozen=True)
class ProbeRule:
    """Expire the deal at the first recheck where the probe's latest search (per engine, no
    older than `max_age_hours`) is `pct` and `eur` above the deal's price: on `engines` "any"
    engine, "both" engines, or Google Flights alone. `same_airport`: only searches that landed
    at the deal's own airport (stricter than `also_seen`, which matches the city).
    `newer_than_price`: only searches made after the deal's price was found (a search from
    before a price drop cannot contradict the drop)."""

    pct: float
    eur: float
    max_age_hours: float
    engines: str
    same_airport: bool = False
    newer_than_price: bool = True

    @property
    def shipped(self) -> bool:
        """The shape of the production rule (D65): every engine, the deal's airport, searches
        after the price was found."""
        return self.engines == "both" and self.same_airport and self.newer_than_price

    @classmethod
    def from_config(cls, cfg: ProbeExpiryConfig) -> ProbeRule:
        """The configured rule (D65), when it asks every probe engine (the backtest's "both")."""
        if set(cfg.engines) != set(PROBE_ENGINES):
            raise ValueError("the backtest replays the probe rule with every engine only")
        return cls(cfg.min_rise_pct, cfg.min_rise_eur, cfg.max_age_hours, "both",
                   same_airport=True, newer_than_price=True)

    @property
    def label(self) -> str:
        return (f"{self.engines}, ≥{self.pct:.0%} and ≥{self.eur:g} €, ≤{self.max_age_hours:g} h"
                + (", same airport" if self.same_airport else "")
                + ("" if self.newer_than_price else ", searches older than the price too"))


def latest_search(deal: CacheDeal, engine: str, t: datetime, max_age: timedelta, *,
                  same_airport: bool = False, since: datetime | None = None) -> ProbeSearch | None:
    """The engine's newest search the pipeline had at `t`, if no older than `max_age` (and,
    with `since`, made at or after it)."""
    usable = [x for x in deal.searches(engine) if x.usable_at <= t
              and (not same_airport or x.airport == deal.airport)]
    return newest_search(usable, engine, t, max_age, since=since)


def fires(deal: CacheDeal, rule: ProbeRule, t: datetime) -> tuple[ProbeSearch, ...]:
    """The searches that make `rule` expire the deal at `t` (empty: it does not). The shipped
    rule's shape (`ProbeRule.shipped`) is decided by the production code itself,
    `recheck.contradicting` (D65), on the searches the pipeline had at `t`."""
    age = timedelta(hours=rule.max_age_hours)
    if rule.shipped:
        usable = [x for x in deal.searches() if x.usable_at <= t]
        return contradicting(deal.price, deal.airport, deal.found, usable, engines=PROBE_ENGINES,
                             pct=rule.pct, eur=rule.eur, max_age=age, now=t) or ()
    since = deal.found if rule.newer_than_price else None
    fresh = {e: latest_search(deal, e, t, age, same_airport=rule.same_airport, since=since)
             for e in PROBE_ENGINES}
    def higher(x: ProbeSearch | None) -> bool:
        return x is not None and rises_above(deal.price, x.price, rule.pct, rule.eur)
    if rule.engines == "any":
        return tuple(x for x in fresh.values() if higher(x))
    if rule.engines == "both":
        return tuple(fresh.values()) if all(higher(x) for x in fresh.values()) else ()
    x = fresh.get(rule.engines)
    return (x,) if higher(x) else ()


def decision_times(deal: CacheDeal) -> list[datetime]:
    """When a rule's verdict can change: the first recheck after detection (taken as detection
    itself) and every probe import while the deal is open."""
    times = {deal.detected_at} | {x.usable_at for x in deal.searches()
                                   if deal.detected_at < x.usable_at < deal.end}
    return sorted(times)


@dataclass(frozen=True)
class Fire:
    deal_id: int
    at: datetime
    searches: tuple[ProbeSearch, ...]
    truth: Truth
    hours_early: float               # before the deal's real expiry, or before the copy's end
    open: bool
    approved: bool                   # approved (so on the site) when the rule fired


def first_fire(deal: CacheDeal, rule: ProbeRule, tolerance: float) -> Fire | None:
    for t in decision_times(deal):
        hit = fires(deal, rule, t)
        if hit:
            truth = truth_at(deal, max(x.at for x in hit), tolerance)
            return Fire(deal.deal_id, t, hit, truth, _hours(t, deal.end), deal.open,
                        deal.approved_at is not None and deal.approved_at <= t)
    return None


def grid_rules(pcts=(0.05, 0.10, 0.15, 0.20, 0.25), eurs=(0, 5, 10, 15), ages=(6, 12, 24, 48),
               engines=ENGINE_MODES, airports=(False, True), newer=(True,)) -> list[ProbeRule]:
    return [ProbeRule(p, e, a, m, s, n) for n in newer for s in airports for m in engines
            for a in ages for p in pcts for e in eurs]


def default_rules() -> list[ProbeRule]:
    """The report's grid: every margin, age and engine mode with both matches, then the same at
    12 and 24 h without the found-time guard (what the guard is worth)."""
    return grid_rules() + grid_rules(ages=(12, 24), airports=(False,), newer=(False,))


@dataclass
class GridRow:
    rule: ProbeRule
    fires: list[Fire]
    control_fires: list[Fire] = field(default_factory=list)   # on the airline-source deals

    def ids(self, verdict: str | None, basis: str | None = None) -> list[int]:
        return [f.deal_id for f in self.fires if f.truth.verdict == verdict
                and (basis is None or f.truth.basis == basis)]

    @property
    def median_hours_early(self) -> float | None:
        early = [f.hours_early for f in self.fires if not f.open]
        return statistics.median(early) if early else None

    def summary(self, stale_known: set[int]) -> dict:
        caught = {f.deal_id for f in self.fires} & stale_known
        return {"rule": self.rule.__dict__, "label": self.rule.label, "fired": len(self.fires),
                "fired_ids": [f.deal_id for f in self.fires],
                "fires": [{"deal_id": f.deal_id, "at": f.at.isoformat(), "hours_early": f.hours_early,
                           "open": f.open, "approved": f.approved, "truth": f.truth.label,
                           "searches": [{"engine": x.engine, "price": x.price, "at": x.at.isoformat(),
                                         "observation_id": x.observation_id} for x in f.searches]}
                          for f in self.fires],
                "approved_when_fired": sum(f.approved for f in self.fires),
                "stale_airline": self.ids("stale", "airline"), "stale_rose": self.ids("stale", "rose"),
                "stale_timer": self.ids("stale", "timer"),
                "real": self.ids("real"), "unknown": self.ids(None),
                "open": [f.deal_id for f in self.fires if f.open],
                "median_hours_early": self.median_hours_early,
                "caught_stale_known": sorted(caught), "stale_known": sorted(stale_known),
                "control_fired": [f.deal_id for f in self.control_fires],
                "control_false": [f.deal_id for f in self.control_fires
                                  if f.hours_early > CONTROL_SLACK.total_seconds() / 3600]}


# A control deal (its source rechecked at the seller every run, D47) is real while open, give
# or take the half hour between rechecks: a rule that expires one earlier than this before its
# own expiry has expired a real price.
CONTROL_SLACK = timedelta(hours=1)


def probe_grid(deals: list[CacheDeal], rules: list[ProbeRule], tolerance: float,
               controls: list[CacheDeal] = ()) -> list[GridRow]:
    """Every rule over `deals`, and over `controls`: deals from a live source, whose fires are
    false positives unless their own source expired them within `CONTROL_SLACK`."""
    rows = []
    for rule in rules:
        hits = [f for f in (first_fire(d, rule, tolerance) for d in deals) if f is not None]
        ctrl = [f for f in (first_fire(d, rule, tolerance) for d in controls) if f is not None]
        rows.append(GridRow(rule, hits, ctrl))
    return rows


def stale_known(deals: list[CacheDeal], tolerance: float) -> set[int]:
    """Deals the truth calls stale at some probe search of their life (what a rule could catch)."""
    return {d.deal_id for d in deals
            if any(truth_at(d, x.at, tolerance).verdict == "stale" for x in d.searches_in_life())}


def engine_pairs(deals: list[CacheDeal]) -> list[tuple[CacheDeal, ProbeSearch, ProbeSearch]]:
    """Each Google Flights search of a deal's life paired with the nearest Kayak search of the
    same trip within `PAIR_WINDOW`; a trip shared by several deals counts once."""
    out, seen = [], set()
    for d in deals:
        kayak = d.searches_in_life(kayak_engine.SOURCE)
        for g in d.searches_in_life(gf_engine.SOURCE):
            near = [k for k in kayak if abs(k.at - g.at) <= PAIR_WINDOW]
            key = (d.route, d.departure_date, d.return_date, g.at)
            if near and key not in seen:
                seen.add(key)
                out.append((d, g, min(near, key=lambda k: abs(k.at - g.at))))
    return out


# --- loading from the copy -------------------------------------------------------------------

def cache_deals(conn: sqlite3.Connection, *, source: str = travelpayouts.SOURCE,
                until: datetime | None = None) -> list[CacheDeal]:
    """Every deal whose observation is from `source`, with its trip's rows at every other
    source and the cache's other rows (`also_seen`'s match: route and dates). `until`: the end
    of an open deal's life (default: the copy's last collection run)."""
    runs = completed_runs(conn)
    until = until or (runs[-1].at if runs else db.utcnow())
    run_at = {r["id"]: datetime.fromisoformat(r["started_at"])
              for r in conn.execute("SELECT id, started_at FROM fetch_runs")}
    backfilled = db.expiries_backfilled_before(conn)
    rows = conn.execute(
        """SELECT d.*, o.origin, o.destination, o.destination_airport, o.departure_date,
                  o.return_date, o.price, o.airline, o.transfers, o.return_transfers, o.gate,
                  o.with_baggage, o.found_at, o.found_date, o.source
           FROM deals d JOIN price_observations o ON o.id = d.observation_id
           WHERE o.source = ? ORDER BY d.id""", (source,)).fetchall()
    out = []
    for r in rows:
        detected = datetime.fromisoformat(r["detected_at"])
        expired = db._dt(r["expired_at"])
        end = expired or until
        approved = (db._dt(r["reviewed_at"])
                    if r["reviewed_at"] and r["status"] != "rejected" else None)
        seen = [_seen(row, run_at) for row in conn.execute(
            """SELECT * FROM price_observations WHERE origin = ? AND destination = ?
               AND departure_date = ? AND return_date = ? AND id != ? ORDER BY id""",
            (r["origin"], r["destination"], r["departure_date"], r["return_date"],
             r["observation_id"]))]
        out.append(CacheDeal(
            deal_id=r["id"], route=f"{r['origin']}-{r['destination']}",
            airport=r["destination_airport"], departure_date=date.fromisoformat(r["departure_date"]),
            return_date=date.fromisoformat(r["return_date"]), price=float(r["price"]),
            airline=r["airline"], seller=r["gate"],
            nonstop=r["transfers"] == 0 and r["return_transfers"] == 0,
            with_baggage=None if r["with_baggage"] is None else bool(r["with_baggage"]),
            source=r["source"], found=_found(r), detected_at=detected, approved_at=approved,
            approver=("none" if approved is None else
                      "rules" if r["review_note"] == auto_review.NOTE else "human"),
            status=r["status"], expired_at=expired, expired_kind=r["expired_kind"],
            last_seen_price=None if r["last_seen_price"] is None else float(r["last_seen_price"]),
            approximate=outcomes.approximate(expired, backfilled), end=end,
            rechecks=sum(1 for x in runs if detected < x.at <= end),
            probe=tuple(s for s in seen if s.source in PROBE_ENGINES),
            airline_seen=tuple(s for s in seen if s.source in ryanair.AIRLINE_SOURCES),
            cache_seen=tuple(s for s in seen if s.source == source)))
    return out


def _found(row: sqlite3.Row) -> datetime | None:
    return found_moment(datetime.fromisoformat(row["found_at"]) if row["found_at"] else None,
                        date.fromisoformat(row["found_date"]) if row["found_date"] else None)


def _seen(row: sqlite3.Row, run_at: dict[int, datetime]) -> Seen:
    first, last = datetime.fromisoformat(row["fetched_at"]), datetime.fromisoformat(row["last_seen_at"])
    return Seen(source=row["source"], price=float(row["price"]), first=first, last=last,
                first_usable=max(first, run_at.get(row["run_id"], first)),
                last_usable=max(last, run_at.get(row["last_run_id"], last)),
                observation_id=row["id"], seller=row["gate"], airline=row["airline"],
                airport=row["destination_airport"],
                nonstop=row["transfers"] == 0 and row["return_transfers"] == 0,
                with_baggage=None if row["with_baggage"] is None else bool(row["with_baggage"]),
                found=_found(row))


# --- the probe report ------------------------------------------------------------------------

def _t(dt: datetime | None) -> str:
    return "–" if dt is None else f"{dt:%d/%m %H:%M}"


def _h(hours: float | None) -> str:
    return "–" if hours is None else f"{hours:.0f}"


def _shares(values: list[float]) -> str:
    return "–" if not values else f"{statistics.median(values):+.0%} ({min(values):+.0%} … {max(values):+.0%})"


def _cadence(searches: list[ProbeSearch]) -> float | None:
    """Median hours between the trip's probe visits (one visit: both engines, minutes apart)."""
    visits: list[datetime] = []
    for x in searches:
        if not visits or x.at - visits[-1] > PAIR_WINDOW:
            visits.append(x.at)
    gaps = [_hours(a, b) for a, b in zip(visits, visits[1:])]
    return statistics.median(gaps) if gaps else None


def probe_report(deals: list[CacheDeal], rules: list[ProbeRule], tolerance: float,
                 controls: list[CacheDeal] = ()) -> dict:
    """The figures behind the probe report, as data (`probe_markdown` prints them). `controls`:
    deals from an airline source (`cache_deals(conn, source="ryanair")`), the same comparison
    where the deal's own price is known to be live."""
    compared = [d for d in deals if d.compared]
    checked = [d for d in controls if d.compared]
    known = stale_known(compared, tolerance)
    grid = probe_grid(compared, rules, tolerance, checked)
    pairs = engine_pairs(compared)
    deal_rows, reading_rows = [], []
    for d in compared:
        life = d.searches_in_life()
        shares = [gap(d, x.price)[1] for x in life]
        own = [airline_price_at(d, x.at) for x in life]
        deal_rows.append({
            "deal_id": d.deal_id, "route": d.route, "airport": d.airport,
            "departure_date": d.departure_date.isoformat(), "return_date": d.return_date.isoformat(),
            "price": d.price, "airline": d.airline, "seller": d.seller, "nonstop": d.nonstop,
            "with_baggage": d.with_baggage, "source": d.source,
            "found": d.found.isoformat() if d.found else None,
            "detected_at": d.detected_at.isoformat(),
            "approved_at": d.approved_at.isoformat() if d.approved_at else None, "approver": d.approver,
            "status": d.status, "expired_at": d.expired_at.isoformat() if d.expired_at else None,
            "expired_kind": d.expired_kind, "rose": d.rose, "last_seen_price": d.last_seen_price,
            "approximate": d.approximate, "life_hours": d.life_hours, "rechecks": d.rechecks,
            "searches": {e: len(d.searches_in_life(e)) for e in PROBE_ENGINES},
            "first_search_hours": _hours(d.detected_at, life[0].at) if life else None,
            "hours_between_searches": _cadence(life),
            "first_gap": shares[0] if shares else None,
            "min_gap": min(shares) if shares else None, "max_gap": max(shares) if shares else None,
            "airline_prices": sorted({s.price for s in own if s is not None}),
            "cache_later": sorted({s.price for s in d.cache_seen if d.detected_at <= s.first < d.end
                                   + TRUTH_WINDOW and s.airport == d.airport}),
        })
        for x in d.searches():
            if not (d.detected_at - TRUTH_WINDOW <= x.at < d.end):
                continue
            euros, share = gap(d, x.price)
            truth = truth_at(d, x.at, tolerance)
            reading_rows.append({
                "deal_id": d.deal_id, "engine": x.engine, "seller": x.seller, "airline": x.airline,
                "airport": x.airport, "airline_differs": x.airline != d.airline,
                "airport_differs": x.airport != d.airport, "price": x.price, "gap_eur": euros,
                "gap_pct": share, "at": x.at.isoformat(), "usable_at": x.usable_at.isoformat(),
                "hours_after_detection": _hours(d.detected_at, x.at),
                "import_lag_hours": _hours(x.at, x.usable_at),
                "hours_before_end": _hours(x.at, d.end), "truth": truth.label,
                "truth_detail": truth.detail})
    pair_rows = [{"deal_id": d.deal_id, "at": g.at.isoformat(), "google_flights": g.price,
                  "kayak": k.price, "gf_gap": gap(d, g.price)[1], "kayak_gap": gap(d, k.price)[1],
                  "between": g.price / k.price - 1} for d, g, k in pairs]
    return {"source": deals[0].source if deals else None, "tolerance": tolerance,
            "deals": len(deals), "compared": len(compared),
            "approved_compared": sum(1 for d in compared if d.approved_at is not None),
            "stale_known": sorted(known), "deal_rows": deal_rows, "readings": reading_rows,
            "pairs": pair_rows, "control": _control(checked), "grid": [row.summary(known) for row in grid]}


def _control(deals: list[CacheDeal]) -> dict:
    """How far the probe's searches sit from deals whose price is live (each search in a
    deal's life, the deal's own carrier and airport only)."""
    shares = [gap(d, x.price)[1] for d in deals for x in d.searches_in_life()
              if x.airport == d.airport]
    return {"source": deals[0].source if deals else None, "deals": len(deals), "searches": len(shares),
            "median_gap": statistics.median(shares) if shares else None,
            "at_least_5": sum(g >= 0.05 - detector.EPS for g in shares),
            "at_least_10": sum(g >= 0.10 - detector.EPS for g in shares),
            "below": sum(g < -detector.EPS for g in shares)}


GRID_HEADER = ("| Match | Engines | Max age h | Margin | Fired | Approved then | Stale: airline | "
               "Stale: rose | Stale: timer | Real: false positives | Unknown | Open | Early h | "
               "Caught stale known | Control false |",
               "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")


def probe_markdown(data: dict, *, every_rule: bool = True) -> str:
    """The probe report as Markdown: the compared deals, every probe reading with its gap and
    the truth at that moment, how the two engines agree, and the rule grid."""
    lines = [f"Cache deals (source `{data['source']}`): {data['deals']}; compared (a probe search "
             f"of the trip while the deal was open): {data['compared']}, of them approved "
             f"{data['approved_compared']}. Truth tolerance {data['tolerance']:.0%} (the recheck's).",
             "", "| Deal | Route, airport | Trip | Price | Carrier, seller, bag | Approved | "
             "Expiry | Life h (rechecks) | Searches GF/K | First search, then every (h) | "
             "Gap first; min … max | Airline price | Cache later |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in data["deal_rows"]:
        expiry = ("open" if r["expired_at"] is None else
                  f"{r['expired_kind']}{' (rose)' if r['rose'] else ''} {_t(datetime.fromisoformat(r['expired_at']))}"
                  f"{' ≈' if r['approximate'] else ''}")
        bag = {None: "bag ?", False: "cabin", True: "checked bag"}[r["with_baggage"]]
        gaps = ("–" if r["first_gap"] is None else
                f"{r['first_gap']:+.0%}; {r['min_gap']:+.0%} … {r['max_gap']:+.0%}")
        lines.append(
            f"| {r['deal_id']} | {r['route']} {r['airport']} | {r['departure_date'][5:]}–{r['return_date'][5:]} | "
            f"{r['price']:g} € | {r['airline']}, {r['seller'] or '–'}, {bag}{'' if r['nonstop'] else ', not nonstop'} | "
            f"{r['approver'] if r['approved_at'] else 'no'} | {expiry} | {r['life_hours']:.0f} ({r['rechecks']}) | "
            f"{r['searches'][gf_engine.SOURCE]}/{r['searches'][kayak_engine.SOURCE]} | "
            f"{_h(r['first_search_hours'])}, {_h(r['hours_between_searches'])} | {gaps} | "
            f"{', '.join(f'{p:g}' for p in r['airline_prices']) or '–'} | "
            f"{', '.join(f'{p:g}' for p in r['cache_later']) or '–'} |")
    lines += ["", "Every probe search from 24 h before detection to the deal's end (cheapest option "
              "per search; * = another carrier or airport than the deal's):", "",
              "| Deal | Engine | Seller | Carrier, airport | Price | Gap | Searched | After detection (h) | "
              "Import lag (h) | Before end (h) | Truth then |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in data["readings"]:
        mark = "*" if r["airline_differs"] or r["airport_differs"] else ""
        lines.append(
            f"| {r['deal_id']} | {r['engine']} | {r['seller'] or '–'} | {r['airline']}, {r['airport']}{mark} | "
            f"{r['price']:g} € | {r['gap_eur']:+g} € ({r['gap_pct']:+.0%}) | {_t(datetime.fromisoformat(r['at']))} | "
            f"{r['hours_after_detection']:.1f} | {r['import_lag_hours']:.1f} | {r['hours_before_end']:.0f} | "
            f"{r['truth']}{': ' + r['truth_detail'] if r['truth_detail'] else ''} |")
    pairs = data["pairs"]
    if pairs:
        between = [abs(p["between"]) for p in pairs]
        lines += ["", f"Google Flights and Kayak on the same trip within {PAIR_WINDOW.seconds // 3600} h, "
                  f"during a deal's life: {len(pairs)} pairs; |GF − Kayak| median {statistics.median(between):.1%}, "
                  f"max {max(between):.1%}; within 5 % of each other {sum(b <= 0.05 for b in between)}.", "",
                  "| Both engines vs the deal | Pairs |", "|---|---|"]
        for label, test in [("both ≥ 10 % higher", lambda p: min(p["gf_gap"], p["kayak_gap"]) >= 0.10),
                            ("both ≥ 5 % higher", lambda p: min(p["gf_gap"], p["kayak_gap"]) >= 0.05),
                            ("both within ±5 %", lambda p: max(abs(p["gf_gap"]), abs(p["kayak_gap"])) <= 0.05),
                            ("one ≥ 10 % higher, the other within 5 %",
                             lambda p: max(p["gf_gap"], p["kayak_gap"]) >= 0.10 and min(p["gf_gap"], p["kayak_gap"]) <= 0.05),
                            ("either below the deal", lambda p: min(p["gf_gap"], p["kayak_gap"]) < 0)]:
            lines.append(f"| {label} | {sum(1 for p in pairs if test(p))} |")
    c = data.get("control") or {}
    if c.get("deals"):
        lines += ["", f"Control: {c['deals']} deals from `{c['source']}` (rechecked at the seller every run) "
                  f"with a probe search while open, {c['searches']} searches at their airport: gap median "
                  f"{c['median_gap']:+.1%}; ≥ 5 % above {c['at_least_5']}, ≥ 10 % above {c['at_least_10']}, "
                  f"below the deal {c['below']}."]
    known = data["stale_known"]
    lines += ["", f"Rule grid. \"Stale known\": deals the truth calls stale at one of their probe "
              f"searches ({len(known)}: {', '.join(map(str, known)) or 'none'}). A rule fires at the "
              f"first recheck (probe import) where its condition holds; the truth is judged at the "
              f"search that fired it. \"Early\": median hours before the real expiry (expired deals). "
              f"\"Control false\": control deals it would have expired more than "
              f"{CONTROL_SLACK.seconds // 3600} h before their own source did (of those it fired on).", "",
              *GRID_HEADER]
    guarded = True
    ids = lambda xs: ", ".join(map(str, xs)) or "–"   # noqa: E731
    for g in data["grid"]:
        if not every_rule and not g["fired"]:
            continue
        r = g["rule"]
        if guarded and not r["newer_than_price"]:
            guarded = False
            lines += ["", "The same rules without the found-time guard (searches older than the "
                      "deal's price count too):", "", *GRID_HEADER]
        lines.append(
            f"| {'airport' if r['same_airport'] else 'trip'} | {r['engines']} | {r['max_age_hours']:g} | "
            f"≥{r['pct']:.0%}, ≥{r['eur']:g} € | {g['fired']} | {g['approved_when_fired']} | "
            f"{ids(g['stale_airline'])} | {ids(g['stale_rose'])} | {ids(g['stale_timer'])} | "
            f"{ids(g['real'])} | {ids(g['unknown'])} | {ids(g['open'])} | {_h(g['median_hours_early'])} | "
            f"{len(g['caught_stale_known'])}/{len(g['stale_known'])} | "
            f"{ids(g['control_false'])} ({len(g['control_fired'])}) |")
    return "\n".join(lines) + "\n"
