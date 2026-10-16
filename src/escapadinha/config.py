"""Configuration: secrets from .env (pydantic-settings) + behaviour from config.yaml."""

from __future__ import annotations

import os
from datetime import time
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import parse_qs, urlsplit

import yaml

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from escapadinha.posting import CHANNELS as POST_CHANNELS

if TYPE_CHECKING:
    from escapadinha.storage.objects import ObjectStore


def project_root() -> Path:
    """Root holding config.yaml, data/ and output/. Override with ESCAPADINHA_HOME."""
    return Path(os.environ.get("ESCAPADINHA_HOME", Path.cwd())).resolve()


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    travelpayouts_token: str = ""
    travelpayouts_marker: str = ""
    pixabay_api_key: str = ""
    cloudflare_api_token: str = ""
    cloudflare_account_id: str = ""
    r2_endpoint: str = ""             # https://<account-id>.r2.cloudflarestorage.com
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
    # Instagram publisher (D36), optional: without both, due Instagram posts wait.
    instagram_access_token: str = ""  # long-lived token (Instagram Login), docs/runbooks/instagram.md
    instagram_account_id: str = ""    # the professional account's Instagram user id
    # Telegram publisher (D38), optional: without both, due Telegram posts wait.
    telegram_bot_token: str = ""      # from @BotFather, docs/runbooks/telegram.md
    telegram_channel: str = ""        # the public channel's @handle (checked by the publisher)

    @property
    def instagram_configured(self) -> bool:
        return bool(self.instagram_access_token.strip() and self.instagram_account_id.strip())

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token.strip() and self.telegram_channel.strip())

    @property
    def r2_configured(self) -> bool:
        """All four R2 keys set: the database, archives, backups and lock live in R2."""
        return all((self.r2_endpoint, self.r2_access_key_id, self.r2_secret_access_key,
                    self.r2_bucket))


class Brand(BaseModel):
    name: str = "Escapadinha"
    tagline: str = ""
    handle: str = "@escapadinha.pt"   # Instagram handle: CTA slide, hashtag, site links

    @property
    def instagram_url(self) -> str:
        return f"https://www.instagram.com/{self.handle.lstrip('@')}/"


class CollectorConfig(BaseModel):
    source: str = "travelpayouts"
    currency: str = "eur"
    months_ahead: int = Field(3, ge=1, le=12)          # departure months every run asks for
    daily_months_ahead: int = Field(6, ge=1, le=12)    # ... and the day's pass (D42)
    daily_pass_hour: int = Field(6, ge=0, le=23)       # Lisbon: the first run from then is the pass
    limit_per_request: int = Field(100, ge=1, le=1000)
    market: str | None = "pt"                     # Aviasales market whose searches feed the cache
    booking_base: str = "https://www.aviasales.pt"  # booking site linked from posts (EUR, EU formats)
    requests_per_minute: int = Field(550, ge=1)   # client-side cap; the API allows 600/min
    workers: int = Field(8, ge=1, le=32)          # concurrent requests (same per-minute cap)

    @model_validator(mode="after")
    def _daily_pass_asks_more(self):
        if self.daily_months_ahead < self.months_ahead:
            raise ValueError("collector.daily_months_ahead must be >= collector.months_ahead "
                             "(the day's pass asks every run's months and the farther ones)")
        return self


class DetectorConfig(BaseModel):
    """Two tiers (D24): low prices (>= low_threshold below the typical low, automatic on the
    site) and promotion candidates (>= threshold AND >= min_saving_eur below, reviewed).

    A typical low is mature (D40) after enough daily lows, counting only days that saw at
    least `min_dates_per_day` departure dates: `min_baseline_days` for low prices and the
    site's typical lows, `min_baseline_days_promo` spanning `min_baseline_span_days` (first to
    last day) for promotion candidates."""

    threshold: float = Field(0.30, gt=0, lt=1)
    min_saving_eur: float = Field(15, ge=0)
    low_threshold: float = Field(0.15, gt=0, lt=1)
    lookback_days: int = Field(90, ge=1)
    min_dates_per_day: int = Field(2, ge=1)
    min_baseline_days: int = Field(7, ge=1)
    min_baseline_days_promo: int = Field(10, ge=1)
    min_baseline_span_days: int = Field(9, ge=0)
    dedupe_days: int = Field(7, ge=0)
    max_deals_per_route: int = Field(1, ge=1)
    max_offer_age_days: int = Field(3, ge=0)

    @model_validator(mode="after")
    def _tiers_nest(self):
        if self.low_threshold > self.threshold:
            raise ValueError("detector.low_threshold must be <= detector.threshold "
                             "(every promotion candidate is also a low price)")
        if self.min_baseline_days_promo < self.min_baseline_days:
            raise ValueError("detector.min_baseline_days_promo must be >= "
                             "detector.min_baseline_days (every promotion candidate is also "
                             "a low price)")
        return self


RouteKind = Literal["europe", "long_haul", "domestic"]


class RuleSet(BaseModel):
    """Default rules for one route kind (see models.RouteRules)."""

    direct_only: bool = True
    min_nights: int = Field(2, ge=1)
    max_nights: int = Field(10, ge=1)
    max_transfers: int | None = Field(0, ge=0)

    @model_validator(mode="after")
    def _nights_order(self):
        if self.min_nights > self.max_nights:
            raise ValueError("min_nights must be <= max_nights")
        return self


class RuleOverride(BaseModel):
    """Per-route exceptions; unset fields keep the kind default."""

    direct_only: bool | None = None
    min_nights: int | None = Field(None, ge=1)
    max_nights: int | None = Field(None, ge=1)
    max_transfers: int | None = Field(None, ge=0)
    price_cap_eur: float | None = None   # absolute ceiling used only while history is short


class SeedRoute(BaseModel):
    origin: str
    destination: str
    city_pt: str
    kind: RouteKind = "europe"


class LongHaulDestination(BaseModel):
    destination: str
    city_pt: str
    origins: list[str] = ["LIS", "OPO"]


DEFAULT_KINDS: dict[str, RuleSet] = {
    "europe": RuleSet(),
    "domestic": RuleSet(),
    "long_haul": RuleSet(direct_only=False, min_nights=7, max_nights=21, max_transfers=1),
}


class RoutesConfig(BaseModel):
    """Routes live in the database; config only shapes them (see routes.py)."""

    kinds: dict[RouteKind, RuleSet] = DEFAULT_KINDS
    overrides: dict[str, RuleOverride] = {}   # "LIS-LON": {max_nights: 7}
    exclusions: list[str] = []                # route keys ("LIS-LON") or destinations ("LON")
    long_haul: list[LongHaulDestination] = []
    seed: list[SeedRoute] = []                # inserted once into an empty routes table
    # Discovery (#5): airports whose direct routes are discovered, how often, and when a
    # route without prices goes dormant.
    origins: list[str] = ["LIS", "OPO", "FAO", "FNC", "PDL", "TER"]
    discover_every_days: int = Field(30, ge=1)
    dormant_after_days: int = Field(30, ge=1)
    city_names: dict[str, str] = {}           # destination -> Portuguese name (beats the catalogue)

    @model_validator(mode="after")
    def _all_kinds(self):
        self.kinds = {**DEFAULT_KINDS, **self.kinds}
        self.overrides = {k.upper(): v for k, v in self.overrides.items()}
        self.exclusions = [e.upper() for e in self.exclusions]
        self.origins = [o.upper() for o in self.origins]
        self.city_names = {k.upper(): v for k, v in self.city_names.items()}
        return self

    def excluded(self, origin: str, destination: str) -> bool:
        return f"{origin}-{destination}" in self.exclusions or destination in self.exclusions


def host_of(value: str) -> str:
    """'https://Example.pt/x' or 'example.pt' -> 'example.pt'."""
    value = value.strip()
    return (urlsplit(value if "//" in value else f"//{value}").hostname or "").lower()


# Hosts Travelpayouts' widget constructor serves its script embeds from (D34). The contract's
# meta.schema.json `search_widget` pattern lists the same hosts (a test compares them). If the
# constructor ever hands out another host, add it to both.
SEARCH_WIDGET_HOSTS: tuple[str, ...] = ("tp.media", "tpwgts.com", "tpembd.com", "tpemd.com", "tpscr.com")
_UNSAFE_URL_CHARS = set(" \t\r\n\"'<>`\\")
WIDGET_RUNBOOK = "docs/runbooks/search-widget.md"


class ConfigError(ValueError):
    """config.yaml and .env disagree (e.g. the search widget was made for another account)."""


def search_widget_problem(src: str, *, project: int | None, marker: str | None) -> str | None:
    """Why the widget script `src` isn't ours, or None. Its affiliate Project (`trs`) must be the
    website's (`affiliate.project_for("website")`, D19), so the commissions land there; with our
    partner marker known (TRAVELPAYOUTS_MARKER), its `shmarker` must be that marker (or
    `<marker>.<sub id>`, the constructor's sub id form). Checked on top of the host allowlist."""
    params = parse_qs(urlsplit(src).query)
    if project is None:
        return "no affiliate Project for the website (affiliate.projects)"
    trs = params.get("trs", [])
    if trs != [str(project)]:
        found = f"trs={','.join(trs)}" if trs else "no trs"
        return (f"it has {found}, not the website's Project trs={project} "
                "(affiliate.project_for('website'))")
    if marker:
        shmarker = params.get("shmarker", [])
        if len(shmarker) != 1 or not (shmarker[0] == marker
                                      or shmarker[0].startswith(f"{marker}.")):
            found = "a different shmarker" if shmarker else "no shmarker"
            return f"it has {found}: the widget must carry our partner marker (TRAVELPAYOUTS_MARKER)"
    return None


class SiteConfig(BaseModel):
    base_url: str = "https://ondestaanocas.pages.dev"   # canonical URLs, sitemap, OG tags
    domain: str | None = None        # final domain (D19); live once base_url points at it
    legacy_hosts: list[str] = []     # old hosts: Bulk Redirect to base_url + noindex in _headers
    redirects: dict[str, str] = {}   # extra old path -> new path (301), written to _redirects
    cloudflare_project: str = "ondestaanocas"
    wrangler_version: str = "4.149.0"
    # Cloudflare Web Analytics beacon token (cookieless), optional. Null while the zone's
    # automatic setup measures at the edge (D34): a token too would count every visit twice.
    analytics_token: str | None = None
    # Aviasales search form (D34): the `src` of the script Travelpayouts' widget constructor gives
    # (Tools → Widgets → Search form, Project "Pontonomada"). Null: no widget anywhere.
    search_widget: str | None = None
    recent_expired: int = 6              # expired deals listed per route page
    # Low prices on route pages (D24): the biggest discounts per route, each with its own
    # tracked link from the partner links API, created once and stored in `partner_links`.
    low_prices_per_route: int = Field(5, ge=0)
    # New low-price partner links per collection run, shared by the site data export and the
    # site build (the export first), biggest discounts first; the rest wait for the next run.
    # <= 900 keeps one build under the API's 100 requests/min (10 links per request).
    max_new_links_per_build: int = Field(300, ge=0, le=900)
    # Website data contract v1 (D27): where `export site-data` writes (relative to the
    # project root; the Astro build in web/ reads it, D35) and the row cap of each per-origin
    # low-price file (size budget).
    data_dir: str = "web/src/data"
    max_low_prices_per_origin: int = Field(1500, ge=1)
    # Expired promotions stay in the export (and on the site, noindex) this many days after they
    # expired; afterwards their links 301 to the route page (`website.routing`, D35).
    expired_promotions_days: int = Field(30, ge=0)

    @field_validator("base_url")
    @classmethod
    def _https_no_trailing_slash(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("site.base_url must start with https://")
        return v.rstrip("/")

    @field_validator("analytics_token")
    @classmethod
    def _plain_token(cls, v: str | None) -> str | None:
        if v is not None and not (16 <= len(v) <= 64 and v.isascii() and v.isalnum()):
            raise ValueError("site.analytics_token must be the token Cloudflare shows (letters and digits)")
        return v

    @field_validator("search_widget")
    @classmethod
    def _widget_script(cls, v: str | None) -> str | None:
        if v is None:
            return v
        parts = urlsplit(v)
        if (parts.scheme != "https" or parts.hostname not in SEARCH_WIDGET_HOSTS
                or parts.port is not None or parts.username is not None
                or any(c in _UNSAFE_URL_CHARS for c in v)):
            raise ValueError("site.search_widget must be the https script URL from Travelpayouts' "
                             f"widget constructor (hosts: {', '.join(SEARCH_WIDGET_HOSTS)})")
        return v

    @field_validator("domain")
    @classmethod
    def _domain_host(cls, v: str | None) -> str | None:
        return host_of(v) or None if v else None

    @field_validator("legacy_hosts")
    @classmethod
    def _hosts_only(cls, v: list[str]) -> list[str]:
        return [host_of(h) for h in v if host_of(h)]

    @field_validator("redirects")
    @classmethod
    def _paths(cls, v: dict[str, str]) -> dict[str, str]:
        for source, target in v.items():
            if not source.startswith("/") or any(c.isspace() for c in source):
                raise ValueError(f"site.redirects: source must be a path starting with '/': {source!r}")
            if not target.startswith(("/", "https://")) or any(c.isspace() for c in target):
                raise ValueError(f"site.redirects: target must be a path or https URL: {target!r}")
        return v

    @property
    def host(self) -> str:
        return host_of(self.base_url)

    @property
    def on_final_domain(self) -> bool:
        """True once base_url points at the final domain (or none is configured)."""
        return self.domain is None or self.host in (self.domain, f"www.{self.domain}")

    @property
    def retired_hosts(self) -> list[str]:
        """Legacy hosts other than the one the site is served from now: these get noindex."""
        return [h for h in self.legacy_hosts if h != self.host]


Channel = Literal["instagram", "website"]
CHANNELS: tuple[str, ...] = ("instagram", "website")


# The affiliate blocks content authors can place in itineraries and tips (D37). Which brand
# each one links to is config (`affiliate.programmes`), never code.
Programme = Literal["esim", "insurance", "activities"]
PROGRAMMES: tuple[str, ...] = ("esim", "insurance", "activities")


class ProgrammeConfig(BaseModel):
    """A Travelpayouts programme the website Project is connected to (D37): the brand named in
    the block and the brand page the partner links API turns into a tracked link."""
    brand: str = Field(min_length=1)
    url: str                                   # the brand's site, e.g. https://yesim.tech
    # Optional deeper page per destination city code (an itinerary's `destination`), e.g. the
    # brand's landing page for that city; the brand's site otherwise.
    destinations: dict[str, str] = {}

    @field_validator("url")
    @classmethod
    def _https(cls, v: str) -> str:
        return _brand_url(v)

    @field_validator("destinations")
    @classmethod
    def _pages(cls, v: dict[str, str]) -> dict[str, str]:
        for code, url in v.items():
            if not (len(code) == 3 and code.isalpha() and code.isupper()):
                raise ValueError(f"destination {code!r} must be a city code such as PAR")
            _brand_url(url)
        return v

    def target(self, destination: str | None) -> str:
        """The brand page an article about `destination` links to."""
        return self.destinations.get(destination or "", self.url)


def _brand_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc or any(c.isspace() for c in url):
        raise ValueError(f"must be an https URL: {url!r}")
    if "marker" in parse_qs(parts.query):
        raise ValueError(f"must be the brand's own page, never a hand-built marker= link: {url!r}")
    return url


class AffiliateConfig(BaseModel):
    """Travelpayouts Projects ("trs"), one per traffic source, each subscribed to Aviasales.

    `projects.website` falls back to the Instagram Project, and `projects.instagram` falls
    back to the older single `project_id` key, so older config files keep working.
    """
    project_id: int | None = None              # legacy single Project (treated as Instagram)
    projects: dict[str, int | None] = {}       # {instagram: 584711, website: null}
    shorten: bool = True
    # Affiliate blocks (D37): programme -> brand and page; null or absent = not configured (the
    # block renders nothing and the site build warns).
    programmes: dict[str, ProgrammeConfig | None] = {}

    @field_validator("programmes")
    @classmethod
    def _known_programmes(cls, v: dict) -> dict:
        unknown = sorted(set(v) - set(PROGRAMMES))
        if unknown:
            raise ValueError(f"affiliate.programmes: unknown programme(s) {unknown}, "
                             f"use {list(PROGRAMMES)}")
        return v

    def programme(self, name: str) -> ProgrammeConfig | None:
        """A block's programme, or None while it is not configured."""
        if name not in PROGRAMMES:
            raise ValueError(f"unknown programme {name!r}")
        return self.programmes.get(name)

    @field_validator("projects")
    @classmethod
    def _known_channels(cls, v: dict[str, int | None]) -> dict[str, int | None]:
        unknown = sorted(set(v) - set(CHANNELS))
        if unknown:
            raise ValueError(f"affiliate.projects: unknown channel(s) {unknown}, use {list(CHANNELS)}")
        return v

    def project_for(self, channel: Channel) -> int | None:
        if channel not in CHANNELS:
            raise ValueError(f"unknown channel {channel!r}")
        if channel == "website" and self.projects.get("website") is not None:
            return self.projects["website"]
        if self.projects.get("instagram") is not None:
            return self.projects["instagram"]
        return self.project_id


class PhotosConfig(BaseModel):
    queries: dict[str, str] = {}
    # Photos fetched automatically per discovery/run for destinations still without one.
    # Each costs 2 Pixabay requests (search + download); the API allows 100 per minute.
    max_per_run: int = Field(40, ge=0, le=45)


class ReviewConfig(BaseModel):
    # An approval's live price check stays valid this long: older approve events are refused
    # when the pipeline applies them (D26). Reject and published events never expire.
    approve_max_age_hours: float = Field(24, gt=0)


PublisherName = Literal["dry-run", "instagram", "telegram"]


# The Graph API host per login flow (D36): the only place it is written.
GRAPH_HOSTS = {"instagram": "https://graph.instagram.com", "facebook": "https://graph.facebook.com"}


class InstagramConfig(BaseModel):
    """The Instagram publisher's Graph API (D36). `login: instagram` is the Instagram API with
    Instagram Login (graph.instagram.com, no Facebook Page; its long-lived token is refreshed
    when fewer than `refresh_days` remain); `facebook` is the Facebook Login variant
    (graph.facebook.com, the account linked to a Page; it needs a Page token that never
    expires, so no refresh). The endpoints are the same; only the host and the token handling
    change. `images_wait_hours`: how long after its slot a post may wait for its JPEGs to be
    live on the site before each further wait counts as a failed attempt."""
    login: Literal["instagram", "facebook"] = "instagram"
    api_version: str = Field("v23.0", pattern=r"^v\d+\.\d+$")
    refresh_days: int = Field(10, ge=1, le=59)
    images_wait_hours: float = Field(24, gt=0)

    @property
    def host(self) -> str:
        return GRAPH_HOSTS[self.login]

    @property
    def refreshes(self) -> bool:
        """Only Instagram Login tokens expire (60 days) and can be refreshed."""
        return self.login == "instagram"


# The Telegram Bot API host (D38): the only place it is written.
TELEGRAM_API = "https://api.telegram.org"


class TelegramConfig(BaseModel):
    """The Telegram publisher (D38). `images_wait_hours`: how long after it was due a post may
    wait for its cover JPEG to be live on the site before each further wait counts as a failed
    attempt (as Instagram's, D36)."""
    images_wait_hours: float = Field(24, gt=0)


class PostingConfig(BaseModel):
    """Posting queue (D32): when approved promotions go out, and through which publisher."""
    # Instagram daily slots, Lisbon time ("HH:MM"), and the most posts a Lisbon day gets.
    instagram_slots: list[str] = ["09:00", "13:00", "19:00"]
    max_per_day: int = Field(3, ge=1)
    # A post goes out only if its promotion was rechecked (or approved) this recently;
    # otherwise it waits for a run whose recheck covers it.
    max_check_age_hours: float = Field(6, gt=0)
    max_attempts: int = Field(5, ge=1)       # a publisher error this often cancels the post
    # channel (posting.CHANNELS) -> publisher; a channel left out gets the dry run. `instagram`
    # and `telegram` (each on its own channel only) make due posts wait while their secrets
    # (INSTAGRAM_*, TELEGRAM_*) are unset.
    publishers: dict[str, PublisherName] = {channel: "dry-run" for channel in POST_CHANNELS}

    @field_validator("instagram_slots")
    @classmethod
    def _slot_times(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("posting.instagram_slots needs at least one 'HH:MM'")
        for item in v:
            try:
                time.fromisoformat(item)
            except ValueError:
                raise ValueError(f"posting.instagram_slots: {item!r} is not 'HH:MM'") from None
        if len(set(v)) != len(v):
            raise ValueError("posting.instagram_slots has a repeated time")
        return sorted(v)

    @field_validator("publishers")
    @classmethod
    def _known_channels(cls, v: dict[str, str]) -> dict[str, str]:
        unknown = sorted(set(v) - set(POST_CHANNELS))
        if unknown:
            raise ValueError(f"posting.publishers: unknown channel(s) {unknown}, "
                             f"use {list(POST_CHANNELS)}")
        for channel, name in sorted(v.items()):
            if name != "dry-run" and name != channel:
                raise ValueError(f"posting.publishers: the {name} publisher only posts to the "
                                 f"{name} channel, not {channel!r}")
        return {**{channel: "dry-run" for channel in POST_CHANNELS}, **v}

    @property
    def slots(self) -> list[time]:
        return [time.fromisoformat(s) for s in self.instagram_slots]


class AppConfig(BaseModel):
    brand: Brand = Brand()
    review: ReviewConfig = ReviewConfig()
    posting: PostingConfig = PostingConfig()
    instagram: InstagramConfig = InstagramConfig()
    telegram: TelegramConfig = TelegramConfig()
    collector: CollectorConfig = CollectorConfig()
    detector: DetectorConfig = DetectorConfig()
    routes: RoutesConfig = RoutesConfig()
    origins_pt: dict[str, str] = {}
    # The definite article an origin's name takes in a sentence ("desde o Porto", "desde a
    # Madeira"); none for the others ("desde Lisboa"). Exported in origins.json for the site.
    origins_article: dict[str, Literal["o", "a", "os", "as"]] = {}
    photos: PhotosConfig = PhotosConfig()
    affiliate: AffiliateConfig = AffiliateConfig()
    site: SiteConfig = SiteConfig()

    @model_validator(mode="after")
    def _widget_for_the_website(self) -> AppConfig:
        """The search widget's Project is the website's (the marker is checked by
        `Context.search_widget`, which has the secrets)."""
        src = self.site.search_widget
        problem = src and search_widget_problem(
            src, project=self.affiliate.project_for("website"), marker=None)
        if problem:
            raise ValueError(f"site.search_widget: {problem}. Make the widget in Travelpayouts' "
                             f"constructor with the website's Project ({WIDGET_RUNBOOK})")
        return self

    def origin_name(self, iata: str) -> str:
        return self.origins_pt.get(iata, iata)

    def origin_article(self, iata: str) -> str | None:
        return self.origins_article.get(iata)


class Context:
    """Everything a command needs: paths, config, secrets. Built once per CLI call."""

    def __init__(self, root: Path | None = None):
        self.root = root or project_root()

    @cached_property
    def config(self) -> AppConfig:
        with open(self.root / "config.yaml", encoding="utf-8") as f:
            return AppConfig.model_validate(yaml.safe_load(f))

    @cached_property
    def secrets(self) -> Secrets:
        return Secrets(_env_file=self.root / ".env")

    @property
    def db_path(self) -> Path:
        return self.root / "data" / "escapadinha.db"

    def search_widget(self) -> str | None:
        """`site.search_widget`, refused (ConfigError) unless it carries the website's Project
        and, when TRAVELPAYOUTS_MARKER is set, our marker: a widget copied from another account
        would earn someone else the commissions (D34)."""
        src = self.config.site.search_widget
        if src is None:
            return None
        problem = search_widget_problem(
            src, project=self.config.affiliate.project_for("website"),
            marker=self.secrets.travelpayouts_marker.strip() or None)
        if problem:
            raise ConfigError(f"site.search_widget: {problem}. Make the widget in Travelpayouts' "
                              f"constructor with the website's Project ({WIDGET_RUNBOOK})")
        return src

    @property
    def remote_store(self) -> bool:
        """True when the R2 keys are set: `run` then syncs the database through `object_store`."""
        return self.secrets.r2_configured

    @cached_property
    def object_store(self) -> "ObjectStore":
        """Raw archives, the database copy, daily backups and the run lock (D21).

        R2 (`S3ObjectStore`) when all four R2 keys are in .env, else `data/objects/` on disk.
        """
        if self.remote_store:
            from escapadinha.storage.s3 import S3ObjectStore, r2_client
            s = self.secrets
            return S3ObjectStore(r2_client(s.r2_endpoint, s.r2_access_key_id,
                                           s.r2_secret_access_key), s.r2_bucket)
        from escapadinha.storage.objects import LocalObjectStore
        return LocalObjectStore(self.local_objects_dir)

    @property
    def local_objects_dir(self) -> Path:
        return self.root / "data" / "objects"

    @property
    def sync_state_path(self) -> Path:
        """Which remote database generation the local copy came from (storage/sync.py)."""
        return self.root / "data" / "escapadinha.db.sync.json"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def photos_dir(self) -> Path:
        return self.root / "assets" / "photos"

    @property
    def assets_dir(self) -> Path:
        return self.root / "assets"

    @property
    def site_dir(self) -> Path:
        return self.root / "site"

    @property
    def guides_dir(self) -> Path:
        return self.root / "content" / "guides"

    @property
    def holidays_file(self) -> Path:
        """Portuguese public holidays (pontes, D31)."""
        return self.root / "content" / "holidays.yaml"
