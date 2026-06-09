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


# CIC-IDS2017-style display headers for each canonical feature. The backend
# ingestor's ``normalize_column`` maps these back to the snake_case keys above,
# so a CSV written with these headers aligns exactly with a model's
# ``feature_order``. Used to generate the bundled sample CSV; the round-trip
# (display header → normalized key → FEATURES) is asserted in the ML tests.
FEATURE_DISPLAY_NAMES: Final[dict[str, str]] = {
    "flow_duration": "Flow Duration",
    "total_fwd_packets": "Total Fwd Packets",
    "total_backward_packets": "Total Backward Packets",
    "total_length_of_fwd_packets": "Total Length of Fwd Packets",
    "total_length_of_bwd_packets": "Total Length of Bwd Packets",
    "fwd_packet_length_mean": "Fwd Packet Length Mean",
    "bwd_packet_length_mean": "Bwd Packet Length Mean",
    "flow_bytes/s": "Flow Bytes/s",
    "flow_packets/s": "Flow Packets/s",
    "flow_iat_mean": "Flow IAT Mean",
    "flow_iat_std": "Flow IAT Std",
    "fwd_iat_mean": "Fwd IAT Mean",
    "bwd_iat_mean": "Bwd IAT Mean",
    "packet_length_mean": "Packet Length Mean",
    "packet_length_std": "Packet Length Std",
    "fin_flag_count": "FIN Flag Count",
    "syn_flag_count": "SYN Flag Count",
    "rst_flag_count": "RST Flag Count",
    "psh_flag_count": "PSH Flag Count",
    "ack_flag_count": "ACK Flag Count",
    "average_packet_size": "Average Packet Size",
}


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


def generate_sample(n_rows: int = 60, *, random_state: int = 7) -> pd.DataFrame:
    """Return a small, demo-friendly frame with the full feature set + metadata.

    Unlike :func:`generate` (snake_case feature columns only, for training), this
    produces a realistic flow CSV: CIC-IDS2017-style display headers for **every**
    canonical feature, plus the network-identity columns the ingestor expects
    (timestamp / IPs / ports / protocol) and a ``Label``. Because it carries all
    of :data:`FEATURES`, a model trained on synthetic data gets 100% feature
    coverage when this sample is ingested — closing the train/serve gap.
    """
    if n_rows <= 0:
        raise ValueError("n_rows must be positive")
    rng = np.random.default_rng(random_state)
    base = generate(n_rows, random_state=random_state, nan_rate=0.0, inf_rate=0.0)
    base = base.head(n_rows).reset_index(drop=True)

    protocols = {"BENIGN": 6, "DDoS": 6, "BruteForce": 6, "PortScan": 6}
    dst_ports = {
        "BENIGN": [443, 80, 53],
        "DDoS": [80, 443],
        "BruteForce": [22, 21],
        "PortScan": [0],
    }
    base_ts = np.datetime64("2024-01-15T08:00:00")

    rows: list[dict[str, object]] = []
    for i, row in base.iterrows():
        label = str(row["label"])
        rows.append(
            {
                "Timestamp": str(base_ts + np.timedelta64(int(i) * 4, "s")),
                "Source IP": f"192.168.1.{50 + int(i) % 200}",
                "Source Port": int(rng.integers(1024, 65535)),
                "Destination IP": "10.0.0.10" if label != "PortScan" else "10.0.0.20",
                "Destination Port": int(rng.choice(dst_ports[label])),
                "Protocol": protocols[label],
                **{FEATURE_DISPLAY_NAMES[f]: round(float(row[f]), 2) for f in FEATURES},
                "Label": label,
            }
        )
    return pd.DataFrame(rows)


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic CIC-IDS2017-like flows.")
    parser.add_argument("--rows", type=int, default=50_000)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--output", type=Path, required=True, help="Output CSV path.")
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Write a small demo CSV (all features + metadata columns) instead of the "
        "training frame. Used to regenerate backend/data/samples/sample_flows.csv.",
    )
    args = parser.parse_args()

    if args.sample:
        df = generate_sample(
            args.rows if args.rows != 50_000 else 60, random_state=args.random_state
        )
    else:
        df = generate(args.rows, random_state=args.random_state)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)
    print(f"Wrote {len(df)} rows to {args.output}")


if __name__ == "__main__":
    _cli()
