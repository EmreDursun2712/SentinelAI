"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routers import alerts, dashboard, detection, health, ingest, reports, response, stream
from app.core.config import get_settings
from app.core.db import dispose_engine, init_engine
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestIdMiddleware
from app.services.model_registry import get_model_registry

logger = get_logger(__name__)

API_V1_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_engine(settings.database_url)

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

    logger.info("backend.startup", env=settings.env, version=__version__)
    try:
        yield
    finally:
        await dispose_engine()
        logger.info("backend.shutdown")


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
    app.include_router(health.router, tags=["health"])

    app.include_router(alerts.router, prefix=API_V1_PREFIX, tags=["alerts"])
    app.include_router(response.router, prefix=API_V1_PREFIX, tags=["response"])
    app.include_router(reports.router, prefix=API_V1_PREFIX, tags=["reports"])
    app.include_router(ingest.router, prefix=API_V1_PREFIX, tags=["ingestion"])
    app.include_router(detection.router, prefix=API_V1_PREFIX, tags=["detection"])
    app.include_router(dashboard.router, prefix=API_V1_PREFIX, tags=["dashboard"])
    app.include_router(stream.router, prefix=API_V1_PREFIX, tags=["stream"])

    return app


app = create_app()
