"""Liveness and readiness endpoints.

Convention follows Kubernetes probes:
  - /health  is liveness: the process is up. Never checks dependencies.
  - /readyz  is readiness: dependencies (the database) are reachable.
             Returns 503 when not ready so an orchestrator can pull the
             pod from rotation without killing it.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app import __version__
from app.core.db import ping_db

router = APIRouter()


@router.get("/health", status_code=status.HTTP_200_OK)
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/readyz")
async def readyz(response: Response) -> dict[str, str]:
    db_ok = await ping_db()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "db": "down", "version": __version__}
    return {"status": "ready", "db": "ok", "version": __version__}
