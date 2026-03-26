#!/usr/bin/env python3
"""
Full training pipeline: build pairs → compute features → train models.
Run after scraping data.

Usage:
  python -u scripts/train.py          # Skip NN (fast, ~25 min)
  python -u scripts/train.py --nn     # Include Neural Network (slow)
"""

import os
import sys
import logging
import time
import argparse

# Prevent thread deadlock between sklearn and PyTorch on macOS
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
    parser.add_argument("--nn", action="store_true",
                        help="Include Neural Network in benchmark (slow, off by default)")
    parser.add_argument("--select-features", type=int, default=0, metavar="N",
                        help="Select top N features by permutation importance (0 = use all)")
    args = parser.parse_args()

    t0 = time.time()

    log.info("=== Step 1: Building H2H pairs ===")
    t1 = time.time()
    pairs_df = build_pairs_sampled(max_rank=50, pairs_per_stage=200)

    if len(pairs_df) == 0:
        log.error("No pairs built — is the database populated? Run scrape_all.py first.")
        sys.exit(1)

    log.info(f"Built {len(pairs_df)} pairs ({_elapsed(t1)})")
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

    dates = pairs_df["stage_url"].map(date_map)
    # Align with feature_df (which may have dropped some rows)
    dates = dates.iloc[:len(feature_df)].reset_index(drop=True)

    log.info("\n=== Step 3: Training and benchmarking models ===")
    t3 = time.time()
    results = run_benchmark(feature_df, dates, skip_nn=not args.nn,
                            select_features=args.select_features)

    log.info(f"Training complete ({_elapsed(t3)})")
    log.info(f"\n✅ Done! Total time: {_elapsed(t0)}")
    log.info(f"Best model: {results['best_model_name']}")
    log.info("Models saved to models/trained/")
    log.info("Run the web app with: python -m webapp.app")


if __name__ == "__main__":
    main()
