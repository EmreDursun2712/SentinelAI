"""Model artifact loading and process-wide caching.

The backend keeps exactly one ``ModelBundle`` in memory at a time. Startup tries
to load it from ``settings.ml_artifacts_dir/latest/`` and continues if no
artifact is found — detection endpoints then return a clear error until one
exists.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ModelBundle:
    """In-memory view of a trained artifact."""

    pipeline: Any
    metadata: dict[str, Any]
    classes: list[str]
    feature_order: list[str]
    name: str
    version: str
    algorithm: str
    artifact_dir: Path
    loaded_at: datetime
    # Cached primary key from model_versions; populated on first DB sync.
    db_id: int | None = field(default=None)


class ModelRegistry:
    """Process-wide singleton for the currently loaded model artifact."""

    def __init__(self) -> None:
        self._bundle: ModelBundle | None = None
        self._lock = threading.Lock()

    def get(self) -> ModelBundle | None:
        return self._bundle

    def is_loaded(self) -> bool:
        return self._bundle is not None

    def load_from_disk(self, artifacts_dir: Path | str) -> ModelBundle | None:
        """Try to load ``<artifacts_dir>/latest/``. Returns None on failure."""
        artifacts_path = Path(artifacts_dir)
        latest = artifacts_path / "latest"
        model_file = latest / "model.joblib"
        meta_file = latest / "metadata.json"

        if not model_file.is_file() or not meta_file.is_file():
            logger.warning(
                "model.not_found",
                artifacts_dir=str(artifacts_path),
                model_file=str(model_file),
                metadata_file=str(meta_file),
            )
            return None

        try:
            pipeline = joblib.load(model_file)
            metadata = json.loads(meta_file.read_text())
        except Exception as exc:
            logger.exception("model.load_failed", error=str(exc))
            return None

        classes = list(metadata.get("classes", []))
        feature_order = list(metadata.get("feature_order", []))
        if not classes or not feature_order:
            logger.error(
                "model.invalid_metadata",
                classes_len=len(classes),
                feature_order_len=len(feature_order),
            )
            return None

        bundle = ModelBundle(
            pipeline=pipeline,
            metadata=metadata,
            classes=classes,
            feature_order=feature_order,
            name=str(metadata.get("name", "unknown")),
            version=str(metadata.get("version", "unknown")),
            algorithm=str(metadata.get("algorithm", "unknown")),
            artifact_dir=latest,
            loaded_at=datetime.now(UTC),
        )

        with self._lock:
            self._bundle = bundle

        logger.info(
            "model.loaded",
            name=bundle.name,
            version=bundle.version,
            algorithm=bundle.algorithm,
            n_classes=len(bundle.classes),
            n_features=len(bundle.feature_order),
        )
        return bundle

    def reload(self, artifacts_dir: Path | str) -> ModelBundle | None:
        return self.load_from_disk(artifacts_dir)

    def clear(self) -> None:
        with self._lock:
            self._bundle = None


_registry = ModelRegistry()


def get_model_registry() -> ModelRegistry:
    return _registry
