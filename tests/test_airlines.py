"""The airlines' own fares next to the cache (D47): the hot list step, the wall that pauses it,
a Ryanair fare that becomes a promotion linked to ryanair.com and rechecked there, and what the
review snapshot and the site export say about it."""

from datetime import date, timedelta

import httpx
import respx

from escapadinha import pipeline, review_snapshot, site_data
from escapadinha.collector import ryanair
from escapadinha.models import Observation
from escapadinha.storage import db
from test_pipeline import ctx, mock_api, seed_history  # noqa: F401
from test_review_events import validate

TRIP = (date(2026, 11, 19), date(2026, 11, 22))


def fare(dep: date, ret: date, price: float, updated_ms: int) -> dict:
    leg = {"departureAirport": {"iataCode": "LIS"}, "arrivalAirport": {"iataCode": "STN"},
           "departureDate": f"{dep}T10:25:00", "arrivalDate": f"{dep}T13:15:00",
           "price": {"value": round(price / 2, 2), "currencyCode": "EUR"},
           "flightNumber": "FR1081", "priceUpdated": updated_ms}
    back = {**leg, "departureAirport": {"iataCode": "STN"}, "arrivalAirport": {"iataCode": "LIS"},
            "departureDate": f"{ret}T06:20:00", "arrivalDate": f"{ret}T09:10:00",
            "flightNumber": "FR1882"}
    return {"outbound": leg, "inbound": back,
            "summary": {"price": {"value": price, "currencyCode": "EUR"}, "tripDurationDays": 3}}


def payload(*fares: dict) -> dict:
    return {"arrivalAirportCategories": None, "fares": list(fares), "nextPage": None, "size": len(fares)}


def mock_ryanair(price: float = 49.99) -> dict:
    """Ryanair's fare finder with one LIS-STN fare in November at `price` (a test may change
    `state["price"]`; `state["calls"]` lists the requests), empty for the other months."""
    state = {"price": price, "calls": []}

    def respond(request):
        state["calls"].append(request)
        month = request.url.params["outboundDepartureDateFrom"][:7]
        updated = int(db.utcnow().timestamp() * 1000)
        fares = [fare(*TRIP, state["price"], updated)] if month == "2026-11" else []
        return httpx.Response(200, json=payload(*fares),
                              headers={"content-type": "application/json;charset=UTF-8"})
    respx.get(ryanair.API_URL).mock(side_effect=respond)
    return state


def cache_offer(conn, price: float, *, airline="FR", airport="STN", source="test",
                trip=TRIP) -> int:
    """One completed run with one LIS-LON offer (test data only): the cache showed a Ryanair
    flight on the pair, so the hot list knows (LIS, LON, STN)."""
    run_id = db.start_run(conn, source if source != "test" else "test")
    db.insert_observations(conn, run_id, [Observation(
        source=source, origin="LIS", destination="LON", origin_airport="LIS",
        destination_airport=airport, departure_date=trip[0], return_date=trip[1], price=price,
        currency="EUR", airline=airline, flight_number="1081", transfers=0, return_transfers=0,
        deep_link="https://www.aviasales.pt/search/LIS1911LON22111" if source != "test" else None,
        fetched_at=db.utcnow(), raw_json="{}", found_date=db.utcnow().date())])
    db.finish_run(conn, run_id, status="ok", n_requests=1, n_observations=1, error=None)
    return run_id


@respx.mock
def test_the_airline_step_asks_the_known_pairs_and_stores_their_offers(ctx):
    conn = pipeline.open_db(ctx)
    cache_offer(conn, 120, trip=(date(2026, 11, 10), date(2026, 11, 13)))   # another trip: the pair
    state = mock_ryanair()
    summary = pipeline.run_airlines(ctx, conn)
    assert (summary.source, summary.status) == ("ryanair", "ok")
    assert summary.n_requests == 3 and summary.plan.describe() == "3 of 3 pair-months in rotation"
    assert (summary.n_observations, summary.n_new) == (1, 1)
    assert "Ryanair: ok, 3 of 3 pair-months in rotation, 3 requests, 1 offers (1 new)" == summary.describe()
    request = state["calls"][0]
    assert request.headers["user-agent"].startswith("pontonomada.pt price check (+https://")
    assert request.url.params["arrivalAirportIataCode"] == "STN"
    assert (request.url.params["durationFrom"], request.url.params["durationTo"]) == ("2", "10")
    stored = [o for o in db.observations_seen_since(conn, summary.run_id) if o.source == "ryanair"]
    assert len(stored) == 1
    o = stored[0]
    assert (o.price, o.airline, o.gate, o.destination_airport) == (49.99, "FR", "Ryanair", "STN")
    assert o.found_at is not None and o.deep_link.startswith("https://www.ryanair.com/pt/pt/trip/")
    row = conn.execute("SELECT source, scope, status, archive_key FROM fetch_runs WHERE id = ?",
                       (summary.run_id,)).fetchone()
    assert (row["source"], row["scope"], row["status"]) == ("ryanair", "airlines", "ok")
    assert row["archive_key"]
    assert db.get_meta_json(conn, "airlines.ryanair.cursor") == {"cursor": 0}   # 3 of 3: wrapped
    # its run is not a collection run: detection and the export still key on the latest `full` one
    assert db.latest_completed_run_id(conn) != summary.run_id
    # the route counts as observed (its last sighting of a price)
    assert conn.execute("SELECT last_observed_at FROM routes WHERE origin='LIS' AND destination='LON'"
                        ).fetchone()[0] is not None


@respx.mock
def test_a_wall_stops_the_pass_and_pauses_the_source(ctx):
    conn = pipeline.open_db(ctx)
    cache_offer(conn, 120, trip=(date(2026, 11, 10), date(2026, 11, 13)))   # another trip: the pair
    wall = respx.get(ryanair.API_URL).mock(return_value=httpx.Response(
        403, text="Access Denied", headers={"content-type": "text/html"}))
    summary = pipeline.run_airlines(ctx, conn)
    assert summary.status == "blocked" and summary.n_requests == 1 and wall.call_count == 1
    assert summary.paused_until is not None and "paused until" in summary.describe()
    assert db.get_meta_json(conn, "airlines.ryanair.blocked")["status"] == 403
    assert conn.execute("SELECT status FROM fetch_runs WHERE id = ?", (summary.run_id,)).fetchone()[0] == "failed"
    again = pipeline.run_airlines(ctx, conn)
    assert again.status == "paused" and again.run_id is None and wall.call_count == 1
    assert again.describe().startswith("Ryanair: paused until ")
    # after `blocked_hours` the source is asked again
    wall.mock(return_value=httpx.Response(200, json=payload(),
                                          headers={"content-type": "application/json"}))
    later = db.utcnow() + timedelta(hours=ctx.config.airlines.ryanair.blocked_hours + 1)
    assert pipeline.run_airlines(ctx, conn, now=later).status == "ok"


def test_off_or_nothing_known_asks_nothing(ctx):
    conn = pipeline.open_db(ctx)
    assert pipeline.run_airlines(ctx, conn).status == "empty"      # no Ryanair offer seen yet
    ctx.config.airlines.ryanair.enabled = False
    assert pipeline.run_airlines(ctx, conn).status == "disabled"


@respx.mock
def test_a_ryanair_fare_becomes_a_deal_linked_to_ryanair_and_rechecked_there(ctx):
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    cache_offer(conn, 120, trip=(date(2026, 11, 10), date(2026, 11, 13)))   # another trip: the pair
    mock_api()
    state = mock_ryanair(49.99)                       # beats the cache's 58 € offer
    collected = pipeline.run_collect(ctx, conn)
    assert pipeline.run_airlines(ctx, conn).n_observations == 1
    run_id, results = pipeline.run_detect(ctx, conn)
    assert run_id == collected.run_id                 # the collection run, not the airline run
    deal_ids = {r.route: r for r in results}["LIS-LON"].deal_ids
    assert len(deal_ids) == 1
    deal, obs = db.get_deal(conn, deal_ids[0])
    assert (obs.source, obs.price, obs.destination_airport) == ("ryanair", 49.99, "STN")

    # The booking link is the airline's own page: no partner API call (none is mocked here).
    pipeline.ensure_affiliate_links(ctx, conn, [(deal, obs)])
    deal = db.get_deal(conn, deal.id)[0]
    assert deal.affiliate_url == obs.deep_link and deal.affiliate_error is None

    # The live check asks Ryanair for the same airport pair and month, never Aviasales.
    before = len(state["calls"])
    check = pipeline.price_now(ctx, conn, deal.id)
    assert check.valid and check.latest_price == 49.99
    assert len(state["calls"]) == before + 1
    assert state["calls"][-1].url.params["arrivalAirportIataCode"] == "STN"
    state["price"] = 80
    check = pipeline.price_now(ctx, conn, deal.id)
    assert not check.valid and "80" in check.reason

    # The run's recheck trusts the deal's own source only: a cheaper Aviasales sighting of the
    # same trip is a comparison, never a confirmation (D13, D47).
    run2 = cache_offer(conn, 45, source="travelpayouts")
    assert pipeline.run_airlines(ctx, conn).n_observations == 1   # Ryanair now says 80 €
    judged = {d.id: r for d, _, r in pipeline.run_recheck(ctx, conn, run_id=run2)}
    assert judged[deal.id].valid is False and "80" in judged[deal.id].reason
    assert db.get_deal(conn, deal.id)[0].status == "expired"


@respx.mock
def test_an_approved_ryanair_promotion_is_exported_with_its_link_kind_and_the_comparison(ctx):
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    cache_offer(conn, 120, trip=(date(2026, 11, 10), date(2026, 11, 13)))   # another trip: the pair
    mock_api()
    mock_ryanair(49.99)
    pipeline.run_collect(ctx, conn)
    pipeline.run_airlines(ctx, conn)
    pipeline.run_detect(ctx, conn)
    deal, obs = next((d, o) for d, o in db.deals_with_status(conn, "new") if o.source == "ryanair")
    cache_offer(conn, 62, source="travelpayouts")     # Aviasales shows the same trip at 62 €
    pipeline.ensure_affiliate_links(ctx, conn, [(deal, obs)])
    db.set_deal_status(conn, deal.id, "rendered")
    pipeline.approve(ctx, conn, deal.id, actor="test")  # the live check at Ryanair passes
    assert db.get_deal(conn, deal.id)[0].status == "approved"

    snap = review_snapshot.build(ctx, conn, db.utcnow())
    validate("snapshot", snap)
    mine = next(d for d in snap["approved"] if d["id"] == deal.id)
    assert (mine["source"], mine["source_label"]) == ("ryanair", "Ryanair")
    assert mine["live_check"]["source"] == "ryanair"
    assert mine["live_check"]["query"]["arrivalAirportIataCode"] == "STN"
    assert [(a["label"], a["price_eur"], a["source"]) for a in mine["also_seen"]] == [("Aviasales", 62, "travelpayouts")]
    assert db.get_observation(conn, mine["also_seen"][0]["observation_id"]).price == 62

    export = site_data.build_export(ctx, conn, db.utcnow(), new_links=False)
    promo = next(p for p in export.files["promotions.json"]["promotions"] if p["id"] == deal.id)
    assert (promo["source"], promo["link_kind"], promo["seller"]) == ("ryanair", "airline", "Ryanair")
    assert promo["booking_link"].startswith("https://www.ryanair.com/pt/pt/trip/flights/select?")
    assert promo["offer"]["price"] == 49.99 and promo["offer"]["arrival_airport"] == "STN"
    seen = promo["also_seen"]
    assert len(seen) == 1 and (seen[0]["source"], seen[0]["label"], seen[0]["eur"]) == ("travelpayouts", "Aviasales", 62)
    assert db.get_observation(conn, seen[0]["obs"]).price == 62
    assert export.files["labels.json"]["disclosure"]["direct"].startswith("Ligação direta ao site da companhia")
    # Ryanair offers are not low-price rows: a row cannot say its link kind yet (D47)
    rows = [r for rel, doc in export.files.items() if rel.startswith("low-prices/") for r in doc["rows"]]
    assert rows and all(db.get_observation(conn, r[0]).source != "ryanair" for r in rows)
