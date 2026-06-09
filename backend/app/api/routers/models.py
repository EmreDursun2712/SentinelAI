"""Model registry / lifecycle API.

    GET  /api/v1/models                      — list registered versions (VIEWER+)
    GET  /api/v1/models/activations          — activation audit history (VIEWER+)
    GET  /api/v1/models/shadow               — recent shadow evaluations (VIEWER+)
    POST /api/v1/models/{id}/activate        — activate a version (ADMIN)
    POST /api/v1/models/rollback             — roll back to the previous active (ADMIN)
    POST /api/v1/models/shadow               — shadow-eval a candidate (ANALYST+)

Listing lazily syncs the registry from artifacts on disk so freshly-trained
versions appear without a restart. Activate/rollback are ADMIN-only and append an
audit row; artifacts are never deleted, so rollback is always possible. Shadow
evaluation runs a candidate over recent events without changing what serves
traffic. The router is mounted behind method-based RBAC (reads VIEWER+, writes
ANALYST+); activate/rollback add an explicit ADMIN guard.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import ActiveUser, SessionDep, rate_limit, require_admin
from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.model_registry import (
    ActivateRequest,
    ActivationResult,
    ModelActivationListOut,
    ModelActivationOut,
    ModelVersionListOut,
    ModelVersionOut,
    RollbackRequest,
    ShadowEvalOut,
    ShadowEvalRequest,
)
from app.services import model_lifecycle_service as lifecycle

router = APIRouter(prefix="/models")
logger = get_logger(__name__)

_detection_limit = Depends(rate_limit("detection"))


@router.get("")
async def list_models(session: SessionDep) -> ModelVersionListOut:
    # Best-effort discovery of on-disk artifacts so new versions show up without
    # a restart; a scan failure never blocks listing what's already registered.
    try:
        await lifecycle.sync_versions_from_disk(session, get_settings().ml_artifacts_dir)
    except Exception:
        logger.warning("model_registry.sync_failed", exc_info=True)

    versions = await lifecycle.list_versions(session)
    active_id = next((v.id for v in versions if v.is_active), None)
    return ModelVersionListOut(
        items=[ModelVersionOut.model_validate(v) for v in versions],
        active_version_id=active_id,
    )


@router.get("/activations")
async def list_activations(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> ModelActivationListOut:
    rows = await lifecycle.list_activations(session, limit=limit)
    return ModelActivationListOut(items=[ModelActivationOut.model_validate(r) for r in rows])


@router.post(
    "/{version_id}/activate",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
)
async def activate_model(
    session: SessionDep,
    version_id: int,
    user: ActiveUser,
    request: ActivateRequest | None = None,
) -> ActivationResult:
    req = request or ActivateRequest()
    version, loaded = await lifecycle.activate_version(
        session, version_id, actor=user.username, reason=req.reason
    )
    return ActivationResult(
        action="activate", loaded=loaded, version=ModelVersionOut.model_validate(version)
    )


@router.post(
    "/rollback",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
)
async def rollback_model(
    session: SessionDep, user: ActiveUser, request: RollbackRequest | None = None
) -> ActivationResult:
    req = request or RollbackRequest()
    version, loaded = await lifecycle.rollback(session, actor=user.username, reason=req.reason)
    return ActivationResult(
        action="rollback", loaded=loaded, version=ModelVersionOut.model_validate(version)
    )


@router.get("/shadow")
async def list_shadow_evals(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 20
) -> list[ShadowEvalOut]:
    from sqlalchemy import desc, select

    from app.models import ModelShadowEval

    rows = list(
        (
            await session.execute(
                select(ModelShadowEval).order_by(desc(ModelShadowEval.created_at)).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [ShadowEvalOut.model_validate(r) for r in rows]


@router.post("/shadow", status_code=status.HTTP_200_OK, dependencies=[_detection_limit])
async def run_shadow_eval(
    session: SessionDep, request: ShadowEvalRequest, user: ActiveUser
) -> ShadowEvalOut:
    snapshot = await lifecycle.shadow_eval(
        session,
        request.candidate_version_id,
        window_hours=request.window_hours,
        actor=user.username,
    )
    return ShadowEvalOut.model_validate(snapshot)
