"""Client telemetry API.

    POST /api/v1/telemetry/client-error  — record a frontend ErrorBoundary error

Public (errors can happen before login) and rate-limited. It only logs the
report via structlog (no DB, no PII beyond what the client sends) and returns
204. Best-effort by design — the frontend never depends on it succeeding.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import rate_limit
from app.core.logging import get_logger
from app.schemas.telemetry import ClientErrorIn

router = APIRouter(prefix="/telemetry")
logger = get_logger(__name__)


@router.post(
    "/client-error",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("authenticated"))],
)
async def report_client_error(payload: ClientErrorIn, request: Request) -> Response:
    logger.warning(
        "client.error",
        message=payload.message[:500],
        url=payload.url,
        component_stack=(payload.component_stack or "")[:500] or None,
        request_id=getattr(request.state, "request_id", None),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
