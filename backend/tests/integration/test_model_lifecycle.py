"""Model lifecycle integration tests against real Postgres.

Exercises the registry/activation tables and the services that drive them:
disk discovery, activate/rollback with an audit trail, drift snapshots carrying
the analyst-feedback proxy, and shadow evaluation persisting comparison metrics.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, ModelVersion, NetworkEvent
from app.models.enums import AlertDisposition, AlertStatus
from app.services import drift_service
from app.services import model_lifecycle_service as lifecycle
from app.services.model_registry import ModelBundle, get_model_registry


def _hand_baseline() -> dict:
    """A minimal drift baseline over features 'a'/'b' (avoids importing ml)."""
    feature = {
        "mean": 35.0,
        "std": 20.0,
        "bin_edges": [0.0, 20.0, 40.0, 60.0, 80.0],
        "bin_props": [0.25, 0.25, 0.25, 0.25],
    }
    return {
        "version": 1,
        "sample_count": 40,
        "n_bins": 4,
        "class_distribution": {"BENIGN": 0.5, "DDoS": 0.5},
        "features": {"a": feature, "b": feature},
    }


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _clear_registry():
    yield
    get_model_registry().clear()


def _stage_artifact(root: Path, name: str, version: str, *, pipeline: object | None = None) -> Path:
    """Write a minimal artifact dir (model.joblib + metadata.json)."""
    d = root / version
    d.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline if pipeline is not None else {"dummy": True}, d / "model.joblib")
    (d / "metadata.json").write_text(
        json.dumps(
            {
                "name": name,
                "version": version,
                "algorithm": "random_forest",
                "classes": ["BENIGN", "DDoS"],
                "feature_order": ["a", "b"],
                "metrics_summary": {"test_f1_macro": 0.9},
                "trained_at": "2026-01-01T00:00:00+00:00",
            }
        )
    )
    return d


def _fit_pipeline(seed: int) -> Pipeline:
    rng = np.random.default_rng(seed)
    n = 60
    benign = pd.DataFrame({"a": rng.normal(10, 1, n), "b": rng.normal(5, 1, n)})
    ddos = pd.DataFrame({"a": rng.normal(100, 1, n), "b": rng.normal(50, 1, n)})
    X = pd.concat([benign, ddos], ignore_index=True)
    y = ["BENIGN"] * n + ["DDoS"] * n
    pipe = Pipeline(
        [
            ("imputer", SimpleImputer()),
            ("clf", RandomForestClassifier(n_estimators=8, random_state=seed)),
        ]
    )
    pipe.fit(X, y)
    return pipe


# ----- disk discovery ------------------------------------------------------


async def test_sync_versions_from_disk_upserts(db_session: AsyncSession, tmp_path: Path) -> None:
    _stage_artifact(tmp_path, "sentinelai-detection", "v1")
    _stage_artifact(tmp_path, "sentinelai-detection", "v2")

    created = await lifecycle.sync_versions_from_disk(db_session, tmp_path)
    assert created == 2

    # Idempotent: a second sync creates nothing new.
    assert await lifecycle.sync_versions_from_disk(db_session, tmp_path) == 0
    versions = await lifecycle.list_versions(db_session)
    assert {v.version for v in versions} >= {"v1", "v2"}


# ----- activate / rollback + audit -----------------------------------------


async def test_activate_rollback_audit_trail(db_session: AsyncSession, tmp_path: Path) -> None:
    d1 = _stage_artifact(tmp_path, "m", "v1")
    d2 = _stage_artifact(tmp_path, "m", "v2")
    v1 = ModelVersion(
        name="m",
        version="v1",
        algorithm="rf",
        classes=["BENIGN", "DDoS"],
        feature_order=["a", "b"],
        metrics={},
        artifact_path=str(d1),
        is_active=False,
    )
    v2 = ModelVersion(
        name="m",
        version="v2",
        algorithm="rf",
        classes=["BENIGN", "DDoS"],
        feature_order=["a", "b"],
        metrics={},
        artifact_path=str(d2),
        is_active=False,
    )
    db_session.add_all([v1, v2])
    await db_session.flush()

    # Activate v1 (no prior active).
    activated, loaded = await lifecycle.activate_version(db_session, v1.id, actor="admin")
    assert activated.id == v1.id and activated.is_active is True
    assert loaded is True  # dummy artifact loads into the registry
    assert get_model_registry().get().version == "v1"

    # Activate v2 → v1 deactivated, audit records previous = v1.
    await lifecycle.activate_version(db_session, v2.id, actor="admin", reason="promote")
    await db_session.refresh(v1)
    await db_session.refresh(v2)
    assert v2.is_active is True and v1.is_active is False

    # Rollback → back to v1.
    rolled, _ = await lifecycle.rollback(db_session, actor="admin", reason="regression")
    assert rolled.id == v1.id
    await db_session.refresh(v1)
    await db_session.refresh(v2)
    assert v1.is_active is True and v2.is_active is False

    # Audit history: 3 rows, newest first (rollback, activate v2, activate v1).
    activations = await lifecycle.list_activations(db_session)
    assert [a.action for a in activations[:3]] == ["rollback", "activate", "activate"]
    rollback_row = activations[0]
    assert rollback_row.model_version_id == v1.id
    assert rollback_row.previous_version_id == v2.id
    assert rollback_row.actor == "admin"
    assert rollback_row.reason == "regression"


async def test_rollback_without_history_errors(db_session: AsyncSession) -> None:
    from app.core.errors import AppError

    with pytest.raises(AppError):
        await lifecycle.rollback(db_session, actor="admin")


async def test_activate_missing_version_errors(db_session: AsyncSession) -> None:
    from app.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await lifecycle.activate_version(db_session, 999_999, actor="admin")


# ----- drift feedback proxy on a persisted snapshot ------------------------


async def test_drift_snapshot_carries_feedback(db_session: AsyncSession) -> None:
    # A loaded bundle whose baseline references features present in recent events.
    bundle = ModelBundle(
        pipeline={"dummy": True},
        metadata={"name": "m", "version": "vX", "baseline": _hand_baseline()},
        classes=["BENIGN", "DDoS"],
        feature_order=["a", "b"],
        name="m",
        version="vX",
        algorithm="rf",
        artifact_dir=Path("/tmp/m"),
        loaded_at=datetime.now(UTC),
    )
    get_model_registry()._bundle = bundle

    # Recent events feeding the baseline features.
    for i in range(15):
        db_session.add(
            NetworkEvent(
                event_time=datetime.now(UTC),
                src_ip="10.0.0.1",
                dst_ip="10.0.0.2",
                features={"a": float(i * 5), "b": float(i * 2)},
            )
        )
    # Alerts with analyst dispositions → the feedback proxy.
    dispositions = [
        AlertDisposition.CONFIRMED,
        AlertDisposition.CONFIRMED,
        AlertDisposition.FALSE_POSITIVE,
        AlertDisposition.OPEN,
    ]
    for disp in dispositions:
        db_session.add(
            Alert(
                src_ip="10.0.0.1",
                dst_ip="10.0.0.2",
                prediction="DDoS",
                confidence=0.9,
                status=AlertStatus.NEW,
                disposition=disp,
            )
        )
    await db_session.flush()

    result = await drift_service.run_drift_check(db_session, window_hours=24)
    assert result.available is True
    fb = result.snapshot.feedback
    assert fb["total"] == 4
    assert fb["confirmed_rate"] == pytest.approx(0.5)
    assert fb["quality_score"] == pytest.approx(2 / 3, abs=1e-3)


# ----- shadow evaluation ---------------------------------------------------


async def test_shadow_eval_persists_comparison(db_session: AsyncSession, tmp_path: Path) -> None:
    active_pipe = _fit_pipeline(seed=1)
    candidate_pipe = _fit_pipeline(seed=2)
    active_dir = _stage_artifact(tmp_path, "m", "active", pipeline=active_pipe)
    cand_dir = _stage_artifact(tmp_path, "m", "candidate", pipeline=candidate_pipe)

    # Active model loaded in memory + a DB row marked active.
    get_model_registry().load_from_dir(active_dir)
    active_row = ModelVersion(
        name="m",
        version="active",
        algorithm="rf",
        classes=["BENIGN", "DDoS"],
        feature_order=["a", "b"],
        metrics={},
        artifact_path=str(active_dir),
        is_active=True,
    )
    candidate_row = ModelVersion(
        name="m",
        version="candidate",
        algorithm="rf",
        classes=["BENIGN", "DDoS"],
        feature_order=["a", "b"],
        metrics={},
        artifact_path=str(cand_dir),
        is_active=False,
    )
    db_session.add_all([active_row, candidate_row])
    await db_session.flush()

    for i in range(12):
        db_session.add(
            NetworkEvent(
                event_time=datetime.now(UTC),
                src_ip="10.0.0.1",
                dst_ip="10.0.0.2",
                features={"a": float(10 + i), "b": float(5 + i)},
            )
        )
    await db_session.flush()

    snapshot = await lifecycle.shadow_eval(
        db_session, candidate_row.id, window_hours=24, actor="alice"
    )
    assert snapshot.sample_count == 12
    assert snapshot.agreement_rate is not None and 0.0 <= snapshot.agreement_rate <= 1.0
    assert snapshot.candidate_version_id == candidate_row.id
    assert snapshot.active_version_id == active_row.id
    assert "candidate_label_distribution" in snapshot.metrics
    assert snapshot.created_by == "alice"
