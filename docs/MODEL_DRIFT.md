# Model drift monitoring

The detector is trained once but traffic keeps changing. Drift monitoring flags
when recent flows diverge from the distribution the model was trained on, so an
analyst knows when predictions may no longer be trustworthy.

## Training baseline

Training embeds a `baseline` block in the artifact's `metadata.json`
(`ml/baseline.py`): per-feature **quantile bin edges + proportions**, means/stds,
and the **training class distribution**. Artifacts trained before this existed
report drift **unavailable** (graceful degradation).

```jsonc
"baseline": {
  "version": 1, "sample_count": 5600, "n_bins": 10,
  "class_distribution": { "BENIGN": 0.6, "DDoS": 0.15, ... },
  "features": { "flow_duration": { "mean": ..., "std": ...,
                "bin_edges": [...11...], "bin_props": [...10...] }, ... }
}
```

## Computation (deterministic, unit-tested)

`app/services/drift_service.py` over a window (default last 24h):

1. For each baseline feature with enough recent samples, bucket recent values
   into the baseline `bin_edges` and compute a **PSI** vs the baseline `bin_props`.
2. Compute a **prediction-mix PSI** (recent alert families vs the baseline's
   non-benign class distribution).
3. `confidence_stats`: mean / min / max / p95 of recent alert confidence.
4. `drift_score` = mean PSI across all computed components.

Status bands (standard PSI thresholds):

| Status | Score | Meaning |
| --- | --- | --- |
| `OK` | `< 0.10` | Distribution stable. |
| `WATCH` | `0.10–0.25` | Moderate shift; keep an eye on it. |
| `DRIFT` | `≥ 0.25` | Significant shift; consider retraining. |

Each run persists a `model_drift_snapshots` row (migration `0006`).

## API

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/detection/drift/latest` | VIEWER+ | Most recent snapshot (or `available:false`). |
| GET | `/api/v1/detection/drift/history?limit=` | VIEWER+ | Recent snapshots. |
| POST | `/api/v1/detection/drift/run` | ANALYST+ | Compute + persist a snapshot. |

Unavailable reasons (`available:false`): `no_snapshot`, `baseline_unavailable`,
`model_not_loaded`, `no_recent_data`, `insufficient_data`.

## Dashboard

The **Model health** panel shows the current status (OK/WATCH/DRIFT/unavailable),
drift score, sample count, average confidence, last-checked time, and the top
drifting features by PSI. Analysts/admins get a **Run drift check** button.

Tests: `backend/tests/test_drift.py` (PSI, bucketing, stats, thresholds,
early-returns, API auth); `frontend/src/lib/drift.test.ts`.
