from datetime import date, datetime, timedelta, timezone

import pytest

from escapadinha.config import DetectorConfig
from escapadinha.detector import (
    Baseline, Decision, baseline, day_key, detect_route, evaluate, is_fresh, month_baselines,
)
from escapadinha.models import Observation

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
TODAY = NOW.date()
CFG = DetectorConfig(threshold=0.30, lookback_days=90, min_baseline_days=4, dedupe_days=7,
                     max_offer_age_days=3)


def obs(price, *, found_ago=0, dep=date(2026, 11, 6), nights=4, oid=None, fetched_ago=0.0,
        found=True):
    return Observation(
        id=oid, run_id=None, source="test", origin="LIS", destination="LON",
        origin_airport="LIS", destination_airport="LGW", departure_date=dep,
        return_date=dep + timedelta(days=nights), price=float(price), currency="EUR",
        airline="TP", flight_number="1", transfers=0, return_transfers=0, deep_link=None,
        fetched_at=NOW - timedelta(days=fetched_ago), raw_json="{}",
        found_date=TODAY - timedelta(days=found_ago) if found else None,
    )


def lows(prices, *, first_ago=4, dep=date(2026, 11, 6)):
    """One offer per day, found `first_ago`, `first_ago+1`, ... days ago (baseline days)."""
    return [obs(p, found_ago=first_ago + i, dep=dep + timedelta(days=i % 20))
            for i, p in enumerate(prices)]


# --- baseline: median of daily lows -------------------------------------------------

def test_baseline_takes_the_lowest_price_per_day_then_the_median():
    history = [obs(100, found_ago=5), obs(80, found_ago=5), obs(300, found_ago=5),   # low 80
               obs(90, found_ago=6), obs(120, found_ago=6),                          # low 90
               obs(70, found_ago=7)]                                                 # low 70
    b = baseline(history, since=TODAY - timedelta(days=90), before=TODAY)
    assert (b.median, b.sample_size, b.span_days) == (80, 3, 2)


def test_baseline_respects_window():
    history = lows([50, 60, 70, 80], first_ago=4)          # days 4..7 ago
    b = baseline(history, since=TODAY - timedelta(days=6), before=TODAY - timedelta(days=4))
    assert b.sample_size == 2 and b.median == 65            # only days 5 and 6


def test_baseline_empty():
    assert baseline([], since=TODAY, before=TODAY) == Baseline(None, 0, 0)


def test_day_key_falls_back_to_fetch_day():
    assert day_key(obs(1, found_ago=3)) == TODAY - timedelta(days=3)
    assert day_key(obs(1, found=False, fetched_ago=2)) == TODAY - timedelta(days=2)


def test_month_baselines_are_per_departure_month_and_exclude_fresh_days():
    nov = lows([100] * 5, dep=date(2026, 11, 1))
    dec = lows([200] * 5, dep=date(2026, 12, 1))
    fresh_cheap = [obs(10, found_ago=0, dep=date(2026, 11, 2))]   # inside freshness window
    b = month_baselines(nov + dec + fresh_cheap, CFG, NOW)
    assert b[(2026, 11)].median == 100 and b[(2026, 12)].median == 200


# --- evaluate -------------------------------------------------------------------------

MATURE = Baseline(median=100, sample_size=6, span_days=6)


def test_price_well_below_typical_low_is_a_deal():
    d = evaluate(obs(60), MATURE, CFG, price_cap=None)
    assert d.kind == "deal" and d.rule == "median"
    assert d.discount_pct == pytest.approx(0.40)


def test_threshold_boundaries():
    assert evaluate(obs(70), MATURE, CFG, price_cap=None).kind == "deal"
    assert evaluate(obs(70.01), MATURE, CFG, price_cap=None).kind == "no_deal"


def test_threshold_is_configurable():
    strict = CFG.model_copy(update={"threshold": 0.5})
    assert evaluate(obs(60), MATURE, strict, price_cap=None).kind == "no_deal"


def test_too_few_baseline_days_is_insufficient_history():
    d = evaluate(obs(10), Baseline(100, 3, 2), CFG, price_cap=None)
    assert d.kind == "insufficient_history" and "3/4" in d.reason


def test_price_cap_flags_only_while_history_is_insufficient():
    thin = Baseline(None, 0, 0)
    d = evaluate(obs(39), thin, CFG, price_cap=40)
    assert d.kind == "deal" and d.rule == "price_cap" and d.discount_pct is None
    assert evaluate(obs(41), thin, CFG, price_cap=40).kind == "insufficient_history"
    assert evaluate(obs(39), Baseline(45, 6, 6), CFG, price_cap=40).kind == "no_deal"


# --- freshness --------------------------------------------------------------------------

def test_freshness_window():
    assert is_fresh(obs(1, found_ago=3), CFG, NOW)
    assert not is_fresh(obs(1, found_ago=4), CFG, NOW)
    assert is_fresh(obs(1, found=False), CFG, NOW)          # unknown found date: fetched today


# --- detect_route -------------------------------------------------------------------------

def test_cold_start_bootstraps_from_found_dates_in_one_run():
    """A single fetch holds a week of found dates: older days form the baseline at once."""
    run = lows([100, 95, 105, 100, 98], first_ago=4) + [obs(60, found_ago=1, oid=1)]
    flags = detect_route(run, run, [], CFG, None, NOW, max_deals=1)
    assert [f.observation.id for f in flags] == [1]
    assert flags[0].baseline.sample_size == 5 and flags[0].baseline.median == 100


def test_cheapest_dates_are_not_deals_when_they_are_the_usual_low():
    # All-fares median would be ~150 and flag 95 as -37%; the typical low is 100.
    history = lows([100, 98, 102, 100, 101]) + [obs(200 + i, found_ago=4 + i % 5) for i in range(10)]
    flags = detect_route([obs(95, oid=1)], history, [], CFG, None, NOW, max_deals=1)
    assert flags == []


def test_baseline_is_per_departure_month():
    history = lows([100] * 5, dep=date(2026, 11, 1)) + lows([40] * 5, dep=date(2026, 12, 1))
    nov = obs(60, oid=1, dep=date(2026, 11, 20))    # -40% vs November low
    dec = obs(60, oid=2, dep=date(2026, 12, 20))    # above December low
    flags = detect_route([nov, dec], history, [], CFG, None, NOW, max_deals=5)
    assert [f.observation.id for f in flags] == [1]


def test_biggest_discount_first_and_max_deals():
    history = lows([100] * 5, dep=date(2026, 11, 1)) + lows([200] * 5, dep=date(2026, 12, 1))
    a = obs(65, oid=1, dep=date(2026, 11, 20))     # -35%
    b = obs(100, oid=2, dep=date(2026, 12, 20))    # -50%
    assert [f.observation.id for f in detect_route([a, b], history, [], CFG, None, NOW, 1)] == [2]
    assert [f.observation.id for f in detect_route([a, b], history, [], CFG, None, NOW, 2)] == [2, 1]


def test_stale_candidates_are_skipped():
    history = lows([100] * 5, first_ago=8)
    stale = obs(50, found_ago=4, oid=1)
    fresh = obs(60, found_ago=3, oid=2, dep=date(2026, 11, 20))
    flags = detect_route([stale, fresh], history, [], CFG, None, NOW, max_deals=3)
    assert [f.observation.id for f in flags] == [2]


def test_same_trip_is_only_flagged_once_per_run():
    history = lows([100] * 5)
    twins = [obs(60, oid=1), obs(60, oid=2)]
    assert len(detect_route(twins, history, [], CFG, None, NOW, max_deals=5)) == 1


def test_dedupes_recently_flagged_same_trip_unless_cheaper():
    history = lows([100] * 5)
    already = [obs(60, fetched_ago=2)]
    assert detect_route([obs(60, oid=1)], history, already, CFG, None, NOW, 1) == []
    assert len(detect_route([obs(55, oid=1)], history, already, CFG, None, NOW, 1)) == 1


def test_dedupe_window_expires():
    history = lows([100] * 5)
    already = [obs(60, fetched_ago=8)]
    assert len(detect_route([obs(60, oid=1)], history, already, CFG, None, NOW, 1)) == 1


def test_no_history_never_flags_without_cap():
    assert detect_route([obs(1, oid=1)], [], [], CFG, None, NOW, max_deals=1) == []


def test_lookback_excludes_old_days():
    old_cheap = lows([10] * 5, first_ago=100)
    assert detect_route([obs(60, oid=1)], old_cheap, [], CFG, None, NOW, 1) == []


def test_decision_is_value_object():
    assert Decision("no_deal", None, None, "x") == Decision("no_deal", None, None, "x")
