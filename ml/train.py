"""Train the SentinelAI detection model.

Usage:

    # Synthetic data (fast smoke test):
    python -m ml.train --synthetic 50000

    # Real CIC-IDS2017 (point at the directory of CSVs):
    python -m ml.train --data ml/data/cic-ids-2017/

Outputs are written to ``ml/artifacts/<version>/`` and mirrored to
``ml/artifacts/latest/`` so the backend always finds a known-good version.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

from ml import __version__
from ml.artifacts import make_version, save_artifacts, update_latest
from ml.baseline import compute_baseline
from ml.data_loader import load_path
from ml.metrics import compute_metrics, confusion_matrix_json
from ml.pipeline import Algorithm, build_pipeline
from ml.preprocess import build_xy, clean_frame
from ml.synthetic import generate as generate_synthetic

logger = logging.getLogger("sentinelai.ml.train")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train the SentinelAI intrusion-detection model.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--data", type=Path, help="Path to a CSV file or directory of CSVs."
    )
    source.add_argument(
        "--synthetic",
        type=int,
        help="Generate N synthetic CIC-IDS2017-like rows instead of reading from disk.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: ml/artifacts/<timestamp_version>).",
    )
    parser.add_argument(
        "--algorithm",
        choices=("random_forest", "gradient_boosting"),
        default="random_forest",
    )
    parser.add_argument("--name", default="sentinelai-detection", help="Model name.")
    parser.add_argument("--test-size", type=float, default=0.15)
    parser.add_argument("--val-size", type=float, default=0.15)
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Subsample to at most this many rows post-clean (for fast iteration).",
    )
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument(
        "--n-estimators",
        type=int,
        default=200,
        help="Number of estimators for RF/GB.",
    )
    parser.add_argument(
        "--no-latest",
        action="store_true",
        help="Do not refresh ml/artifacts/latest/ with the new version.",
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


def _load_data(args: argparse.Namespace) -> tuple["pd.DataFrame", str]:
    import pandas as pd  # noqa: F401 — alias for return type

    if args.synthetic is not None:
        logger.info("Generating %d synthetic rows", args.synthetic)
        return (
            generate_synthetic(args.synthetic, random_state=args.random_state),
            f"synthetic:{args.synthetic}@rs{args.random_state}",
        )

    if args.data is None:
        raise ValueError("--data or --synthetic is required")
    logger.info("Loading data from %s", args.data)
    return load_path(args.data), str(args.data)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_logging(args.log_level)

    df, source = _load_data(args)
    logger.info("Raw rows loaded: %d (cols=%d)", len(df), len(df.columns))

    df = clean_frame(df)
    logger.info("Rows after cleaning: %d", len(df))

    if args.max_samples and len(df) > args.max_samples:
        df = df.sample(n=args.max_samples, random_state=args.random_state).reset_index(drop=True)
        logger.info("Subsampled to %d rows", len(df))

    if "label" not in df.columns:
        logger.error("Input data is missing a 'label' column.")
        return 2

    X, y_str = build_xy(df)
    feature_order = list(X.columns)
    logger.info("Using %d features", len(feature_order))

    encoder = LabelEncoder()
    y = encoder.fit_transform(y_str)
    classes: list[str] = encoder.classes_.tolist()
    logger.info("Classes (%d): %s", len(classes), classes)

    # Single split, then carve val out of train-pool.
    holdout_size = args.test_size + args.val_size
    if not 0 < holdout_size < 1:
        logger.error("test_size + val_size must be in (0, 1); got %s", holdout_size)
        return 2

    X_train, X_hold, y_train, y_hold = train_test_split(
        X, y, test_size=holdout_size, stratify=y, random_state=args.random_state
    )
    test_fraction_of_hold = args.test_size / holdout_size
    X_val, X_test, y_val, y_test = train_test_split(
        X_hold,
        y_hold,
        test_size=test_fraction_of_hold,
        stratify=y_hold,
        random_state=args.random_state,
    )
    logger.info(
        "Split sizes — train=%d val=%d test=%d",
        len(X_train),
        len(X_val),
        len(X_test),
    )

    pipeline = build_pipeline(
        algorithm=args.algorithm,
        random_state=args.random_state,
        n_estimators=args.n_estimators,
    )
    logger.info("Fitting %s ...", args.algorithm)
    pipeline.fit(X_train, y_train)

    val_pred = pipeline.predict(X_val)
    test_pred = pipeline.predict(X_test)

    val_metrics = compute_metrics(y_val, val_pred, classes)
    test_metrics = compute_metrics(y_test, test_pred, classes)
    confusion = {
        "validation": confusion_matrix_json(y_val, val_pred, classes),
        "test": confusion_matrix_json(y_test, test_pred, classes),
    }

    logger.info(
        "Validation: precision=%.4f recall=%.4f f1=%.4f",
        val_metrics["precision_macro"],
        val_metrics["recall_macro"],
        val_metrics["f1_macro"],
    )
    logger.info(
        "Test:       precision=%.4f recall=%.4f f1=%.4f",
        test_metrics["precision_macro"],
        test_metrics["recall_macro"],
        test_metrics["f1_macro"],
    )

    version = make_version()
    artifacts_root = Path("ml/artifacts")
    output_dir = args.output or (artifacts_root / version)

    metadata = {
        "name": args.name,
        "version": version,
        "pipeline_version": __version__,
        "algorithm": args.algorithm,
        "trained_at": datetime.now(UTC).isoformat(),
        "source": source,
        "random_state": args.random_state,
        "n_estimators": args.n_estimators,
        "training_params": {
            "test_size": args.test_size,
            "val_size": args.val_size,
            "max_samples": args.max_samples,
        },
        "dataset_sizes": {
            "train": int(len(X_train)),
            "validation": int(len(X_val)),
            "test": int(len(X_test)),
        },
        "metrics_summary": {
            "validation_f1_macro": val_metrics["f1_macro"],
            "test_f1_macro": test_metrics["f1_macro"],
            "validation_accuracy": val_metrics["accuracy"],
            "test_accuracy": test_metrics["accuracy"],
        },
        # Drift-monitoring baseline: per-feature quantile bins + means/stds and
        # the training class distribution. The backend compares recent traffic
        # against this; artifacts without it report drift "unavailable".
        "baseline": compute_baseline(
            X_train, encoder.inverse_transform(y_train).tolist(), classes
        ),
    }
    metrics_payload = {"validation": val_metrics, "test": test_metrics}

    save_artifacts(
        output_dir=output_dir,
        pipeline=pipeline,
        classes=classes,
        feature_order=feature_order,
        metadata=metadata,
        metrics=metrics_payload,
        confusion=confusion,
    )
    logger.info("Saved artifacts to %s", output_dir.resolve())

    if not args.no_latest:
        latest = update_latest(artifacts_root, output_dir)
        logger.info("Refreshed latest pointer at %s", latest.resolve())

    print(f"\nSaved model to {output_dir}")
    print(f"  validation macro-F1: {val_metrics['f1_macro']:.4f}")
    print(f"  test       macro-F1: {test_metrics['f1_macro']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
