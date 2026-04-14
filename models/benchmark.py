"""
Train and benchmark XGBoost models for H2H prediction.

Trains raw XGBoost and CalibratedXGBoost (isotonic, for betting).
Uses stratified stage split to avoid data leakage.
"""

import os
import json
import logging
import pickle

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    accuracy_score, roc_auc_score, log_loss, classification_report,
    brier_score_loss,
)
from sklearn.calibration import CalibratedClassifierCV
import xgboost as xgb

log = logging.getLogger(__name__)

MODELS_DIR = os.path.join(os.path.dirname(__file__), "trained")
os.makedirs(MODELS_DIR, exist_ok=True)


def time_based_split(
    feature_df: pd.DataFrame,
    date_series: pd.Series,
    test_years: list[int] = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """
    Split data by time: train on earlier years, test on later.
    Default: test on 2025-2026, train on everything before.
    """
    if test_years is None:
        test_years = [2025, 2026]

    years = date_series.apply(lambda d: int(str(d)[:4]) if pd.notna(d) else 2020)
    train_mask = ~years.isin(test_years)
    test_mask = years.isin(test_years)

    X = feature_df.drop(columns=["label"])
    y = feature_df["label"]

    return X[train_mask], X[test_mask], y[train_mask], y[test_mask]


def stratified_stage_split(
    feature_df: pd.DataFrame,
    stage_urls: pd.Series,
    test_fraction: float = 0.2,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """
    Split data by stage: randomly assign 20% of stages to test, 80% to train.
    All pairs from a given stage stay together (no within-race leakage).
    Stages are stratified by year so every year is in both train and test.
    """
    rng = np.random.RandomState(seed)

    # Extract year from stage_url (e.g. 'race/tour-de-france/2025/stage-1' → 2025)
    def _year_from_url(url):
        if pd.isna(url):
            return 2020
        parts = str(url).split("/")
        for p in parts:
            if p.isdigit() and len(p) == 4:
                return int(p)
        return 2020

    years = stage_urls.apply(_year_from_url)
    unique_stages = pd.DataFrame({"stage_url": stage_urls, "year": years}).drop_duplicates("stage_url")

    test_stages = set()
    for _, grp in unique_stages.groupby("year"):
        stage_list = grp["stage_url"].tolist()
        rng.shuffle(stage_list)
        n_test = max(1, int(len(stage_list) * test_fraction))
        test_stages.update(stage_list[:n_test])

    test_mask = stage_urls.isin(test_stages)
    train_mask = ~test_mask

    X = feature_df.drop(columns=["label"])
    y = feature_df["label"]

    return X[train_mask], X[test_mask], y[train_mask], y[test_mask]


def evaluate_model(name: str, y_true, y_pred, y_prob) -> dict:
    """Compute evaluation metrics for a model."""
    metrics = {
        "model": name,
        "accuracy": accuracy_score(y_true, y_pred),
        "roc_auc": roc_auc_score(y_true, y_prob),
        "log_loss": log_loss(y_true, y_prob),
        "brier_score": brier_score_loss(y_true, y_prob),
    }
    return metrics


def _select_features(X_train_scaled, y_train, X_test_scaled, y_test,
                     feature_names, top_n=120):
    """Select top-N features by permutation importance on a raw XGBoost."""
    from sklearn.inspection import permutation_importance

    log.info(f"Feature selection: training XGBoost on all {len(feature_names)} features (300 rounds)...")
    selector_model = xgb.XGBClassifier(
        n_estimators=300, max_depth=8, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        min_child_weight=10, reg_alpha=0.1, reg_lambda=1.0,
        random_state=42, eval_metric="logloss",
    )
    selector_model.fit(
        X_train_scaled, y_train,
        eval_set=[(X_test_scaled, y_test)],
        verbose=50,
    )

    log.info("Computing permutation importance...")
    perm = permutation_importance(
        selector_model, X_test_scaled, y_test,
        n_repeats=10, random_state=42, scoring="roc_auc",
    )
    perm_ranking = np.argsort(perm.importances_mean)[::-1]
    selected_idx = sorted(perm_ranking[:top_n].tolist())
    selected_names = [feature_names[i] for i in selected_idx]

    log.info(f"Selected {len(selected_names)} features (top {top_n} by permutation importance)")
    log.info(f"Top 10: {[feature_names[i] for i in perm_ranking[:10]]}")

    return selected_idx, selected_names


def _print_calibration_report(y_true, probs, correct, X_test, model_name):
    """Print calibration and accuracy breakdown after benchmarking."""
    print(f"\n{'=' * 70}")
    print(f"CALIBRATION & ACCURACY BREAKDOWN ({model_name})")
    print("=" * 70)

    # Calibration by confidence bins
    print(f"\n{'Conf Range':<12} {'Model Avg':>10} {'Actual Win%':>12} {'Accuracy':>10} {'Count':>8}")
    bins = [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70),
            (0.70, 0.75), (0.75, 0.80), (0.80, 1.0)]
    for lo, hi in bins:
        mask = (probs >= lo) & (probs < hi)
        if mask.sum() > 10:
            avg_p = probs[mask].mean()
            actual = y_true[mask].mean()
            acc = correct[mask].mean()
            cal_err = abs(avg_p - actual)
            icon = "✅" if cal_err < 0.03 else "⚠️" if cal_err < 0.06 else "❌"
            print(f"{icon} {lo:.0%}-{hi:.0%}    {avg_p:>9.1%} {actual:>11.1%} "
                  f"{acc:>9.1%} {mask.sum():>8}")

    # Accuracy by confidence level
    print(f"\n  Confidence breakdown:")
    for label, lo, hi in [("Low (50-60%)", 0.5, 0.6),
                           ("Medium (60-70%)", 0.6, 0.7),
                           ("High (70%+)", 0.7, 1.0)]:
        mask = (probs >= lo) & (probs < hi)
        if mask.sum() > 0:
            print(f"    {label}: {correct[mask].mean():.1%} accuracy (n={mask.sum()})")

    # Accuracy by race type (if column exists)
    if "race_is_one_day_race" in X_test.columns:
        print(f"\n  By race type:")
        for val, label in [(1, "One-day"), (0, "Stage race")]:
            mask = (X_test["race_is_one_day_race"].values == val)
            if mask.sum() > 0:
                print(f"    {label}: {correct[mask].mean():.1%} (n={mask.sum()})")

    # Accuracy by course type (if column exists)
    if "race_profile_icon_num" in X_test.columns:
        print(f"\n  By course type:")
        icon_vals = X_test["race_profile_icon_num"].values
        course_bins = [("Flat", [0, 1]), ("Hilly", [2, 3]), ("Mountain", [4, 5])]
        for label, vals in course_bins:
            mask = np.isin(icon_vals, vals)
            if mask.sum() > 0:
                print(f"    {label}: {correct[mask].mean():.1%} (n={mask.sum()})")

    print("=" * 70)


def run_benchmark(
    feature_df: pd.DataFrame,
    date_series: pd.Series,
    test_years: list[int] = None,
    select_features: int = 0,
    stage_urls: pd.Series = None,
    split_mode: str = "stratified",
) -> dict:
    """
    Train XGBoost models and return comparison results.

    Args:
        select_features: If > 0, use permutation importance to select top-N
                         features before training. 0 = use all features.
        stage_urls: Stage URL for each row — needed for stratified split.
        split_mode: "stratified" (default) = random 80/20 by stage across all
                    years; "time" = train on older years, test on test_years.

    Returns dict with:
        - results: list of metric dicts per model
        - best_model_name: name of best model by ROC-AUC
        - scaler: fitted StandardScaler
        - models: dict of name → fitted model
    """
    if split_mode == "stratified" and stage_urls is not None:
        X_train, X_test, y_train, y_test = stratified_stage_split(
            feature_df, stage_urls
        )
        log.info("Using stratified stage split (80/20 across all years)")
    else:
        X_train, X_test, y_train, y_test = time_based_split(
            feature_df, date_series, test_years
        )
        log.info("Using time-based split")

    log.info(f"Train size: {len(X_train)}, Test size: {len(X_test)}")

    all_feature_names = list(X_train.columns)

    if select_features > 0:
        # Feature selection: scale all, rank, then re-scale selected subset
        tmp_scaler = StandardScaler()
        Xtr_tmp = tmp_scaler.fit_transform(X_train)
        Xte_tmp = tmp_scaler.transform(X_test)

        selected_idx, feature_names = _select_features(
            Xtr_tmp, y_train, Xte_tmp, y_test,
            all_feature_names, top_n=select_features,
        )
        X_train = X_train.iloc[:, selected_idx]
        X_test = X_test.iloc[:, selected_idx]
    else:
        feature_names = all_feature_names

    # Standardize features
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    results = []
    models = {}

    # --- XGBoost ---
    log.info("Training XGBoost (300 rounds)...")
    xgb_model = xgb.XGBClassifier(
        n_estimators=300, max_depth=8, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        min_child_weight=10, reg_alpha=0.1, reg_lambda=1.0,
        random_state=42, eval_metric="logloss",
    )
    xgb_model.fit(
        X_train_scaled, y_train,
        eval_set=[(X_test_scaled, y_test)],
        verbose=50,
    )
    xgb_prob = xgb_model.predict_proba(X_test_scaled)[:, 1]
    xgb_pred = (xgb_prob >= 0.5).astype(int)
    results.append(evaluate_model("XGBoost", y_test, xgb_pred, xgb_prob))
    models["XGBoost"] = xgb_model

    # --- Calibrated XGBoost (for betting) ---
    log.info("Training Calibrated XGBoost (5-fold CV × 300 rounds each — no per-fold progress)...")
    cal_xgb = CalibratedClassifierCV(
        xgb.XGBClassifier(
            n_estimators=300, max_depth=8, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            min_child_weight=10, random_state=42, eval_metric="logloss",
        ),
        method="isotonic", cv=5,
    )
    cal_xgb.fit(X_train_scaled, y_train)
    cal_prob = cal_xgb.predict_proba(X_test_scaled)[:, 1]
    cal_pred = (cal_prob >= 0.5).astype(int)
    results.append(evaluate_model("CalibratedXGBoost", y_test, cal_pred, cal_prob))
    models["CalibratedXGBoost"] = cal_xgb

    # Print results
    results_df = pd.DataFrame(results).sort_values("roc_auc", ascending=False)
    print("\n" + "=" * 70)
    print("MODEL BENCHMARK RESULTS")
    print("=" * 70)
    print(results_df.to_string(index=False))
    print("=" * 70)

    best_name = results_df.iloc[0]["model"]
    print(f"\nBest model by ROC-AUC: {best_name}")

    # Feature importance from XGBoost
    importance = xgb_model.feature_importances_
    feat_imp = sorted(
        zip(feature_names, importance),
        key=lambda x: x[1], reverse=True,
    )
    print("\nTop 20 features (XGBoost importance):")
    for fname, imp in feat_imp[:20]:
        print(f"  {fname}: {imp:.4f}")

    # Calibration & accuracy breakdown (using best model)
    best_model = models[best_name]
    best_prob = best_model.predict_proba(X_test_scaled)[:, 1]
    best_correct = ((best_prob >= 0.5).astype(int) == y_test.values).astype(int)
    _print_calibration_report(y_test.values, best_prob, best_correct, X_test, best_name)

    # Save models and scaler
    with open(os.path.join(MODELS_DIR, "scaler.pkl"), "wb") as f:
        pickle.dump(scaler, f)
    with open(os.path.join(MODELS_DIR, "feature_names.json"), "w") as f:
        json.dump(feature_names, f)

    for name, model in models.items():
        with open(os.path.join(MODELS_DIR, f"{name}.pkl"), "wb") as f:
            pickle.dump(model, f)

    # Save results
    results_df.to_csv(os.path.join(MODELS_DIR, "benchmark_results.csv"), index=False)

    return {
        "results": results,
        "best_model_name": best_name,
        "scaler": scaler,
        "models": models,
        "feature_names": feature_names,
    }
