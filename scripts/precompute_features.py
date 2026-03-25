#!/usr/bin/env python3
"""
Pre-compute rider and race features and cache to parquet files.

Run this after scraping new data. Training will then use the cache
instead of recomputing features from scratch (~18 min → ~30 sec).

Usage:
    python scripts/precompute_features.py              # incremental (only new data)
    python scripts/precompute_features.py --full        # recompute everything
    python scripts/precompute_features.py --max-rank 50 # include top-50 riders
"""

import os
import sys
import logging
import argparse
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from features.feature_store import precompute_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Pre-compute and cache rider/race features")
    parser.add_argument("--full", action="store_true",
                        help="Recompute all features from scratch (ignore existing cache)")
    parser.add_argument("--max-rank", type=int, default=50,
                        help="Max finishing rank to include (default: 50)")
    args = parser.parse_args()

    t0 = time.time()
    precompute_all(max_rank=args.max_rank, incremental=not args.full)
    elapsed = time.time() - t0
    print(f"\n✅ Feature pre-computation complete in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
