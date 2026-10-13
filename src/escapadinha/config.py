"""Configuration: secrets from .env (pydantic-settings) + behaviour from config.yaml."""

from __future__ import annotations

import os
from functools import cached_property
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    months_ahead: int = Field(3, ge=1, le=12)
    limit_per_request: int = Field(100, ge=1, le=1000)
    market: str | None = "pt"                     # Aviasales market whose searches feed the cache
    booking_base: str = "https://www.aviasales.pt"  # booking site linked from posts (EUR, EU formats)


class DetectorConfig(BaseModel):
    threshold: float = Field(0.30, gt=0, lt=1)
    lookback_days: int = Field(90, ge=1)
    min_baseline_days: int = Field(4, ge=1)
    dedupe_days: int = Field(7, ge=0)
    max_deals_per_route: int = Field(1, ge=1)
    max_offer_age_days: int = Field(3, ge=0)


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

    @model_validator(mode="after")
    def _all_kinds(self):
        self.kinds = {**DEFAULT_KINDS, **self.kinds}
        self.overrides = {k.upper(): v for k, v in self.overrides.items()}
        self.exclusions = [e.upper() for e in self.exclusions]
        return self

    def excluded(self, origin: str, destination: str) -> bool:
        return f"{origin}-{destination}" in self.exclusions or destination in self.exclusions


def host_of(value: str) -> str:
    """'https://Example.pt/x' or 'example.pt' -> 'example.pt'."""
    value = value.strip()
    return (urlsplit(value if "//" in value else f"//{value}").hostname or "").lower()


class SiteConfig(BaseModel):
    base_url: str = "https://ondestaanocas.pages.dev"   # canonical URLs, sitemap, OG tags
    domain: str | None = None        # final domain (D19); live once base_url points at it
    legacy_hosts: list[str] = []     # old hosts: Bulk Redirect to base_url + noindex in _headers
    redirects: dict[str, str] = {}   # extra old path -> new path (301), written to _redirects
    cloudflare_project: str = "ondestaanocas"
    wrangler_version: str = "4.149.0"
    analytics_token: str | None = None   # Cloudflare Web Analytics (cookieless), optional
    recent_expired: int = 6              # expired deals listed per route page

    @field_validator("base_url")
    @classmethod
    def _https_no_trailing_slash(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("site.base_url must start with https://")
        return v.rstrip("/")

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


class AffiliateConfig(BaseModel):
    """Travelpayouts Projects ("trs"), one per traffic source, each subscribed to Aviasales.

    `projects.website` falls back to the Instagram Project, and `projects.instagram` falls
    back to the older single `project_id` key, so older config files keep working.
    """
    project_id: int | None = None              # legacy single Project (treated as Instagram)
    projects: dict[str, int | None] = {}       # {instagram: 584711, website: null}
    shorten: bool = True

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


class AppConfig(BaseModel):
    brand: Brand = Brand()
    collector: CollectorConfig = CollectorConfig()
    detector: DetectorConfig = DetectorConfig()
    routes: RoutesConfig = RoutesConfig()
    origins_pt: dict[str, str] = {}
    photos: PhotosConfig = PhotosConfig()
    affiliate: AffiliateConfig = AffiliateConfig()
    site: SiteConfig = SiteConfig()

    def origin_name(self, iata: str) -> str:
        return self.origins_pt.get(iata, iata)


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

    @property
    def object_store(self) -> "LocalObjectStore":
        """Raw archives (and later the DB sync, backups and lock). R2 comes with #4."""
        from escapadinha.storage.objects import LocalObjectStore
        return LocalObjectStore(self.root / "data" / "objects")

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
