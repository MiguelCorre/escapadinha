"""Telegram publisher (D38): an approved promotion as one photo message in the public channel.

Bot API `sendPhoto` (`config.TELEGRAM_API`), `chat_id` = the channel's @handle
(`TELEGRAM_CHANNEL`), the bot an admin of the channel allowed to post:

1. the photo is the promotion's cover JPEG on the public site (`website.public_jpeg_urls`,
   the first slide), which Telegram fetches by URL; it must answer a HEAD with 200 (the
   pipeline's `instagram.image_problem`), else the post waits for the deploy, without counting
   an attempt until `telegram.images_wait_hours` after it was due (as Instagram's, D36);
2. the caption is the post's text (`captions.whatsapp_text`: the stored partner link and
   `DISCLOSURE`), plain text, never cut: longer than Telegram's 1024 characters (UTF-16 code
   units) it is cancelled, since cutting it could drop the link or the disclosure;
3. before sending, a record of the attempt is written to the object store
   (`record_key(deal_id)`, durable at once, unlike the database, which reaches R2 only when the
   run ends, D21); after Telegram's answer it holds the message id and link. Telegram lets a
   bot neither list a channel's posts nor send idempotently, so this record is what stops a
   duplicate: a send whose answer was lost (a timeout after the request went out, an unreadable
   answer, a job killed before it saved the answer) is **cancelled, never resent** ("confirma
   no canal"); a send Telegram refused, or that never reached it, removes the record and is
   retried. A promotion sent with a lost database is adopted from the record, not sent again.

Bot API errors become the queue's signals (`TelegramPublisher._signal`): 429 waits (no attempt
counted); 401 (the token) waits with a notice; 400/403 about the photo is a failure (retried);
any other 400/403 (chat not found, the bot not an admin) cancels with a pt-PT reason and leaves
a notice for `queue list` (meta `telegram.problem`, cleared by the next message that goes out);
anything else is a failure, retried up to `posting.max_attempts`. The token is part of the
request URL: it never appears in an error, a log or the database (`BotApi` reports transport
errors by type only and removes it from any text).

The message never marks the promotion published (Instagram is its main channel, D36: a
`published` promotion cancels its Instagram post); its link is the queue row's `result_url`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta

import httpx

from escapadinha import i18n_pt
from escapadinha.config import TELEGRAM_API
from escapadinha.models import Deal, Post
from escapadinha.posting import Message, Published, PublishCancel, PublishWait
from escapadinha.storage import db
from escapadinha.storage.objects import ObjectStore

RUNBOOK = "docs/runbooks/telegram.md"
CAPTION_LIMIT = 1024                    # a photo caption, in UTF-16 code units
RECORDS = "posting/telegram/"           # object store: one record per promotion sent
PROBLEM_META = "telegram.problem"       # meta: what `queue list` says until a message goes out
# Fragments of Telegram's 400 descriptions about the photo (it could not fetch or read it):
# failures, retried, never a cancelled post.
PHOTO_ERRORS = ("http url", "web page", "file identifier", "image_process", "photo_")


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


class TelegramError(RuntimeError):
    """A failure the run retries (attempt counted, D32)."""


class BotApi:
    """Bot API calls with one token (in the URL path, as Telegram documents)."""

    def __init__(self, http: httpx.Client, token: str):
        self.http, self.token = http, token

    def _redact(self, text: str) -> str:
        return text.replace(self.token, "***") if self.token else text

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
            raise BotApiError(self._redact(str(body.get("description") or "erro sem mensagem")),
                              status=response.status_code,
                              code=code if isinstance(code, int) else None,
                              retry_after=extra.get("retry_after"))
        result = body.get("result")
        if not isinstance(result, dict):
            raise NoAnswer(f"resposta da API sem resultado (HTTP {response.status_code})",
                           sent=True)
        return result


def chat_id(channel: str) -> str:
    """`TELEGRAM_CHANNEL` as the Bot API's `chat_id`: the @handle ('pontonomada' gains its @),
    or a numeric id as given."""
    channel = channel.strip()
    if channel.startswith("@") or channel.lstrip("-").isdigit():
        return channel
    return f"@{channel.removeprefix('https://t.me/')}"


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
        photo = self._live_cover(deal, post)
        key = record_key(deal.id)
        record = {"deal_id": deal.id, "observation_id": deal.observation_id, "post_id": post.id,
                  "chat": self.chat, "started_at": db.utc_iso(self.now)}
        self._write(key, record)                # before the request: a lost answer is known
        try:
            sent = self.api.call("sendPhoto", chat_id=self.chat, photo=photo, caption=caption)
        except NoAnswer as err:
            if not err.sent:
                self.store.delete(key)
                raise TelegramError(f"Sem ligação ao Telegram ({err}): nada foi enviado.") \
                    from None
            reason = (f"O Telegram não respondeu ao envio ({err}): a mensagem pode ter saído. "
                      f"{self._confirm()}")
            self.log(f"Telegram: deal {deal.id}: {reason}")
            raise PublishCancel(reason) from None
        except BotApiError as err:              # refused: nothing went out
            self.store.delete(key)
            raise self._signal(err) from None
        message_id = sent.get("message_id")
        if message_id is None:
            raise PublishCancel(f"O Telegram aceitou a mensagem mas não disse qual é. "
                                f"{self._confirm()}")
        url = message_link(sent)
        try:
            self._write(key, {**record, "message_id": str(message_id), "url": url,
                              "sent_at": db.utc_iso(self.now)})
        except Exception as exc:                # it is out: the database still records it
            self.log(f"Telegram: deal {deal.id} enviado, mas o registo do envio não foi "
                     f"guardado ({type(exc).__name__}).")
        self.save(post.id, message_id=str(message_id))
        self.problem(None)
        return Published(url)

    def _earlier_send(self, post: Post, deal: Deal) -> Published | None:
        """An earlier attempt's record: its message adopted, or, without an answer, the post
        cancelled (it may be out). None when this promotion was never sent."""
        try:
            record = json.loads(self.store.get(record_key(deal.id)))
        except KeyError:
            return None
        if record.get("observation_id") != deal.observation_id:   # another promotion's id
            return None
        if record.get("message_id"):
            self.save(post.id, message_id=record["message_id"])
            self.log(f"Telegram: a mensagem do deal {deal.id} já tinha saído "
                     f"({record.get('url') or record['message_id']}): não volta a ser enviada.")
            return Published(record.get("url"))
        started = i18n_pt.lisbon_timestamp(datetime.fromisoformat(record["started_at"]))
        raise PublishCancel(f"Uma tentativa anterior ({started}) enviou a mensagem ao Telegram "
                            f"sem guardar a resposta: pode ter saído. {self._confirm()}")

    def _confirm(self) -> str:
        return (f"Confirma no canal {self.chat}; não é enviada outra vez, para não sair "
                "repetida.")

    def _write(self, key: str, record: dict) -> None:
        self.store.put(key, json.dumps(record, ensure_ascii=False).encode("utf-8"))

    def _live_cover(self, deal: Deal, post: Post) -> str:
        """The cover JPEG's public URL, once it is live (the deploy that carries it may still
        be to come: a new approval's full path runs after the publish step). Waiting is free
        until `images_wait` after the post was due, then each wait is a failure, so D32's
        max_attempts ends a post whose image never arrives."""
        urls = self.image_urls(deal)
        if not urls:
            raise PublishCancel("A promoção não tem slides renderizados.")
        cover = urls[0]
        problem = self.check_image(cover)
        if problem:
            if self.now - post.due_at > self.images_wait:
                hours = i18n_pt.number(self.images_wait.total_seconds() / 3600)
                raise TelegramError(f"A imagem continua sem estar no site mais de {hours} h "
                                    f"depois da aprovação ({cover} → {problem}).")
            raise PublishWait(f"A imagem ainda não está no site ({cover} → {problem}): espera "
                              "pelo próximo deploy.")
        return cover

    def _signal(self, err: BotApiError) -> Exception:
        """A refusal as the queue's signal (pt-PT reason)."""
        code = err.code or err.status
        text = err.description.lower()
        if code == 429:
            after = f" (tenta daqui a {err.retry_after} s)" if err.retry_after else ""
            return PublishWait(f"Limite de mensagens do Telegram{after}: espera pela próxima "
                               "execução.")
        if code == 401:
            reason = (f"O Telegram recusou o token do bot ({err}): confirma TELEGRAM_BOT_TOKEN "
                      f"({RUNBOOK}); as publicações esperam.")
            self.problem(reason)
            self.log(f"Telegram: {reason}")
            return PublishWait(reason)
        if code in (400, 403) and any(hint in text for hint in PHOTO_ERRORS):
            return TelegramError(f"O Telegram não conseguiu usar a imagem ({err}).")
        if code == 400 and "caption" in text:
            return PublishCancel(f"O Telegram recusou o texto da mensagem ({err}).")
        if code in (400, 403):
            reason = (f"O Telegram recusou a mensagem ({err}): confirma que o canal {self.chat} "
                      f"existe e que o bot é administrador com permissão para publicar "
                      f"({RUNBOOK}).")
            self.problem(reason)
            self.log(f"Telegram: {reason}")
            return PublishCancel(reason)
        return TelegramError(f"Erro da API do Telegram: {err}")


def problem_state(conn, reason: str | None) -> None:
    """A channel problem for `queue list` (`reason`), or a message went out (None: it goes)."""
    if reason:
        db.set_meta(conn, PROBLEM_META, reason)
    elif db.get_meta(conn, PROBLEM_META) is not None:
        db.delete_meta(conn, PROBLEM_META)


def notices(conn) -> list[str]:
    """What `queue list` says about the channel (pt-PT)."""
    reason = db.get_meta(conn, PROBLEM_META)
    return [reason] if reason else []
