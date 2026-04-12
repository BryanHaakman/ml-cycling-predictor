#!/usr/bin/env python3
"""
Training script for Azure ML compute.

Runs on AML compute instances/clusters. Accepts hyperparameters as CLI args,
logs metrics to MLflow, and registers the best model.

Usage (local test):
  python scripts/aml_train.py --n-estimators 300 --max-depth 8 --learning-rate 0.05

Usage (on AML via hyperdrive):
  Launched automatically by scripts/aml_sweep.py
"""

import os
import sys
import argparse
import logging
import pickle
import json
import time

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    accuracy_score, roc_auc_score, log_loss, brier_score_loss,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Try to import mlflow (available on AML, optional locally)
try:
    import mlflow
    import mlflow.sklearn
    HAS_MLFLOW = True
except ImportError:
    HAS_MLFLOW = False
    log.warning("mlflow not installed — metrics will only be printed")


def parse_args():
    parser = argparse.ArgumentParser(description="Train XGBoost for H2H prediction")

    # XGBoost hyperparameters
    parser.add_argument("--n-estimators", type=int, default=300)
    parser.add_argument("--max-depth", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--subsample", type=float, default=0.8)
    parser.add_argument("--colsample-bytree", type=float, default=0.8)
    parser.add_argument("--min-child-weight", type=int, default=10)
    parser.add_argument("--reg-alpha", type=float, default=0.1)
    parser.add_argument("--reg-lambda", type=float, default=1.0)
    parser.add_argument("--gamma", type=float, default=0.0)
    parser.add_argument("--scale-pos-weight", type=float, default=1.0)

    # Calibration
    parser.add_argument("--calibration-method", type=str, default="isotonic",
                        choices=["isotonic", "sigmoid"])
    parser.add_argument("--calibration-cv", type=int, default=5)

    # Data
    parser.add_argument("--split-mode", type=str, default="stratified",
                        choices=["stratified", "time"])
    parser.add_argument("--output-dir", type=str, default="outputs")

    return parser.parse_args()


def main():
    args = parse_args()
    t0 = time.time()

    os.makedirs(args.output_dir, exist_ok=True)

    # ── Build training data ───────────────────────────────────────────
    from data.scraper import get_db
    from data.builder import build_pairs_sampled
    from features.pipeline import build_feature_matrix
    from models.benchmark import time_based_split, stratified_stage_split

    log.info("Building H2H pairs...")
    pairs_df = build_pairs_sampled(max_rank=50, pairs_per_stage=200)
    log.info(f"Built {len(pairs_df)} pairs")

    log.info("Computing features...")
    feature_df = build_feature_matrix(pairs_df)
    log.info(f"Feature matrix: {feature_df.shape}")

    # Get dates and stage URLs for splitting
    conn = get_db()
    date_map = {s["url"]: s["date"] for s in conn.execute("SELECT url, date FROM stages").fetchall()}
    conn.close()

    dates = pairs_df["stage_url"].map(date_map).iloc[:len(feature_df)].reset_index(drop=True)
    stage_urls = pairs_df["stage_url"].iloc[:len(feature_df)].reset_index(drop=True)

    # Split
    if args.split_mode == "stratified":
        X_train, X_test, y_train, y_test = stratified_stage_split(feature_df, stage_urls)
    else:
        X_train, X_test, y_train, y_test = time_based_split(feature_df, dates)

    feature_names = list(X_train.columns)
    log.info(f"Train: {len(X_train)}, Test: {len(X_test)}, Features: {len(feature_names)}")

    # Scale
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # ── Train XGBoost ─────────────────────────────────────────────────
    log.info("Training XGBoost...")
    xgb_params = {
        "n_estimators": args.n_estimators,
        "max_depth": args.max_depth,
        "learning_rate": args.learning_rate,
        "subsample": args.subsample,
        "colsample_bytree": args.colsample_bytree,
        "min_child_weight": args.min_child_weight,
        "reg_alpha": args.reg_alpha,
        "reg_lambda": args.reg_lambda,
        "gamma": args.gamma,
        "scale_pos_weight": args.scale_pos_weight,
        "random_state": 42,
        "eval_metric": "logloss",
    }

    xgb_model = xgb.XGBClassifier(**xgb_params)
    xgb_model.fit(X_train_scaled, y_train, verbose=False)

    xgb_prob = xgb_model.predict_proba(X_test_scaled)[:, 1]
    xgb_pred = (xgb_prob >= 0.5).astype(int)

    xgb_metrics = {
        "xgb_accuracy": accuracy_score(y_test, xgb_pred),
        "xgb_roc_auc": roc_auc_score(y_test, xgb_prob),
        "xgb_log_loss": log_loss(y_test, xgb_prob),
        "xgb_brier_score": brier_score_loss(y_test, xgb_prob),
    }

    # ── Train Calibrated XGBoost ──────────────────────────────────────
    log.info("Training Calibrated XGBoost...")
    cal_xgb = CalibratedClassifierCV(
        xgb.XGBClassifier(**xgb_params),
        method=args.calibration_method,
        cv=args.calibration_cv,
    )
    cal_xgb.fit(X_train_scaled, y_train)

    cal_prob = cal_xgb.predict_proba(X_test_scaled)[:, 1]
    cal_pred = (cal_prob >= 0.5).astype(int)

    cal_metrics = {
        "accuracy": accuracy_score(y_test, cal_pred),
        "roc_auc": roc_auc_score(y_test, cal_prob),
        "log_loss": log_loss(y_test, cal_prob),
        "brier_score": brier_score_loss(y_test, cal_prob),
    }

    # Calibration accuracy at high confidence (70%+)
    high_conf_mask = cal_prob >= 0.70
    if high_conf_mask.sum() > 0:
        cal_metrics["high_conf_accuracy"] = accuracy_score(
            y_test[high_conf_mask], cal_pred[high_conf_mask]
        )
        cal_metrics["high_conf_count"] = int(high_conf_mask.sum())

    all_metrics = {**xgb_metrics, **cal_metrics}

    # ── Log to MLflow ─────────────────────────────────────────────────
    if HAS_MLFLOW:
        mlflow.log_params(xgb_params)
        mlflow.log_param("calibration_method", args.calibration_method)
        mlflow.log_param("calibration_cv", args.calibration_cv)
        mlflow.log_param("split_mode", args.split_mode)
        mlflow.log_param("n_train", len(X_train))
        mlflow.log_param("n_test", len(X_test))
        mlflow.log_param("n_features", len(feature_names))
        mlflow.log_metrics(all_metrics)

    # ── Print results ─────────────────────────────────────────────────
    elapsed = time.time() - t0
    log.info(f"Training complete in {elapsed:.0f}s")
    log.info(f"XGBoost:    acc={xgb_metrics['xgb_accuracy']:.4f}  AUC={xgb_metrics['xgb_roc_auc']:.4f}")
    log.info(f"Calibrated: acc={cal_metrics['accuracy']:.4f}  AUC={cal_metrics['roc_auc']:.4f}  "
             f"Brier={cal_metrics['brier_score']:.4f}")
    if "high_conf_accuracy" in cal_metrics:
        log.info(f"High-confidence (70%+): {cal_metrics['high_conf_accuracy']:.1%} "
                 f"({cal_metrics['high_conf_count']} picks)")

    # ── Save artifacts ────────────────────────────────────────────────
    with open(os.path.join(args.output_dir, "CalibratedXGBoost.pkl"), "wb") as f:
        pickle.dump(cal_xgb, f)
    with open(os.path.join(args.output_dir, "XGBoost.pkl"), "wb") as f:
        pickle.dump(xgb_model, f)
    with open(os.path.join(args.output_dir, "scaler.pkl"), "wb") as f:
        pickle.dump(scaler, f)
    with open(os.path.join(args.output_dir, "feature_names.json"), "w") as f:
        json.dump(feature_names, f)
    with open(os.path.join(args.output_dir, "sweep_metrics.json"), "w") as f:
        json.dump(all_metrics, f, indent=2)

    if HAS_MLFLOW:
        mlflow.sklearn.log_model(cal_xgb, "calibrated_xgboost")
        mlflow.log_artifacts(args.output_dir)

    log.info(f"Artifacts saved to {args.output_dir}/")


if __name__ == "__main__":
    main()
