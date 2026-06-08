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
    # Short-lived access token (Bearer). Refresh tokens (below) carry the long
    # session. ``jwt_ttl_minutes`` is kept as a back-compat alias/default source.
    jwt_ttl_minutes: int = 60 * 12
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7

    # Cookie-based auth. The refresh token lives in an httpOnly Secure cookie; a
    # readable CSRF cookie pairs with an X-CSRF-Token header (double-submit) to
    # protect cookie-authenticated mutations. Production defaults are secure;
    # local non-HTTPS dev must set SENTINEL_AUTH_COOKIE_SECURE=false (the browser
    # silently drops Secure cookies over http://localhost otherwise).
    auth_cookie_secure: bool = True
    auth_cookie_samesite: str = "lax"  # lax | strict | none  (none ⇒ must be secure)
    auth_cookie_domain: str | None = None

    # Account lockout (separate from rate limiting). After N failed logins within
    # the rolling window, the account is locked for the lockout duration.
    login_max_failed_attempts: int = 5
    login_failed_window_minutes: int = 15
    login_lockout_minutes: int = 15

    # HTTP security headers (CSP, nosniff, frame-deny, Referrer/Permissions
    # policy). HSTS is added on top in production (or when forced) — only
    # meaningful behind TLS, so it is off by default in dev.
    security_headers_enabled: bool = True
    security_hsts_enabled: bool = False

    # Observability. Prometheus /metrics is always on (cheap, public — restrict
    # at the network in prod). OpenTelemetry tracing is opt-in + no-op unless
    # both enabled and the otel extra is installed (see app.core.tracing).
    metrics_enabled: bool = True
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "sentinelai-backend"

    # Bootstrap admin — created once on startup if both are set. If either is
    # missing, NO default user is created (no hardcoded credentials ever ship).
    # The password must satisfy the password policy (see app.core.password_policy).
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: str | None = None

    cors_origins: str = "http://localhost:5173"

    ml_artifacts_dir: str = "/app/ml_artifacts"

    # Rate limiting. Redis-backed in production; falls back to an in-process
    # limiter only in development if Redis is unreachable (see lifespan).
    redis_url: str | None = None
    rate_limit_enabled: bool = True
    # Compact "<count>/<unit>" specs; unit ∈ second|minute|hour. Env-overridable.
    rate_limit_login: str = "5/minute"  # per IP+username
    rate_limit_authenticated: str = "120/minute"  # general per-user fallback
    rate_limit_ingest: str = "10/minute"  # per user
    rate_limit_detection: str = "5/minute"  # per user
    rate_limit_report: str = "20/minute"  # per user
    rate_limit_response: str = "60/minute"  # per user
    rate_limit_tasks: str = "30/minute"  # per user — guards background-job spam

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

    # Agent runtime automation. Triage + Response agents always run (idempotent:
    # they no-op when the synchronous detection pipeline already handled the
    # alert). Investigation + Reporting stay analyst-triggered unless enabled.
    investigation_auto: bool = False
    reporting_auto: bool = False

    # Async task queue (arq, Redis-backed). The worker calls the same services.
    # When no Redis is configured, enqueue is a no-op (tasks stay PENDING) — dev
    # without a worker still serves the synchronous endpoints. See TASK_QUEUE.md.
    task_queue_name: str = "sentinelai:queue"
    retention_days: int = 90  # housekeeping cutoff for terminal tasks + drift snapshots
    ml_retrain_enabled: bool = False  # gate the (heavy) ML retrain task endpoint

    # Data retention. Each is an age cutoff in days; **0 disables** that policy
    # (safe default — nothing is deleted/archived unless explicitly configured).
    # Events are hard-deleted (alerts.event_id is SET NULL); alerts + reports are
    # soft-deleted (archived_at) to preserve the audit trail. See DATA_RETENTION.md.
    retention_events_days: int = 0
    retention_alerts_days: int = 0
    retention_reports_days: int = 0

    # Reporting
    reports_dir: str = "data/reports"

    # Response execution. Default is fully simulated; LAB (real, allowlisted)
    # effects are impossible unless ALL of: enabled=true, mode=lab, a lab
    # executor, and allowed CIDRs. See ``lab_response_active``.
    response_mode: str = "simulated"  # simulated | lab
    response_enabled: bool = False
    response_executor: str = "simulated"  # simulated | mock_lab | nftables_lab
    response_allowed_cidrs: str = ""  # required for LAB; comma-separated
    response_max_block_minutes: int = 60
    response_require_approval: bool = True

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

    @property
    def hsts_active(self) -> bool:
        """Send HSTS in production, or when explicitly forced (TLS in front)."""
        return self.is_production or self.security_hsts_enabled

    @property
    def response_allowed_cidrs_list(self) -> list[str]:
        return [c.strip() for c in self.response_allowed_cidrs.split(",") if c.strip()]

    @property
    def lab_response_active(self) -> bool:
        """True only when real lab response is fully + safely configured.

        Every condition must hold, so the default config can never produce a
        real effect: must be enabled, mode=lab, a non-simulated lab executor,
        and at least one allowed CIDR. Anything missing → simulated only.
        """
        return (
            self.response_enabled
            and self.response_mode.strip().lower() == "lab"
            and self.response_executor.strip().lower() in {"mock_lab", "nftables_lab"}
            and bool(self.response_allowed_cidrs_list)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
