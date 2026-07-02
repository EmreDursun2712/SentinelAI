"""Host-centric views.

    GET /api/v1/hosts/{ip}/timeline — kill-chain attack timeline for one IP.

Merges the host's flows, alerts, and response actions into one time-ordered
narrative so an analyst can scan an attack top-to-bottom. Reads are VIEWER+
(mounted behind the same method-based RBAC as the rest of /api/v1).
"""

from __future__ import annotations

import ipaddress
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.core.errors import BadRequestError
from app.schemas.timeline import HostTimelineOut
from app.services import timeline_service

router = APIRouter(prefix="/hosts")


@router.get("/{ip}/timeline")
async def get_host_timeline(
    session: SessionDep,
    ip: str,
    window_hours: Annotated[int, Query(ge=1, le=720)] = 24,
) -> HostTimelineOut:
    try:
        ipaddress.ip_address(ip)
    except ValueError as exc:
        raise BadRequestError(f"Invalid IP address: {ip!r}") from exc
    data = await timeline_service.host_timeline(session, ip, window_hours=window_hours)
    return HostTimelineOut.model_validate(data)
