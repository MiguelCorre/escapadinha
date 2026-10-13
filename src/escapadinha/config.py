"""Configuration: secrets from .env (pydantic-settings) + behaviour from config.yaml."""

from __future__ import annotations

import os
from functools import cached_property
from pathlib import Path

import yaml
from typing import Literal

from pydantic import BaseModel, Field, model_validator
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
    handle: str = "@escapadinha.pt"


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


class SiteConfig(BaseModel):
    base_url: str = "https://ondestaanocas.pages.dev"   # canonical URLs, sitemap, OG tags
    cloudflare_project: str = "ondestaanocas"
    wrangler_version: str = "4.149.0"
    analytics_token: str | None = None   # Cloudflare Web Analytics (cookieless), optional
    recent_expired: int = 6              # expired deals listed per route page


class AffiliateConfig(BaseModel):
    project_id: int | None = None   # Travelpayouts Project ("trs") subscribed to Aviasales
    shorten: bool = True


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
