"""
Full feature pipeline: (rider_a, rider_b, stage) → feature vector.

Combines race features + rider features (differenced) + head-to-head history.
"""

import sqlite3
import logging
from typing import Optional

import numpy as np
import pandas as pd
from tqdm import tqdm

from data.scraper import get_db, DB_PATH
from features.race_features import extract_race_features, RACE_FEATURE_NAMES
from features.rider_features import compute_rider_features, RIDER_FEATURE_NAMES

log = logging.getLogger(__name__)


def compute_h2h_history(
    conn: sqlite3.Connection,
    rider_a_url: str,
    rider_b_url: str,
    before_date: str,
) -> dict:
    """Compute head-to-head historical record between two riders."""
    shared = conn.execute("""
        SELECT ra.rank as rank_a, rb.rank as rank_b
        FROM results ra
        JOIN results rb ON ra.stage_url = rb.stage_url
        JOIN stages s ON ra.stage_url = s.url
        WHERE ra.rider_url = ? AND rb.rider_url = ?
        AND s.date < ? AND ra.rank IS NOT NULL AND rb.rank IS NOT NULL
    """, (rider_a_url, rider_b_url, before_date)).fetchall()

    total = len(shared)
    a_wins = sum(1 for r in shared if r["rank_a"] < r["rank_b"])
    b_wins = total - a_wins

    return {
        "h2h_total_races": total,
        "h2h_a_win_rate": a_wins / total if total > 0 else 0.5,
        "h2h_a_wins": a_wins,
        "h2h_b_wins": b_wins,
        "h2h_avg_rank_diff": np.mean(
            [r["rank_a"] - r["rank_b"] for r in shared]
        ) if shared else 0.0,
    }


H2H_FEATURE_NAMES = [
    "h2h_total_races", "h2h_a_win_rate", "h2h_a_wins", "h2h_b_wins",
    "h2h_avg_rank_diff",
]


STARTLIST_FEATURE_NAMES = [
    "field_rank_quality",     # percentile by career_top10_rate (1.0 = best in field)
    "field_rank_form",        # percentile by form_90d_avg_pcs (1.0 = best form)
    "field_strength_ratio",   # rider career_top10_rate / field average
]

STARTLIST_RACE_FEATURE_NAMES = [
    "field_size",             # number of riders in the race
    "field_avg_quality",      # avg career_top10_rate of field
]


def build_feature_vector(
    conn: sqlite3.Connection,
    rider_a_url: str,
    rider_b_url: str,
    stage_url: str,
) -> Optional[dict]:
    """
    Build complete feature vector for a head-to-head prediction.

    Returns dict with all feature names → float values, or None if
    essential data is missing.
    """
    stage_row = conn.execute(
        """SELECT s.*, r.uci_tour FROM stages s
           LEFT JOIN races r ON s.race_url = r.url
           WHERE s.url = ?""", (stage_url,)
    ).fetchone()

    if not stage_row:
        return None

    race_date = stage_row["date"]
    if not race_date:
        return None

    features = {}

    # 1. Race features (shared)
    race_feats = extract_race_features(dict(stage_row))
    for k, v in race_feats.items():
        features[f"race_{k}"] = v

    # 2. Rider A features
    rider_a_feats = compute_rider_features(conn, rider_a_url, race_date, stage_url)

    # 3. Rider B features
    rider_b_feats = compute_rider_features(conn, rider_b_url, race_date, stage_url)

    # 4. Differenced features (A - B) — the model learns relative strength
    for name in RIDER_FEATURE_NAMES:
        val_a = rider_a_feats.get(name, 0.0) or 0.0
        val_b = rider_b_feats.get(name, 0.0) or 0.0
        features[f"diff_{name}"] = float(val_a) - float(val_b)

    # Also include absolute values for each rider (model can learn non-linear interactions)
    for name in RIDER_FEATURE_NAMES:
        features[f"a_{name}"] = float(rider_a_feats.get(name, 0.0) or 0.0)
        features[f"b_{name}"] = float(rider_b_feats.get(name, 0.0) or 0.0)

    # 5. Head-to-head history
    h2h = compute_h2h_history(conn, rider_a_url, rider_b_url, race_date)
    for k, v in h2h.items():
        features[k] = v

    # 5b. Startlist-relative features (compute from all riders in this stage)
    all_riders = conn.execute(
        "SELECT rider_url FROM results WHERE stage_url = ?", (stage_url,)
    ).fetchall()
    field_qualities = {}
    field_forms = {}
    for r in all_riders:
        rurl = r["rider_url"]
        rf = compute_rider_features(conn, rurl, race_date, stage_url)
        field_qualities[rurl] = float(rf.get("career_top10_rate", 0) or 0)
        field_forms[rurl] = float(rf.get("form_90d_avg_pcs", 0) or 0)

    field_size = len(all_riders)
    avg_quality = np.mean(list(field_qualities.values())) if field_qualities else 0.0
    features["race_field_size"] = float(field_size)
    features["race_field_avg_quality"] = avg_quality

    # Compute percentiles for rider A and B
    q_sorted = sorted(field_qualities.values())
    f_sorted = sorted(field_forms.values())
    for prefix, rurl in [("a", rider_a_url), ("b", rider_b_url)]:
        rq = field_qualities.get(rurl, 0)
        rf_val = field_forms.get(rurl, 0)
        pct_q = sum(1 for v in q_sorted if v <= rq) / max(len(q_sorted), 1)
        pct_f = sum(1 for v in f_sorted if v <= rf_val) / max(len(f_sorted), 1)
        strength_ratio = rq / avg_quality if avg_quality > 0 else 1.0
        features[f"{prefix}_field_rank_quality"] = pct_q
        features[f"{prefix}_field_rank_form"] = pct_f
        features[f"{prefix}_field_strength_ratio"] = strength_ratio
    for name in STARTLIST_FEATURE_NAMES:
        features[f"diff_{name}"] = features[f"a_{name}"] - features[f"b_{name}"]

    # 6. Specialty-race interaction features
    profile = race_feats.get("profile_icon_num", 1)
    features["interact_a_climber_x_profile"] = rider_a_feats.get("spec_climber", 0) * profile
    features["interact_b_climber_x_profile"] = rider_b_feats.get("spec_climber", 0) * profile
    features["interact_diff_climber_x_profile"] = (
        features["interact_a_climber_x_profile"] - features["interact_b_climber_x_profile"]
    )

    vert = race_feats.get("vertical_meters", 0)
    features["interact_a_climber_x_vert"] = rider_a_feats.get("spec_climber", 0) * (vert / 1000.0)
    features["interact_b_climber_x_vert"] = rider_b_feats.get("spec_climber", 0) * (vert / 1000.0)
    features["interact_diff_climber_x_vert"] = (
        features["interact_a_climber_x_vert"] - features["interact_b_climber_x_vert"]
    )

    is_itt = race_feats.get("is_itt", 0)
    features["interact_a_tt_x_itt"] = rider_a_feats.get("spec_tt", 0) * is_itt
    features["interact_b_tt_x_itt"] = rider_b_feats.get("spec_tt", 0) * is_itt
    features["interact_diff_tt_x_itt"] = (
        features["interact_a_tt_x_itt"] - features["interact_b_tt_x_itt"]
    )

    dist = race_feats.get("distance_km", 0)
    features["interact_a_sprint_x_flat"] = rider_a_feats.get("spec_sprint", 0) * max(0, 1 - profile / 3)
    features["interact_b_sprint_x_flat"] = rider_b_feats.get("spec_sprint", 0) * max(0, 1 - profile / 3)
    features["interact_diff_sprint_x_flat"] = (
        features["interact_a_sprint_x_flat"] - features["interact_b_sprint_x_flat"]
    )

    # GC specialist × mountain stage
    a_gc = rider_a_feats.get("spec_gc", 0) or 0
    b_gc = rider_b_feats.get("spec_gc", 0) or 0
    features["interact_a_gc_x_profile"] = a_gc * profile
    features["interact_b_gc_x_profile"] = b_gc * profile
    features["interact_diff_gc_x_profile"] = (a_gc - b_gc) * profile

    # Career quality × recent form
    a_quality = rider_a_feats.get("career_top10_rate", 0) or 0
    b_quality = rider_b_feats.get("career_top10_rate", 0) or 0
    a_form = 1.0 / max(rider_a_feats.get("form_90d_avg_rank", 50) or 50, 1)
    b_form = 1.0 / max(rider_b_feats.get("form_90d_avg_rank", 50) or 50, 1)
    features["interact_a_quality_x_form"] = a_quality * a_form
    features["interact_b_quality_x_form"] = b_quality * b_form
    features["interact_diff_quality_x_form"] = a_quality * a_form - b_quality * b_form

    # Terrain match × form
    a_terrain = rider_a_feats.get("terrain_same_profile_top10", 0) or 0
    b_terrain = rider_b_feats.get("terrain_same_profile_top10", 0) or 0
    features["interact_a_terrain_x_form"] = a_terrain * a_form
    features["interact_b_terrain_x_form"] = b_terrain * b_form
    features["interact_diff_terrain_x_form"] = a_terrain * a_form - b_terrain * b_form

    # Climbing specialist × mountain performance
    a_climber = rider_a_feats.get("spec_climber", 0) or 0
    b_climber = rider_b_feats.get("spec_climber", 0) or 0
    a_mt = rider_a_feats.get("mountain_avg_rank", 50) or 50
    b_mt = rider_b_feats.get("mountain_avg_rank", 50) or 50
    a_mt_inv = 1.0 / max(a_mt, 1)
    b_mt_inv = 1.0 / max(b_mt, 1)
    features["interact_a_climber_x_mountain"] = a_climber * a_mt_inv * profile
    features["interact_b_climber_x_mountain"] = b_climber * b_mt_inv * profile
    features["interact_diff_climber_x_mountain"] = (
        a_climber * a_mt_inv - b_climber * b_mt_inv
    ) * profile

    return features


def build_feature_vector_manual(
    conn: sqlite3.Connection,
    rider_a_url: str,
    rider_b_url: str,
    race_params: dict,
) -> Optional[dict]:
    """
    Build feature vector for an upcoming/manual race not in the database.

    Args:
        conn: Database connection (for rider history lookup).
        rider_a_url: PCS rider URL for rider A.
        rider_b_url: PCS rider URL for rider B.
        race_params: Dict describing the race with keys:
            - distance (float): Distance in km
            - vertical_meters (float): Total elevation gain
            - profile_icon (str): p1–p5
            - profile_score (float): PCS-style score (optional, estimated from icon if missing)
            - is_one_day_race (bool): True for one-day race
            - stage_type (str): RR, ITT, TTT
            - race_date (str): ISO date for the race (e.g. "2026-03-30")
            - race_base_url (str): Optional, e.g. "race/tour-de-france" for same-race history
            - num_climbs (int): Number of categorised climbs (optional)
            - avg_temperature (float): Temperature in °C (optional)

    Returns:
        dict with all feature names → float values, or None on failure.
    """
    race_date = race_params.get("race_date")
    if not race_date:
        from datetime import date as _date
        race_date = _date.today().isoformat()

    # Estimate profile_score from icon if not provided
    if not race_params.get("profile_score"):
        icon_scores = {"p1": 5, "p2": 25, "p3": 60, "p4": 120, "p5": 180}
        race_params["profile_score"] = icon_scores.get(race_params.get("profile_icon", "p1"), 30)

    # Build a synthetic stage_row dict for extract_race_features
    stage_row = {
        "distance": race_params.get("distance") or 0,
        "vertical_meters": race_params.get("vertical_meters") or 0,
        "profile_score": race_params.get("profile_score") or 0,
        "profile_icon": race_params.get("profile_icon") or "p1",
        "avg_speed_winner": race_params.get("avg_speed_winner") or 0,
        "avg_temperature": race_params.get("avg_temperature") or 0,
        "is_one_day_race": 1 if race_params.get("is_one_day_race") else 0,
        "stage_type": race_params.get("stage_type") or "RR",
        "startlist_quality_score": race_params.get("startlist_quality_score"),
        "num_climbs": race_params.get("num_climbs") or 0,
        "climbs_json": race_params.get("climbs_json") or "[]",
    }

    features = {}

    # 1. Race features
    race_feats = extract_race_features(stage_row)
    for k, v in race_feats.items():
        features[f"race_{k}"] = v

    # 2. Rider features (pass manual_race for terrain affinity)
    manual_race = {
        "profile_score": stage_row["profile_score"],
        "profile_icon": stage_row["profile_icon"],
        "distance": stage_row["distance"],
        "vertical_meters": stage_row["vertical_meters"],
        "is_one_day_race": stage_row["is_one_day_race"],
        "stage_type": stage_row["stage_type"],
        "race_base_url": race_params.get("race_base_url"),
    }

    rider_a_feats = compute_rider_features(
        conn, rider_a_url, race_date, stage_url="", manual_race=manual_race
    )
    rider_b_feats = compute_rider_features(
        conn, rider_b_url, race_date, stage_url="", manual_race=manual_race
    )

    # 3. Differenced features
    for name in RIDER_FEATURE_NAMES:
        val_a = rider_a_feats.get(name, 0.0) or 0.0
        val_b = rider_b_feats.get(name, 0.0) or 0.0
        features[f"diff_{name}"] = float(val_a) - float(val_b)

    # 4. Absolute rider features
    for name in RIDER_FEATURE_NAMES:
        features[f"a_{name}"] = float(rider_a_feats.get(name, 0.0) or 0.0)
        features[f"b_{name}"] = float(rider_b_feats.get(name, 0.0) or 0.0)

    # 5. H2H history
    h2h = compute_h2h_history(conn, rider_a_url, rider_b_url, race_date)
    for k, v in h2h.items():
        features[k] = v

    # 6. Interaction features
    profile = race_feats.get("profile_icon_num", 1)
    features["interact_a_climber_x_profile"] = rider_a_feats.get("spec_climber", 0) * profile
    features["interact_b_climber_x_profile"] = rider_b_feats.get("spec_climber", 0) * profile
    features["interact_diff_climber_x_profile"] = (
        features["interact_a_climber_x_profile"] - features["interact_b_climber_x_profile"]
    )

    vert = race_feats.get("vertical_meters", 0)
    features["interact_a_climber_x_vert"] = rider_a_feats.get("spec_climber", 0) * (vert / 1000.0)
    features["interact_b_climber_x_vert"] = rider_b_feats.get("spec_climber", 0) * (vert / 1000.0)
    features["interact_diff_climber_x_vert"] = (
        features["interact_a_climber_x_vert"] - features["interact_b_climber_x_vert"]
    )

    is_itt = race_feats.get("is_itt", 0)
    features["interact_a_tt_x_itt"] = rider_a_feats.get("spec_tt", 0) * is_itt
    features["interact_b_tt_x_itt"] = rider_b_feats.get("spec_tt", 0) * is_itt
    features["interact_diff_tt_x_itt"] = (
        features["interact_a_tt_x_itt"] - features["interact_b_tt_x_itt"]
    )

    features["interact_a_sprint_x_flat"] = rider_a_feats.get("spec_sprint", 0) * max(0, 1 - profile / 3)
    features["interact_b_sprint_x_flat"] = rider_b_feats.get("spec_sprint", 0) * max(0, 1 - profile / 3)
    features["interact_diff_sprint_x_flat"] = (
        features["interact_a_sprint_x_flat"] - features["interact_b_sprint_x_flat"]
    )

    # GC specialist × mountain stage
    a_gc = rider_a_feats.get("spec_gc", 0) or 0
    b_gc = rider_b_feats.get("spec_gc", 0) or 0
    features["interact_a_gc_x_profile"] = a_gc * profile
    features["interact_b_gc_x_profile"] = b_gc * profile
    features["interact_diff_gc_x_profile"] = (a_gc - b_gc) * profile

    # Career quality × recent form (#2 most important feature)
    a_quality = rider_a_feats.get("career_top10_rate", 0) or 0
    b_quality = rider_b_feats.get("career_top10_rate", 0) or 0
    a_form = 1.0 / max(rider_a_feats.get("form_90d_avg_rank", 50) or 50, 1)
    b_form = 1.0 / max(rider_b_feats.get("form_90d_avg_rank", 50) or 50, 1)
    features["interact_a_quality_x_form"] = a_quality * a_form
    features["interact_b_quality_x_form"] = b_quality * b_form
    features["interact_diff_quality_x_form"] = a_quality * a_form - b_quality * b_form

    # Terrain match × form
    a_terrain = rider_a_feats.get("terrain_same_profile_top10", 0) or 0
    b_terrain = rider_b_feats.get("terrain_same_profile_top10", 0) or 0
    features["interact_a_terrain_x_form"] = a_terrain * a_form
    features["interact_b_terrain_x_form"] = b_terrain * b_form
    features["interact_diff_terrain_x_form"] = a_terrain * a_form - b_terrain * b_form

    # Climbing specialist × mountain performance
    a_climber = rider_a_feats.get("spec_climber", 0) or 0
    b_climber = rider_b_feats.get("spec_climber", 0) or 0
    a_mt = rider_a_feats.get("mountain_avg_rank", 50) or 50
    b_mt = rider_b_feats.get("mountain_avg_rank", 50) or 50
    a_mt_inv = 1.0 / max(a_mt, 1)
    b_mt_inv = 1.0 / max(b_mt, 1)
    features["interact_a_climber_x_mountain"] = a_climber * a_mt_inv * profile
    features["interact_b_climber_x_mountain"] = b_climber * b_mt_inv * profile
    features["interact_diff_climber_x_mountain"] = (
        a_climber * a_mt_inv - b_climber * b_mt_inv
    ) * profile

    return features


def get_all_feature_names() -> list[str]:
    """Return ordered list of all feature names."""
    names = []
    # Race features
    for n in RACE_FEATURE_NAMES:
        names.append(f"race_{n}")
    # Startlist race-level features
    for n in STARTLIST_RACE_FEATURE_NAMES:
        names.append(f"race_{n}")
    # Diff rider features
    for n in RIDER_FEATURE_NAMES:
        names.append(f"diff_{n}")
    # Absolute rider features
    for n in RIDER_FEATURE_NAMES:
        names.append(f"a_{n}")
    for n in RIDER_FEATURE_NAMES:
        names.append(f"b_{n}")
    # H2H features
    names.extend(H2H_FEATURE_NAMES)
    # Startlist-relative rider features (diff + absolute)
    for n in STARTLIST_FEATURE_NAMES:
        names.append(f"diff_{n}")
    for n in STARTLIST_FEATURE_NAMES:
        names.append(f"a_{n}")
    for n in STARTLIST_FEATURE_NAMES:
        names.append(f"b_{n}")
    # Interaction features
    names.extend([
        "interact_a_climber_x_profile", "interact_b_climber_x_profile",
        "interact_diff_climber_x_profile",
        "interact_a_climber_x_vert", "interact_b_climber_x_vert",
        "interact_diff_climber_x_vert",
        "interact_a_tt_x_itt", "interact_b_tt_x_itt", "interact_diff_tt_x_itt",
        "interact_a_sprint_x_flat", "interact_b_sprint_x_flat",
        "interact_diff_sprint_x_flat",
        # New: GC specialist × mountain stage
        "interact_a_gc_x_profile", "interact_b_gc_x_profile",
        "interact_diff_gc_x_profile",
        # New: career quality × recent form
        "interact_a_quality_x_form", "interact_b_quality_x_form",
        "interact_diff_quality_x_form",
        # New: terrain match × form (how good is rider on this terrain recently)
        "interact_a_terrain_x_form", "interact_b_terrain_x_form",
        "interact_diff_terrain_x_form",
        # New: mountain specialist × mountain performance
        "interact_a_climber_x_mountain", "interact_b_climber_x_mountain",
        "interact_diff_climber_x_mountain",
    ])
    return names


def build_feature_matrix(pairs_df: pd.DataFrame, db_path: str = DB_PATH) -> pd.DataFrame:
    """
    Build feature matrix from pairs DataFrame.

    Uses pre-computed rider/race feature caches when available (from
    ``scripts/precompute_features.py``).  Falls back to live DB queries
    when the cache is missing.

    Args:
        pairs_df: DataFrame with columns [stage_url, rider_a_url, rider_b_url, label]

    Returns:
        DataFrame with all features + label column
    """
    from features.feature_store import load_rider_features_cache, load_race_features_cache

    conn = get_db(db_path)
    feature_names = get_all_feature_names()

    # Try to load caches
    rider_cache_df = load_rider_features_cache()
    race_cache_df = load_race_features_cache()

    rider_lookup = None
    race_lookup = None

    if rider_cache_df is not None:
        rider_cache_df = rider_cache_df.set_index(["rider_url", "stage_url"])
        rider_lookup = rider_cache_df.to_dict("index")
        log.info(f"Loaded rider feature cache ({len(rider_lookup)} entries)")
    else:
        log.info("No rider feature cache found — computing live (slow)")

    if race_cache_df is not None:
        race_cache_df = race_cache_df.set_index("stage_url")
        race_lookup = race_cache_df.to_dict("index")
        log.info(f"Loaded race feature cache ({len(race_lookup)} entries)")
    else:
        log.info("No race feature cache found — computing live")

    # Pre-fetch all stage dates in bulk (avoid per-pair DB query)
    stage_dates = {}
    for row in conn.execute("SELECT url, date FROM stages WHERE date IS NOT NULL").fetchall():
        stage_dates[row["url"]] = row["date"]

    # --- Pre-compute startlist-relative features per stage ---
    # Get all riders per stage (approximate startlist from results table)
    stage_riders = {}
    for row in conn.execute("SELECT stage_url, rider_url FROM results").fetchall():
        stage_riders.setdefault(row["stage_url"], []).append(row["rider_url"])

    # Compute field stats and rider percentiles for stages in our pairs
    startlist_rider_feats = {}  # (rider_url, stage_url) → {field_rank_quality, ...}
    startlist_race_feats = {}   # stage_url → {field_size, field_avg_quality}
    target_stages = set(pairs_df["stage_url"].unique())

    for surl in tqdm(target_stages, desc="Computing startlist features"):
        riders_in_stage = stage_riders.get(surl, [])
        if len(riders_in_stage) < 2:
            continue

        # Collect career_top10_rate and form_90d_avg_pcs for all riders in field
        quality_vals = {}  # rider_url → career_top10_rate
        form_vals = {}     # rider_url → form_90d_avg_pcs

        for rurl in riders_in_stage:
            rkey = (rurl, surl)
            if rider_lookup and rkey in rider_lookup:
                rf = rider_lookup[rkey]
                quality_vals[rurl] = float(rf.get("career_top10_rate", 0) or 0)
                form_vals[rurl] = float(rf.get("form_90d_avg_pcs", 0) or 0)

        if not quality_vals:
            continue

        field_size = len(riders_in_stage)
        q_values = list(quality_vals.values())
        avg_quality = np.mean(q_values) if q_values else 0.0

        startlist_race_feats[surl] = {
            "field_size": field_size,
            "field_avg_quality": avg_quality,
        }

        # Sort to compute percentiles (higher = better)
        q_sorted = sorted(quality_vals.items(), key=lambda x: x[1])
        f_sorted = sorted(form_vals.items(), key=lambda x: x[1])
        n_q = len(q_sorted)
        n_f = len(f_sorted)

        for rank_idx, (rurl, _) in enumerate(q_sorted):
            pct_q = rank_idx / max(n_q - 1, 1)  # 0 = worst, 1 = best
            rider_quality = quality_vals.get(rurl, 0)
            strength_ratio = rider_quality / avg_quality if avg_quality > 0 else 1.0
            startlist_rider_feats.setdefault((rurl, surl), {})["field_rank_quality"] = pct_q
            startlist_rider_feats[(rurl, surl)]["field_strength_ratio"] = strength_ratio

        for rank_idx, (rurl, _) in enumerate(f_sorted):
            pct_f = rank_idx / max(n_f - 1, 1)
            startlist_rider_feats.setdefault((rurl, surl), {})["field_rank_form"] = pct_f

    log.info(f"Computed startlist features for {len(startlist_race_feats)} stages, "
             f"{len(startlist_rider_feats)} rider-stage entries")

    rows = []
    skipped = 0
    cache_hits = 0
    cache_misses = 0
    total = len(pairs_df)

    for i, (_, pair) in enumerate(tqdm(pairs_df.iterrows(), total=total, desc="Building feature matrix")):
        stage_url = pair["stage_url"]
        rider_a_url = pair["rider_a_url"]
        rider_b_url = pair["rider_b_url"]

        # --- Race features ---
        if race_lookup and stage_url in race_lookup:
            race_feats = race_lookup[stage_url]
        else:
            stage_row = conn.execute(
                """SELECT s.*, r.uci_tour FROM stages s
                   LEFT JOIN races r ON s.race_url = r.url
                   WHERE s.url = ?""", (stage_url,)
            ).fetchone()
            if not stage_row:
                skipped += 1
                continue
            race_feats = extract_race_features(dict(stage_row))

        # --- Get race_date for H2H ---
        race_date = stage_dates.get(stage_url)
        if not race_date:
            skipped += 1
            continue

        # --- Rider features (from cache or live) ---
        rider_a_key = (rider_a_url, stage_url)
        rider_b_key = (rider_b_url, stage_url)

        if rider_lookup and rider_a_key in rider_lookup and rider_b_key in rider_lookup:
            rider_a_feats = rider_lookup[rider_a_key]
            rider_b_feats = rider_lookup[rider_b_key]
            cache_hits += 1
        else:
            rider_a_feats = compute_rider_features(conn, rider_a_url, race_date, stage_url)
            rider_b_feats = compute_rider_features(conn, rider_b_url, race_date, stage_url)
            cache_misses += 1

        # --- Assemble feature vector ---
        features = {}

        # Race features
        for k in RACE_FEATURE_NAMES:
            features[f"race_{k}"] = float(race_feats.get(k, 0.0) or 0.0)

        # Startlist race-level features
        sl_race = startlist_race_feats.get(stage_url, {})
        for k in STARTLIST_RACE_FEATURE_NAMES:
            features[f"race_{k}"] = float(sl_race.get(k, 0.0) or 0.0)

        # Diff + absolute rider features
        for name in RIDER_FEATURE_NAMES:
            val_a = float(rider_a_feats.get(name, 0.0) or 0.0)
            val_b = float(rider_b_feats.get(name, 0.0) or 0.0)
            features[f"diff_{name}"] = val_a - val_b
            features[f"a_{name}"] = val_a
            features[f"b_{name}"] = val_b

        # H2H history (always computed live — pair-specific)
        h2h = compute_h2h_history(conn, rider_a_url, rider_b_url, race_date)
        for k, v in h2h.items():
            features[k] = v

        # Startlist-relative rider features (diff + absolute)
        sl_a = startlist_rider_feats.get((rider_a_url, stage_url), {})
        sl_b = startlist_rider_feats.get((rider_b_url, stage_url), {})
        for name in STARTLIST_FEATURE_NAMES:
            val_a = float(sl_a.get(name, 0.5) or 0.5)
            val_b = float(sl_b.get(name, 0.5) or 0.5)
            features[f"diff_{name}"] = val_a - val_b
            features[f"a_{name}"] = val_a
            features[f"b_{name}"] = val_b

        # Interaction features
        profile = race_feats.get("profile_icon_num", 1) or 1
        vert = race_feats.get("vertical_meters", 0) or 0
        is_itt = race_feats.get("is_itt", 0) or 0

        a_climber = rider_a_feats.get("spec_climber", 0) or 0
        b_climber = rider_b_feats.get("spec_climber", 0) or 0
        a_tt = rider_a_feats.get("spec_tt", 0) or 0
        b_tt = rider_b_feats.get("spec_tt", 0) or 0
        a_sprint = rider_a_feats.get("spec_sprint", 0) or 0
        b_sprint = rider_b_feats.get("spec_sprint", 0) or 0

        features["interact_a_climber_x_profile"] = a_climber * profile
        features["interact_b_climber_x_profile"] = b_climber * profile
        features["interact_diff_climber_x_profile"] = (a_climber - b_climber) * profile

        features["interact_a_climber_x_vert"] = a_climber * (vert / 1000.0)
        features["interact_b_climber_x_vert"] = b_climber * (vert / 1000.0)
        features["interact_diff_climber_x_vert"] = (a_climber - b_climber) * (vert / 1000.0)

        features["interact_a_tt_x_itt"] = a_tt * is_itt
        features["interact_b_tt_x_itt"] = b_tt * is_itt
        features["interact_diff_tt_x_itt"] = (a_tt - b_tt) * is_itt

        flat_factor = max(0, 1 - profile / 3)
        features["interact_a_sprint_x_flat"] = a_sprint * flat_factor
        features["interact_b_sprint_x_flat"] = b_sprint * flat_factor
        features["interact_diff_sprint_x_flat"] = (a_sprint - b_sprint) * flat_factor

        # GC specialist × mountain stage
        a_gc = rider_a_feats.get("spec_gc", 0) or 0
        b_gc = rider_b_feats.get("spec_gc", 0) or 0
        features["interact_a_gc_x_profile"] = a_gc * profile
        features["interact_b_gc_x_profile"] = b_gc * profile
        features["interact_diff_gc_x_profile"] = (a_gc - b_gc) * profile

        # Career quality × recent form (top10_rate × 90d form rank inverted)
        a_quality = rider_a_feats.get("career_top10_rate", 0) or 0
        b_quality = rider_b_feats.get("career_top10_rate", 0) or 0
        a_form = 1.0 / max(rider_a_feats.get("form_90d_avg_rank", 50) or 50, 1)
        b_form = 1.0 / max(rider_b_feats.get("form_90d_avg_rank", 50) or 50, 1)
        features["interact_a_quality_x_form"] = a_quality * a_form
        features["interact_b_quality_x_form"] = b_quality * b_form
        features["interact_diff_quality_x_form"] = a_quality * a_form - b_quality * b_form

        # Terrain match × form
        a_terrain = rider_a_feats.get("terrain_same_profile_top10", 0) or 0
        b_terrain = rider_b_feats.get("terrain_same_profile_top10", 0) or 0
        features["interact_a_terrain_x_form"] = a_terrain * a_form
        features["interact_b_terrain_x_form"] = b_terrain * b_form
        features["interact_diff_terrain_x_form"] = a_terrain * a_form - b_terrain * b_form

        # Climbing specialist × mountain race performance
        a_mt = rider_a_feats.get("mountain_avg_rank", 50) or 50
        b_mt = rider_b_feats.get("mountain_avg_rank", 50) or 50
        a_mt_inv = 1.0 / max(a_mt, 1)
        b_mt_inv = 1.0 / max(b_mt, 1)
        features["interact_a_climber_x_mountain"] = a_climber * a_mt_inv * profile
        features["interact_b_climber_x_mountain"] = b_climber * b_mt_inv * profile
        features["interact_diff_climber_x_mountain"] = (
            a_climber * a_mt_inv - b_climber * b_mt_inv
        ) * profile

        row = [features.get(name, 0.0) for name in feature_names]
        row.append(pair["label"])
        rows.append(row)

        if (i + 1) % 5000 == 0:
            log.info(f"  Progress: {i+1}/{total} pairs, {len(rows)} kept, {skipped} skipped")

    conn.close()

    if rider_lookup:
        log.info(f"Cache stats: {cache_hits} hits, {cache_misses} misses")

    columns = feature_names + ["label"]
    df = pd.DataFrame(rows, columns=columns)

    # Domain-aware fillna: rank features default to 50 (median), others to 0
    rank_keywords = ("avg_rank", "median_rank", "best_rank", "ranking")
    for col in df.columns:
        if col == "label":
            continue
        if df[col].isna().any():
            if col.startswith(("a_", "b_")) and any(k in col for k in rank_keywords):
                df[col] = df[col].fillna(50.0)
            else:
                df[col] = df[col].fillna(0.0)

    log.info(f"Built feature matrix: {df.shape[0]} rows × {df.shape[1]} columns")
    return df
