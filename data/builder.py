"""
Build head-to-head training pairs from cached race data.

For each stage/race result, generates pairs of riders and labels
indicating which rider finished ahead.
"""

import sqlite3
import random
import logging
from typing import Optional

import pandas as pd

from data.scraper import get_db, DB_PATH

log = logging.getLogger(__name__)

MAX_RANK_CUTOFF = 50  # Only pair riders who both finished in top N


def build_pairs(db_path: str = DB_PATH, max_rank: int = MAX_RANK_CUTOFF, seed: int = 42) -> pd.DataFrame:
    """
    Build all head-to-head pairs from cached results.

    For each stage, takes all riders who finished in top `max_rank` and
    creates ordered pairs (rider_a, rider_b) where rider_a finished ahead.
    Then randomly assigns which rider is "A" to avoid ordering bias.

    Returns DataFrame with columns:
        stage_url, rider_a_url, rider_b_url, label (1 = A finishes ahead)
    """
    random.seed(seed)
    conn = get_db(db_path)

    # Get all stages with results
    stages = conn.execute("""
        SELECT DISTINCT s.url, s.date, s.race_url
        FROM stages s
        JOIN results r ON r.stage_url = s.url
        WHERE s.date IS NOT NULL
        ORDER BY s.date
    """).fetchall()

    pairs = []
    for stage in stages:
        stage_url = stage["url"]

        # Get finishers ranked in top N (exclude DNF/DNS — rank must exist)
        results = conn.execute("""
            SELECT rider_url, rank FROM results
            WHERE stage_url = ? AND rank IS NOT NULL AND rank <= ?
            ORDER BY rank
        """, (stage_url, max_rank)).fetchall()

        riders = [(r["rider_url"], r["rank"]) for r in results]

        # Generate pairs — each unique combination of two riders
        for i in range(len(riders)):
            for j in range(i + 1, len(riders)):
                url_a, rank_a = riders[i]
                url_b, rank_b = riders[j]

                # Randomly swap to avoid always having the better rider as A
                if random.random() < 0.5:
                    pairs.append({
                        "stage_url": stage_url,
                        "rider_a_url": url_a,
                        "rider_b_url": url_b,
                        "label": 1,  # A finished ahead
                    })
                else:
                    pairs.append({
                        "stage_url": stage_url,
                        "rider_a_url": url_b,
                        "rider_b_url": url_a,
                        "label": 0,  # A finished behind
                    })

    conn.close()
    df = pd.DataFrame(pairs)
    log.info(f"Built {len(df)} pairs from {len(stages)} stages")
    return df


def build_pairs_sampled(
    db_path: str = DB_PATH,
    max_rank: int = MAX_RANK_CUTOFF,
    pairs_per_stage: int = 200,
    wt_only: bool = False,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Like build_pairs but samples a fixed number of pairs per stage
    to keep the dataset manageable for very large result sets.

    If wt_only=True, only include stages from World Tour races
    (uci_tour IN ('1.UWT', '2.UWT')).
    """
    random.seed(seed)
    conn = get_db(db_path)

    if wt_only:
        stages = conn.execute("""
            SELECT DISTINCT s.url, s.date, s.race_url
            FROM stages s
            JOIN results r ON r.stage_url = s.url
            JOIN races ra ON s.race_url = ra.url
            WHERE s.date IS NOT NULL
              AND ra.uci_tour IN ('1.UWT', '2.UWT')
            ORDER BY s.date
        """).fetchall()
    else:
        stages = conn.execute("""
            SELECT DISTINCT s.url, s.date, s.race_url
            FROM stages s
            JOIN results r ON r.stage_url = s.url
            WHERE s.date IS NOT NULL
            ORDER BY s.date
        """).fetchall()

    all_pairs = []
    for stage in stages:
        stage_url = stage["url"]

        results = conn.execute("""
            SELECT rider_url, rank FROM results
            WHERE stage_url = ? AND rank IS NOT NULL AND rank <= ?
            ORDER BY rank
        """, (stage_url, max_rank)).fetchall()

        riders = [(r["rider_url"], r["rank"]) for r in results]
        n = len(riders)
        if n < 2:
            continue

        # Generate candidate pairs
        stage_pairs = []
        max_possible = n * (n - 1) // 2
        sample_size = min(pairs_per_stage, max_possible)

        if max_possible <= pairs_per_stage:
            # Small enough — use all pairs
            for i in range(n):
                for j in range(i + 1, n):
                    stage_pairs.append((i, j))
        else:
            # Sample random pairs
            seen = set()
            while len(stage_pairs) < sample_size:
                i = random.randint(0, n - 1)
                j = random.randint(0, n - 1)
                if i == j:
                    continue
                key = (min(i, j), max(i, j))
                if key not in seen:
                    seen.add(key)
                    stage_pairs.append(key)

        for i, j in stage_pairs:
            url_better, rank_better = riders[i] if riders[i][1] < riders[j][1] else riders[j]
            url_worse, rank_worse = riders[j] if riders[i][1] < riders[j][1] else riders[i]

            if random.random() < 0.5:
                all_pairs.append({
                    "stage_url": stage_url,
                    "rider_a_url": url_better,
                    "rider_b_url": url_worse,
                    "label": 1,
                })
            else:
                all_pairs.append({
                    "stage_url": stage_url,
                    "rider_a_url": url_worse,
                    "rider_b_url": url_better,
                    "label": 0,
                })

    conn.close()
    df = pd.DataFrame(all_pairs)
    log.info(f"Built {len(df)} sampled pairs from {len(stages)} stages")
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    df = build_pairs_sampled()
    out_path = "data/pairs.parquet"
    df.to_parquet(out_path, index=False)
    print(f"Saved {len(df)} pairs to {out_path}")
    print(f"Label distribution:\n{df['label'].value_counts()}")
