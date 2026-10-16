"""The day's pass (D42): months 4-6 and the routes that never returned a price, once a Lisbon day.

Through the pipeline seam (`pipeline.run_collect` with the clock passed in) on a mocked API.
"""

import json
from datetime import date, datetime, time, timedelta, timezone

import httpx
import pytest
import respx
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from escapadinha import cli, pipeline, run_path, site_data
from escapadinha.collector.travelpayouts import API_URL
from escapadinha.config import CollectorConfig, Context
from escapadinha.i18n_pt import LISBON
from escapadinha.storage import db
from test_pipeline import EMPTY, ctx  # noqa: F401 (fixture)


def utc(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)


def configure(ctx: Context, **collector) -> Context:
    """Rewrite the temp project's `collector` section; returns a fresh Context."""
    path = ctx.root / "config.yaml"
    data = yaml.safe_load(path.read_text("utf-8"))
    data["collector"].update(collector)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), "utf-8")
    return Context(root=ctx.root)


def offer(params) -> dict:
    """One nonstop round trip departing on the 10th of the asked month (synthetic, test data)."""
    year, month = map(int, params["departure_at"].split("-"))
    o, d = params["origin"], params["destination"]
    return {"success": True, "currency": "eur", "data": [{
        "origin": o, "destination": d, "origin_airport": o, "destination_airport": d,
        "price": 80, "airline": "TP", "flight_number": "1",
        "departure_at": f"{year}-{month:02d}-10T08:00:00+00:00",
        "return_at": f"{year}-{month:02d}-14T18:00:00+00:00",
        "transfers": 0, "return_transfers": 0,
        "link": f"/search/{o}10{month:02d}{d}14{month:02d}1?t=x&search_date=14102026"}]}


def api(answer=offer):
    """Every route answers with `answer(params)`; returns the mock, to read the asked months."""
    return respx.get(API_URL).mock(side_effect=lambda r: httpx.Response(200, json=answer(r.url.params)))


def test_far_months_start_after_every_runs_months_and_open_promotions_count_them():
    """One place says where the far months begin (month `months_ahead` + 1): the plan asks them
    on the day's pass, and the site reads them from it (`pipeline.latest_offers`)."""
    from escapadinha.collector import plan
    from escapadinha.models import Route, RouteRules
    assert plan.first_far_month(date(2026, 10, 16), 3) == date(2027, 1, 1)
    assert plan.first_far_month(date(2026, 12, 31), 3) == date(2027, 3, 1)
    route = Route(origin="LIS", destination="LON", city_pt="Londres", kind="europe",
                  rules=RouteRules(), last_observed_at=utc(10, 15, 3))
    regular = plan.plan([route], today=date(2026, 10, 16), daily=False, months_ahead=3,
                        daily_months_ahead=6,
                        deal_months=[("LIS-LON", date(2027, 2, 1)), ("LIS-LON", date(2026, 12, 1))])
    assert [m for _, m in regular.tasks][-1] == date(2027, 2, 1)
    assert regular.n_far_deal_months == 1          # December is asked on every run anyway
    assert regular.describe() == "regular pass: months 1–3 of 1 route + 1 far month of open promotions"


def test_the_daily_pass_asks_at_least_every_runs_months():
    with pytest.raises(ValidationError, match="daily_months_ahead"):
        CollectorConfig(months_ahead=4, daily_months_ahead=3)
    with pytest.raises(ValidationError):
        CollectorConfig(daily_pass_hour=24)


@respx.mock
def test_the_first_run_after_the_hour_each_lisbon_day_is_the_daily_pass(ctx):
    ctx = configure(ctx, months_ahead=3, daily_months_ahead=6, daily_pass_hour=6)
    conn = pipeline.open_db(ctx)
    api()
    runs = [pipeline.run_collect(ctx, conn, now=t) for t in (
        utc(10, 15, 3),         # 04:00 Lisbon (summer time): no pass yet, so this run is one
        utc(10, 15, 7),         # 08:00: the day already had its pass
        utc(10, 15, 23, 30),    # 00:30 on the 16th in Lisbon, still the 15th in UTC: before 06:00
        utc(10, 16, 4, 59),     # 05:59 Lisbon
        utc(10, 16, 5),         # 06:00 Lisbon: the 16th's pass
        utc(10, 16, 9),
    )]
    assert [r.plan.daily for r in runs] == [True, False, False, False, True, False]
    assert [r.n_requests for r in runs] == [60, 30, 30, 30, 60, 30]    # 10 routes × 6 or 3 months


@respx.mock
def test_never_seen_routes_wait_for_the_daily_pass_until_their_first_price(ctx):
    ctx = configure(ctx, months_ahead=3, daily_months_ahead=6, daily_pass_hour=6)
    conn = pipeline.open_db(ctx)
    answering = {"LIS-LON"}
    mock = api(lambda p: offer(p) if f"{p['origin']}-{p['destination']}" in answering else EMPTY)

    def run(now):
        before = len(mock.calls)
        summary = pipeline.run_collect(ctx, conn, now=now)
        asked = {f"{c.request.url.params['origin']}-{c.request.url.params['destination']}"
                 for c in list(mock.calls)[before:]}
        return summary, asked

    daily, asked = run(utc(10, 15, 3))
    assert daily.plan.daily and daily.n_requests == 60 and len(asked) == 10
    regular, asked = run(utc(10, 15, 7))
    assert asked == {"LIS-LON"} and regular.n_requests == 3
    assert len(regular.plan.waiting) == 9 and "OPO-PAR" in {r.key for r in regular.plan.waiting}

    answering.add("OPO-PAR")                # the cache now has a price for it: not asked yet
    _, asked = run(utc(10, 15, 9))
    assert asked == {"LIS-LON"}
    daily, asked = run(utc(10, 16, 5))      # the 16th's pass asks every route and finds it
    assert len(asked) == 10
    regular, asked = run(utc(10, 16, 9))    # from then on, every run asks for it
    assert asked == {"LIS-LON", "OPO-PAR"} and regular.n_requests == 6
    assert len(regular.plan.waiting) == 8


@respx.mock
def test_every_run_asks_for_the_far_month_of_an_open_promotion_so_its_recheck_holds(ctx):
    """A candidate from a far month (found on the day's pass) is rechecked on every run: the
    runs in between ask for its route-month too, never judge it on prices they didn't ask for."""
    ctx = configure(ctx, months_ahead=3, daily_months_ahead=6, daily_pass_hour=6)
    conn = pipeline.open_db(ctx)
    mock = api(lambda p: offer(p) if p["destination"] == "LON" and p["origin"] == "LIS" else EMPTY)
    pipeline.run_collect(ctx, conn, now=utc(10, 15, 3))          # the day's pass: Oct → Mar
    far = next(o for o in db.observations_seen_since(conn, db.latest_completed_run_id(conn))
               if o.departure_date == date(2027, 2, 10))
    deal_id = db.insert_deal(conn, observation_id=far.id, rule="median", baseline_median=130,
                             sample_size=10, discount_pct=0.38, threshold=0.30)

    before = len(mock.calls)
    regular = pipeline.run_collect(ctx, conn, now=utc(10, 15, 7))
    asked = sorted(c.request.url.params["departure_at"] for c in list(mock.calls)[before:])
    assert not regular.plan.daily and regular.n_requests == 4
    assert asked == ["2026-10", "2026-11", "2026-12", "2027-02"]
    [(deal, _, check)] = pipeline.run_recheck(ctx, conn, now=utc(10, 15, 7, 5))
    assert deal.id == deal_id and check.valid and deal.status == "new"


@respx.mock
def test_the_run_log_says_which_pass_ran_and_how_many_requests_it_made(ctx, monkeypatch):
    ctx = configure(ctx, months_ahead=3, daily_months_ahead=6, daily_pass_hour=6)
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    monkeypatch.setenv("COLUMNS", "300")
    api(lambda p: offer(p) if p["destination"] == "LON" and p["origin"] == "LIS" else EMPTY)
    first = CliRunner().invoke(cli.app, ["collect"]).output    # no pass yet: this run is one
    assert "daily pass: months 1–6 of 10 routes · 60 requests" in first
    second = CliRunner().invoke(cli.app, ["collect"]).output
    assert ("regular pass: months 1–3 of 1 route; 9 never-seen routes wait for the daily pass"
            " · 3 requests") in second


@respx.mock
def test_a_reactivated_route_never_seen_is_probed_by_the_daily_pass_before_it_sleeps_again(ctx):
    """Dormancy (D23) unchanged: after 30 days without a price a route sleeps, and a discovery
    that finds it again gives it a probe. For a never-seen route that probe is the next daily
    pass: a run that doesn't ask for it can't put it back to sleep."""
    ctx = configure(ctx, months_ahead=3, daily_months_ahead=6, daily_pass_hour=6)
    conn = pipeline.open_db(ctx)                 # routes discovered now (the real clock)
    api(lambda p: offer(p) if p["destination"] == "LON" and p["origin"] == "LIS" else EMPTY)
    day = (db.utcnow() + timedelta(days=31)).astimezone(LISBON).date()

    def lisbon(d, hour):
        return datetime.combine(d, time(hour), tzinfo=LISBON)

    def run(now):
        summary = pipeline.run_collect(ctx, conn, now=now)
        return {r.key for r in pipeline.run_dormancy(ctx, conn, summary, now)}

    assert "OPO-PAR" in run(lisbon(day, 4))                # probed by a pass, no price in 31 days
    db.set_route_status(conn, [("OPO", "PAR")], "active")   # as a discovery that finds it again
    assert run(lisbon(day, 9)) == set()                     # not asked: not judged
    assert pipeline.route_for(ctx, conn, "OPO-PAR").status == "active"
    assert run(lisbon(day + timedelta(days=1), 7)) == {"OPO-PAR"}   # the pass probed it


@respx.mock
def test_the_site_shows_the_far_months_of_the_last_daily_pass_until_the_next_one(ctx):
    """The newest prices of a far month are those of the latest daily pass: a run in between
    neither drops them from the site nor changes what the site shows (no extra full path)."""
    ctx = configure(ctx, months_ahead=3, daily_months_ahead=6, daily_pass_hour=6)
    conn = pipeline.open_db(ctx)
    api(lambda p: offer(p) if p["destination"] == "LON" and p["origin"] == "LIS" else EMPTY)

    def lis_lon(now):
        files = site_data.build_export(ctx, conn, now, new_links=False).files
        route = next(r for r in files["routes.json"]["routes"] if r["key"] == "LIS-LON")
        return [day["dep"][:7] for day in route["calendar"]], run_path.site_data_digest(ctx, conn, now)

    pipeline.run_collect(ctx, conn, now=utc(10, 15, 3))     # the day's pass: Oct → Mar
    after_pass, shown = lis_lon(utc(10, 15, 3, 5))
    assert after_pass == ["2026-11", "2026-12", "2027-01", "2027-02", "2027-03"]   # Oct 10 is past
    pipeline.run_collect(ctx, conn, now=utc(10, 15, 7))     # Oct → Dec only
    assert lis_lon(utc(10, 15, 7, 5)) == (after_pass, shown)


# --- the run log's warning when the day's pass went missing ---------------------------------

def recorded_pass(conn, started: datetime) -> int:
    """A daily pass as `run_collect` records it: its run and meta `collector.daily_pass`."""
    cur = conn.execute("INSERT INTO fetch_runs (source, started_at, scope, status) "
                       "VALUES ('travelpayouts', ?, 'full', 'ok')", (started.isoformat(),))
    day = started.astimezone(LISBON).date().isoformat()
    db.set_meta(conn, pipeline.DAILY_PASS, json.dumps({"day": day, "run": cur.lastrowid}))
    return cur.lastrowid


def test_no_warning_without_a_recorded_pass_or_within_30_hours(ctx):
    conn = pipeline.open_db(ctx)
    now = utc(10, 16, 12)
    assert pipeline.missed_daily_pass_warning(ctx, conn, now) is None   # the next run is the pass
    recorded_pass(conn, now - timedelta(hours=30))      # yesterday's 07:00, today's still to come
    assert pipeline.missed_daily_pass_warning(ctx, conn, now) is None


def test_a_last_daily_pass_more_than_30_hours_old_is_a_warning(ctx):
    """The day's pass (months 4-6, never-seen routes) went missing: no run after 06:00 Lisbon
    recorded one, e.g. every request of it failed."""
    ctx = configure(ctx, months_ahead=3, daily_months_ahead=6, daily_pass_hour=6)
    conn = pipeline.open_db(ctx)
    run_id = recorded_pass(conn, utc(10, 15, 5, 17))    # 06:17 Lisbon on the 15th
    assert pipeline.missed_daily_pass_warning(ctx, conn, utc(10, 16, 11, 22)) == (
        f"the last daily pass (#{run_id}, 2026-10-15) started 30 h 05 min ago, more than 30 h: "
        "months 4–6 and the never-seen routes were not asked since. A pass where every request "
        "failed is not recorded: check the runs after 06:00 Lisbon (D42).")
