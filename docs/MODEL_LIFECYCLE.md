# Model Lifecycle — registry, activate / rollback, shadow eval

Training produces versioned artifacts; this is how the running backend chooses
**which** version serves traffic, switches between them safely, and compares a
candidate before promoting it. See [ML_TRAINING.md](ML_TRAINING.md) for producing
versions and [DETECTION.md](DETECTION.md) for how the active model is served.

## Registry

`model_versions` is the source of truth for the active model. A partial unique
index (`uq_model_versions_one_active`) guarantees **at most one** `is_active` row.
Listing lazily syncs the registry from artifacts on disk
(`sync_versions_from_disk`), so a freshly-trained version appears without a
restart. Rows are keyed on `(name, version)`, so the `latest/` mirror and its
concrete version directory collapse to a single row.

**Artifacts are never deleted.** Activation only flips a flag and reloads the
in-memory model; every prior version stays on disk and in the registry, so
rollback is always possible.

## API

All endpoints are under `/api/v1/models`, behind method-based RBAC (reads
VIEWER+, writes ANALYST+). Activate/rollback add an explicit **ADMIN** guard.

| Method | Path                                  | Role     | Purpose                                              |
| ------ | ------------------------------------- | -------- | ---------------------------------------------------- |
| GET    | `/api/v1/models`                      | VIEWER+  | List registered versions (+ `active_version_id`).    |
| GET    | `/api/v1/models/activations`          | VIEWER+  | Activation/rollback audit history.                   |
| GET    | `/api/v1/models/shadow`               | VIEWER+  | Recent shadow evaluations.                           |
| POST   | `/api/v1/models/{id}/activate`        | ADMIN    | Activate a version; audited.                         |
| POST   | `/api/v1/models/rollback`             | ADMIN    | Roll back to the previously active version; audited. |
| POST   | `/api/v1/models/shadow`               | ANALYST+ | Shadow-eval a candidate against the active model.    |

### Activate / rollback

Activation deactivates every other row, marks the target active, loads its
artifact into the in-memory registry, and appends a `model_activations` audit
row. The response includes `loaded` — whether the artifact was loaded into *this*
process (the DB flag is authoritative even if the file isn't present here):

```bash
# Activate version 7
curl -fsS -X POST localhost:8000/api/v1/models/7/activate \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H 'content-type: application/json' \
  -d '{"reason":"better recall on PortScan"}'
```

Rollback reads the most recent activation's `previous_version_id` and re-activates
it (also audited, with `action="rollback"`):

```bash
curl -fsS -X POST localhost:8000/api/v1/models/rollback \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H 'content-type: application/json' \
  -d '{"reason":"regression in production"}'
```

### Activation audit

Each `model_activations` row records `action` (`activate`|`rollback`),
`model_version_id` (now active), `previous_version_id` (replaced — the rollback
target), `actor`, `reason`, and `created_at`. Append-only; never deleted.

## Shadow / A-B evaluation

Shadow evaluation runs a **candidate** model over recent events **without
changing** what serves traffic, then compares its predictions to the active
model. Results persist to `model_shadow_evals`:

```bash
curl -fsS -X POST localhost:8000/api/v1/models/shadow \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"candidate_version_id": 9, "window_hours": 24}'
```

The stored `metrics` capture:

- `agreement_rate` — fraction of events where candidate and active agree
- `candidate_label_distribution` / `active_label_distribution`
- `candidate_mean_confidence` / `active_mean_confidence` / `mean_confidence_delta`

Use it to gauge how differently a candidate would behave before an ADMIN
activates it.

## Frontend

The **System** page shows a *Model versions* panel: every registered version with
the active one badged, an **Activate** button per inactive version (ADMIN), and a
**Rollback** button (ADMIN). The dashboard **Model** panel shows the active
model's calibration + expected feature coverage; **Model health** surfaces the
analyst-feedback quality proxy (see below).

## Analyst feedback as a quality proxy

Drift snapshots also carry a weak-label **model-quality proxy** derived from
analyst dispositions in the window (`feedback`):

- `false_positive_rate`, `confirmed_rate`, `resolved_rate`, `unresolved_rate`
- `quality_score` = CONFIRMED / (CONFIRMED + FALSE_POSITIVE) — a precision proxy
  over alerts that got a definitive verdict (`null` when there are none)

This treats `CONFIRMED` ≈ true positive and `FALSE_POSITIVE` ≈ false positive, so
rising false-positive / falling quality is an early signal the model needs
retraining — complementing the distributional PSI drift score. Surfaced on the
dashboard **Model health** panel. See [DETECTION.md](DETECTION.md#drift-monitoring).

## Storage contract

| Table                  | Written by                                        |
| ---------------------- | ------------------------------------------------- |
| `model_versions`       | training sync + activate/rollback (`is_active`).  |
| `model_activations`    | activate/rollback — append-only audit.            |
| `model_shadow_evals`   | shadow evaluation — one row per run.              |
| `model_drift_snapshots.feedback` | drift run — analyst-feedback proxy JSONB. |
