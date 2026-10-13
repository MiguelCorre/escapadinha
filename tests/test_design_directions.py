"""Design directions (issue #11): 7 pages from real DB rows only, disclosure, no booking link on
expired promotions, AA contrast for body text. Test data lives in tmp_path only."""

import re
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest
from PIL import Image

from escapadinha import i18n_pt as pt
from escapadinha import pipeline
from escapadinha.design_directions import build_directions
from escapadinha.design_directions.contrast import over, ratio
from escapadinha.design_directions.data import NBSP
from escapadinha.design_directions.directions import DIRECTIONS
from escapadinha.models import Observation, Photo
from escapadinha.presentation import DISCLOSURE
from escapadinha.storage import db
from test_pipeline import ctx  # noqa: F401

NOW = datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc)
PRICE = re.compile(r"(\d+(?:,\d{2})?)\s?€")


def obs(price, *, fetched, found, dep=date(2026, 11, 10), nights=3, transfers=0):
    return Observation(source="travelpayouts", origin="LIS", destination="LON", origin_airport="LIS",
                       destination_airport="STN", departure_date=dep,
                       return_date=dep + timedelta(days=nights), price=price, currency="EUR",
                       airline="FR", flight_number="1", transfers=transfers, return_transfers=0,
                       deep_link="https://www.aviasales.com/search/LIS1011LON13111", fetched_at=fetched,
                       raw_json="{}", found_date=found)


def run(conn, observations):
    run_id = db.start_run(conn, "travelpayouts")
    db.insert_observations(conn, run_id, observations)
    db.finish_run(conn, run_id, status="ok", n_requests=1, n_observations=len(observations), error=None)
    return {o.price: o for o in db.observations_seen_since(conn, run_id)}


def deal(conn, o, status, link, median=101.0):
    deal_id = db.insert_deal(conn, observation_id=o.id, rule="median", baseline_median=median,
                             sample_size=7, discount_pct=1 - o.price / median, threshold=0.3)
    db.set_deal_affiliate(conn, deal_id, link, None)
    if status == "expired":
        db.record_recheck(conn, deal_id, valid=False, latest_price=101, reason="o preço subiu para 101 €")
    else:
        db.record_review(conn, deal_id, status=status, note=None)
    return deal_id


@pytest.fixture
def seeded(ctx):
    """7 baseline days for LIS-LON November (daily lows 100/101/102 -> typical low 101) and a
    latest run with a direct low (58), a direct non-low (140) and a cheap non-direct offer (40)."""
    conn = pipeline.open_db(ctx)
    history = [obs(100 + i % 3, fetched=NOW - timedelta(days=i + 5),
                   found=(NOW - timedelta(days=i + 5)).date(), dep=date(2026, 11, 3 + i))
               for i in range(7)]
    run(conn, history)
    fresh = NOW - timedelta(hours=1)
    latest = run(conn, [obs(58, fetched=fresh, found=NOW.date()),
                        obs(61, fetched=fresh, found=NOW.date(), dep=date(2026, 11, 20)),
                        obs(140, fetched=fresh, found=NOW.date(), dep=date(2026, 11, 24)),
                        obs(40, fetched=fresh, found=NOW.date(), dep=date(2026, 11, 26), transfers=1)])
    ids = {"expired": deal(conn, latest[58], "expired", "https://aviasales.tpo.lu/EXPIRED"),
           "live": deal(conn, latest[61], "approved", "https://aviasales.tpo.lu/LIVE"),
           "rejected": deal(conn, latest[140], "rejected", "https://aviasales.tpo.lu/REJECTED")}
    ctx.photos_dir.mkdir(parents=True)
    Image.new("RGB", (64, 48), (200, 120, 60)).save(ctx.photos_dir / "LON.jpg")
    db.upsert_photo(conn, Photo("LON", "LON.jpg", "pixabay", "https://pixabay.com/photos/x-1/",
                                "someone", "https://pixabay.com/users/someone-1/",
                                "Pixabay Content License", NOW))
    conn.close()
    return ids


def read_only(ctx):
    conn = sqlite3.connect(f"{ctx.db_path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def test_seven_pages_with_disclosure_and_photo(ctx, seeded):
    summary = build_directions(ctx, read_only(ctx), NOW)      # read-only: generator never writes
    out = ctx.output_dir / "directions"
    assert len(summary["pages"]) == 7
    assert sorted(p.relative_to(out).as_posix() for p in summary["pages"]) == [
        "a-caderno/index.html", "a-caderno/promocao.html", "b-por-do-sol/index.html",
        "b-por-do-sol/promocao.html", "c-quadro/index.html", "c-quadro/promocao.html", "index.html"]
    for page in summary["pages"]:
        html = page.read_text("utf-8")
        assert DISCLOSURE in html, page
        assert 'name="viewport"' in html and "prefers-color-scheme: dark" in html
    assert (out / "assets" / "photos" / "LON.jpg").is_file()
    home = (out / "b-por-do-sol" / "index.html").read_text("utf-8")
    assert "../assets/photos/LON.jpg" in home and "someone" in home


def test_every_price_comes_from_the_database(ctx, seeded):
    summary = build_directions(ctx, read_only(ctx), NOW)
    conn = read_only(ctx)
    real = {float(r[0]) for r in conn.execute("SELECT price FROM price_observations")}
    real |= {float(r[0]) for r in conn.execute("SELECT baseline_median FROM deals")}
    allowed = {pt.eur(p).removesuffix(" €") for p in real}
    shown = set()
    for page in summary["pages"]:
        shown |= set(PRICE.findall(page.read_text("utf-8")))
    assert shown, "no prices rendered"
    assert shown <= allowed, shown - allowed
    # The low price and its typical low (median of daily lows 100/101/102) are shown.
    a_home = (ctx.output_dir / "directions" / "a-caderno" / "index.html").read_text("utf-8")
    assert f"58{NBSP}€" in a_home and f"101{NBSP}€" in a_home
    # A cheaper offer with a connection is not a low price (direct_only).
    assert f"40{NBSP}€" not in a_home and "40€" not in a_home


def test_expired_promotion_has_no_booking_link(ctx, seeded):
    summary = build_directions(ctx, read_only(ctx), NOW, deal_id=seeded["expired"])
    for page in summary["pages"]:
        html = page.read_text("utf-8")
        assert "tpo.lu/EXPIRED" not in html and "tpo.lu/REJECTED" not in html
        assert "aviasales.com/search" not in html          # raw deep links are never linked
    for d in DIRECTIONS:
        promo = (ctx.output_dir / "directions" / d.slug / "promocao.html").read_text("utf-8")
        assert f"Esta promoção já expirou: o preço subiu para 101{NBSP}€" in promo
        assert "Ver voo e reservar" not in promo and 'rel="sponsored' not in promo


def test_live_promotion_uses_the_stored_partner_link(ctx, seeded):
    summary = build_directions(ctx, read_only(ctx), NOW)          # live deals are featured first
    for d in DIRECTIONS:
        promo = (ctx.output_dir / "directions" / d.slug / "promocao.html").read_text("utf-8")
        assert 'href="https://aviasales.tpo.lu/LIVE" rel="sponsored nofollow noopener"' in promo
    assert all("REJECTED" not in p.read_text("utf-8") for p in summary["pages"])


def test_empty_database_still_builds_all_pages(ctx):
    pipeline.open_db(ctx).close()
    summary = build_directions(ctx, read_only(ctx), NOW)
    assert len(summary["pages"]) == 7 and summary["promos"] == 0 and summary["lows"] == 0
    assert not any(PRICE.search(p.read_text("utf-8")) for p in summary["pages"])


def test_contrast_math():
    assert ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert ratio("#777777", "#FFFFFF") == pytest.approx(4.48, abs=0.01)
    assert over("#000000", 0.5, "#FFFFFF") == "#808080"


@pytest.mark.parametrize("direction", DIRECTIONS, ids=lambda d: d.slug)
def test_body_text_pairs_pass_wcag_aa(direction):
    rows = direction.contrast()
    assert {r.mode for r in rows} == {"light", "dark"}
    body = [r for r in rows if r.role == "body"]
    assert body
    failing = [(r.mode, r.label, r.ratio) for r in body if r.ratio < 4.5]
    assert not failing
    assert all(f.licence == "SIL Open Font License 1.1" for f in direction.fonts)
