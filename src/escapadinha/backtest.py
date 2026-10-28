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

from escapadinha import detector, i18n_pt, routes
from escapadinha.config import DetectorConfig, RoutesConfig
from escapadinha.models import Observation, Route, RouteRules
from escapadinha.recheck import recheck
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
