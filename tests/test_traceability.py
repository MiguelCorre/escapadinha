"""Never fabricate prices (D2), enforced: render the whole site and every caption from a
temporary database and fail when a price string cannot be traced to stored data that the
page or caption references.

A page references observations with `data-obs`, deals with `data-deal` and a route's
typical lows with `data-route`. A price is traceable when it equals:
- the price of a referenced observation;
- a referenced deal's observation price, its stored `baseline_median`, or the price its last
  recheck saw (only if a stored observation of the same route and trip has that price);
- a typical low (median of daily lows) computed from the referenced route's stored
  observations.
A caption references its deal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pytest
import respx

from escapadinha import detector, pipeline, routes
from escapadinha.captions import guide_caption
from escapadinha.config import Context
from escapadinha.guides import load_guide
from escapadinha.models import Observation
from escapadinha.presentation import PhotoCredit
from escapadinha.storage import db
from escapadinha.website import build_site
from test_pipeline import ctx, mock_links  # noqa: F401

# '58 €', '85,40 €', '58€' (slides style), with a normal or non-breaking space.
PRICE = re.compile(r"(\d+(?:,\d{1,2})?)(?:\s|&nbsp;|&#160;| )?€")


# --- the checker ---------------------------------------------------------------------------

@dataclass
class Refs:
    observations: set[int] = field(default_factory=set)
    deals: set[int] = field(default_factory=set)
    routes: set[str] = field(default_factory=set)


def page_refs(html: str) -> Refs:
    return Refs({int(i) for i in re.findall(r'data-obs="(\d+)"', html)},
                {int(i) for i in re.findall(r'data-deal="(\d+)"', html)},
                set(re.findall(r'data-route="([A-Z0-9]+-[A-Z0-9]+)"', html)))


def cents(value: float) -> int:
    return round(value * 100)


def prices_in(text: str) -> list[tuple[str, int]]:
    return [(m.group(0), cents(float(m.group(1).replace(",", ".")))) for m in PRICE.finditer(text)]


def traceable_amounts(ctx: Context, conn, refs: Refs) -> set[int]:
    amounts: set[int] = set()
    for oid in refs.observations:
        amounts.add(cents(db.get_observation(conn, oid).price))
    for deal_id in refs.deals:
        deal, obs = db.get_deal(conn, deal_id)
        amounts.add(cents(obs.price))
        if deal.baseline_median is not None:
            amounts.add(cents(deal.baseline_median))
        if deal.last_seen_price is not None and conn.execute(
                """SELECT 1 FROM price_observations WHERE origin = ? AND destination = ?
                   AND departure_date = ? AND return_date = ? AND price = ?""",
                (obs.origin, obs.destination, obs.departure_date.isoformat(),
                 obs.return_date.isoformat(), deal.last_seen_price)).fetchone():
            amounts.add(cents(deal.last_seen_price))
    cfg = ctx.config.detector
    for key in refs.routes:
        route = routes.get_route(conn, ctx.config.routes, key)
        history = db.route_history(conn, route.origin, route.destination,
                                   since=db.utcnow() - timedelta(days=cfg.lookback_days),
                                   exclude_run_id=None)
        for base in detector.month_baselines(history, cfg, db.utcnow(), route.rules).values():
            if base.median is not None:
                amounts.add(cents(base.median))
    return amounts


def untraceable(ctx: Context, conn, text: str, refs: Refs) -> list[str]:
    allowed = traceable_amounts(ctx, conn, refs)
    return [shown for shown, amount in prices_in(text) if amount not in allowed]


def site_files(site_dir: Path) -> list[Path]:
    return sorted(p for p in site_dir.rglob("*")
                  if p.is_file() and p.suffix in (".html", ".xml", ".txt"))


def all_captions(ctx: Context, conn) -> list[tuple[str, str, Refs]]:
    """(name, text, refs) for every deal's caption (any status) and every guide's caption."""
    out = []
    for row in conn.execute("SELECT id FROM deals ORDER BY id"):
        deal, obs = db.get_deal(conn, row["id"])
        view, _ = pipeline.deal_view(ctx, conn, deal, obs)
        out.append((f"deal {deal.id} caption", pipeline.deal_caption_text(ctx, view),
                    Refs(deals={deal.id})))
    for path in sorted(ctx.guides_dir.glob("*.yaml")):
        guide = load_guide(ctx.guides_dir, path.stem)
        out.append((f"guide {path.stem} caption",
                    guide_caption(guide, PhotoCredit.from_photo(None, None)), Refs()))
    return out


# --- a realistic database ---------------------------------------------------------------------

def offer(origin: str, destination: str, price: float, *, found_ago: int, dep: date,
          nights: int = 4, transfers: int = 0, airport: str = "LGW") -> Observation:
    """Synthetic API-shaped offer (test data only, tmp_path database)."""
    now = db.utcnow()
    return Observation(
        source="travelpayouts", origin=origin, destination=destination, origin_airport=origin,
        destination_airport=airport, departure_date=dep, return_date=dep + timedelta(days=nights),
        price=price, currency="eur", airline="FR", flight_number="1",
        transfers=transfers, return_transfers=0,
        deep_link=(f"https://www.aviasales.com/search/{origin}{dep:%d%m}{destination}"
                   f"{dep + timedelta(days=nights):%d%m}1?t=test{cents(price)}"),
        fetched_at=now - timedelta(days=found_ago), found_date=now.date() - timedelta(days=found_ago),
    )


def store_run(conn, offers: list[Observation]) -> int:
    run_id = db.start_run(conn, "travelpayouts")
    db.insert_observations(conn, run_id, offers)
    db.finish_run(conn, run_id, status="ok", n_requests=len(offers), n_observations=len(offers),
                  error=None)
    return run_id


def history(origin: str, destination: str, lows: list[float], dep: date) -> list[Observation]:
    """One daily low per day, found 5, 6, ... days ago (outside the freshness window)."""
    return [offer(origin, destination, p, found_ago=5 + i, dep=dep + timedelta(days=i % 7))
            for i, p in enumerate(lows)]


@dataclass
class Scenario:
    live_deal: int
    expired_deal: int
    new_deal: int
    low_only: list[int]          # observation ids that are low prices, not promotions
    cheap_route_low: int         # LIS-BCN: -35 % but saves only 14 €


def build_scenario(ctx: Context, conn) -> Scenario:
    """Three runs: history; an OPO-PAR promotion approved; a current run that expires it and
    brings a live LIS-LON promotion, low prices and a small-fare route."""
    nov = date(db.utcnow().year + 1, 1, 10)      # a departure month well ahead of today
    store_run(conn, history("LIS", "LON", [100, 101] * 5, nov)        # typical low 100,50 €
              + history("LIS", "BCN", [40] * 6, nov)
              + history("LIS", "ROM", [120] * 6, nov)
              + history("OPO", "PAR", [100] * 6, nov))

    trip = nov + timedelta(days=12)
    second = store_run(conn, [offer("OPO", "PAR", 55, found_ago=1, dep=trip)])
    _, results = pipeline.run_detect(ctx, conn, second)
    [expired] = {r.route: r for r in results}["OPO-PAR"].deal_ids
    pipeline.ensure_affiliate_links(ctx, conn, [db.get_deal(conn, expired)])
    db.record_review(conn, expired, status="approved", note=None)

    current = store_run(conn, [
        offer("LIS", "LON", 60, found_ago=0, dep=nov + timedelta(days=3)),    # -40 %: promotion
        offer("LIS", "LON", 80, found_ago=1, dep=nov + timedelta(days=5)),    # -20 %: low price
        offer("LIS", "LON", 85.4, found_ago=2, dep=nov + timedelta(days=8), airport="STN"),
        offer("LIS", "LON", 95, found_ago=0, dep=nov + timedelta(days=9)),    # -5 %: neither
        offer("LIS", "LON", 50, found_ago=0, dep=nov + timedelta(days=10), transfers=1),
        offer("LIS", "BCN", 26, found_ago=0, dep=nov + timedelta(days=4), airport="BCN"),
        offer("LIS", "ROM", 70, found_ago=0, dep=nov + timedelta(days=6), airport="FCO"),
        offer("OPO", "PAR", 90, found_ago=0, dep=trip),                       # the deal's trip
    ])
    pipeline.run_recheck(ctx, conn, current)
    _, results = pipeline.run_detect(ctx, conn, current)
    by_route = {r.route: r for r in results}
    [live] = by_route["LIS-LON"].deal_ids
    [new] = by_route["LIS-ROM"].deal_ids
    assert by_route["LIS-BCN"].deal_ids == [] and by_route["LIS-BCN"].low_prices == 1
    assert by_route["LIS-LON"].low_prices == 3
    pipeline.ensure_affiliate_links(ctx, conn, [db.get_deal(conn, live)])
    db.record_review(conn, live, status="approved", note=None)

    ids = {(o.route_key, o.price): o.id for o in db.observations_seen_since(conn, current)}
    return Scenario(live, expired, new, [ids["LIS-LON", 80], ids["LIS-LON", 85.4]],
                    ids["LIS-BCN", 26])


@pytest.fixture
def built(ctx):  # noqa: F811
    """The scenario's database and the site built from it (partner links API mocked)."""
    with respx.mock:
        links = mock_links()
        conn = pipeline.open_db(ctx)
        scenario = build_scenario(ctx, conn)
        guide = ctx.guides_dir / "voos-baratos-dicas.yaml"
        guide.write_text(guide.read_text("utf-8").replace("reviewed: false", "reviewed: true"),
                         "utf-8")
        summary = build_site(ctx, conn)
        yield ctx, conn, scenario, summary, links


# --- tests ----------------------------------------------------------------------------------

def test_every_price_on_the_site_and_in_captions_traces_to_stored_data(built):
    ctx, conn, scenario, summary, _ = built
    assert db.get_deal(conn, scenario.expired_deal)[0].status == "expired"
    assert summary["live_deals"] == 1 and summary["low_prices"] >= 3

    checked, shown = 0, 0
    for path in site_files(ctx.site_dir):
        text = path.read_text("utf-8")
        bad = untraceable(ctx, conn, text, page_refs(text))
        assert not bad, f"{path.relative_to(ctx.site_dir)}: untraceable prices {bad}"
        checked += 1
        shown += len(prices_in(text))
    for name, text, refs in all_captions(ctx, conn):
        bad = untraceable(ctx, conn, text, refs)
        assert not bad, f"{name}: untraceable prices {bad}"
        shown += len(prices_in(text))
    assert checked > 15 and shown > 20          # the check really looked at prices


def test_the_scenario_shows_every_kind_of_price(built):
    """Guard against a vacuous traceability test: each price source is on some page."""
    ctx, conn, scenario, _, _ = built
    route = (ctx.site_dir / "voos/lisboa-londres/index.html").read_text("utf-8")
    assert "80 €" in route and "85,40 €" in route          # low prices
    assert "100,50 €" in route                              # typical low (even median)
    assert "60 €" in route                                  # live promotion card
    amounts = {amount for _, amount in prices_in(route)}
    assert 9500 not in amounts and 5000 not in amounts      # neither tier (-5 %, not direct)
    expired = next((ctx.site_dir / "promos").glob(f"{scenario.expired_deal}-*/index.html"))
    assert "o preço subiu para 90 €" in expired.read_text("utf-8")
    assert "26 €" in (ctx.site_dir / "voos/lisboa-barcelona/index.html").read_text("utf-8")


def test_checker_flags_fabricated_and_unreferenced_prices(built):
    ctx, conn, scenario, _, _ = built
    page = (ctx.site_dir / "voos/lisboa-londres/index.html").read_text("utf-8")
    assert untraceable(ctx, conn, page, page_refs(page)) == []
    fabricated = page.replace("</h1>", " desde 19 €</h1>", 1)
    assert untraceable(ctx, conn, fabricated, page_refs(fabricated)) == ["19 €"]
    # A real stored price (LIS-BCN 26 €) that this page does not reference is not traceable.
    borrowed = page.replace("</h1>", " ou 26 €</h1>", 1)
    assert untraceable(ctx, conn, borrowed, page_refs(borrowed)) == ["26 €"]
    # A recheck price without a stored observation of that trip is not traceable either.
    conn.execute("UPDATE deals SET last_seen_price = 77 WHERE id = ?", (scenario.expired_deal,))
    assert untraceable(ctx, conn, "subiu para 77 €", Refs(deals={scenario.expired_deal})) == ["77 €"]


def test_captions_reference_only_their_own_deal(built):
    ctx, conn, scenario, _, _ = built
    captions = {name: (text, refs) for name, text, refs in all_captions(ctx, conn)}
    text, refs = captions[f"deal {scenario.live_deal} caption"]
    assert "60 €" in text and untraceable(ctx, conn, text, refs) == []
    other = Refs(deals={scenario.new_deal})
    assert untraceable(ctx, conn, text, other) == ["60 €"]
