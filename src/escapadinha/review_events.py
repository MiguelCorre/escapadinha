"""Review decisions as an append-only event log in the object store (D26).

A reviewer (CLI, local review page, review Function on Cloudflare) never changes a deal's
status: it writes one event object under `review/events/pending/`. The pipeline applies pending
events oldest first (`apply_pending`), re-checking each against the deal's status at that moment,
and moves every event to `review/events/archive/<YYYY-MM>/` with its outcome. The shape is the
contract in `contract/review/v1/event.schema.json`.

Idempotency: the database records each event's outcome (meta `review_event:<id>`) in the same
transaction as the status change. An event recorded there is never applied again, whatever its
pending/archive objects look like. With R2 the database only becomes durable when the run pushes
it, so an event applied by a run stays pending until a later run, starting from the pushed
database, finds it recorded; a run that dies before pushing just applies it again.
"""

from __future__ import annotations

import getpass
import json
import re
import socket
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from escapadinha import i18n_pt
from escapadinha.recheck import Recheck
from escapadinha.review import DECISIONS, ReviewError, check_decision
from escapadinha.storage import db
from escapadinha.storage.objects import ObjectStore

VERSION = 1
PENDING = "review/events/pending/"
ARCHIVE = "review/events/archive/"
_NAME = re.compile(r"^(\d{4})(\d{2})\d{2}T\d{6}Z-.+\.json$")


def _parse_time(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"'{field}' em falta")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"'{field}' não é uma data ISO 8601: {value!r}") from None
    if dt.tzinfo is None:
        raise ValueError(f"'{field}' sem fuso horário: {value!r}")
    return dt.astimezone(timezone.utc)


def local_actor(tool: str) -> str:
    """'cli:miguel@DESKTOP': who decided, for decisions made on this machine."""
    try:
        user = getpass.getuser()
    except Exception:
        user = "?"
    return f"{tool}:{user}@{socket.gethostname()}"


@dataclass(frozen=True)
class LiveCheck:
    """The price check done right before an approval (by the CLI, page or Function)."""

    valid: bool
    price_eur: float | None
    reason: str
    checked_at: datetime

    @classmethod
    def from_recheck(cls, result: Recheck, at: datetime) -> LiveCheck:
        return cls(result.valid, result.latest_price, result.reason, at)


@dataclass(frozen=True)
class Event:
    id: str
    type: str                     # approve | reject | published
    deal_id: int
    created_at: datetime
    actor: str                    # 'cli:user@host', 'review-page:...', or the Access e-mail
    note: str | None = None
    post_url: str | None = None   # published only
    live_check: LiveCheck | None = None   # approve only (required there)

    @classmethod
    def new(cls, type: str, deal_id: int, *, actor: str, now: datetime, note: str | None = None,
            post_url: str | None = None, live_check: LiveCheck | None = None) -> Event:
        return cls(str(uuid.uuid4()), type, deal_id, now.replace(microsecond=0), actor,
                   note or None, post_url or None, live_check)

    @property
    def key(self) -> str:
        """Pending object key: sorts by creation time, unique by id."""
        return f"{PENDING}{self.created_at:%Y%m%dT%H%M%SZ}-{self.id}.json"

    def to_json(self) -> dict:
        lc = self.live_check
        return {
            "version": VERSION,
            "id": self.id,
            "type": self.type,
            "deal_id": self.deal_id,
            "created_at": db.utc_iso(self.created_at),
            "actor": self.actor,
            "note": self.note,
            "post_url": self.post_url,
            "live_check": None if lc is None else {
                "valid": lc.valid, "price_eur": lc.price_eur, "reason": lc.reason,
                "checked_at": db.utc_iso(lc.checked_at)},
        }

    @classmethod
    def from_json(cls, data: object) -> Event:
        """Raises ValueError (pt-PT reason) on anything the schema would reject."""
        if not isinstance(data, dict):
            raise ValueError("o evento não é um objeto JSON")
        if data.get("version") != VERSION:
            raise ValueError(f"versão do evento não suportada: {data.get('version')!r}")
        if data.get("type") not in DECISIONS:
            raise ValueError(f"tipo de evento desconhecido: {data.get('type')!r}")
        try:
            event_id = str(uuid.UUID(str(data.get("id"))))
        except ValueError:
            raise ValueError(f"'id' não é um UUID: {data.get('id')!r}") from None
        deal_id = data.get("deal_id")
        if not isinstance(deal_id, int) or isinstance(deal_id, bool) or deal_id < 1:
            raise ValueError(f"'deal_id' inválido: {deal_id!r}")
        actor = data.get("actor")
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError("'actor' em falta")
        for field in ("note", "post_url"):
            if data.get(field) is not None and not isinstance(data[field], str):
                raise ValueError(f"'{field}' tem de ser texto")
        lc = data.get("live_check")
        live_check = None
        if lc is not None:
            if not isinstance(lc, dict) or not isinstance(lc.get("valid"), bool) \
                    or not isinstance(lc.get("reason"), str):
                raise ValueError("'live_check' inválido")
            price = lc.get("price_eur")
            if price is not None and (not isinstance(price, int | float) or isinstance(price, bool)):
                raise ValueError("'live_check.price_eur' inválido")
            live_check = LiveCheck(lc["valid"], price, lc["reason"],
                                   _parse_time(lc.get("checked_at"), "live_check.checked_at"))
        return cls(event_id, data["type"], deal_id, _parse_time(data.get("created_at"), "created_at"),
                   actor, data.get("note"), data.get("post_url"), live_check)


@dataclass(frozen=True)
class Outcome:
    """What applying one event did. Stored in the database and in the archived event."""

    event_id: str
    type: str | None
    deal_id: int | None
    actor: str | None
    outcome: str                  # applied | refused | malformed
    reason: str | None            # pt-PT, why it was refused / malformed
    settled_at: datetime
    status_before: str | None = None
    status_after: str | None = None

    @property
    def applied(self) -> bool:
        return self.outcome == "applied"

    def to_json(self) -> dict:
        return {"event_id": self.event_id, "type": self.type, "deal_id": self.deal_id,
                "actor": self.actor, "outcome": self.outcome, "reason": self.reason,
                "settled_at": db.utc_iso(self.settled_at), "status_before": self.status_before,
                "status_after": self.status_after}

    @classmethod
    def from_json(cls, data: dict) -> Outcome:
        return cls(data["event_id"], data["type"], data["deal_id"], data["actor"], data["outcome"],
                   data["reason"], _parse_time(data["settled_at"], "settled_at"),
                   data.get("status_before"), data.get("status_after"))


# --- store ------------------------------------------------------------------------------

def write(store: ObjectStore, event: Event) -> str:
    store.put(event.key, json.dumps(event.to_json(), ensure_ascii=False, indent=2).encode("utf-8"))
    return event.key


def _read(store: ObjectStore, key: str) -> tuple[object, Event | None, str | None]:
    """(raw content, event or None, why it is malformed)."""
    data = store.get(key)
    try:
        raw = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return data.decode("utf-8", "replace"), None, "o objeto não é JSON válido"
    try:
        return raw, Event.from_json(raw), None
    except ValueError as exc:
        return raw, None, str(exc)


def pending(store: ObjectStore, conn: sqlite3.Connection) -> list[Event]:
    """Events waiting for the pipeline, oldest first. Events this database already applied (kept
    pending until the next run, see the module doc) and malformed objects are left out."""
    events = []
    for key in store.list(PENDING):
        try:
            _, event, _ = _read(store, key)
        except KeyError:
            continue                               # settled meanwhile
        if event is not None and db.review_event_outcome(conn, event.id) is None:
            events.append(event)
    return events


def _archive_key(pending_key: str, now: datetime) -> str:
    name = pending_key.removeprefix(PENDING)
    m = _NAME.match(name)
    month = f"{m.group(1)}-{m.group(2)}" if m else f"{now:%Y-%m}"
    return f"{ARCHIVE}{month}/{name.replace('/', '_')}"


def _archive(store: ObjectStore, key: str, raw: object, outcome: Outcome, now: datetime) -> None:
    """Archive first, then delete. A store error is swallowed: the event stays pending, and as
    the database already has its outcome the next pass only archives it again (same key)."""
    body = {"event": raw, **outcome.to_json()}
    try:
        store.put(_archive_key(key, now),
                  json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8"))
        store.delete(key)
    except Exception:
        pass


def _check_age(event: Event, now: datetime, approve_max_age: timedelta | None) -> None:
    """An approval rests on a live price check: past `approve_max_age` (from the check, else from
    the event's creation) it no longer says anything about today's price."""
    if event.type != "approve" or approve_max_age is None:
        return
    checked = event.live_check.checked_at if event.live_check else event.created_at
    if now - checked > approve_max_age:
        hours = i18n_pt.number(approve_max_age.total_seconds() / 3600)
        raise ReviewError(f"Aprovação com mais de {hours} h: verifica o preço outra vez.")


PlanPosts = Callable[[sqlite3.Connection, int, datetime], list[tuple[str, datetime]]]


def _decide(conn: sqlite3.Connection, event: Event, now: datetime,
            approve_max_age: timedelta | None = None,
            plan_posts: PlanPosts | None = None) -> Outcome:
    """Validate against the current status, then record (and apply) in one transaction."""
    def done(outcome: str, reason: str | None = None, before: str | None = None,
             after: str | None = None) -> Outcome:
        return Outcome(event.id, event.type, event.deal_id, event.actor, outcome, reason, now,
                       before, after)

    try:
        deal, _ = db.get_deal(conn, event.deal_id)
    except KeyError:
        result = done("refused", f"o deal {event.deal_id} não existe")
        db.settle_review_event(conn, event.id, result.to_json())
        return result
    try:
        target = check_decision(event.type, deal.status, affiliate_url=deal.affiliate_url,
                                post_url=event.post_url)
        if event.type == "approve" and not (event.live_check and event.live_check.valid):
            raise ReviewError("Aprovação sem uma verificação de preço válida.")
        _check_age(event, now, approve_max_age)
    except ReviewError as exc:
        result = done("refused", str(exc), deal.status, deal.status)
        db.settle_review_event(conn, event.id, result.to_json())
        return result
    result = done("applied", None, deal.status, target)
    posts = plan_posts(conn, deal.id, now) if plan_posts and event.type == "approve" else []
    db.settle_review_event(conn, event.id, result.to_json(), deal_id=deal.id, status=target,
                           note=event.note, post_url=event.post_url, at=event.created_at,
                           posts=posts)
    return result


def apply_pending(store: ObjectStore, conn: sqlite3.Connection, *, now: datetime,
                  durable: bool, approve_max_age: timedelta | None = None,
                  plan_posts: PlanPosts | None = None) -> list[Outcome]:
    """Apply every pending event, oldest first; returns the outcomes decided by this call.

    `durable`: the database is saved as soon as it commits (no R2), so events are archived at
    once. Otherwise (a `run` with R2, pushed at its end) an event is archived by the first call
    whose database already has its outcome. Malformed objects are archived at once; nothing
    here raises for a bad event. `approve_max_age`: an approve event whose live check (else its
    creation) is older than this at `now` is refused (`review.approve_max_age_hours`).
    `plan_posts(conn, deal_id, now)`: the (channel, due_at) posts an applied approval queues,
    written with its status change (posting queue, D32).
    """
    decided = []
    for key in store.list(PENDING):
        try:
            raw, event, malformed = _read(store, key)
        except KeyError:
            continue
        if event is None:
            name = key.removeprefix(PENDING)
            outcome = Outcome(name, None, None, None, "malformed", malformed, now)
            _archive(store, key, raw, outcome, now)
            decided.append(outcome)
            continue
        recorded = db.review_event_outcome(conn, event.id)
        if recorded is not None:
            _archive(store, key, raw, Outcome.from_json(recorded), now)
            continue
        outcome = _decide(conn, event, now, approve_max_age, plan_posts)
        decided.append(outcome)
        if durable:
            _archive(store, key, raw, outcome, now)
    return decided


def recent_outcomes(conn: sqlite3.Connection, limit: int = 20) -> list[Outcome]:
    return [Outcome.from_json(o) for o in db.review_event_outcomes(conn)[:limit]]
