#!/usr/bin/env python3
"""
Feature selection experiments: test whether pruning low-importance features
improves accuracy beyond the full 284-feature baseline.

Uses time-based split (test years 2025-2026) to match production benchmark.
Two ranking methods: XGBoost gain importance and permutation importance.
Tests top-N subsets with both raw XGBoost and CalibratedXGBoost.
"""

import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import logging
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, roc_auc_score, brier_score_loss
from sklearn.calibration import CalibratedClassifierCV
from sklearn.inspection import permutation_importance
import xgboost as xgb

from data.builder import build_pairs_sampled
from data.scraper import get_db
from features.pipeline import build_feature_matrix
from models.benchmark import time_based_split

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TOP_N_VALUES = [20, 30, 50, 80, 100, 120, 150, 200]


def get_xgb_model():
    """Return XGBoost with same hyperparams as production benchmark."""
    return xgb.XGBClassifier(
        n_estimators=300, max_depth=8, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        min_child_weight=10, reg_alpha=0.1, reg_lambda=1.0,
        random_state=42, eval_metric="logloss",
    )


def evaluate_subset(X_train, y_train, X_test, y_test, col_indices, use_calibrated=False):
    """Train and evaluate on a feature subset."""
    Xtr = X_train[:, col_indices]
    Xte = X_test[:, col_indices]

    scaler = StandardScaler()
    Xtr_s = scaler.fit_transform(Xtr)
    Xte_s = scaler.transform(Xte)

    if use_calibrated:
        model = CalibratedClassifierCV(get_xgb_model(), method="isotonic", cv=5)
    else:
        model = get_xgb_model()

    model.fit(Xtr_s, y_train, **({"verbose": False} if not use_calibrated else {}))
    probs = model.predict_proba(Xte_s)[:, 1]
    preds = (probs >= 0.5).astype(int)

    return {
        "accuracy": accuracy_score(y_test, preds),
        "roc_auc": roc_auc_score(y_test, probs),
        "brier": brier_score_loss(y_test, probs),
    }


def run_feature_selection():
    t0 = time.time()

    # Build data
    print("Building dataset (using cached features)...", flush=True)
    pairs = build_pairs_sampled(max_rank=50, pairs_per_stage=200)
    feat_df = build_feature_matrix(pairs)
    feature_names = [c for c in feat_df.columns if c != "label"]

    # Time-based split (same as train.py)
    conn = get_db()
    date_map = {}
    stages = conn.execute("SELECT url, date FROM stages").fetchall()
    for s in stages:
        date_map[s["url"]] = s["date"]
    conn.close()
    dates = pairs["stage_url"].map(date_map)
    dates = dates.iloc[:len(feat_df)].reset_index(drop=True)

    X_train, X_test, y_train, y_test = time_based_split(feat_df, dates)
    log.info(f"Train: {len(X_train)}, Test: {len(X_test)}, Features: {len(feature_names)}")

    X_train_np = X_train.values
    X_test_np = X_test.values
    y_train_np = y_train.values
    y_test_np = y_test.values

    # ── Phase 1: Baseline with all features ───────────────────────────────
    print("\n--- Phase 1: Baselines ---", flush=True)

    scaler_full = StandardScaler()
    Xtr_full = scaler_full.fit_transform(X_train_np)
    Xte_full = scaler_full.transform(X_test_np)

    # Train raw XGBoost for importance ranking
    xgb_full = get_xgb_model()
    xgb_full.fit(Xtr_full, y_train_np, verbose=False)
    xgb_probs = xgb_full.predict_proba(Xte_full)[:, 1]
    xgb_preds = (xgb_probs >= 0.5).astype(int)

    baseline_xgb = {
        "accuracy": accuracy_score(y_test_np, xgb_preds),
        "roc_auc": roc_auc_score(y_test_np, xgb_probs),
        "brier": brier_score_loss(y_test_np, xgb_probs),
    }
    print(f"  XGBoost baseline (all {len(feature_names)}): "
          f"acc={baseline_xgb['accuracy']:.4f} auc={baseline_xgb['roc_auc']:.4f} "
          f"brier={baseline_xgb['brier']:.4f}", flush=True)

    # CalibratedXGBoost baseline
    cal_full = CalibratedClassifierCV(get_xgb_model(), method="isotonic", cv=5)
    cal_full.fit(Xtr_full, y_train_np)
    cal_probs = cal_full.predict_proba(Xte_full)[:, 1]
    cal_preds = (cal_probs >= 0.5).astype(int)

    baseline_cal = {
        "accuracy": accuracy_score(y_test_np, cal_preds),
        "roc_auc": roc_auc_score(y_test_np, cal_probs),
        "brier": brier_score_loss(y_test_np, cal_probs),
    }
    print(f"  CalXGBoost baseline (all {len(feature_names)}): "
          f"acc={baseline_cal['accuracy']:.4f} auc={baseline_cal['roc_auc']:.4f} "
          f"brier={baseline_cal['brier']:.4f}", flush=True)

    # ── Phase 2: Get feature rankings ─────────────────────────────────────
    print("\n--- Phase 2: Feature rankings ---", flush=True)

    # Method 1: XGBoost gain importance
    gain_importance = xgb_full.feature_importances_
    gain_ranking = np.argsort(gain_importance)[::-1]
    print(f"  Top 10 by gain importance:")
    for i in range(10):
        idx = gain_ranking[i]
        print(f"    {i+1:2d}. {feature_names[idx]:45s} {gain_importance[idx]:.4f}")

    # Method 2: Permutation importance (more robust, accounts for correlations)
    print("\n  Computing permutation importance (may take ~60s)...", flush=True)
    perm_result = permutation_importance(
        xgb_full, Xte_full, y_test_np,
        n_repeats=10, random_state=42, scoring="roc_auc",
    )
    perm_importance = perm_result.importances_mean
    perm_ranking = np.argsort(perm_importance)[::-1]
    print(f"  Top 10 by permutation importance:")
    for i in range(10):
        idx = perm_ranking[i]
        print(f"    {i+1:2d}. {feature_names[idx]:45s} {perm_importance[idx]:.4f}")

    # Features with negative permutation importance (actively hurting)
    neg_features = [(feature_names[i], perm_importance[i])
                    for i in range(len(feature_names)) if perm_importance[i] < -0.0005]
    if neg_features:
        neg_features.sort(key=lambda x: x[1])
        print(f"\n  ⚠️ {len(neg_features)} features with negative perm importance (hurting model):")
        for name, imp in neg_features[:15]:
            print(f"    {name:45s} {imp:.4f}")

    # ── Phase 3: Top-N experiments with gain importance ───────────────────
    print("\n--- Phase 3: Top-N by gain importance (XGBoost) ---", flush=True)
    results_gain_xgb = []
    for n in TOP_N_VALUES:
        if n > len(feature_names):
            continue
        cols = gain_ranking[:n].tolist()
        m = evaluate_subset(X_train_np, y_train_np, X_test_np, y_test_np, cols, use_calibrated=False)
        delta_auc = m["roc_auc"] - baseline_xgb["roc_auc"]
        flag = "✅" if delta_auc > 0.001 else "❌" if delta_auc < -0.001 else "➖"
        print(f"  {flag} top_{n:3d} -> acc={m['accuracy']:.4f} auc={m['roc_auc']:.4f} "
              f"brier={m['brier']:.4f}  (Δauc={delta_auc:+.4f})", flush=True)
        results_gain_xgb.append({"method": "gain", "model": "XGBoost", "top_n": n, **m})

    # ── Phase 4: Top-N by gain importance (CalibratedXGBoost) ─────────────
    print("\n--- Phase 4: Top-N by gain importance (CalibratedXGBoost) ---", flush=True)
    results_gain_cal = []
    for n in TOP_N_VALUES:
        if n > len(feature_names):
            continue
        cols = gain_ranking[:n].tolist()
        m = evaluate_subset(X_train_np, y_train_np, X_test_np, y_test_np, cols, use_calibrated=True)
        delta_auc = m["roc_auc"] - baseline_cal["roc_auc"]
        flag = "✅" if delta_auc > 0.001 else "❌" if delta_auc < -0.001 else "➖"
        print(f"  {flag} top_{n:3d} -> acc={m['accuracy']:.4f} auc={m['roc_auc']:.4f} "
              f"brier={m['brier']:.4f}  (Δauc={delta_auc:+.4f})", flush=True)
        results_gain_cal.append({"method": "gain", "model": "CalXGBoost", "top_n": n, **m})

    # ── Phase 5: Top-N by permutation importance (XGBoost) ────────────────
    print("\n--- Phase 5: Top-N by permutation importance (XGBoost) ---", flush=True)
    results_perm_xgb = []
    for n in TOP_N_VALUES:
        if n > len(feature_names):
            continue
        cols = perm_ranking[:n].tolist()
        m = evaluate_subset(X_train_np, y_train_np, X_test_np, y_test_np, cols, use_calibrated=False)
        delta_auc = m["roc_auc"] - baseline_xgb["roc_auc"]
        flag = "✅" if delta_auc > 0.001 else "❌" if delta_auc < -0.001 else "➖"
        print(f"  {flag} top_{n:3d} -> acc={m['accuracy']:.4f} auc={m['roc_auc']:.4f} "
              f"brier={m['brier']:.4f}  (Δauc={delta_auc:+.4f})", flush=True)
        results_perm_xgb.append({"method": "perm", "model": "XGBoost", "top_n": n, **m})

    # ── Phase 6: Top-N by permutation importance (CalibratedXGBoost) ──────
    print("\n--- Phase 6: Top-N by permutation importance (CalibratedXGBoost) ---", flush=True)
    results_perm_cal = []
    for n in TOP_N_VALUES:
        if n > len(feature_names):
            continue
        cols = perm_ranking[:n].tolist()
        m = evaluate_subset(X_train_np, y_train_np, X_test_np, y_test_np, cols, use_calibrated=True)
        delta_auc = m["roc_auc"] - baseline_cal["roc_auc"]
        flag = "✅" if delta_auc > 0.001 else "❌" if delta_auc < -0.001 else "➖"
        print(f"  {flag} top_{n:3d} -> acc={m['accuracy']:.4f} auc={m['roc_auc']:.4f} "
              f"brier={m['brier']:.4f}  (Δauc={delta_auc:+.4f})", flush=True)
        results_perm_cal.append({"method": "perm", "model": "CalXGBoost", "top_n": n, **m})

    # ── Phase 7: Remove harmful features only ─────────────────────────────
    print("\n--- Phase 7: Remove harmful features (negative perm importance) ---", flush=True)
    harmful_indices = set(i for i in range(len(feature_names)) if perm_importance[i] < 0)
    if harmful_indices:
        clean_cols = [i for i in range(len(feature_names)) if i not in harmful_indices]
        print(f"  Removing {len(harmful_indices)} harmful features, keeping {len(clean_cols)}")

        m_xgb = evaluate_subset(X_train_np, y_train_np, X_test_np, y_test_np, clean_cols, use_calibrated=False)
        delta = m_xgb["roc_auc"] - baseline_xgb["roc_auc"]
        print(f"  XGBoost:    acc={m_xgb['accuracy']:.4f} auc={m_xgb['roc_auc']:.4f} "
              f"brier={m_xgb['brier']:.4f}  (Δauc={delta:+.4f})")

        m_cal = evaluate_subset(X_train_np, y_train_np, X_test_np, y_test_np, clean_cols, use_calibrated=True)
        delta = m_cal["roc_auc"] - baseline_cal["roc_auc"]
        print(f"  CalXGBoost: acc={m_cal['accuracy']:.4f} auc={m_cal['roc_auc']:.4f} "
              f"brier={m_cal['brier']:.4f}  (Δauc={delta:+.4f})")
    else:
        print("  No harmful features found.")

    # ── Summary ───────────────────────────────────────────────────────────
    all_results = results_gain_xgb + results_gain_cal + results_perm_xgb + results_perm_cal
    df = pd.DataFrame(all_results)

    print(f"\n{'='*90}")
    print("FEATURE SELECTION SUMMARY")
    print(f"{'='*90}")
    print(f"\nBaselines:")
    print(f"  XGBoost (all {len(feature_names)}):    acc={baseline_xgb['accuracy']:.4f} "
          f"auc={baseline_xgb['roc_auc']:.4f} brier={baseline_xgb['brier']:.4f}")
    print(f"  CalXGBoost (all {len(feature_names)}): acc={baseline_cal['accuracy']:.4f} "
          f"auc={baseline_cal['roc_auc']:.4f} brier={baseline_cal['brier']:.4f}")

    print(f"\nAll experiments:")
    print(df.to_string(index=False))

    best = df.loc[df["roc_auc"].idxmax()]
    print(f"\n🏆 Best overall: {best['method']} / {best['model']} / top_{int(best['top_n'])} "
          f"-> AUC={best['roc_auc']:.4f}")

    # Best per model type
    for model_name in ["XGBoost", "CalXGBoost"]:
        sub = df[df["model"] == model_name]
        if len(sub) > 0:
            best_row = sub.loc[sub["roc_auc"].idxmax()]
            baseline_auc = baseline_xgb["roc_auc"] if model_name == "XGBoost" else baseline_cal["roc_auc"]
            delta = best_row["roc_auc"] - baseline_auc
            print(f"  Best {model_name}: top_{int(best_row['top_n'])} ({best_row['method']}) "
                  f"AUC={best_row['roc_auc']:.4f} (Δ={delta:+.4f} vs all features)")

    elapsed = time.time() - t0
    print(f"\nTotal time: {elapsed:.0f}s ({elapsed/60:.1f}min)")

    # Save detailed results
    results_path = os.path.join(os.path.dirname(__file__), "..", "data", "feature_selection_results.csv")
    df.to_csv(results_path, index=False)
    print(f"Results saved to {results_path}")

    # Save feature rankings
    rankings = pd.DataFrame({
        "feature": feature_names,
        "gain_importance": gain_importance,
        "perm_importance": perm_importance,
        "gain_rank": np.argsort(np.argsort(gain_importance)[::-1]) + 1,
        "perm_rank": np.argsort(np.argsort(perm_importance)[::-1]) + 1,
    }).sort_values("perm_importance", ascending=False)
    rankings_path = os.path.join(os.path.dirname(__file__), "..", "data", "feature_rankings.csv")
    rankings.to_csv(rankings_path, index=False)
    print(f"Feature rankings saved to {rankings_path}")


if __name__ == "__main__":
    print(f"\n{'='*90}")
    print("CYCLING H2H — FEATURE SELECTION EXPERIMENTS")
    print(f"{'='*90}\n")
    run_feature_selection()
