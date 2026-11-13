"""The slides show the price the page shows (D66): a recheck that holds a small rise within the
tolerance (D53) moves the page to its own observation, and the full path renders the slides
again from that observation; an expiry moves both back to the price it was a promotion at."""

import json
from datetime import date
from pathlib import Path

import respx
from PIL import Image

from escapadinha import i18n_pt as pt
from escapadinha import pipeline, site_data
from escapadinha.storage import db
from test_pipeline import ctx  # noqa: F401
from test_review import price_api
from test_website import approved_deal


LATER = date(2026, 12, 30)      # a found day no fixture observation has


class CapturingRenderer:
    """Stands in for Chromium: writes small real PNGs and keeps each view (and its price)."""
    prices: list[str] = []
    views: list = []

    def __init__(self, assets_dir, brand):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def render_deal(self, view, photo_path, out_dir: Path):
        CapturingRenderer.prices.append(view.price)
        CapturingRenderer.views.append(view)
        out_dir.mkdir(parents=True, exist_ok=True)
        for n in (1, 2, 3):
            Image.new("RGB", (108, 135), (200, 80, 60)).save(out_dir / f"slide_{n:02d}.png")


def site_deals(ctx, conn):
    return site_data.exported_deals(ctx, conn, db.utcnow())


def page_price(conn, deal_id) -> tuple[int, float]:
    """(obs, price) the page shows: promotions.json's `latest` while live, else the offer."""
    deal, obs = db.get_deal(conn, deal_id)
    shown = pipeline.shown_observation(conn, deal, obs)
    return shown.id, shown.price


@respx.mock
def test_a_held_rise_renders_the_slides_again_at_the_pages_price(ctx, monkeypatch):
    monkeypatch.setattr(pipeline, "SlideRenderer", CapturingRenderer)
    CapturingRenderer.prices, CapturingRenderer.views = [], []
    conn = pipeline.open_db(ctx)
    deal_id = approved_deal(ctx, conn)                     # 58 €, rendered from its observation
    assert pipeline.stale_renders(conn, site_deals(ctx, conn)) == []

    price_api(59)                                          # +1 €: held within the tolerance (D53)
    run_id = pipeline.run_collect(ctx, conn).run_id
    pipeline.run_recheck(ctx, conn, run_id)
    deal, obs = db.get_deal(conn, deal_id)
    assert deal.status == "approved" and deal.last_seen_price == 59
    latest_obs, latest_price = page_price(conn, deal_id)
    assert latest_obs != obs.id and latest_price == 59
    # The recheck's row was found a day later and has no baggage answer; the detected one has.
    conn.execute("UPDATE price_observations SET found_date = ?, with_baggage = NULL WHERE id = ?",
                 (LATER.isoformat(), latest_obs))
    conn.execute("UPDATE price_observations SET with_baggage = 0 WHERE id = ?", (obs.id,))
    conn.commit()
    # The mismatch the walk-through saw: slides of 58 € beside a page of 59 €.
    assert [d.id for d, _ in pipeline.stale_renders(conn, site_deals(ctx, conn))] == [deal_id]

    [(folder, _)] = pipeline.run_rerender_stale(ctx, conn, site_deals(ctx, conn))
    deal, _ = db.get_deal(conn, deal_id)
    assert deal.status == "approved"                       # a render never moves a status
    assert deal.rendered_observation_id == latest_obs and deal.output_path == str(folder)
    assert CapturingRenderer.prices == [pt.eur(59)]
    meta = json.loads((folder / "meta.json").read_text("utf-8"))
    assert (meta["observation_id"], meta["price"]) == (latest_obs, 59)
    assert pipeline.stale_renders(conn, site_deals(ctx, conn)) == []
    assert pipeline.run_rerender_stale(ctx, conn, site_deals(ctx, conn)) == []   # once only

    # Only the price moved (D66): like the page, the slides keep the found day, the airline and
    # the baggage of the detected observation, though the recheck's own row has others.
    view = CapturingRenderer.views[-1]
    assert (view.observation_id, view.price) == (latest_obs, pt.eur(59))
    assert view.found_on == pt.numeric_date(obs.found_date) != pt.numeric_date(LATER)
    assert view.baggage_line == pt.baggage_line(False)
    assert meta["detected_observation_id"] == obs.id

    # Expired, the page shows the price it was a promotion at again: so do the slides.
    db.record_recheck(conn, deal_id, valid=False, latest_price=80, reason="subiu", kind="gone")
    expired_obs, _ = page_price(conn, deal_id)
    assert expired_obs == obs.id
    [(_, again)] = pipeline.run_rerender_stale(ctx, conn, site_deals(ctx, conn))
    assert db.get_deal(conn, again.id)[0].rendered_observation_id == obs.id
    assert CapturingRenderer.prices[-1] == pt.eur(58)


def test_a_deal_rendered_before_v21_counts_as_rendered_from_its_own_observation(ctx):
    """No `rendered_observation_id` (rendered before the column): its own observation, so a
    deal without a recheck price is not rendered again."""
    from test_review import rendered_deal
    import test_pipeline
    with respx.mock:
        conn = pipeline.open_db(ctx)
        deal_id = rendered_deal(ctx, conn)
        test_pipeline.mock_links()
    deal, obs = db.get_deal(conn, deal_id)
    assert deal.rendered_observation_id is None
    assert pipeline.stale_renders(conn, [(deal, obs)]) == []
