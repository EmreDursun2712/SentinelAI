"""Class-imbalance handling for training.

Real CIC-IDS2017 is extremely skewed — ~85% BENIGN and a long tail of rare
families (Heartbleed, Infiltration have a few dozen rows each). Training on the
raw distribution lets the majority classes dominate and buries macro-F1 on the
rare families. :func:`balance_classes` addresses this the conservative way: it
*caps* over-represented classes at ``max_per_class`` (random, seeded subsample)
while keeping **every** row of the rarer classes. Combined with the pipeline's
``class_weight="balanced"`` and ``--calibrate sigmoid``, this lifts rare-class
recall without inventing synthetic minority rows.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

BalanceMode = str  # "none" | "cap"


def class_counts(df: pd.DataFrame, label_col: str = "label") -> dict[str, int]:
    """Row count per label, largest first (JSON-friendly)."""
    counts = df[label_col].astype(str).value_counts()
    return {str(k): int(v) for k, v in counts.items()}


def drop_rare_classes(
    df: pd.DataFrame,
    *,
    min_count: int,
    label_col: str = "label",
) -> tuple[pd.DataFrame, list[str]]:
    """Drop classes with fewer than ``min_count`` rows. Returns ``(df, dropped)``.

    A stratified train/val/test split plus CV calibration needs a handful of rows
    per class; CIC-IDS2017's tiniest families (Heartbleed, Infiltration) have too
    few to evaluate reliably. ``min_count <= 0`` keeps everything.
    """
    if min_count <= 0:
        return df, []
    counts = df[label_col].astype(str).value_counts()
    keep = {str(k) for k, v in counts.items() if v >= min_count}
    dropped = sorted({str(k) for k in counts.index} - keep)
    if not dropped:
        return df, []
    filtered = df[df[label_col].astype(str).isin(keep)].reset_index(drop=True)
    return filtered, dropped


def balance_classes(
    df: pd.DataFrame,
    *,
    mode: BalanceMode = "cap",
    max_per_class: int,
    label_col: str = "label",
    random_state: int = 42,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return ``(balanced_df, report)``.

    ``mode="cap"`` downsamples any class with more than ``max_per_class`` rows to
    exactly ``max_per_class`` (seeded), leaving smaller classes fully intact.
    ``mode="none"`` is a no-op. The report records the before/after per-class
    counts so the training metadata can show what balancing did.
    """
    before = class_counts(df, label_col)
    if mode == "none" or max_per_class <= 0:
        return df, {
            "mode": "none",
            "max_per_class": max_per_class,
            "class_counts_before": before,
            "class_counts_after": before,
            "capped_classes": [],
        }
    if mode != "cap":
        raise ValueError(f"Unknown balance mode {mode!r}. Choices: none, cap")

    capped: list[str] = []
    parts: list[pd.DataFrame] = []
    for label, group in df.groupby(label_col, sort=False):
        if len(group) > max_per_class:
            group = group.sample(n=max_per_class, random_state=random_state)
            capped.append(str(label))
        parts.append(group)

    balanced = (
        pd.concat(parts, ignore_index=True)
        .sample(frac=1.0, random_state=random_state)
        .reset_index(drop=True)
    )
    report = {
        "mode": "cap",
        "max_per_class": max_per_class,
        "class_counts_before": before,
        "class_counts_after": class_counts(balanced, label_col),
        "capped_classes": capped,
    }
    return balanced, report
