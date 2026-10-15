"""Telegram channel publisher (D38) through the pipeline seam (`pipeline.run_publish`), the Bot
API and the site's HEAD answers mocked with respx (no network): the photo message, images not
deployed yet, rate limits, refused chats, ambiguous failures never sent twice, the durable
record, missing secrets, the schema and `queue list`."""

from __future__ import annotations

import json
from datetime import timedelta
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from escapadinha import pipeline, review_events, telegram
from escapadinha.presentation import DISCLOSURE
from escapadinha.storage import db
from test_pipeline import ctx  # noqa: F401
from test_posting import APPLIED, approve_event, approved, by_channel, cli, publish, second_deal, utc

TOKEN = "123456789:AAtest-secret-bot-token"
CHANNEL = "@pontonomada_promos"
SITE = "https://pontonomada.pt"


@pytest.fixture(autouse=True)
def instagram_dry_run(ctx):
    """Only Telegram is under test: Instagram on the dry run (no Graph API calls)."""
    ctx.config.posting.publishers["instagram"] = "dry-run"


def send(ctx, conn, now) -> tuple[list[tuple], list[str]]:
    """A publish step: what it did with the Telegram posts (deal, action), and the log."""
    done, lines = publish(ctx, conn, now)
    return [(deal_id, action) for deal_id, channel, action in done if channel == "telegram"], lines


# --- missing secrets ------------------------------------------------------------------------

WAIT_SECRETS = ("À espera do bot: faltam TELEGRAM_BOT_TOKEN e/ou TELEGRAM_CHANNEL (.env ou "
                "secrets do GitHub, docs/runbooks/telegram.md).")


@respx.mock          # any HTTP request would fail: nothing is sent without the secrets
def test_without_the_secrets_a_due_telegram_post_waits(ctx, monkeypatch):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    done, lines = send(ctx, conn, APPLIED)
    assert done == [(deal_id, "waiting")]
    assert not any("[dry-run] Telegram" in line for line in lines)
    post = by_channel(conn)["telegram"]
    assert (post.status, post.attempts, post.publisher, post.last_error) == (
        "queued", 0, None, WAIT_SECRETS)
    assert "À espera do bot" in cli(ctx, monkeypatch, "queue", "list")


# --- the photo message ----------------------------------------------------------------------

class FakeBot:
    """Telegram's Bot API as far as the publisher uses it: records every call (path and form);
    `answers` queues what the next calls get (a sent message by default)."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.answers: list = []
        self.sent: list[dict] = []
        self._next = 41

    def __call__(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.calls.append((request.url.path, form))
        if self.answers:
            answer = self.answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        self._next += 1
        self.sent.append(form)
        return httpx.Response(200, json={"ok": True, "result": {
            "message_id": self._next, "date": 1764572400,
            "chat": {"id": -1001234567890, "title": "Ponto Nómada", "type": "channel",
                     "username": CHANNEL.lstrip("@")},
            "photo": [{"file_id": "AgAC", "width": 1080, "height": 1350}],
            "caption": form.get("caption")}})


def refused(status: int, description: str, **parameters) -> httpx.Response:
    body = {"ok": False, "error_code": status, "description": description}
    if parameters:
        body["parameters"] = parameters
    return httpx.Response(status, json=body)


@pytest.fixture
def bot(ctx, monkeypatch):
    """The secrets set, the Bot API and the site mocked: every JPEG answers 200 unless a test
    says otherwise (`site_status`)."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHANNEL", CHANNEL)
    fake = FakeBot()
    fake.site_status = 200
    fake.heads = []
    with respx.mock:
        respx.route(host="api.telegram.org").mock(side_effect=fake)

        def head(request):
            fake.heads.append(str(request.url))
            return httpx.Response(fake.site_status)
        respx.head(url__regex=r"^https://pontonomada\.pt/").mock(side_effect=head)
        yield fake


def test_an_approved_promotion_goes_out_as_a_photo_with_the_whatsapp_text(ctx, bot):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    deal, obs = db.get_deal(conn, deal_id)
    text = pipeline.deal_whatsapp_text(ctx, conn, deal, obs)

    done, lines = send(ctx, conn, APPLIED)
    assert done == [(deal_id, "published")]
    [(path, form)] = bot.calls
    assert path == f"/bot{TOKEN}/sendPhoto"
    cover = f"{SITE}/img/promos/{deal_id}/slide_01.jpg"
    assert bot.heads == [cover]                      # live before it is sent
    assert form == {"chat_id": CHANNEL, "photo": cover, "caption": text.strip()}
    assert f"👉 {deal.affiliate_url}" in form["caption"] and DISCLOSURE in form["caption"]

    post = by_channel(conn)["telegram"]
    assert (post.status, post.publisher, post.message_id, post.result_url) == (
        "published", "telegram", "42", "https://t.me/pontonomada_promos/42")
    # Not the promotion's main channel: no `published` decision, Instagram still to come.
    assert db.get_deal(conn, deal_id)[0].status == "approved"
    assert by_channel(conn)["instagram"].status == "queued"
    assert ctx.object_store.list(review_events.PENDING) == []
    assert not any(TOKEN in line for line in lines)

    bot.calls.clear()                                 # nothing goes out twice
    assert send(ctx, conn, utc(2026, 12, 1, 8))[0] == [] and bot.calls == []


def test_it_waits_for_the_cover_on_the_site_then_counts_failures_after_a_day(ctx, bot):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    bot.site_status = 404
    done, _ = send(ctx, conn, APPLIED)
    assert done == [(deal_id, "waiting")] and bot.calls == []
    post = by_channel(conn)["telegram"]
    assert post.attempts == 0 and post.last_error.startswith("A imagem ainda não está no site (")
    assert ctx.object_store.list(telegram.RECORDS) == []      # nothing was sent

    later = APPLIED + timedelta(hours=25)
    db.record_recheck(conn, deal_id, valid=True, latest_price=58, reason="continua", at=later)
    done, _ = send(ctx, conn, later)
    assert done == [(deal_id, "failed")] and bot.calls == []
    assert by_channel(conn)["telegram"].attempts == 1

    bot.site_status = 200                             # the deploy arrived
    assert send(ctx, conn, later)[0] == [(deal_id, "published")]


# --- refusals -------------------------------------------------------------------------------

def test_a_rate_limit_waits_without_an_attempt_and_the_next_run_sends_it(ctx, bot):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    bot.answers = [refused(429, "Too Many Requests: retry after 30", retry_after=30)]
    assert send(ctx, conn, APPLIED)[0] == [(deal_id, "waiting")]
    post = by_channel(conn)["telegram"]
    assert (post.attempts, post.last_error) == (
        0, "Limite de mensagens do Telegram (tenta daqui a 30 s): espera pela próxima execução.")
    assert send(ctx, conn, APPLIED + timedelta(minutes=5))[0] == [(deal_id, "published")]
    assert len(bot.sent) == 1


@pytest.mark.parametrize("status, description", [
    (403, "Forbidden: bot is not a member of the channel chat"),
    (400, "Bad Request: chat not found"),
    (400, "Bad Request: not enough rights to send photos to the chat"),
])
def test_a_refused_chat_cancels_with_a_notice_until_a_message_goes_out(ctx, bot, monkeypatch,
                                                                        status, description):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    bot.answers = [refused(status, description)]
    done, lines = send(ctx, conn, APPLIED)
    assert done == [(deal_id, "cancelled")]
    reason = (f"O Telegram recusou a mensagem ({description} (HTTP {status})): confirma que o "
              f"canal {CHANNEL} existe e que o bot é administrador com permissão para publicar "
              "(docs/runbooks/telegram.md).")
    assert by_channel(conn)["telegram"].reason == reason
    assert f"Telegram: {reason}" in lines
    assert ctx.object_store.list(telegram.RECORDS) == []      # refused: nothing went out
    assert reason in cli(ctx, monkeypatch, "queue", "list")

    second = second_deal(ctx, conn)                  # Miguel fixed the channel
    db.set_deal_output_path(conn, second, db.get_deal(conn, deal_id)[0].output_path)  # slides
    approve_event(ctx.object_store, second)
    pipeline.apply_review_events(ctx, conn, now=APPLIED)
    assert send(ctx, conn, APPLIED)[0] == [(second, "published")]
    assert reason not in cli(ctx, monkeypatch, "queue", "list")


def test_a_refused_token_waits_with_a_notice(ctx, bot, monkeypatch):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    bot.answers = [refused(401, "Unauthorized")]
    assert send(ctx, conn, APPLIED)[0] == [(deal_id, "waiting")]
    post = by_channel(conn)["telegram"]
    assert post.attempts == 0 and "O Telegram recusou o token do bot" in post.last_error
    assert "confirma TELEGRAM_BOT_TOKEN" in cli(ctx, monkeypatch, "queue", "list")


def test_a_photo_telegram_could_not_fetch_is_a_failure_retried(ctx, bot):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    bot.answers = [refused(400, "Bad Request: failed to get HTTP URL content")]
    assert send(ctx, conn, APPLIED)[0] == [(deal_id, "failed")]
    assert by_channel(conn)["telegram"].attempts == 1
    assert send(ctx, conn, APPLIED)[0] == [(deal_id, "published")]


def test_server_errors_are_retried_then_cancel_the_post(ctx, bot):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    bot.answers = [refused(500, "Internal Server Error")] * 5
    actions = [send(ctx, conn, APPLIED)[0] for _ in range(5)]
    assert actions == [[(deal_id, "failed")]] * 4 + [[(deal_id, "cancelled")]]
    assert by_channel(conn)["telegram"].reason.startswith("O publicador falhou 5 vezes: ")


# --- never twice ----------------------------------------------------------------------------

CONFIRM = f"Confirma no canal {CHANNEL}; não é enviada outra vez, para não sair repetida."


@pytest.mark.parametrize("answer, what", [
    (httpx.ReadTimeout("timed out"), "sem resposta da API (ReadTimeout)"),
    (httpx.RemoteProtocolError("Server disconnected"), "sem resposta da API (RemoteProtocolError)"),
    (httpx.Response(502, text="<html>Bad Gateway</html>"), "resposta da API ilegível (HTTP 502)"),
])
def test_a_send_without_an_answer_is_cancelled_never_sent_again(ctx, bot, answer, what):
    """The request went out but no answer says what happened: it may be in the channel, and
    Telegram can't tell a bot, so it is never resent (D38: a lost post, not a duplicate)."""
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    bot.answers = [answer]
    done, lines = send(ctx, conn, APPLIED)
    assert done == [(deal_id, "cancelled")]
    reason = f"O Telegram não respondeu ao envio ({what}): a mensagem pode ter saído. {CONFIRM}"
    assert by_channel(conn)["telegram"].reason == reason
    assert f"Telegram: deal {deal_id}: {reason}" in lines
    assert len(bot.calls) == 1
    assert send(ctx, conn, APPLIED + timedelta(hours=2))[0] == [] and len(bot.calls) == 1


def test_a_send_that_never_reached_telegram_is_retried(ctx, bot):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    bot.answers = [httpx.ConnectError("[Errno 11001] getaddrinfo failed")]
    assert send(ctx, conn, APPLIED)[0] == [(deal_id, "failed")]
    post = by_channel(conn)["telegram"]
    assert (post.attempts, post.last_error) == (
        1, "TelegramError: Sem ligação ao Telegram (sem ligação à API (ConnectError)): nada foi "
           "enviado.")
    assert ctx.object_store.list(telegram.RECORDS) == []
    assert send(ctx, conn, APPLIED)[0] == [(deal_id, "published")]
    assert len(bot.sent) == 1


def lose_the_database(conn) -> None:
    """A job killed after the send, before the database reached R2 (D21): the next run starts
    from the database as it was, the queued row with no trace of the send; only the object
    store (written at once) remembers."""
    conn.execute("UPDATE posting_queue SET status = 'queued', settled_at = NULL, publisher = "
                 "NULL, result_url = NULL, message_id = NULL WHERE channel = 'telegram'")
    conn.commit()


def test_a_message_sent_before_the_database_was_lost_is_adopted_not_sent_again(ctx, bot):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    assert send(ctx, conn, APPLIED)[0] == [(deal_id, "published")]
    lose_the_database(conn)
    done, lines = send(ctx, conn, APPLIED + timedelta(hours=2))
    assert done == [(deal_id, "published")]
    assert len(bot.calls) == 1                        # not sent again
    post = by_channel(conn)["telegram"]
    assert (post.message_id, post.result_url) == ("42", "https://t.me/pontonomada_promos/42")
    assert any("já tinha saído" in line for line in lines)


def test_a_send_whose_answer_was_never_saved_is_cancelled_not_sent_again(ctx, bot):
    """The job died between the request and saving its answer: the record says a send
    started, nothing says how it ended."""
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    deal = db.get_deal(conn, deal_id)[0]
    ctx.object_store.put(telegram.record_key(deal_id), json.dumps({
        "deal_id": deal_id, "observation_id": deal.observation_id, "post_id": 1,
        "chat": CHANNEL, "started_at": "2026-12-01T07:00:00Z"}).encode())
    assert send(ctx, conn, APPLIED + timedelta(hours=2))[0] == [(deal_id, "cancelled")]
    assert bot.calls == []
    assert by_channel(conn)["telegram"].reason == (
        "Uma tentativa anterior (01/12/2026 às 07:00) enviou a mensagem ao Telegram sem "
        f"guardar a resposta: pode ter saído. {CONFIRM}")


def test_a_record_of_another_promotion_with_the_same_id_is_ignored(ctx, bot):
    """A deal id reused after a lost database belongs to another offer: it is sent."""
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    ctx.object_store.put(telegram.record_key(deal_id), json.dumps({
        "deal_id": deal_id, "observation_id": -1, "post_id": 1, "chat": CHANNEL,
        "started_at": "2026-11-30T07:00:00Z", "message_id": "7"}).encode())
    assert send(ctx, conn, APPLIED)[0] == [(deal_id, "published")]
    assert len(bot.sent) == 1 and by_channel(conn)["telegram"].message_id == "42"


# --- the caption, the token, the CLI and the config -----------------------------------------

def test_a_text_over_telegrams_caption_limit_is_cancelled_never_cut(ctx, bot):
    """1024 UTF-16 code units: cutting it could drop the partner link or the disclosure."""
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    def text_with_link(n: int) -> str:
        db.set_deal_affiliate(conn, deal_id, "https://aviasales.tpo.lu/" + "x" * n, None)
        return pipeline.deal_whatsapp_text(ctx, conn, *db.get_deal(conn, deal_id)).strip()
    text = text_with_link(1024 - len(text_with_link(0)))     # 1024 characters...
    assert len(text) == 1024 < len(text.encode("utf-16-le")) // 2   # ...but emoji count twice
    assert send(ctx, conn, APPLIED)[0] == [(deal_id, "cancelled")]
    assert bot.calls == []
    assert by_channel(conn)["telegram"].reason.startswith("O texto tem ")


def test_the_token_never_reaches_an_error_a_log_the_database_or_the_store(ctx, bot):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    bot.answers = [refused(500, f"Internal error at {url}"),
                   httpx.ReadTimeout(f"timed out: {url}")]
    _, first = send(ctx, conn, APPLIED)
    _, second = send(ctx, conn, APPLIED)
    post = by_channel(conn)["telegram"]
    assert post.status == "cancelled"
    seen = "\n".join([*first, *second, post.reason, *conn.iterdump()])
    assert TOKEN not in seen and "bot***" in seen     # the 500's text, redacted
    store = ctx.object_store
    assert not any(TOKEN.encode() in store.get(key) for key in store.list())


def test_queue_list_shows_the_message_link(ctx, bot, monkeypatch):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    send(ctx, conn, APPLIED)
    out = cli(ctx, monkeypatch, "queue", "list", "--all")
    assert (f"Telegram deal {deal_id} Lisboa → Londres 58 € 01/12/2026 às 07:00 · publicada "
            "(telegram) · https://t.me/pontonomada_promos/42") in out


def test_each_real_publisher_posts_only_to_its_own_channel():
    from escapadinha.config import PostingConfig
    assert PostingConfig(publishers={"telegram": "telegram"}).publishers["telegram"] == "telegram"
    with pytest.raises(ValueError, match="the telegram publisher only posts to the telegram"):
        PostingConfig(publishers={"instagram": "telegram"})
    with pytest.raises(ValueError, match="the instagram publisher only posts to the instagram"):
        PostingConfig(publishers={"telegram": "instagram"})


@pytest.mark.parametrize("channel, chat", [("@pontonomada", "@pontonomada"),
                                           ("pontonomada", "@pontonomada"),
                                           ("https://t.me/pontonomada", "@pontonomada"),
                                           (" -1001234567890 ", "-1001234567890")])
def test_the_channel_secret_becomes_a_chat_id(channel, chat):
    assert telegram.chat_id(channel) == chat
