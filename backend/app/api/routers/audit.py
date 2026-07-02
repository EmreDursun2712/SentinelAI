"""Unified audit trail API (ADMIN).

    GET /api/v1/audit — merged "who did what, when" feed across auth logins,
                        model activations, analyst dispositions, and human
                        response approvals/rejections.

Reads are already VIEWER+ globally; the audit trail is accountability data, so
this router adds an explicit ADMIN guard on top.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import SessionDep, require_admin
from app.schemas.audit import AuditEntryOut, AuditListOut
from app.services import audit_service

router = APIRouter(prefix="/audit", dependencies=[Depends(require_admin)])


@router.get("")
async def list_audit(
    session: SessionDep,
    category: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    since: Annotated[datetime | None, Query()] = None,
) -> AuditListOut:
    entries, has_more = await audit_service.list_audit(
        session, categories=category, limit=limit, offset=offset, since=since
    )
    return AuditListOut(
        items=[AuditEntryOut(**e.to_dict()) for e in entries],
        has_more=has_more,
        limit=limit,
        offset=offset,
    )
