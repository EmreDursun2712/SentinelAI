"""Save / load trained model artifacts to a versioned directory layout.

Layout:

    ml/artifacts/
    ├── <version>/
    │   ├── model.joblib            # the sklearn Pipeline (imputer + classifier)
    │   ├── metadata.json           # name, version, algorithm, classes, feature_order, ...
    │   ├── metrics.json            # validation + test metrics
    │   └── confusion_matrix.json   # confusion matrices for val + test
    └── latest/                     # copy of the most recent <version>/

The backend's Detection Agent will read ``ml/artifacts/latest/`` by default and
fall back to whatever path the ``model_versions`` DB row points at.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
from sklearn.pipeline import Pipeline


def make_version(prefix: str = "v") -> str:
    """Generate a timestamp-based version string."""
    return datetime.now(UTC).strftime(f"{prefix}%Y%m%d-%H%M%S")


def save_artifacts(
    *,
    output_dir: Path,
    pipeline: Pipeline,
    classes: list[str],
    feature_order: list[str],
    metadata: dict[str, Any],
    metrics: dict[str, Any],
    confusion: dict[str, Any],
) -> None:
    """Persist the model and its surrounding JSON to ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, output_dir / "model.joblib")

    full_metadata = {
        **metadata,
        "classes": list(classes),
        "feature_order": list(feature_order),
        "saved_at": datetime.now(UTC).isoformat(),
    }
    _write_json(output_dir / "metadata.json", full_metadata)
    _write_json(output_dir / "metrics.json", metrics)
    _write_json(output_dir / "confusion_matrix.json", confusion)


def update_latest(artifacts_root: Path, version_dir: Path) -> Path:
    """Refresh ``artifacts/latest/`` so it mirrors ``version_dir``.

    Implemented as a directory copy for cross-platform portability (Windows
    symlinks require elevated privileges; copytree always works).
    """
    latest = artifacts_root / "latest"
    if latest.exists():
        if latest.is_symlink() or latest.is_file():
            latest.unlink()
        else:
            shutil.rmtree(latest)
    shutil.copytree(version_dir, latest)
    return latest


def load_artifact_bundle(model_dir: Path) -> tuple[Pipeline, dict[str, Any]]:
    """Load a saved model and its metadata together."""
    pipeline = joblib.load(model_dir / "model.joblib")
    metadata = json.loads((model_dir / "metadata.json").read_text())
    return pipeline, metadata


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
