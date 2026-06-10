# SentinelAI — ML training pipeline

Offline training pipeline for the Detection Agent. Reads CIC-IDS2017-style CSVs
(or generates synthetic ones), trains an `sklearn.pipeline.Pipeline` containing
a `SimpleImputer` and a baseline classifier, and writes versioned artifacts the
backend can `joblib.load` at inference time.

## Stack

- **Algorithm:** `RandomForestClassifier` (default) — robust to unscaled features,
  exposes `feature_importances_` for the Investigation Agent. `--algorithm
  gradient_boosting` swaps in `GradientBoostingClassifier`.
- **Preprocessing:** in-pipeline `SimpleImputer(strategy="median")`. NaN/±Inf
  are pre-cleaned in the dataframe; the imputer handles whatever survives.
- **Label handling:** `sklearn.preprocessing.LabelEncoder`. The class array is
  persisted to `metadata.json` so the backend can decode integer predictions.
- **Reproducibility:** every run is parameterised by `--random-state` and the
  full training params are recorded in `metadata.json`.

## Layout

```
ml/
├── pyproject.toml
├── __init__.py
├── feature_list.py    canonical column normalization + exclusion set
├── data_loader.py     CSV/Parquet loading (file or directory)
├── preprocess.py      cleaning, feature selection, X/y construction
├── pipeline.py        sklearn Pipeline factory (RF | GB)
├── metrics.py         precision/recall/F1 + confusion matrix
├── artifacts.py       versioned save/load + ``latest/`` mirror
├── synthetic.py       CIC-IDS2017-like data generator (CLI + import)
├── train.py           training CLI
├── evaluate.py        evaluation CLI
├── notebooks/
└── artifacts/
    ├── latest/        copy of the most recent training run
    └── v<timestamp>/  every historical run
```

## Install

```bash
cd ml
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

This installs every dep (`numpy`, `pandas`, `scikit-learn`, `joblib`, `pyarrow`)
and registers two console scripts:

| Command                | Equivalent                            |
| ---------------------- | ------------------------------------- |
| `sentinelai-train`     | `python -m ml.train`                  |
| `sentinelai-evaluate`  | `python -m ml.evaluate`               |

All `python -m ml.*` invocations run from the **project root** (the directory
that contains `ml/`).

## Quick start — synthetic data

```bash
# 50k synthetic rows, ~10 seconds end-to-end on a laptop
python -m ml.train --synthetic 50000
```

Output (truncated):

```
Generating 50000 synthetic rows
Rows after cleaning: 49823
Using 21 features
Classes (4): ['BENIGN', 'BruteForce', 'DDoS', 'PortScan']
Split sizes — train=34876 val=7473 test=7474
Fitting random_forest ...
Validation: precision=0.998 recall=0.998 f1=0.998
Test:       precision=0.998 recall=0.998 f1=0.998
Saved artifacts to /…/ml/artifacts/v20260520-101410
Refreshed latest pointer at /…/ml/artifacts/latest
```

## Train on CIC-IDS2017

1. Download the dataset from <https://www.unb.ca/cic/datasets/ids-2017.html>.
2. Drop the day-by-day CSVs under `ml/data/cic-ids-2017/`. Raw files are
   gitignored.
3. Train with the `cic2017` profile (folds attack sub-labels into coarse families):

   ```bash
   python -m ml.train --data ml/data/cic-ids-2017 --profile cic2017
   ```

The loader tolerates the CIC-IDS2017 column-name quirks (UTF-8 BOM, leading
spaces, mixed case) — they're normalized to `snake_case` so trained feature
names match what the backend ingestor produces.

See **[docs/ML_TRAINING.md](../docs/ML_TRAINING.md)** for the full real-data
workflow, dataset profiles, hyperparameter search, and calibration.

## Hyperparameter search & calibration (optional)

Both are off by default so normal training stays fast.

```bash
# Cross-validated search over a small grid (random or grid); best params used + recorded.
python -m ml.train --synthetic 50000 --search random --search-iter 30

# Probability calibration — the served confidence (hence the alert threshold
# decision) then uses calibrated probabilities. Brier score + reliability curve
# are recorded either way.
python -m ml.train --synthetic 50000 --calibrate sigmoid
```

## Feature parity (train ↔ serve)

The synthetic generator and the bundled sample CSV share **one canonical feature
set**, so a synthetic-trained model gets full feature coverage on the sample.
Regenerate the sample (all features + metadata columns) with:

```bash
python -m ml.synthetic --sample --output backend/data/samples/sample_flows.csv
```

Each model records `expected_feature_coverage`; the backend warns (or fails) when
an inference batch is missing too many trained features. The `ml/tests/` suite
fails if the sample CSV or generator drifts from the trained feature set.

## Evaluate a saved model

```bash
python -m ml.evaluate \
    --model ml/artifacts/latest \
    --data  ml/data/holdout.csv
```

Prints classification metrics + confusion matrix to stdout and optionally to a
file via `--output results.json`. Rows with labels the model wasn't trained on
are dropped with a warning.

## Generate synthetic data without training

```bash
python -m ml.synthetic --rows 100000 --output ml/data/synthetic_flows.csv
```

## Artifact contract

Every training run produces a directory with four files:

```
ml/artifacts/<version>/
├── model.joblib           sklearn Pipeline: SimpleImputer → classifier
├── metadata.json          name, version, algorithm, classes, feature_order, training params, metrics summary, baseline, profile, expected_feature_coverage, hpo, calibration
├── metrics.json           validation + test scalar/per-class metrics
└── confusion_matrix.json  matrices for validation + test
```

`ml/artifacts/latest/` is a copy of the most recent run so the backend can
default to `<root>/latest/` when no `model_versions` DB row has been activated.

### Drift baseline (`metadata.baseline`)

To support backend **drift monitoring**, `metadata.json` carries a `baseline`
block computed from the training split (`ml/baseline.py`):

```jsonc
"baseline": {
  "version": 1,
  "sample_count": 36000,
  "n_bins": 10,
  "class_distribution": { "BENIGN": 0.71, "DDoS": 0.07, ... },   // proportions
  "features": {
    "flow_duration": {
      "mean": 1487.3, "std": 902.1,
      "bin_edges": [ ... 11 quantile edges ... ],   // 10 bins
      "bin_props": [ ... 10 proportions summing to 1 ... ]
    },
    ...
  }
}
```

The backend buckets recent traffic into these `bin_edges` and computes a PSI
against `bin_props` per feature (plus a PSI over the prediction mix). The
bucketing convention in `ml.baseline.bin_props` must match the backend's
`drift_service.bucket_props` exactly. **Artifacts trained before this block
existed are handled gracefully — the backend reports drift "unavailable".**
Constant/degenerate features (fewer than two distinct quantile edges) are
omitted from the baseline.

### How the backend will load it

```python
import joblib, json, numpy as np, pandas as pd

bundle_dir = Path("ml/artifacts/latest")
pipeline = joblib.load(bundle_dir / "model.joblib")
metadata = json.loads((bundle_dir / "metadata.json").read_text())

classes        = metadata["classes"]         # ["BENIGN", "DDoS", ...]
feature_order  = metadata["feature_order"]   # ["flow_duration", ...]

def predict(event_features: dict[str, float]) -> tuple[str, float]:
    """``event_features`` comes straight from ``network_events.features``."""
    row = pd.DataFrame(
        [[event_features.get(c, np.nan) for c in feature_order]],
        columns=feature_order,
    )
    proba = pipeline.predict_proba(row)[0]
    idx = int(np.argmax(proba))
    return classes[idx], float(proba[idx])
```

The Detection Agent in Phase 3 will use exactly this contract.

## CLI flags reference

`python -m ml.train --help`

| Flag                | Default                                | Notes                                                  |
| ------------------- | -------------------------------------- | ------------------------------------------------------ |
| `--data`            | —                                      | CSV file or directory of CSVs (mutually exclusive with `--synthetic`). |
| `--synthetic`       | —                                      | Generate N synthetic rows instead.                     |
| `--output`          | `ml/artifacts/<version>`               | Output directory.                                      |
| `--algorithm`       | `random_forest`                        | Or `gradient_boosting`.                                |
| `--name`            | `sentinelai-detection`                 | Used in `metadata.json`.                               |
| `--profile`         | `auto`                                 | `auto` \| `synthetic` \| `cic2017` label handling.     |
| `--search`          | `none`                                 | `none` \| `random` \| `grid` hyperparameter search.    |
| `--search-iter`     | `20`                                   | Candidates for `--search random`.                      |
| `--search-cv`       | `3`                                    | CV folds for the search.                               |
| `--calibrate`       | `none`                                 | `none` \| `sigmoid` \| `isotonic` probability calibration. |
| `--calibrate-cv`    | `3`                                    | CV folds for calibration.                              |
| `--min-feature-coverage` | `0.8`                             | Stored as `expected_feature_coverage`.                 |
| `--test-size`       | `0.15`                                 | Fraction held out for test.                            |
| `--val-size`        | `0.15`                                 | Fraction held out for validation.                      |
| `--max-samples`     | unset                                  | Subsample after cleaning, for fast iteration.          |
| `--random-state`    | `42`                                   | Reproducibility seed.                                  |
| `--n-estimators`    | `200`                                  | Trees in RF / GB.                                      |
| `--no-latest`       | off                                    | Skip refreshing `ml/artifacts/latest/`.                |
| `--log-level`       | `INFO`                                 | `DEBUG`/`INFO`/`WARNING`/`ERROR`.                      |

## Notes & assumptions

- **CIC-IDS2017 class imbalance is real.** `class_weight="balanced"` on the
  Random Forest plus stratified splits handle it for the baseline; if you bring
  in your own dataset, expect to tune this.
- **Feature set is data-driven, not hand-coded.** Whatever numeric columns are
  present (after excluding metadata fields like IPs/ports/timestamps/label)
  become features. The list is captured in `metadata.json` so inference can
  rebuild the same vector.
- **No XGBoost / LightGBM yet.** Both would add a heavy native dep that the
  course-project environment doesn't need. Easy to add later by adding a third
  branch to `pipeline.build_pipeline`.
- **`ml/artifacts/` is mounted read-only into the backend container.** Anything
  the training pipeline writes here is immediately visible at `/app/ml_artifacts/`
  inside the running backend.
