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
from typing import TYPE_CHECKING

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

from ml import __version__
from ml.artifacts import make_version, save_artifacts, update_latest
from ml.baseline import compute_baseline
from ml.calibration import calibration_report, calibrate_pipeline
from ml.data_loader import load_path
from ml.feature_list import CANONICAL_FEATURES
from ml.hpo import run_search
from ml.metrics import compute_metrics, confusion_matrix_json
from ml.pipeline import build_pipeline
from ml.preprocess import build_xy, clean_frame
from ml.profiles import get_profile
from ml.sampling import balance_classes, drop_rare_classes
from ml.synthetic import generate as generate_synthetic

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger("sentinelai.ml.train")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train the SentinelAI intrusion-detection model.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--data", type=Path, help="Path to a CSV file or directory of CSVs.")
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
    parser.add_argument(
        "--profile",
        choices=("auto", "synthetic", "cic2017"),
        default="auto",
        help="Dataset profile — controls label normalization (see ml/profiles.py). "
        "Use 'cic2017' with real CIC-IDS2017 data.",
    )
    parser.add_argument(
        "--feature-set",
        choices=("full", "canonical"),
        default="full",
        help="Which columns become features. 'full' uses every numeric column "
        "(the real CIC-IDS2017 ~76-feature vector). 'canonical' restricts to the "
        "21-feature schema the demo CSV and backend share, so a model trained on "
        "real data serves the shipped sample with 100%% feature coverage.",
    )
    parser.add_argument(
        "--balance",
        choices=("none", "cap"),
        default="none",
        help="Class-imbalance handling. 'cap' downsamples over-represented classes "
        "to --max-per-class while keeping every rare-class row; pairs with "
        "class_weight='balanced' and --calibrate to lift rare-class macro-F1.",
    )
    parser.add_argument(
        "--max-per-class",
        type=int,
        default=20_000,
        help="Row cap per class when --balance cap is set.",
    )
    parser.add_argument(
        "--min-class-count",
        type=int,
        default=0,
        help="Drop classes with fewer than N rows before splitting (0 = keep all). "
        "Guards the stratified split + CV calibration against CIC's tiniest "
        "families (e.g. Heartbleed) that are too small to evaluate.",
    )
    parser.add_argument(
        "--search",
        choices=("none", "random", "grid"),
        default="none",
        help="Hyperparameter search mode. Default 'none' keeps training fast.",
    )
    parser.add_argument(
        "--search-iter",
        type=int,
        default=20,
        help="Candidates to sample for --search random.",
    )
    parser.add_argument("--search-cv", type=int, default=3, help="CV folds for the HPO search.")
    parser.add_argument(
        "--calibrate",
        choices=("none", "sigmoid", "isotonic"),
        default="none",
        help="Probability calibration. When set, the served confidence (and the "
        "alert threshold decision) uses calibrated probabilities.",
    )
    parser.add_argument(
        "--calibrate-cv", type=int, default=3, help="CV folds for probability calibration."
    )
    parser.add_argument(
        "--min-feature-coverage",
        type=float,
        default=0.8,
        help="Expected fraction of trained features present at inference time, "
        "recorded in metadata so the backend can warn on under-covered input.",
    )
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


def _load_data(args: argparse.Namespace) -> tuple[pd.DataFrame, str]:
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

    # Normalize labels per the dataset profile (e.g. fold CIC-IDS2017 attack
    # sub-labels into coarse families), then drop rows that map to empty.
    profile = get_profile(args.profile)
    df["label"] = df["label"].astype(str).map(profile.normalize_label)
    df = df[df["label"] != ""].reset_index(drop=True)
    logger.info("Applied '%s' label profile; rows: %d", profile.name, len(df))

    # Drop classes too small to split/evaluate (keep-all by default).
    df, dropped_classes = drop_rare_classes(df, min_count=args.min_class_count)
    if dropped_classes:
        logger.info(
            "Dropped %d class(es) below min-class-count=%d: %s",
            len(dropped_classes),
            args.min_class_count,
            dropped_classes,
        )

    # Class-imbalance handling (cap the majority, keep the rare tail) — applied
    # after label folding so the cap operates on final class names.
    df, balance_report = balance_classes(
        df, mode=args.balance, max_per_class=args.max_per_class, random_state=args.random_state
    )
    if args.balance != "none":
        logger.info(
            "Balanced classes (mode=%s, cap=%d); rows: %d; capped=%s",
            args.balance,
            args.max_per_class,
            len(df),
            balance_report["capped_classes"],
        )

    # 'canonical' pins the feature vector to the 21-column demo schema (missing
    # columns fill as NaN for the imputer); 'full' auto-selects every numeric col.
    forced_features = list(CANONICAL_FEATURES) if args.feature_set == "canonical" else None
    X, y_str = build_xy(df, feature_order=forced_features)
    feature_order = list(X.columns)
    logger.info("Using %d features (feature-set=%s)", len(feature_order), args.feature_set)

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

    # Optional hyperparameter search (fits internally, returns the best fitted
    # pipeline). Default is "none" so normal training stays fast.
    if args.search != "none":
        logger.info("Running %s hyperparameter search ...", args.search)
        pipeline, hpo_record = run_search(
            pipeline,
            X_train,
            y_train,
            algorithm=args.algorithm,
            mode=args.search,
            n_iter=args.search_iter,
            cv=args.search_cv,
            random_state=args.random_state,
        )
        logger.info(
            "HPO best macro-F1=%.4f params=%s",
            hpo_record.get("best_score", float("nan")),
            hpo_record.get("best_params"),
        )
    else:
        hpo_record = {"mode": "none"}
        logger.info("Fitting %s ...", args.algorithm)
        pipeline.fit(X_train, y_train)

    # Optional probability calibration. CalibratedClassifierCV re-fits a clone of
    # the (best) pipeline with internal CV, so the served predict_proba — and the
    # alert threshold decision that reads it — is calibrated.
    if args.calibrate != "none":
        logger.info("Calibrating probabilities (%s) ...", args.calibrate)
        pipeline = calibrate_pipeline(
            pipeline, X_train, y_train, method=args.calibrate, cv=args.calibrate_cv
        )

    val_pred = pipeline.predict(X_val)
    test_pred = pipeline.predict(X_test)

    # Calibration diagnostics are computed even when calibration is off, giving a
    # baseline Brier score + reliability curve (calibrated=False) to compare against.
    calibration = calibration_report(
        y_val, pipeline.predict_proba(X_val), classes, method=args.calibrate
    )
    logger.info(
        "Validation Brier=%.4f (calibrated=%s)",
        calibration["brier_score"],
        calibration["calibrated"],
    )

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
        "profile": profile.name,
        "feature_set": args.feature_set,
        # Before/after per-class counts from imbalance handling ({"mode": "none"}
        # when balancing is off) — makes the rare-class preservation auditable.
        "balance": balance_report,
        "min_class_count": args.min_class_count,
        "dropped_classes": dropped_classes,
        # Expected share of trained features present at inference time. The
        # backend warns when an inference batch falls below this (see
        # detection_service.assess_feature_coverage).
        "expected_feature_coverage": args.min_feature_coverage,
        "feature_coverage": {
            "n_features": len(feature_order),
            "expected": args.min_feature_coverage,
        },
        # Hyperparameter search record ({"mode": "none"} when not run).
        "hpo": hpo_record,
        # Calibration method + Brier score + reliability curve.
        "calibration": calibration,
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
        "baseline": compute_baseline(X_train, encoder.inverse_transform(y_train).tolist(), classes),
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
