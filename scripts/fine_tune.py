#!/usr/bin/env python3
"""
Incremental fine-tuning: warm-start XGBoost on new race data only.

Much faster than a full retrain (~1-2 min vs ~15 min). Uses XGBoost's
native warm-start (xgb_model parameter) to add trees for new data while
mixing in a historical replay buffer to prevent overfitting.

Usage:
  python scripts/fine_tune.py                    # auto-detect new data since last train
  python scripts/fine_tune.py --since 2026-04-01 # explicit date cutoff
  python scripts/fine_tune.py --min-stages 3     # require at least 3 new stages
  python scripts/fine_tune.py --dry-run           # show what would happen, don't train

Suggests a full retrain (scripts/train.py) after 7 fine-tunes.
"""

import os
import sys
import json
import logging
import pickle
import shutil
import time
from datetime import datetime

# Thread safety on macOS
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, roc_auc_score, brier_score_loss, log_loss

from data.scraper import get_db
from data.builder import build_pairs_sampled
from features.pipeline import build_feature_matrix
from models.benchmark import time_based_split

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "models", "trained")
META_PATH = os.path.join(MODELS_DIR, "training_meta.json")

# Fine-tuning hyperparameters
FT_N_ESTIMATORS = 50       # additional trees per fine-tune
FT_LEARNING_RATE = 0.01    # lower LR to preserve existing knowledge
REPLAY_RATIO = 3.0         # replay 3x as many historical pairs as new pairs
MIN_STAGES_DEFAULT = 3     # minimum new stages before fine-tuning
MAX_FINE_TUNES = 7         # suggest full retrain after this many


def load_training_meta() -> dict:
    """Load or create training metadata."""
    if os.path.exists(META_PATH):
        with open(META_PATH) as f:
            return json.load(f)
    return {
        "last_full_train": None,
        "last_fine_tune": None,
        "fine_tune_count": 0,
        "last_data_date": None,
    }


def save_training_meta(meta: dict):
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)


def backup_models():
    """Backup current model files before overwriting."""
    backup_dir = os.path.join(MODELS_DIR, "backup")
    os.makedirs(backup_dir, exist_ok=True)
    for fname in ["XGBoost.pkl", "CalibratedXGBoost.pkl"]:
        src = os.path.join(MODELS_DIR, fname)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(backup_dir, fname))
    log.info(f"Backed up models to {backup_dir}")


def get_latest_stage_date() -> str:
    """Get the most recent stage date in the database."""
    conn = get_db()
    row = conn.execute("""
        SELECT MAX(s.date) as max_date
        FROM stages s
        JOIN results r ON r.stage_url = s.url
        WHERE s.date IS NOT NULL
    """).fetchone()
    conn.close()
    return row["max_date"] if row else None


def count_stages_since(since_date: str) -> int:
    """Count how many stages have results since a given date."""
    conn = get_db()
    row = conn.execute("""
        SELECT COUNT(DISTINCT s.url) as cnt
        FROM stages s
        JOIN results r ON r.stage_url = s.url
        WHERE s.date >= ?
    """, (since_date,)).fetchone()
    conn.close()
    return row["cnt"]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Incremental fine-tune of XGBoost model")
    parser.add_argument("--since", type=str, default=None,
                        help="Only use data from this date onward (YYYY-MM-DD)")
    parser.add_argument("--min-stages", type=int, default=MIN_STAGES_DEFAULT,
                        help=f"Minimum new stages required (default: {MIN_STAGES_DEFAULT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without training")
    parser.add_argument("--force", action="store_true",
                        help="Skip minimum stage check")
    args = parser.parse_args()

    t0 = time.time()
    meta = load_training_meta()

    # Determine since_date
    since_date = args.since
    if not since_date:
        since_date = meta.get("last_data_date")
        if not since_date:
            log.error("No --since date provided and no training metadata found. "
                      "Run scripts/train.py for a full initial train first.")
            sys.exit(1)

    # Check how many new stages are available
    n_new_stages = count_stages_since(since_date)
    latest_date = get_latest_stage_date()
    log.info(f"Fine-tune since: {since_date}")
    log.info(f"New stages available: {n_new_stages}")
    log.info(f"Latest data date: {latest_date}")

    if meta["fine_tune_count"] >= MAX_FINE_TUNES:
        log.warning(f"⚠️  {meta['fine_tune_count']} fine-tunes since last full retrain. "
                    f"Consider running: python scripts/train.py")

    if n_new_stages < args.min_stages and not args.force:
        log.info(f"Only {n_new_stages} new stages (need {args.min_stages}). "
                 f"Use --force to override or wait for more data.")
        return

    if args.dry_run:
        log.info("[DRY RUN] Would fine-tune with the above data. Exiting.")
        return

    # Load existing model artifacts
    xgb_path = os.path.join(MODELS_DIR, "XGBoost.pkl")
    scaler_path = os.path.join(MODELS_DIR, "scaler.pkl")
    features_path = os.path.join(MODELS_DIR, "feature_names.json")

    for path in [xgb_path, scaler_path, features_path]:
        if not os.path.exists(path):
            log.error(f"Missing: {path}. Run scripts/train.py first.")
            sys.exit(1)

    with open(xgb_path, "rb") as f:
        base_xgb = pickle.load(f)
    with open(scaler_path, "rb") as f:
        scaler = pickle.load(f)
    with open(features_path) as f:
        feature_names = json.load(f)

    log.info(f"Loaded base XGBoost ({base_xgb.n_estimators} trees)")

    # === Step 1: Build new pairs ===
    log.info("\n=== Step 1: Building new H2H pairs ===")
    new_pairs = build_pairs_sampled(max_rank=50, pairs_per_stage=200,
                                    since_date=since_date)
    if len(new_pairs) == 0:
        log.error("No new pairs found. Nothing to fine-tune.")
        return
    log.info(f"New pairs: {len(new_pairs)}")

    # === Step 2: Build replay buffer from older data ===
    log.info("\n=== Step 2: Building replay buffer ===")
    replay_size = int(len(new_pairs) * REPLAY_RATIO)
    all_pairs = build_pairs_sampled(max_rank=50, pairs_per_stage=200)

    # Filter out the new pairs (only keep older data for replay)
    older_pairs = all_pairs[~all_pairs["stage_url"].isin(new_pairs["stage_url"].unique())]
    if len(older_pairs) > replay_size:
        older_pairs = older_pairs.sample(n=replay_size, random_state=42)
    log.info(f"Replay pairs: {len(older_pairs)}")

    # Combine new + replay
    combined_pairs = pd.concat([new_pairs, older_pairs], ignore_index=True)
    log.info(f"Combined training pairs: {len(combined_pairs)}")

    # === Step 3: Compute features ===
    log.info("\n=== Step 3: Computing features ===")
    feature_df = build_feature_matrix(combined_pairs)
    if len(feature_df) == 0:
        log.error("No features computed.")
        return

    X = feature_df.drop(columns=["label"])
    y = feature_df["label"]

    # Ensure feature columns match the trained model
    missing = set(feature_names) - set(X.columns)
    extra = set(X.columns) - set(feature_names)
    if missing:
        log.warning(f"Missing features (filling with 0): {missing}")
        for col in missing:
            X[col] = 0
    if extra:
        log.warning(f"Extra features (dropping): {extra}")
        X = X.drop(columns=list(extra))
    X = X[feature_names]

    X_scaled = pd.DataFrame(scaler.transform(X), columns=feature_names, index=X.index)
    log.info(f"Feature matrix: {X_scaled.shape[0]} rows × {X_scaled.shape[1]} columns")

    # === Step 4: Warm-start XGBoost ===
    log.info("\n=== Step 4: Warm-starting XGBoost ===")
    backup_models()

    # Create new XGBoost with same config but fewer trees and lower LR
    ft_xgb = xgb.XGBClassifier(
        n_estimators=FT_N_ESTIMATORS,
        max_depth=8,
        learning_rate=FT_LEARNING_RATE,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=10,
        reg_alpha=0.1,
        reg_lambda=1.0,
        random_state=42,
        eval_metric="logloss",
    )

    # Warm-start from existing booster
    ft_xgb.fit(X_scaled, y, xgb_model=base_xgb.get_booster(), verbose=False)
    total_trees = base_xgb.n_estimators + FT_N_ESTIMATORS
    log.info(f"Added {FT_N_ESTIMATORS} trees → {total_trees} total")

    # === Step 5: Recalibrate with prefit ===
    log.info("\n=== Step 5: Calibrating (prefit + sigmoid) ===")
    # Use sigmoid (Platt scaling) — more stable than isotonic on small samples
    cal_xgb = CalibratedClassifierCV(ft_xgb, method="sigmoid", cv="prefit")
    cal_xgb.fit(X_scaled, y)

    # === Step 6: Evaluate on 2025-2026 test set ===
    log.info("\n=== Step 6: Evaluating on test set ===")
    # Build full feature matrix for evaluation
    full_pairs = build_pairs_sampled(max_rank=50, pairs_per_stage=200)
    full_features = build_feature_matrix(full_pairs)

    conn = get_db()
    date_map = {}
    stages = conn.execute("SELECT url, date FROM stages").fetchall()
    for s in stages:
        date_map[s["url"]] = s["date"]
    conn.close()

    dates = full_pairs["stage_url"].map(date_map)
    dates = dates.iloc[:len(full_features)].reset_index(drop=True)

    X_full = full_features.drop(columns=["label"])
    y_full = full_features["label"]

    # Apply same feature alignment
    for col in missing:
        if col not in X_full.columns:
            X_full[col] = 0
    for col in extra:
        if col in X_full.columns:
            X_full = X_full.drop(columns=[col])
    X_full = X_full[[c for c in feature_names if c in X_full.columns]]
    if len(X_full.columns) < len(feature_names):
        for col in feature_names:
            if col not in X_full.columns:
                X_full[col] = 0
        X_full = X_full[feature_names]

    X_full_scaled = pd.DataFrame(scaler.transform(X_full),
                                  columns=feature_names, index=X_full.index)

    years = dates.apply(lambda d: int(str(d)[:4]) if pd.notna(d) else 2020)
    test_mask = years.isin([2025, 2026])

    if test_mask.sum() > 0:
        X_test = X_full_scaled[test_mask]
        y_test = y_full[test_mask]

        cal_prob = cal_xgb.predict_proba(X_test)[:, 1]
        cal_pred = (cal_prob >= 0.5).astype(int)

        ft_prob = ft_xgb.predict_proba(X_test)[:, 1]
        ft_pred = (ft_prob >= 0.5).astype(int)

        metrics = {
            "ft_accuracy": accuracy_score(y_test, ft_pred),
            "ft_roc_auc": roc_auc_score(y_test, ft_prob),
            "ft_brier": brier_score_loss(y_test, ft_prob),
            "cal_accuracy": accuracy_score(y_test, cal_pred),
            "cal_roc_auc": roc_auc_score(y_test, cal_prob),
            "cal_brier": brier_score_loss(y_test, cal_prob),
            "cal_log_loss": log_loss(y_test, cal_prob),
        }

        print("\n" + "=" * 60)
        print("FINE-TUNE EVALUATION (2025-2026 test set)")
        print("=" * 60)
        print(f"  XGBoost (raw):  Acc={metrics['ft_accuracy']:.4f}  "
              f"AUC={metrics['ft_roc_auc']:.4f}  Brier={metrics['ft_brier']:.4f}")
        print(f"  Calibrated:     Acc={metrics['cal_accuracy']:.4f}  "
              f"AUC={metrics['cal_roc_auc']:.4f}  Brier={metrics['cal_brier']:.4f}")
        print("=" * 60)
    else:
        log.warning("No 2025-2026 test data found — skipping evaluation")
        metrics = {}

    # === Step 7: Save models ===
    log.info("\n=== Step 7: Saving models ===")
    with open(os.path.join(MODELS_DIR, "XGBoost.pkl"), "wb") as f:
        pickle.dump(ft_xgb, f)
    with open(os.path.join(MODELS_DIR, "CalibratedXGBoost.pkl"), "wb") as f:
        pickle.dump(cal_xgb, f)
    log.info("Saved XGBoost.pkl and CalibratedXGBoost.pkl")

    # === Step 8: Update metadata ===
    meta["last_fine_tune"] = datetime.now().isoformat()
    meta["fine_tune_count"] = meta.get("fine_tune_count", 0) + 1
    meta["last_data_date"] = latest_date
    if metrics:
        meta["last_ft_metrics"] = {
            "cal_accuracy": round(metrics["cal_accuracy"], 4),
            "cal_roc_auc": round(metrics["cal_roc_auc"], 4),
            "cal_brier": round(metrics["cal_brier"], 4),
        }
    save_training_meta(meta)

    elapsed = time.time() - t0
    mins, secs = divmod(int(elapsed), 60)
    log.info(f"\n✅ Fine-tune complete in {mins}m {secs}s")
    log.info(f"  New stages: {n_new_stages} | Trees added: {FT_N_ESTIMATORS} | "
             f"Total trees: {total_trees}")
    if meta["fine_tune_count"] >= MAX_FINE_TUNES:
        log.warning(f"⚠️  {meta['fine_tune_count']} fine-tunes accumulated. "
                    f"Run a full retrain soon: python scripts/train.py")


if __name__ == "__main__":
    main()
