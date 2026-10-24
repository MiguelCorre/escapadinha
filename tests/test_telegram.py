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
from test_pipeline import ctx, set_publishers  # noqa: F401
from test_web_build import npm  # noqa: F401
from test_posting import APPLIED, approve_event, approved, by_channel, cli, publish, second_deal, utc

TOKEN = "123456789:AAtest-secret-bot-token"
CHANNEL = "@pontonomada_promos"
SITE = "https://pontonomada.pt"


@pytest.fixture(autouse=True)
def instagram_dry_run(ctx):
    """Only Telegram is under test: Instagram on the dry run (no Graph API calls)."""
    set_publishers(ctx, instagram="dry-run", telegram="telegram")   # config.yaml pauses it (D46)


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
    assert post.attempts == 0 and post.last_error.startswith("As imagens ainda não estão no site (")
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


# Error texts as the Bot API sends them: its own (tdlib/telegram-bot-api `Client.cpp`, e.g.
# `fail_query_with_error` maps WEBPAGE_CURL_FAILED to "Failed to get HTTP URL content") or an
# MTProto error name passed through ("Bad Request: CHAT_WRITE_FORBIDDEN"; an all-caps 403
# becomes a 400 there). Names: core.telegram.org/method/messages.sendMedia.
CHANNEL_SETUP = [
    (403, "Forbidden: bot is not a member of the channel chat"),
    (403, "Forbidden: bot was kicked from the channel chat"),
    (400, "Bad Request: chat not found"),
    (400, "Bad Request: not enough rights to send photos to the chat"),
    (400, "Bad Request: need administrator rights in the channel chat"),
    (400, "Bad Request: CHAT_WRITE_FORBIDDEN"),
    (400, "Bad Request: CHAT_ADMIN_REQUIRED"),
]


@pytest.mark.parametrize("status, description", CHANNEL_SETUP)
def test_a_refused_channel_waits_with_a_notice_until_a_message_goes_out(ctx, bot, monkeypatch,
                                                                        status, description):
    """A channel or bot set up wrong is not this message's fault: every post waits (no attempt
    counted, none lost) and `queue list` says what to fix, until a message goes out."""
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    bot.answers = [refused(status, description)]
    done, lines = send(ctx, conn, APPLIED)
    assert done == [(deal_id, "waiting")]
    reason = (f"O Telegram recusou o canal ({description} (HTTP {status})): confirma que o canal "
              f"{CHANNEL} existe e que o bot é administrador com permissão para publicar "
              "(docs/runbooks/telegram.md); as publicações esperam.")
    post = by_channel(conn)["telegram"]
    assert (post.status, post.attempts, post.last_error) == ("queued", 0, reason)
    assert f"Telegram: {reason}" in lines
    assert ctx.object_store.list(telegram.RECORDS) == []      # refused: nothing went out
    assert cli(ctx, monkeypatch, "queue", "list").count(reason) == 2   # notice + the post

    # Miguel fixed the channel: the same post goes out and the notice goes.
    assert send(ctx, conn, APPLIED + timedelta(hours=2))[0] == [(deal_id, "published")]
    assert reason not in cli(ctx, monkeypatch, "queue", "list")


def test_a_refused_token_waits_with_a_notice(ctx, bot, monkeypatch):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    bot.answers = [refused(401, "Unauthorized")]
    assert send(ctx, conn, APPLIED)[0] == [(deal_id, "waiting")]
    post = by_channel(conn)["telegram"]
    assert post.attempts == 0 and "O Telegram recusou o token do bot" in post.last_error
    assert "confirma TELEGRAM_BOT_TOKEN" in cli(ctx, monkeypatch, "queue", "list")


@pytest.mark.parametrize("description", [
    "Bad Request: failed to get HTTP URL content",            # WEBPAGE_CURL_FAILED
    "Bad Request: wrong type of the web page content",         # WEBPAGE_MEDIA_EMPTY
    "Bad Request: wrong file identifier/HTTP URL specified",
    "Bad Request: PHOTO_SAVE_FILE_INVALID",                    # "Internal issues, try again later"
])
def test_a_photo_telegram_could_not_fetch_now_is_a_failure_retried(ctx, bot, description):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    bot.answers = [refused(400, description)]
    assert send(ctx, conn, APPLIED)[0] == [(deal_id, "failed")]
    post = by_channel(conn)["telegram"]
    assert post.attempts == 1 and post.last_error == (
        f"RetryableSendError: O Telegram não conseguiu ir buscar a imagem ({description} "
        "(HTTP 400)).")
    assert send(ctx, conn, APPLIED)[0] == [(deal_id, "published")]


@pytest.mark.parametrize("description, why", [
    ("Bad Request: PHOTO_INVALID_DIMENSIONS", "dimensões da imagem inválidas"),
    ("Bad Request: PHOTO_EXT_INVALID", "formato da imagem inválido"),
    ("Bad Request: IMAGE_PROCESS_FAILED", "o Telegram não conseguiu processar a imagem"),
    ("Bad Request: wrong HTTP URL specified", "o endereço da imagem é inválido"),
    ("Bad Request: MEDIA_CAPTION_TOO_LONG", "o texto é demasiado longo"),
    ("Bad Request: message caption is too long", "o texto é demasiado longo"),
])
def test_a_message_telegram_refuses_for_good_is_cancelled(ctx, bot, description, why):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    bot.answers = [refused(400, description)]
    assert send(ctx, conn, APPLIED)[0] == [(deal_id, "cancelled")]
    assert by_channel(conn)["telegram"].reason == (
        f"O Telegram recusou esta mensagem: {why} ({description} (HTTP 400)).")
    assert pipeline.publisher_notices(ctx, conn) == []        # not the channel's fault


def test_another_bad_request_is_a_failure_retried(ctx, bot):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    bot.answers = [refused(400, "Bad Request: MEDIA_INVALID")]
    assert send(ctx, conn, APPLIED)[0] == [(deal_id, "failed")]
    assert by_channel(conn)["telegram"].last_error == (
        "RetryableSendError: Erro da API do Telegram: Bad Request: MEDIA_INVALID (HTTP 400)")


def test_server_errors_are_retried_then_cancel_the_post(ctx, bot):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    bot.answers = [refused(500, "Internal Server Error")] * 5
    actions = [send(ctx, conn, APPLIED)[0] for _ in range(5)]
    assert actions == [[(deal_id, "failed")]] * 4 + [[(deal_id, "cancelled")]]
    assert by_channel(conn)["telegram"].reason.startswith("O publicador falhou 5 vezes: ")


# --- never twice ----------------------------------------------------------------------------

def confirm(deal_id: int) -> str:
    return (f"Confirma no canal {CHANNEL}: não é reenviada sozinha, para não sair repetida; se "
            f"não saiu, `escapadinha queue retry {deal_id} telegram` volta a pô-la na fila.")


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
    reason = (f"O Telegram não respondeu ao envio ({what}): a mensagem pode ter saído. "
              f"{confirm(deal_id)}")
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
        1, "RetryableSendError: Sem ligação ao Telegram (sem ligação à API (ConnectError)): nada foi "
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
        f"guardar a resposta: pode ter saído. {confirm(deal_id)}")


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
    assert telegram.unconfirmed(ctx.object_store) == []        # nothing was sent


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


# --- a way back after a lost answer ---------------------------------------------------------

def test_a_lost_answer_is_listed_until_miguel_retries_it_and_then_it_goes_out_once(ctx, bot,
                                                                                    monkeypatch):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    bot.answers = [httpx.ReadTimeout("timed out")]
    assert send(ctx, conn, APPLIED)[0] == [(deal_id, "cancelled")]
    notice = (f"Envio ao Telegram por confirmar: deal {deal_id} (01/12/2026 às 07:00). "
              f"{confirm(deal_id)}")
    assert notice in cli(ctx, monkeypatch, "queue", "list")

    # Miguel looked: it isn't in the channel. Without R2 the request applies at once.
    out = cli(ctx, monkeypatch, "queue", "retry", str(deal_id), "telegram")
    assert (f"deal {deal_id}: a publicação do Telegram voltou à fila e sai na próxima "
            "execução.") in out
    post = by_channel(conn)["telegram"]
    assert (post.status, post.attempts, post.reason, post.settled_at) == ("queued", 0, None, None)
    assert notice not in cli(ctx, monkeypatch, "queue", "list")

    later = APPLIED + timedelta(hours=2)
    db.record_recheck(conn, deal_id, valid=True, latest_price=58, reason="continua", at=later)
    assert send(ctx, conn, later)[0] == [(deal_id, "published")]
    assert len(bot.calls) == 2 and len(bot.sent) == 1
    assert send(ctx, conn, later + timedelta(hours=2))[0] == []      # once


def test_with_r2_the_next_run_requeues_a_retried_post(ctx, bot):
    """The PC writes the request to the store; the run that owns the database applies it."""
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    bot.answers = [httpx.ReadTimeout("timed out")]
    send(ctx, conn, APPLIED)
    deal = db.get_deal(conn, deal_id)[0]
    telegram.request_retry(ctx.object_store, deal, now=APPLIED + timedelta(minutes=30))
    assert by_channel(conn)["telegram"].status == "cancelled"        # nothing applied yet
    later = APPLIED + timedelta(hours=2)
    db.record_recheck(conn, deal_id, valid=True, latest_price=58, reason="continua", at=later)
    done, lines = send(ctx, conn, later)
    assert done == [(deal_id, "published")] and len(bot.sent) == 1
    assert f"Telegram: deal {deal_id} voltou à fila (pedido do Miguel)." in lines


def test_a_retried_post_cancelled_again_later_is_not_requeued_again(ctx, bot):
    """The request requeues the cancellation it answered, not a later one (an expiry)."""
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    bot.answers = [httpx.ReadTimeout("timed out")]
    send(ctx, conn, APPLIED)
    telegram.request_retry(ctx.object_store, db.get_deal(conn, deal_id)[0],
                           now=APPLIED + timedelta(minutes=30))
    later = APPLIED + timedelta(hours=2)
    db.record_recheck(conn, deal_id, valid=False, latest_price=90, reason="o preço subiu",
                      at=later)
    assert send(ctx, conn, later)[0] == [(deal_id, "cancelled")]      # requeued, then expired
    assert send(ctx, conn, later + timedelta(hours=2))[0] == []
    assert bot.sent == []


def test_retry_needs_a_send_without_an_answer(ctx, bot, monkeypatch):
    from typer.testing import CliRunner
    from escapadinha import cli as cli_module
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)

    def refused_retry(*args) -> str:
        result = CliRunner().invoke(cli_module.app, ["queue", "retry", *args])
        assert result.exit_code == 1, result.output
        return " ".join(result.output.split())

    assert (f"deal {deal_id}: não há nenhum envio ao Telegram por confirmar."
            in refused_retry(str(deal_id), "telegram"))
    send(ctx, conn, APPLIED)                                           # out, with its link
    assert (f"deal {deal_id}: a mensagem do Telegram saiu "
            "(https://t.me/pontonomada_promos/42): não há nada a repor."
            in refused_retry(str(deal_id), "telegram"))
    assert "Só as publicações do Telegram" in refused_retry(str(deal_id), "instagram")
    assert by_channel(conn)["telegram"].status == "published"


# --- the link, the CLI and the config -------------------------------------------------------

def test_the_message_link_shows_wherever_the_promotions_posts_do(ctx, bot, monkeypatch):
    from test_review import price_api
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    send(ctx, conn, APPLIED)
    link = "https://t.me/pontonomada_promos/42"
    out = cli(ctx, monkeypatch, "queue", "list")                  # the Instagram post still to go
    assert (f"Instagram deal {deal_id} Lisboa → Londres 58 € 01/12/2026 às 09:00 · agendada · "
            f"Telegram: {link}") in out
    out = cli(ctx, monkeypatch, "queue", "list", "--all")
    assert (f"Telegram deal {deal_id} Lisboa → Londres 58 € 01/12/2026 às 07:00 · publicada "
            f"(telegram) · {link}") in out
    price_api(58)
    out = cli(ctx, monkeypatch, "deal", "check", str(deal_id))
    assert f"Telegram: publicada (telegram) · {link}" in out
    assert "Instagram: agendada para 01/12/2026 às 09:00" in out


def test_each_real_publisher_posts_only_to_its_own_channel():
    from escapadinha.config import PostingConfig
    assert PostingConfig(publishers={"telegram": "telegram"}).publishers["telegram"] == "telegram"
    with pytest.raises(ValueError, match="the telegram publisher only posts to the telegram"):
        PostingConfig(publishers={"instagram": "telegram"})
    with pytest.raises(ValueError, match="the instagram publisher only posts to the instagram"):
        PostingConfig(publishers={"telegram": "instagram"})


def test_every_publisher_name_in_config_has_one_factory():
    from typing import get_args
    from escapadinha.config import PublisherName
    assert set(pipeline.PUBLISHERS) == set(get_args(PublisherName))


@pytest.mark.parametrize("channel", ["@pontonomada", " @pontonomada_promos ", "-1001234567890"])
def test_the_channel_secret_is_a_handle_or_a_numeric_id(channel):
    assert telegram.channel_problem(channel) is None


BAD_CHANNELS = ["pontonomada", "https://t.me/pontonomada", "@pt", "@1abc"]


@pytest.mark.parametrize("channel", BAD_CHANNELS)
def test_any_other_channel_secret_is_a_problem_but_the_secrets_still_load(channel):
    from escapadinha.config import Secrets
    assert telegram.channel_problem(channel).startswith(
        "TELEGRAM_CHANNEL tem de ser o @handle do canal público")
    assert Secrets(_env_file=None, telegram_channel=channel).telegram_channel == channel


def test_a_malformed_channel_pauses_telegram_but_the_run_goes_on(ctx, monkeypatch, npm):
    """A typo in TELEGRAM_CHANNEL never stops collection, detection or the site: the run goes
    on, the Telegram post waits (no attempt, nothing sent) and `queue list` says what to fix."""
    from test_pipeline import mock_api, mock_links
    from test_review import rendered_deal
    from test_web_build import web_package
    from test_website import real_slides
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHANNEL", "pontonomada")            # no @
    with respx.mock:                                 # any call to Telegram would fail the test
        web_package(ctx.root)
        conn = pipeline.open_db(ctx)
        deal_id = rendered_deal(ctx, conn)
        real_slides(conn, deal_id)
        db.set_meta(conn, pipeline.DISCOVERED_AT, db.utcnow().isoformat())
        approve_event(ctx.object_store, deal_id, checked=db.utcnow())
        mock_api()
        mock_links()
        runs = conn.execute("SELECT COUNT(*) FROM fetch_runs WHERE scope = 'full'").fetchone()[0]
        out = cli(ctx, monkeypatch, "run", "--no-render")
        assert "Detection for run" in out and "Path:" in out            # collected, detected, on
        assert conn.execute("SELECT COUNT(*) FROM fetch_runs WHERE scope = 'full'").fetchone()[0] == runs + 1
        problem = telegram.channel_problem("pontonomada")
        assert f"publicação Telegram deal {deal_id}: à espera ({problem})" in out
        post = by_channel(conn)["telegram"]
        assert (post.status, post.attempts, post.last_error) == ("queued", 0, problem)
        assert out.count(problem) >= 1
        assert f"! {problem}" in cli(ctx, monkeypatch, "queue", "list")   # the notice on top
