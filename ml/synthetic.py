"""Generate synthetic CIC-IDS2017-like flow records for demos and CI.

The goal is *not* fidelity to real attack traffic — it's a deterministic source
of well-separated, multi-class data so the training pipeline can be exercised
end-to-end (and the model gets a high macro-F1) without anyone needing to
download the full CIC-IDS2017 dataset.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd


FEATURES: Final[tuple[str, ...]] = (
    "flow_duration",
    "total_fwd_packets",
    "total_backward_packets",
    "total_length_of_fwd_packets",
    "total_length_of_bwd_packets",
    "fwd_packet_length_mean",
    "bwd_packet_length_mean",
    "flow_bytes/s",
    "flow_packets/s",
    "flow_iat_mean",
    "flow_iat_std",
    "fwd_iat_mean",
    "bwd_iat_mean",
    "packet_length_mean",
    "packet_length_std",
    "fin_flag_count",
    "syn_flag_count",
    "rst_flag_count",
    "psh_flag_count",
    "ack_flag_count",
    "average_packet_size",
)


# Per-class center vectors (in feature order). Real CIC-IDS2017 values are far
# more spread out than these, but the relative magnitudes are representative.
CLASS_CENTERS: Final[dict[str, np.ndarray]] = {
    "BENIGN": np.array(
        [
            1500.0,
            12.0,
            14.0,
            1800.0,
            5000.0,
            150.0,
            350.0,
            4800.0,
            18.0,
            220.0,
            320.0,
            110.0,
            220.0,
            250.0,
            90.0,
            0.5,
            1.2,
            0.1,
            1.0,
            8.0,
            280.0,
        ]
    ),
    "DDoS": np.array(
        [
            32.0,
            4.0,
            0.5,
            240.0,
            12.0,
            60.0,
            8.0,
            8500.0,
            135.0,
            8.0,
            18.0,
            6.0,
            22.0,
            60.0,
            22.0,
            0.1,
            4.5,
            0.0,
            4.5,
            5.0,
            64.0,
        ]
    ),
    "BruteForce": np.array(
        [
            55.0,
            3.0,
            0.5,
            140.0,
            8.0,
            46.0,
            10.0,
            2700.0,
            55.0,
            22.0,
            32.0,
            11.0,
            33.0,
            46.0,
            18.0,
            0.1,
            3.2,
            0.0,
            3.2,
            3.5,
            50.0,
        ]
    ),
    "PortScan": np.array(
        [
            820.0,
            9.0,
            7.0,
            1320.0,
            2840.0,
            146.0,
            405.0,
            5100.0,
            19.5,
            105.0,
            155.0,
            200.0,
            155.0,
            275.0,
            130.0,
            0.2,
            1.0,
            0.0,
            2.0,
            7.0,
            275.0,
        ]
    ),
}

DEFAULT_WEIGHTS: Final[dict[str, float]] = {
    "BENIGN": 0.60,
    "DDoS": 0.15,
    "BruteForce": 0.13,
    "PortScan": 0.12,
}


def generate(
    n_rows: int,
    *,
    random_state: int = 42,
    weights: dict[str, float] | None = None,
    nan_rate: float = 0.01,
    inf_rate: float = 0.001,
) -> pd.DataFrame:
    """Return a DataFrame with ``len(FEATURES)`` numeric columns and a ``label``."""
    if n_rows <= 0:
        raise ValueError("n_rows must be positive")
    weights = weights or DEFAULT_WEIGHTS
    if abs(sum(weights.values()) - 1.0) > 1e-3:
        raise ValueError("class weights must sum to 1.0")

    rng = np.random.default_rng(random_state)
    chunks: list[pd.DataFrame] = []

    for cls, weight in weights.items():
        cls_n = max(int(round(n_rows * weight)), 1)
        center = CLASS_CENTERS[cls]
        # Multiplicative log-normal noise — keeps values non-negative and
        # produces the heavy-tailed look real flow features have.
        noise = rng.normal(loc=0.0, scale=0.30, size=(cls_n, len(FEATURES)))
        values = center * np.exp(noise)

        # Sprinkle missing values + infinities so the cleaner does real work.
        if nan_rate > 0:
            mask = rng.random((cls_n, len(FEATURES))) < nan_rate
            values[mask] = np.nan
        if inf_rate > 0:
            mask = rng.random((cls_n, len(FEATURES))) < inf_rate
            values[mask] = np.inf

        frame = pd.DataFrame(values, columns=list(FEATURES))
        frame["label"] = cls
        chunks.append(frame)

    df = pd.concat(chunks, ignore_index=True)
    return df.sample(frac=1.0, random_state=random_state).reset_index(drop=True)


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic CIC-IDS2017-like flows.")
    parser.add_argument("--rows", type=int, default=50_000)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--output", type=Path, required=True, help="Output CSV path.")
    args = parser.parse_args()

    df = generate(args.rows, random_state=args.random_state)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)
    print(f"Wrote {len(df)} rows to {args.output}")


if __name__ == "__main__":
    _cli()
