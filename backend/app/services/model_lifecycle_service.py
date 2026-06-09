"""Model lifecycle: version registry, activate / rollback, and shadow evaluation.

The ``model_versions`` table is the source of truth for *which* model is active
(enforced by a partial unique index allowing one ``is_active`` row). This service
adds the operations around it:

* ``sync_versions_from_disk`` — discover trained artifacts on disk and upsert a
  registry row per version (never activating, never deleting).
* ``list_versions`` — list everything in the registry, newest first.
* ``activate_version`` / ``rollback`` — flip the active version (ADMIN), load the
  artifact into the in-memory registry, and append a :class:`ModelActivation`
  audit row recording who/what/why.
* ``shadow_eval`` — run a candidate model over recent events and compare it to the
  active model without changing what serves traffic; persist the comparison.

Artifacts are never deleted — activation only toggles a flag and reloads memory,
so rollback is always possible.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger
from app.models import ModelActivation, ModelShadowEval, ModelVersion, NetworkEvent
from app.services.detection_service import build_feature_matrix
from app.services.model_registry import ModelBundle, get_model_registry, load_bundle

logger = get_logger(__name__)

SHADOW_DEFAULT_WINDOW_HOURS = 24
SHADOW_MAX_EVENTS = 5_000


# ---------------------------------------------------------------------------
# Disk discovery.
# ---------------------------------------------------------------------------


def _parse_iso_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


async def sync_versions_from_disk(session: AsyncSession, artifacts_root: Path | str) -> int:
    """Upsert a ``model_versions`` row for every artifact dir under ``artifacts_root``.

    Scans immediate subdirectories that contain a ``metadata.json``; rows are
    keyed on ``(name, version)`` so the ``latest/`` mirror and its concrete
    version dir collapse to one row (the concrete path wins). Never changes
    ``is_active`` and never deletes. Returns the number of rows created.
    """
    root = Path(artifacts_root)
    if not root.is_dir():
        return 0

    created = 0
    # Sort so 'latest' is processed before 'vXXXX' dirs; the concrete version
    # directory therefore wins when setting artifact_path.
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        meta_file = child / "metadata.json"
        if not meta_file.is_file():
            continue
        try:
            import json

            meta = json.loads(meta_file.read_text())
        except Exception:
            logger.warning("model_registry.bad_metadata", path=str(meta_file))
            continue

        name = str(meta.get("name", "unknown"))
        version = str(meta.get("version", "unknown"))
        existing = (
            await session.execute(
                select(ModelVersion).where(
                    ModelVersion.name == name, ModelVersion.version == version
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            session.add(
                ModelVersion(
                    name=name,
                    version=version,
                    algorithm=str(meta.get("algorithm", "unknown")),
                    classes=list(meta.get("classes", [])),
                    feature_order=list(meta.get("feature_order", [])),
                    metrics=meta.get("metrics_summary", {}) or {},
                    artifact_path=str(child),
                    is_active=False,
                    trained_at=_parse_iso_dt(meta.get("trained_at")),
                )
            )
            created += 1
        elif child.name != "latest":
            # Keep the concrete version dir as the canonical artifact path.
            existing.artifact_path = str(child)

    await session.flush()
    return created


# ---------------------------------------------------------------------------
# Listing.
# ---------------------------------------------------------------------------


async def list_versions(session: AsyncSession) -> list[ModelVersion]:
    """All registered versions, active first then newest-trained first."""
    result = await session.execute(
        select(ModelVersion).order_by(
            desc(ModelVersion.is_active),
            desc(ModelVersion.trained_at),
            desc(ModelVersion.created_at),
        )
    )
    return list(result.scalars().all())


async def get_active_version(session: AsyncSession) -> ModelVersion | None:
    return (
        await session.execute(select(ModelVersion).where(ModelVersion.is_active.is_(True)))
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Activation / rollback.
# ---------------------------------------------------------------------------


async def _set_active(
    session: AsyncSession,
    target: ModelVersion,
    *,
    action: str,
    actor: str | None,
    reason: str | None,
    previous_id: int | None,
) -> bool:
    """Flip ``target`` to active (deactivating others), audit it, reload memory.

    Returns whether the artifact was loaded into the in-memory registry. The DB
    activation is authoritative even if the artifact can't be loaded here (e.g.
    the file isn't present in this process) — a warning is logged in that case.
    """
    await session.execute(
        update(ModelVersion).where(ModelVersion.is_active.is_(True)).values(is_active=False)
    )
    target.is_active = True
    session.add(
        ModelActivation(
            model_version_id=target.id,
            previous_version_id=previous_id,
            action=action,
            actor=actor,
            reason=reason,
        )
    )
    await session.commit()
    await session.refresh(target)

    loaded = get_model_registry().load_from_dir(target.artifact_path) is not None
    if not loaded:
        logger.warning(
            "model.activate_not_loaded",
            version=target.version,
            artifact_path=target.artifact_path,
        )
    logger.info(
        "model.activated",
        action=action,
        version=target.version,
        actor=actor,
        loaded=loaded,
    )
    return loaded


async def activate_version(
    session: AsyncSession, version_id: int, *, actor: str | None, reason: str | None = None
) -> tuple[ModelVersion, bool]:
    """Activate the version with ``version_id``. Returns ``(version, loaded)``."""
    target = await session.get(ModelVersion, version_id)
    if target is None:
        raise NotFoundError(f"Model version {version_id} not found.")
    if target.is_active:
        # Already active — still (re)load to be safe, but no audit churn.
        loaded = get_model_registry().load_from_dir(target.artifact_path) is not None
        return target, loaded

    previous = await get_active_version(session)
    loaded = await _set_active(
        session,
        target,
        action="activate",
        actor=actor,
        reason=reason,
        previous_id=previous.id if previous else None,
    )
    return target, loaded


async def rollback(
    session: AsyncSession, *, actor: str | None, reason: str | None = None
) -> tuple[ModelVersion, bool]:
    """Roll back to the version active before the most recent activation.

    Uses the activation audit's ``previous_version_id`` to find the rollback
    target. Returns ``(version, loaded)``. Raises if there is no prior version.
    """
    last = (
        await session.execute(
            select(ModelActivation).order_by(desc(ModelActivation.created_at)).limit(1)
        )
    ).scalar_one_or_none()
    if last is None or last.previous_version_id is None:
        raise AppError("No previous model version to roll back to.")

    target = await session.get(ModelVersion, last.previous_version_id)
    if target is None:
        raise AppError("The previous model version no longer exists in the registry.")

    current = await get_active_version(session)
    if current is not None and current.id == target.id:
        raise AppError("The rollback target is already the active version.")

    loaded = await _set_active(
        session,
        target,
        action="rollback",
        actor=actor,
        reason=reason,
        previous_id=current.id if current else None,
    )
    return target, loaded


async def list_activations(session: AsyncSession, *, limit: int = 50) -> list[ModelActivation]:
    result = await session.execute(
        select(ModelActivation).order_by(desc(ModelActivation.created_at)).limit(limit)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Shadow / A-B evaluation.
# ---------------------------------------------------------------------------


def _top_labels(
    bundle: ModelBundle, feature_dicts: list[dict[str, Any]]
) -> tuple[list[str], list[float]]:
    """Top predicted label + confidence per row for ``bundle`` (no DB)."""
    X = build_feature_matrix(feature_dicts, bundle.feature_order)
    proba = np.asarray(bundle.pipeline.predict_proba(X))
    labels = [bundle.classes[int(np.argmax(row))] for row in proba]
    confs = [float(np.max(row)) for row in proba]
    return labels, confs


def compare_predictions(
    candidate_labels: list[str],
    candidate_confs: list[float],
    active_labels: list[str],
    active_confs: list[float],
) -> dict[str, Any]:
    """Agreement + distribution/confidence deltas between two label streams."""
    n = len(candidate_labels)
    if n == 0:
        return {"sample_count": 0, "agreement_rate": None}
    agree = sum(1 for c, a in zip(candidate_labels, active_labels, strict=True) if c == a)

    def _dist(labels: list[str]) -> dict[str, float]:
        counts: dict[str, int] = {}
        for label in labels:
            counts[label] = counts.get(label, 0) + 1
        return {k: round(v / n, 4) for k, v in counts.items()}

    cand_mean = round(float(np.mean(candidate_confs)), 4) if candidate_confs else None
    active_mean = round(float(np.mean(active_confs)), 4) if active_confs else None
    return {
        "sample_count": n,
        "agreement_rate": round(agree / n, 4),
        "disagreements": n - agree,
        "candidate_label_distribution": _dist(candidate_labels),
        "active_label_distribution": _dist(active_labels),
        "candidate_mean_confidence": cand_mean,
        "active_mean_confidence": active_mean,
        "mean_confidence_delta": (
            round(cand_mean - active_mean, 4)
            if cand_mean is not None and active_mean is not None
            else None
        ),
    }


async def shadow_eval(
    session: AsyncSession,
    candidate_version_id: int,
    *,
    window_hours: int = SHADOW_DEFAULT_WINDOW_HOURS,
    actor: str | None = None,
) -> ModelShadowEval:
    """Run a candidate model over recent events and compare to the active model.

    Does **not** change the active model. Persists a :class:`ModelShadowEval` with
    the agreement rate + comparison metrics. Raises if the candidate version,
    its artifact, or the active model is unavailable, or there are no events.
    """
    candidate_row = await session.get(ModelVersion, candidate_version_id)
    if candidate_row is None:
        raise NotFoundError(f"Model version {candidate_version_id} not found.")

    active_bundle = get_model_registry().get()
    if active_bundle is None:
        raise AppError("No active model is loaded to compare against.")

    candidate_bundle = load_bundle(candidate_row.artifact_path)
    if candidate_bundle is None:
        raise AppError(
            "Candidate model artifact could not be loaded.",
            details={"artifact_path": candidate_row.artifact_path},
        )

    now = datetime.now(UTC)
    window_start = now - timedelta(hours=window_hours)
    events = list(
        (
            await session.execute(
                select(NetworkEvent)
                .where(NetworkEvent.created_at >= window_start)
                .order_by(desc(NetworkEvent.created_at))
                .limit(SHADOW_MAX_EVENTS)
            )
        )
        .scalars()
        .all()
    )
    if not events:
        raise AppError("No recent events to shadow-evaluate against.")

    feature_dicts = [dict(ev.features or {}) for ev in events]

    def _run() -> dict[str, Any]:
        cand_labels, cand_confs = _top_labels(candidate_bundle, feature_dicts)
        act_labels, act_confs = _top_labels(active_bundle, feature_dicts)
        return compare_predictions(cand_labels, cand_confs, act_labels, act_confs)

    metrics = await asyncio.to_thread(_run)

    active_row = await get_active_version(session)
    snapshot = ModelShadowEval(
        candidate_version_id=candidate_row.id,
        active_version_id=active_row.id if active_row else None,
        window_start=window_start,
        window_end=now,
        sample_count=metrics.get("sample_count", 0),
        agreement_rate=metrics.get("agreement_rate"),
        metrics=metrics,
        created_by=actor,
    )
    session.add(snapshot)
    await session.commit()
    await session.refresh(snapshot)
    logger.info(
        "model.shadow_eval",
        candidate=candidate_row.version,
        active=active_row.version if active_row else None,
        agreement_rate=metrics.get("agreement_rate"),
        sample_count=metrics.get("sample_count"),
    )
    return snapshot
