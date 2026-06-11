"""Admin-only operational endpoints.

    POST /api/v1/admin/reset-demo   wipe operational data (demo helper)

Everything here is ADMIN-only (on top of the router-level RBAC) and the
demo-reset route additionally 404s unless ``SENTINEL_DEMO_RESET_ENABLED=true``,
so it is invisible and inert in any non-demo deployment.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.api.deps import rate_limit, require_admin
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import NotFoundError
from app.services.demo_service import reset_demo_data

router = APIRouter(prefix="/admin")


class DemoResetResponse(BaseModel):
    """Result of a demo reset: how many rows each table gave up."""

    reset: bool
    cleared: dict[str, int]


@router.post(
    "/reset-demo",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin), Depends(rate_limit("authenticated"))],
)
async def reset_demo() -> DemoResetResponse:
    """Wipe events/alerts/actions/reports/drift so the dashboard returns to zero.

    Preserves users, sessions, and the trained model. ADMIN-only; 404 unless the
    demo-reset feature is explicitly enabled. The session is opened lazily so the
    feature gate is evaluated before any database access.
    """
    if not get_settings().demo_reset_enabled:
        raise NotFoundError("Demo reset is not enabled.")
    async with session_scope() as session:
        cleared = await reset_demo_data(session)
    return DemoResetResponse(reset=True, cleared=cleared)
