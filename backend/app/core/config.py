"""Typed application settings, sourced from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENTINEL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "development"
    log_level: str = "info"

    database_url: str = Field(
        default="postgresql+psycopg://sentinelai:sentinelai@localhost:5432/sentinelai"
    )

    api_key: str = "dev-api-key-change-me"
    jwt_secret: str = "dev-jwt-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 60 * 12

    cors_origins: str = "http://localhost:5173"

    ml_artifacts_dir: str = "/app/ml_artifacts"

    # Ingestion
    ingest_data_dir: str = "data"
    ingest_max_upload_bytes: int = 20 * 1024 * 1024  # 20 MiB

    # Detection
    detection_threshold: float = 0.5
    detection_benign_label: str = "BENIGN"

    # Reporting
    reports_dir: str = "data/reports"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
