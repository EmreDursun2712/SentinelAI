"""Detection logic.

Pure-Python helpers (``build_feature_matrix``, ``should_create_alert``) are
unit-testable in isolation. The async functions handle the DB-bound steps:
ensuring the loaded bundle has a corresponding ``model_versions`` row, running
inference, and persisting alerts + decisions inside a single transaction.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import EventType, publish_event
from app.core.logging import get_logger
from app.core.metrics import DETECTION_ALERTS, DETECTION_EVENTS, DETECTION_RUNS
from app.models import (
    AgentDecision,
    Alert,
    ModelVersion,
    NetworkEvent,
)
from app.models.enums import AgentName, AlertStatus
from app.schemas.ingestion import FlowRecordIn
from app.services.model_registry import ModelBundle
from app.services.response_service import recommend_for_alert
from app.services.triage_service import triage_alert

logger = get_logger(__name__)


@dataclass
class Prediction:
    event_id: int | None
    predicted_label: str
    confidence: float
    class_probabilities: dict[str, float]
    threshold: float
    benign: bool
    alert_created: bool
    alert_id: int | None = None


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable without a DB).
# ---------------------------------------------------------------------------


def _to_float(value: Any) -> float:
    """Coerce a JSONB value to float, mapping nulls/inf/non-numerics to NaN."""
    if value is None:
        return float("nan")
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return result if np.isfinite(result) else float("nan")


def build_feature_matrix(
    feature_dicts: list[dict[str, Any]], feature_order: list[str]
) -> pd.DataFrame:
    """Align a list of feature dicts to the model's training column order.

    Missing keys become NaN so the in-pipeline imputer can fill them.
    """
    if not feature_dicts:
        return pd.DataFrame(columns=feature_order)
    rows = [{col: _to_float(fd.get(col)) for col in feature_order} for fd in feature_dicts]
    return pd.DataFrame(rows, columns=feature_order)


def resolve_threshold(
    label: str, default: float, class_thresholds: dict[str, float] | None
) -> float:
    """Per-class threshold if configured for ``label``, else the global default.

    Lets rare/high-impact families alert at a lower confidence than the global
    bar (better recall on the classes that matter most).
    """
    if class_thresholds:
        override = class_thresholds.get(label)
        if override is not None:
            return float(override)
    return default


def should_create_alert(label: str, confidence: float, threshold: float, benign_label: str) -> bool:
    """A non-benign label that clears the confidence threshold becomes an alert."""
    if label == benign_label:
        return False
    return confidence >= threshold


def assess_feature_coverage(
    feature_dicts: list[dict[str, Any]], feature_order: list[str]
) -> dict[str, Any]:
    """How many of the model's trained features are present in the input.

    A feature counts as *present* when it carries a finite value in at least one
    row of the batch — so a column that is entirely absent or all-NaN counts as
    missing. ``coverage`` is ``n_present / n_expected`` and is the signal the
    backend uses to warn (or fail) on train/serve feature mismatch. Empty input
    or an empty ``feature_order`` returns ``coverage=1.0`` (nothing to assess).
    """
    n_expected = len(feature_order)
    if n_expected == 0 or not feature_dicts:
        return {
            "n_expected": n_expected,
            "n_present": n_expected,
            "coverage": 1.0,
            "missing": [],
        }
    present: set[str] = set()
    for fd in feature_dicts:
        for col in feature_order:
            if col not in present and np.isfinite(_to_float(fd.get(col))):
                present.add(col)
        if len(present) == n_expected:
            break
    missing = [col for col in feature_order if col not in present]
    return {
        "n_expected": n_expected,
        "n_present": len(present),
        "coverage": round(len(present) / n_expected, 4),
        "missing": missing,
    }


def coverage_warn_threshold(bundle: ModelBundle, fallback: float) -> float:
    """The coverage below which inference should warn for ``bundle``.

    Prefers the model's declared ``expected_feature_coverage`` (set at train time)
    so the model's own expectation drives the warning; falls back to the
    operator-configured default otherwise.
    """
    declared = bundle.metadata.get("expected_feature_coverage")
    try:
        return float(declared) if declared is not None else float(fallback)
    except (TypeError, ValueError):
        return float(fallback)


def _log_coverage(
    bundle: ModelBundle, feature_dicts: list[dict[str, Any]], warn_below: float
) -> dict[str, Any]:
    """Compute coverage and emit a warning when it dips below ``warn_below``."""
    report = assess_feature_coverage(feature_dicts, bundle.feature_order)
    if report["coverage"] < warn_below:
        logger.warning(
            "detection.low_feature_coverage",
            coverage=report["coverage"],
            warn_below=warn_below,
            n_present=report["n_present"],
            n_expected=report["n_expected"],
            missing=report["missing"][:20],
            model_version=bundle.version,
        )
    return report


# ---------------------------------------------------------------------------
# Inference helpers — the bundle is required; pass an already-loaded one.
# ---------------------------------------------------------------------------


def _run_inference(
    bundle: ModelBundle, X: pd.DataFrame
) -> tuple[list[str], list[float], list[dict[str, float]]]:
    """Run ``predict_proba`` and split the output into top label / confidence / per-class probs."""
    proba = np.asarray(bundle.pipeline.predict_proba(X))
    top_labels: list[str] = []
    top_conf: list[float] = []
    all_probs: list[dict[str, float]] = []
    for row in proba:
        idx = int(np.argmax(row))
        top_labels.append(bundle.classes[idx])
        top_conf.append(float(row[idx]))
        all_probs.append({cls: float(p) for cls, p in zip(bundle.classes, row, strict=False)})
    return top_labels, top_conf, all_probs


def predict_flows(
    bundle: ModelBundle,
    flows: list[FlowRecordIn],
    *,
    threshold: float,
    benign_label: str,
    class_thresholds: dict[str, float] | None = None,
) -> list[Prediction]:
    """Run inference on raw ``FlowRecordIn`` rows. No DB writes."""
    if not flows:
        return []
    feature_dicts = [f.features for f in flows]
    _log_coverage(bundle, feature_dicts, coverage_warn_threshold(bundle, 0.5))
    X = build_feature_matrix(feature_dicts, bundle.feature_order)
    labels, confs, probs = _run_inference(bundle, X)

    predictions: list[Prediction] = []
    for label, conf, probabilities in zip(labels, confs, probs, strict=True):
        thr = resolve_threshold(label, threshold, class_thresholds)
        predictions.append(
            Prediction(
                event_id=None,
                predicted_label=label,
                confidence=conf,
                class_probabilities=probabilities,
                threshold=thr,
                benign=(label == benign_label),
                alert_created=False,
                alert_id=None,
            )
        )
    return predictions


# ---------------------------------------------------------------------------
# DB-bound helpers — synchronize the loaded bundle with the model_versions row.
# ---------------------------------------------------------------------------


def _parse_iso_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


async def ensure_model_version_row(session: AsyncSession, bundle: ModelBundle) -> int:
    """Upsert + activate the ``model_versions`` row matching ``bundle``.

    The partial unique index ``uq_model_versions_one_active`` enforces that only
    one row can have ``is_active = TRUE``, so we always deactivate everyone
    first inside a single transaction.
    """
    if bundle.db_id is not None:
        return bundle.db_id

    result = await session.execute(
        select(ModelVersion).where(
            ModelVersion.name == bundle.name,
            ModelVersion.version == bundle.version,
        )
    )
    mv = result.scalar_one_or_none()

    # Step 1 — deactivate every active row so the partial unique index stays valid.
    await session.execute(
        update(ModelVersion).where(ModelVersion.is_active.is_(True)).values(is_active=False)
    )

    # Step 2 — insert or refresh the row we care about.
    metrics = bundle.metadata.get("metrics_summary", {}) or {}
    if mv is None:
        mv = ModelVersion(
            name=bundle.name,
            version=bundle.version,
            algorithm=bundle.algorithm,
            classes=bundle.classes,
            feature_order=bundle.feature_order,
            metrics=metrics,
            artifact_path=str(bundle.artifact_dir),
            is_active=True,
            trained_at=_parse_iso_dt(bundle.metadata.get("trained_at")),
        )
        session.add(mv)
    else:
        mv.is_active = True
        mv.artifact_path = str(bundle.artifact_dir)
        mv.metrics = metrics

    await session.flush()
    bundle.db_id = mv.id
    return mv.id


# ---------------------------------------------------------------------------
# Detection on stored events — persists alerts + decisions.
# ---------------------------------------------------------------------------


async def detect_events(
    session: AsyncSession,
    bundle: ModelBundle,
    events: list[NetworkEvent],
    *,
    threshold: float,
    benign_label: str,
    auto_triage: bool = True,
    auto_respond: bool = True,
    class_thresholds: dict[str, float] | None = None,
) -> list[Prediction]:
    """Classify ``events``, persist alerts + decisions, mark events as detected.

    When ``auto_triage`` is True (default), each newly-created alert is
    immediately scored by the Triage agent inside the same transaction so
    dashboards see severity + priority on the first read.

    When ``auto_respond`` is True (default; requires ``auto_triage=True``),
    the Response agent generates recommendations right after triage and
    auto-executes the simulated ones inline. ``auto_respond`` is silently
    ignored if ``auto_triage`` is False, since response rules depend on
    severity.
    """
    if not events:
        return []

    model_version_id = await ensure_model_version_row(session, bundle)

    feature_dicts = [dict(ev.features or {}) for ev in events]
    _log_coverage(bundle, feature_dicts, coverage_warn_threshold(bundle, 0.5))
    X = build_feature_matrix(feature_dicts, bundle.feature_order)
    # predict_proba is CPU-bound and synchronous; offload to a worker thread
    # so the event loop stays responsive when classifying large batches.
    labels, confs, probs = await asyncio.to_thread(_run_inference, bundle, X)
    now = datetime.now(UTC)

    # Collected during the txn, broadcast only after a successful commit below.
    broadcast: list[tuple[str, dict[str, Any]]] = []
    # Alerts that qualify for an external notification (severity known post-triage);
    # captured as plain values so dispatch is safe after the commit expires ORM state.
    notify_candidates: list[dict[str, Any]] = []

    predictions: list[Prediction] = []
    for event, label, conf, probabilities in zip(events, labels, confs, probs, strict=True):
        benign = label == benign_label
        thr = resolve_threshold(label, threshold, class_thresholds)
        alert_now = should_create_alert(label, conf, thr, benign_label)
        event.detected_at = now

        alert_id: int | None = None
        if alert_now:
            alert = Alert(
                event_id=event.id,
                model_version_id=model_version_id,
                src_ip=event.src_ip,
                dst_ip=event.dst_ip,
                src_port=event.src_port,
                dst_port=event.dst_port,
                protocol=event.protocol,
                prediction=label,
                confidence=conf,
                status=AlertStatus.NEW,
            )
            session.add(alert)
            await session.flush()
            alert_id = alert.id

            decision = AgentDecision(
                alert_id=alert.id,
                agent=AgentName.DETECTION,
                decision={"predicted_label": label, "confidence": conf},
                reasoning={
                    "class_probabilities": probabilities,
                    "model_name": bundle.name,
                    "model_version": bundle.version,
                    "threshold": thr,
                    "benign_label": benign_label,
                },
            )
            session.add(decision)

            broadcast.append(
                (
                    EventType.ALERT_CREATED,
                    {
                        "alert_id": alert_id,
                        "src_ip": str(alert.src_ip),
                        "dst_ip": str(alert.dst_ip),
                        "prediction": label,
                        "confidence": conf,
                    },
                )
            )

            if auto_triage:
                # Same transaction — keeps NEW → TRIAGED atomic per alert.
                await triage_alert(session, alert, commit=False)
                broadcast.append(
                    (
                        EventType.ALERT_TRIAGED,
                        {
                            "alert_id": alert_id,
                            "severity": alert.severity.value if alert.severity else None,
                            "priority": alert.priority,
                        },
                    )
                )
                notify_candidates.append(
                    {
                        "alert_id": alert_id,
                        "prediction": label,
                        "severity": alert.severity.value if alert.severity else None,
                        "src_ip": str(alert.src_ip) if alert.src_ip else None,
                        "dst_ip": str(alert.dst_ip) if alert.dst_ip else None,
                        "confidence": conf,
                    }
                )
                if auto_respond:
                    # Response uses the severity set by triage.
                    await recommend_for_alert(session, alert, commit=False)
                    broadcast.append(
                        (
                            EventType.ALERT_RESPONDED,
                            {"alert_id": alert_id, "status": alert.status.value},
                        )
                    )

        predictions.append(
            Prediction(
                event_id=event.id,
                predicted_label=label,
                confidence=conf,
                class_probabilities=probabilities,
                threshold=thr,
                benign=benign,
                alert_created=alert_now,
                alert_id=alert_id,
            )
        )

    await session.commit()
    n_alerts = sum(1 for p in predictions if p.alert_created)
    DETECTION_RUNS.inc()
    DETECTION_EVENTS.inc(len(events))
    DETECTION_ALERTS.inc(n_alerts)
    logger.info(
        "detection.completed",
        n_events=len(events),
        n_alerts=n_alerts,
        model_version_id=model_version_id,
        auto_triage=auto_triage,
        auto_respond=auto_respond and auto_triage,
    )

    # Broadcast only after the commit succeeded — rolled-back work never emits.
    for event_type, payload in broadcast:
        await publish_event(event_type, payload)
    await publish_event(
        EventType.DETECTION_RUN_COMPLETED,
        {"processed": len(predictions), "alerts_created": n_alerts},
    )

    # External notifications for high-severity alerts (gated + best-effort;
    # no-op unless notifications are enabled and a channel is configured).
    from app.services.notification_service import notify_alert

    for c in notify_candidates:
        await notify_alert(**c, reason="new_alert")
    return predictions


async def fetch_undetected_events(session: AsyncSession, limit: int) -> list[NetworkEvent]:
    """Return up to ``limit`` events whose ``detected_at`` is still NULL, oldest first."""
    result = await session.execute(
        select(NetworkEvent)
        .where(NetworkEvent.detected_at.is_(None))
        .order_by(NetworkEvent.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())
