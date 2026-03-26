"""
Train and benchmark multiple models for H2H prediction.

Models: Logistic Regression, Random Forest, XGBoost, Neural Network.
Uses time-based train/test split to avoid data leakage.
"""

import os
import json
import logging
import pickle

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    accuracy_score, roc_auc_score, log_loss, classification_report,
    brier_score_loss,
)
from sklearn.calibration import CalibratedClassifierCV
import xgboost as xgb

# Lazy import: neural_net imports torch which conflicts with XGBoost's OpenMP on macOS
# Import inside functions that need it instead

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

    log.info(f"Feature selection: training XGBoost on all {len(feature_names)} features...")
    selector_model = xgb.XGBClassifier(
        n_estimators=300, max_depth=8, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        min_child_weight=10, reg_alpha=0.1, reg_lambda=1.0,
        random_state=42, eval_metric="logloss",
    )
    selector_model.fit(X_train_scaled, y_train, verbose=False)

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


def run_benchmark(
    feature_df: pd.DataFrame,
    date_series: pd.Series,
    test_years: list[int] = None,
    skip_nn: bool = False,
    select_features: int = 0,
) -> dict:
    """
    Train all models and return comparison results.

    Args:
        select_features: If > 0, use permutation importance to select top-N
                         features before training. 0 = use all features.

    Returns dict with:
        - results: list of metric dicts per model
        - best_model_name: name of best model by ROC-AUC
        - scaler: fitted StandardScaler
        - models: dict of name → fitted model
    """
    X_train, X_test, y_train, y_test = time_based_split(
        feature_df, date_series, test_years
    )

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

    # --- Logistic Regression ---
    log.info("Training Logistic Regression...")
    lr = LogisticRegression(max_iter=1000, C=1.0, random_state=42)
    lr.fit(X_train_scaled, y_train)
    lr_prob = lr.predict_proba(X_test_scaled)[:, 1]
    lr_pred = (lr_prob >= 0.5).astype(int)
    results.append(evaluate_model("LogisticRegression", y_test, lr_pred, lr_prob))
    models["LogisticRegression"] = lr

    # --- Random Forest ---
    log.info("Training Random Forest...")
    rf = RandomForestClassifier(
        n_estimators=200, max_depth=15, min_samples_leaf=10,
        random_state=42, n_jobs=1,
    )
    rf.fit(X_train_scaled, y_train)
    rf_prob = rf.predict_proba(X_test_scaled)[:, 1]
    rf_pred = (rf_prob >= 0.5).astype(int)
    results.append(evaluate_model("RandomForest", y_test, rf_pred, rf_prob))
    models["RandomForest"] = rf

    # --- XGBoost ---
    log.info("Training XGBoost...")
    xgb_model = xgb.XGBClassifier(
        n_estimators=300, max_depth=8, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        min_child_weight=10, reg_alpha=0.1, reg_lambda=1.0,
        random_state=42, eval_metric="logloss",
    )
    xgb_model.fit(X_train_scaled, y_train, verbose=False)
    xgb_prob = xgb_model.predict_proba(X_test_scaled)[:, 1]
    xgb_pred = (xgb_prob >= 0.5).astype(int)
    results.append(evaluate_model("XGBoost", y_test, xgb_pred, xgb_prob))
    models["XGBoost"] = xgb_model

    # --- Neural Network ---
    if not skip_nn:
        log.info("Training Neural Network...")
        from models.neural_net import train_neural_net, predict_neural_net
        nn_model, nn_history = train_neural_net(
            X_train_scaled, y_train.values.astype(np.float32),
            X_test_scaled, y_test.values.astype(np.float32),
        )
        nn_prob = predict_neural_net(nn_model, X_test_scaled)
        nn_pred = (nn_prob >= 0.5).astype(int)
        results.append(evaluate_model("NeuralNetwork", y_test, nn_pred, nn_prob))
        models["NeuralNetwork"] = nn_model
    else:
        log.info("Skipping Neural Network (--nn to include)")

    # --- Calibrated XGBoost (for betting) ---
    log.info("Training Calibrated XGBoost...")
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

    # Save models and scaler
    with open(os.path.join(MODELS_DIR, "scaler.pkl"), "wb") as f:
        pickle.dump(scaler, f)
    with open(os.path.join(MODELS_DIR, "feature_names.json"), "w") as f:
        json.dump(feature_names, f)

    for name, model in models.items():
        if name == "NeuralNetwork":
            import torch
            torch.save(model.state_dict(), os.path.join(MODELS_DIR, "neural_net.pt"))
        else:
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
