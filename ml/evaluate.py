"""Evaluate a saved SentinelAI model against a labelled CSV / directory.

Loads the trained pipeline + metadata from ``--model``, aligns the input CSV
columns to the ``feature_order`` the model was trained on, runs inference, and
prints classification metrics + a confusion matrix.

Usage:

    python -m ml.evaluate --model ml/artifacts/latest --data ml/data/test_set.csv
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

from ml.artifacts import load_artifact_bundle
from ml.data_loader import load_path
from ml.metrics import compute_metrics, confusion_matrix_json
from ml.preprocess import build_xy, clean_frame

logger = logging.getLogger("sentinelai.ml.evaluate")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate a trained SentinelAI model on a labelled dataset.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--model",
        type=Path,
        required=True,
        help="Path to a saved model directory (e.g. ml/artifacts/latest).",
    )
    parser.add_argument(
        "--data",
        type=Path,
        required=True,
        help="Path to a labelled CSV file or directory of CSVs.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON file to write metrics into.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    return parser.parse_args(argv)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_logging(args.log_level)

    pipeline, metadata = load_artifact_bundle(args.model)
    classes: list[str] = metadata["classes"]
    feature_order: list[str] = metadata["feature_order"]
    logger.info(
        "Loaded model %s (version=%s, algorithm=%s, classes=%d, features=%d)",
        metadata.get("name"),
        metadata.get("version"),
        metadata.get("algorithm"),
        len(classes),
        len(feature_order),
    )

    df = load_path(args.data)
    df = clean_frame(df)
    logger.info("Evaluation rows: %d", len(df))

    if "label" not in df.columns:
        logger.error("Input data has no 'label' column — cannot evaluate.")
        return 2

    X, y_str = build_xy(df, feature_order=feature_order)
    y_str_values = y_str.to_numpy()

    # Map labels to the integer space the model was trained on, dropping rows
    # whose label is unknown to the model.
    class_to_idx = {c: i for i, c in enumerate(classes)}
    mask = np.array([label in class_to_idx for label in y_str_values])
    unknown = int((~mask).sum())
    if unknown:
        logger.warning(
            "Dropping %d row(s) whose label is not in the model's class set (%s)",
            unknown,
            sorted(set(y_str_values[~mask])),
        )

    X = X.loc[mask].reset_index(drop=True)
    y_str_values = y_str_values[mask]
    y_true = np.array([class_to_idx[label] for label in y_str_values])
    if len(y_true) == 0:
        logger.error("No rows remain after label alignment.")
        return 2

    y_pred = pipeline.predict(X)

    metrics = compute_metrics(y_true, y_pred, classes)
    confusion = confusion_matrix_json(y_true, y_pred, classes)

    print(json.dumps({"metrics": metrics, "confusion": confusion}, indent=2))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"metrics": metrics, "confusion": confusion}, indent=2))
        logger.info("Wrote results to %s", args.output)

    print(
        f"\nMacro-F1={metrics['f1_macro']:.4f}"
        f" Precision={metrics['precision_macro']:.4f}"
        f" Recall={metrics['recall_macro']:.4f}"
        f" Accuracy={metrics['accuracy']:.4f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
