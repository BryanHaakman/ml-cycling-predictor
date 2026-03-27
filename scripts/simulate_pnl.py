#!/usr/bin/env python3
"""
Simulate P&L across test data with different Kelly strategies and scaling functions.

Generates realistic bookmaker odds by adding noise + margin to the model's
probability estimates, then simulates bankroll progression under each strategy.

Usage:
    python scripts/simulate_pnl.py
    python scripts/simulate_pnl.py --bankroll 500 --margin 0.06
    python scripts/simulate_pnl.py --split time   # use time-based split instead
"""

import os
import sys
import math
import argparse
import logging

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.scraper import get_db
from data.builder import build_pairs_sampled
from features.pipeline import build_feature_matrix
from models.benchmark import stratified_stage_split, time_based_split

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Kelly scaling functions ──────────────────────────────────────────────

def scale_linear(prob):
    """Linear scaling: 50% → 0.5, 60% → 0.75, 70%+ → 1.0"""
    return max(0.5, min(1.0, (prob - 0.5) / 0.2))


def scale_sigmoid(prob, center=0.65, steepness=20):
    """Sigmoid scaling: stays low until ~65%, then ramps up."""
    return 1.0 / (1.0 + math.exp(-(prob - center) * steepness))


def scale_none(prob):
    """No scaling — raw Kelly."""
    return 1.0


SCALING_FUNCS = {
    "none": scale_none,
    "linear": scale_linear,
    "sigmoid": scale_sigmoid,
}

# ── Odds simulation ─────────────────────────────────────────────────────

def simulate_market_odds(model_probs, margin=0.05, noise_std=0.08, seed=42):
    """
    Generate realistic bookmaker odds from model probabilities.

    The 'market' is a noisier estimator than our model. We add Gaussian noise
    to the model's probability and apply a bookmaker margin (overround).

    Returns decimal odds for rider A winning.
    """
    rng = np.random.RandomState(seed)
    noise = rng.normal(0, noise_std, size=len(model_probs))
    market_prob = np.clip(model_probs + noise, 0.15, 0.85)
    # Apply margin: odds are shorter than fair
    decimal_odds = 1.0 / (market_prob * (1 + margin))
    return decimal_odds


# ── Kelly calculation ────────────────────────────────────────────────────

def kelly_fraction(model_prob, decimal_odds, max_frac=0.25):
    """Raw Kelly fraction, capped."""
    b = decimal_odds - 1.0
    if b <= 0:
        return 0.0
    f = (b * model_prob - (1 - model_prob)) / b
    return max(0.0, min(f, max_frac))


# ── Simulation ───────────────────────────────────────────────────────────

def simulate_strategy(model_probs, outcomes, odds, kelly_frac_name, scale_name,
                      bankroll_start=1000.0, flat_stake=True):
    """
    Simulate a betting strategy across all test pairs.

    Args:
        flat_stake: If True, stake is a fraction of the STARTING bankroll
                    (realistic for H2H betting). If False, compound Kelly.

    Returns dict with final bankroll, P&L, max drawdown, # bets, win rate.
    """
    scale_fn = SCALING_FUNCS[scale_name]

    kelly_multipliers = {
        "full": 1.0,
        "half": 0.5,
        "quarter": 0.25,
    }
    kelly_mult = kelly_multipliers[kelly_frac_name]

    bankroll = bankroll_start
    peak = bankroll
    max_drawdown = 0.0
    n_bets = 0
    n_wins = 0
    total_staked = 0.0

    for i in range(len(model_probs)):
        p = model_probs[i]
        o = odds[i]
        outcome = outcomes[i]

        kf = kelly_fraction(p, o)
        if kf <= 0:
            continue

        scale = scale_fn(p)
        stake_frac = kf * kelly_mult * scale

        # Flat staking: fraction of starting bankroll (not current)
        stake_base = bankroll_start if flat_stake else bankroll
        stake = stake_base * stake_frac

        if stake < 0.01 or bankroll <= 0:
            continue

        # Don't bet more than current bankroll
        stake = min(stake, bankroll)

        n_bets += 1
        total_staked += stake

        if outcome == 1:
            profit = stake * (o - 1)
            bankroll += profit
            n_wins += 1
        else:
            bankroll -= stake

        peak = max(peak, bankroll)
        drawdown = (peak - bankroll) / peak if peak > 0 else 0
        max_drawdown = max(max_drawdown, drawdown)

    return {
        "kelly": kelly_frac_name,
        "scaling": scale_name,
        "final_bankroll": bankroll,
        "pnl": bankroll - bankroll_start,
        "pnl_pct": (bankroll - bankroll_start) / bankroll_start * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "n_bets": n_bets,
        "win_rate": n_wins / n_bets * 100 if n_bets > 0 else 0,
        "total_staked": total_staked,
        "roi_pct": (bankroll - bankroll_start) / total_staked * 100 if total_staked > 0 else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Simulate P&L with different Kelly strategies")
    parser.add_argument("--bankroll", type=float, default=1000.0,
                        help="Starting bankroll (default: £1000)")
    parser.add_argument("--margin", type=float, default=0.05,
                        help="Bookmaker margin/overround (default: 0.05 = 5%%)")
    parser.add_argument("--noise", type=float, default=0.08,
                        help="Market noise std dev (default: 0.08)")
    parser.add_argument("--split", choices=["stratified", "time"], default="stratified",
                        help="Split mode (default: stratified)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    # ── Load data ────────────────────────────────────────────────────────
    log.info("Building pairs...")
    pairs_df = build_pairs_sampled(max_rank=50, pairs_per_stage=200)

    log.info("Computing features...")
    feature_df = build_feature_matrix(pairs_df)

    conn = get_db()
    date_map = {s["url"]: s["date"] for s in conn.execute("SELECT url, date FROM stages").fetchall()}
    conn.close()

    dates = pairs_df["stage_url"].map(date_map).iloc[:len(feature_df)].reset_index(drop=True)
    stage_urls = pairs_df["stage_url"].iloc[:len(feature_df)].reset_index(drop=True)

    # ── Split ────────────────────────────────────────────────────────────
    if args.split == "stratified":
        X_train, X_test, y_train, y_test = stratified_stage_split(feature_df, stage_urls)
    else:
        X_train, X_test, y_train, y_test = time_based_split(feature_df, dates)

    log.info(f"Test set: {len(X_test)} pairs")

    # ── Train a quick XGBoost for predictions ────────────────────────────
    from sklearn.preprocessing import StandardScaler
    from sklearn.calibration import CalibratedClassifierCV
    import xgboost as xgb

    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"

    log.info("Training CalibratedXGBoost for simulation...")
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    cal_xgb = CalibratedClassifierCV(
        xgb.XGBClassifier(
            n_estimators=300, max_depth=8, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            min_child_weight=10, random_state=42, eval_metric="logloss",
        ),
        method="isotonic", cv=5,
    )
    cal_xgb.fit(X_train_s, y_train)
    model_probs = cal_xgb.predict_proba(X_test_s)[:, 1]
    outcomes = y_test.values

    # ── Generate market odds ─────────────────────────────────────────────
    odds = simulate_market_odds(model_probs, margin=args.margin,
                                noise_std=args.noise, seed=args.seed)

    log.info(f"Odds range: {odds.min():.2f} – {odds.max():.2f}, "
             f"median: {np.median(odds):.2f}")

    # ── Run simulations ──────────────────────────────────────────────────
    kelly_levels = ["full", "half", "quarter"]
    scale_types = ["none", "linear", "sigmoid"]

    results = []
    for kl in kelly_levels:
        for st in scale_types:
            r = simulate_strategy(model_probs, outcomes, odds, kl, st,
                                  bankroll_start=args.bankroll)
            results.append(r)

    # ── Print results ────────────────────────────────────────────────────
    print(f"\n{'=' * 90}")
    print(f"P&L SIMULATION  (bankroll: £{args.bankroll:.0f}, "
          f"margin: {args.margin:.0%}, noise: {args.noise}, "
          f"{len(X_test)} test pairs)")
    print(f"{'=' * 90}")

    df = pd.DataFrame(results)
    df = df.sort_values("pnl", ascending=False)

    print(f"\n{'Strategy':<22} {'P&L':>10} {'P&L%':>8} {'ROI%':>8} "
          f"{'MaxDD%':>8} {'Bets':>7} {'Win%':>7} {'Final£':>10}")
    print("-" * 90)

    for _, row in df.iterrows():
        label = f"{row['kelly']:>7} + {row['scaling']:<8}"
        pnl_color = "+" if row["pnl"] >= 0 else ""
        print(f"{label:<22} {pnl_color}£{row['pnl']:>8.2f} "
              f"{row['pnl_pct']:>7.1f}% {row['roi_pct']:>7.2f}% "
              f"{row['max_drawdown_pct']:>7.1f}% {row['n_bets']:>7} "
              f"{row['win_rate']:>6.1f}% £{row['final_bankroll']:>9.2f}")

    print(f"\n{'=' * 90}")

    # Highlight best by different criteria
    best_pnl = df.iloc[0]
    best_roi = df.loc[df["roi_pct"].idxmax()]
    safest = df.loc[df["max_drawdown_pct"].idxmin()]

    print(f"\n  💰 Best P&L:      {best_pnl['kelly']} + {best_pnl['scaling']}"
          f"  (£{best_pnl['pnl']:+.2f}, {best_pnl['pnl_pct']:+.1f}%)")
    print(f"  📈 Best ROI:      {best_roi['kelly']} + {best_roi['scaling']}"
          f"  ({best_roi['roi_pct']:.2f}% return on stakes)")
    print(f"  🛡️  Lowest risk:   {safest['kelly']} + {safest['scaling']}"
          f"  (max drawdown {safest['max_drawdown_pct']:.1f}%)")


if __name__ == "__main__":
    main()
