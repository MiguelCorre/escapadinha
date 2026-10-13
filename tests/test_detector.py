from datetime import date, datetime, timedelta, timezone

import pytest

from escapadinha.config import DetectorConfig
from escapadinha.detector import (
    Baseline, Decision, Detection, LowPrice, baseline, day_key, detect, detect_route, evaluate,
    is_fresh, low_prices, month_baselines,
)
from escapadinha.models import Observation, RouteRules

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


# --- per-route rules ------------------------------------------------------------------------

def _with_stops(o, back=1, out=0):
    from dataclasses import replace
    return replace(o, transfers=out, return_transfers=back)


DIRECT = RouteRules()
LONG_HAUL = RouteRules(direct_only=False, min_nights=7, max_nights=21, max_transfers=1)


def test_direct_only_ignores_connections_for_deals_and_baseline():
    cheap_connection = _with_stops(obs(40, oid=1))
    history = lows([100] * 5) + [_with_stops(o) for o in lows([30] * 5)]   # cheap lows w/ stops
    flags = detect_route([cheap_connection, obs(65, oid=2)], history, [], CFG, None, NOW, 5,
                         rules=DIRECT)
    assert [f.observation.id for f in flags] == [2]           # 65 vs direct typical low 100
    assert flags[0].baseline.median == 100


def test_direct_only_off_keeps_everything():
    anything = RouteRules(direct_only=False, max_transfers=None)
    flags = detect_route([_with_stops(obs(40, oid=1), back=3)], lows([100] * 5), [], CFG, None,
                         NOW, 5, rules=anything)
    assert [f.observation.id for f in flags] == [1]


def test_max_transfers_is_per_direction_and_unknown_counts_never_pass():
    rules = RouteRules(direct_only=False, max_transfers=1)
    assert rules.allows(_with_stops(obs(40), back=1, out=1))
    assert not rules.allows(_with_stops(obs(40), back=2, out=0))
    assert not rules.allows(_with_stops(obs(40), back=None))


def test_long_haul_rules_take_one_stop_and_their_own_nights_range():
    """A long-haul route: one stop each way is fine, a 4-night trip is not."""
    week = [_with_stops(o, back=1, out=1) for o in lows([800] * 5)]
    week = [replace_nights(o, 10) for o in week]
    one_stop = replace_nights(_with_stops(obs(500, oid=1), back=1, out=1), 10)
    two_stops = replace_nights(_with_stops(obs(400, oid=2), back=2, out=1), 10)
    too_short = _with_stops(obs(300, oid=3), back=1, out=1)                 # 4 nights
    flags = detect_route([one_stop, two_stops, too_short], week, [], CFG, None, NOW, 5,
                         rules=LONG_HAUL)
    assert [f.observation.id for f in flags] == [1]
    assert flags[0].baseline.median == 800
    # The same offers on a Europe route: none qualifies (connections), no baseline either.
    assert detect_route([one_stop], week, [], CFG, None, NOW, 5, rules=DIRECT) == []


def test_nights_range_filters_the_baseline_too():
    short = lows([50] * 5)                                    # 4-night trips, cheap
    long_ = [replace_nights(o, 8) for o in lows([100] * 5)]
    rules = RouteRules(min_nights=7, max_nights=14)
    assert month_baselines(short + long_, CFG, NOW, rules)[(2026, 11)].median == 100


def replace_nights(o, nights):
    from dataclasses import replace
    return replace(o, return_date=o.departure_date + timedelta(days=nights))


# --- two tiers: promotion candidates (threshold + 15 € floor) and low prices (D24) ---------

CHEAP = Baseline(median=40, sample_size=6, span_days=6)


def test_candidate_needs_the_min_saving_in_euros_too():
    """26 € is 35 % below a 40 € typical low but saves only 14 €: not a promotion."""
    d = evaluate(obs(26), CHEAP, CFG, price_cap=None)
    assert d.kind == "no_deal" and "saves only 14.00" in d.reason
    assert evaluate(obs(25), CHEAP, CFG, price_cap=None).kind == "deal"        # exactly 15 €
    assert evaluate(obs(25.01), CHEAP, CFG, price_cap=None).kind == "no_deal"


def test_min_saving_floor_is_configurable_and_both_rules_must_hold():
    assert evaluate(obs(26), CHEAP, CFG.model_copy(update={"min_saving_eur": 0}), None).kind == "deal"
    strict = CFG.model_copy(update={"min_saving_eur": 50})
    assert evaluate(obs(60), MATURE, strict, price_cap=None).kind == "no_deal"   # 40 % but 40 €
    assert evaluate(obs(75), MATURE, CFG, price_cap=None).kind == "no_deal"      # 25 € but 25 %


def test_price_cap_path_ignores_the_saving_floor():
    d = evaluate(obs(39), Baseline(None, 0, 0), CFG, price_cap=40)
    assert d.kind == "deal" and d.rule == "price_cap"


def test_low_threshold_boundaries():
    history = lows([100] * 5)
    assert [lp.observation.id for lp in low_prices([obs(85, oid=1)], history, CFG, NOW)] == [1]
    assert low_prices([obs(85.01, oid=1)], history, CFG, NOW) == []
    [lp] = low_prices([obs(80, oid=1)], history, CFG, NOW)
    assert lp.discount_pct == pytest.approx(0.20) and lp.baseline.median == 100


def test_low_threshold_is_configurable():
    history = lows([100] * 5)
    loose = CFG.model_copy(update={"low_threshold": 0.05})
    assert len(low_prices([obs(94, oid=1)], history, loose, NOW)) == 1
    assert low_prices([obs(94, oid=1)], history, CFG, NOW) == []


def test_default_tiers_and_low_threshold_above_threshold_is_rejected():
    default = DetectorConfig()
    assert (default.low_threshold, default.threshold, default.min_saving_eur) == (0.15, 0.30, 15)
    with pytest.raises(ValueError, match="low_threshold"):
        DetectorConfig(threshold=0.2, low_threshold=0.3)


def test_low_prices_need_a_mature_baseline_even_with_a_price_cap():
    thin = lows([100] * 3)                                   # 3 of 4 days
    assert low_prices([obs(10, oid=1)], thin, CFG, NOW) == []
    assert len(detect_route([obs(10, oid=1)], thin, [], CFG, 40, NOW, 1)) == 1   # cap candidate


def test_low_prices_are_fresh_within_the_rules_one_per_trip_biggest_discount_first():
    history = lows([100] * 5, dep=date(2026, 11, 1)) + lows([200] * 5, dep=date(2026, 12, 1))
    offers = [
        obs(80, oid=1, dep=date(2026, 11, 20)),                  # -20 %
        obs(78, oid=2, dep=date(2026, 11, 20)),                  # same trip, cheaper: kept
        obs(120, oid=3, dep=date(2026, 12, 20)),                 # -40 % vs December
        obs(50, oid=4, found_ago=4),                             # stale
        _with_stops(obs(50, oid=5, dep=date(2026, 11, 25))),     # not direct
        obs(90, oid=6, dep=date(2026, 11, 22)),                  # -10 %: not low
    ]
    assert [lp.observation.id for lp in low_prices(offers, history, CFG, NOW)] == [3, 2]


def test_detect_returns_low_prices_and_candidates_separately():
    history = lows([100] * 5, dep=date(2026, 11, 1))
    low_only = obs(80, oid=1, dep=date(2026, 11, 20))           # -20 %: low price only
    both = obs(65, oid=2, dep=date(2026, 11, 22))               # -35 %, 35 €: also a candidate
    found = detect([low_only, both], history, [], CFG, None, NOW, max_deals=5)
    assert isinstance(found, Detection)
    assert [lp.observation.id for lp in found.low_prices] == [2, 1]
    assert all(isinstance(lp, LowPrice) for lp in found.low_prices)
    assert [f.observation.id for f in found.candidates] == [2]


def test_detect_keeps_one_candidate_per_route_but_every_low_price():
    history = lows([100] * 5, dep=date(2026, 11, 1))
    offers = [obs(60, oid=1, dep=date(2026, 11, 20)), obs(62, oid=2, dep=date(2026, 11, 22))]
    found = detect(offers, history, [], CFG, None, NOW, max_deals=1)
    assert [f.observation.id for f in found.candidates] == [1]
    assert [lp.observation.id for lp in found.low_prices] == [1, 2]


def test_detect_offers_already_a_deal_stay_low_prices_but_never_candidates():
    history = lows([100] * 5)
    found = detect([obs(60, oid=7)], history, [], CFG, None, NOW, max_deals=1, taken={7})
    assert [lp.observation.id for lp in found.low_prices] == [7] and found.candidates == []


def test_small_fare_route_gets_low_prices_but_no_candidate():
    """A 40 € route: 26 € is a low price (-35 %) but saves only 14 €, so no promotion."""
    found = detect([obs(26, oid=1)], lows([40] * 5), [], CFG, None, NOW, max_deals=1)
    assert [lp.observation.id for lp in found.low_prices] == [1] and found.candidates == []
