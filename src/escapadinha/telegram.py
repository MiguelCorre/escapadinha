"""Telegram publisher (D38): an approved promotion as one photo message in the public channel.

Bot API `sendPhoto` (`config.TELEGRAM_API`), `chat_id` = `TELEGRAM_CHANNEL` (the channel's
@handle or numeric id, checked when the secrets load), the bot an admin of the channel allowed
to post:

1. the photo is the promotion's cover JPEG on the public site (`website.public_jpeg_urls`,
   the first slide), which Telegram fetches by URL; it must answer a HEAD with 200 first
   (`posting.live_images`, shared with Instagram: wait for the deploy, bounded by
   `telegram.images_wait_hours` after the post was due);
2. the caption is the post's text (`captions.whatsapp_text`: the stored partner link and
   `DISCLOSURE`), plain text, never cut: longer than Telegram's 1024 characters (UTF-16 code
   units) it is cancelled, since cutting it could drop the link or the disclosure;
3. before sending, a record of the attempt is written to the object store
   (`record_key(deal_id)`, durable at once, unlike the database, which reaches R2 only when the
   run ends, D21); after Telegram's answer it holds the message id and link. Telegram lets a
   bot neither list a channel's posts nor send idempotently, so this record is what stops a
   duplicate: a send whose answer was lost (a timeout after the request went out, an unreadable
   answer, a job killed before it saved the answer) is **cancelled, never resent**; `queue list`
   lists it (`unconfirmed`) until Miguel, having checked the channel, asks for it again
   (`escapadinha queue retry <deal> telegram`: `request_retry`, applied by `apply_retries`). A
   send Telegram refused, or that never reached it, removes the record and is retried. A
   promotion sent with a lost database is adopted from the record, not sent again.

Bot API errors become the queue's signals (`TelegramPublisher._signal`). Their texts are the
Bot API's own (tdlib/telegram-bot-api `Client.cpp`, `fail_query_with_error`: WEBPAGE_CURL_FAILED
→ "Failed to get HTTP URL content", WEBPAGE_MEDIA_EMPTY → "Wrong type of the web page content",
EXTERNAL_URL_INVALID → "Wrong HTTP URL specified"; an all-caps 403 becomes a 400) or MTProto
error names passed through ("Bad Request: CHAT_WRITE_FORBIDDEN"; the names and meanings in
core.telegram.org/method/messages.sendMedia). 429 waits; 401 (the token) and a refused channel
(any 403, `CHANNEL_SETUP` 400s: chat not found, the bot not an admin…) wait with a notice for
`queue list` (meta `telegram.problem`, cleared by the next message that goes out): no post is
lost to a setup mistake; this message refused for good (`PERMANENT`: photo dimensions or
format, caption too long) cancels; a photo Telegram couldn't fetch now (`TRANSIENT_PHOTO`) and
anything else is retried up to `posting.max_attempts`. The token is part of the request URL: it
never appears in an error, a log or the database (`BotApi` reports transport errors by type
only and removes it from any text).

The message never marks the promotion published (Instagram is its main channel, D36: a
`published` promotion cancels its Instagram post); its link is the queue row's `result_url`.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta

import httpx

from escapadinha import i18n_pt, posting
from escapadinha.config import TELEGRAM_API
from escapadinha.models import Deal, Post
from escapadinha.posting import (Message, Published, PublishCancel, PublishWait,
                                 RetryableSendError)
from escapadinha.storage import db
from escapadinha.storage.objects import ObjectStore

RUNBOOK = "docs/runbooks/telegram.md"
CAPTION_LIMIT = 1024                    # a photo caption, in UTF-16 code units
RECORDS = "posting/telegram/"           # object store: one record per promotion sent
PROBLEM_META = "telegram.problem"       # meta: what `queue list` says until a message goes out

# Fragments of the Bot API's error texts (lower case), sources in the module docstring.
CHANNEL_SETUP = ("chat not found", "not a member", "bot was kicked", "not enough rights",
                 "need administrator rights", "chat_write_forbidden", "chat_admin_required",
                 "chat_restricted", "chat_send_photos_forbidden", "chat_send_media_forbidden",
                 "channel_private", "channel_invalid", "peer_id_invalid",
                 "user_banned_in_channel")
PERMANENT = {                           # this message, refused for good: cancelled
    "photo_invalid_dimensions": "dimensões da imagem inválidas",
    "photo_ext_invalid": "formato da imagem inválido",
    "image_process_failed": "o Telegram não conseguiu processar a imagem",
    "wrong http url specified": "o endereço da imagem é inválido",
    "media_caption_too_long": "o texto é demasiado longo",
    "caption is too long": "o texto é demasiado longo",
}
TRANSIENT_PHOTO = ("failed to get http url content", "wrong type of the web page content",
                   "wrong file identifier/http url specified", "photo_save_file_invalid",
                   "can't upload file by url")


class BotApiError(Exception):
    """Telegram answered that it did not do it (`ok: false`); the text never holds the token."""

    def __init__(self, description: str, *, status: int, code: int | None = None,
                 retry_after: int | None = None):
        self.description, self.status, self.code = description, status, code
        self.retry_after = retry_after
        super().__init__(f"{description} (HTTP {status})")


class NoAnswer(Exception):
    """No answer from Telegram that says what happened. `sent` is False only when the request
    never reached it (the connection failed), so it can't have been done."""

    def __init__(self, message: str, *, sent: bool):
        self.sent = sent
        super().__init__(message)


class RetryRefused(ValueError):
    """`queue retry` can't put this post back (pt-PT reason)."""


class BotApi:
    """Bot API calls with one token (in the URL path, as Telegram documents)."""

    def __init__(self, http: httpx.Client, token: str):
        self.http, self.token = http, token

    def call(self, method: str, **params: str) -> dict:
        url = f"{TELEGRAM_API}/bot{self.token}/{method}"
        try:
            response = self.http.post(url, data=params)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise NoAnswer(f"sem ligação à API ({type(exc).__name__})", sent=False) from None
        except httpx.HTTPError as exc:          # its text can hold the URL: never shown raw
            raise NoAnswer(f"sem resposta da API ({type(exc).__name__})", sent=True) from None
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("ok"), bool):
            raise NoAnswer(f"resposta da API ilegível (HTTP {response.status_code})", sent=True)
        if not body["ok"]:
            extra = body.get("parameters") if isinstance(body.get("parameters"), dict) else {}
            code = body.get("error_code")
            text = posting.redact(str(body.get("description") or "erro sem mensagem"), self.token)
            raise BotApiError(text, status=response.status_code,
                              code=code if isinstance(code, int) else None,
                              retry_after=extra.get("retry_after"))
        result = body.get("result")
        if not isinstance(result, dict):
            raise NoAnswer(f"resposta da API sem resultado (HTTP {response.status_code})",
                           sent=True)
        return result


def message_link(sent: dict) -> str | None:
    """The public link of a sent message (`https://t.me/<handle>/<id>`); None for a channel
    without a username (a private one)."""
    username = (sent.get("chat") or {}).get("username")
    return f"https://t.me/{username}/{sent['message_id']}" if username else None


def caption_length(text: str) -> int:
    """Length as Telegram counts it (UTF-16 code units: an emoji is 2)."""
    return len(text.encode("utf-16-le")) // 2


def record_key(deal_id: int) -> str:
    return f"{RECORDS}deal-{deal_id}.json"


def retry_command(deal_id: int) -> str:
    return f"`escapadinha queue retry {deal_id} telegram`"


def confirm(chat: str, deal_id: int) -> str:
    """What Miguel does about a send that may be out (pt-PT)."""
    return (f"Confirma no canal {chat}: não é reenviada sozinha, para não sair repetida; se não "
            f"saiu, {retry_command(deal_id)} volta a pô-la na fila.")


def _read(store: ObjectStore, deal_id: int) -> dict | None:
    try:
        return json.loads(store.get(record_key(deal_id)))
    except KeyError:
        return None


def _write(store: ObjectStore, record: dict) -> None:
    store.put(record_key(record["deal_id"]),
              json.dumps(record, ensure_ascii=False).encode("utf-8"))


class TelegramPublisher:
    """`posting.Publisher` for the telegram channel (D38). Injected: the Bot API client, the
    channel, the object store (the send records), the deal's public JPEG URLs, the image check,
    where progress is saved, the clock and where a channel problem is noted."""

    name = "telegram"

    def __init__(self, api: BotApi, chat: str, *, store: ObjectStore,
                 image_urls: Callable[[Deal], list[str]],
                 check_image: Callable[[str], str | None],
                 save: Callable[..., None], now: datetime, images_wait: timedelta,
                 log: Callable[[str], None] = print,
                 problem: Callable[[str | None], None] = lambda reason: None):
        self.api, self.chat, self.store = api, chat, store
        self.image_urls, self.check_image, self.save = image_urls, check_image, save
        self.now, self.images_wait, self.log, self.problem = now, images_wait, log, problem

    def publish(self, message: Message) -> Published:
        post, deal = message.post, message.deal
        earlier = self._earlier_send(post, deal)
        if earlier is not None:
            return earlier
        caption = message.text.strip()
        if caption_length(caption) > CAPTION_LIMIT:
            raise PublishCancel(f"O texto tem {caption_length(caption)} caracteres e o Telegram "
                                f"aceita {CAPTION_LIMIT} numa foto: não é cortado (perderia o "
                                "link ou o aviso de publicidade).")
        [photo] = posting.live_images(self.image_urls(deal)[:1], self.check_image,
                                      due_at=post.due_at, now=self.now, wait=self.images_wait)
        record = {"deal_id": deal.id, "observation_id": deal.observation_id, "post_id": post.id,
                  "chat": self.chat, "started_at": db.utc_iso(self.now)}
        _write(self.store, record)              # before the request: a lost answer is known
        try:
            sent = self.api.call("sendPhoto", chat_id=self.chat, photo=photo, caption=caption)
        except NoAnswer as err:
            if not err.sent:
                self.store.delete(record_key(deal.id))
                raise RetryableSendError(f"Sem ligação ao Telegram ({err}): nada foi "
                                         "enviado.") from None
            reason = (f"O Telegram não respondeu ao envio ({err}): a mensagem pode ter saído. "
                      f"{confirm(self.chat, deal.id)}")
            self.log(f"Telegram: deal {deal.id}: {reason}")
            raise PublishCancel(reason) from None
        except BotApiError as err:              # refused: nothing went out
            self.store.delete(record_key(deal.id))
            raise self._signal(err) from None
        message_id = sent.get("message_id")
        if message_id is None:
            raise PublishCancel(f"O Telegram aceitou a mensagem mas não disse qual é. "
                                f"{confirm(self.chat, deal.id)}")
        url = message_link(sent)
        try:
            _write(self.store, {**record, "message_id": str(message_id), "url": url,
                                "sent_at": db.utc_iso(self.now)})
        except Exception as exc:                # it is out: the database still records it
            self.log(f"Telegram: deal {deal.id} enviado, mas o registo do envio não foi "
                     f"guardado ({type(exc).__name__}).")
        self.save(post.id, message_id=str(message_id))
        self.problem(None)
        return Published(url)

    def _earlier_send(self, post: Post, deal: Deal) -> Published | None:
        """An earlier attempt's record: its message adopted, or, without an answer, the post
        cancelled (it may be out). None when this promotion was never sent, or Miguel asked
        for it again (`request_retry`)."""
        record = _read(self.store, deal.id)
        if record is None or record.get("observation_id") != deal.observation_id:
            return None                         # never sent (or another promotion's id)
        if record.get("message_id"):
            self.save(post.id, message_id=record["message_id"])
            self.log(f"Telegram: a mensagem do deal {deal.id} já tinha saído "
                     f"({record.get('url') or record['message_id']}): não volta a ser enviada.")
            return Published(record.get("url"))
        if record.get("retry_requested_at"):
            return None
        started = i18n_pt.lisbon_timestamp(datetime.fromisoformat(record["started_at"]))
        raise PublishCancel(f"Uma tentativa anterior ({started}) enviou a mensagem ao Telegram "
                            f"sem guardar a resposta: pode ter saído. "
                            f"{confirm(self.chat, deal.id)}")

    def _signal(self, err: BotApiError) -> Exception:
        """A refusal as the queue's signal (pt-PT reason)."""
        code = err.code or err.status
        text = err.description.lower()
        if code == 429:
            after = f" (tenta daqui a {err.retry_after} s)" if err.retry_after else ""
            return PublishWait(f"Limite de mensagens do Telegram{after}: espera pela próxima "
                               "execução.")
        if code == 401:
            return self._setup_problem(f"O Telegram recusou o token do bot ({err}): confirma "
                                       f"TELEGRAM_BOT_TOKEN ({RUNBOOK}); as publicações esperam.")
        if code in (400, 403):
            why = next((why for hint, why in PERMANENT.items() if hint in text), None)
            if why:
                return PublishCancel(f"O Telegram recusou esta mensagem: {why} ({err}).")
            if any(hint in text for hint in TRANSIENT_PHOTO):
                return RetryableSendError(f"O Telegram não conseguiu ir buscar a imagem ({err}).")
            if code == 403 or any(hint in text for hint in CHANNEL_SETUP):
                return self._setup_problem(
                    f"O Telegram recusou o canal ({err}): confirma que o canal {self.chat} "
                    f"existe e que o bot é administrador com permissão para publicar "
                    f"({RUNBOOK}); as publicações esperam.")
        return RetryableSendError(f"Erro da API do Telegram: {err}")

    def _setup_problem(self, reason: str) -> PublishWait:
        """The bot or the channel set up wrong: every post waits, none lost, until it's fixed."""
        self.problem(reason)
        self.log(f"Telegram: {reason}")
        return PublishWait(reason)


# --- a way back after a lost answer (`escapadinha queue retry`) ------------------------------

def unconfirmed(store: ObjectStore) -> list[dict]:
    """Sends whose answer was lost (no message id) that Miguel hasn't asked for again."""
    records = [json.loads(store.get(key)) for key in store.list(RECORDS)]
    return [r for r in records if not r.get("message_id") and not r.get("retry_requested_at")]


def request_retry(store: ObjectStore, deal: Deal, *, now: datetime) -> None:
    """Miguel checked the channel: the message isn't there. The record says so
    (`retry_requested_at`); the run that owns the database requeues the post
    (`apply_retries`) and its send no longer stops at the record."""
    record = _read(store, deal.id)
    if record is None or record.get("observation_id") != deal.observation_id:
        raise RetryRefused(f"deal {deal.id}: não há nenhum envio ao Telegram por confirmar.")
    if record.get("message_id"):
        where = record.get("url") or f"mensagem {record['message_id']}"
        raise RetryRefused(f"deal {deal.id}: a mensagem do Telegram saiu ({where}): não há "
                           "nada a repor.")
    _write(store, {**record, "retry_requested_at": db.utc_iso(now)})


def apply_retries(conn: sqlite3.Connection, store: ObjectStore, *, log: Callable[[str], None]
                  ) -> list[int]:
    """Requeue the cancelled Telegram posts Miguel asked for again (`request_retry`): only a
    post cancelled for a lost answer (its reason names `retry_command`), so any other
    cancellation (an expiry after the request) stands. Idempotent: the record keeps the request
    until the next send replaces it."""
    done = []
    for key in store.list(RECORDS):
        record = json.loads(store.get(key))
        asked = record.get("retry_requested_at")
        if not asked or record.get("message_id"):
            continue
        post = next((p for p in db.posts(conn, "cancelled")
                     if p.deal_id == record["deal_id"] and p.channel == "telegram"), None)
        if post is None or retry_command(post.deal_id) not in (post.reason or ""):
            continue                            # not cancelled for a lost answer (an expiry)
        deal, _ = db.get_deal(conn, post.deal_id)
        if deal.observation_id != record.get("observation_id"):
            continue
        db.requeue_post(conn, post.id, why="Reposta na fila pelo Miguel depois de confirmar o "
                                           "canal.")
        log(f"Telegram: deal {post.deal_id} voltou à fila (pedido do Miguel).")
        done.append(post.deal_id)
    return done


# --- notices for `queue list` ------------------------------------------------------------------

def problem_state(conn, reason: str | None) -> None:
    """A channel problem for `queue list` (`reason`), or a message went out (None: it goes)."""
    if reason:
        db.set_meta(conn, PROBLEM_META, reason)
    elif db.get_meta(conn, PROBLEM_META) is not None:
        db.delete_meta(conn, PROBLEM_META)


def notices(conn, store: ObjectStore, chat: str) -> list[str]:
    """What `queue list` says about the channel (pt-PT): a refused channel or token, and every
    send to confirm."""
    reason = db.get_meta(conn, PROBLEM_META)
    out = [reason] if reason else []
    for record in unconfirmed(store):
        started = i18n_pt.lisbon_timestamp(datetime.fromisoformat(record["started_at"]))
        out.append(f"Envio ao Telegram por confirmar: deal {record['deal_id']} ({started}). "
                   f"{confirm(record.get('chat') or chat, record['deal_id'])}")
    return out
