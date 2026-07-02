# ML Training — synthetic, real CIC-IDS2017, HPO & calibration

The training pipeline lives under [`ml/`](../ml) and writes versioned artifacts the
backend serves (see [DETECTION.md](DETECTION.md) and [ml/README.md](../ml/README.md)).
This guide covers the production-grade training paths: real CIC-IDS2017, optional
hyperparameter search, and probability calibration — plus the feature-parity and
metadata guarantees that keep train and serve aligned.

## Quick start (synthetic)

```bash
# ~10s on a laptop; high macro-F1 on well-separated synthetic classes.
python -m ml.train --synthetic 50000
ls ml/artifacts/latest/   # confusion_matrix.json metadata.json metrics.json model.joblib
```

## Train on real CIC-IDS2017

The raw dataset is **never committed** (`ml/data/` is gitignored). Download it,
drop the CSVs in, and point the trainer at the directory with the `cic2017`
profile:

```bash
# 1. Download from https://www.unb.ca/cic/datasets/ids-2017.html
# 2. Put the day-by-day CSVs under ml/data/cic-ids-2017/
# 3. Train:
python -m ml.train --data ml/data/cic-ids-2017 --profile cic2017
```

The loader tolerates CIC-IDS2017's quirks (UTF-8 BOM, leading spaces, mixed
case): headers are normalized to `snake_case` so trained feature names match what
the backend ingestor produces. Cleaned Kaggle mirrors that rename a few columns
(`Fwd Packets Length Total`, `Bwd Packets Length Total`, `Avg Packet Size`) are
folded onto the canonical names via [`COLUMN_ALIASES`](../ml/feature_list.py).

### Demo-compatible canonical model (recommended)

By default the real dataset yields a ~76-feature model that will **not** line up
with the 21-feature demo CSV. Train with `--feature-set canonical` to pin the
model to exactly the demo/backend schema, and balance the wildly-skewed classes
so rare families aren't buried:

```bash
python -m ml.train \
    --data ml/data/cic-ids-2017 --profile cic2017 \
    --feature-set canonical \              # 21-feature demo schema (100% coverage on the sample)
    --balance cap --max-per-class 20000 \  # cap BENIGN/DoS, keep the rare tail whole
    --min-class-count 100 \                # drop families too tiny to split (Heartbleed, Infiltration)
    --calibrate sigmoid                    # realistic confidences + reliability curve
```

This is the model the demo ships with: real CIC-IDS2017 traffic, serving the
bundled sample live. The `metadata.json` records `feature_set`, the before/after
`balance` counts, and any `dropped_classes` so the run is fully auditable.

| Flag                | Effect                                                                    |
| ------------------- | ------------------------------------------------------------------------- |
| `--feature-set`     | `full` (every numeric column) or `canonical` (the 21 demo features).      |
| `--balance`         | `none` or `cap` — downsample majority classes to `--max-per-class`.       |
| `--max-per-class`   | Row cap per class under `--balance cap` (default `20000`).                |
| `--min-class-count` | Drop classes with fewer than N rows before splitting (default `0`).       |
| `--calibrate`       | `sigmoid` / `isotonic` — calibrate served probabilities; records Brier + reliability curve. |

### Profiles (`--profile`)

A profile bundles dataset-specific label handling ([`ml/profiles.py`](../ml/profiles.py)):

| Profile     | Label handling                                                              |
| ----------- | -------------------------------------------------------------------------- |
| `auto`      | Default. Labels used as-is (whitespace trimmed).                            |
| `synthetic` | Same as `auto`; documents intent for synthetic data.                       |
| `cic2017`   | Folds attack sub-labels into coarse families that line up with the synthetic class space. |

The `cic2017` mapping (substring-based, casing/spacing tolerant):

| Raw label (examples)                              | Family       |
| ------------------------------------------------- | ------------ |
| `BENIGN`                                          | `BENIGN`     |
| `DDoS`, `DoS Hulk`, `DoS GoldenEye`, `DoS slowloris` | `DDoS`     |
| `PortScan`, `Port Scan`                           | `PortScan`   |
| `FTP-Patator`, `SSH-Patator`                      | `BruteForce` |
| `Web Attack – Brute Force / XSS / Sql Injection`  | `WebAttack`  |
| `Bot`                                             | `Bot`        |
| `Infiltration`                                    | `Infiltration` |
| `Heartbleed`                                      | `Heartbleed` |

Unknown labels pass through cleaned (title-cased) — nothing is silently dropped.
The chosen profile is recorded in `metadata.profile`.

## Feature parity (train ↔ serve)

A model is only as good as the feature vector it sees at inference. The pipeline
guarantees alignment three ways:

1. **One canonical feature set.** The synthetic generator, the canonical-feature
   real model, and the bundled sample CSV all share the same 21 features
   ([`CANONICAL_FEATURES`](../ml/feature_list.py)). The sample carries CIC-style
   display headers for **every** trained feature, so both a synthetic- and a
   real-canonical-trained model get 100% coverage on it. Regenerate the sample:

   ```bash
   # Real flows (what ships — the real model flags them as actual attacks):
   python -m ml.sample_export --data ml/data/cic-ids-2017 \
       --output backend/data/samples/sample_flows.csv

   # Or purely synthetic (no dataset download needed):
   python -m ml.synthetic --sample --output backend/data/samples/sample_flows.csv
   ```

2. **`feature_order` in metadata.** The backend rebuilds the inference vector in
   the exact trained order; missing keys become NaN for the in-pipeline imputer.

3. **Coverage validation.** Each model records `expected_feature_coverage`
   (`--min-feature-coverage`, default `0.8`). At inference the backend computes
   the share of trained features actually present and **warns** when it dips below
   the model's expectation. Set `SENTINEL_DETECTION_FEATURE_COVERAGE_MIN > 0` to
   turn under-coverage into a hard 400 instead of graceful degradation. The
   detection run summary returns the batch `feature_coverage`. See
   [DETECTION.md](DETECTION.md).

The ML test-suite (`ml/tests/`) fails loudly if the sample CSV or synthetic
generator drifts from the trained feature set.

## Hyperparameter search (`--search`)

Off by default so normal training stays fast. Opt in with a cross-validated
search over a small per-algorithm grid ([`ml/hpo.py`](../ml/hpo.py)):

```bash
# Randomized search, 30 candidates, 3-fold CV, optimizing macro-F1.
python -m ml.train --synthetic 50000 --search random --search-iter 30 --search-cv 3

# Exhaustive grid search.
python -m ml.train --data ml/data/cic-ids-2017 --profile cic2017 --search grid
```

The best estimator is refit and used; the search record (`mode`, `best_params`,
`best_score`, `n_candidates`) is persisted to `metadata.hpo`.

## Probability calibration (`--calibrate`)

A Random Forest's `predict_proba` isn't a well-calibrated probability, yet the
top value is exactly what the alert threshold compares against. Calibration wraps
the fitted pipeline in `CalibratedClassifierCV` so the **served confidence — and
therefore the alerting decision — uses calibrated probabilities**:

```bash
python -m ml.train --synthetic 50000 --calibrate sigmoid   # or: isotonic
```

Diagnostics are computed every run (even uncalibrated, as a baseline) and stored
in `metadata.calibration`:

- `method` / `calibrated`
- `brier_score` — multiclass Brier (lower is better; 0 is perfect)
- `reliability_curve` — binned confidence vs. empirical accuracy

The backend surfaces `calibrated` on the dashboard model panel.

## Artifact metadata contract

Every run writes `ml/artifacts/<version>/metadata.json` (mirrored to `latest/`)
with, in addition to the existing fields:

```jsonc
{
  "profile": "cic2017",
  "expected_feature_coverage": 0.8,
  "feature_coverage": { "n_features": 78, "expected": 0.8 },
  "hpo": { "mode": "random", "best_score": 0.94, "best_params": { ... } },
  "calibration": {
    "method": "sigmoid", "calibrated": true,
    "brier_score": 0.031,
    "reliability_curve": { "mean_confidence": [...], "accuracy": [...], "count": [...] }
  }
}
```

## CLI flags added

| Flag                       | Default | Notes                                                        |
| -------------------------- | ------- | ------------------------------------------------------------ |
| `--profile`                | `auto`  | `auto` \| `synthetic` \| `cic2017`.                          |
| `--search`                 | `none`  | `none` \| `random` \| `grid`.                                |
| `--search-iter`            | `20`    | Candidates for random search.                                |
| `--search-cv`              | `3`     | CV folds for the search.                                     |
| `--calibrate`              | `none`  | `none` \| `sigmoid` \| `isotonic`.                           |
| `--calibrate-cv`           | `3`     | CV folds for calibration.                                    |
| `--min-feature-coverage`   | `0.8`   | Stored as `expected_feature_coverage`.                       |

See [MODEL_LIFECYCLE.md](MODEL_LIFECYCLE.md) for activating/rolling back trained
versions and shadow-evaluating a candidate before promoting it.
