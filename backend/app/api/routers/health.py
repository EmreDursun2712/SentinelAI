"""Liveness, readiness, and Prometheus metrics endpoints.

Convention follows Kubernetes probes:
  - /health   liveness: the process is up. Never checks dependencies.
  - /readyz    readiness: structured dependency status (DB, Redis, task queue,
               model). Returns 503 when a *required* dependency is down so an
               orchestrator can pull the instance from rotation.
  - /metrics   Prometheus exposition (text). Public + cheap — restrict at the
               network layer in production (see docs/DEPLOYMENT_SECURITY.md).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status

from app import __version__
from app.core.config import get_settings
from app.core.db import ping_db
from app.core.metrics import render_latest
from app.core.queue import get_task_queue
from app.core.ratelimit import get_rate_limiter
from app.services.model_registry import get_model_registry

router = APIRouter()


@router.get("/health", status_code=status.HTTP_200_OK)
async def health() -> dict[str, str]:
    """Liveness: cheap, dependency-free."""
    return {"status": "ok", "version": __version__}


async def _check_database() -> dict[str, Any]:
    return {"status": "ok" if await ping_db() else "down", "required": True}


async def _check_redis() -> dict[str, Any]:
    """Rate-limit backend reachability. Only *required* when actually Redis."""
    limiter = get_rate_limiter()
    backend = getattr(limiter, "backend", "unknown")
    required = backend == "redis"
    if backend in ("memory", "noop"):
        # No external dependency in this mode (dev fallback / disabled).
        return {"status": "skipped", "backend": backend, "required": False}
    reachable = await limiter.ping()
    return {"status": "ok" if reachable else "down", "backend": backend, "required": required}


async def _check_queue() -> dict[str, Any]:
    """Task-queue (Redis) reachability. Informational — the API works without a
    worker (jobs just wait); only 'down' when a real queue can't be reached."""
    queue = get_task_queue()
    backend = getattr(queue, "backend", "unknown")
    if backend == "null":
        return {"status": "skipped", "backend": backend, "required": False}
    reachable = await queue.ping()
    return {"status": "ok" if reachable else "down", "backend": backend, "required": False}


def _check_model() -> dict[str, Any]:
    """Model availability is informational — the app runs without one."""
    bundle = get_model_registry().get()
    if bundle is None:
        return {"status": "unavailable", "required": False}
    return {
        "status": "loaded",
        "required": False,
        "name": bundle.name,
        "version": bundle.version,
    }


@router.get("/readyz")
async def readyz(response: Response) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "database": await _check_database(),
        "redis": await _check_redis(),
        "queue": await _check_queue(),
        "model": _check_model(),
    }
    ready = all(c.get("status") == "ok" for c in checks.values() if c.get("required"))
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready else "not_ready",
        "version": __version__,
        "checks": checks,
    }


@router.get("/metrics")
async def metrics() -> Response:
    if not get_settings().metrics_enabled:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    body, content_type = render_latest()
    return Response(content=body, media_type=content_type)
