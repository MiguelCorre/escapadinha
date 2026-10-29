from datetime import date, datetime, timedelta, timezone

from escapadinha.config import DetectorConfig
from escapadinha.detector import Baseline
from escapadinha.models import Observation, RouteRules
from escapadinha.recheck import promotion_expiry, recheck

NOW = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)
CFG = DetectorConfig(max_offer_age_days=3)


def obs(price, *, dep=date(2026, 11, 25), ret=date(2026, 11, 28), found_ago=0):
    return Observation(source="test", origin="OPO", destination="PAR", origin_airport="OPO",
                       destination_airport="BVA", departure_date=dep, return_date=ret,
                       price=float(price), currency="EUR", airline="FR", flight_number="1",
                       transfers=0, return_transfers=0, deep_link=None, fetched_at=NOW,
                       raw_json="{}", found_date=NOW.date() - timedelta(days=found_ago))


DEAL = obs(60, found_ago=3)


def test_still_valid_at_same_or_lower_price():
    r = recheck(DEAL, [obs(60), obs(90)], CFG, NOW)
    assert r.valid and r.latest_price == 60
    assert recheck(DEAL, [obs(55)], CFG, NOW).valid


def test_expires_when_price_rose():
    """The real case from 2026-10-12: OPO-PAR 25/11 went from 60 € to 70 €."""
    r = recheck(DEAL, [obs(70), obs(200, dep=date(2026, 11, 26))], CFG, NOW)
    assert not r.valid and r.latest_price == 70 and r.reason == "o preço subiu para 70 €"


def test_expires_when_trip_disappears():
    r = recheck(DEAL, [obs(40, dep=date(2026, 11, 26))], CFG, NOW)
    assert not r.valid and r.latest_price is None


def test_expires_when_price_is_no_longer_fresh():
    r = recheck(DEAL, [obs(60, found_ago=4)], CFG, NOW)
    assert not r.valid and "há mais de 3 dias" in r.reason


def test_tolerance():
    assert recheck(DEAL, [obs(61)], CFG, NOW, tolerance_eur=1).valid


def test_a_rise_within_the_tolerance_holds_while_still_a_promotion():
    """D53: a bouncing fare is one promotion. 60 -> 62 (3 %) holds; 60 -> 64 (6.7 %) expires;
    a rise within the tolerance that is no longer 30 % and 15 € below the typical low expires
    too, with the typical low in the reason."""
    cfg = DetectorConfig(recheck_tolerance_pct=0.05)
    held = recheck(DEAL, [obs(62)], cfg, NOW, typical_low=100)
    assert held.valid and held.latest_price == 62
    assert held.reason == "subiu para 62 €, dentro da tolerância de 5%"
    gone = recheck(DEAL, [obs(64)], cfg, NOW, typical_low=100)
    assert not gone.valid and gone.reason == "o preço subiu para 64 €"
    edge = recheck(DEAL, [obs(63)], cfg, NOW, typical_low=100)          # exactly 5 %
    assert edge.valid
    not_promo = recheck(DEAL, [obs(62)], cfg, NOW, typical_low=85)     # 62 > 85 × 0.7
    assert not not_promo.valid
    assert not_promo.reason == "o preço subiu para 62 € e já não é promoção face ao preço habitual (85 €)"
    # Without a typical low (price-cap deals, older deals) only the tolerance applies.
    assert recheck(DEAL, [obs(62)], cfg, NOW).valid
    # A fall is never a rise: the old reason.
    assert recheck(DEAL, [obs(55)], cfg, NOW, typical_low=85).reason == "continua a 55 €"


def test_direct_only_expires_deals_with_connections():
    from dataclasses import replace
    connection = replace(DEAL, return_transfers=1)
    r = recheck(connection, [connection], CFG, NOW, rules=RouteRules())
    assert not r.valid and "voos diretos" in r.reason
    one_stop = RouteRules(direct_only=False, max_transfers=1)
    assert recheck(connection, [connection], CFG, NOW, rules=one_stop).valid


def test_long_haul_deal_expires_when_it_gains_a_second_stop():
    from dataclasses import replace
    rules = RouteRules(direct_only=False, min_nights=2, max_nights=21, max_transfers=1)
    deal = replace(DEAL, transfers=1, return_transfers=1)
    assert recheck(deal, [deal], CFG, NOW, rules=rules).valid
    r = recheck(replace(deal, transfers=2), [deal], CFG, NOW, rules=rules)
    assert not r.valid and "1 escala" in r.reason


def test_deal_outside_the_routes_nights_range_expires():
    r = recheck(DEAL, [DEAL], CFG, NOW, rules=RouteRules(min_nights=7, max_nights=14))
    assert not r.valid and "7–14 noites" in r.reason


# --- an open promotion against its month's current typical low (D40) -------------------------

PROMO = DetectorConfig()                      # the shipped maturity: 10 days spanning 9
MATURE = Baseline(median=76, sample_size=12, span_days=14)


def test_a_promotion_on_a_typical_low_still_too_young_expires():
    """The 6 deals waiting for review on 2026-10-16 were detected on 4-6-day typical lows."""
    young = Baseline(median=76, sample_size=5, span_days=6)
    assert promotion_expiry(obs(51), "median", young, PROMO, None) == \
        "preço habitual ainda sem dados suficientes (5 de 10 dias)"
    narrow = Baseline(median=76, sample_size=10, span_days=7)   # only with a lower day count
    assert promotion_expiry(obs(51), "median", narrow, PROMO, None) == \
        "preço habitual ainda sem dados suficientes (10 dias, mas do primeiro ao último só 7 de 9)"
    none = Baseline(median=None, sample_size=0, span_days=0)
    assert promotion_expiry(obs(51), "median", none, PROMO, None) == \
        "preço habitual ainda sem dados suficientes (0 de 10 dias)"


def test_a_promotion_still_below_the_current_typical_low_stays():
    assert promotion_expiry(obs(51), "median", MATURE, PROMO, None) is None   # 33 %, 25 €


def test_a_promotion_no_longer_below_the_current_typical_low_expires():
    assert promotion_expiry(obs(60), "median", MATURE, PROMO, None) == (
        "já não é promoção face ao preço habitual atual (76 €): 60 € fica 21% abaixo; "
        "são precisos 30% e 15 €")
    assert promotion_expiry(obs(80), "median", MATURE, PROMO, None) == (
        "já não é promoção face ao preço habitual atual (76 €): 80 € fica 5% acima; "
        "são precisos 30% e 15 €")
    cheap = Baseline(median=40, sample_size=12, span_days=14)     # 35 % but saves only 14 €
    assert "26 € fica 35% abaixo" in promotion_expiry(obs(26), "median", cheap, PROMO, None)


def test_a_promotion_that_is_no_longer_a_new_low_expires_with_the_reason():
    """D44: a cheaper fare joined the window since detection, so the deal would not be
    detected now; without the rule it stays."""
    from dataclasses import replace
    floor = obs(49, found_ago=5)
    undercut = replace(MATURE, min_low=floor)                 # 51 € is not 5 % below 49 €
    assert promotion_expiry(obs(51), "median", undercut, PROMO, None) == (
        "já não é um novo mínimo: entretanto vimos 49 € para este mês, e 51 € teria de ficar "
        "5% abaixo disso")
    assert promotion_expiry(obs(46), "median", undercut, PROMO, None) is None
    lax = PROMO.model_copy(update={"require_new_low": False})
    assert promotion_expiry(obs(51), "median", undercut, lax, None) is None
    # The percentage rule still comes first: 60 € fails it before the new-low one.
    assert promotion_expiry(obs(60), "median", undercut, PROMO, None).startswith(
        "já não é promoção face ao preço habitual atual")


def test_the_price_cap_only_keeps_the_promotions_it_made():
    """Until the typical low is mature only a route's price cap makes a promotion (D3, D40); a
    deal of the median rule never survives on the cap."""
    young = Baseline(median=76, sample_size=5, span_days=6)
    assert promotion_expiry(obs(51), "price_cap", young, PROMO, 55) is None
    assert promotion_expiry(obs(56), "price_cap", young, PROMO, 55).startswith(
        "preço habitual ainda sem dados suficientes")
    assert promotion_expiry(obs(51), "median", young, PROMO, 55).startswith(
        "preço habitual ainda sem dados suficientes")
    # Once mature, a cap promotion is judged like any other (the cap no longer applies).
    assert promotion_expiry(obs(51), "price_cap", MATURE, PROMO, 55) is None
    assert promotion_expiry(obs(60), "price_cap", MATURE, PROMO, 65).startswith(
        "já não é promoção")
