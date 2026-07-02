"""Export a demo CSV of *real* CIC-IDS2017 flows in the canonical schema.

The bundled ``sample_flows.csv`` used to be synthetic. A model trained on real
CIC-IDS2017 data classifies those synthetic magnitudes as all-BENIGN (the demo
shows no alerts). This module samples a labelled mix of **actual** flows, keeps
exactly the 21 canonical features (written with CIC-style display headers so the
backend ingestor round-trips them), and synthesizes the network-identity columns
the parquet mirror strips (timestamp / IPs / ports). The result: the real model
running live in the demo flags real DDoS / PortScan / BruteForce / WebAttack /
Bot flows, with 100% feature coverage.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from ml.data_loader import load_path
from ml.profiles import get_profile
from ml.synthetic import FEATURE_DISPLAY_NAMES, FEATURES

# A demo-friendly mix: enough BENIGN to be realistic, plus every attack family
# the canonical CIC model learns so the dashboard shows a spread of alerts.
DEFAULT_MIX: Final[dict[str, int]] = {
    "BENIGN": 20,
    "DDoS": 12,
    "PortScan": 10,
    "BruteForce": 10,
    "WebAttack": 5,
    "Bot": 3,
}

# Per-family destination ports / protocol for the synthesized identity columns —
# plausible values so the flows read like the attack they represent.
_DST_PORTS: Final[dict[str, list[int]]] = {
    "BENIGN": [443, 80, 53],
    "DDoS": [80, 443],
    "PortScan": [0, 22, 3389],
    "BruteForce": [22, 21],
    "WebAttack": [80, 443],
    "Bot": [8080, 443],
}


def _sanitize(value: object) -> float:
    """Real CIC rows carry ±inf (zero-duration flows) and NaN; coerce to finite."""
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return round(f, 4) if np.isfinite(f) else 0.0


def export_real_sample(
    data_dir: Path | str,
    *,
    mix: dict[str, int] | None = None,
    random_state: int = 7,
    profile_name: str = "cic2017",
) -> pd.DataFrame:
    """Return a demo DataFrame of real flows (canonical features + identity cols)."""
    mix = mix or DEFAULT_MIX
    df = load_path(data_dir)  # normalizes + applies canonical column aliases
    if "label" not in df.columns:
        raise ValueError("Loaded data has no 'label' column.")

    profile = get_profile(profile_name)
    df["label"] = df["label"].astype(str).map(profile.normalize_label)

    picked: list[pd.DataFrame] = []
    for family, n in mix.items():
        sub = df[df["label"] == family]
        if sub.empty:
            continue
        picked.append(sub.sample(n=min(n, len(sub)), random_state=random_state))
    if not picked:
        raise ValueError("None of the requested families were found in the data.")

    real = (
        pd.concat(picked, ignore_index=True)
        .sample(frac=1.0, random_state=random_state)
        .reset_index(drop=True)
    )

    rng = np.random.default_rng(random_state)
    base_ts = np.datetime64("2024-01-15T08:00:00")
    proto_col = real["protocol"] if "protocol" in real.columns else None

    rows: list[dict[str, object]] = []
    for i, row in real.iterrows():
        family = str(row["label"])
        proto = int(_sanitize(proto_col.iloc[i])) if proto_col is not None else 6
        rows.append(
            {
                "Timestamp": str(base_ts + np.timedelta64(int(i) * 4, "s")),
                "Source IP": f"192.168.1.{50 + int(i) % 200}",
                "Source Port": int(rng.integers(1024, 65535)),
                "Destination IP": "10.0.0.10" if family != "PortScan" else "10.0.0.20",
                "Destination Port": int(rng.choice(_DST_PORTS.get(family, [80]))),
                "Protocol": proto if proto in (6, 17) else 6,
                **{FEATURE_DISPLAY_NAMES[f]: _sanitize(row.get(f)) for f in FEATURES},
                "Label": family,
            }
        )
    return pd.DataFrame(rows)


def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Export a demo CSV of real CIC-IDS2017 flows (canonical schema)."
    )
    parser.add_argument("--data", type=Path, required=True, help="CIC-IDS2017 dir or file.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/data/samples/sample_flows.csv"),
        help="Where to write the demo CSV.",
    )
    parser.add_argument("--random-state", type=int, default=7)
    args = parser.parse_args()

    df = export_real_sample(args.data, random_state=args.random_state)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)
    print(f"Wrote {len(df)} real flows to {args.output}")
    print("Label mix:", df["Label"].value_counts().to_dict())


if __name__ == "__main__":
    _cli()
