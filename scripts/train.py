#!/usr/bin/env python3
"""
Full training pipeline: build pairs → compute features → train models.
Run after scraping data.

Usage:
  python -u scripts/train.py
"""

import os
import sys
import logging
import time
import json
import argparse
from datetime import datetime

# Prevent thread deadlock between sklearn and XGBoost on macOS
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from data.scraper import get_db, DB_PATH
from data.builder import build_pairs_sampled
from features.pipeline import build_feature_matrix
from models.benchmark import run_benchmark

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _elapsed(start):
    secs = time.time() - start
    mins, secs = divmod(int(secs), 60)
    return f"{mins}m {secs}s"


def main():
    parser = argparse.ArgumentParser(description="Train cycling H2H predictor")
    parser.add_argument("--select-features", type=int, default=150, metavar="N",
                        help="Select top N features by permutation importance (0 = use all, default: 150)")
    parser.add_argument("--wt-only", action="store_true",
                        help="Train only on World Tour races (uci_tour 1.UWT/2.UWT)")
    parser.add_argument("--split", choices=["stratified", "time"], default="stratified",
                        help="Split mode: 'stratified' (80/20 by stage, default) or 'time' (test on 2025-2026)")
    args = parser.parse_args()

    t0 = time.time()

    log.info("=== Step 1: Building H2H pairs ===")
    t1 = time.time()
    pairs_df = build_pairs_sampled(max_rank=50, pairs_per_stage=200,
                                   wt_only=args.wt_only)

    if len(pairs_df) == 0:
        log.error("No pairs built — is the database populated? Run scrape_all.py first.")
        sys.exit(1)

    log.info(f"Built {len(pairs_df)} pairs ({_elapsed(t1)})")
    if args.wt_only:
        log.info("⚡ World Tour only mode — excluded lower-tier races")
    log.info(f"Label distribution:\n{pairs_df['label'].value_counts().to_string()}")

    log.info("\n=== Step 2: Computing features ===")
    t2 = time.time()
    feature_df = build_feature_matrix(pairs_df)

    if len(feature_df) == 0:
        log.error("No features computed — check the database.")
        sys.exit(1)

    log.info(f"Feature matrix: {feature_df.shape[0]} rows × {feature_df.shape[1]} columns ({_elapsed(t2)})")

    # Get dates for time-based splitting
    conn = get_db()
    date_map = {}
    stages = conn.execute("SELECT url, date FROM stages").fetchall()
    for s in stages:
        date_map[s["url"]] = s["date"]
    conn.close()

    # Align with feature_df by index (surviving rows may not be the first N rows)
    dates = pairs_df.loc[feature_df.index, "stage_url"].map(date_map).reset_index(drop=True)

    stage_urls = pairs_df.loc[feature_df.index, "stage_url"].reset_index(drop=True)

    log.info("\n=== Step 3: Training and benchmarking models ===")
    t3 = time.time()
    results = run_benchmark(feature_df, dates,
                            select_features=args.select_features,
                            stage_urls=stage_urls,
                            split_mode=args.split)

    log.info(f"Training complete ({_elapsed(t3)})")

    # Save training metadata for fine-tuning
    meta_path = os.path.join("models", "trained", "training_meta.json")
    conn = get_db()
    latest_date = conn.execute("""
        SELECT MAX(s.date) as d FROM stages s
        JOIN results r ON r.stage_url = s.url WHERE s.date IS NOT NULL
    """).fetchone()["d"]
    conn.close()

    meta = {
        "last_full_train": datetime.now().isoformat(),
        "last_fine_tune": None,
        "fine_tune_count": 0,
        "last_data_date": latest_date,
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    log.info(f"Saved training metadata (data through {latest_date})")

    log.info(f"\n✅ Done! Total time: {_elapsed(t0)}")
    log.info(f"Best model: {results['best_model_name']}")
    log.info("Models saved to models/trained/")
    log.info("Run the web app with: python -m webapp.app")


if __name__ == "__main__":
    main()
