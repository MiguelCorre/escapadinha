from datetime import date

from escapadinha.collector import hotlist
from escapadinha.models import Route, RouteRules

NOV, DEC, JAN = date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1)


def route(origin, destination, *, status="active", pax=None):
    return Route(origin, destination, destination, "europe", RouteRules(), status=status,
                 demand_pax_month=pax, demand_period="2026-06" if pax else None)


ROUTES = [route("LIS", "LON", pax=50_000), route("OPO", "PAR", pax=80_000), route("LIS", "MIL"),
          route("LIS", "BER", status="dormant")]
SEEN = [("LIS", "LON", "STN", 78), ("OPO", "PAR", "BVA", 151), ("LIS", "MIL", "BGY", 61),
        ("LIS", "MIL", "MXP", 9), ("LIS", "BER", "BER", 83), ("LIS", "LON", None, 5),
        ("LIS", "XXX", "XXX", 99)]


def test_pairs_are_active_routes_only_busiest_first():
    got = hotlist.pairs(ROUTES, SEEN)
    # demand rank first (OPO-PAR 80k, LIS-LON 50k), routes without a figure after, by offers seen
    assert [p.key for p in got] == [("OPO", "PAR", "BVA"), ("LIS", "LON", "STN"),
                                     ("LIS", "MIL", "BGY"), ("LIS", "MIL", "MXP")]
    assert all(p.route.status == "active" for p in got)   # the dormant route and the unknown one left


def test_plan_asks_open_promotions_first_then_rotates_within_the_limit():
    known = hotlist.pairs(ROUTES, SEEN)
    months = (NOV, DEC, JAN)
    first = hotlist.plan(known, months=months, deal_trips=[("LIS", "MIL", "BGY", JAN)],
                         cursor=0, limit=4)
    assert first.n_deal_tasks == 1 and first.tasks[0][0].key == ("LIS", "MIL", "BGY")
    assert first.tasks[0][1] == JAN
    # three rotation tasks follow: the busiest pair's months
    assert [(t[0].key, t[1]) for t in first.tasks[1:]] == [
        (("OPO", "PAR", "BVA"), NOV), (("OPO", "PAR", "BVA"), DEC), (("OPO", "PAR", "BVA"), JAN)]
    assert first.cursor == 3 and first.n_pairs == 4 and first.n_months == 3
    assert first.describe() == "3 of 12 pair-months in rotation + 1 for open promotions"

    second = hotlist.plan(known, months=months, deal_trips=[], cursor=first.cursor, limit=4)
    assert [(t[0].key, t[1]) for t in second.tasks] == [
        (("LIS", "LON", "STN"), NOV), (("LIS", "LON", "STN"), DEC), (("LIS", "LON", "STN"), JAN),
        (("LIS", "MIL", "BGY"), NOV)]
    assert second.cursor == 7


def test_rotation_wraps_around_and_skips_tasks_already_asked_for_promotions():
    known = hotlist.pairs(ROUTES, SEEN)
    got = hotlist.plan(known, months=(NOV,), deal_trips=[("OPO", "PAR", "BVA", NOV)],
                       cursor=3, limit=3)
    # cursor 3 of 4 pairs: the last pair, then wrap to the first (already asked for the
    # promotion: skipped), then the second
    assert [(t[0].key, t[1]) for t in got.tasks] == [
        (("OPO", "PAR", "BVA"), NOV), (("LIS", "MIL", "MXP"), NOV), (("LIS", "LON", "STN"), NOV)]
    assert got.cursor == 2


def test_unknown_trips_and_empty_inputs_are_harmless():
    known = hotlist.pairs(ROUTES, SEEN)
    got = hotlist.plan(known, months=(NOV,), deal_trips=[("LIS", "LON", None, NOV),
                                                          ("LIS", "ZZZ", "ZZZ", NOV)],
                       cursor=0, limit=1)
    assert got.n_deal_tasks == 0 and len(got.tasks) == 1
    empty = hotlist.plan([], months=(NOV,), deal_trips=[], cursor=5, limit=10)
    assert empty.tasks == () and empty.cursor == 0 and empty.describe() == "0 of 0 pair-months in rotation"
