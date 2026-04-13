#!/usr/bin/env python3
"""
Experiment: evaluate post-processing probability adjustments.

Tests variance adjustment, Bayesian uncertainty, upset injection,
temperature scaling, Platt scaling, and beta calibration against
the raw CalibratedXGBoost baseline.

Usage:
    python scripts/eval_post_processing.py
"""

import os
import sys
import json
import logging
import pickle

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score, roc_auc_score, log_loss, brier_score_loss,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

from data.builder import build_pairs_sampled
from features.pipeline import build_feature_matrix
from models.benchmark import stratified_stage_split
from models.post_processing import (
    ProbabilityAdjuster, AdjustmentConfig,
    fit_temperature, fit_platt_scaling, apply_platt_scaling,
    fit_beta_calibration, apply_beta_calibration,
)
from scripts.eval_calibration import (
    expected_calibration_error, brier_decomposition,
    confidence_stratified_metrics,
)

log = logging.getLogger(__name__)

MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "models", "trained")


def extract_feature_dicts_from_matrix(feature_df, indices):
    """
    Extract per-rider and per-race feature dicts from the feature matrix.

    The feature matrix has columns like 'a_career_rank_stddev', 'b_form_90d_races',
    'race_profile_icon_num' etc. We strip the prefix to get the rider feature dict keys
    that ProbabilityAdjuster expects.

    Returns: (features_a_list, features_b_list, race_features_list)
    """
    from features.rider_features import RIDER_FEATURE_NAMES

    all_cols = feature_df.columns.tolist()

    # Identify rider-a, rider-b, and race columns
    a_cols = [c for c in all_cols if c.startswith("a_")]
    b_cols = [c for c in all_cols if c.startswith("b_")]
    race_cols = [c for c in all_cols if c.startswith("race_")]

    subset = feature_df.loc[indices]
    features_a = []
    features_b = []
    race_feats = []

    for _, row in subset.iterrows():
        fa = {c[2:]: row[c] for c in a_cols}  # strip 'a_' prefix
        fb = {c[2:]: row[c] for c in b_cols}  # strip 'b_' prefix
        rf = {c: row[c] for c in race_cols}
        features_a.append(fa)
        features_b.append(fb)
        race_feats.append(rf)

    return features_a, features_b, race_feats


def evaluate_config(name, y_true, y_prob):
    """Compute metrics for a given configuration."""
    y_pred = (y_prob >= 0.5).astype(int)
    ece, _ = expected_calibration_error(y_true, y_prob)
    brier = brier_decomposition(y_true, y_prob)

    return {
        "name": name,
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "roc_auc": float(roc_auc_score(y_true, y_prob)),
        "log_loss": float(log_loss(y_true, y_prob)),
        "brier": float(brier_score_loss(y_true, y_prob)),
        "ece": ece,
        "reliability": brier["reliability"],
        "resolution": brier["resolution"],
    }


def run_experiment():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Load model
    log.info("Loading model...")
    with open(os.path.join(MODELS_DIR, "scaler.pkl"), "rb") as f:
        scaler = pickle.load(f)
    with open(os.path.join(MODELS_DIR, "feature_names.json"), "r") as f:
        feature_names = json.load(f)
    with open(os.path.join(MODELS_DIR, "CalibratedXGBoost.pkl"), "rb") as f:
        model = pickle.load(f)

    # Build data
    log.info("Building pairs and features...")
    pairs_df = build_pairs_sampled()
    feature_df = build_feature_matrix(pairs_df)

    stage_urls = pairs_df.loc[feature_df.index, "stage_url"].reset_index(drop=True)
    feature_df_reset = feature_df.reset_index(drop=True)

    X_train, X_test, y_train, y_test = stratified_stage_split(feature_df_reset, stage_urls)

    X_test_aligned = X_test[feature_names]
    X_test_scaled = scaler.transform(X_test_aligned)

    # Get raw probabilities
    y_prob_raw = model.predict_proba(X_test_scaled)[:, 1]
    y_true = y_test.values.astype(float)

    log.info(f"Test set: {len(y_true)} samples")

    # ===================================================================
    # Extract rider/race feature dicts from feature matrix for post-processing
    # ===================================================================
    log.info("Extracting rider feature dicts from feature matrix...")
    features_a, features_b, race_feats = extract_feature_dicts_from_matrix(
        feature_df_reset, X_test.index
    )
    log.info(f"  Extracted feature dicts for {len(features_a)} test pairs")

    # Also split into train/val for fitting calibration params
    # Use first 70% of train for fitting, last 30% for validation
    n_train = len(X_train)
    n_cal = int(n_train * 0.3)
    X_cal = X_train.iloc[-n_cal:]
    y_cal = y_train.iloc[-n_cal:]

    X_cal_aligned = X_cal[feature_names]
    X_cal_scaled = scaler.transform(X_cal_aligned)
    y_cal_prob = model.predict_proba(X_cal_scaled)[:, 1]
    y_cal_true = y_cal.values.astype(float)

    # ===================================================================
    # Experiments
    # ===================================================================
    results = []

    # 0. Baseline (raw CalibratedXGBoost)
    results.append(evaluate_config("baseline_raw", y_true, y_prob_raw))
    log.info(f"Baseline: AUC={results[0]['roc_auc']:.4f} Brier={results[0]['brier']:.4f} ECE={results[0]['ece']:.4f}")

    # --- Temperature scaling ---
    log.info("Fitting temperature scaling on calibration set...")
    T = fit_temperature(y_cal_true, y_cal_prob)
    log.info(f"  Fitted T = {T:.4f}")

    y_prob_temp = np.clip(y_prob_raw, 1e-7, 1 - 1e-7)
    logits = np.log(y_prob_temp / (1 - y_prob_temp))
    y_prob_temp = 1.0 / (1.0 + np.exp(-logits / T))
    results.append(evaluate_config("temperature_scaling", y_true, y_prob_temp))

    # --- Platt scaling ---
    log.info("Fitting Platt scaling...")
    a, b = fit_platt_scaling(y_cal_true, y_cal_prob)
    log.info(f"  Fitted a={a:.4f}, b={b:.4f}")
    y_prob_platt = apply_platt_scaling(y_prob_raw, a, b)
    results.append(evaluate_config("platt_scaling", y_true, y_prob_platt))

    # --- Beta calibration ---
    log.info("Fitting beta calibration...")
    ba, bb, bc = fit_beta_calibration(y_cal_true, y_cal_prob)
    log.info(f"  Fitted a={ba:.4f}, b={bb:.4f}, c={bc:.4f}")
    y_prob_beta = apply_beta_calibration(y_prob_raw, ba, bb, bc)
    results.append(evaluate_config("beta_calibration", y_true, y_prob_beta))

    # --- Post-processing configurations ---
    configs = {
        "variance_only": AdjustmentConfig(
            use_variance_adjustment=True,
            use_bayesian_uncertainty=False,
            use_upset_injection=False,
            use_extreme_shrinkage=False,
            use_temperature=False,
        ),
        "bayesian_only": AdjustmentConfig(
            use_variance_adjustment=False,
            use_bayesian_uncertainty=True,
            use_upset_injection=False,
            use_extreme_shrinkage=False,
            use_temperature=False,
        ),
        "upset_only": AdjustmentConfig(
            use_variance_adjustment=False,
            use_bayesian_uncertainty=False,
            use_upset_injection=True,
            use_extreme_shrinkage=False,
            use_temperature=False,
        ),
        "shrinkage_only": AdjustmentConfig(
            use_variance_adjustment=False,
            use_bayesian_uncertainty=False,
            use_upset_injection=False,
            use_extreme_shrinkage=True,
            use_temperature=False,
        ),
        "variance_plus_bayesian": AdjustmentConfig(
            use_variance_adjustment=True,
            use_bayesian_uncertainty=True,
            use_upset_injection=False,
            use_extreme_shrinkage=False,
            use_temperature=False,
        ),
        "full_pipeline": AdjustmentConfig(
            use_variance_adjustment=True,
            use_bayesian_uncertainty=True,
            use_upset_injection=True,
            use_extreme_shrinkage=True,
            use_temperature=False,
        ),
        "full_with_temperature": AdjustmentConfig(
            use_variance_adjustment=True,
            use_bayesian_uncertainty=True,
            use_upset_injection=True,
            use_extreme_shrinkage=True,
            use_temperature=True,
            temperature=T,
        ),
        "conservative_sigma": AdjustmentConfig(
            sigma_base=0.25,
            sigma_rider_weight=0.012,
            sigma_course_weight=0.008,
            use_variance_adjustment=True,
            use_bayesian_uncertainty=True,
            use_upset_injection=True,
            use_extreme_shrinkage=True,
            use_temperature=False,
        ),
        "aggressive_epsilon": AdjustmentConfig(
            epsilon_base=0.05,
            epsilon_one_day_bonus=0.04,
            epsilon_hilly_bonus=0.02,
            use_variance_adjustment=True,
            use_bayesian_uncertainty=True,
            use_upset_injection=True,
            use_extreme_shrinkage=True,
            use_temperature=False,
        ),
    }

    for config_name, config in configs.items():
        log.info(f"Testing {config_name}...")
        adjuster = ProbabilityAdjuster(config)

        y_prob_adj = np.empty(len(y_prob_raw))
        for i in range(len(y_prob_raw)):
            result = adjuster.adjust(
                y_prob_raw[i], features_a[i], features_b[i], race_feats[i]
            )
            y_prob_adj[i] = result.p_adjusted

        results.append(evaluate_config(config_name, y_true, y_prob_adj))
        r = results[-1]
        log.info(f"  AUC={r['roc_auc']:.4f} Brier={r['brier']:.4f} ECE={r['ece']:.4f}")

    # ===================================================================
    # Print results
    # ===================================================================
    print("\n" + "=" * 90)
    print("POST-PROCESSING EXPERIMENT RESULTS")
    print("=" * 90)

    df = pd.DataFrame(results)
    df = df.sort_values("brier", ascending=True)

    baseline_brier = results[0]["brier"]
    baseline_ece = results[0]["ece"]
    baseline_auc = results[0]["roc_auc"]

    print(f"\n{'Config':<28} {'Acc':>7} {'AUC':>7} {'Brier':>7} {'ΔECE':>8} "
          f"{'ΔBrier':>8} {'ΔAUC':>8} {'Reliab':>8}")
    for _, row in df.iterrows():
        d_brier = row["brier"] - baseline_brier
        d_ece = row["ece"] - baseline_ece
        d_auc = row["roc_auc"] - baseline_auc
        icon = "🟢" if d_brier < -0.0005 else "🟡" if abs(d_brier) < 0.0005 else "🔴"
        print(f"{icon} {row['name']:<26} {row['accuracy']:>6.4f} {row['roc_auc']:>6.4f} "
              f"{row['brier']:>6.4f} {d_ece:>+7.4f} {d_brier:>+7.4f} "
              f"{d_auc:>+7.4f} {row['reliability']:>7.5f}")

    print("\n" + "=" * 90)

    # Save results
    out_path = os.path.join(MODELS_DIR, "post_processing_results.csv")
    df.to_csv(out_path, index=False)
    log.info(f"Results saved to {out_path}")

    return results


if __name__ == "__main__":
    run_experiment()
