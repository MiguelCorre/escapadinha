"""Posting queue (D32): when an approved promotion goes out, and through which publisher.

Approving a promotion (an approve event applied by the run, D26) queues one post per channel
(`CHANNELS`): Instagram at the next free daily slot (Lisbon time, `posting.instagram_slots`, at
most `posting.max_per_day` a day), Telegram at once; each row keeps the approval's live-check
time (`Post.checked_at`). Every run, after `detect` and before the path decision (so after this
run's recheck), `pipeline.run_publish` asks `verdict` what to do with each queued post: a
promotion that expired or was rejected cancels it; a due post goes out only if the price was
verified (the last recheck, else the approval's live check) within `posting.max_check_age_hours`.
Publishers are pluggable (`Publisher`); `DryRunPublisher` only logs what would be posted, the
Instagram publisher (`instagram.py`, D36) posts a carousel and then a story (`story_verdict`),
the Telegram publisher (`telegram.py`, D38) a photo message; `Paused` waits for their secrets.

The rules here are pure (no I/O, no clock): `now` is passed in.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Protocol, runtime_checkable

from escapadinha import i18n_pt
from escapadinha.i18n_pt import LISBON
from escapadinha.models import Deal, Observation, Post
from escapadinha.review import STATUS_PT
from escapadinha.storage.db import OPEN_STATUSES      # the statuses a run rechecks

# The channels a promotion is queued on: the one list (config validation and defaults, the queue
# planner; the SQL CHECK in schema.sql/db.py is tested against it).
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

class VerdictAction(StrEnum):
    """What `verdict` says to do with a queued post."""

    PUBLISH = "publish"     # due and verified recently: post it now
    LATER = "later"         # not due yet
    WAIT = "wait"           # due, but the price was not verified recently: a later run decides
    CANCEL = "cancel"       # can never go out (reason given)


class PostAction(StrEnum):
    """What the publish step did with a post (`pipeline.PostResult`)."""

    PUBLISHED = "published"
    CANCELLED = "cancelled"
    WAITING = "waiting"
    FAILED = "failed"       # publisher error, retried next run


class StoryStatus(StrEnum):
    """The story that follows a published Instagram carousel (`posting_queue.story_status`, D36;
    the SQL CHECK is tested against it). NULL in the table: no story for this post."""

    PENDING = "pending"         # the carousel is out, the story not yet
    PUBLISHED = "published"
    SKIPPED = "skipped"         # will not go out (reason in story_note)


@dataclass(frozen=True)
class Verdict:
    action: VerdictAction
    reason: str | None = None


def verdict(post: Post, deal: Deal, *, now: datetime, max_check_age: timedelta) -> Verdict:
    """What the run does with a queued post now. A promotion that can no longer go out cancels
    the post whether or not it is due. A due post goes out only if the price was verified within
    `max_check_age`: the last recheck (`deal.last_checked_at`) or else the approval's live check
    (`post.checked_at`, the event's `live_check.checked_at`, which can be earlier than the
    approval itself). Unverified, it waits for a recheck while the promotion is still rechecked;
    one marked published is not rechecked any more, so its post is cancelled instead (D32)."""
    cancel = VerdictAction.CANCEL
    if deal.status == "expired":
        why = f": {deal.expired_reason}" if deal.expired_reason else ""
        return Verdict(cancel, f"A promoção expirou{why}.")
    if deal.status == "rejected":
        return Verdict(cancel, "A promoção foi rejeitada.")
    if deal.status == "published" and post.channel == "instagram":
        return Verdict(cancel, "A promoção já foi marcada como publicada no Instagram.")
    if deal.status not in ("approved", "published"):
        return Verdict(cancel, f"A promoção não está aprovada ({STATUS_PT[deal.status]}).")
    if not deal.affiliate_url:
        return Verdict(cancel, "A promoção não tem link de afiliado.")
    if post.due_at > now:
        return Verdict(VerdictAction.LATER)
    verified = max((t for t in (deal.last_checked_at, post.checked_at) if t), default=None)
    if verified is not None and now - verified <= max_check_age:
        return Verdict(VerdictAction.PUBLISH)
    hours = i18n_pt.number(max_check_age.total_seconds() / 3600)
    if deal.status not in OPEN_STATUSES:        # never rechecked again: waiting would be forever
        return Verdict(cancel, f"A promoção foi marcada como publicada e já não é verificada: o "
                               f"preço confirmado tem mais de {hours} h.")
    return Verdict(VerdictAction.WAIT, f"Preço verificado há mais de {hours} h: espera por uma "
                                       "recolha que o confirme.")


def story_verdict(post: Post, deal: Deal, *, now: datetime, max_check_age: timedelta) -> Verdict:
    """What the run does with the pending story of a published Instagram post (D36): it shows
    the cover slide, a price, so it goes out only while the carousel's verification still
    holds (`max_check_age` after the carousel went out) and the promotion did not expire or
    get rejected since; otherwise it is skipped with the reason, never retried forever."""
    skip = VerdictAction.CANCEL
    if deal.status == "expired":
        return Verdict(skip, "A promoção expirou: a story já não sai.")
    if deal.status == "rejected":
        return Verdict(skip, "A promoção foi rejeitada: a story já não sai.")
    if post.settled_at is not None and now - post.settled_at > max_check_age:
        hours = i18n_pt.number(max_check_age.total_seconds() / 3600)
        return Verdict(skip, f"A story não saiu nas {hours} h a seguir ao carrossel: já não sai.")
    return Verdict(VerdictAction.PUBLISH)


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
    # The promotion is now out on its main channel: the run writes a `published` review event
    # (D26), which the next run applies; a publisher never changes a status itself (D36).
    marks_published: bool = False
    story: bool = False     # a story follows (`Publisher.publish_story`), retried on its own


@dataclass(frozen=True)
class Attempt:
    """What one publisher call came to (`attempt`): its result, or why it waits, is cancelled
    or failed (pt-PT; a failure is `Type: message`)."""

    result: object = None
    wait: str | None = None
    cancel: str | None = None
    error: str | None = None


def attempt(call: Callable[[], object]) -> Attempt:
    """Run a publisher call; its signals (`PublishWait`, `PublishCancel`, any other error, which
    never stops the run) as data, so the post and the story ladders read the same."""
    try:
        return Attempt(result=call())
    except PublishWait as wait:
        return Attempt(wait=str(wait))
    except PublishCancel as cancel:
        return Attempt(cancel=str(cancel))
    except Exception as exc:
        return Attempt(error=f"{type(exc).__name__}: {exc}")


class PublishWait(Exception):
    """Not now, through no fault of the post (images not deployed yet, API limit, token):
    it stays queued and no attempt is counted. `str(exc)` says why (pt-PT)."""


class PublishCancel(Exception):
    """The post can never go out as it is (e.g. Meta refuses the media): it is cancelled with
    `str(exc)` as the reason (pt-PT)."""


class RetryableSendError(RuntimeError):
    """A failure the run retries: the post stays queued and an attempt is counted (D32's
    max_attempts ends it)."""


def redact(text: str, secret: str) -> str:
    """`text` without `secret` (a token in an API's error text or URL)."""
    return text.replace(secret, "***") if secret else text


def live_images(urls: list[str], check: Callable[[str], str | None], *, due_at: datetime | None,
                now: datetime, wait: timedelta) -> list[str]:
    """`urls` (a promotion's JPEGs on the public site, D36) once every one is live, by `check`
    (None = live, else what is wrong). The deploy that carries them may still be to come (a new
    approval's full path runs after the publish step): waiting is free until `wait` after
    `due_at`, then each wait is a failure, so max_attempts ends a post whose images never
    arrive. `due_at` None (a story): always free."""
    if not urls:
        raise PublishCancel("A promoção não tem slides renderizados.")
    for url in urls:
        problem = check(url)
        if problem:
            if due_at is not None and now - due_at > wait:
                hours = i18n_pt.number(wait.total_seconds() / 3600)
                raise RetryableSendError(f"As imagens continuam sem estar no site mais de {hours} "
                                         f"h depois da hora marcada ({url} → {problem}).")
            raise PublishWait(f"As imagens ainda não estão no site ({url} → {problem}): espera "
                              "pelo próximo deploy.")
    return urls


@runtime_checkable
class Publisher(Protocol):
    """Posts a message to one channel. Raises `PublishWait` to wait without counting an attempt,
    `PublishCancel` to cancel, anything else on a failure the run retries (D32's max_attempts)."""

    name: str

    def publish(self, message: Message) -> Published: ...


@runtime_checkable
class StoryPublisher(Publisher, Protocol):
    """A publisher whose `publish` can return `Published(story=True)`: the story is posted
    afterwards on its own (its media id, None when out but unknown), same exceptions."""

    def publish_story(self, post: Post, deal: Deal) -> str | None: ...


def publisher_actor(name: str) -> str:
    """The actor of the `published` decision a real publisher's post writes: 'instagram-publisher'."""
    return f"{name}-publisher"


class Paused:
    """A channel while it can't post (no secrets): every due post waits, no attempt counted,
    the reason in `queue list`. Never a dry run, which would settle the post (D36)."""

    def __init__(self, name: str, reason: str):
        self.name, self.reason = name, reason

    def publish(self, message: Message) -> Published:
        raise PublishWait(self.reason)


class DryRunPublisher:
    """Posts nothing (no network): logs what would be posted. Only for a channel configured as
    `dry-run`; a real publisher that can't post (no secrets) waits instead (D36)."""

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
