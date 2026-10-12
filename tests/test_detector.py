from datetime import date, datetime, timedelta, timezone

import pytest

from escapadinha.config import DetectorConfig
from escapadinha.detector import Decision, baseline, detect_route, evaluate
from escapadinha.models import Observation

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
CFG = DetectorConfig(threshold=0.30, lookback_days=90, min_samples=5, min_history_days=3,
                     dedupe_days=7)


def obs(price, *, days_ago=0.0, dep=date(2026, 11, 6), nights=4, airline="TP", oid=None):
    return Observation(
        id=oid, run_id=None, source="test", origin="LIS", destination="LON",
        origin_airport="LIS", destination_airport="LGW", departure_date=dep,
        return_date=dep + timedelta(days=nights), price=float(price), currency="EUR",
        airline=airline, flight_number="1", transfers=0, return_transfers=0, deep_link=None,
        fetched_at=NOW - timedelta(days=days_ago), raw_json="{}",
    )


def spread_history(prices, span_days=10):
    """Distinct offers spread evenly over `span_days`."""
    step = span_days / max(len(prices) - 1, 1)
    return [obs(p, days_ago=i * step, dep=date(2026, 11, 1) + timedelta(days=i))
            for i, p in enumerate(prices)]


# --- baseline -----------------------------------------------------------------

def test_baseline_median_of_odd_and_even_samples():
    assert baseline(spread_history([100, 300, 200])).median == 200
    assert baseline(spread_history([100, 200, 300, 400])).median == 250


def test_baseline_counts_same_offer_once_per_day():
    # The cache returns the same offer on every run; three fetches on one day = one sample.
    same_day = [obs(50, days_ago=0.1 * i) for i in range(3)]
    other = [obs(150, days_ago=5, dep=date(2026, 12, 1))]
    b = baseline(same_day + other)
    assert b.sample_size == 2
    assert b.median == 100


def test_baseline_same_offer_on_different_days_counts_each_day():
    b = baseline([obs(80, days_ago=d) for d in (0, 1, 2)])
    assert b.sample_size == 3


def test_baseline_span_days():
    assert baseline(spread_history([1, 2, 3], span_days=10)).span_days == pytest.approx(10)


def test_baseline_empty_history():
    b = baseline([])
    assert (b.median, b.sample_size, b.span_days) == (None, 0, 0)


# --- evaluate -----------------------------------------------------------------

def mature():
    return baseline(spread_history([100, 100, 100, 100, 100, 100], span_days=10))


def test_price_well_below_median_is_a_deal():
    d = evaluate(obs(60), mature(), CFG, price_cap=None)
    assert d.kind == "deal" and d.rule == "median"
    assert d.discount_pct == pytest.approx(0.40)


def test_price_exactly_at_threshold_is_a_deal():
    assert evaluate(obs(70), mature(), CFG, price_cap=None).kind == "deal"


def test_price_just_above_threshold_is_not_a_deal():
    assert evaluate(obs(70.01), mature(), CFG, price_cap=None).kind == "no_deal"


def test_threshold_is_configurable():
    strict = CFG.model_copy(update={"threshold": 0.5})
    assert evaluate(obs(60), mature(), strict, price_cap=None).kind == "no_deal"


def test_too_few_samples_is_insufficient_history():
    thin = baseline(spread_history([100, 100, 100], span_days=10))
    d = evaluate(obs(10), thin, CFG, price_cap=None)
    assert d.kind == "insufficient_history"
    assert "3/5" in d.reason


def test_too_short_history_span_is_insufficient_history():
    short = baseline(spread_history([100] * 10, span_days=1))
    assert evaluate(obs(10), short, CFG, price_cap=None).kind == "insufficient_history"


def test_price_cap_flags_only_while_history_is_insufficient():
    thin = baseline([])
    d = evaluate(obs(39), thin, CFG, price_cap=40)
    assert d.kind == "deal" and d.rule == "price_cap" and d.discount_pct is None
    assert evaluate(obs(41), thin, CFG, price_cap=40).kind == "insufficient_history"
    # Once history is mature the median rule decides, the cap is ignored.
    assert evaluate(obs(39), baseline(spread_history([45] * 6)), CFG, price_cap=40).kind == "no_deal"


# --- detect_route -------------------------------------------------------------

def test_detect_route_flags_cheapest_deal_only():
    history = spread_history([100] * 6)
    candidates = [obs(65, oid=1), obs(50, oid=2, dep=date(2026, 11, 20)), obs(99, oid=3)]
    flagged = detect_route(candidates, history, recently_flagged=[], cfg=CFG, price_cap=None,
                           now=NOW, max_deals=1)
    assert [(o.id, d.kind) for o, d in flagged] == [(2, "deal")]


def test_detect_route_respects_max_deals():
    history = spread_history([100] * 6)
    candidates = [obs(65, oid=1), obs(50, oid=2, dep=date(2026, 11, 20))]
    flagged = detect_route(candidates, history, [], CFG, None, NOW, max_deals=2)
    assert [o.id for o, _ in flagged] == [2, 1]


def test_detect_route_ignores_history_outside_lookback():
    old_cheap = [obs(10, days_ago=200 + i, dep=date(2026, 11, 1) + timedelta(days=i))
                 for i in range(10)]
    recent = spread_history([100] * 6)
    flagged = detect_route([obs(60, oid=1)], old_cheap + recent, [], CFG, None, NOW, max_deals=1)
    assert [o.id for o, _ in flagged] == [1]


def test_detect_route_dedupes_recently_flagged_same_trip():
    history = spread_history([100] * 6)
    already = [obs(60, days_ago=2)]
    assert detect_route([obs(60, oid=1)], history, already, CFG, None, NOW, max_deals=1) == []


def test_detect_route_reflags_when_price_drops_further():
    history = spread_history([100] * 6)
    already = [obs(60, days_ago=2)]
    flagged = detect_route([obs(55, oid=1)], history, already, CFG, None, NOW, max_deals=1)
    assert [o.id for o, _ in flagged] == [1]


def test_detect_route_dedupe_window_expires():
    history = spread_history([100] * 6)
    already = [obs(60, days_ago=8)]
    flagged = detect_route([obs(60, oid=1)], history, already, CFG, None, NOW, max_deals=1)
    assert [o.id for o, _ in flagged] == [1]


def test_detect_route_with_no_history_never_flags_without_cap():
    assert detect_route([obs(1, oid=1)], [], [], CFG, None, NOW, max_deals=1) == []


def test_decision_is_value_object():
    assert Decision("no_deal", None, None, "x") == Decision("no_deal", None, None, "x")
