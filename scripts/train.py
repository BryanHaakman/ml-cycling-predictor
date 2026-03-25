#!/usr/bin/env python3
"""
Full training pipeline: build pairs → compute features → train models.
Run after scraping data.
"""

import os
import sys
import logging

# Prevent thread deadlock between sklearn and PyTorch
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import torch
torch.set_num_threads(1)

import pandas as pd

from data.scraper import get_db, DB_PATH
from data.builder import build_pairs_sampled
from features.pipeline import build_feature_matrix
from models.benchmark import run_benchmark

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main():
    log.info("=== Step 1: Building H2H pairs ===")
    pairs_df = build_pairs_sampled(max_rank=50, pairs_per_stage=200)

    if len(pairs_df) == 0:
        log.error("No pairs built — is the database populated? Run scrape_all.py first.")
        sys.exit(1)

    log.info(f"Built {len(pairs_df)} pairs")
    log.info(f"Label distribution:\n{pairs_df['label'].value_counts().to_string()}")

    log.info("\n=== Step 2: Computing features ===")
    feature_df = build_feature_matrix(pairs_df)

    if len(feature_df) == 0:
        log.error("No features computed — check the database.")
        sys.exit(1)

    log.info(f"Feature matrix: {feature_df.shape[0]} rows × {feature_df.shape[1]} columns")

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
    results = run_benchmark(feature_df, dates)

    log.info(f"\n✅ Done! Best model: {results['best_model_name']}")
    log.info("Models saved to models/trained/")
    log.info("Run the web app with: python -m webapp.app")


if __name__ == "__main__":
    main()
