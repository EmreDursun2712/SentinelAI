"""Load CIC-IDS2017-style data from a file or directory of CSVs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.feature_list import normalize_column


def load_path(path: Path | str) -> pd.DataFrame:
    """Load a single CSV or every ``*.csv`` under a directory, concatenated."""
    p = Path(path)
    if p.is_file():
        return _load_csv(p)
    if p.is_dir():
        csvs = sorted(p.rglob("*.csv"))
        if not csvs:
            raise FileNotFoundError(f"No CSV files under {p}")
        frames = [_load_csv(c) for c in csvs]
        return pd.concat(frames, ignore_index=True, copy=False)
    raise FileNotFoundError(f"Path not found: {p}")


def _load_csv(path: Path) -> pd.DataFrame:
    # CIC-IDS2017 files use UTF-8 with BOM and have stray leading whitespace in
    # column names; ``utf-8-sig`` plus column normalization handles both.
    df = pd.read_csv(path, low_memory=False, encoding="utf-8-sig")
    df.columns = [normalize_column(c) for c in df.columns]
    return df
