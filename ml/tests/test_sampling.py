"""Class-balancing (cap majority, preserve rare) behavior."""

from __future__ import annotations

import pandas as pd

from ml.sampling import balance_classes, class_counts


def _frame() -> pd.DataFrame:
    rows = (
        [{"label": "BENIGN", "x": i} for i in range(1000)]
        + [{"label": "DDoS", "x": i} for i in range(300)]
        + [{"label": "Heartbleed", "x": i} for i in range(11)]
    )
    return pd.DataFrame(rows)


def test_cap_downsamples_majority_and_preserves_rare() -> None:
    df = _frame()
    balanced, report = balance_classes(df, mode="cap", max_per_class=200, random_state=7)
    counts = class_counts(balanced)
    assert counts["BENIGN"] == 200  # capped
    assert counts["DDoS"] == 200  # capped
    assert counts["Heartbleed"] == 11  # kept whole — below the cap
    assert set(report["capped_classes"]) == {"BENIGN", "DDoS"}
    assert report["class_counts_before"]["BENIGN"] == 1000


def test_cap_is_deterministic() -> None:
    df = _frame()
    a, _ = balance_classes(df, mode="cap", max_per_class=150, random_state=1)
    b, _ = balance_classes(df, mode="cap", max_per_class=150, random_state=1)
    pd.testing.assert_frame_equal(a, b)


def test_none_mode_is_a_noop() -> None:
    df = _frame()
    balanced, report = balance_classes(df, mode="none", max_per_class=10, random_state=7)
    assert len(balanced) == len(df)
    assert report["mode"] == "none"
    assert report["capped_classes"] == []
