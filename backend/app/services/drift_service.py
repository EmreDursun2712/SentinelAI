"""Model drift monitoring.

Compares recent network-flow features and model predictions against the training
baseline embedded in the active model artifact (``metadata["baseline"]``), using
a Population Stability Index (PSI) per feature plus a PSI over the prediction
mix. The pure helpers (``psi``, ``bucket_props``, ``compute_feature_drift`` …)
are deterministic and unit-tested; the async ``run_drift_check`` wraps them with
the DB I/O and persists a :class:`ModelDriftSnapshot`.

Status thresholds (standard PSI bands):

    OK     score < 0.10
    WATCH  0.10 ≤ score < 0.25
    DRIFT  score ≥ 0.25

If the active artifact has no baseline (older models) or there's no recent data,
drift is reported **unavailable** and nothing is persisted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import DRIFT_RUNS, DRIFT_SCORE
from app.models import Alert, ModelDriftSnapshot, ModelVersion, NetworkEvent
from app.models.enums import DriftStatus
from app.services.model_registry import ModelBundle, get_model_registry

logger = get_logger(__name__)

DEFAULT_WINDOW_HOURS = 24
MAX_EVENTS = 20_000
MIN_FEATURE_SAMPLES = 10  # don't compute PSI on a handful of points
PSI_EPS = 1e-6

WATCH_THRESHOLD = 0.10
DRIFT_THRESHOLD = 0.25


# ---------------------------------------------------------------------------
# Pure helpers (deterministic, unit-testable).
# ---------------------------------------------------------------------------


def _to_float(value: Any) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return f


def psi(expected: list[float], actual: list[float], *, eps: float = PSI_EPS) -> float:
    """Population Stability Index between two same-length proportion vectors."""
    total = 0.0
    for e, a in zip(expected, actual, strict=True):
        e = max(e, eps)
        a = max(a, eps)
        total += (a - e) * math.log(a / e)
    return total


def bucket_props(values: list[float], edges: list[float]) -> list[float]:
    """Proportion of ``values`` per bin defined by ``edges`` (k+1 edges → k bins).

    Mirrors ``ml.baseline.bin_props`` exactly so train-time and runtime bucketing
    agree: extremes are clipped into the end bins.
    """
    arr = np.asarray(values, dtype=float)
    edge_arr = np.asarray(edges, dtype=float)
    k = len(edge_arr) - 1
    if k < 1:
        return []
    clean = arr[np.isfinite(arr)]
    if clean.size == 0:
        return [0.0] * k
    idx = np.digitize(clean, edge_arr[1:-1], right=False)
    counts = np.bincount(idx, minlength=k).astype(float)
    total = counts.sum()
    return (counts / total).tolist() if total else [0.0] * k


def compute_feature_drift(
    baseline_features: dict[str, Any],
    recent_values: dict[str, list[float]],
    *,
    min_samples: int = MIN_FEATURE_SAMPLES,
) -> dict[str, dict[str, Any]]:
    """PSI per feature for features present in both the baseline and recent data."""
    out: dict[str, dict[str, Any]] = {}
    for feature, spec in baseline_features.items():
        values = recent_values.get(feature)
        if not values or len(values) < min_samples:
            continue
        edges = spec.get("bin_edges")
        base_props = spec.get("bin_props")
        if not edges or not base_props:
            continue
        recent_props = bucket_props(values, edges)
        out[feature] = {
            "psi": round(psi(base_props, recent_props), 4),
            "sample_count": len(values),
        }
    return out


def distribution_psi(
    baseline_dist: dict[str, float], recent_counts: dict[str, int]
) -> tuple[float, dict[str, float]]:
    """PSI between a baseline proportion map and recent category counts.

    Returns ``(psi, recent_proportions)`` over the union of categories.
    """
    total = sum(recent_counts.values())
    recent_props = {k: v / total for k, v in recent_counts.items()} if total else {}
    categories = set(baseline_dist) | set(recent_props)
    expected = [baseline_dist.get(c, 0.0) for c in categories]
    actual = [recent_props.get(c, 0.0) for c in categories]
    score = psi(expected, actual) if categories else 0.0
    return round(score, 4), {k: round(v, 4) for k, v in recent_props.items()}


def confidence_stats(confidences: list[float]) -> dict[str, float | None]:
    if not confidences:
        return {"count": 0, "mean": None, "min": None, "max": None, "p95": None}
    arr = np.asarray(confidences, dtype=float)
    return {
        "count": int(arr.size),
        "mean": round(float(arr.mean()), 4),
        "min": round(float(arr.min()), 4),
        "max": round(float(arr.max()), 4),
        "p95": round(float(np.percentile(arr, 95)), 4),
    }


def status_for_score(score: float) -> DriftStatus:
    if score >= DRIFT_THRESHOLD:
        return DriftStatus.DRIFT
    if score >= WATCH_THRESHOLD:
        return DriftStatus.WATCH
    return DriftStatus.OK


def aggregate_drift_score(
    feature_drift: dict[str, dict[str, Any]], prediction_psi: float | None
) -> float | None:
    """Mean PSI across all computed components (features + prediction mix)."""
    scores = [d["psi"] for d in feature_drift.values()]
    if prediction_psi is not None:
        scores.append(prediction_psi)
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


# ---------------------------------------------------------------------------
# Run result.
# ---------------------------------------------------------------------------


@dataclass
class DriftRunResult:
    available: bool
    reason: str | None = None
    snapshot: ModelDriftSnapshot | None = None


# ---------------------------------------------------------------------------
# DB-bound orchestration.
# ---------------------------------------------------------------------------


async def _resolve_model_version_id(session: AsyncSession, bundle: ModelBundle) -> int | None:
    """Look up the persisted model_versions id by name+version.

    We deliberately re-query rather than trust ``bundle.db_id``: that cache can
    be set by a detection transaction that later rolled back, leaving a stale id
    that would violate the FK on insert. A NULL is fine — the snapshot just
    won't be linked to a model row.
    """
    return (
        await session.execute(
            select(ModelVersion.id).where(
                ModelVersion.name == bundle.name,
                ModelVersion.version == bundle.version,
            )
        )
    ).scalar_one_or_none()


async def run_drift_check(
    session: AsyncSession,
    *,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    commit: bool = True,
) -> DriftRunResult:
    """Compute drift over the last ``window_hours`` and persist a snapshot.

    Returns ``available=False`` (persisting nothing) when there is no loaded
    model, no baseline in the artifact, or no recent data to analyze.
    """
    bundle = get_model_registry().get()
    if bundle is None:
        return DriftRunResult(False, reason="model_not_loaded")

    baseline = bundle.metadata.get("baseline") or {}
    baseline_features = baseline.get("features") or {}
    if not baseline_features:
        return DriftRunResult(False, reason="baseline_unavailable")

    now = datetime.now(UTC)
    window_start = now - timedelta(hours=window_hours)

    # Recent flows → per-feature value lists (only baseline features).
    events = list(
        (
            await session.execute(
                select(NetworkEvent)
                .where(NetworkEvent.created_at >= window_start)
                .order_by(desc(NetworkEvent.created_at))
                .limit(MAX_EVENTS)
            )
        )
        .scalars()
        .all()
    )
    recent_values: dict[str, list[float]] = {f: [] for f in baseline_features}
    for ev in events:
        features = ev.features or {}
        for fname in baseline_features:
            val = _to_float(features.get(fname))
            if math.isfinite(val):
                recent_values[fname].append(val)

    # Recent alerts → prediction mix + confidence.
    alerts = list(
        (await session.execute(select(Alert).where(Alert.created_at >= window_start)))
        .scalars()
        .all()
    )

    if not events and not alerts:
        return DriftRunResult(False, reason="no_recent_data")

    feature_drift = compute_feature_drift(baseline_features, recent_values)

    # Prediction-mix PSI vs the baseline's non-benign class distribution.
    settings = get_settings()
    benign = settings.detection_benign_label
    base_classes = baseline.get("class_distribution") or {}
    base_nonbenign = {k: v for k, v in base_classes.items() if k != benign}
    nb_total = sum(base_nonbenign.values())
    base_nonbenign = {k: v / nb_total for k, v in base_nonbenign.items()} if nb_total else {}

    pred_counts: dict[str, int] = {}
    confidences: list[float] = []
    for a in alerts:
        if a.prediction:
            pred_counts[a.prediction] = pred_counts.get(a.prediction, 0) + 1
        if a.confidence is not None:
            confidences.append(float(a.confidence))

    prediction_psi: float | None = None
    recent_pred_props: dict[str, float] = {}
    if base_nonbenign and pred_counts:
        prediction_psi, recent_pred_props = distribution_psi(base_nonbenign, pred_counts)

    drift_score = aggregate_drift_score(feature_drift, prediction_psi)
    if drift_score is None:
        return DriftRunResult(False, reason="insufficient_data")

    status = status_for_score(drift_score)
    model_version_id = await _resolve_model_version_id(session, bundle)

    snapshot = ModelDriftSnapshot(
        model_version_id=model_version_id,
        window_start=window_start,
        window_end=now,
        sample_count=len(events),
        feature_drift=feature_drift,
        prediction_distribution={
            "recent": recent_pred_props,
            "baseline_nonbenign": {k: round(v, 4) for k, v in base_nonbenign.items()},
            "psi": prediction_psi,
            "alert_count": len(alerts),
        },
        confidence_stats=confidence_stats(confidences),
        drift_score=drift_score,
        status=status,
    )
    session.add(snapshot)
    if commit:
        await session.commit()
        await session.refresh(snapshot)

    DRIFT_SCORE.set(drift_score)
    DRIFT_RUNS.labels(status=status.value).inc()

    logger.info(
        "drift.checked",
        drift_score=drift_score,
        status=status.value,
        n_events=len(events),
        n_alerts=len(alerts),
        n_features=len(feature_drift),
    )
    return DriftRunResult(True, snapshot=snapshot)


async def get_latest_snapshot(session: AsyncSession) -> ModelDriftSnapshot | None:
    return (
        await session.execute(
            select(ModelDriftSnapshot).order_by(desc(ModelDriftSnapshot.created_at)).limit(1)
        )
    ).scalar_one_or_none()


async def count_snapshots(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count(ModelDriftSnapshot.id)))).scalar_one() or 0)


async def list_snapshots(session: AsyncSession, *, limit: int = 20) -> list[ModelDriftSnapshot]:
    return list(
        (
            await session.execute(
                select(ModelDriftSnapshot)
                .order_by(desc(ModelDriftSnapshot.created_at))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
