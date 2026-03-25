#!/usr/bin/env python3
"""
Feature ablation experiments: test which feature groups improve accuracy.

Tests combinations of feature groups and reports a comparison table.
Run after scraping data (even 2+ races is enough to see patterns).
"""

import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import torch
torch.set_num_threads(1)

from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, roc_auc_score, brier_score_loss
import xgboost as xgb

from data.builder import build_pairs_sampled
from features.pipeline import build_feature_matrix, get_all_feature_names
from features.race_features import RACE_FEATURE_NAMES
from features.rider_features import RIDER_FEATURE_NAMES
from features.pipeline import H2H_FEATURE_NAMES
from models.neural_net import train_neural_net, predict_neural_net

logging.basicConfig(level=logging.WARNING)


# ── Feature groups ──────────────────────────────────────────────────────────

FEATURE_GROUPS = {
    "race": [f"race_{n}" for n in RACE_FEATURE_NAMES],

    "diff_physical": [f"diff_{n}" for n in RIDER_FEATURE_NAMES
                      if n in ("weight", "height", "bmi", "age")],

    "diff_specialty": [f"diff_{n}" for n in RIDER_FEATURE_NAMES
                       if n.startswith("spec_")],

    "diff_career": [f"diff_{n}" for n in RIDER_FEATURE_NAMES
                    if n.startswith("career_")],

    "diff_form_time": [f"diff_{n}" for n in RIDER_FEATURE_NAMES
                       if n.startswith("form_") and ("30d" in n or "60d" in n or "90d" in n or "180d" in n)],

    "diff_form_recent": [f"diff_{n}" for n in RIDER_FEATURE_NAMES
                         if n.startswith("form_last")],

    "diff_terrain": [f"diff_{n}" for n in RIDER_FEATURE_NAMES
                     if n.startswith("terrain_") or n.startswith("mountain") or
                        n.startswith("flat_") or n.startswith("one_day") or n.startswith("itt_")],

    "diff_race_history": [f"diff_{n}" for n in RIDER_FEATURE_NAMES
                          if n.startswith("same_race")],

    "diff_season_pts": [f"diff_{n}" for n in RIDER_FEATURE_NAMES
                        if "season_points" in n or "ranking" in n or "points_trend" in n],

    "diff_breakaway": [f"diff_breakaway_rate"],

    "abs_rider_a": [f"a_{n}" for n in RIDER_FEATURE_NAMES],
    "abs_rider_b": [f"b_{n}" for n in RIDER_FEATURE_NAMES],

    "h2h": H2H_FEATURE_NAMES,

    "interactions": [n for n in get_all_feature_names() if n.startswith("interact_")],
}


def get_group_columns(groups: list[str], all_cols: list[str]) -> list[str]:
    """Get column names for a list of feature groups, filtered to what exists."""
    cols = []
    for g in groups:
        cols.extend(FEATURE_GROUPS.get(g, []))
    return [c for c in cols if c in all_cols]


# ── Experiments to run ──────────────────────────────────────────────────────

EXPERIMENTS = {
    # Baselines
    "all_features": list(FEATURE_GROUPS.keys()),
    "random_baseline": [],  # will be handled specially

    # Individual group tests
    "race_only": ["race"],
    "diff_career_only": ["diff_career"],
    "diff_form_time_only": ["diff_form_time"],
    "diff_form_recent_only": ["diff_form_recent"],
    "diff_specialty_only": ["diff_specialty"],
    "h2h_only": ["h2h"],

    # Diff features only (no absolute rider values)
    "diff_only": ["race", "diff_physical", "diff_specialty", "diff_career",
                   "diff_form_time", "diff_form_recent", "diff_terrain",
                   "diff_race_history", "diff_season_pts", "diff_breakaway", "h2h"],

    # No absolute features
    "no_abs": ["race", "diff_physical", "diff_specialty", "diff_career",
               "diff_form_time", "diff_form_recent", "diff_terrain",
               "diff_race_history", "diff_season_pts", "diff_breakaway",
               "h2h", "interactions"],

    # Core betting features
    "core_form": ["diff_form_time", "diff_form_recent", "diff_career"],
    "core_form_plus_race": ["race", "diff_form_time", "diff_form_recent", "diff_career"],

    # Form + specialty + terrain
    "form_spec_terrain": ["race", "diff_form_time", "diff_form_recent",
                          "diff_specialty", "diff_terrain"],

    # Everything except interactions
    "no_interactions": [g for g in FEATURE_GROUPS if g != "interactions"],

    # Everything except absolute rider values
    "no_absolute": [g for g in FEATURE_GROUPS if g not in ("abs_rider_a", "abs_rider_b")],

    # Everything except race features
    "no_race": [g for g in FEATURE_GROUPS if g != "race"],

    # Everything except h2h
    "no_h2h": [g for g in FEATURE_GROUPS if g != "h2h"],

    # Minimal: just form + h2h
    "form_h2h": ["diff_form_time", "diff_form_recent", "h2h"],

    # Strong combo: form + career + specialty + race + h2h
    "strong_combo": ["race", "diff_career", "diff_form_time", "diff_form_recent",
                     "diff_specialty", "diff_terrain", "diff_season_pts", "h2h"],

    # Kitchen sink minus physical (physical might add noise)
    "no_physical": [g for g in FEATURE_GROUPS if g != "diff_physical"],
}


def evaluate_experiment(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
    model_type: str = "xgboost",
) -> dict:
    """Train and evaluate a single model on given features."""
    if X_train.shape[1] == 0:
        # Random baseline
        preds = np.random.randint(0, 2, len(y_test))
        return {"accuracy": accuracy_score(y_test, preds), "roc_auc": 0.5, "brier": 0.25}

    scaler = StandardScaler()
    Xtr = scaler.fit_transform(X_train)
    Xte = scaler.transform(X_test)

    if model_type == "xgboost":
        model = xgb.XGBClassifier(
            n_estimators=200, max_depth=6, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            min_child_weight=10, random_state=42,
            eval_metric="logloss",
        )
        model.fit(Xtr, y_train, verbose=False)
        probs = model.predict_proba(Xte)[:, 1]
    elif model_type == "nn":
        model, _ = train_neural_net(
            Xtr, y_train.astype(np.float32),
            Xte, y_test.astype(np.float32),
            epochs=50, patience=8,
        )
        probs = predict_neural_net(model, Xte)
    else:
        raise ValueError(f"Unknown model_type: {model_type}")

    preds = (probs >= 0.5).astype(int)
    return {
        "accuracy": accuracy_score(y_test, preds),
        "roc_auc": roc_auc_score(y_test, probs),
        "brier": brier_score_loss(y_test, probs),
    }


def run_experiments(model_type: str = "xgboost", n_splits: int = 3):
    """Run all experiments with cross-validation-style repeated splits."""

    print("Building dataset...", flush=True)
    pairs = build_pairs_sampled(max_rank=25, pairs_per_stage=100)
    feat_df = build_feature_matrix(pairs)
    all_cols = [c for c in feat_df.columns if c != "label"]

    X_all = feat_df[all_cols].values
    y_all = feat_df["label"].values
    n = len(X_all)

    print(f"Dataset: {n} samples, {len(all_cols)} features")
    print(f"Model: {model_type} | Splits: {n_splits}")
    print(f"Running {len(EXPERIMENTS)} experiments...\n")

    results = []

    for exp_name, groups in EXPERIMENTS.items():
        if exp_name == "random_baseline":
            cols_idx = []
        else:
            col_names = get_group_columns(groups, all_cols)
            cols_idx = [all_cols.index(c) for c in col_names]

        split_metrics = []
        for seed in range(n_splits):
            np.random.seed(seed * 42 + 7)
            idx = np.random.permutation(n)
            split = int(n * 0.8)
            train_idx, test_idx = idx[:split], idx[split:]

            if cols_idx:
                Xtr = X_all[train_idx][:, cols_idx]
                Xte = X_all[test_idx][:, cols_idx]
            else:
                Xtr = np.zeros((len(train_idx), 0))
                Xte = np.zeros((len(test_idx), 0))

            ytr = y_all[train_idx]
            yte = y_all[test_idx]

            m = evaluate_experiment(Xtr, ytr, Xte, yte, model_type)
            split_metrics.append(m)

        avg = {
            "experiment": exp_name,
            "n_features": len(cols_idx),
            "accuracy": np.mean([m["accuracy"] for m in split_metrics]),
            "acc_std": np.std([m["accuracy"] for m in split_metrics]),
            "roc_auc": np.mean([m["roc_auc"] for m in split_metrics]),
            "auc_std": np.std([m["roc_auc"] for m in split_metrics]),
            "brier": np.mean([m["brier"] for m in split_metrics]),
        }
        results.append(avg)

        flag = "★" if avg["roc_auc"] >= results[0]["roc_auc"] else " "
        print(f"  {flag} {exp_name:30s} | feats={avg['n_features']:3d} | "
              f"acc={avg['accuracy']:.3f}±{avg['acc_std']:.3f} | "
              f"auc={avg['roc_auc']:.3f}±{avg['auc_std']:.3f} | "
              f"brier={avg['brier']:.4f}", flush=True)

    results_df = pd.DataFrame(results).sort_values("roc_auc", ascending=False)

    print("\n" + "=" * 90)
    print(f"FEATURE ABLATION RESULTS ({model_type.upper()})")
    print("=" * 90)
    print(results_df.to_string(index=False))
    print("=" * 90)

    best = results_df.iloc[0]
    worst_non_baseline = results_df[results_df["experiment"] != "random_baseline"].iloc[-1]
    print(f"\n🏆 Best:  {best['experiment']} (AUC={best['roc_auc']:.4f})")
    print(f"📉 Worst: {worst_non_baseline['experiment']} (AUC={worst_non_baseline['roc_auc']:.4f})")

    all_feats = results_df[results_df["experiment"] == "all_features"].iloc[0]
    print(f"\n📊 All features baseline: AUC={all_feats['roc_auc']:.4f}")

    better_than_all = results_df[results_df["roc_auc"] > all_feats["roc_auc"]]
    if len(better_than_all) > 0:
        print("✅ Feature sets that beat 'all_features':")
        for _, row in better_than_all.iterrows():
            if row["experiment"] != "all_features":
                delta = row["roc_auc"] - all_feats["roc_auc"]
                print(f"   {row['experiment']} (AUC +{delta:.4f}, {int(row['n_features'])} feats)")
    else:
        print("ℹ️  No subset beat all_features — more features = better with this data size.")

    return results_df


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="xgboost", choices=["xgboost", "nn"])
    parser.add_argument("--splits", type=int, default=3)
    args = parser.parse_args()

    print(f"\n{'='*90}")
    print(f"CYCLING H2H FEATURE ABLATION STUDY")
    print(f"{'='*90}\n")

    run_experiments(model_type=args.model, n_splits=args.splits)
