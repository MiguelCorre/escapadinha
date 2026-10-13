"""Configuration: secrets from .env (pydantic-settings) + behaviour from config.yaml."""

from __future__ import annotations

import os
from functools import cached_property
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, Field, field_validator
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
    min_nights: int = Field(2, ge=1)
    max_nights: int = Field(10, ge=1)
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
    direct_only: bool = True   # only nonstop both ways (no self-transfers between airports)


class Route(BaseModel):
    origin: str
    destination: str
    city_pt: str
    price_cap_eur: float | None = None

    @property
    def key(self) -> str:
        return f"{self.origin}-{self.destination}"


def host_of(value: str) -> str:
    """'https://Example.pt/x' or 'example.pt' -> 'example.pt'."""
    value = value.strip()
    return (urlsplit(value if "//" in value else f"//{value}").hostname or "").lower()


class SiteConfig(BaseModel):
    base_url: str = "https://ondestaanocas.pages.dev"   # canonical URLs, sitemap, OG tags
    domain: str | None = None        # final domain (D17); live once base_url points at it
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
    routes: list[Route]
    origins_pt: dict[str, str] = {}
    photos: PhotosConfig = PhotosConfig()
    affiliate: AffiliateConfig = AffiliateConfig()
    site: SiteConfig = SiteConfig()

    def route(self, key: str) -> Route:
        for r in self.routes:
            if r.key == key.upper():
                return r
        raise KeyError(f"Route {key} is not in config.yaml")

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
