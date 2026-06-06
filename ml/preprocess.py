"""Cleaning and feature selection for CIC-IDS2017-style frames."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.feature_list import EXCLUDED_COLUMNS


def clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Drop duplicate rows, replace ±inf with NaN, drop rows missing a label."""
    df = df.replace([np.inf, -np.inf], np.nan)
    if "label" in df.columns:
        df["label"] = df["label"].astype(str).str.strip()
        df = df[df["label"] != ""]
        df = df.dropna(subset=["label"])
    return df.drop_duplicates(ignore_index=True)


def select_feature_columns(df: pd.DataFrame) -> list[str]:
    """Return ordered numeric feature columns, excluding metadata fields."""
    features: list[str] = []
    for col in df.columns:
        if col in EXCLUDED_COLUMNS:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            features.append(col)
    return features


def build_xy(
    df: pd.DataFrame,
    *,
    label_col: str = "label",
    feature_order: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """Return ``(X, y)``.

    If ``feature_order`` is provided, X is built in exactly that order with
    missing columns filled as NaN — this is how the inference path keeps the
    feature vector aligned with what the model was trained on.
    """
    if label_col not in df.columns:
        raise ValueError(f"DataFrame missing required label column: {label_col!r}")

    if feature_order is None:
        feature_order = select_feature_columns(df)
        if not feature_order:
            raise ValueError("No numeric feature columns found.")

    X = pd.DataFrame(index=df.index)
    for col in feature_order:
        X[col] = df[col] if col in df.columns else np.nan

    y = df[label_col].astype(str).str.strip()
    return X, y
