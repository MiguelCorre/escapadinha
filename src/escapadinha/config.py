"""Configuration: secrets from .env (pydantic-settings) + behaviour from config.yaml."""

from __future__ import annotations

import os
from functools import cached_property
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def project_root() -> Path:
    """Root holding config.yaml, data/ and output/. Override with ESCAPADINHA_HOME."""
    return Path(os.environ.get("ESCAPADINHA_HOME", Path.cwd())).resolve()


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    travelpayouts_token: str = ""
    travelpayouts_marker: str = ""
    pixabay_api_key: str = ""


class Brand(BaseModel):
    name: str = "Escapadinha"
    handle: str = "@escapadinha.pt"


class CollectorConfig(BaseModel):
    source: str = "travelpayouts"
    currency: str = "eur"
    months_ahead: int = Field(3, ge=1, le=12)
    min_nights: int = Field(2, ge=1)
    max_nights: int = Field(10, ge=1)
    limit_per_request: int = Field(100, ge=1, le=1000)


class DetectorConfig(BaseModel):
    threshold: float = Field(0.30, gt=0, lt=1)
    lookback_days: int = Field(90, ge=1)
    min_samples: int = Field(20, ge=1)
    min_history_days: int = Field(7, ge=0)
    dedupe_days: int = Field(7, ge=0)
    max_deals_per_route: int = Field(1, ge=1)
    max_offer_age_days: int = Field(3, ge=0)


class Route(BaseModel):
    origin: str
    destination: str
    city_pt: str
    price_cap_eur: float | None = None

    @property
    def key(self) -> str:
        return f"{self.origin}-{self.destination}"


class PhotosConfig(BaseModel):
    queries: dict[str, str] = {}


class AppConfig(BaseModel):
    brand: Brand = Brand()
    collector: CollectorConfig = CollectorConfig()
    detector: DetectorConfig = DetectorConfig()
    routes: list[Route]
    origins_pt: dict[str, str] = {}
    photos: PhotosConfig = PhotosConfig()

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
    def guides_dir(self) -> Path:
        return self.root / "content" / "guides"
