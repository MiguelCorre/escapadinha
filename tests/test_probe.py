"""The browser probe on the PC (D48): what it searches, how it reads Google Flights' texts, what
it writes, how the pipeline imports it as a comparison source that never becomes a deal."""

import json
import random
from datetime import date, datetime, timedelta, timezone

import respx

from escapadinha import pipeline, review_snapshot, site_data
from escapadinha.models import Observation
from escapadinha.probe import google_flights as gf
from escapadinha.probe import results, runner, wanted
from escapadinha.storage import db
from escapadinha.storage.objects import LocalObjectStore
from test_pipeline import ctx, mock_api, seed_history  # noqa: F401

NOW = datetime(2026, 10, 24, 16, 30, tzinfo=timezone.utc)
# Rows as Google Flights' results list shows them (read on 2026-10-24 from this PC).
ROW_CHEAP = "3:10 PM\n – \n6:00 PM\nRyanair\n2 hr 50 min\nLIS–STN\nNonstop\n137 kg CO2e\nAvg emissions\n€65\nround trip"
ROW_OPERATED = "5:30 PM\n – \n8:20 PM\nRyanairOperated by Malta Air\n2 hr 50 min\nLIS–STN\nNonstop\n137 kg CO2e\nAvg emissions\n€68\nround trip"
ROW_STOP = "7:00 AM\n – \n1:15 PM\nTAP Air Portugal\n5 hr 15 min\nLIS–LHR\n1 stop\n200 kg CO2e\n+20% emissions\n€59\nround trip"
ROW_RETURN = "6:20 AM\n – \n9:10 AM\nRyanair\n2 hr 50 min\nSTN–LIS\nNonstop\n137 kg CO2e\nAvg emissions\n€65\nround trip"
BOOK_AIRLINE = "Continue to book with Ryanair airline for 65 euros"
BOOK_OTA = "Continue to book with eDreams online travel agency for 1,062 euros"


def obs(origin="LIS", destination="LON", airport="STN", dep=date(2026, 11, 19), nights=3,
        price=70.0, source="travelpayouts", airline="FR", oid=None, transfers=0, found=None):
    return Observation(source=source, origin=origin, destination=destination, origin_airport=origin,
                       destination_airport=airport, departure_date=dep,
                       return_date=dep + timedelta(days=nights), price=price, currency="EUR",
                       airline=airline, flight_number="1", transfers=transfers,
                       return_transfers=transfers, deep_link="https://www.aviasales.pt/search/x",
                       fetched_at=NOW, raw_json="{}", id=oid, found_date=found or NOW.date())


# --- wanted --------------------------------------------------------------------------------

def test_wanted_lists_open_promotions_first_then_rotates_the_cheapest_offers():
    promos = [(7, obs(oid=1)), (8, obs(destination="PAR", airport="BVA", oid=2))]
    cheapest = [obs(oid=1), obs(destination="ROM", airport="FCO", oid=3), obs(destination="BCN", oid=4)]
    first = wanted.plan(promos, cheapest, cursor=0, limit=3)
    assert [t.reason for t in first.trips] == ["promotion", "promotion", "low"]
    assert first.trips[0].deal_id == 7 and first.trips[2].destination == "ROM"   # LIS-LON already in
    assert first.cursor == 4 and first.n_promotions == 2          # 2 promotions + LON (dup) + ROM
    assert first.describe() == "3 trips (2 open promotions first)"
    second = wanted.plan(promos, cheapest, cursor=first.cursor, limit=2)
    assert [t.destination for t in second.trips] == ["BCN", "LON"] and second.cursor == 1
    assert second.n_promotions == 1 and second.describe() == "2 trips (1 open promotions first)"
    # more promotions than the limit: they rotate too, so each gets its turn
    many = [(i, obs(destination=f"X{i:02d}", oid=100 + i)) for i in range(5)]
    a = wanted.plan(many, [], cursor=0, limit=2)
    b = wanted.plan(many, [], cursor=a.cursor, limit=2)
    c = wanted.plan(many, [], cursor=b.cursor, limit=2)
    assert [t.deal_id for t in a.trips] == [0, 1] and [t.deal_id for t in b.trips] == [2, 3]
    assert [t.deal_id for t in c.trips] == [4, 0] and c.cursor == 1
    doc = wanted.to_json(first, generated_at=NOW, run_id=5)
    back = wanted.from_json(json.loads(json.dumps(doc)))
    assert back == list(first.trips) and doc["run"] == 5 and doc["version"] == 1


# --- parsers --------------------------------------------------------------------------------

def test_parse_result_reads_the_row_as_shown_and_never_guesses():
    r = gf.parse_result(ROW_CHEAP)
    assert (r.price, r.airline, r.nonstop, r.departs, r.arrives) == (65.0, "Ryanair", True, "3:10 PM", "6:00 PM")
    assert gf.parse_result(ROW_OPERATED).airline == "Ryanair"           # operating carrier dropped
    stop = gf.parse_result(ROW_STOP)
    assert stop.nonstop is False and stop.airline == "TAP Air Portugal" and stop.price == 59.0
    assert gf.parse_result("Sort by\nBest") is None                     # no price: not a row
    assert gf.parse_result("€\nround trip") is None
    assert gf.cheapest_nonstop([ROW_STOP, ROW_OPERATED, ROW_CHEAP]) == (2, gf.parse_result(ROW_CHEAP))
    assert gf.cheapest_nonstop([ROW_STOP]) is None


def test_parse_booking_and_airline_codes():
    assert gf.parse_booking(BOOK_AIRLINE) == gf.Option("Ryanair", "airline", 65.0)
    assert gf.parse_booking(BOOK_OTA) == gf.Option("eDreams", "online travel agency", 1062.0)
    assert gf.parse_booking("Track prices for selected flights") is None
    assert gf.airline_code("Ryanair") == "FR" and gf.airline_code("TAP Air Portugal") == "TP"
    assert gf.airline_code("easyJet") in ("U2", "EC") and gf.airline_code("Nobody Air") is None
    assert gf.airline_code(None) is None


def test_search_url_and_wall_reasons():
    url = gf.search_url("LIS", "STN", date(2026, 11, 19), date(2026, 11, 22))
    assert url.startswith("https://www.google.com/travel/flights?q=Flights%20from%20LIS%20to%20STN")
    assert "hl=en" in url and "curr=EUR" in url and "gl=PT" in url and "nonstop" in url
    assert gf.wall_reason("https://consent.google.com/m?continue=x", "Before you continue", "") == "consent"
    assert gf.wall_reason("https://www.google.com/sorry/index?x", "", "") == "unusual_traffic"
    assert gf.wall_reason("https://www.google.com/travel/flights", "", "Our systems have detected unusual traffic") == "unusual_traffic"
    assert gf.wall_reason("https://x", "", "please confirm you're not a robot (reCAPTCHA)") == "captcha"
    assert gf.wall_reason("https://www.google.com/travel/flights?q=x", "Lisbon to London | Google Flights", "€65 round trip") is None


class FakeFlights:
    """A scripted browser: the pages a search visits, in order."""

    def __init__(self, outbound, inbound, labels, *, wall_at: str | None = None):
        self.outbound, self.inbound, self.labels, self.wall_at = outbound, inbound, labels, wall_at
        self.step = "start"
        self.log: list[str] = []
        self.closed = False

    def _view(self, name):
        if self.wall_at == name:
            return gf.View("https://www.google.com/sorry/index", "Sorry", "unusual traffic")
        return gf.View("https://www.google.com/travel/flights?q=x", "Lisbon to London", "ok")

    def open(self, url):
        self.log.append(f"open {url[:40]}")
        self.step = "outbound"
        return self._view("open")

    def rows(self):
        return self.outbound if self.step == "outbound" else self.inbound

    def click_row(self, index):
        self.log.append(f"click {self.step} {index}")
        self.step = "inbound" if self.step == "outbound" else "booking"
        return self._view(self.step)

    def expand_options(self):
        self.log.append("expand")

    def booking_labels(self):
        return self.labels

    def pause(self, seconds):
        self.log.append(f"pause {seconds:.0f}")

    def close(self):
        self.closed = True


def test_search_picks_the_cheapest_nonstop_legs_and_reads_the_sellers():
    fake = FakeFlights([ROW_STOP, ROW_OPERATED, ROW_CHEAP], [ROW_RETURN], [BOOK_OTA, BOOK_AIRLINE, "Track prices"])
    found = gf.search(fake, "LIS", "STN", date(2026, 11, 19), date(2026, 11, 22), rng=random.Random(1))
    assert found.outcome == "ok" and found.price == 65.0
    assert found.outbound.price == 65.0 and found.inbound.departs == "6:20 AM"
    assert [(o.seller, o.price) for o in found.options] == [("eDreams", 1062.0), ("Ryanair", 65.0)]
    assert fake.log[0].startswith("open https://www.google.com/travel/flights") and fake.log[1].startswith("pause ")
    assert "click outbound 2" in fake.log and "click inbound 0" in fake.log and "expand" in fake.log


def test_search_reports_what_it_could_not_find_and_stops_at_a_wall():
    assert gf.search(FakeFlights([], [], []), "LIS", "STN", date(2026, 11, 19), date(2026, 11, 22)).outcome == "no_results"
    assert gf.search(FakeFlights([ROW_STOP], [], []), "LIS", "STN", date(2026, 11, 19), date(2026, 11, 22)).outcome == "no_nonstop"
    assert gf.search(FakeFlights([ROW_CHEAP], [], []), "LIS", "STN", date(2026, 11, 19), date(2026, 11, 22)).outcome == "no_return"
    assert gf.search(FakeFlights([ROW_CHEAP], [ROW_RETURN], []), "LIS", "STN", date(2026, 11, 19), date(2026, 11, 22)).outcome == "no_options"
    try:
        gf.search(FakeFlights([ROW_CHEAP], [ROW_RETURN], [], wall_at="inbound"), "LIS", "STN", date(2026, 11, 19), date(2026, 11, 22))
    except gf.Wall as wall:
        assert wall.reason == "unusual_traffic"
    else:
        raise AssertionError("a wall must stop the search")


# --- results and the runner ----------------------------------------------------------------

def trip():
    return wanted.Trip("LIS", "LON", "STN", date(2026, 11, 19), date(2026, 11, 22), "promotion", 7, 1)


def test_results_become_observations_per_seller_without_links():
    found = gf.Search("https://g/x", gf.parse_result(ROW_CHEAP), gf.parse_result(ROW_RETURN),
                      (gf.Option("Ryanair", "airline", 65.0), gf.Option("eDreams", "online travel agency", 1062.0)), "ok")
    doc = results.document([results.record(trip(), found, NOW),
                            results.record(trip(), gf.Search("https://g/y", None, None, (), "no_results"), NOW)],
                           engine="google_flights", started_at=NOW, finished_at=NOW, stopped=None,
                           wanted_generated_at=None)
    got = results.to_observations(json.loads(results.dumps(doc)))
    assert (got.records, got.searches_ok) == (2, 1)
    assert [(o.gate, o.price) for o in got.observations] == [("Ryanair", 65.0), ("eDreams", 1062.0)]
    o = got.observations[0]
    assert (o.source, o.origin, o.destination, o.destination_airport) == ("google_flights", "LIS", "LON", "STN")
    assert (o.departure_date, o.return_date, o.airline, o.deep_link) == (date(2026, 11, 19), date(2026, 11, 22), "FR", None)
    assert o.found_at == NOW and o.fetched_at == NOW and (o.transfers, o.return_transfers) == (0, 0)
    assert json.loads(o.raw_json)["outbound"].startswith("3:10 PM")
    assert o.dedup_key != got.observations[1].dedup_key


def test_runner_writes_one_results_file_and_its_state(tmp_path):
    store = LocalObjectStore(tmp_path / "objects")
    plan = wanted.plan([(7, obs(oid=1))], [obs(destination="ROM", airport="FCO", oid=3)], cursor=0, limit=5)
    store.put(wanted.KEY, json.dumps(wanted.to_json(plan, generated_at=NOW, run_id=9)).encode())
    fakes = []

    def open_flights():
        fakes.append(FakeFlights([ROW_CHEAP], [ROW_RETURN], [BOOK_AIRLINE]))
        return fakes[-1]
    clock = iter(NOW + timedelta(minutes=m) for m in range(1, 10))
    summary = runner.run(store, open_flights, now=NOW, limit=10, pause=(20, 45), paused_hours=24,
                         rng=random.Random(2), clock=lambda: next(clock))
    assert summary.status == "ok" and (summary.trips, summary.searched, summary.with_options) == (2, 2, 2)
    assert summary.describe() == "probe: ok, 2 of 2 trips searched, 2 with booking options"
    assert fakes[0].closed and any(log.startswith("pause 2") or log.startswith("pause 3") or log.startswith("pause 4") for log in fakes[0].log)
    [key] = store.list(results.RESULTS_PREFIX)
    assert key == summary.results_key and key.startswith("probe/results/20261024T16")
    doc = json.loads(store.get(key))
    assert doc["engine"] == "google_flights" and doc["stopped"] is None and len(doc["records"]) == 2
    assert doc["records"][0]["trip"]["deal_id"] == 7 and doc["records"][0]["options"][0]["seller"] == "Ryanair"
    state = runner.read_state(store)
    assert state["last_trips"] == 2 and state["last_results"] == key and "paused_until" not in state
    # nothing to search: no browser is opened
    store.put(wanted.KEY, json.dumps(wanted.to_json(wanted.plan([], [], cursor=0, limit=5), generated_at=NOW, run_id=9)).encode())
    assert runner.run(store, open_flights, now=NOW, limit=10, pause=(0, 0), paused_hours=24).status == "empty"
    assert len(fakes) == 1
    assert runner.run(store, open_flights, now=NOW, limit=10, pause=(0, 0), paused_hours=24, enabled=False).status == "disabled"


def test_a_wall_ends_the_run_keeps_what_was_read_and_pauses_the_probe(tmp_path):
    store = LocalObjectStore(tmp_path / "objects")
    plan = wanted.plan([(7, obs(oid=1)), (8, obs(destination="PAR", airport="BVA", oid=2))], [], cursor=0, limit=5)
    store.put(wanted.KEY, json.dumps(wanted.to_json(plan, generated_at=NOW, run_id=9)).encode())
    calls = []

    def open_flights():
        fake = FakeFlights([ROW_CHEAP], [ROW_RETURN], [BOOK_AIRLINE], wall_at=None)
        calls.append(fake)
        # the second trip hits a wall when its results page opens
        original = fake.open

        def open_(url):
            if "BVA" in url:
                fake.wall_at = "open"
            return original(url)
        fake.open = open_
        return fake
    summary = runner.run(store, open_flights, now=NOW, limit=10, pause=(0, 0), paused_hours=24,
                         rng=random.Random(3))
    assert summary.status == "wall" and summary.reason == "unusual_traffic"
    assert (summary.searched, summary.with_options) == (1, 1) and calls[0].closed
    assert "paused until 2026-10-25 16:30 UTC" in summary.describe()
    doc = json.loads(store.get(summary.results_key))
    assert doc["stopped"] == "unusual_traffic" and len(doc["records"]) == 1
    state = runner.read_state(store)
    assert state["reason"] == "unusual_traffic" and runner.paused_until(state, NOW) == NOW + timedelta(hours=24)
    again = runner.run(store, open_flights, now=NOW + timedelta(hours=1), limit=10, pause=(0, 0), paused_hours=24)
    assert again.status == "paused" and len(calls) == 1
    later = runner.run(store, open_flights, now=NOW + timedelta(hours=25), limit=10, pause=(0, 0), paused_hours=24)
    assert later.status in ("ok", "partial", "wall") and len(calls) == 2


# --- the pipeline side -----------------------------------------------------------------------

@respx.mock
def test_the_pipeline_lists_trips_for_the_probe_and_imports_its_results_as_a_comparison(ctx):
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    mock_api()
    pipeline.run_collect(ctx, conn)
    pipeline.run_detect(ctx, conn)                       # the 58 € LIS-LON offer becomes a deal
    [(deal, deal_obs)] = db.deals_with_status(conn, "new")

    listed = pipeline.run_probe_wanted(ctx, conn)
    assert listed.promotions == 1 and listed.trips >= 1 and listed.key == "probe/wanted.json"
    doc = json.loads(ctx.object_store.get("probe/wanted.json"))
    first = doc["trips"][0]
    assert (first["reason"], first["deal_id"], first["origin"], first["destination"]) == ("promotion", deal.id, "LIS", "LON")
    assert (first["departure"], first["return_date"]) == (deal_obs.departure_date.isoformat(), deal_obs.return_date.isoformat())
    assert db.get_meta_json(conn, "probe.cursor")["cursor"] >= 0
    assert "Probe list:" in listed.describe()

    # The probe answers with two sellers for the promotion's trip and a cheaper one for a trip
    # nobody else saw: the import stores them as google_flights offers under one run row.
    t = wanted.Trip.from_json(first)
    found = gf.Search("https://g/x", gf.parse_result(ROW_CHEAP), gf.parse_result(ROW_RETURN),
                      (gf.Option("Ryanair", "airline", 57.0), gf.Option("eDreams", "online travel agency", 55.0)), "ok")
    other = wanted.Trip("LIS", "LON", "LGW", date(2026, 11, 25), date(2026, 11, 28), "low")
    cheap = gf.Search("https://g/y", gf.parse_result(ROW_CHEAP), gf.parse_result(ROW_RETURN),
                      (gf.Option("Kiwi.com", "online travel agency", 20.0),), "ok")
    at = db.utcnow()
    body = results.dumps(results.document([results.record(t, found, at), results.record(other, cheap, at)],
                                          engine="google_flights", started_at=at, finished_at=at,
                                          stopped=None, wanted_generated_at=doc["generated_at"]))
    ctx.object_store.put(results.results_key(at), body)
    ctx.object_store.put("probe/results/broken.json", b"{not json")
    imported = pipeline.run_probe_import(ctx, conn)
    assert (imported.files, imported.records, imported.searches_ok, imported.observations, imported.n_new) == (2, 2, 2, 3, 3)
    assert imported.errors == ["probe/results/broken.json: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"]
    assert ctx.object_store.list("probe/results/") == ["probe/results/broken.json"]   # imported ones archived and removed
    row = conn.execute("SELECT source, scope, status, archive_key FROM fetch_runs WHERE id = ?", (imported.run_id,)).fetchone()
    assert (row["source"], row["scope"], row["status"]) == ("google_flights", "probe", "partial") and row["archive_key"]
    stored = [o for o in db.observations_seen_since(conn, imported.run_id) if o.source == "google_flights"]
    assert sorted((o.gate, o.price) for o in stored) == [("Kiwi.com", 20.0), ("Ryanair", 57.0), ("eDreams", 55.0)]
    assert all(o.deep_link is None for o in stored)

    # A comparison source never becomes a deal or a low price, and is not a route's price...
    run_id, detections = pipeline.run_detect(ctx, conn)
    lon = {r.route: r for r in detections}["LIS-LON"]
    assert lon.deal_ids == [] and lon.low_prices == 1                  # the 20 € Kiwi row is ignored
    export = site_data.build_export(ctx, conn, db.utcnow(), new_links=False)
    lon_route = next(r for r in export.files["routes.json"]["routes"] if r["key"] == "LIS-LON")
    assert lon_route["cheapest"]["price"] != 20 and all(c["price"] != 20 for c in lon_route["calendar"])
    rows = [r for rel, d in export.files.items() if rel.startswith("low-prices/") for r in d["rows"]]
    assert all(db.get_observation(conn, r[0]).source != "google_flights" for r in rows)
    # ... but it is the comparison next to the promotion, cheapest first, each on its observation.
    snap = review_snapshot.build(ctx, conn, db.utcnow())
    mine = next(d for d in snap["queue"] if d["id"] == deal.id)
    assert [(a["label"], a["price_eur"]) for a in mine["also_seen"]] == [("Google Flights via eDreams", 55.0),
                                                                         ("Google Flights via Ryanair", 57.0)]
    assert all(db.get_observation(conn, a["observation_id"]).price == a["price_eur"] for a in mine["also_seen"])
    assert pipeline.run_probe_import(ctx, conn).files == 1                 # only the broken one is left
