"""Load CIC-IDS2017-style data from a file or directory of CSV/Parquet files."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.feature_list import apply_column_aliases, normalize_column

# Extensions we know how to read. Parquet covers the popular cleaned mirrors of
# CIC-IDS2017 (e.g. Kaggle's ``dhoogla/cicids2017``), which ship .parquet rather
# than CSV; reading it needs a parquet engine (``pip install pyarrow``).
_SUPPORTED_SUFFIXES = (".csv", ".parquet")


def load_path(path: Path | str) -> pd.DataFrame:
    """Load a single CSV/Parquet file, or every supported file under a directory."""
    p = Path(path)
    if p.is_file():
        return _load_file(p)
    if p.is_dir():
        files = sorted(f for f in p.rglob("*") if f.suffix.lower() in _SUPPORTED_SUFFIXES)
        if not files:
            raise FileNotFoundError(f"No CSV or Parquet files under {p}")
        frames = [_load_file(f) for f in files]
        return pd.concat(frames, ignore_index=True, copy=False)
    raise FileNotFoundError(f"Path not found: {p}")


def _load_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        # Cleaned mirrors already carry tidy column names; normalize anyway so the
        # downstream feature/label lookup is format-agnostic.
        df = pd.read_parquet(path)
    else:
        # CIC-IDS2017 CSVs use UTF-8 with BOM and have stray leading whitespace in
        # column names; ``utf-8-sig`` plus column normalization handles both.
        df = pd.read_csv(path, low_memory=False, encoding="utf-8-sig")
    # Normalize headers, then fold mirror-specific column names onto the
    # canonical schema so canonical-feature training works across CIC mirrors.
    df.columns = apply_column_aliases([normalize_column(c) for c in df.columns])
    return df
