"""Train/serve feature-parity guards.

The bundled sample CSV and the synthetic generator must agree with the feature
set a model is trained on, otherwise inference silently runs on a half-empty
vector. These tests fail loudly if that alignment regresses.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.feature_list import is_feature_column, normalize_column
from ml.preprocess import build_xy, clean_frame, select_feature_columns
from ml.synthetic import FEATURE_DISPLAY_NAMES, FEATURES, generate_sample

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CSV = REPO_ROOT / "backend" / "data" / "samples" / "sample_flows.csv"


def test_display_headers_round_trip_to_feature_keys() -> None:
    # Every CIC-style header normalizes back to its canonical snake_case feature.
    for feature, header in FEATURE_DISPLAY_NAMES.items():
        assert normalize_column(header) == feature
    # And there is a display header for every feature.
    assert set(FEATURE_DISPLAY_NAMES) == set(FEATURES)


def test_generated_sample_covers_every_trained_feature() -> None:
    df = generate_sample(40)
    normalized = {normalize_column(c) for c in df.columns}
    missing = set(FEATURES) - normalized
    assert not missing, f"sample is missing trained features: {sorted(missing)}"


def test_bundled_sample_csv_aligns_with_synthetic_features() -> None:
    assert SAMPLE_CSV.is_file(), f"sample CSV not found at {SAMPLE_CSV}"
    df = pd.read_csv(SAMPLE_CSV)
    df.columns = [normalize_column(c) for c in df.columns]

    feature_cols = {c for c in df.columns if is_feature_column(c)}
    missing = set(FEATURES) - feature_cols
    assert not missing, (
        "the bundled sample CSV no longer carries every synthetic feature "
        f"(missing: {sorted(missing)}) — regenerate it with "
        "`python -m ml.synthetic --sample`"
    )


def test_sample_feeds_full_feature_vector_for_synthetic_model() -> None:
    # A model trained on synthetic data uses exactly FEATURES; the sample must
    # supply all of them so inference coverage is 100%.
    sample = pd.read_csv(SAMPLE_CSV)
    sample.columns = [normalize_column(c) for c in sample.columns]
    sample = clean_frame(sample)

    trained_features = list(FEATURES)
    X, _ = build_xy(sample, feature_order=trained_features)
    # build_xy fills missing columns with NaN; assert every trained feature has
    # at least one finite value in the sample (i.e. it was actually present).
    present = [c for c in trained_features if X[c].notna().any()]
    assert set(present) == set(trained_features)


def test_select_feature_columns_excludes_metadata() -> None:
    df = generate_sample(10)
    df.columns = [normalize_column(c) for c in df.columns]
    selected = select_feature_columns(df)
    assert "src_ip" not in selected
    assert "label" not in selected
    assert "flow_duration" in selected
