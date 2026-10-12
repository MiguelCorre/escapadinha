from datetime import date, datetime, timedelta, timezone

from escapadinha.config import DetectorConfig
from escapadinha.models import Observation
from escapadinha.recheck import recheck

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
    assert not r.valid and r.latest_price == 70 and "70" in r.reason


def test_expires_when_trip_disappears():
    r = recheck(DEAL, [obs(40, dep=date(2026, 11, 26))], CFG, NOW)
    assert not r.valid and r.latest_price is None


def test_expires_when_price_is_no_longer_fresh():
    r = recheck(DEAL, [obs(60, found_ago=4)], CFG, NOW)
    assert not r.valid and "older than 3 days" in r.reason


def test_tolerance():
    assert recheck(DEAL, [obs(61)], CFG, NOW, tolerance_eur=1).valid


def test_direct_only_expires_deals_with_connections():
    from dataclasses import replace
    connection = replace(DEAL, return_transfers=1)
    r = recheck(connection, [connection], DetectorConfig(direct_only=True), NOW)
    assert not r.valid and "direct" in r.reason
    assert recheck(connection, [connection], DetectorConfig(direct_only=False, max_offer_age_days=3), NOW).valid
