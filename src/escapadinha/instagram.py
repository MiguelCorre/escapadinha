"""Instagram publisher (D36): a due queue item as a carousel, then a story of its cover.

Graph API (content publishing), Instagram API with Instagram Login by default
(`instagram.login` in config: the host is `HOSTS[login]`, the version `instagram.api_version`):

1. the slides' JPEG copies on the public site (`website.deal_jpeg_paths`) must answer 200 to a
   HEAD first; otherwise the post waits for the deploy (no attempt counted);
2. `content_publishing_limit` must leave room for the carousel and its story, else it waits;
3. a carousel already on the account with this caption (a run that died after `media_publish`)
   is adopted, never posted again;
4. one container per slide (`is_carousel_item`), the carousel container with the caption, its
   status polled until FINISHED (bounded, backing off; still IN_PROGRESS: wait for the next run,
   the container is kept), `media_publish`, the permalink;
5. later in the same run (`pipeline.run_publish`), the story: a STORIES container of the cover,
   polled and published the same way. Its failure never touches the carousel.

Every id is stored on the queue row as soon as it is known (`db.save_post_progress`), so a retry
resumes where the last attempt stopped. Graph errors become the queue's signals (`classify`):
token problems, rate and publishing limits and missing permissions wait; media Meta refuses
for good cancels; anything else is retried up to `posting.max_attempts`.

The long-lived token (`ensure_token`) is refreshed when fewer than `instagram.refresh_days`
remain. CI can't write GitHub secrets, so a new token is kept in the object store
(`TOKEN_KEY`, private), used from there by later runs, and Miguel is told to copy it into the
secret (`escapadinha instagram token` prints it on the PC only). The token never appears in a
log, an error or the database (only its fingerprint and expiry, meta `instagram.token`).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from datetime import datetime, timedelta

import httpx

from escapadinha import i18n_pt
from escapadinha.models import Deal, Post
from escapadinha.posting import Message, Published, PublishCancel, PublishWait
from escapadinha.storage import db
from escapadinha.storage.objects import ObjectStore

HOSTS = {"instagram": "https://graph.instagram.com", "facebook": "https://graph.facebook.com"}
RUNBOOK = "docs/runbooks/instagram.md"
README = "README §Instagram"
MAX_CHILDREN = 10                       # Instagram's carousel limit
POLL_DELAYS = (2, 3, 5, 10, 15, 25)     # seconds between status checks (~1 min in all)
QUOTA_CAROUSEL = 2                      # a carousel and its story must both fit the limit
RECENT_MEDIA = 25                       # the account's latest posts searched for a lost publish
TOKEN_KEY = "private/instagram/token.json"   # a refreshed token (object store, never the DB)
TOKEN_META = "instagram.token"          # meta: fingerprint, expiry, notices (never the token)
TOKEN_MIN_AGE = timedelta(days=1)       # Instagram refreshes only tokens at least 24 h old
ACTOR = "instagram-publisher"           # the `published` event's actor

# Graph error codes (Meta's error reference) -> what the queue does.
TOKEN_CODES = {102, 190}                # invalid, expired or revoked token
RATE_CODES = {4, 17, 32, 613, 80002}    # application / user / page rate limits
PERMISSION_CODES = {10, *range(200, 300)}
LIMIT_SUBCODE = 2207042                 # content publishing limit reached
PERMANENT_SUBCODES = {                  # media Meta refuses for good
    2207004: "imagem demasiado grande",
    2207005: "formato de imagem não suportado",
    2207009: "proporção da imagem não suportada",
    2207023: "tipo de media desconhecido",
    2207028: "o carrossel tem de ter entre 2 e 10 imagens",
}


class GraphError(Exception):
    """A Graph API call that failed; the message never holds the token."""

    def __init__(self, message: str, *, status: int | None = None, code: int | None = None,
                 subcode: int | None = None):
        self.status, self.code, self.subcode = status, code, subcode
        parts = [f"código {code}" + (f"/{subcode}" if subcode else "") if code else None,
                 f"HTTP {status}" if status else None]
        detail = ", ".join(p for p in parts if p)
        super().__init__(f"{message} ({detail})" if detail else message)


class InstagramError(RuntimeError):
    """A failure the run retries (attempt counted, D32)."""


class TokenProblem(PublishWait):
    """The token is invalid or expired: nothing is posted until Miguel fixes it."""


def classify(err: GraphError) -> Exception:
    """A Graph error as the queue's signal (pt-PT reason)."""
    if err.code in TOKEN_CODES:
        return TokenProblem(f"Token do Instagram inválido ou expirado ({err}): gera um novo "
                            f"({RUNBOOK}); as publicações esperam.")
    if err.code in RATE_CODES or err.subcode == LIMIT_SUBCODE:
        return PublishWait(f"Limite de pedidos ou de publicações da API do Instagram ({err}): "
                           "tenta na próxima execução.")
    if err.code in PERMISSION_CODES:
        return PublishWait(f"A app não tem permissão para publicar ({err}): revê as permissões "
                           f"({RUNBOOK}).")
    if err.subcode in PERMANENT_SUBCODES:
        return PublishCancel(f"O Instagram recusou as imagens: {PERMANENT_SUBCODES[err.subcode]} "
                             f"({err}).")
    return InstagramError(f"Erro da API do Instagram: {err}")


class Graph:
    """Graph API calls with one token (`access_token` parameter, as Meta documents)."""

    def __init__(self, http: httpx.Client, *, host: str, version: str, token: str):
        self.http, self.host, self.version, self.token = http, host, version, token

    def _redact(self, text: str) -> str:
        return text.replace(self.token, "***") if self.token else text

    def call(self, method: str, path: str, *, versioned: bool = True, **params: str) -> dict:
        url = f"{self.host}/{self.version}/{path}" if versioned else f"{self.host}/{path}"
        params = {**params, "access_token": self.token}
        try:
            if method == "GET":
                response = self.http.get(url, params=params)
            else:
                response = self.http.post(url, data=params)
        except httpx.HTTPError as exc:          # its text can hold the URL: never shown raw
            raise GraphError(f"sem resposta da API ({type(exc).__name__})") from None
        try:
            body = response.json()
        except ValueError:
            body = None
        error = body.get("error") if isinstance(body, dict) else None
        if response.status_code >= 400 or error is not None:
            error = error if isinstance(error, dict) else {}
            message = self._redact(str(error.get("message") or "erro sem mensagem"))
            raise GraphError(message, status=response.status_code, code=error.get("code"),
                             subcode=error.get("error_subcode"))
        if not isinstance(body, dict):
            raise GraphError("resposta da API inválida", status=response.status_code)
        return body

    def get(self, path: str, **params: str) -> dict:
        return self.call("GET", path, **params)

    def post(self, path: str, **params: str) -> dict:
        return self.call("POST", path, **params)


def caption_key(text: str | None) -> str:
    """A caption compared line by line, ignoring blank lines and outer spaces."""
    return "\n".join(line.strip() for line in (text or "").splitlines() if line.strip())


class InstagramPublisher:
    """`posting.Publisher` for the instagram channel (D36). Injected: the Graph client, the
    deal's public JPEG URLs, a HEAD check (status code), where progress is saved, the sleeper."""

    name = "instagram"

    def __init__(self, graph: Graph, account_id: str, *,
                 image_urls: Callable[[Deal], list[str]], head: Callable[[str], int],
                 save: Callable[..., None], sleep: Callable[[float], None] = time.sleep,
                 log: Callable[[str], None] = print,
                 on_token_problem: Callable[[str], None] = lambda reason: None):
        self.graph, self.account = graph, account_id
        self.image_urls, self.head, self.save = image_urls, head, save
        self.sleep, self.log, self.on_token_problem = sleep, log, on_token_problem

    # --- the carousel ------------------------------------------------------------------------

    def publish(self, message: Message) -> Published:
        post = message.post
        try:
            media_id = post.media_id or self._carousel(message)
        except GraphError as err:
            raise self._signal(err) from None
        return Published(self._permalink(media_id), marks_published=True, story=True)

    def _carousel(self, message: Message) -> str:
        post = message.post
        urls = self._live_images(message.deal)
        self._check_quota(QUOTA_CAROUSEL)
        found = self._already_posted(message.text)
        if found:
            self.log(f"Instagram: o carrossel do deal {post.deal_id} já estava publicado "
                     f"({found}): não volta a ser publicado.")
            self.save(post.id, media_id=found, container_id=None)
            return found
        container = post.container_id
        if container:
            status, _ = self._status(container)
            if status == "PUBLISHED":           # out, but not among the latest posts
                raise PublishCancel(
                    f"O carrossel já foi publicado (contentor {container}) mas o post não foi "
                    "encontrado: confirma no Instagram e marca a promoção como publicada.")
            if status in ("ERROR", "EXPIRED"):
                container = None
        if not container:
            container = self._create_carousel(urls[:MAX_CHILDREN], message.text)
            self.save(post.id, container_id=container)
        self._wait_finished(container, lambda: self.save(post.id, container_id=None))
        media_id = str(self.graph.post(f"{self.account}/media_publish",
                                       creation_id=container)["id"])
        self.save(post.id, media_id=media_id, container_id=None)
        return media_id

    def _create_carousel(self, urls: list[str], caption: str) -> str:
        if len(urls) == 1:                      # one slide: a single-image post
            return str(self.graph.post(f"{self.account}/media", image_url=urls[0],
                                       caption=caption)["id"])
        children = [str(self.graph.post(f"{self.account}/media", image_url=url,
                                        is_carousel_item="true")["id"]) for url in urls]
        return str(self.graph.post(f"{self.account}/media", media_type="CAROUSEL",
                                   children=",".join(children), caption=caption)["id"])

    # --- the story ---------------------------------------------------------------------------

    def publish_story(self, post: Post, deal: Deal) -> str | None:
        """The cover slide as a story; its media id (None when it was already out but the id
        is unknown). Same signals as `publish`."""
        try:
            return self._story(post, deal)
        except GraphError as err:
            raise self._signal(err) from None

    def _story(self, post: Post, deal: Deal) -> str | None:
        cover = self._live_images(deal)[0]
        container = post.story_container_id
        if container:
            status, _ = self._status(container)
            if status == "PUBLISHED":
                self.save(post.id, story_container_id=None)
                return None
            if status in ("ERROR", "EXPIRED"):
                container = None
        if not container:
            self._check_quota(1)
            container = str(self.graph.post(f"{self.account}/media", image_url=cover,
                                            media_type="STORIES")["id"])
            self.save(post.id, story_container_id=container)
        self._wait_finished(container, lambda: self.save(post.id, story_container_id=None))
        media_id = str(self.graph.post(f"{self.account}/media_publish",
                                       creation_id=container)["id"])
        self.save(post.id, story_media_id=media_id, story_container_id=None)
        return media_id

    # --- shared steps ------------------------------------------------------------------------

    def _signal(self, err: GraphError) -> Exception:
        signal = classify(err)
        if isinstance(signal, TokenProblem):
            self.on_token_problem(str(signal))
        return signal

    def _live_images(self, deal: Deal) -> list[str]:
        """The slides' public JPEG URLs, once every one answers 200 (the deploy that carries
        them may still be to come: a new approval's full path runs after the publish step)."""
        urls = self.image_urls(deal)
        if not urls:
            raise PublishCancel("A promoção não tem slides renderizados.")
        for url in urls[:MAX_CHILDREN]:
            status = self.head(url)
            if status != 200:
                raise PublishWait(f"As imagens ainda não estão no site ({url} → "
                                  f"{status or 'sem resposta'}): espera pelo próximo deploy.")
        return urls

    def _check_quota(self, needed: int) -> None:
        body = self.graph.get(f"{self.account}/content_publishing_limit",
                              fields="quota_usage,config")
        data = (body.get("data") or [{}])[0]
        used = int(data.get("quota_usage") or 0)
        total = int((data.get("config") or {}).get("quota_total") or 0)
        if total and total - used < needed:
            raise PublishWait(f"Limite de publicações do Instagram: {used} de {total} nas "
                              "últimas 24 h; espera.")

    def _already_posted(self, caption: str) -> str | None:
        body = self.graph.get(f"{self.account}/media", fields="id,caption,timestamp",
                              limit=str(RECENT_MEDIA))
        wanted = caption_key(caption)
        return next((str(m["id"]) for m in body.get("data") or []
                     if caption_key(m.get("caption")) == wanted), None)

    def _status(self, container: str) -> tuple[str, str]:
        body = self.graph.get(container, fields="status_code,status")
        return str(body.get("status_code") or ""), str(body.get("status") or "")

    def _wait_finished(self, container: str, forget: Callable[[], None]) -> None:
        """Poll until FINISHED; ERROR/EXPIRED forgets the container (a new one next time) and
        fails; still in progress after the last poll waits for the next run (kept)."""
        for delay in (0, *POLL_DELAYS):
            if delay:
                self.sleep(delay)
            status, detail = self._status(container)
            if status in ("FINISHED", "PUBLISHED"):
                return
            if status in ("ERROR", "EXPIRED"):
                forget()
                raise InstagramError(f"O Instagram não processou as imagens ({status}"
                                     + (f": {detail}" if detail else "") + ").")
        raise PublishWait("O Instagram ainda está a processar as imagens: a próxima execução "
                          "continua.")

    def _permalink(self, media_id: str) -> str | None:
        try:
            return self.graph.get(media_id, fields="permalink").get("permalink") or None
        except GraphError as err:               # the post is out: no URL is no failure
            self.log(f"Instagram: post {media_id} publicado, sem link ({err}).")
            return None


class Paused:
    """The instagram channel while the token can't be used: every due post waits."""

    name = "instagram"

    def __init__(self, reason: str):
        self.reason = reason

    def publish(self, message: Message) -> Published:
        raise PublishWait(self.reason)

    def publish_story(self, post: Post, deal: Deal) -> str | None:
        raise PublishWait(self.reason)


# --- the long-lived token ----------------------------------------------------------------------

def fingerprint(token: str) -> str:
    """Tells tokens apart in meta and logs without revealing them."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def stored_token(store: ObjectStore) -> dict | None:
    """The latest refreshed token, kept for later runs and for Miguel to copy: {token,
    fingerprint, expires_at, refreshed_at, replaces: fingerprints of the tokens it replaced}."""
    try:
        return json.loads(store.get(TOKEN_KEY))
    except KeyError:
        return None


def _iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def ensure_token(secret: str, *, conn, store: ObjectStore, http: httpx.Client, login: str,
                 version: str, refresh_days: int, now: datetime,
                 log: Callable[[str], None]) -> tuple[str | None, str | None]:
    """(token to publish with, None) or (None, why nothing can be posted, pt-PT).

    The secret is the seed. A token this pipeline refreshed (`TOKEN_KEY`) replaces it while the
    secret is still one it replaced (Miguel hasn't updated the secret yet). With Instagram Login,
    a token whose expiry is within `refresh_days`, or unknown (a new secret: refreshing tells
    its expiry) and at least a day old, is refreshed; a new token string is stored and Miguel is
    told to update the secret. Meta `instagram.token` keeps the fingerprint, expiry and notices
    `notices` shows."""
    meta = db.get_meta_json(conn, TOKEN_META)
    stored = stored_token(store)
    secret_fp = fingerprint(secret)
    outdated = bool(stored and secret_fp in stored.get("replaces", []))
    if outdated:
        token, expires = stored["token"], _iso(stored.get("expires_at"))
    else:
        token = secret
        expires = (_iso(stored.get("expires_at")) if stored and stored["fingerprint"] == secret_fp
                   else _iso(meta.get("expires_at")) if meta.get("fingerprint") == secret_fp
                   else None)
    fp = fingerprint(token)
    if meta.get("fingerprint") != fp:
        meta = {"fingerprint": fp, "first_seen": db.utc_iso(now), "expires_at": db.utc_iso(expires)}
    if outdated:                                 # Miguel hasn't copied the stored token yet
        meta.setdefault("secret_outdated", stored.get("refreshed_at") or db.utc_iso(now))
    else:
        meta.pop("secret_outdated", None)        # the secret is the current token
    if expires is not None and expires <= now:
        meta["problem"] = (f"O token do Instagram expirou a {i18n_pt.lisbon_timestamp(expires)}: "
                           f"gera um novo ({RUNBOOK}); as publicações esperam.")
        db.set_meta(conn, TOKEN_META, json.dumps(meta))
        return None, meta["problem"]
    first_seen = _iso(meta.get("first_seen")) or now
    due = (expires - now < timedelta(days=refresh_days) if expires is not None
           else now - first_seen >= TOKEN_MIN_AGE)
    if login == "instagram" and due:
        graph = Graph(http, host=HOSTS["instagram"], version=version, token=token)
        try:
            body = graph.call("GET", "refresh_access_token", versioned=False,
                              grant_type="ig_refresh_token")
            new, seconds = str(body["access_token"]), int(body["expires_in"])
        except GraphError as err:
            if err.code in TOKEN_CODES:
                meta["problem"] = str(classify(err))
                db.set_meta(conn, TOKEN_META, json.dumps(meta))
                return None, meta["problem"]
            log(f"Instagram: não foi possível renovar o token ({err}); tenta na próxima execução.")
        except (KeyError, TypeError, ValueError):
            log("Instagram: resposta inesperada ao renovar o token; tenta na próxima execução.")
        else:
            expires = now + timedelta(seconds=seconds)
            if new != token or outdated:        # a new string, or the stored one's new expiry
                replaced = [*(stored or {}).get("replaces", [])] if outdated else []
                store.put(TOKEN_KEY, json.dumps({
                    "token": new, "fingerprint": fingerprint(new),
                    "expires_at": db.utc_iso(expires), "refreshed_at": db.utc_iso(now),
                    "replaces": replaced + ([fp] if new != token else []),
                }).encode("utf-8"))
            if new != token:
                token, fp = new, fingerprint(new)
                meta["secret_outdated"] = db.utc_iso(now)
                log(secret_notice(now))
            meta.update(fingerprint=fp, expires_at=db.utc_iso(expires),
                        refreshed_at=db.utc_iso(now))
            meta.setdefault("first_seen", db.utc_iso(now))
            log(f"Instagram: token renovado, válido até {i18n_pt.lisbon_timestamp(expires)}.")
    meta.pop("problem", None)
    db.set_meta(conn, TOKEN_META, json.dumps(meta))
    return token, None


def secret_notice(at: datetime) -> str:
    return (f"Token do Instagram renovado a {i18n_pt.lisbon_timestamp(at)}: atualiza o secret "
            "INSTAGRAM_ACCESS_TOKEN no GitHub e no .env (`escapadinha instagram token` mostra-o "
            f"neste PC) — {README}.")


def token_problem(conn, reason: str) -> None:
    """A call refused the token: kept in meta until a run gets through with it."""
    meta = db.get_meta_json(conn, TOKEN_META)
    meta["problem"] = reason
    db.set_meta(conn, TOKEN_META, json.dumps(meta))


def notices(conn) -> list[str]:
    """What `queue list` says about the token (pt-PT): an outdated secret, a token problem,
    its expiry."""
    meta = db.get_meta_json(conn, TOKEN_META)
    out = []
    if meta.get("secret_outdated"):
        out.append(secret_notice(_iso(meta["secret_outdated"])))
    if meta.get("problem"):
        out.append(meta["problem"])
    if meta.get("expires_at"):
        out.append(f"Token do Instagram válido até "
                   f"{i18n_pt.lisbon_timestamp(_iso(meta['expires_at']))}.")
    return out
