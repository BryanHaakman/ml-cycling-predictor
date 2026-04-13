#!/usr/bin/env python3
"""
Calibration and probability-quality evaluation framework.

Produces:
  - Calibration curve (reliability diagram)
  - Expected Calibration Error (ECE)
  - Brier score decomposition (reliability, resolution, uncertainty)
  - Confidence-stratified accuracy and calibration
  - Overconfidence analysis
  - Per-race-type breakdown

Usage:
    python scripts/eval_calibration.py              # full evaluation
    python scripts/eval_calibration.py --plot        # save calibration plots
    python scripts/eval_calibration.py --json        # output metrics as JSON
"""

import os
import sys
import json
import argparse
import logging

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score, roc_auc_score, log_loss, brier_score_loss,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.scraper import get_db
from data.builder import build_pairs_sampled
from features.pipeline import build_feature_matrix
from models.benchmark import stratified_stage_split

log = logging.getLogger(__name__)

MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "models", "trained")


# ---------------------------------------------------------------------------
# Calibration metrics
# ---------------------------------------------------------------------------

def expected_calibration_error(y_true, y_prob, n_bins=15):
    """
    Compute Expected Calibration Error (ECE).

    ECE = Σ (|B_m| / N) * |acc(B_m) - conf(B_m)|

    where B_m is the set of samples in bin m, acc is accuracy,
    conf is average predicted probability.
    """
    bin_edges = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    bin_data = []

    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        mask = (y_prob >= lo) & (y_prob < hi)
        if i == n_bins - 1:  # include 1.0 in last bin
            mask = (y_prob >= lo) & (y_prob <= hi)

        n_in_bin = mask.sum()
        if n_in_bin == 0:
            bin_data.append({
                "bin_lo": lo, "bin_hi": hi, "count": 0,
                "avg_conf": 0, "avg_acc": 0, "cal_error": 0,
            })
            continue

        avg_conf = y_prob[mask].mean()
        avg_acc = y_true[mask].mean()
        cal_error = abs(avg_acc - avg_conf)
        ece += (n_in_bin / len(y_true)) * cal_error

        bin_data.append({
            "bin_lo": lo, "bin_hi": hi, "count": int(n_in_bin),
            "avg_conf": float(avg_conf), "avg_acc": float(avg_acc),
            "cal_error": float(cal_error),
        })

    return float(ece), bin_data


def brier_decomposition(y_true, y_prob, n_bins=15):
    """
    Decompose Brier score into reliability, resolution, and uncertainty.

    Brier = Reliability - Resolution + Uncertainty

    - Reliability: how well calibrated (lower = better)
    - Resolution: how much predictions deviate from base rate (higher = better)
    - Uncertainty: inherent difficulty = p̄(1-p̄) where p̄ = base rate
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)

    base_rate = y_true.mean()
    uncertainty = base_rate * (1 - base_rate)

    bin_edges = np.linspace(0, 1, n_bins + 1)
    reliability = 0.0
    resolution = 0.0

    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        mask = (y_prob >= lo) & (y_prob < hi)
        if i == n_bins - 1:
            mask = (y_prob >= lo) & (y_prob <= hi)

        n_k = mask.sum()
        if n_k == 0:
            continue

        avg_prob = y_prob[mask].mean()
        avg_outcome = y_true[mask].mean()

        reliability += n_k * (avg_outcome - avg_prob) ** 2
        resolution += n_k * (avg_outcome - base_rate) ** 2

    n = len(y_true)
    reliability /= n
    resolution /= n

    return {
        "brier_score": float(brier_score_loss(y_true, y_prob)),
        "reliability": float(reliability),
        "resolution": float(resolution),
        "uncertainty": float(uncertainty),
        "base_rate": float(base_rate),
    }


def confidence_stratified_metrics(y_true, y_prob):
    """
    Compute accuracy and calibration stratified by prediction confidence.

    Confidence = max(P, 1-P) — how certain the model is, regardless of direction.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)

    confidence = np.maximum(y_prob, 1 - y_prob)
    y_pred = (y_prob >= 0.5).astype(int)
    correct = (y_pred == y_true).astype(int)

    bands = [
        ("50-55%", 0.50, 0.55),
        ("55-60%", 0.55, 0.60),
        ("60-65%", 0.60, 0.65),
        ("65-70%", 0.65, 0.70),
        ("70-75%", 0.70, 0.75),
        ("75-80%", 0.75, 0.80),
        ("80%+",   0.80, 1.01),
    ]

    results = []
    for label, lo, hi in bands:
        mask = (confidence >= lo) & (confidence < hi)
        n = mask.sum()
        if n == 0:
            results.append({"band": label, "count": 0, "accuracy": None,
                            "avg_confidence": None, "cal_error": None,
                            "overconfident": None})
            continue

        acc = correct[mask].mean()
        avg_conf = confidence[mask].mean()
        avg_outcome = y_true[mask].mean()
        # For the "winning" side prediction, expected accuracy = avg confidence
        cal_error = avg_conf - acc  # positive = overconfident
        results.append({
            "band": label,
            "count": int(n),
            "accuracy": float(acc),
            "avg_confidence": float(avg_conf),
            "cal_error": float(cal_error),
            "overconfident": float(cal_error) > 0.02,
        })

    return results


def overconfidence_analysis(y_true, y_prob, thresholds=(0.70, 0.75, 0.80, 0.85)):
    """
    For each confidence threshold, compute how often "confident" predictions are wrong.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)

    confidence = np.maximum(y_prob, 1 - y_prob)
    y_pred = (y_prob >= 0.5).astype(int)
    correct = (y_pred == y_true)

    results = []
    for thresh in thresholds:
        mask = confidence >= thresh
        n = mask.sum()
        if n == 0:
            results.append({"threshold": thresh, "count": 0,
                            "accuracy": None, "error_rate": None})
            continue
        acc = correct[mask].mean()
        results.append({
            "threshold": float(thresh),
            "count": int(n),
            "accuracy": float(acc),
            "error_rate": float(1 - acc),
            "expected_accuracy": float(confidence[mask].mean()),
        })

    return results


def race_type_breakdown(y_true, y_prob, X_test):
    """
    Compute metrics broken down by race type.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    y_pred = (y_prob >= 0.5).astype(int)

    breakdowns = {}

    # By one-day vs stage race
    if "race_is_one_day_race" in X_test.columns:
        for val, label in [(1, "one_day"), (0, "stage_race")]:
            mask = X_test["race_is_one_day_race"].values == val
            if mask.sum() < 50:
                continue
            yt, yp = y_true[mask], y_prob[mask]
            breakdowns[label] = {
                "count": int(mask.sum()),
                "accuracy": float(accuracy_score(yt, (yp >= 0.5).astype(int))),
                "roc_auc": float(roc_auc_score(yt, yp)),
                "brier": float(brier_score_loss(yt, yp)),
                "ece": float(expected_calibration_error(yt, yp)[0]),
            }

    # By course profile
    if "race_profile_icon_num" in X_test.columns:
        icon_vals = X_test["race_profile_icon_num"].values
        for label, vals in [("flat", [0, 1]), ("hilly", [2, 3]), ("mountain", [4, 5])]:
            mask = np.isin(icon_vals, vals)
            if mask.sum() < 50:
                continue
            yt, yp = y_true[mask], y_prob[mask]
            breakdowns[label] = {
                "count": int(mask.sum()),
                "accuracy": float(accuracy_score(yt, (yp >= 0.5).astype(int))),
                "roc_auc": float(roc_auc_score(yt, yp)),
                "brier": float(brier_score_loss(yt, yp)),
                "ece": float(expected_calibration_error(yt, yp)[0]),
            }

    # By ITT
    if "race_is_itt" in X_test.columns:
        mask = X_test["race_is_itt"].values == 1
        if mask.sum() >= 50:
            yt, yp = y_true[mask], y_prob[mask]
            breakdowns["itt"] = {
                "count": int(mask.sum()),
                "accuracy": float(accuracy_score(yt, (yp >= 0.5).astype(int))),
                "roc_auc": float(roc_auc_score(yt, yp)),
                "brier": float(brier_score_loss(yt, yp)),
                "ece": float(expected_calibration_error(yt, yp)[0]),
            }

    return breakdowns


def save_calibration_plot(y_true, y_prob, bin_data, output_path):
    """Save calibration curve plot to file."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        log.warning("matplotlib not available, skipping plot")
        return

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Left: Reliability diagram
    ax = axes[0]
    bins_with_data = [b for b in bin_data if b["count"] > 0]
    if bins_with_data:
        x = [b["avg_conf"] for b in bins_with_data]
        y = [b["avg_acc"] for b in bins_with_data]
        sizes = [max(20, min(200, b["count"] / 5)) for b in bins_with_data]
        ax.scatter(x, y, s=sizes, alpha=0.7, zorder=3)
        ax.plot([0, 1], [0, 1], "k--", alpha=0.5, label="Perfect calibration")
        ax.set_xlabel("Mean predicted probability")
        ax.set_ylabel("Fraction of positives")
        ax.set_title("Calibration Curve (Reliability Diagram)")
        ax.legend()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.grid(True, alpha=0.3)

    # Right: Confidence histogram
    ax = axes[1]
    confidence = np.maximum(y_prob, 1 - y_prob)
    ax.hist(confidence, bins=30, alpha=0.7, edgecolor="black", linewidth=0.5)
    ax.set_xlabel("Prediction confidence (max(P, 1-P))")
    ax.set_ylabel("Count")
    ax.set_title("Confidence Distribution")
    ax.axvline(x=0.5, color="red", linestyle="--", alpha=0.5)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    log.info(f"Saved calibration plot to {output_path}")


# ---------------------------------------------------------------------------
# Main evaluation pipeline
# ---------------------------------------------------------------------------

def run_evaluation(save_plot=False, output_json=False):
    """Run full calibration evaluation on the current model."""
    import pickle

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Force single-threaded for macOS compatibility
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"

    # Load model and scaler
    log.info("Loading model artifacts...")
    with open(os.path.join(MODELS_DIR, "scaler.pkl"), "rb") as f:
        scaler = pickle.load(f)
    with open(os.path.join(MODELS_DIR, "feature_names.json"), "r") as f:
        feature_names = json.load(f)
    with open(os.path.join(MODELS_DIR, "CalibratedXGBoost.pkl"), "rb") as f:
        model = pickle.load(f)

    # Build data
    log.info("Building H2H pairs...")
    pairs_df = build_pairs_sampled()
    log.info(f"Built {len(pairs_df)} pairs")

    log.info("Computing features...")
    feature_df = build_feature_matrix(pairs_df)
    log.info(f"Feature matrix: {feature_df.shape}")

    # Split (same as benchmark)
    stage_urls = pairs_df.loc[feature_df.index, "stage_url"].reset_index(drop=True)
    feature_df = feature_df.reset_index(drop=True)
    X_train, X_test, y_train, y_test = stratified_stage_split(feature_df, stage_urls)

    log.info(f"Train: {len(X_train)}, Test: {len(X_test)}")

    # Ensure feature alignment
    X_test_aligned = X_test[feature_names] if set(feature_names).issubset(X_test.columns) else X_test
    X_test_scaled = scaler.transform(X_test_aligned)

    # Get predictions
    y_prob = model.predict_proba(X_test_scaled)[:, 1]
    y_true = y_test.values.astype(float)
    y_pred = (y_prob >= 0.5).astype(int)

    # ===================================================================
    # Compute all metrics
    # ===================================================================

    print("\n" + "=" * 70)
    print("CALIBRATION & PROBABILITY QUALITY EVALUATION")
    print("=" * 70)

    # Overall metrics
    overall = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "roc_auc": float(roc_auc_score(y_true, y_prob)),
        "log_loss": float(log_loss(y_true, y_prob)),
        "brier_score": float(brier_score_loss(y_true, y_prob)),
        "n_test": int(len(y_true)),
    }
    print(f"\n{'OVERALL METRICS':^40}")
    print(f"  Accuracy:    {overall['accuracy']:.4f}")
    print(f"  ROC-AUC:     {overall['roc_auc']:.4f}")
    print(f"  Log Loss:    {overall['log_loss']:.4f}")
    print(f"  Brier Score: {overall['brier_score']:.4f}")
    print(f"  N (test):    {overall['n_test']}")

    # ECE
    ece, bin_data = expected_calibration_error(y_true, y_prob)
    overall["ece"] = ece
    print(f"\n  ECE (15 bins): {ece:.4f}")

    # Brier decomposition
    brier = brier_decomposition(y_true, y_prob)
    print(f"\n{'BRIER SCORE DECOMPOSITION':^40}")
    print(f"  Brier Score:  {brier['brier_score']:.4f}")
    print(f"  Reliability:  {brier['reliability']:.4f}  (lower = better calibrated)")
    print(f"  Resolution:   {brier['resolution']:.4f}  (higher = more discriminating)")
    print(f"  Uncertainty:  {brier['uncertainty']:.4f}  (inherent difficulty)")
    print(f"  Base rate:    {brier['base_rate']:.4f}")
    # Verify: Brier ≈ Reliability - Resolution + Uncertainty
    recon = brier['reliability'] - brier['resolution'] + brier['uncertainty']
    print(f"  Check: R-Res+U = {recon:.4f} (should ≈ Brier)")

    # Calibration curve data
    print(f"\n{'CALIBRATION CURVE DATA':^40}")
    print(f"  {'Bin':>8}  {'Count':>6}  {'Avg Conf':>9}  {'Actual':>8}  {'Error':>7}")
    for b in bin_data:
        if b["count"] > 0:
            icon = "✅" if b["cal_error"] < 0.03 else "⚠️" if b["cal_error"] < 0.06 else "❌"
            print(f"  {icon} {b['bin_lo']:.2f}-{b['bin_hi']:.2f}  "
                  f"{b['count']:>5}  {b['avg_conf']:>8.3f}  "
                  f"{b['avg_acc']:>7.3f}  {b['cal_error']:>6.3f}")

    # Confidence-stratified
    conf_metrics = confidence_stratified_metrics(y_true, y_prob)
    print(f"\n{'CONFIDENCE-STRATIFIED METRICS':^40}")
    print(f"  {'Band':<10}  {'Count':>6}  {'Accuracy':>9}  {'Avg Conf':>9}  {'Cal Err':>8}  {'Status':>10}")
    for m in conf_metrics:
        if m["count"] > 0:
            status = "⚠️ OVERCONF" if m["overconfident"] else "✅ OK"
            print(f"  {m['band']:<10}  {m['count']:>6}  "
                  f"{m['accuracy']:>8.1%}  {m['avg_confidence']:>8.1%}  "
                  f"{m['cal_error']:>+7.3f}  {status}")

    # Overconfidence analysis
    overconf = overconfidence_analysis(y_true, y_prob)
    print(f"\n{'OVERCONFIDENCE ANALYSIS':^40}")
    print(f"  {'Threshold':>10}  {'Count':>6}  {'Accuracy':>9}  {'Expected':>9}  {'Error Rate':>10}")
    for o in overconf:
        if o["count"] > 0:
            icon = "✅" if o["accuracy"] >= o["expected_accuracy"] - 0.03 else "⚠️"
            print(f"  {icon} ≥{o['threshold']:.0%}       "
                  f"{o['count']:>5}  {o['accuracy']:>8.1%}  "
                  f"{o['expected_accuracy']:>8.1%}  {o['error_rate']:>9.1%}")

    # Race type breakdown
    race_breakdown = race_type_breakdown(y_true, y_prob, X_test)
    if race_breakdown:
        print(f"\n{'RACE TYPE BREAKDOWN':^40}")
        print(f"  {'Type':<12}  {'Count':>6}  {'Acc':>7}  {'AUC':>7}  {'Brier':>7}  {'ECE':>7}")
        for rtype, metrics in race_breakdown.items():
            print(f"  {rtype:<12}  {metrics['count']:>6}  "
                  f"{metrics['accuracy']:>6.3f}  {metrics['roc_auc']:>6.3f}  "
                  f"{metrics['brier']:>6.3f}  {metrics['ece']:>6.3f}")

    # Prediction distribution
    print(f"\n{'PREDICTION DISTRIBUTION':^40}")
    print(f"  Mean P(A>B):     {y_prob.mean():.4f}")
    print(f"  Std P(A>B):      {y_prob.std():.4f}")
    print(f"  Min:             {y_prob.min():.4f}")
    print(f"  Max:             {y_prob.max():.4f}")
    print(f"  P < 0.10:        {(y_prob < 0.10).sum()} ({(y_prob < 0.10).mean():.1%})")
    print(f"  P > 0.90:        {(y_prob > 0.90).sum()} ({(y_prob > 0.90).mean():.1%})")
    print(f"  P in [0.45,0.55]:{(np.abs(y_prob - 0.5) < 0.05).sum()} "
          f"({(np.abs(y_prob - 0.5) < 0.05).mean():.1%})")

    print("\n" + "=" * 70)

    # Collect all results
    all_metrics = {
        "overall": overall,
        "brier_decomposition": brier,
        "calibration_bins": bin_data,
        "confidence_bands": conf_metrics,
        "overconfidence": overconf,
        "race_type_breakdown": race_breakdown,
        "prediction_distribution": {
            "mean": float(y_prob.mean()),
            "std": float(y_prob.std()),
            "min": float(y_prob.min()),
            "max": float(y_prob.max()),
        },
    }

    # Save plot
    if save_plot:
        plot_path = os.path.join(MODELS_DIR, "calibration_plot.png")
        save_calibration_plot(y_true, y_prob, bin_data, plot_path)

    # Save JSON
    if output_json:
        json_path = os.path.join(MODELS_DIR, "calibration_metrics.json")
        with open(json_path, "w") as f:
            json.dump(all_metrics, f, indent=2)
        log.info(f"Saved metrics to {json_path}")

    return all_metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate model calibration and probability quality")
    parser.add_argument("--plot", action="store_true", help="Save calibration plot")
    parser.add_argument("--json", action="store_true", help="Save metrics as JSON")
    args = parser.parse_args()

    run_evaluation(save_plot=args.plot, output_json=args.json)
