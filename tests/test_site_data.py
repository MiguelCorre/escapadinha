"""Website data contract v1 (D27): the JSON export validates against the schemas in
contract/site/v1, every price in it traces to stored data, the per-origin low-price files
stay inside their size budget, and the committed fixtures validate too."""

from __future__ import annotations

import gzip
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import respx
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from typer.testing import CliRunner

from escapadinha import cli, detector, pipeline, routes, site_data
from escapadinha.models import Photo
from escapadinha.storage import db
from escapadinha.website import build_site
from test_pipeline import ctx, mock_links, seed_history  # noqa: F401
from test_traceability import (
    Refs, build_scenario, cents, history, offer, store_run, untraceable,
)

REPO = Path(__file__).resolve().parents[1]
CONTRACT = REPO / "contract" / "site" / "v1"


def registry() -> Registry:
    resources = []
    for path in sorted(CONTRACT.glob("*.schema.json")):
        schema = json.loads(path.read_text("utf-8"))
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def schema_for(rel: str) -> dict:
    name = "low-prices" if rel.startswith("low-prices/") else rel.removesuffix(".json")
    return json.loads((CONTRACT / f"{name}.schema.json").read_text("utf-8"))


def validation_errors(out: Path) -> list[str]:
    reg, errors = registry(), []
    for path in sorted(out.rglob("*.json")):
        rel = path.relative_to(out).as_posix()
        validator = Draft202012Validator(schema_for(rel), registry=reg)
        errors += [f"{rel} {list(e.absolute_path)}: {e.message}"
                   for e in validator.iter_errors(json.loads(path.read_text("utf-8")))]
    return errors


def read(out: Path, rel: str):
    return json.loads((out / rel).read_text("utf-8"))


@pytest.fixture
def exported(ctx, tmp_path):  # noqa: F811
    """The traceability scenario's database exported (partner links API mocked)."""
    with respx.mock:
        mock_links()
        conn = pipeline.open_db(ctx)
        scenario = build_scenario(ctx, conn)
        out = tmp_path / "site-data"
        summary = site_data.export_site_data(ctx, conn, out)
        yield ctx, conn, scenario, out, summary


def test_export_validates_against_the_v1_schemas(exported):
    ctx, conn, _, out, _ = exported
    meta = read(out, "meta.json")
    assert meta["version"] == 1 and meta["fixture"] is False
    assert meta["run"]["id"] == db.latest_completed_run_id(conn)
    listed = {v for v in meta["files"].values() if isinstance(v, str)}
    listed |= set(meta["files"]["low_prices"].values()) | {"meta.json"}
    assert {p.relative_to(out).as_posix() for p in out.rglob("*.json")} == listed
    assert validation_errors(out) == []


def test_validation_catches_a_broken_document(exported):
    """Guard against a vacuous schema check."""
    _, _, _, out, _ = exported
    doc = read(out, "routes.json")
    doc["routes"][0]["months"].append({"month": "2026-13", "typical_low": -1})
    (out / "routes.json").write_text(json.dumps(doc), "utf-8")
    assert len(validation_errors(out)) >= 2


# --- traceability (D2): every price in the export maps to stored data ------------------------

def price_fields(node, path=""):
    """(path, 'eur' | 'offer') for every price-typed field of a schema (`*` = any element)."""
    if not isinstance(node, dict):
        return
    ref = node.get("$ref", "")
    if ref.endswith("#/$defs/eur"):
        yield path, "eur"
    if ref.endswith("#/$defs/offer"):
        yield path, "offer"
    for key, sub in node.items():
        if key == "properties":
            for name, prop in sub.items():
                yield from price_fields(prop, f"{path}/{name}")
        elif key == "items":
            yield from price_fields(sub, f"{path}/*")
        elif key == "prefixItems":
            for i, item in enumerate(sub):
                yield from price_fields(item, f"{path}/{i}")
        elif key in ("anyOf", "oneOf", "allOf"):
            for item in sub:
                yield from price_fields(item, path)


# What `untraced_prices` checks, per schema. A new price field fails the guard below until
# the checker learns how to trace it.
CHECKED = {
    "defs": set(),
    "routes": {("/routes/*/months/*/typical_low", "eur"), ("/routes/*/months/*/average", "eur"),
               ("/routes/*/cheapest", "offer"), ("/routes/*/calendar/*/price", "eur")},
    "promotions": {("/promotions/*/offer", "offer"), ("/promotions/*/typical_low", "eur"),
                   ("/promotions/*/expired/latest/price", "eur")},
    "low-prices": {("/rows/*/2", "eur"), ("/rows/*/10", "eur")},
}


def test_the_checker_covers_every_price_field_in_the_schemas():
    defs = json.loads((CONTRACT / "defs.schema.json").read_text("utf-8"))["$defs"]
    assert set(price_fields(defs["offer"])) == {("/price", "eur")}   # checked with its `obs`
    for path in sorted(CONTRACT.glob("*.schema.json")):
        name = path.name.removesuffix(".schema.json")
        assert set(price_fields(json.loads(path.read_text("utf-8")))) == CHECKED.get(name, set()), name


def route_lows(ctx, conn, key: str) -> dict[str, set[int]]:
    """'YYYY-MM' -> typical low and plain average (cents) recomputed from stored observations."""
    route = routes.get_route(conn, ctx.config.routes, key)
    history = pipeline.route_history(ctx, conn, route, db.utcnow())
    return {f"{y:04d}-{m:02d}": {cents(b.median), cents(b.mean)}
            for (y, m), b in detector.month_baselines(history, ctx.config.detector, db.utcnow(),
                                                      route.rules).items() if b.median}


def untraced_prices(ctx, conn, out: Path) -> list[str]:
    bad = []

    def offer(where: str, o: dict, route: str) -> None:
        stored = db.get_observation(conn, o["obs"])
        if stored.route_key != route or cents(stored.price) != cents(o["price"]):
            bad.append(f"{where}: {o['price']} (obs {o['obs']})")

    for r in read(out, "routes.json")["routes"]:
        lows = route_lows(ctx, conn, r["key"])
        for m in r["months"]:
            for field in ("typical_low", "average"):
                if m[field] is not None and cents(m[field]) not in lows.get(m["month"], set()):
                    bad.append(f"{r['key']} {m['month']} {field}: {m[field]}")
        if r["cheapest"]:
            offer(f"{r['key']} cheapest", r["cheapest"], r["key"])
        for c in r["calendar"]:
            offer(f"{r['key']} calendar {c['dep']}", c, r["key"])
            stored = db.get_observation(conn, c["obs"])
            if stored.departure_date.isoformat() != c["dep"]:
                bad.append(f"{r['key']} calendar {c['dep']}: obs {c['obs']} departs another day")
    for p in read(out, "promotions.json")["promotions"]:
        deal, obs = db.get_deal(conn, p["id"])
        offer(f"promotion {p['id']}", p["offer"], obs.route_key)
        if p["offer"]["obs"] != obs.id:
            bad.append(f"promotion {p['id']}: offer is not the deal's observation")
        if p["typical_low"] is not None and cents(p["typical_low"]) != cents(deal.baseline_median):
            bad.append(f"promotion {p['id']} typical_low: {p['typical_low']}")
        if p["expired"]:
            if p["expired"]["latest"]:
                offer(f"promotion {p['id']} latest", p["expired"]["latest"], obs.route_key)
            reason = p["expired"]["reason"] or ""
            bad += [f"promotion {p['id']} reason: {s}"
                    for s in untraceable(ctx, conn, reason, Refs(deals={p["id"]}))]
    for path in sorted((out / "low-prices").glob("*.json")):
        doc = read(out, f"low-prices/{path.name}")
        cols = {c: i for i, c in enumerate(doc["cols"])}
        for row in doc["rows"]:
            key = f"{doc['origin']}-{row[cols['dest']]}"
            offer(f"{path.name} row", {"obs": row[cols["obs"]], "price": row[cols["price"]]}, key)
            if cents(row[cols["typical"]]) not in route_lows(ctx, conn, key).get(row[cols["dep"]][:7], set()):
                bad.append(f"{path.name} {key} typical: {row[cols['typical']]}")
    return bad


def test_every_price_in_the_export_traces_to_stored_data(exported):
    ctx, conn, _, out, _ = exported
    assert untraced_prices(ctx, conn, out) == []
    # the check really looked at prices of every kind
    assert read(out, "meta.json")["counts"]["low_prices"] >= 4
    assert len(read(out, "promotions.json")["promotions"]) == 2


def test_the_export_checker_flags_a_fabricated_price(exported):
    ctx, conn, _, out, _ = exported
    doc = read(out, "low-prices/LIS.json")
    doc["rows"][0][2] = 19
    (out / "low-prices/LIS.json").write_text(json.dumps(doc), "utf-8")
    doc = read(out, "routes.json")
    month = next(m for r in doc["routes"] for m in r["months"] if m["typical_low"])
    month["average"] = 12.34
    (out / "routes.json").write_text(json.dumps(doc), "utf-8")
    bad = untraced_prices(ctx, conn, out)
    assert len(bad) == 2 and "19" in bad[0] + bad[1] and "12.34" in bad[0] + bad[1]


# --- what the pages need ------------------------------------------------------------------

def route(out: Path, key: str) -> dict:
    return next(r for r in read(out, "routes.json")["routes"] if r["key"] == key)


def test_routes_carry_typical_lows_averages_status_and_counts(ctx, tmp_path):  # noqa: F811
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)       # LIS-LON daily lows 100/101/102 €
    jan = date(db.utcnow().year + 1, 1, 10)
    store_run(conn, history("LIS", "BCN", [40, 41], jan))         # 2 days: not mature yet
    db.set_route_status(conn, [("OPO", "BER")], "dormant")
    out = tmp_path / "data"
    site_data.export_site_data(ctx, conn, out, new_links=False)

    lon = route(out, "LIS-LON")
    # 22 days older than the freshness window: 8 x 100, 7 x 101, 7 x 102 -> median 101,
    # mean 2221 / 22 = 100,95.
    assert lon["months"] == [{"month": "2026-11", "typical_low": 101, "average": 100.95,
                              "days": 22}]
    assert lon["path"] == "/voos/lisboa-londres/" and lon["kind"] == "europe"
    assert lon["rules"] == {"direct_only": True, "min_nights": 2, "max_nights": 10,
                            "max_transfers": 0}
    assert lon["counts"]["observations"] == 50 and lon["status"] == "active"   # 2 a day
    assert route(out, "LIS-BCN")["months"] == [
        {"month": f"{jan:%Y-%m}", "typical_low": None, "average": None, "days": 2}]
    assert route(out, "OPO-BER")["status"] == "dormant"
    origins = {o["iata"]: o for o in read(out, "origins.json")["origins"]}
    assert list(origins) == ["LIS", "OPO"] and origins["OPO"]["routes"]["dormant"] == 1
    assert origins["LIS"]["name"] == "Lisboa" and origins["LIS"]["slug"] == "lisboa"
    dests = {d["code"]: d for d in read(out, "destinations.json")["destinations"]}
    assert dests["LON"]["routes"] == ["LIS-LON", "OPO-LON"] and dests["LON"]["city"] == "Londres"
    assert validation_errors(out) == []


def test_cheapest_is_the_routes_cheapest_fresh_offer_within_its_rules(exported):
    ctx, conn, s, out, _ = exported
    cheapest = route(out, "LIS-LON")["cheapest"]
    # 50 € has a stop (direct-only route), so 60 € (the live promotion's offer) is cheapest.
    assert cheapest["price"] == 60 and cheapest["obs"] == db.get_deal(conn, s.live_deal)[1].id
    assert cheapest["arrival_airport"] == "LGW" and cheapest["found_date"]
    assert cheapest["fetched_at"].endswith("Z")


def test_promotions_live_and_expired_after_approval(exported):
    ctx, conn, s, out, _ = exported
    promos = {p["id"]: p for p in read(out, "promotions.json")["promotions"]}
    assert set(promos) == {s.live_deal, s.expired_deal}           # never-approved deal left out
    live, expired = promos[s.live_deal], promos[s.expired_deal]
    assert live["live"] and live["status"] == "approved"
    assert live["path"] == f"/promos/{s.live_deal}-lisboa-londres/"
    assert live["offer"]["price"] == 60 and live["typical_low"] == 100.5
    assert live["booking_link"] == db.get_deal(conn, s.live_deal)[0].affiliate_url
    assert live["booking_link"].startswith("https://aviasales.tpo.lu/")
    assert not expired["live"] and expired["booking_link"] is None
    assert expired["expired"]["reason"] == "o preço subiu para 90 €"
    assert expired["expired"]["latest"]["price"] == 90
    assert db.get_observation(conn, expired["expired"]["latest"]["obs"]).price == 90
    assert [p["id"] for p in read(out, "promotions.json")["promotions"]] == [s.live_deal,
                                                                           s.expired_deal]


@pytest.mark.parametrize("post_url, shown", [
    ("https://www.instagram.com/p/C1234/", "https://www.instagram.com/p/C1234/"),
    ("https://instagram.com/p/C1234/", "https://instagram.com/p/C1234/"),
    ("https://t.me/pontonomada/12", None),           # given by hand: not an Instagram post
    (None, None),
])
def test_a_published_promotion_carries_its_instagram_post(exported, tmp_path, post_url, shown):
    """D36: the publisher's permalink reaches the deal through the published event; the page
    links it. Approved promotions have none yet."""
    ctx, conn, s, out, _ = exported
    assert {p["post_url"] for p in read(out, "promotions.json")["promotions"]} == {None}
    conn.execute("UPDATE deals SET status = 'published', published_at = reviewed_at, "
                 "post_url = ? WHERE id = ?", (post_url, s.live_deal))
    conn.commit()
    again = tmp_path / "again"
    site_data.export_site_data(ctx, conn, again, new_links=False)
    promos = {p["id"]: p for p in read(again, "promotions.json")["promotions"]}
    assert promos[s.live_deal]["status"] == "published"
    assert promos[s.live_deal]["post_url"] == shown and promos[s.expired_deal]["post_url"] is None
    assert validation_errors(again) == []


def test_expired_promotions_leave_the_export_after_the_configured_window(exported):
    """`site.expired_promotions_days` (default 30) after it expired; live ones always stay."""
    ctx, conn, s, _, _ = exported
    assert ctx.config.site.expired_promotions_days == 30
    expired_at = db.get_deal(conn, s.expired_deal)[0].last_checked_at

    def exported_ids(days_later: float) -> list[int]:
        export = site_data.build_export(ctx, conn, expired_at + timedelta(days=days_later),
                                        new_links=False)
        route = next(r for r in export.files["routes.json"]["routes"] if r["key"] == "OPO-PAR")
        promos = export.files["promotions.json"]["promotions"]
        assert route["counts"]["promotions_expired"] == sum(not p["live"] for p in promos)
        assert export.counts["promotions_expired"] == sum(not p["live"] for p in promos)
        return [p["id"] for p in promos]

    assert exported_ids(29.9) == [s.live_deal, s.expired_deal]
    assert exported_ids(30.1) == [s.live_deal]
    ctx.config.site.expired_promotions_days = 60
    assert exported_ids(30.1) == [s.live_deal, s.expired_deal]


def test_low_prices_per_origin_with_found_date_and_tracked_links(exported):
    ctx, conn, s, out, _ = exported
    doc = read(out, "low-prices/LIS.json")
    rows = {r[0]: dict(zip(doc["cols"], r)) for r in doc["rows"]}
    # LIS-LON 60 € (the promotion's offer is a low price too), 80 €, 85,40 €; BCN 26 €; ROM 70 €
    assert sorted(r["price"] for r in rows.values()) == [26, 60, 70, 80, 85.4]
    row = rows[s.low_only[1]]
    obs = db.get_observation(conn, s.low_only[1])
    assert row["dest"] == "LON" and row["airport"] == "STN" and row["typical"] == 100.5
    assert row["found"] == obs.found_date.isoformat() and row["stops"] == 0
    assert row["link"] == f"https://aviasales.tpo.lu/site-low-{obs.id}"
    assert [r[3] for r in doc["rows"]] == sorted(r[3] for r in doc["rows"])   # by departure
    assert read(out, "low-prices/OPO.json")["rows"] == []
    text = "".join(p.read_text("utf-8") for p in out.rglob("*.json"))
    assert "marker=" not in text and "aviasales.com/search" not in text   # no hand-built links


@respx.mock
def test_promotion_images_are_the_files_the_site_build_writes(ctx, tmp_path):  # noqa: F811
    from test_website import approved_deal
    conn = pipeline.open_db(ctx)
    deal_id = approved_deal(ctx, conn)
    site_data.export_site_data(ctx, conn, tmp_path / "data")
    [promo] = read(tmp_path / "data", "promotions.json")["promotions"]
    images = promo["images"]
    assert promo["id"] == deal_id and len(images["slides"]) == 3
    build_site(ctx, conn)
    for path in [*images["slides"], images["thumb"], images["og"], promo["path"]]:
        target = ctx.site_dir / path.lstrip("/")
        assert target.is_file() or (target / "index.html").is_file(), path


@respx.mock
def test_without_new_links_the_export_sends_no_partner_request(ctx, tmp_path):  # noqa: F811
    links = mock_links()
    conn = pipeline.open_db(ctx)
    build_scenario(ctx, conn)
    before = links.call_count
    site_data.export_site_data(ctx, conn, tmp_path / "data", new_links=False)
    assert links.call_count == before
    rows = read(tmp_path / "data", "low-prices/LIS.json")["rows"]
    assert rows and all(r[-1] is None for r in rows)
    site_data.export_site_data(ctx, conn, tmp_path / "data")       # creates them, once
    made = links.call_count - before
    assert made == 1 and all(r[-1] for r in read(tmp_path / "data", "low-prices/LIS.json")["rows"])
    build_site(ctx, conn)                                           # the Jinja site reuses them
    assert links.call_count - before == made


@respx.mock
def test_export_and_site_build_share_one_new_link_budget_per_run(ctx, tmp_path):  # noqa: F811
    """`site.max_new_links_per_build` caps a run's export + site build together (D24, D27):
    the export takes the biggest discounts, the build only what is left."""
    links = mock_links()
    conn = pipeline.open_db(ctx)
    build_scenario(ctx, conn)
    ctx.config.site.max_new_links_per_build = 2

    def low_link_requests() -> list[int]:
        return [int(link["sub_id"].removeprefix("site-low-")) for call in links.calls
                for link in json.loads(call.request.content)["links"]
                if link["sub_id"].startswith("site-low-")]

    site_data.export_site_data(ctx, conn, tmp_path / "data")
    run_id = db.latest_completed_run_id(conn)
    by_price = {(o.route_key, o.price): o.id for o in db.observations_seen_since(conn, run_id)}
    # LIS-ROM 70 € (-42 %) and LIS-LON 60 € (-40 %) are the biggest discounts.
    assert sorted(low_link_requests()) == sorted([by_price["LIS-ROM", 70], by_price["LIS-LON", 60]])
    summary = build_site(ctx, conn)
    assert len(low_link_requests()) == 2 and summary["low_price_links_created"] == 0
    site_data.export_site_data(ctx, conn, tmp_path / "data")
    assert len(low_link_requests()) == 2                      # still the same run: spent

    next_run = store_run(conn, db.observations_seen_since(conn, run_id))   # same offers again
    assert db.latest_completed_run_id(conn) == next_run
    site_data.export_site_data(ctx, conn, tmp_path / "data")
    assert len(low_link_requests()) == 4                      # a new run, a new budget


def test_a_month_shows_its_typical_low_only_once_mature(ctx, tmp_path):  # noqa: F811
    """D40: seven daily lows, counting only days that saw two departure dates; the route page
    reads both numbers from meta to say what "ainda sem dados suficientes" means."""
    conn = pipeline.open_db(ctx)
    jan = date(db.utcnow().year + 1, 1, 10)
    one_date = offer("LIS", "BCN", 30, found_ago=11, dep=jan)     # a 7th, cheap day: one date
    store_run(conn, history("LIS", "BCN", [40] * 6, jan) + [one_date]
              + history("LIS", "ROM", [50] * 7, jan))
    out = tmp_path / "data"
    site_data.export_site_data(ctx, conn, out, new_links=False)
    month = f"{jan:%Y-%m}"
    assert route(out, "LIS-BCN")["months"] == [
        {"month": month, "typical_low": None, "average": None, "days": 6}]
    assert route(out, "LIS-ROM")["months"] == [
        {"month": month, "typical_low": 50, "average": 50, "days": 7}]
    det = read(out, "meta.json")["detector"]
    assert (det["min_baseline_days"], det["min_dates_per_day"]) == (7, 2)
    assert validation_errors(out) == []


# --- size budget (D27) --------------------------------------------------------------------

@respx.mock
def test_low_price_files_stay_inside_the_size_budget(ctx, tmp_path):  # noqa: F811
    mock_links()
    conn = pipeline.open_db(ctx)
    jan = date(db.utcnow().year + 1, 1, 10)
    store_run(conn, history("LIS", "LON", [100] * 7, jan))           # typical low 100 € in Jan
    trips = [offer("LIS", "LON", 60 + (day * 9 + n) % 25 + 0.5 * (n % 2), found_ago=n % 3,
                   dep=jan + timedelta(days=day), nights=n)
             for day in range(22) for n in range(2, 11)]                # 198 trips, all -15 %+
    run_id = store_run(conn, trips)
    ctx.config.site.max_low_prices_per_origin = 150
    out = tmp_path / "data"
    now = db.utcnow()          # both exports at the same time: generated_at must not differ
    site_data.export_site_data(ctx, conn, out, now)

    path = out / "low-prices" / "LIS.json"
    doc = read(out, "low-prices/LIS.json")
    assert len(doc["rows"]) == 150 and doc["truncated"] == 48
    kept_ids = {r[0] for r in doc["rows"]}
    run_prices = {o.id: o.price for o in db.observations_seen_since(conn, run_id)}
    cut = [p for oid, p in run_prices.items() if oid not in kept_ids]
    assert len(cut) == 48 and max(run_prices[i] for i in kept_ids) <= min(cut)   # smallest discounts cut
    raw = path.read_bytes()
    assert len(raw) / len(doc["rows"]) <= site_data.ROW_BUDGET_BYTES
    assert len(gzip.compress(raw)) < len(raw) / 3                      # gzip-friendly
    assert raw.count(b"\n") == len(doc["rows"]) + 2                    # one row per line
    site_data.export_site_data(ctx, conn, tmp_path / "again", now)
    assert (tmp_path / "again" / "low-prices" / "LIS.json").read_bytes() == raw   # deterministic
    assert validation_errors(out) == []


# --- CLI and the run -----------------------------------------------------------------------

def test_export_command_writes_the_contract_files(ctx, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    conn.close()
    result = CliRunner().invoke(cli.app, ["export", "site-data", "--no-new-links"])
    assert result.exit_code == 0, result.output
    out = ctx.root / "web" / "src" / "data"                         # site.data_dir
    assert "10 routes" in result.output and str(out) in result.output.replace("\n", "")
    assert read(out, "meta.json")["counts"]["routes"] == 10 and validation_errors(out) == []
    custom = ctx.root / "web-data"
    custom.mkdir()
    (custom / "package.json").write_text("{}", "utf-8")             # not ours: left alone
    (custom / "low-prices").mkdir()
    (custom / "low-prices" / "XXX.json").write_text("{}", "utf-8")  # a stale origin: removed
    assert CliRunner().invoke(cli.app, ["export", "site-data", "--out", str(custom),
                                        "--no-new-links"]).exit_code == 0
    assert (custom / "routes.json").exists() and (custom / "package.json").exists()
    assert not (custom / "low-prices" / "XXX.json").exists()


def test_run_exports_the_site_data_in_the_full_path_right_before_the_site_build(monkeypatch):
    from types import SimpleNamespace

    from escapadinha import run_path
    calls = []
    for name in ("apply_review_events", "_warn_if_late", "routes_upkeep",
                 "_warn_if_daily_pass_missed", "recheck_cmd", "detect", "publish_due",
                 "render_deals", "_export_site_data", "_site_build", "_site_deploy",
                 "export_review_snapshot"):
        monkeypatch.setattr(cli, name, lambda *a, _n=name.lstrip("_"), **k: calls.append(_n)
                            or SimpleNamespace(installed=False))
    monkeypatch.setattr(cli, "_collect", lambda: SimpleNamespace(
        status="ok", n_requests=1, n_observations=1, n_new=0, errors=[],
        plan=SimpleNamespace(describe=lambda: "daily pass")))
    monkeypatch.setattr(cli, "_ctx", lambda: (None, None))
    monkeypatch.setattr(cli, "_site_configured", lambda ctx: True)
    monkeypatch.setattr(cli.pipeline, "mirror_local_files", lambda ctx, conn: [])
    monkeypatch.setattr(run_path, "record_full_path",
                        lambda ctx, conn, export: calls.append("record_full_path"))
    monkeypatch.setattr(run_path, "decide", lambda ctx, conn, force: run_path.PathDecision(force, "x"))
    cli._run_steps(render=True, full=True, report=[])
    assert calls == ["apply_review_events", "warn_if_late", "routes_upkeep",
                     "warn_if_daily_pass_missed", "recheck_cmd", "detect", "publish_due",
                     "render_deals", "export_site_data", "site_build", "site_deploy",
                     "record_full_path",
                     "export_review_snapshot"]                 # D25, D26, D27, D32, D41, D42
    calls.clear()
    cli._run_steps(render=False, full=True, report=[])
    assert calls[-5:] == ["export_site_data", "site_build", "site_deploy", "record_full_path",
                          "export_review_snapshot"]
    calls.clear()
    cli._run_steps(render=True, full=False, report=[])                 # fast path: no export
    assert calls == ["apply_review_events", "warn_if_late", "routes_upkeep",
                     "warn_if_daily_pass_missed", "recheck_cmd", "detect", "publish_due",
                     "export_review_snapshot"]                 # posting on the fast path too


# --- committed fixtures -----------------------------------------------------------------------

FIXTURES = CONTRACT / "fixtures"


def no_real_links(out: Path) -> list[str]:
    """Links in a fixture set that are not the anonymous placeholder."""
    bad = []
    for path in out.rglob("*.json"):
        text = path.read_text("utf-8")
        bad += [f"{path.name}: {m}" for m in re.findall(r'"(https://[^"]+)"', text)
                if not m.startswith((site_data.FIXTURE_LINK, "https://pixabay.com",
                                     "https://ondestaanocas.pages.dev", "https://pontonomada.pt"))]
        if "marker" in text or "tpo.lu" in text:
            bad.append(f"{path.name}: marker / partner link")
    return bad


def test_committed_fixtures_validate_and_are_anonymous():
    assert validation_errors(FIXTURES) == []
    meta = read(FIXTURES, "meta.json")
    assert meta["fixture"] is True and no_real_links(FIXTURES) == []
    promos = read(FIXTURES, "promotions.json")["promotions"]
    assert any(p["live"] for p in promos) and any(not p["live"] for p in promos)
    assert meta["counts"]["routes"] <= 20 and meta["counts"]["low_prices"] >= 1
    assert sum(p.stat().st_size for p in FIXTURES.rglob("*.json")) < 100_000


@respx.mock
def test_fixtures_come_from_a_read_only_database_and_are_anonymous(ctx, tmp_path):  # noqa: F811
    mock_links()
    conn = pipeline.open_db(ctx)
    s = build_scenario(ctx, conn)
    db.upsert_photo(conn, Photo("LON", "LON.jpg", "pixabay", "https://pixabay.com/photos/x-1/",
                                "Joana Silva", "https://pixabay.com/users/joana-1/",
                                "Pixabay Content License", db.utcnow()))
    conn.close()
    before = ctx.db_path.read_bytes()
    out = tmp_path / "fixtures"
    export = site_data.generate_fixtures(ctx, ctx.db_path, out)
    assert ctx.db_path.read_bytes() == before                        # never written
    assert validation_errors(out) == [] and no_real_links(out) == []
    meta = read(out, "meta.json")
    assert meta["fixture"] is True and meta["run"]["id"] == 3
    assert meta["generated_at"] == meta["run"]["finished_at"]       # windows as of that run
    promos = {p["id"]: p for p in read(out, "promotions.json")["promotions"]}
    assert set(promos) == {s.live_deal, s.expired_deal}
    assert promos[s.live_deal]["booking_link"] == f"{site_data.FIXTURE_LINK}site-deal-{s.live_deal}"
    routes_out = {r["key"] for r in read(out, "routes.json")["routes"]}
    assert {"LIS-LON", "OPO-PAR"} <= routes_out and len(routes_out) < 10   # a modest subset
    rows = read(out, "low-prices/LIS.json")["rows"]
    assert rows and all(r[-1] == f"{site_data.FIXTURE_LINK}site-low-{r[0]}" for r in rows)
    assert export.files["meta.json"] == meta
    [lon] = [d for d in read(out, "destinations.json")["destinations"] if d["code"] == "LON"]
    text = "".join(p.read_text("utf-8") for p in out.rglob("*.json"))
    assert lon["photo"]["file"] == "LON.jpg" and "Joana" not in text and "joana" not in text


def test_fixtures_show_both_promotion_states_even_without_approved_deals(ctx, tmp_path):  # noqa: F811
    """Real data may have no approved deal yet: the fixture copy (in memory) marks the newest
    deal live and an expired one as approved before expiring, so the site can test both."""
    with respx.mock:
        mock_links()
        conn = pipeline.open_db(ctx)
        s = build_scenario(ctx, conn)
    conn.execute("UPDATE deals SET reviewed_at = NULL, status = 'expired'")
    conn.commit()
    conn.close()
    out = tmp_path / "fixtures"
    site_data.generate_fixtures(ctx, ctx.db_path, out)
    promos = read(out, "promotions.json")["promotions"]
    assert [(p["id"], p["live"]) for p in promos] == [(s.new_deal, True), (s.live_deal, False)]
    assert validation_errors(out) == []
    raw = pipeline.open_db(ctx).execute("SELECT COUNT(*) FROM deals WHERE status = 'expired'")
    assert raw.fetchone()[0] == 3                                       # the real file unchanged


# --- origin pages, destination hubs and the route calendar (#14, D30) -----------------------

def test_origins_and_destinations_carry_their_page_paths(exported):
    _, _, _, out, _ = exported
    origins = {o["iata"]: o for o in read(out, "origins.json")["origins"]}
    assert origins["LIS"]["path"] == "/partidas/lisboa/"
    assert origins["OPO"]["path"] == "/partidas/porto/"
    dests = {d["code"]: d for d in read(out, "destinations.json")["destinations"]}
    assert dests["LON"]["path"] == "/destinos/londres/" and dests["LON"]["slug"] == "londres"
    assert dests["ROM"]["path"] == "/destinos/roma/"


def test_destination_slugs_take_the_code_when_two_cities_share_a_name():
    from escapadinha.website import destination_slugs
    assert destination_slugs({"LON": "Londres", "AMS": "Amesterdão"}) == {
        "LON": "londres", "AMS": "amesterdao"}
    # Two provider cities with one Portuguese name: both get their code, whatever else exists.
    assert destination_slugs({"SJO": "São José", "SJC": "São José", "ROM": "Roma"}) == {
        "SJO": "sao-jose-sjo", "SJC": "sao-jose-sjc", "ROM": "roma"}


def test_a_published_hub_keeps_its_slug_when_a_same_name_city_appears_later():
    from escapadinha.website import destination_slugs
    # SJO was published as /destinos/sao-jose/; SJC (also "São José") is found afterwards.
    assert destination_slugs({"SJO": "São José", "SJC": "São José"}, {"SJO": ["sao-jose"]}) == {
        "SJO": "sao-jose", "SJC": "sao-jose-sjc"}
    # Published with its code, it keeps it; a renamed city gets a new slug (old path: 301).
    assert destination_slugs({"SJO": "São José", "SJC": "São José"},
                             {"SJO": ["sao-jose-sjo"], "SJC": ["sao-jose-sjc"]}) == {
        "SJO": "sao-jose-sjo", "SJC": "sao-jose-sjc"}
    assert destination_slugs({"SJO": "San José"}, {"SJO": ["sao-jose"]}) == {"SJO": "san-jose"}
    # Back to an earlier name: the slug it had then, the latest that fits.
    assert destination_slugs({"SJO": "São José"}, {"SJO": ["sao-jose", "san-jose"]}) == {
        "SJO": "sao-jose"}


def test_destination_slugs_stay_put_across_exports_and_changes_get_a_301(exported):
    """A same-name city discovered after the first export takes its code; the hub that was
    already published keeps /destinos/londres/. Every exported path is remembered in
    site.paths, so a slug that does change (a renamed city) gets a 301 from the old path."""
    from escapadinha.website import redirects
    ctx, conn, _, out, _ = exported
    assert route(out, "LIS-LON") and _dest(out, "LON")["path"] == "/destinos/londres/"
    assert pipeline.site_paths(ctx, conn)["destination:LON"] == ["/destinos/londres/"]
    db.insert_route(conn, origin="LIS", destination="XLO", city_pt="Londres", kind="europe",
                    discovered_at=db.utcnow())
    conn.commit()
    site_data.export_site_data(ctx, conn, out, new_links=False)
    assert _dest(out, "LON")["path"] == "/destinos/londres/"
    assert _dest(out, "XLO")["path"] == "/destinos/londres-xlo/"
    # Renamed in the data: a new slug, and the old path redirects to it.
    conn.execute("UPDATE routes SET city_pt = 'Londres (Reino Unido)' WHERE destination = 'LON'")
    conn.commit()
    site_data.export_site_data(ctx, conn, out, new_links=False)
    new = _dest(out, "LON")["path"]
    assert new == "/destinos/londres-reino-unido/"
    history = pipeline.site_paths(ctx, conn)
    assert history["destination:LON"] == ["/destinos/londres/", new]
    plan = redirects.plan_redirects({"destination:LON": new}, history, extra={}, aliases={})
    assert ("/destinos/londres/", new) in plan.rules


def _dest(out: Path, code: str) -> dict:
    return next(d for d in read(out, "destinations.json")["destinations"] if d["code"] == code)


def test_route_calendar_is_the_cheapest_fresh_offer_per_departure_date(exported):
    """The calendar of cheapest found prices (story 34): the latest run's fresh offers within
    the route's rules, the cheapest per departure day, ascending, each with its observation."""
    _, _, _, out, _ = exported
    lon = route(out, "LIS-LON")
    jan = date(db.utcnow().year + 1, 1, 10)
    # 50 € has a stop on a direct-only route: not in it. 60/80/85,40/95 € are fresh and direct.
    assert [(c["dep"], c["price"]) for c in lon["calendar"]] == [
        ((jan + timedelta(days=d)).isoformat(), p) for d, p in [(3, 60), (5, 80), (8, 85.4), (9, 95)]]
    first = lon["calendar"][0]
    assert first["obs"] == lon["cheapest"]["obs"]
    assert first["ret"] == (jan + timedelta(days=7)).isoformat()
    assert route(out, "OPO-BER")["calendar"] == []


def test_the_calendar_starts_on_the_lisbon_day_not_the_utc_day(ctx, tmp_path):  # noqa: F811
    """One "today" for the whole export, Lisbon's: at 23:30 UTC on 1 July it is already 2 July
    in Lisbon (summer time), so a 1 July departure has left and is not in the calendar."""
    from dataclasses import replace
    conn = pipeline.open_db(ctx)
    now = datetime(2026, 7, 1, 23, 30, tzinfo=timezone.utc)
    seen = datetime(2026, 7, 1, 20, 0, tzinfo=timezone.utc)

    def at(o):
        return replace(o, fetched_at=seen, found_date=seen.date())
    store_run(conn, [at(offer("LIS", "LON", 70, found_ago=0, dep=date(2026, 7, 1))),
                     at(offer("LIS", "LON", 80, found_ago=0, dep=date(2026, 7, 2)))])
    lon = next(r for r in site_data.build_export(ctx, conn, now, new_links=False)
               .files["routes.json"]["routes"] if r["key"] == "LIS-LON")
    assert [c["dep"] for c in lon["calendar"]] == ["2026-07-02"]
    before = datetime(2026, 7, 1, 22, 59, tzinfo=timezone.utc)      # 23:59 in Lisbon: still 1 July
    lon = next(r for r in site_data.build_export(ctx, conn, before, new_links=False)
               .files["routes.json"]["routes"] if r["key"] == "LIS-LON")
    assert [c["dep"] for c in lon["calendar"]] == ["2026-07-01", "2026-07-02"]


# --- pontes (D31) -----------------------------------------------------------------------------

def test_pontes_are_every_long_weekend_with_a_page_per_origin(ctx, tmp_path):  # noqa: F811
    """From content/holidays.yaml: every long weekend of the calendar, past ones too (their
    pages stay, noindex), each with its travel window and one page path per origin; raw values
    only (no titles: the site writes them from the name and the origin's article)."""
    conn = pipeline.open_db(ctx)
    now = datetime(2026, 12, 2, 23, 30, tzinfo=timezone.utc)       # 2 Dec, 23:30 in Lisbon
    out = tmp_path / "site-data"
    site_data.build_export(ctx, conn, now, new_links=False).write(out)
    assert validation_errors(out) == []
    assert read(out, "meta.json")["files"]["pontes"] == "pontes.json"
    doc = read(out, "pontes.json")
    assert doc["pontes"][0]["slug"] == "ano-novo-2026"    # long past: listed all the same
    assert [p["holiday"]["date"] for p in doc["pontes"]] == sorted(
        p["holiday"]["date"] for p in doc["pontes"])
    first = next(p for p in doc["pontes"] if p["slug"] == "1-dezembro-2026")
    assert first["name"] == "Ponte de 1 de dezembro"
    assert first["holiday"] == {"date": "2026-12-01", "name": "Restauração da Independência",
                                "optional": False}
    assert first["days_off"] == {"first": "2026-11-28", "last": "2026-12-01"}
    assert first["bridge"] == "2026-11-30"
    assert first["window"] == {"start": "2026-11-27", "end": "2026-12-02"}
    assert [o["iata"] for o in first["origins"]] == [
        o["iata"] for o in read(out, "origins.json")["origins"]]
    origins = {o["iata"]: o for o in first["origins"]}
    assert origins["OPO"] == {"iata": "OPO", "path": "/pontes/1-dezembro-2026/porto/"}
    # One origin slug for both page types: /partidas/porto/ and /pontes/<feriado>/porto/.
    pages = {o["iata"]: o for o in read(out, "origins.json")["origins"]}
    assert all(o["path"].endswith(f"/{pages[o['iata']]['slug']}/") for o in first["origins"])
    assert pages["OPO"]["path"] == "/partidas/porto/"
    # The article for "desde o Porto" comes from config (origins_article), not from code.
    assert (pages["OPO"]["article"], pages["LIS"]["article"]) == ("o", None)
    assert "Código do Trabalho" in doc["source"]
    carnaval = next(p for p in doc["pontes"] if p["slug"] == "carnaval-2027")
    assert carnaval["holiday"]["optional"] is True and carnaval["bridge"] == "2027-02-08"
    later = datetime(2027, 6, 1, tzinfo=timezone.utc)
    assert site_data.build_export(ctx, conn, later, new_links=False).files[
        "pontes.json"] == doc                                      # the same list, whatever the day


def test_origin_articles_come_from_config(ctx, tmp_path):  # noqa: F811
    ctx.config.origins_article = {"LIS": "a"}
    conn = pipeline.open_db(ctx)
    origins = site_data.build_export(ctx, conn, db.utcnow(), new_links=False).files[
        "origins.json"]["origins"]
    assert {o["iata"]: o["article"] for o in origins}.get("LIS") == "a"
    assert all(o["article"] is None for o in origins if o["iata"] != "LIS")


# --- site integrations (D34): analytics token, search widget, Instagram handle ----------------

FAKE_TOKEN = "fakeTestToken0000000000000000000"
# The ctx fixture has no website Project, so the site uses the Instagram one (584711); its
# marker is the fake TRAVELPAYOUTS_MARKER 424242. Test values, not a real widget.
FAKE_WIDGET = "https://tp.media/content?trs=584711&shmarker=424242&fake=test-only&promo_id=0"


def test_meta_carries_the_analytics_token_search_widget_and_handle_from_config(ctx, tmp_path):  # noqa: F811
    ctx.config.site.analytics_token = FAKE_TOKEN
    ctx.config.site.search_widget = FAKE_WIDGET
    conn = pipeline.open_db(ctx)
    export = site_data.build_export(ctx, conn, db.utcnow(), new_links=False)
    meta = export.files["meta.json"]
    assert meta["analytics_token"] == FAKE_TOKEN
    assert meta["search_widget"] == FAKE_WIDGET
    assert meta["instagram_handle"] == ctx.config.brand.handle
    out = tmp_path / "site-data"
    export.write(out)
    assert validation_errors(out) == []


def test_meta_says_null_when_analytics_and_widget_are_not_configured(ctx):  # noqa: F811
    conn = pipeline.open_db(ctx)
    meta = site_data.build_export(ctx, conn, db.utcnow(), new_links=False).files["meta.json"]
    assert meta["analytics_token"] is None and meta["search_widget"] is None


@respx.mock
def test_fixtures_never_carry_the_analytics_token_or_the_widget(ctx, tmp_path):  # noqa: F811
    """A fixture build stays unconfigured (Lighthouse measures the site without third parties)."""
    mock_links()
    ctx.config.site.analytics_token = FAKE_TOKEN
    ctx.config.site.search_widget = FAKE_WIDGET
    conn = pipeline.open_db(ctx)
    build_scenario(ctx, conn)
    conn.close()
    out = tmp_path / "fixtures"
    site_data.generate_fixtures(ctx, ctx.db_path, out)
    meta = read(out, "meta.json")
    assert meta["analytics_token"] is None and meta["search_widget"] is None
    assert validation_errors(out) == [] and no_real_links(out) == []


def test_committed_fixtures_are_unconfigured():
    meta = read(FIXTURES, "meta.json")
    assert meta["analytics_token"] is None and meta["search_widget"] is None
    assert meta["instagram_handle"].startswith("@")


def test_search_widget_must_be_an_https_travelpayouts_widget_script():
    from pydantic import ValidationError
    from escapadinha.config import SEARCH_WIDGET_HOSTS, SiteConfig
    assert SiteConfig(search_widget=FAKE_WIDGET).search_widget == FAKE_WIDGET
    for bad in ("http://tp.media/content?x=1", "https://example.com/content?x=1",
                "https://tp.media.example.com/x", "https://tp.media/x\" onload=\"x"):
        with pytest.raises(ValidationError, match="search_widget"):
            SiteConfig(search_widget=bad)
    # The contract's pattern accepts exactly the same hosts.
    pattern = re.compile(json.loads((CONTRACT / "meta.schema.json").read_text("utf-8"))
                         ["properties"]["search_widget"]["anyOf"][0]["pattern"])
    for host in SEARCH_WIDGET_HOSTS:
        assert pattern.search(f"https://{host}/content?x=1"), host
    assert not pattern.search("https://example.com/content?x=1")
    assert not pattern.search("https://tp.media.example.com/x")


def test_search_widget_must_carry_the_websites_project_and_our_marker(ctx):  # noqa: F811
    """Host allowlist first; then the widget's affiliate Project (`trs`) must be the website's
    (`affiliate.project_for("website")`) and, with TRAVELPAYOUTS_MARKER set, its `shmarker` our
    marker: a widget copied from another account would earn someone else the commissions."""
    from pydantic import ValidationError
    from escapadinha.config import AppConfig, ConfigError
    base = ctx.config.model_dump()

    def load(src: str, website: int | None = None) -> AppConfig:
        data = {**base, "site": {**base["site"], "search_widget": src},
                "affiliate": {**base["affiliate"], "projects": {**base["affiliate"]["projects"],
                                                                 "website": website}}}
        return AppConfig.model_validate(data)

    assert load(FAKE_WIDGET).site.search_widget == FAKE_WIDGET       # Instagram's, as fallback
    site_widget = "https://tpwgts.com/content?trs=585209&shmarker=424242&locale=pt"
    assert load(site_widget, website=585209).site.search_widget == site_widget
    for bad, why in (("https://tp.media/content?shmarker=424242", "no trs"),
                     ("https://tp.media/content?trs=111111&shmarker=424242", "trs=111111"),
                     ("https://tp.media/content?trs=584711&trs=585209", "trs=584711,585209")):
        with pytest.raises(ValidationError,
                           match=f"search_widget: it has {why}, not the website's Project trs=584711"):
            load(bad)
    with pytest.raises(ValidationError, match="trs=585209"):
        load(FAKE_WIDGET, website=585209)                    # made for the Instagram Project

    # The marker comes from the secrets (TRAVELPAYOUTS_MARKER=424242 in the fixture).
    ctx.config.site.search_widget = FAKE_WIDGET
    assert ctx.search_widget() == FAKE_WIDGET
    ctx.config.site.search_widget = FAKE_WIDGET.replace("shmarker=424242", "shmarker=424242.site")
    assert ctx.search_widget()                                # the constructor's sub id form
    for bad in (FAKE_WIDGET.replace("shmarker=424242", "shmarker=999999"),
                FAKE_WIDGET.replace("shmarker=424242", "shmarker=4242421"),
                FAKE_WIDGET.replace("shmarker=424242&", "")):
        ctx.config.site.search_widget = bad
        with pytest.raises(ConfigError, match="TRAVELPAYOUTS_MARKER"):
            ctx.search_widget()
        conn = pipeline.open_db(ctx)
        with pytest.raises(ConfigError):                      # never exported
            site_data.build_export(ctx, conn, db.utcnow(), new_links=False)
        conn.close()


def test_without_a_known_marker_only_the_project_is_checked(ctx, monkeypatch):  # noqa: F811
    monkeypatch.setenv("TRAVELPAYOUTS_MARKER", "")
    ctx.config.site.search_widget = FAKE_WIDGET.replace("shmarker=424242", "shmarker=999999")
    assert ctx.search_widget() == ctx.config.site.search_widget


def _differences(a, b, path: str = "") -> set[str]:
    """Paths ('routes[].counts.observations') where two export documents differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        return set().union(*(_differences(a.get(k), b.get(k), f"{path}.{k}" if path else k)
                             for k in a.keys() | b.keys()))
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return set().union(*(_differences(x, y, f"{path}[]") for x, y in zip(a, b)))
    return set() if a == b else {path}


def test_every_field_a_new_run_changes_is_classified_per_run(ctx):  # noqa: F811
    """Two exports with the same offers, one collection run apart: the only differences are
    the fields `site_data.PER_RUN` lists, and `shown_digest` (the full path's fingerprint, D35)
    ignores them. A new field that changes every run fails here until it is classified there
    (or made stable), so a routine run never takes the full path for bookkeeping."""
    from test_web_build import store_offer
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    departure = date.today() + timedelta(days=40)
    store_offer(conn, 70, departure)
    first = site_data.build_export(ctx, conn, db.utcnow(), new_links=False)
    store_offer(conn, 70, departure)                             # the same offer seen again
    second = site_data.build_export(ctx, conn, db.utcnow() + timedelta(seconds=1), new_links=False)
    assert first.files.keys() == second.files.keys()
    assert any(f["rows"] for rel, f in first.files.items() if rel.startswith("low-prices/"))
    unclassified, seen = [], set()
    for rel in first.files:
        pattern = "low-prices/*" if rel.startswith("low-prices/") else rel
        per_run = site_data.PER_RUN.get(pattern, ())
        for path in _differences(first.files[rel], second.files[rel]):
            match = next((p for p in per_run if path == p or path.startswith((f"{p}.", f"{p}[]"))),
                         None)
            if match is None:
                unclassified.append(f"{rel}: {path}")
            seen.add(f"{pattern}: {match}")
    assert unclassified == [], "classify these in site_data.PER_RUN (or make them stable)"
    assert {"meta.json: generated_at", "meta.json: run", "low-prices/*: run"} <= seen
    assert site_data.shown_digest(first) == site_data.shown_digest(second)
    # Every PER_RUN file exists in the export (a renamed file would silently stop matching).
    for pattern in site_data.PER_RUN:
        assert any(rel == pattern or (pattern.endswith("/*") and rel.startswith(pattern[:-1]))
                   for rel in first.files), pattern


def test_analytics_token_is_a_plain_token():
    from pydantic import ValidationError
    from escapadinha.config import SiteConfig
    assert SiteConfig(analytics_token=FAKE_TOKEN).analytics_token == FAKE_TOKEN
    with pytest.raises(ValidationError, match="analytics_token"):
        SiteConfig(analytics_token='x"}; alert(1)')
