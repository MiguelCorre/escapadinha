"""Posting queue (D32): when an approved promotion goes out, and through which publisher.

Approving a promotion (an approve event applied by the run, D26) queues one post per channel:
Instagram at the next free daily slot (Lisbon time, `posting.instagram_slots`, at most
`posting.max_per_day` a day), Telegram at once. Every run, right after the recheck, publishes
the posts that are due after re-verifying the promotion; a promotion that expired, was rejected
or was not re-verified recently enough never goes out (`blocker`). Publishers are pluggable
(`Publisher`); `DryRunPublisher` only logs what would be posted.

The slot rules here are pure (no I/O, no clock): `now` is passed in.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol

from escapadinha import i18n_pt
from escapadinha.i18n_pt import LISBON
from escapadinha.models import Deal, Observation, Post
from escapadinha.review import STATUS_PT

CHANNELS = ("instagram", "telegram")
CHANNEL_PT = {"instagram": "Instagram", "telegram": "Telegram"}
STATUS_PT_POST = {"queued": "agendada", "published": "publicada", "cancelled": "cancelada"}
_SEARCH_DAYS = 400          # every slot of a day can only be taken by a finite queue


def _at(day: date, at: time) -> datetime:
    """`at` on `day` in Lisbon, as UTC. A time skipped by the March clock change is read with
    the winter offset (01:30 -> 02:30 summer time); a repeated October time is the first one."""
    return datetime.combine(day, at, tzinfo=LISBON).astimezone(timezone.utc)


def next_slot(now: datetime, taken: list[datetime], *, slots: list[time],
              max_per_day: int) -> datetime:
    """The first daily slot at or after `now` that no post holds, on a Lisbon day with fewer
    than `max_per_day` posts. `taken`: due times of the channel's queued and published posts."""
    if not slots:
        raise ValueError("no posting slots configured")
    if max_per_day < 1:
        raise ValueError("max_per_day must be at least 1")
    held = {t.astimezone(timezone.utc) for t in taken}
    per_day: dict[date, int] = {}
    for t in held:
        day = t.astimezone(LISBON).date()
        per_day[day] = per_day.get(day, 0) + 1
    today = now.astimezone(LISBON).date()
    for offset in range(_SEARCH_DAYS):
        day = today + timedelta(days=offset)
        if per_day.get(day, 0) >= max_per_day:
            continue
        for at in sorted(slots):
            candidate = _at(day, at)
            if candidate >= now and candidate not in held:
                return candidate
    raise ValueError("no free posting slot found")


# --- re-verification before posting --------------------------------------------------------

@dataclass(frozen=True)
class Verdict:
    action: str             # publish | later (not due) | wait (due, not re-verified) | cancel
    reason: str | None = None


def verdict(post: Post, deal: Deal, *, now: datetime, max_check_age: timedelta) -> Verdict:
    """What the run does with a queued post now. A promotion that can no longer go out cancels
    the post whenever it is due; a due post goes out only if the promotion's price was verified
    (recheck, else the approval's live check) within `max_check_age`."""
    if deal.status == "expired":
        why = f": {deal.expired_reason}" if deal.expired_reason else ""
        return Verdict("cancel", f"A promoção expirou{why}.")
    if deal.status == "rejected":
        return Verdict("cancel", "A promoção foi rejeitada.")
    if deal.status == "published" and post.channel == "instagram":
        return Verdict("cancel", "A promoção já foi marcada como publicada no Instagram.")
    if deal.status not in ("approved", "published"):
        return Verdict("cancel", f"A promoção não está aprovada ({STATUS_PT[deal.status]}).")
    if not deal.affiliate_url:
        return Verdict("cancel", "A promoção não tem link de afiliado.")
    if post.due_at > now:
        return Verdict("later")
    verified = max((t for t in (deal.last_checked_at, deal.reviewed_at) if t), default=None)
    if verified is None or now - verified > max_check_age:
        hours = i18n_pt.number(max_check_age.total_seconds() / 3600)
        return Verdict("wait", f"Preço verificado há mais de {hours} h: espera por uma recolha "
                                 "que o confirme.")
    return Verdict("publish")


# --- publishers ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Message:
    """What a publisher posts: one queued post of one promotion."""

    post: Post
    deal: Deal
    observation: Observation
    headline: str           # 'Lisboa → Paris (Beauvais)'
    price: str              # '58 €'
    text: str               # Instagram: the caption; Telegram: the short text (with the link)
    link: str               # the promotion's stored partner link


@dataclass(frozen=True)
class Published:
    url: str | None = None  # the post's URL, when the channel gives one


class Publisher(Protocol):
    """Posts a message to one channel; raises on failure (the run retries it later)."""

    name: str

    def publish(self, message: Message) -> Published: ...


class DryRunPublisher:
    """Posts nothing (no network): logs what would be posted."""

    name = "dry-run"

    def __init__(self, log: Callable[[str], None]):
        self.log = log

    def publish(self, message: Message) -> Published:
        post = message.post
        self.log(f"[dry-run] {CHANNEL_PT[post.channel]} · deal {post.deal_id} · "
                 f"{message.headline} · {message.price} · agendada para "
                 f"{i18n_pt.lisbon_timestamp(post.due_at)}")
        for line in message.text.rstrip().splitlines():
            self.log(f"    {line}")
        return Published(None)


def publishers(names: dict[str, str], log: Callable[[str], None]) -> dict[str, Publisher]:
    """channel -> publisher, from `posting.publishers` in config."""
    known: dict[str, Callable[[], Publisher]] = {"dry-run": lambda: DryRunPublisher(log)}
    return {channel: known[name]() for channel, name in names.items()}
