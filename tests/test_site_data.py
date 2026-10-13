"""Website data contract v1 (D27): the JSON export validates against the schemas in
contract/site/v1, every price in it traces to stored data, the per-origin low-price files
stay inside their size budget, and the committed fixtures validate too."""

from __future__ import annotations

import gzip
import json
import re
from datetime import date, timedelta
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
               ("/routes/*/cheapest", "offer")},
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
    assert lon["counts"]["observations"] == 25 and lon["status"] == "active"
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


# --- size budget (D27) --------------------------------------------------------------------

@respx.mock
def test_low_price_files_stay_inside_the_size_budget(ctx, tmp_path):  # noqa: F811
    mock_links()
    conn = pipeline.open_db(ctx)
    jan = date(db.utcnow().year + 1, 1, 10)
    store_run(conn, history("LIS", "LON", [100] * 6, jan))           # typical low 100 € in Jan
    trips = [offer("LIS", "LON", 60 + (day * 9 + n) % 25 + 0.5 * (n % 2), found_ago=n % 3,
                   dep=jan + timedelta(days=day), nights=n)
             for day in range(22) for n in range(2, 11)]                # 198 trips, all -15 %+
    run_id = store_run(conn, trips)
    ctx.config.site.max_low_prices_per_origin = 150
    out = tmp_path / "data"
    site_data.export_site_data(ctx, conn, out)

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
    site_data.export_site_data(ctx, conn, tmp_path / "again")
    assert (tmp_path / "again" / "low-prices" / "LIS.json").read_bytes() == raw   # deterministic    assert validation_errors(out) == []


# --- CLI and the run -----------------------------------------------------------------------

def test_export_command_writes_the_contract_files(ctx, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    conn = pipeline.open_db(ctx)
    seed_history(conn, days=25, price=100)
    conn.close()
    result = CliRunner().invoke(cli.app, ["export", "site-data", "--no-new-links"])
    assert result.exit_code == 0, result.output
    out = ctx.root / "output" / "site-data" / "v1"                  # site.data_dir
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
    for name in ("routes_upkeep", "recheck_cmd", "detect", "render_deals",
                 "export_site_data", "site_build", "site_deploy"):
        monkeypatch.setattr(cli, name, lambda *a, _n=name, **k: calls.append(_n))
    monkeypatch.setattr(cli, "_collect", lambda: SimpleNamespace(
        status="ok", n_requests=1, n_observations=1, n_new=0, errors=[]))
    monkeypatch.setattr(cli, "_ctx", lambda: (None, None))
    monkeypatch.setattr(cli, "_site_configured", lambda ctx: True)
    monkeypatch.setattr(cli.pipeline, "mirror_local_files", lambda ctx, conn: [])
    monkeypatch.setattr(run_path, "record_full_path", lambda ctx, conn: None)
    monkeypatch.setattr(run_path, "decide", lambda ctx, conn, force: run_path.Decision(force, "x"))
    cli._run_steps(render=True, full=True, report=[])
    assert calls[-4:] == ["render_deals", "export_site_data", "site_build", "site_deploy"]
    calls.clear()
    cli._run_steps(render=False, full=True, report=[])
    assert calls[-3:] == ["export_site_data", "site_build", "site_deploy"]
    calls.clear()
    cli._run_steps(render=True, full=False, report=[])                 # fast path: no export
    assert "export_site_data" not in calls and "site_build" not in calls


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
