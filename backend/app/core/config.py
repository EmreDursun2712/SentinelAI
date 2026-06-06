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

    # Bootstrap admin — created once on startup if both are set. If either is
    # missing, NO default user is created (no hardcoded credentials ever ship).
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: str | None = None

    cors_origins: str = "http://localhost:5173"

    ml_artifacts_dir: str = "/app/ml_artifacts"

    # Rate limiting. Redis-backed in production; falls back to an in-process
    # limiter only in development if Redis is unreachable (see lifespan).
    redis_url: str | None = None
    rate_limit_enabled: bool = True
    # Compact "<count>/<unit>" specs; unit ∈ second|minute|hour. Env-overridable.
    rate_limit_login: str = "5/minute"          # per IP+username
    rate_limit_authenticated: str = "120/minute"  # general per-user fallback
    rate_limit_ingest: str = "10/minute"        # per user
    rate_limit_detection: str = "5/minute"      # per user
    rate_limit_report: str = "20/minute"        # per user
    rate_limit_response: str = "60/minute"      # per user

    # Ingestion
    ingest_data_dir: str = "data"
    ingest_max_upload_bytes: int = 20 * 1024 * 1024  # 20 MiB

    # Detection
    detection_threshold: float = 0.5
    detection_benign_label: str = "BENIGN"
    # When true, the batch ingest endpoint runs detection on freshly-queued
    # events right after insert (bounded). Off by default — opt-in for demos.
    detection_auto_run_on_ingest: bool = False
    detection_auto_run_limit: int = 1000

    # Live-sensor status: how recent ingest activity must be to count as "live".
    sensor_live_window_seconds: int = 120

    # Reporting
    reports_dir: str = "data/reports"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"production", "prod", "staging"}

    @property
    def jwt_secret_is_default(self) -> bool:
        """True if the JWT secret is still the shipped placeholder."""
        return self.jwt_secret == "dev-jwt-secret-change-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()
