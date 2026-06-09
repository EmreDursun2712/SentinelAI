"""Detection API.

Surface:

    GET  /api/v1/detection/model            — current bundle info
    POST /api/v1/detection/predict          — inference on raw FlowRecordIn (no DB)
    POST /api/v1/detection/events/{id}      — detect a stored event; persists
    POST /api/v1/detection/batch            — detect a list of event_ids; persists
    POST /api/v1/detection/run              — process recent un-detected events
    GET  /api/v1/detection/drift/latest     — most recent drift snapshot
    GET  /api/v1/detection/drift/history    — recent drift snapshots
    POST /api/v1/detection/drift/run        — compute + persist a drift snapshot
"""

from __future__ import annotations

from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select

from app.api.deps import SessionDep, rate_limit
from app.api.pagination import set_total_count
from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError
from app.models import ModelVersion, NetworkEvent
from app.schemas.detection import (
    BatchEventRequest,
    DriftHistoryOut,
    DriftReport,
    DriftRunRequest,
    DriftSnapshotOut,
    ModelInfoOut,
    PredictionOut,
    PredictRequest,
    RunRequest,
    RunSummary,
)
from app.services import drift_service
from app.services.detection_service import (
    Prediction,
    assess_feature_coverage,
    detect_events,
    fetch_undetected_events,
    predict_flows,
)
from app.services.model_registry import ModelBundle, get_model_registry

router = APIRouter(prefix="/detection")


def _enforce_feature_coverage(bundle: ModelBundle, feature_dicts: list[dict]) -> dict:
    """Assess coverage; raise 400 when below the configured hard minimum.

    Returns the coverage report so callers can surface it. The warning path is
    handled inside the detection service; this only adds the optional hard fail
    (``SENTINEL_DETECTION_FEATURE_COVERAGE_MIN`` > 0).
    """
    report = assess_feature_coverage(feature_dicts, bundle.feature_order)
    minimum = get_settings().detection_feature_coverage_min
    if minimum > 0 and report["coverage"] < minimum:
        raise AppError(
            "Inference input is missing too many trained features.",
            details={
                "coverage": report["coverage"],
                "minimum": minimum,
                "n_present": report["n_present"],
                "n_expected": report["n_expected"],
                "missing": report["missing"][:50],
            },
        )
    return report


def _drift_report(result: drift_service.DriftRunResult) -> DriftReport:
    bundle = get_model_registry().get()
    return DriftReport(
        available=result.available,
        reason=result.reason,
        model_name=bundle.name if bundle else None,
        model_version=bundle.version if bundle else None,
        snapshot=(
            DriftSnapshotOut.model_validate(result.snapshot)
            if result.snapshot is not None
            else None
        ),
    )


def _require_bundle() -> ModelBundle:
    """Return the loaded bundle, attempting one lazy reload before giving up."""
    registry = get_model_registry()
    bundle = registry.get()
    if bundle is None:
        bundle = registry.load_from_disk(get_settings().ml_artifacts_dir)
    if bundle is None:
        raise AppError(
            "Detection model is not loaded. Train and stage artifacts under "
            "ml/artifacts/latest/ first.",
            details={"artifacts_dir": get_settings().ml_artifacts_dir},
        )
    return bundle


def _to_out(p: Prediction) -> PredictionOut:
    return PredictionOut(
        event_id=p.event_id,
        predicted_label=p.predicted_label,
        confidence=p.confidence,
        class_probabilities=p.class_probabilities,
        threshold=p.threshold,
        benign=p.benign,
        alert_created=p.alert_created,
        alert_id=p.alert_id,
    )


@router.get("/model")
async def model_info(session: SessionDep) -> ModelInfoOut:
    settings = get_settings()
    bundle = get_model_registry().get()
    if bundle is None:
        return ModelInfoOut(
            loaded=False,
            threshold=settings.detection_threshold,
            benign_label=settings.detection_benign_label,
        )

    db_id = bundle.db_id
    is_active: bool | None = None
    if db_id is not None:
        is_active = (
            await session.execute(select(ModelVersion.is_active).where(ModelVersion.id == db_id))
        ).scalar_one_or_none()
    else:
        row = (
            await session.execute(
                select(ModelVersion).where(
                    ModelVersion.name == bundle.name,
                    ModelVersion.version == bundle.version,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            db_id = row.id
            is_active = row.is_active
            bundle.db_id = row.id

    return ModelInfoOut(
        loaded=True,
        name=bundle.name,
        version=bundle.version,
        algorithm=bundle.algorithm,
        classes=bundle.classes,
        feature_order=bundle.feature_order,
        metrics_summary=bundle.metadata.get("metrics_summary", {}) or {},
        artifact_dir=str(bundle.artifact_dir),
        loaded_at=bundle.loaded_at,
        db_id=db_id,
        is_active=is_active,
        threshold=settings.detection_threshold,
        benign_label=settings.detection_benign_label,
        expected_feature_coverage=bundle.metadata.get("expected_feature_coverage"),
        calibrated=bool((bundle.metadata.get("calibration") or {}).get("calibrated", False)),
    )


@router.post(
    "/predict",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit("detection"))],
)
async def predict(request: PredictRequest) -> list[PredictionOut]:
    bundle = _require_bundle()
    settings = get_settings()
    _enforce_feature_coverage(bundle, [f.features for f in request.flows])
    predictions = predict_flows(
        bundle,
        request.flows,
        threshold=settings.detection_threshold,
        benign_label=settings.detection_benign_label,
    )
    return [_to_out(p) for p in predictions]


@router.post(
    "/events/{event_id}",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit("detection"))],
)
async def detect_one(session: SessionDep, event_id: int) -> PredictionOut:
    bundle = _require_bundle()
    settings = get_settings()

    event = await session.get(NetworkEvent, event_id)
    if event is None:
        raise NotFoundError(f"NetworkEvent {event_id} not found.")

    predictions = await detect_events(
        session,
        bundle,
        [event],
        threshold=settings.detection_threshold,
        benign_label=settings.detection_benign_label,
    )
    return _to_out(predictions[0])


@router.post(
    "/batch",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit("detection"))],
)
async def detect_many(session: SessionDep, request: BatchEventRequest) -> list[PredictionOut]:
    bundle = _require_bundle()
    settings = get_settings()

    result = await session.execute(
        select(NetworkEvent).where(NetworkEvent.id.in_(request.event_ids))
    )
    events = list(result.scalars().all())

    found_ids = {ev.id for ev in events}
    missing = [i for i in request.event_ids if i not in found_ids]
    if missing:
        raise NotFoundError(
            f"{len(missing)} NetworkEvent id(s) not found.",
            details={"missing": missing[:50]},
        )

    by_id = {ev.id: ev for ev in events}
    ordered = [by_id[i] for i in request.event_ids]

    predictions = await detect_events(
        session,
        bundle,
        ordered,
        threshold=settings.detection_threshold,
        benign_label=settings.detection_benign_label,
    )
    return [_to_out(p) for p in predictions]


@router.post(
    "/run",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit("detection"))],
)
async def run_recent(session: SessionDep, request: RunRequest) -> RunSummary:
    bundle = _require_bundle()
    settings = get_settings()

    events = await fetch_undetected_events(session, request.limit)
    if not events:
        return RunSummary(
            processed=0,
            alerts_created=0,
            benign_count=0,
            by_label={},
            model_name=bundle.name,
            model_version=bundle.version,
            feature_coverage=None,
        )

    coverage = _enforce_feature_coverage(bundle, [dict(ev.features or {}) for ev in events])
    predictions = await detect_events(
        session,
        bundle,
        events,
        threshold=settings.detection_threshold,
        benign_label=settings.detection_benign_label,
    )

    by_label = Counter(p.predicted_label for p in predictions)
    return RunSummary(
        processed=len(predictions),
        alerts_created=sum(1 for p in predictions if p.alert_created),
        benign_count=sum(1 for p in predictions if p.benign),
        by_label=dict(by_label),
        model_name=bundle.name,
        model_version=bundle.version,
        feature_coverage=coverage["coverage"],
    )


# ----- Drift monitoring (GET → VIEWER+, POST → ANALYST+ via method-based RBAC) --


@router.get("/drift/latest")
async def drift_latest(session: SessionDep) -> DriftReport:
    snapshot = await drift_service.get_latest_snapshot(session)
    if snapshot is None:
        return _drift_report(drift_service.DriftRunResult(False, reason="no_snapshot"))
    return _drift_report(drift_service.DriftRunResult(True, snapshot=snapshot))


@router.get("/drift/history")
async def drift_history(
    session: SessionDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> DriftHistoryOut:
    set_total_count(response, await drift_service.count_snapshots(session))
    snapshots = await drift_service.list_snapshots(session, limit=limit)
    return DriftHistoryOut(items=[DriftSnapshotOut.model_validate(s) for s in snapshots])


@router.post(
    "/drift/run",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit("detection"))],
)
async def drift_run(session: SessionDep, request: DriftRunRequest | None = None) -> DriftReport:
    req = request or DriftRunRequest()
    result = await drift_service.run_drift_check(session, window_hours=req.window_hours)
    return _drift_report(result)
