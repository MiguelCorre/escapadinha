"""Local approval queue: `escapadinha review` serves this on 127.0.0.1 only.

Thin HTTP layer over pipeline.live_check / approve / reject / mark_published; every rule
lives in review.py and pipeline.py so the CLI and the page behave the same. Decisions are
written as review events (D26): applied at once with a local database, else listed as pending
until the next run applies them.
"""

from __future__ import annotations

import re
import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from jinja2 import Environment, PackageLoader
from pydantic import BaseModel

from escapadinha import i18n_pt as pt
from escapadinha import pipeline, review_events
from escapadinha.config import Context
from escapadinha.models import Deal, Observation
from escapadinha.presentation import PhotoCredit, build_deal_view
from escapadinha.review import DECISION_PT, STATUS_PT, TABS, ReviewError, UnknownDeal
from escapadinha.storage import db

SLIDE_NAME = re.compile(r"^slide_\d{2}\.png$")


class Note(BaseModel):
    note: str | None = None


class Published(BaseModel):
    post_url: str | None = None


def pending_json(event: review_events.Event) -> dict:
    return {"id": event.id, "type": event.type, "type_pt": DECISION_PT[event.type],
            "actor": event.actor, "note": event.note, "post_url": event.post_url,
            "created_at": pt.lisbon_timestamp(event.created_at)}


def deal_json(ctx: Context, conn: sqlite3.Connection, deal: Deal, obs: Observation,
              pending: list[review_events.Event] = ()) -> dict:
    route = pipeline.route_for(ctx, conn, obs.route_key)
    view = build_deal_view(deal, obs, origin_city=ctx.config.origin_name(obs.origin),
                           destination_city=route.city_pt, photo=PhotoCredit.from_photo(None, None))
    folder = pipeline.deal_folder(ctx, deal)     # downloaded when a runner rendered it (D25)
    caption_file = folder / "caption.txt" if folder else None
    slides = sorted(p.name for p in folder.glob("slide_*.png")) if folder and folder.exists() else []
    return {
        "id": deal.id,
        "status": deal.status,
        "status_pt": STATUS_PT.get(deal.status, deal.status),
        "headline": f"{view.origin_city} → {view.destination_headline}",
        "price": view.price,
        "dates": view.dates,
        "nights": view.nights,
        "airline": view.airline,
        "direct": view.direct,
        "arrival_airport": view.arrival_airport,
        "baggage": view.baggage_line,            # D39: null when unknown (no row)
        "gate": view.gate,
        "rule": deal.rule,
        "discount_pct": view.discount_pct,
        "typical_low": None if deal.baseline_median is None else pt.eur(deal.baseline_median),
        "baseline_days": deal.sample_size,
        "found_on": view.found_on,
        "checked_at": view.checked_at,
        "last_checked_at": pt.lisbon_timestamp(deal.last_checked_at) if deal.last_checked_at else None,
        "last_seen_price": None if deal.last_seen_price is None else pt.eur(deal.last_seen_price),
        "expired_reason": deal.expired_reason,
        "review_note": deal.review_note,
        "affiliate_url": deal.affiliate_url,
        "affiliate_error": deal.affiliate_error,
        "caption": caption_file.read_text("utf-8") if caption_file and caption_file.exists() else None,
        "whatsapp_text": pipeline.whatsapp_for(deal, view),      # approved / published (D32)
        "slides": [f"/deals/{deal.id}/slides/{name}" for name in slides],
        "output_path": deal.output_path,
        "post_url": deal.post_url,
        "published_at": pt.lisbon_timestamp(deal.published_at) if deal.published_at else None,
        "pending": [pending_json(e) for e in pending if e.deal_id == deal.id],
    }


def create_app(ctx: Context, conn_factory=None) -> FastAPI:
    """`conn_factory` returns a fresh connection per request (SQLite objects are per-thread)."""
    connect = conn_factory or (lambda: pipeline.open_db(ctx))
    app = FastAPI(title="Escapadinha: fila de aprovação", docs_url=None, redoc_url=None)
    page = Environment(loader=PackageLoader("escapadinha", "templates"), autoescape=True)

    def with_conn(fn):
        conn: sqlite3.Connection = connect()
        try:
            return fn(conn)
        except UnknownDeal as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ReviewError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Deal não encontrado") from exc
        finally:
            conn.close()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return page.get_template("review.html.j2").render(brand=ctx.config.brand)

    @app.get("/api/deals")
    def list_deals(tab: str = "queue") -> dict:
        if tab not in TABS:
            raise HTTPException(status_code=400, detail="Separador desconhecido")

        def run(conn):
            counts = {t: len(db.deals_with_status(conn, *s)) for t, s in TABS.items()}
            pending = pipeline.pending_decisions(ctx, conn)
            deals = [deal_json(ctx, conn, d, o, pending)
                     for d, o in db.deals_with_status(conn, *TABS[tab])]
            return {"tab": tab, "counts": counts, "deals": deals}
        return with_conn(run)

    @app.get("/deals/{deal_id}/slides/{name}")
    def slide(deal_id: int, name: str) -> FileResponse:
        if not SLIDE_NAME.match(name):
            raise HTTPException(status_code=404)
        deal, _ = with_conn(lambda conn: db.get_deal(conn, deal_id))
        folder = pipeline.deal_folder(ctx, deal)
        path = folder / name if folder else None
        if path is None or not path.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(path, media_type="image/png")

    actor = review_events.local_actor("review-page")

    def action_result(conn, deal: Deal, check=None, decision: pipeline.ReviewResult | None = None) -> dict:
        _, obs = db.get_deal(conn, deal.id)
        out = {"deal": deal_json(ctx, conn, deal, obs, pipeline.pending_decisions(ctx, conn))}
        if check is not None:
            out["check"] = {"valid": check.valid, "reason": check.reason,
                            "latest_price": None if check.latest_price is None
                            else pt.eur(check.latest_price)}
        if decision is not None:
            o = decision.outcome
            out["decision"] = {"event_id": decision.event.id,
                               "outcome": "pending" if o is None else o.outcome,
                               "reason": None if o is None else o.reason}
        return out

    def decided(conn, decision: pipeline.ReviewResult) -> dict:
        return action_result(conn, decision.deal, decision.check, decision)

    @app.post("/api/deals/{deal_id}/check")
    def check(deal_id: int) -> dict:
        return with_conn(lambda conn: action_result(conn, *pipeline.live_check(ctx, conn, deal_id)))

    @app.post("/api/deals/{deal_id}/approve")
    def approve(deal_id: int, body: Note) -> dict:
        return with_conn(lambda conn: decided(
            conn, pipeline.approve(ctx, conn, deal_id, body.note, actor=actor)))

    @app.post("/api/deals/{deal_id}/reject")
    def reject(deal_id: int, body: Note) -> dict:
        return with_conn(lambda conn: decided(
            conn, pipeline.reject(ctx, conn, deal_id, body.note, actor=actor)))

    @app.post("/api/deals/{deal_id}/published")
    def published(deal_id: int, body: Published) -> dict:
        return with_conn(lambda conn: decided(
            conn, pipeline.mark_published(ctx, conn, deal_id, body.post_url, actor=actor)))

    return app
