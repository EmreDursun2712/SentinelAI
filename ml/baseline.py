"""Training-baseline statistics for drift monitoring.

Captured at train time and embedded in ``metadata.json`` under ``baseline`` so
the backend can compare recent traffic against the distribution the model was
trained on — without re-reading the training data.

For each numeric feature we store quantile bin edges and the baseline proportion
in each bin (the reference distribution for a PSI computation), plus mean/std.
We also store the training class distribution. The bucketing convention here
(``bin_props``) must match the backend's drift computation exactly.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# Bump if the baseline shape changes so the backend can detect incompatibility.
BASELINE_VERSION = 1
DEFAULT_BINS = 10


def bin_props(values: np.ndarray, edges: list[float] | np.ndarray) -> list[float]:
    """Proportion of ``values`` in each bin defined by ``edges`` (len k+1 → k bins).

    Values are clipped into the end bins (anything below the first edge lands in
    bin 0; anything at/above the last edge lands in bin k-1). Returns proportions
    that sum to 1 (or all zeros for empty input).
    """
    edges = np.asarray(edges, dtype=float)
    k = len(edges) - 1
    if k < 1:
        return []
    clean = values[np.isfinite(values)]
    if clean.size == 0:
        return [0.0] * k
    # Internal boundaries only → indices 0..k-1.
    idx = np.digitize(clean, edges[1:-1], right=False)
    counts = np.bincount(idx, minlength=k).astype(float)
    total = counts.sum()
    return (counts / total).tolist() if total else [0.0] * k


def compute_baseline(
    X: pd.DataFrame,
    y_labels: list[str],
    classes: list[str],
    *,
    n_bins: int = DEFAULT_BINS,
) -> dict[str, Any]:
    """Build the baseline payload from the training feature matrix + labels."""
    features: dict[str, Any] = {}
    for col in X.columns:
        series = (
            pd.to_numeric(X[col], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
        )
        if series.empty:
            continue
        edges = np.unique(np.quantile(series.to_numpy(), np.linspace(0, 1, n_bins + 1)))
        # Need at least two distinct bins for PSI to be meaningful; skip
        # constant/degenerate features.
        if edges.size < 3:
            continue
        features[col] = {
            "mean": float(series.mean()),
            "std": float(series.std(ddof=0)),
            "bin_edges": [float(e) for e in edges],
            "bin_props": bin_props(series.to_numpy(), edges),
        }

    counts = pd.Series(list(y_labels)).value_counts()
    total = int(counts.sum()) or 1
    class_distribution = {str(k): float(v) / total for k, v in counts.items()}

    return {
        "version": BASELINE_VERSION,
        "sample_count": int(len(X)),
        "n_bins": n_bins,
        "class_distribution": class_distribution,
        "features": features,
    }
