"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.deps import enforce_rbac, rate_limit
from app.api.routers import (
    alerts,
    auth,
    dashboard,
    detection,
    health,
    ingest,
    reports,
    response,
    stream,
)
from app.core.config import get_settings
from app.core.db import dispose_engine, get_session, init_engine
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestIdMiddleware
from app.core.ratelimit import (
    InMemoryRateLimiter,
    NoopRateLimiter,
    RedisRateLimiter,
    get_rate_limiter,
    set_rate_limiter,
)
from app.core.ws_manager import get_connection_manager
from app.services.model_registry import get_model_registry
from app.services.user_service import ensure_bootstrap_admin

logger = get_logger(__name__)

API_V1_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_engine(settings.database_url)

    # Refuse to run with the placeholder JWT secret in a production-like env —
    # signing tokens with a public default would let anyone mint admin tokens.
    if settings.is_production and settings.jwt_secret_is_default:
        raise RuntimeError(
            "SENTINEL_JWT_SECRET is still the shipped default. Set a strong "
            "secret before running in a production-like environment."
        )

    await _configure_rate_limiter(settings)

    # Best-effort model load. The backend stays serviceable without a model;
    # detection endpoints return a clear error and operators can stage an
    # artifact and call /api/v1/detection/model to recover without restart.
    try:
        bundle = get_model_registry().load_from_disk(settings.ml_artifacts_dir)
        if bundle is None:
            logger.warning(
                "model.not_loaded",
                artifacts_dir=settings.ml_artifacts_dir,
            )
    except Exception:
        logger.exception(
            "model.load_failed",
            artifacts_dir=settings.ml_artifacts_dir,
        )

    # Idempotent bootstrap admin. Only runs when BOTH env vars are set; never
    # creates a hardcoded default account. Best-effort: a transient DB error
    # here must not block startup (migrations may still be settling).
    if settings.bootstrap_admin_username and settings.bootstrap_admin_password:
        try:
            async for session in get_session():
                created = await ensure_bootstrap_admin(
                    session,
                    username=settings.bootstrap_admin_username,
                    password=settings.bootstrap_admin_password,
                )
                logger.info(
                    "auth.bootstrap_admin",
                    username=settings.bootstrap_admin_username,
                    created=created is not None,
                )
        except Exception:
            logger.exception("auth.bootstrap_admin_failed")

    # Periodic keepalive so idle WebSocket connections survive proxies and the
    # client can detect a dead link.
    heartbeat = asyncio.create_task(_heartbeat_loop())

    logger.info("backend.startup", env=settings.env, version=__version__)
    try:
        yield
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        await get_rate_limiter().aclose()
        await dispose_engine()
        logger.info("backend.shutdown")


HEARTBEAT_SECONDS = 25


async def _heartbeat_loop() -> None:
    manager = get_connection_manager()
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        await manager.broadcast({"type": "stream.heartbeat", "payload": {}})


async def _configure_rate_limiter(settings) -> None:
    """Pick the rate-limit backend from settings.

    Redis is required in production; if it is unreachable the app refuses to
    boot (fail closed). In development we warn and fall back to an in-process
    limiter so the demo still runs.
    """
    if not settings.rate_limit_enabled:
        set_rate_limiter(NoopRateLimiter())
        logger.warning("ratelimit.disabled")
        return

    if not settings.redis_url:
        if settings.is_production:
            raise RuntimeError(
                "SENTINEL_REDIS_URL is required for rate limiting in production."
            )
        set_rate_limiter(InMemoryRateLimiter())
        logger.warning("ratelimit.no_redis_url", backend="memory", env=settings.env)
        return

    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
    except Exception as exc:
        if settings.is_production:
            raise RuntimeError(
                f"Redis is required for rate limiting in production but is "
                f"unreachable at {settings.redis_url}: {exc}"
            ) from exc
        set_rate_limiter(InMemoryRateLimiter())
        logger.warning(
            "ratelimit.redis_unavailable_dev_fallback",
            backend="memory",
            error=str(exc),
        )
        return

    set_rate_limiter(RedisRateLimiter(client))
    logger.info("ratelimit.backend", backend="redis", url=settings.redis_url)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="SentinelAI",
        version=__version__,
        description="AI-driven intrusion detection and response dashboard.",
        lifespan=lifespan,
        openapi_url=f"{API_V1_PREFIX}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Order matters: request_id first so error responses can include it,
    # CORS outermost so preflight responses also carry CORS headers.
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id"],
    )

    register_error_handlers(app)

    # Health probes live at the root — orchestrators expect them there.
    # These stay public, as do /docs, /redoc, and the OpenAPI schema.
    app.include_router(health.router, tags=["health"])

    # Auth is public at /login; /me, /logout, /users self-guard internally.
    app.include_router(auth.router, prefix=API_V1_PREFIX, tags=["auth"])

    # Every functional API router is behind method-based RBAC and a general
    # per-user rate limit:
    #   RBAC: GET/HEAD/OPTIONS → VIEWER+,  mutations → ANALYST+ (ADMIN ≥ both).
    #   Rate: the "authenticated" policy (default 120/min per user). Expensive
    #   endpoints add their own stricter policy on top (see each router).
    protected = [Depends(enforce_rbac), Depends(rate_limit("authenticated"))]
    app.include_router(
        alerts.router, prefix=API_V1_PREFIX, tags=["alerts"], dependencies=protected
    )
    app.include_router(
        response.router, prefix=API_V1_PREFIX, tags=["response"], dependencies=protected
    )
    app.include_router(
        reports.router, prefix=API_V1_PREFIX, tags=["reports"], dependencies=protected
    )
    app.include_router(
        ingest.router, prefix=API_V1_PREFIX, tags=["ingestion"], dependencies=protected
    )
    app.include_router(
        detection.router, prefix=API_V1_PREFIX, tags=["detection"], dependencies=protected
    )
    app.include_router(
        dashboard.router, prefix=API_V1_PREFIX, tags=["dashboard"], dependencies=protected
    )
    # NOTE: the WebSocket /stream is an echo stub today and is secured in the
    # WebSocket-broadcasting etap (token via query param). It carries no data.
    app.include_router(stream.router, prefix=API_V1_PREFIX, tags=["stream"])

    return app


app = create_app()
