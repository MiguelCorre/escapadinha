"""Instagram publisher (D36) through the pipeline seam (`pipeline.run_publish`), the Graph API
and the site's HEAD answers mocked with respx (no network): carousel, status polling, publish,
permalink, story, publishing limit, images not deployed yet, idempotent retries, error mapping,
the `published` event, token refresh, missing secrets, `queue list` and `instagram token`."""

from __future__ import annotations

import json
from datetime import timedelta
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from escapadinha import instagram, pipeline, review_events
from escapadinha.storage import db
from test_pipeline import ctx  # noqa: F401
from test_posting import APPLIED, approved, by_channel, cli, publish, second_deal, utc

ACCOUNT = "17841400000000001"
TOKEN = "IGAAtest-secret-token-1"
SITE = "https://pontonomada.pt"
DUE = utc(2026, 12, 1, 9, 0)            # the 09:00 slot (Lisbon = UTC in December)


class FakeGraph:
    """Instagram's Graph API as far as the publisher uses it. Records every call; containers
    answer the statuses queued for them (FINISHED by default); published media keep their
    caption, so a lost publish can be found again."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.statuses: dict[str, list[str]] = {}
        self.default_status: list[str] = ["FINISHED"]
        self.containers: dict[str, dict] = {}
        self.media: list[dict] = []
        self.quota = (0, 100)
        self.errors: dict[tuple[str, str], tuple[int, dict]] = {}   # (method, kind) -> answer
        self.refresh = {"access_token": "IGAAtest-refreshed-2", "token_type": "bearer",
                        "expires_in": 5184000}
        self.tokens: set[str] = set()
        self.token_log: list[tuple[str, str]] = []     # (kind, token sent)
        self._next = 1000

    def _id(self) -> str:
        self._next += 1
        return str(self._next)

    def kinds(self, method: str | None = None) -> list[str]:
        return [kind for m, kind, _ in self.calls if method in (None, m)]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        method = request.method
        params = (dict(request.url.params) if method == "GET"
                  else {k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        token = params.pop("access_token", None)
        self.tokens.add(token)
        parts = request.url.path.strip("/").split("/")
        if parts == ["refresh_access_token"]:
            kind = "refresh"
        elif parts[-1] in ("media", "media_publish", "content_publishing_limit"):
            kind = parts[-1]
            if kind == "media" and method == "POST":
                kind = ("story" if params.get("media_type") == "STORIES" else
                        "carousel" if params.get("media_type") == "CAROUSEL" else
                        "child" if params.get("is_carousel_item") else "image")
        else:
            kind = "permalink" if params.get("fields") == "permalink" else "status"
        self.calls.append((method, kind, params))
        self.token_log.append((kind, token))
        if (method, kind) in self.errors:
            status, body = self.errors[(method, kind)]
            return httpx.Response(status, json=body)
        match kind:
            case "refresh":
                return httpx.Response(200, json=self.refresh)
            case "content_publishing_limit":
                used, total = self.quota
                return httpx.Response(200, json={"data": [{"quota_usage": used, "config": {
                    "quota_total": total, "quota_duration": 86400}}]})
            case "media":
                return httpx.Response(200, json={"data": [
                    {"id": m["id"], "caption": m["caption"], "timestamp": "2026-12-01T09:00:00+0000"}
                    for m in reversed(self.media)]})
            case "child" | "carousel" | "story" | "image":
                container = self._id()
                self.containers[container] = {"kind": kind, **params}
                self.statuses[container] = list(self.default_status)
                return httpx.Response(200, json={"id": container})
            case "status":
                container = parts[-1]
                queue = self.statuses[container]
                status = queue.pop(0) if len(queue) > 1 else queue[0]
                return httpx.Response(200, json={"status_code": status, "status": status.lower(),
                                                 "id": container})
            case "media_publish":
                container = params["creation_id"]
                media = {"id": self._id(), "container": container,
                         "kind": self.containers[container]["kind"],
                         "caption": self.containers[container].get("caption")}
                self.media.append(media)
                self.statuses[container] = ["PUBLISHED"]
                return httpx.Response(200, json={"id": media["id"]})
            case "permalink":
                return httpx.Response(200, json={"id": parts[-1],
                                                 "permalink": f"https://www.instagram.com/p/C{parts[-1]}/"})
        raise AssertionError(f"unexpected call {method} {request.url.path}")


@pytest.fixture
def graph(ctx, monkeypatch):
    """The secrets set, Graph API and site mocked: every JPEG answers 200 unless a test says
    otherwise (`site_status`)."""
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("INSTAGRAM_ACCOUNT_ID", ACCOUNT)
    fake = FakeGraph()
    fake.site_status = 200
    fake.heads = []
    with respx.mock:                    # the default router: the provider mocks of the helpers too
        respx.route(host="graph.instagram.com").mock(side_effect=fake)

        def head(request):
            fake.heads.append(str(request.url))
            return httpx.Response(fake.site_status)
        respx.head(url__startswith=f"{SITE}/img/").mock(side_effect=head)
        fake.router = respx.mock
        yield fake


def setup(ctx, graph):
    """An approved promotion (approved at 07:00, live check 06:30) with its Telegram post out,
    the Instagram post queued for 09:00; then a recheck at 08:30 so the 09:00 post is verified."""
    conn = pipeline.open_db(ctx)
    deal_id = _approved(ctx, conn, graph)
    db.record_recheck(conn, deal_id, valid=True, latest_price=58, reason="continua",
                      at=utc(2026, 12, 1, 8, 30))
    return conn, deal_id


def _approved(ctx, conn, graph) -> int:
    deal_id = approved(ctx, conn)
    publish(ctx, conn, APPLIED, sleep=no_sleep)              # Telegram (dry run) goes now
    return deal_id


def no_sleep(seconds: float) -> None:
    pass


def run(ctx, conn, now=DUE, sleep=no_sleep):
    return publish(ctx, conn, now, sleep=sleep)


def pending_events(ctx) -> list[dict]:
    store = ctx.object_store
    return [json.loads(store.get(k)) for k in store.list(review_events.PENDING)]


# --- missing secrets ------------------------------------------------------------------------

@respx.mock
def test_without_the_secrets_instagram_stays_a_dry_run_and_says_why(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    publish(ctx, conn, APPLIED)
    db.record_recheck(conn, deal_id, valid=True, latest_price=58, reason="continua",
                      at=utc(2026, 12, 1, 8, 30))
    done, lines = publish(ctx, conn, DUE)
    assert done == [(deal_id, "instagram", "published")]
    log = "\n".join(lines)
    assert "Instagram em dry run: faltam INSTAGRAM_ACCESS_TOKEN e/ou INSTAGRAM_ACCOUNT_ID" in log
    assert "[dry-run] Instagram" in log
    assert by_channel(conn)["instagram"].publisher == "dry-run"
    assert pending_events(ctx) == []                      # a dry run marks nothing published


# --- the carousel and the story -------------------------------------------------------------

def test_a_due_post_goes_out_as_a_carousel_then_a_story(ctx, graph):
    conn, deal_id = setup(ctx, graph)
    caption = pipeline.deal_caption_text(ctx, pipeline.text_view(ctx, conn,
                                                                 *db.get_deal(conn, deal_id)))
    done, lines = run(ctx, conn)
    assert done == [(deal_id, "instagram", "published")]
    assert graph.kinds() == ["content_publishing_limit", "media", "child", "child", "child",
                             "carousel", "status", "media_publish", "permalink",
                             "content_publishing_limit", "story", "status", "media_publish"]
    jpegs = [f"{SITE}/img/promos/{deal_id}/slide_0{n}.jpg" for n in (1, 2, 3)]
    assert graph.heads[:3] == jpegs                          # checked before anything is created
    children = [p for _, kind, p in graph.calls if kind == "child"]
    assert [c["image_url"] for c in children] == jpegs
    assert all(c["is_carousel_item"] == "true" for c in children)
    [carousel] = [p for _, kind, p in graph.calls if kind == "carousel"]
    assert carousel["caption"] == caption
    assert carousel["children"] == ",".join(sorted(c for c, v in graph.containers.items()
                                                   if v["kind"] == "child"))
    [story] = [p for _, kind, p in graph.calls if kind == "story"]
    assert story["image_url"] == jpegs[0]
    assert graph.tokens == {TOKEN}
    assert [m["kind"] for m in graph.media] == ["carousel", "story"]

    post = by_channel(conn)["instagram"]
    carousel_media, story_media = graph.media
    assert (post.status, post.publisher, post.media_id) == ("published", "instagram",
                                                            carousel_media["id"])
    assert post.result_url == f"https://www.instagram.com/p/C{carousel_media['id']}/"
    assert (post.story_status, post.story_media_id) == ("published", story_media["id"])
    assert post.container_id is None and post.story_container_id is None
    assert f"Story Instagram deal {deal_id}: publicada" in "\n".join(lines)

    # The promotion is marked published by an event (D26), applied by the next run.
    [event] = pending_events(ctx)
    assert (event["type"], event["deal_id"], event["actor"], event["post_url"]) == \
        ("published", deal_id, "instagram-publisher", post.result_url)
    assert db.get_deal(conn, deal_id)[0].status == "approved"
    [outcome] = pipeline.apply_review_events(ctx, conn, now=utc(2026, 12, 1, 11))
    assert outcome.applied
    deal = db.get_deal(conn, deal_id)[0]
    assert (deal.status, deal.post_url) == ("published", post.result_url)

    # Nothing goes out twice.
    graph.calls.clear()
    assert run(ctx, conn, utc(2026, 12, 1, 13))[0] == [] and graph.calls == []


def test_status_is_polled_with_backoff_until_finished(ctx, graph):
    conn, deal_id = setup(ctx, graph)
    graph.default_status = ["IN_PROGRESS", "IN_PROGRESS", "FINISHED"]
    slept: list[float] = []
    done, _ = run(ctx, conn, sleep=slept.append)
    assert done == [(deal_id, "instagram", "published")]
    assert slept == [2, 3, 2, 3]                     # carousel, then story: each 3 polls
    assert graph.kinds().count("status") == 6


def test_a_container_still_in_progress_waits_and_the_next_run_resumes_it(ctx, graph):
    conn, deal_id = setup(ctx, graph)
    graph.default_status = ["IN_PROGRESS"]
    slept: list[float] = []
    done, _ = run(ctx, conn, sleep=slept.append)
    assert done == [(deal_id, "instagram", "waiting")]
    assert slept == list(instagram.POLL_DELAYS)
    post = by_channel(conn)["instagram"]
    assert (post.status, post.attempts) == ("queued", 0)
    assert post.last_error == ("O Instagram ainda está a processar as imagens: a próxima execução "
                               "continua.")
    container = post.container_id
    assert graph.containers[container]["kind"] == "carousel"

    graph.statuses[container] = ["FINISHED"]
    graph.default_status = ["FINISHED"]
    graph.calls.clear()
    done, _ = run(ctx, conn, utc(2026, 12, 1, 11))
    assert done == [(deal_id, "instagram", "published")]
    assert "child" not in graph.kinds() and "carousel" not in graph.kinds()   # reused
    assert [m["container"] for m in graph.media][:1] == [container]


def test_a_container_in_error_is_a_retried_failure_with_a_new_container(ctx, graph):
    conn, deal_id = setup(ctx, graph)
    graph.default_status = ["ERROR"]
    done, _ = run(ctx, conn)
    assert done == [(deal_id, "instagram", "failed")]
    post = by_channel(conn)["instagram"]
    assert (post.status, post.attempts, post.container_id) == ("queued", 1, None)
    assert post.last_error == "InstagramError: O Instagram não processou as imagens (ERROR: error)."
    assert graph.media == []

    graph.default_status = ["FINISHED"]
    done, _ = run(ctx, conn, utc(2026, 12, 1, 11))
    assert done == [(deal_id, "instagram", "published")]
    assert len([k for k in graph.kinds() if k == "carousel"]) == 2      # a fresh container


def test_the_publishing_limit_is_checked_first(ctx, graph):
    conn, deal_id = setup(ctx, graph)
    graph.quota = (99, 100)                     # no room for the carousel and its story
    done, _ = run(ctx, conn)
    assert done == [(deal_id, "instagram", "waiting")]
    assert graph.kinds() == ["content_publishing_limit"]
    post = by_channel(conn)["instagram"]
    assert (post.attempts, post.last_error) == (
        0, "Limite de publicações do Instagram: 99 de 100 nas últimas 24 h; espera.")


def test_images_not_on_the_site_yet_wait_for_the_deploy(ctx, graph):
    """Right after an approval the Instagram slot can come before the full path deployed the
    promotion's JPEGs: the post waits, no attempt counted, nothing sent to Meta."""
    conn, deal_id = setup(ctx, graph)
    graph.site_status = 404
    done, _ = run(ctx, conn)
    assert done == [(deal_id, "instagram", "waiting")]
    assert graph.calls == []
    post = by_channel(conn)["instagram"]
    assert (post.status, post.attempts) == ("queued", 0)
    assert post.last_error == (f"As imagens ainda não estão no site ({SITE}/img/promos/{deal_id}/"
                               "slide_01.jpg → 404): espera pelo próximo deploy.")
    graph.site_status = 200
    assert run(ctx, conn, utc(2026, 12, 1, 11))[0] == [(deal_id, "instagram", "published")]


def test_a_crash_between_publish_and_recording_never_posts_twice(ctx, graph, monkeypatch):
    """The run dies after `media_publish` answered and before its id was stored (here the save
    fails; with R2 a killed job loses the database copy too). The retry finds the carousel on
    the account by its caption and adopts it: one post, one event."""
    conn, deal_id = setup(ctx, graph)
    real = db.save_post_progress

    def crash_on_media(conn_, post_id, **fields):
        if fields.get("media_id"):
            raise RuntimeError("o processo morreu")
        real(conn_, post_id, **fields)
    monkeypatch.setattr(db, "save_post_progress", crash_on_media)
    done, _ = run(ctx, conn)
    assert done == [(deal_id, "instagram", "failed")]
    assert len(graph.media) == 1 and pending_events(ctx) == []
    monkeypatch.setattr(db, "save_post_progress", real)
    db.save_post_progress(conn, by_channel(conn)["instagram"].id, container_id=None)  # lost too

    graph.calls.clear()
    done, lines = run(ctx, conn, utc(2026, 12, 1, 11))
    assert done == [(deal_id, "instagram", "published")]
    assert "media_publish" in graph.kinds()                       # the story's only
    assert [m["kind"] for m in graph.media] == ["carousel", "story"]
    assert "já estava publicado" in "\n".join(lines)
    post = by_channel(conn)["instagram"]
    assert post.media_id == graph.media[0]["id"]
    assert [e["type"] for e in pending_events(ctx)] == ["published"]


def test_a_story_failure_never_reposts_the_carousel(ctx, graph):
    conn, deal_id = setup(ctx, graph)
    graph.errors[("POST", "story")] = (500, {"error": {"message": "An unknown error occurred",
                                                       "code": 1, "is_transient": True}})
    done, lines = run(ctx, conn)
    assert done == [(deal_id, "instagram", "published")]
    post = by_channel(conn)["instagram"]
    assert (post.status, post.story_status, post.story_attempts) == ("published", "pending", 1)
    assert post.story_note == ("InstagramError: Erro da API do Instagram: An unknown error "
                               "occurred (código 1, HTTP 500)")
    assert len(pending_events(ctx)) == 1

    del graph.errors[("POST", "story")]
    graph.calls.clear()
    assert run(ctx, conn, utc(2026, 12, 1, 11))[0] == []
    assert "carousel" not in graph.kinds() and "story" in graph.kinds()
    assert by_channel(conn)["instagram"].story_status == "published"
    assert [m["kind"] for m in graph.media] == ["carousel", "story"]


def test_a_story_that_can_not_go_out_in_time_is_skipped(ctx, graph):
    conn, deal_id = setup(ctx, graph)
    graph.errors[("POST", "story")] = (500, {"error": {"message": "x", "code": 2}})
    run(ctx, conn)
    graph.calls.clear()
    run(ctx, conn, DUE + timedelta(hours=6, minutes=1))          # past posting.max_check_age
    assert graph.calls == []
    post = by_channel(conn)["instagram"]
    assert (post.status, post.story_status) == ("published", "skipped")
    assert post.story_note == "A story não saiu nas 6 h a seguir ao carrossel: já não sai."


# --- error mapping --------------------------------------------------------------------------

@pytest.mark.parametrize("answer, action, attempts, reason", [
    ((400, {"error": {"message": "Only photo or video can be accepted as media type.",
                      "code": 9004, "error_subcode": 2207005}}),
     "cancelled", 0, "O Instagram recusou as imagens: formato de imagem não suportado "
                     "(Only photo or video can be accepted as media type. (código 9004/2207005, "
                     "HTTP 400))."),
    ((400, {"error": {"message": "Application request limit reached", "code": 4}}),
     "waiting", 0, "Limite de pedidos ou de publicações da API do Instagram (Application request "
                   "limit reached (código 4, HTTP 400)): tenta na próxima execução."),
    ((503, {"error": {"message": "Service temporarily unavailable", "code": 2}}),
     "failed", 1, "InstagramError: Erro da API do Instagram: Service temporarily unavailable "
                  "(código 2, HTTP 503)"),
])
def test_graph_errors_wait_retry_or_cancel(ctx, graph, answer, action, attempts, reason):
    conn, deal_id = setup(ctx, graph)
    graph.errors[("POST", "child")] = answer
    done, _ = run(ctx, conn)
    assert done == [(deal_id, "instagram", action)]
    post = by_channel(conn)["instagram"]
    assert post.attempts == attempts
    assert (post.reason if action == "cancelled" else post.last_error) == reason


def test_an_invalid_token_holds_every_post_and_tells_miguel(ctx, graph, monkeypatch):
    conn, deal_id = setup(ctx, graph)
    graph.errors[("GET", "content_publishing_limit")] = (
        400, {"error": {"message": f"Error validating access token {TOKEN}", "code": 190}})
    done, _ = run(ctx, conn)
    assert done == [(deal_id, "instagram", "waiting")]
    post = by_channel(conn)["instagram"]
    assert post.attempts == 0 and TOKEN not in post.last_error
    assert post.last_error.startswith("Token do Instagram inválido ou expirado (Error validating "
                                      "access token *** (código 190, HTTP 400))")
    out = cli(ctx, monkeypatch, "queue", "list")
    assert "Token do Instagram inválido ou expirado" in out and TOKEN not in out


def test_a_backlog_still_goes_out_one_carousel_per_run(ctx, graph):
    conn = pipeline.open_db(ctx)
    first = _approved(ctx, conn, graph)
    second = second_deal(ctx, conn)
    from test_posting import approve_event, CHECKED
    approve_event(ctx.object_store, second, checked=CHECKED.replace(second=1))
    pipeline.apply_review_events(ctx, conn, now=APPLIED)
    for deal_id in (first, second):
        db.record_recheck(conn, deal_id, valid=True, latest_price=58, reason="continua",
                          at=utc(2026, 12, 1, 13))
    done, _ = run(ctx, conn, utc(2026, 12, 1, 13, 30))
    assert [d for d in done if d[1] == "instagram"] == [(first, "instagram", "published")]
    assert [m["kind"] for m in graph.media] == ["carousel", "story"]


# --- the token ------------------------------------------------------------------------------

def token_meta(conn) -> dict:
    return db.get_meta_json(conn, instagram.TOKEN_META)


def test_a_token_with_ten_days_or_more_left_is_not_refreshed(ctx, graph):
    conn, _ = setup(ctx, graph)
    db.set_meta(conn, instagram.TOKEN_META, json.dumps({
        "fingerprint": instagram.fingerprint(TOKEN), "first_seen": "2026-11-01T00:00:00Z",
        "expires_at": db.utc_iso(DUE + timedelta(days=10))}))
    run(ctx, conn)
    assert "refresh" not in graph.kinds() and graph.tokens == {TOKEN}


def test_a_token_with_less_than_ten_days_left_is_refreshed_and_miguel_told(ctx, graph,
                                                                         monkeypatch):
    conn, _ = setup(ctx, graph)
    db.set_meta(conn, instagram.TOKEN_META, json.dumps({
        "fingerprint": instagram.fingerprint(TOKEN), "first_seen": "2026-10-01T00:00:00Z",
        "expires_at": db.utc_iso(DUE + timedelta(days=9, hours=23))}))
    new = graph.refresh["access_token"]
    _, lines = run(ctx, conn)
    log = "\n".join(lines)
    [refresh] = [p for _, kind, p in graph.calls if kind == "refresh"]
    assert refresh == {"grant_type": "ig_refresh_token"}
    # Refreshed with the old token before anything is posted; everything after uses the new one.
    assert graph.token_log[0] == ("refresh", TOKEN)
    assert len(graph.token_log) > 1 and {t for _, t in graph.token_log[1:]} == {new}
    assert TOKEN not in log and new not in log
    assert "Token do Instagram renovado a 01/12/2026 às 09:00: atualiza o secret " \
           "INSTAGRAM_ACCESS_TOKEN" in log
    stored = instagram.stored_token(ctx.object_store)
    assert stored["token"] == new and stored["replaces"] == [instagram.fingerprint(TOKEN)]
    meta = token_meta(conn)
    assert meta["fingerprint"] == instagram.fingerprint(new)
    assert meta["expires_at"] == db.utc_iso(DUE + timedelta(days=60))
    assert new not in json.dumps(meta)

    out = cli(ctx, monkeypatch, "queue", "list")
    assert "atualiza o secret INSTAGRAM_ACCESS_TOKEN" in out and new not in out
    assert "válido até 30/01/2027" in out

    # Later runs use the stored token while the secret is the old one; no second refresh.
    graph.calls.clear()
    graph.tokens.clear()
    run(ctx, conn, utc(2026, 12, 1, 13))
    assert "refresh" not in graph.kinds()

    # Miguel updates the secret: the notice goes away.
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", new)
    ctx.__dict__.pop("secrets", None)
    run(ctx, conn, utc(2026, 12, 1, 19))
    assert "secret_outdated" not in token_meta(conn)
    assert "atualiza o secret" not in cli(ctx, monkeypatch, "queue", "list")


def test_a_stored_token_is_refreshed_in_turn_while_the_secret_stays_old(ctx, graph):
    """Miguel never copied the first refreshed token: 50 days later the stored one is due and
    is refreshed itself; the secret (still the original) keeps leading to the newest token."""
    conn, _ = setup(ctx, graph)
    db.set_meta(conn, instagram.TOKEN_META, json.dumps({
        "fingerprint": instagram.fingerprint(TOKEN), "first_seen": "2026-10-01T00:00:00Z",
        "expires_at": db.utc_iso(DUE + timedelta(days=5))}))
    first = graph.refresh["access_token"]
    run(ctx, conn)
    graph.refresh = {"access_token": "IGAAtest-refreshed-3", "expires_in": 5184000}
    later = DUE + timedelta(days=51)                 # the first refreshed token has 9 days left
    graph.token_log.clear()
    instagram.ensure_token(TOKEN, conn=conn, store=ctx.object_store, http=httpx.Client(),
                           login="instagram", version="v23.0", refresh_days=10, now=later,
                           log=lambda line: None)
    assert graph.token_log == [("refresh", first)]
    stored = instagram.stored_token(ctx.object_store)
    assert stored["token"] == "IGAAtest-refreshed-3"
    assert stored["replaces"] == [instagram.fingerprint(TOKEN), instagram.fingerprint(first)]
    token, problem = instagram.ensure_token(
        TOKEN, conn=conn, store=ctx.object_store, http=httpx.Client(), login="instagram",
        version="v23.0", refresh_days=10, now=later, log=lambda line: None)
    assert (token, problem) == ("IGAAtest-refreshed-3", None)
    assert token_meta(conn)["secret_outdated"]


def test_a_new_token_of_unknown_expiry_is_refreshed_once_a_day_old(ctx, graph):
    conn, _ = setup(ctx, graph)                 # first seen by the 07:00 run (Telegram)
    run(ctx, conn)                              # 09:00: too new to refresh
    assert "refresh" not in graph.kinds()
    assert token_meta(conn)["first_seen"] == db.utc_iso(APPLIED)
    assert token_meta(conn)["expires_at"] is None
    graph.calls.clear()
    run(ctx, conn, APPLIED + timedelta(days=1))
    assert graph.kinds()[:1] == ["refresh"]
    assert token_meta(conn)["expires_at"] == db.utc_iso(APPLIED + timedelta(days=61))


def test_an_expired_token_posts_nothing_and_the_posts_wait(ctx, graph):
    conn, deal_id = setup(ctx, graph)
    db.set_meta(conn, instagram.TOKEN_META, json.dumps({
        "fingerprint": instagram.fingerprint(TOKEN), "first_seen": "2026-10-01T00:00:00Z",
        "expires_at": "2026-11-30T09:00:00Z"}))
    done, lines = run(ctx, conn)
    assert done == [(deal_id, "instagram", "waiting")] and graph.calls == []
    assert by_channel(conn)["instagram"].last_error.startswith(
        "O token do Instagram expirou a 30/11/2026 às 09:00")


def test_facebook_login_uses_graph_facebook_com_and_never_refreshes(ctx, graph):
    ctx.config.instagram.login = "facebook"
    conn, deal_id = setup(ctx, graph)
    db.set_meta(conn, instagram.TOKEN_META, json.dumps({     # would be refreshed on Instagram
        "fingerprint": instagram.fingerprint(TOKEN), "first_seen": "2026-10-01T00:00:00Z",
        "expires_at": db.utc_iso(DUE + timedelta(days=3))}))
    facebook = FakeGraph()
    graph.router.route(host="graph.facebook.com").mock(side_effect=facebook)
    run(ctx, conn)
    assert graph.calls == [] and "refresh" not in facebook.kinds()
    assert facebook.calls[0][2] == {"fields": "quota_usage,config"}
    assert [m["kind"] for m in facebook.media] == ["carousel", "story"]


def test_instagram_token_prints_the_stored_token_on_the_pc_only(ctx, graph, monkeypatch):
    from typer.testing import CliRunner
    from escapadinha import cli as cli_module
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    result = CliRunner().invoke(cli_module.app, ["instagram", "token"])
    assert result.exit_code == 1 and "Nenhum token renovado" in result.output

    conn, _ = setup(ctx, graph)
    db.set_meta(conn, instagram.TOKEN_META, json.dumps({
        "fingerprint": instagram.fingerprint(TOKEN), "first_seen": "2026-10-01T00:00:00Z",
        "expires_at": db.utc_iso(DUE + timedelta(days=3))}))
    run(ctx, conn)
    result = CliRunner().invoke(cli_module.app, ["instagram", "token"])
    assert result.exit_code == 0 and graph.refresh["access_token"] in result.output

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    result = CliRunner().invoke(cli_module.app, ["instagram", "token"])
    assert result.exit_code == 1 and graph.refresh["access_token"] not in result.output
