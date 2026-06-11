"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.agents.runtime import register_agents
from app.api.deps import enforce_rbac, rate_limit
from app.api.routers import (
    admin,
    alerts,
    auth,
    dashboard,
    detection,
    health,
    ingest,
    models,
    reports,
    response,
    stream,
    tasks,
    telemetry,
)
from app.core.broadcast import (
    LocalBroadcaster,
    RedisBroadcaster,
    get_broadcaster,
    set_broadcaster,
)
from app.core.config import get_settings
from app.core.csrf import CsrfMiddleware
from app.core.db import dispose_engine, get_engine, get_session, init_engine
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.metrics import MetricsMiddleware
from app.core.middleware import RequestIdMiddleware
from app.core.queue import (
    ArqTaskQueue,
    NullTaskQueue,
    arq_redis_settings,
    get_task_queue,
    set_task_queue,
)
from app.core.ratelimit import (
    InMemoryRateLimiter,
    NoopRateLimiter,
    RedisRateLimiter,
    get_rate_limiter,
    set_rate_limiter,
)
from app.core.security_headers import SecurityHeadersMiddleware, validate_cors_origins
from app.core.tracing import setup_tracing
from app.core.ws_manager import get_connection_manager
from app.services.model_registry import get_model_registry
from app.services.user_service import ensure_bootstrap_admin

logger = get_logger(__name__)

API_V1_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_engine(settings.database_url)

    # OpenTelemetry tracing (opt-in + no-op unless configured). After init_engine
    # so the SQLAlchemy engine can be instrumented.
    setup_tracing(app, settings, engine=get_engine())

    # Refuse to run with the placeholder JWT secret in a production-like env —
    # signing tokens with a public default would let anyone mint admin tokens.
    if settings.is_production and settings.jwt_secret_is_default:
        raise RuntimeError(
            "SENTINEL_JWT_SECRET is still the shipped default. Set a strong "
            "secret before running in a production-like environment."
        )

    # Cookies must be Secure in production; SameSite=None requires Secure anywhere.
    if settings.is_production and not settings.auth_cookie_secure:
        raise RuntimeError(
            "SENTINEL_AUTH_COOKIE_SECURE must be true in a production-like environment."
        )
    if settings.auth_cookie_samesite.strip().lower() == "none" and not settings.auth_cookie_secure:
        raise RuntimeError("SameSite=None auth cookies require SENTINEL_AUTH_COOKIE_SECURE=true.")

    await _configure_rate_limiter(settings)
    await _configure_broadcaster(settings)
    await _configure_task_queue(settings)

    # Register the agent runtime on the in-process event bus (idempotent,
    # state-guarded handlers; see app.agents.runtime).
    register_agents()

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
        await get_broadcaster().aclose()
        await get_task_queue().aclose()
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
            raise RuntimeError("SENTINEL_REDIS_URL is required for rate limiting in production.")
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


async def _configure_broadcaster(settings) -> None:
    """Pick the WebSocket broadcaster: Redis pub/sub (cross-worker) or local.

    Mirrors the rate limiter: production requires Redis (fails closed); dev falls
    back to a single-process local broadcast with a warning.
    """
    if not settings.redis_url:
        if settings.is_production:
            raise RuntimeError(
                "SENTINEL_REDIS_URL is required for WebSocket broadcast in production."
            )
        set_broadcaster(LocalBroadcaster())
        logger.warning("broadcast.no_redis_url", backend="local", env=settings.env)
        return

    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
    except Exception as exc:
        if settings.is_production:
            raise RuntimeError(
                f"Redis is required for WebSocket broadcast in production but is "
                f"unreachable at {settings.redis_url}: {exc}"
            ) from exc
        set_broadcaster(LocalBroadcaster())
        logger.warning("broadcast.redis_unavailable_dev_fallback", backend="local", error=str(exc))
        return

    broadcaster = RedisBroadcaster(client)
    await broadcaster.start()
    set_broadcaster(broadcaster)
    logger.info("broadcast.backend", backend="redis", channel="sentinelai:events")


async def _configure_task_queue(settings) -> None:
    """Connect the API to the arq task queue (Redis). Without Redis, enqueue is a
    no-op (tasks stay PENDING) so dev without a worker still serves sync endpoints.
    """
    if not settings.redis_url:
        set_task_queue(NullTaskQueue())
        logger.warning("queue.no_redis_url", backend="null", env=settings.env)
        return
    try:
        from arq import create_pool

        pool = await create_pool(arq_redis_settings(settings.redis_url))
    except Exception as exc:
        if settings.is_production:
            raise RuntimeError(
                f"Redis is required for the task queue in production but is "
                f"unreachable at {settings.redis_url}: {exc}"
            ) from exc
        set_task_queue(NullTaskQueue())
        logger.warning("queue.redis_unavailable_dev_fallback", backend="null", error=str(exc))
        return

    set_task_queue(ArqTaskQueue(pool, settings.task_queue_name))
    logger.info("queue.backend", backend="arq", queue=settings.task_queue_name)


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

    # Fail closed on unsafe CORS (e.g. "*" with credentials): fatal in prod,
    # a loud warning in dev.
    cors_issues = validate_cors_origins(settings.cors_origins_list, allow_credentials=True)
    if cors_issues:
        message = "Unsafe CORS configuration: " + "; ".join(cors_issues)
        if settings.is_production:
            raise RuntimeError(message)
        logger.warning("cors.unsafe_config", issues=cors_issues)

    # Order matters (last added = outermost). Resulting request flow:
    #   SecurityHeaders → CORS → RequestId → CSRF → Metrics → app
    # SecurityHeaders outermost so EVERY response (incl. CORS preflight, CSRF
    # rejections, errors) is stamped; CORS next so preflight carries CORS
    # headers; RequestId so a request_id is bound before CSRF can reject; CSRF
    # guards cookie-authenticated mutations; Metrics innermost so the matched
    # route template is resolved when recording request count + latency.
    if settings.metrics_enabled:
        app.add_middleware(MetricsMiddleware)
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id", "x-total-count"],
    )
    if settings.security_headers_enabled:
        app.add_middleware(SecurityHeadersMiddleware, hsts=settings.hsts_active)

    register_error_handlers(app)

    # Health probes live at the root — orchestrators expect them there.
    # These stay public, as do /docs, /redoc, and the OpenAPI schema.
    app.include_router(health.router, tags=["health"])

    # Auth is public at /login; /me, /logout, /users self-guard internally.
    app.include_router(auth.router, prefix=API_V1_PREFIX, tags=["auth"])

    # Client telemetry is public (errors can occur pre-login) + self-rate-limited.
    app.include_router(telemetry.router, prefix=API_V1_PREFIX, tags=["telemetry"])

    # Every functional API router is behind method-based RBAC and a general
    # per-user rate limit:
    #   RBAC: GET/HEAD/OPTIONS → VIEWER+,  mutations → ANALYST+ (ADMIN ≥ both).
    #   Rate: the "authenticated" policy (default 120/min per user). Expensive
    #   endpoints add their own stricter policy on top (see each router).
    protected = [Depends(enforce_rbac), Depends(rate_limit("authenticated"))]
    app.include_router(alerts.router, prefix=API_V1_PREFIX, tags=["alerts"], dependencies=protected)
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
    app.include_router(models.router, prefix=API_V1_PREFIX, tags=["models"], dependencies=protected)
    app.include_router(tasks.router, prefix=API_V1_PREFIX, tags=["tasks"], dependencies=protected)
    app.include_router(admin.router, prefix=API_V1_PREFIX, tags=["admin"], dependencies=protected)
    # NOTE: the WebSocket /stream is an echo stub today and is secured in the
    # WebSocket-broadcasting etap (token via query param). It carries no data.
    app.include_router(stream.router, prefix=API_V1_PREFIX, tags=["stream"])

    return app


app = create_app()
