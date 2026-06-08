"""OpenTelemetry tracing — opt-in and no-op by default.

Activated only when ``SENTINEL_OTEL_ENABLED=true`` *and* the OpenTelemetry
packages are installed (``pip install -e ".[otel]"``). Otherwise ``setup_tracing``
returns immediately, so the app runs unchanged without the dependency.

When active it instruments FastAPI, the SQLAlchemy engine, and outbound httpx,
and exports spans over OTLP/gRPC to ``SENTINEL_OTEL_EXPORTER_OTLP_ENDPOINT``
(defaults to the OTLP collector default).
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_initialized = False


def setup_tracing(app: Any, settings: Settings, *, engine: Any | None = None) -> bool:
    """Wire OpenTelemetry if enabled + available. Returns True if activated.

    Safe to call once at startup. Any import/setup failure degrades to a logged
    warning and a no-op — tracing must never break the app.
    """
    global _initialized
    if _initialized or not settings.otel_enabled:
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        logger.warning(
            "otel.unavailable",
            error=str(exc),
            hint='install with: pip install -e ".[otel]"',
        )
        return False

    try:
        resource = Resource.create({SERVICE_NAME: settings.otel_service_name})
        provider = TracerProvider(resource=resource)
        endpoint = settings.otel_exporter_otlp_endpoint or None
        exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()
        if engine is not None:
            # SQLAlchemy async engine exposes the sync engine via .sync_engine.
            SQLAlchemyInstrumentor().instrument(engine=getattr(engine, "sync_engine", engine))

        _initialized = True
        logger.info(
            "otel.enabled",
            service=settings.otel_service_name,
            endpoint=endpoint or "(otlp default)",
        )
        return True
    except Exception as exc:  # never let tracing setup take down startup
        logger.warning("otel.setup_failed", error=str(exc))
        return False
