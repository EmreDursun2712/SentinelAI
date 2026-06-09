# Detection — model loading and inference

The Detection Agent is the first step of the workflow: it consumes a
`NetworkEvent`, runs the trained scikit-learn pipeline on the event's
`features` JSONB, and — when the prediction crosses the configured
confidence threshold — creates an `Alert` plus an `AgentDecision` audit row.

## Lifecycle

```
┌──────────────────────────┐
│ ml.train  (Phase 2)      │  → ml/artifacts/<version>/{model.joblib, metadata.json, …}
│                          │  → ml/artifacts/latest/ (copy)
└──────────────┬───────────┘
               │ (bind-mount)
               ▼
┌──────────────────────────┐    startup: ModelRegistry.load_from_disk()
│ Backend container        │    ─────────────────────────────────────────
│ /app/ml_artifacts/latest │    on first detect():
└──────────────┬───────────┘      • ensure_model_version_row()  ← syncs model_versions table
               │                  • build_feature_matrix(...)
               │                  • pipeline.predict_proba(X)
               ▼                  • should_create_alert(label, conf, threshold, benign_label)
       Alert + AgentDecision      • event.detected_at = now()
       (or: just mark detected)
```

## How predictions become alerts

For every event passed through detection:

1. The model returns a probability vector over `classes`.
2. The top class becomes `predicted_label`; the top probability becomes `confidence`.
3. **Alert rule:** `predicted_label != BENIGN AND confidence ≥ threshold`.
4. If yes: a new `Alert` row is inserted (`status=NEW`) and an `AgentDecision`
   row captures the full probability vector + threshold for audit.
5. The **Triage agent runs inline** in the same transaction (`auto_triage=True`
   by default). Severity + priority are computed, a second `AgentDecision`
   row is appended, and the alert transitions to `status=TRIAGED`. See
   [TRIAGE.md](TRIAGE.md) for the rule engine.
6. Either way, `network_events.detected_at` is stamped so the event isn't
   re-processed.

The `simulated=TRUE` ethics guardrail lives on `response_actions`, not on
detection — detection itself is a read-only inference step.

## Feature coverage & calibrated confidence

A model is only meaningful on the feature vector it was trained on. Two
safeguards keep train and serve aligned (see [ML_TRAINING.md](ML_TRAINING.md)):

- **Coverage validation.** Before inference the backend computes the share of the
  model's trained features actually present (finite) in the batch
  (`assess_feature_coverage`). Below the model's declared
  `expected_feature_coverage` (metadata) — or `SENTINEL_DETECTION_FEATURE_COVERAGE_WARN`
  as a fallback — it logs `detection.low_feature_coverage`. Setting
  `SENTINEL_DETECTION_FEATURE_COVERAGE_MIN > 0` makes under-coverage a hard 400
  instead. `POST /detection/run` returns the batch `feature_coverage`; the
  dashboard model panel shows the model's expected coverage.
- **Calibrated confidence.** When a model is trained with `--calibrate`, its
  `predict_proba` is calibrated, so the confidence the alert threshold compares
  against is a real probability. `GET /detection/model` reports `calibrated`.

## Endpoints

| Method | Path                                  | Persistence | Notes                                                  |
| ------ | ------------------------------------- | ----------- | ------------------------------------------------------ |
| GET    | `/api/v1/detection/model`             | —           | Loaded bundle info + threshold + DB id of model_versions. |
| POST   | `/api/v1/detection/predict`           | No          | Inference on raw `FlowRecordIn` list; no DB writes.     |
| POST   | `/api/v1/detection/events/{event_id}` | Yes         | Detect one stored event; persists alert + decision.    |
| POST   | `/api/v1/detection/batch`             | Yes         | Detect a list of `event_ids`; persists.                |
| POST   | `/api/v1/detection/run`               | Yes         | Process the next `limit` un-detected events.           |
| GET    | `/api/v1/detection/drift/latest`      | —           | Most recent drift snapshot (or `available:false`). VIEWER+. |
| GET    | `/api/v1/detection/drift/history`     | —           | Recent drift snapshots (`?limit=`). VIEWER+.           |
| POST   | `/api/v1/detection/drift/run`         | Yes         | Compute + persist a drift snapshot. ANALYST+.          |

## Drift monitoring

The model is trained once but traffic keeps changing. Drift monitoring flags
when recent flows diverge from the distribution the model was trained on, so an
analyst knows when predictions may no longer be trustworthy (time to retrain).

**Baseline.** Training embeds a `baseline` block in `metadata.json` (see
[ml/README.md](../../ml/README.md)): per-feature quantile bins + proportions,
means/stds, and the training class distribution. Artifacts without it report
drift **unavailable** (graceful degradation).

**Computation** (`app/services/drift_service.py`, deterministic + unit-tested):

* Pull recent `network_events` (features) and `alerts` (predictions/confidence)
  in a window (default last 24h, configurable via `window_hours`).
* For each baseline feature with enough recent samples, bucket recent values
  into the baseline `bin_edges` and compute **PSI** vs the baseline `bin_props`.
* Compute a **PSI over the prediction mix** (recent alert families vs the
  baseline's non-benign class distribution).
* `confidence_stats`: mean / min / max / p95 of recent alert confidence.
* `drift_score` = mean PSI across all computed components.

**Status bands** (standard PSI thresholds):

| Status  | Score          | Meaning                                  |
| ------- | -------------- | ---------------------------------------- |
| `OK`    | `< 0.10`       | Distribution stable.                     |
| `WATCH` | `0.10–0.25`    | Moderate shift; keep an eye on it.       |
| `DRIFT` | `≥ 0.25`       | Significant shift; consider retraining.  |

**Analyst-feedback quality proxy.** Each snapshot also carries a `feedback`
block derived from alert dispositions in the window — a weak-label signal that
complements the distributional PSI: `false_positive_rate`, `confirmed_rate`,
`unresolved_rate`, and a `quality_score` (CONFIRMED / (CONFIRMED +
FALSE_POSITIVE), a precision proxy). Rising false positives / a falling quality
score flags a model that may need retraining even when feature PSI looks stable.
See [MODEL_LIFECYCLE.md](MODEL_LIFECYCLE.md#analyst-feedback-as-a-quality-proxy).

Each run persists a `model_drift_snapshots` row. The dashboard's **Model
health** panel shows the latest status, drift score, sample count, average
confidence, last-checked time, the top drifting features, and the analyst-feedback
quality proxy; analysts/admins can trigger a check with **Run drift check**.

## Configuration

| Env var                              | Default              | Purpose                                          |
| ------------------------------------ | -------------------- | ------------------------------------------------ |
| `SENTINEL_ML_ARTIFACTS_DIR`          | `/app/ml_artifacts`  | Path containing the `latest/` bundle.            |
| `SENTINEL_DETECTION_THRESHOLD`       | `0.5`                | Minimum top-class probability to create an alert. |
| `SENTINEL_DETECTION_BENIGN_LABEL`    | `BENIGN`             | Class that suppresses alerts at any confidence.   |
| `SENTINEL_DETECTION_FEATURE_COVERAGE_WARN` | `0.5`          | Coverage below which inference logs a warning (model metadata wins). |
| `SENTINEL_DETECTION_FEATURE_COVERAGE_MIN`  | `0.0`          | `> 0` ⇒ under-coverage is a hard 400; `0` ⇒ graceful degradation. |

## Storage contract

| Table                 | What detection writes                                                                |
| --------------------- | ------------------------------------------------------------------------------------ |
| `model_versions`      | Upsert on `(name, version)`; row marked `is_active=TRUE` (partial unique index).     |
| `network_events`      | `detected_at` set so the event won't be reprocessed.                                 |
| `alerts`              | One row per suspicious event with `prediction`, `confidence`, `model_version_id`.    |
| `agent_decisions`     | One row tied to the alert with `agent=DETECTION`, full probabilities in `reasoning`. |

The lazy DB sync (`ensure_model_version_row`) only fires the first time a
session-aware detection call runs. The `/api/v1/detection/model` endpoint also
triggers it implicitly when the bundle's `db_id` is `None`.

## End-to-end demo

```bash
# 1. Train a model (Phase 2)
python -m ml.train --synthetic 50000
ls ml/artifacts/latest/        # → confusion_matrix.json metadata.json metrics.json model.joblib

# 2. Bring the stack up; backend will auto-load the bundle on startup
docker compose up -d --build

# 3. Migrate (Phase 1 + 0002 detected_at)
docker compose exec backend alembic upgrade head

# 4. Confirm the model is loaded
curl -s http://localhost:8000/api/v1/detection/model | jq
# {
#   "loaded": true,
#   "name": "sentinelai-detection",
#   "version": "v20260520-073940",
#   "classes": ["BENIGN", "BruteForce", "DDoS", "PortScan"],
#   "feature_order": [...],
#   "threshold": 0.5,
#   "benign_label": "BENIGN",
#   ...
# }

# 5. Ingest the bundled sample CSV
curl -s -X POST -F 'file=@backend/data/samples/sample_flows.csv' \
     http://localhost:8000/api/v1/ingest/upload | jq

# 6. Run detection on the freshly-ingested events
curl -s -X POST -H 'Content-Type: application/json' \
     http://localhost:8000/api/v1/detection/run -d '{"limit": 1000}' | jq
# {
#   "processed": 20, "alerts_created": 12, "benign_count": 7,
#   "by_label": {"BENIGN": 7, "DDoS": 5, "BruteForce": 5, "PortScan": 3},
#   "model_name": "sentinelai-detection", "model_version": "v..."
# }

# 7. List the alerts that were created
curl -s "http://localhost:8000/api/v1/alerts?limit=10" | jq

# 8. Verify the audit trail in psql
docker compose exec postgres psql -U sentinelai -d sentinelai -c "
  SELECT a.id, a.prediction, a.confidence::numeric(5,3) AS conf,
         a.status, d.agent
  FROM alerts a
  JOIN agent_decisions d ON d.alert_id = a.id
  ORDER BY a.id DESC LIMIT 10;
"

# 9. Try the no-persistence path
curl -s -X POST http://localhost:8000/api/v1/detection/predict \
     -H 'Content-Type: application/json' \
     -d '{"flows": [{
           "event_time":"2024-01-15T08:23:14Z",
           "src_ip":"10.0.0.1","dst_ip":"10.0.0.2",
           "src_port":52341,"dst_port":443,"protocol":"TCP",
           "features": {"flow_duration": 32, "total_fwd_packets": 4,
                        "flow_bytes/s": 8500}
         }]}' | jq
```

## Behavior when no model is loaded

If `ml/artifacts/latest/` is missing or the metadata is malformed:

- Backend still starts; `/health` is 200 and `/readyz` is 200 (DB is fine).
- `/api/v1/detection/model` returns `{"loaded": false, ...}`.
- Any persistence-bound detection call returns the standard error envelope
  with `code="app_error"` and a clear message pointing at the artifacts dir.
- Operators can drop a new bundle into `ml/artifacts/latest/` and call
  `/api/v1/detection/model` to trigger a lazy reload without restarting.

## Notes

- The pipeline is bundled (`SimpleImputer → classifier`), so the backend
  doesn't need to know anything about preprocessing — just the
  `feature_order` from `metadata.json`.
- Missing feature keys, `None`, `"NaN"`, and `±Inf` in `network_events.features`
  all become `NaN` in the feature matrix and the imputer fills them with the
  training-set median.
- Alerts inherit the event's `src_ip`/`dst_ip`/`src_port`/`dst_port`/`protocol`
  so dashboard queries can filter by network identity without re-joining
  `network_events`.
