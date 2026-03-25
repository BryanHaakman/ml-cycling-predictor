"""
Feature store: pre-compute and cache rider features per (rider, stage).

Rider feature computation is the bottleneck (~5 DB queries per rider per pair).
Since features are deterministic for a given (rider_url, stage_url, DB snapshot),
we can compute them once and cache the results.

This turns an 18-minute feature computation step into a ~10-second lookup.
"""

import os
import time
import logging
import sqlite3
from typing import Optional

import pandas as pd
import numpy as np
from tqdm import tqdm

from data.scraper import get_db, DB_PATH
from features.rider_features import compute_rider_features, RIDER_FEATURE_NAMES
from features.race_features import extract_race_features, RACE_FEATURE_NAMES

log = logging.getLogger(__name__)

STORE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
RIDER_FEATURES_PATH = os.path.join(STORE_DIR, "rider_features_cache.parquet")
RACE_FEATURES_PATH = os.path.join(STORE_DIR, "race_features_cache.parquet")


def _get_all_rider_stage_pairs(conn: sqlite3.Connection, max_rank: int = 50) -> list[tuple[str, str, str]]:
    """Get all (rider_url, stage_url, race_date) tuples from the DB."""
    rows = conn.execute("""
        SELECT DISTINCT r.rider_url, r.stage_url, s.date
        FROM results r
        JOIN stages s ON r.stage_url = s.url
        WHERE r.rank IS NOT NULL AND r.rank <= ? AND s.date IS NOT NULL
        ORDER BY s.date, r.stage_url
    """, (max_rank,)).fetchall()
    return [(row["rider_url"], row["stage_url"], row["date"]) for row in rows]


def _get_all_stages(conn: sqlite3.Connection) -> list[dict]:
    """Get all stages for race feature extraction."""
    rows = conn.execute("SELECT * FROM stages WHERE date IS NOT NULL").fetchall()
    return [dict(row) for row in rows]


def load_rider_features_cache() -> Optional[pd.DataFrame]:
    """Load the cached rider features DataFrame, or None if not found."""
    if os.path.exists(RIDER_FEATURES_PATH):
        try:
            df = pd.read_parquet(RIDER_FEATURES_PATH)
            return df
        except Exception as e:
            log.warning(f"Failed to load rider features cache: {e}")
    return None


def load_race_features_cache() -> Optional[pd.DataFrame]:
    """Load the cached race features DataFrame, or None if not found."""
    if os.path.exists(RACE_FEATURES_PATH):
        try:
            df = pd.read_parquet(RACE_FEATURES_PATH)
            return df
        except Exception as e:
            log.warning(f"Failed to load race features cache: {e}")
    return None


def precompute_rider_features(
    db_path: str = DB_PATH,
    max_rank: int = 50,
    incremental: bool = True,
) -> pd.DataFrame:
    """
    Pre-compute rider features for all (rider, stage) combinations.

    Args:
        db_path: Path to the SQLite database
        max_rank: Only include riders who finished at this rank or better
        incremental: If True, only compute features for new (rider, stage) pairs

    Returns:
        DataFrame with columns: rider_url, stage_url, + all RIDER_FEATURE_NAMES
    """
    conn = get_db(db_path)

    all_pairs = _get_all_rider_stage_pairs(conn, max_rank)
    log.info(f"Found {len(all_pairs)} (rider, stage) pairs in DB (max_rank={max_rank})")

    existing_keys = set()
    existing_df = None

    if incremental:
        existing_df = load_rider_features_cache()
        if existing_df is not None:
            existing_keys = set(zip(existing_df["rider_url"], existing_df["stage_url"]))
            log.info(f"Loaded {len(existing_keys)} existing cached features")

    new_pairs = [
        (rider_url, stage_url, race_date)
        for rider_url, stage_url, race_date in all_pairs
        if (rider_url, stage_url) not in existing_keys
    ]

    if not new_pairs:
        log.info("All features already cached — nothing to compute")
        conn.close()
        return existing_df

    log.info(f"Computing features for {len(new_pairs)} new (rider, stage) pairs...")

    rows = []
    for rider_url, stage_url, race_date in tqdm(new_pairs, desc="Pre-computing rider features"):
        feats = compute_rider_features(conn, rider_url, race_date, stage_url)
        row = {"rider_url": rider_url, "stage_url": stage_url}
        for name in RIDER_FEATURE_NAMES:
            row[name] = float(feats.get(name, 0.0) or 0.0)
        rows.append(row)

    conn.close()

    new_df = pd.DataFrame(rows)

    if existing_df is not None and len(existing_df) > 0:
        result = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        result = new_df

    result.to_parquet(RIDER_FEATURES_PATH, index=False)
    log.info(f"Saved {len(result)} rider features to {RIDER_FEATURES_PATH}")

    return result


def precompute_race_features(db_path: str = DB_PATH) -> pd.DataFrame:
    """
    Pre-compute race features for all stages.

    Returns:
        DataFrame with columns: stage_url, + all RACE_FEATURE_NAMES
    """
    conn = get_db(db_path)
    stages = _get_all_stages(conn)
    conn.close()

    log.info(f"Computing race features for {len(stages)} stages...")

    rows = []
    for stage in stages:
        race_feats = extract_race_features(stage)
        row = {"stage_url": stage["url"]}
        for name in RACE_FEATURE_NAMES:
            row[name] = float(race_feats.get(name, 0.0) or 0.0)
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_parquet(RACE_FEATURES_PATH, index=False)
    log.info(f"Saved {len(df)} race features to {RACE_FEATURES_PATH}")
    return df


def precompute_all(db_path: str = DB_PATH, max_rank: int = 50, incremental: bool = True):
    """Pre-compute both rider and race features."""
    t0 = time.time()
    rider_df = precompute_rider_features(db_path, max_rank, incremental)
    race_df = precompute_race_features(db_path)
    elapsed = time.time() - t0
    log.info(f"Feature pre-computation complete in {elapsed:.1f}s "
             f"({len(rider_df)} rider features, {len(race_df)} race features)")
    return rider_df, race_df
