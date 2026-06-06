"""Model drift monitoring tests.

The PSI / windowing math is pure and tested directly. The DB-bound
``run_drift_check`` is tested on its early-return (no model / no baseline)
paths, and the API surface is tested for auth + serialization with the service
layer stubbed (so the suite stays Redis/DB-free and deterministic).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.deps import db_session
from app.core.security import create_access_token
from app.models.enums import DriftStatus, Role
from app.services import drift_service
from app.services.drift_service import (
    DriftRunResult,
    aggregate_drift_score,
    bucket_props,
    compute_feature_drift,
    confidence_stats,
    distribution_psi,
    psi,
    run_drift_check,
    status_for_score,
)
from app.services.model_registry import ModelBundle, get_model_registry

# ---------------------------------------------------------------------------
# PSI + bucketing.
# ---------------------------------------------------------------------------


def test_psi_zero_for_identical_distributions() -> None:
    p = [0.25, 0.25, 0.25, 0.25]
    assert psi(p, p) == pytest.approx(0.0, abs=1e-9)


def test_psi_grows_with_divergence() -> None:
    base = [0.5, 0.5]
    small = psi(base, [0.45, 0.55])
    large = psi(base, [0.1, 0.9])
    assert 0 < small < large


def test_bucket_props_clips_into_end_bins() -> None:
    edges = [0.0, 1.0, 2.0, 3.0]  # 3 bins
    props = bucket_props([-5.0, 0.5, 1.5, 2.5, 100.0], edges)
    assert props == pytest.approx([0.4, 0.2, 0.4])  # -5 and 100 clip to ends
    assert sum(props) == pytest.approx(1.0)


def test_bucket_props_empty_input() -> None:
    assert bucket_props([], [0.0, 1.0, 2.0]) == [0.0, 0.0]


def test_distribution_psi_handles_new_category() -> None:
    score, props = distribution_psi({"DDoS": 1.0}, {"DDoS": 5, "PortScan": 5})
    assert props == {"DDoS": 0.5, "PortScan": 0.5}
    assert score > 0  # a brand-new family is a real shift


# ---------------------------------------------------------------------------
# Stats + scoring.
# ---------------------------------------------------------------------------


def test_confidence_stats() -> None:
    s = confidence_stats([0.2, 0.4, 0.6, 0.8, 1.0])
    assert s["count"] == 5
    assert s["mean"] == pytest.approx(0.6)
    assert s["min"] == pytest.approx(0.2)
    assert s["max"] == pytest.approx(1.0)
    assert s["p95"] == pytest.approx(0.96, abs=1e-6)


def test_confidence_stats_empty() -> None:
    s = confidence_stats([])
    assert s == {"count": 0, "mean": None, "min": None, "max": None, "p95": None}


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, DriftStatus.OK),
        (0.09, DriftStatus.OK),
        (0.10, DriftStatus.WATCH),
        (0.24, DriftStatus.WATCH),
        (0.25, DriftStatus.DRIFT),
        (1.0, DriftStatus.DRIFT),
    ],
)
def test_status_thresholds(score: float, expected: DriftStatus) -> None:
    assert status_for_score(score) == expected


def test_aggregate_drift_score_means_components() -> None:
    feature_drift = {"a": {"psi": 0.2}, "b": {"psi": 0.4}}
    assert aggregate_drift_score(feature_drift, None) == pytest.approx(0.3)
    assert aggregate_drift_score(feature_drift, 0.6) == pytest.approx(0.4)
    assert aggregate_drift_score({}, None) is None


def test_compute_feature_drift_skips_thin_and_unknown_features() -> None:
    baseline = {
        "flow_duration": {
            "bin_edges": [0.0, 1.0, 2.0, 3.0],
            "bin_props": [0.34, 0.33, 0.33],
        }
    }
    recent = {
        "flow_duration": [0.5] * 20,  # all in bin 0 → big shift
        "not_in_baseline": [1.0] * 50,
    }
    out = compute_feature_drift(baseline, recent, min_samples=10)
    assert set(out) == {"flow_duration"}
    assert out["flow_duration"]["psi"] > 0.25
    assert out["flow_duration"]["sample_count"] == 20


def test_compute_feature_drift_respects_min_samples() -> None:
    baseline = {"f": {"bin_edges": [0.0, 1.0, 2.0], "bin_props": [0.5, 0.5]}}
    out = compute_feature_drift(baseline, {"f": [0.5, 1.5]}, min_samples=10)
    assert out == {}


# ---------------------------------------------------------------------------
# run_drift_check early returns (no DB needed).
# ---------------------------------------------------------------------------


def _fake_bundle(metadata: dict) -> ModelBundle:
    return ModelBundle(
        pipeline=object(),
        metadata=metadata,
        classes=["BENIGN", "DDoS"],
        feature_order=["flow_duration"],
        name="t",
        version="v0",
        algorithm="rf",
        artifact_dir=Path("/tmp"),
        loaded_at=datetime.now(UTC),
    )


async def test_run_drift_check_unavailable_without_model() -> None:
    reg = get_model_registry()
    reg.clear()
    result = await run_drift_check(object())  # type: ignore[arg-type]
    assert result.available is False
    assert result.reason == "model_not_loaded"


async def test_run_drift_check_unavailable_without_baseline() -> None:
    reg = get_model_registry()
    reg._bundle = _fake_bundle({"name": "t"})  # no "baseline" key
    try:
        result = await run_drift_check(object())  # type: ignore[arg-type]
        assert result.available is False
        assert result.reason == "baseline_unavailable"
    finally:
        reg.clear()


# ---------------------------------------------------------------------------
# API surface (auth + serialization; service stubbed, DB session overridden).
# ---------------------------------------------------------------------------


async def _dummy_session() -> AsyncIterator[None]:
    yield None


def _headers(role: Role) -> dict[str, str]:
    token, _ = create_access_token("drift-user", {"role": role.value})
    return {"Authorization": f"Bearer {token}"}


async def test_drift_latest_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/detection/drift/latest")).status_code == 401


async def test_drift_run_forbidden_for_viewer(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/detection/drift/run", headers=_headers(Role.VIEWER)
    )
    assert resp.status_code == 403


async def test_drift_latest_reports_unavailable(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[db_session] = _dummy_session
    get_model_registry().clear()

    async def fake_latest(session):
        return None

    monkeypatch.setattr(drift_service, "get_latest_snapshot", fake_latest)
    resp = await client.get(
        "/api/v1/detection/drift/latest", headers=_headers(Role.VIEWER)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["reason"] == "no_snapshot"
    app.dependency_overrides.clear()


async def test_drift_run_analyst_gets_report(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[db_session] = _dummy_session

    async def fake_run(session, *, window_hours):
        assert window_hours == 24
        return DriftRunResult(False, reason="baseline_unavailable")

    monkeypatch.setattr(drift_service, "run_drift_check", fake_run)
    resp = await client.post(
        "/api/v1/detection/drift/run", headers=_headers(Role.ANALYST)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["reason"] == "baseline_unavailable"
    app.dependency_overrides.clear()


async def test_drift_history_serializes_snapshots(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[db_session] = _dummy_session
    from app.models import ModelDriftSnapshot

    snap = ModelDriftSnapshot(
        id=1,
        model_version_id=None,
        window_start=datetime.now(UTC),
        window_end=datetime.now(UTC),
        sample_count=42,
        feature_drift={"flow_duration": {"psi": 0.3, "sample_count": 42}},
        prediction_distribution={"recent": {"DDoS": 1.0}, "psi": 0.0},
        confidence_stats={"count": 5, "mean": 0.9, "min": 0.8, "max": 1.0, "p95": 0.99},
        drift_score=0.3,
        status=DriftStatus.DRIFT,
        created_at=datetime.now(UTC),
    )

    async def fake_list(session, *, limit):
        return [snap]

    monkeypatch.setattr(drift_service, "list_snapshots", fake_list)
    resp = await client.get(
        "/api/v1/detection/drift/history?limit=5", headers=_headers(Role.VIEWER)
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "DRIFT"
    assert items[0]["drift_score"] == 0.3
    app.dependency_overrides.clear()
