"""Tests for build_pairs_sampled seed reproducibility."""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.scraper import get_db
from data.builder import build_pairs_sampled


@pytest.fixture
def seeded_db(tmp_path):
    """Minimal DB with enough riders and results to trigger random sampling."""
    db_path = str(tmp_path / "test.db")
    conn = get_db(db_path)

    conn.execute("""
        INSERT INTO races (url, name, year, nationality, is_one_day_race, uci_tour)
        VALUES ('race/test/2024', 'Test Race', 2024, 'Belgium', 0, '1.UWT')
    """)
    conn.execute("""
        INSERT INTO stages (url, race_url, stage_name, date, distance, vertical_meters,
                            profile_score, profile_icon, stage_type, is_one_day_race)
        VALUES ('race/test/2024/stage-1', 'race/test/2024', 'Stage 1',
                '2024-04-14', 180.0, 1500, 40, 'p2', 'RR', 0)
    """)

    # Insert 25 riders and results so random sampling kicks in (pairs_per_stage default 200,
    # but 25 riders = 300 possible pairs which forces sampling)
    for i in range(25):
        conn.execute(
            "INSERT OR IGNORE INTO riders (url, name) VALUES (?, ?)",
            (f"rider/r{i}", f"Rider {i}")
        )
        conn.execute(
            "INSERT OR IGNORE INTO results (stage_url, rider_url, rider_name, rank) VALUES (?, ?, ?, ?)",
            ("race/test/2024/stage-1", f"rider/r{i}", f"Rider {i}", i + 1)
        )

    conn.commit()
    conn.close()
    return db_path


def test_same_seed_produces_identical_pairs(seeded_db):
    """Two calls with the same seed must produce identical pair sets."""
    df1 = build_pairs_sampled(db_path=seeded_db, seed=42)
    df2 = build_pairs_sampled(db_path=seeded_db, seed=42)

    assert list(df1["rider_a_url"]) == list(df2["rider_a_url"])
    assert list(df1["rider_b_url"]) == list(df2["rider_b_url"])
    assert list(df1["label"]) == list(df2["label"])


def test_different_seeds_produce_different_pairs(seeded_db):
    """Two calls with different seeds should (very likely) differ."""
    df1 = build_pairs_sampled(db_path=seeded_db, seed=42)
    df2 = build_pairs_sampled(db_path=seeded_db, seed=99)

    # Extremely unlikely to be identical with different seeds on 25 riders
    pairs1 = list(zip(df1["rider_a_url"], df1["rider_b_url"]))
    pairs2 = list(zip(df2["rider_a_url"], df2["rider_b_url"]))
    assert pairs1 != pairs2


def test_default_seed_is_reproducible(seeded_db):
    """Default call (no explicit seed) should still be reproducible."""
    df1 = build_pairs_sampled(db_path=seeded_db)
    df2 = build_pairs_sampled(db_path=seeded_db)

    assert list(df1["rider_a_url"]) == list(df2["rider_a_url"])
