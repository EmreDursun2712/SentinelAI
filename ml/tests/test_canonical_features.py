"""Guards for canonical-feature training and CIC mirror column aliases."""

from __future__ import annotations

import pandas as pd

from ml.feature_list import (
    CANONICAL_FEATURES,
    COLUMN_ALIASES,
    apply_column_aliases,
    normalize_column,
)
from ml.preprocess import build_xy
from ml.synthetic import FEATURES


def test_synthetic_features_are_the_canonical_set() -> None:
    # synthetic.FEATURES must be exactly CANONICAL_FEATURES, in the same order,
    # so the generator's CLASS_CENTERS stay positionally aligned.
    assert tuple(FEATURES) == tuple(CANONICAL_FEATURES)
    assert len(CANONICAL_FEATURES) == 21


def test_aliases_map_mirror_names_to_canonical() -> None:
    # The three columns that differ in the cleaned Kaggle mirror.
    mirror = ["fwd_packets_length_total", "bwd_packets_length_total", "avg_packet_size"]
    mapped = apply_column_aliases(mirror)
    assert mapped == [
        "total_length_of_fwd_packets",
        "total_length_of_bwd_packets",
        "average_packet_size",
    ]


def test_every_alias_target_is_a_canonical_feature() -> None:
    for target in COLUMN_ALIASES.values():
        assert target in CANONICAL_FEATURES


def test_alias_does_not_clobber_existing_canonical_column() -> None:
    # If both the mirror name and the canonical name are present, keep both
    # (don't create a duplicate canonical column).
    cols = ["avg_packet_size", "average_packet_size"]
    assert apply_column_aliases(cols) == ["avg_packet_size", "average_packet_size"]


def test_canonical_feature_order_forces_full_vector_from_partial_frame() -> None:
    # A real-mirror-style frame carrying the aliased names, once aliased, yields
    # all 21 canonical features (missing ones fill NaN) in canonical order.
    raw_cols = {
        "Flow Duration": [10.0],
        "Fwd Packets Length Total": [100.0],
        "Bwd Packets Length Total": [200.0],
        "Avg Packet Size": [50.0],
        "Label": ["BENIGN"],
    }
    df = pd.DataFrame(raw_cols)
    df.columns = apply_column_aliases([normalize_column(c) for c in df.columns])
    X, _ = build_xy(df, feature_order=list(CANONICAL_FEATURES))
    assert list(X.columns) == list(CANONICAL_FEATURES)
    # The three aliased columns are present (finite), the rest fill as NaN.
    assert X["total_length_of_fwd_packets"].notna().all()
    assert X["average_packet_size"].iloc[0] == 50.0
