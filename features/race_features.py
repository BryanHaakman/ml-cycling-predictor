"""
Race feature extraction from cached stage data.
"""

import json
import numpy as np

# Profile icon mapping: p1 (flat) → p5 (high mountain)
PROFILE_MAP = {"p1": 1, "p2": 2, "p3": 3, "p4": 4, "p5": 5}

# Climb category mapping
CLIMB_CAT_MAP = {"4": 1, "3": 2, "2": 3, "1": 4, "HC": 5}


def extract_race_features(stage_row: dict) -> dict:
    """
    Extract numeric features from a stage database row.

    Returns dict of feature_name → float value.
    """
    features = {}

    # Basic race metrics
    features["distance_km"] = stage_row.get("distance") or 0.0
    features["vertical_meters"] = stage_row.get("vertical_meters") or 0.0
    features["profile_score"] = stage_row.get("profile_score") or 0.0

    # Profile icon encoded
    icon = stage_row.get("profile_icon") or "p1"
    features["profile_icon_num"] = PROFILE_MAP.get(icon, 1)

    # Terrain difficulty ratio
    dist = features["distance_km"]
    if dist > 0:
        features["vert_per_km"] = features["vertical_meters"] / dist
    else:
        features["vert_per_km"] = 0.0

    # Speed and conditions
    features["avg_speed_winner"] = stage_row.get("avg_speed_winner") or 0.0
    features["avg_temperature"] = stage_row.get("avg_temperature") or 0.0

    # Race type
    features["is_one_day_race"] = float(stage_row.get("is_one_day_race") or 0)

    # Stage type encoding (RR=road race, ITT=individual TT, TTT=team TT)
    stype = (stage_row.get("stage_type") or "RR").upper()
    features["is_itt"] = 1.0 if stype == "ITT" else 0.0
    features["is_ttt"] = 1.0 if stype == "TTT" else 0.0

    # Startlist quality
    sq = stage_row.get("startlist_quality_score")
    if sq:
        try:
            parsed = json.loads(sq) if isinstance(sq, str) else sq
            if isinstance(parsed, (list, tuple)) and len(parsed) >= 1:
                features["startlist_quality"] = float(parsed[0])
            elif isinstance(parsed, (int, float)):
                features["startlist_quality"] = float(parsed)
            else:
                features["startlist_quality"] = 0.0
        except (json.JSONDecodeError, ValueError):
            features["startlist_quality"] = 0.0
    else:
        features["startlist_quality"] = 0.0

    # Climb features
    climbs_json = stage_row.get("climbs_json") or "[]"
    try:
        climbs = json.loads(climbs_json) if isinstance(climbs_json, str) else climbs_json
    except json.JSONDecodeError:
        climbs = []

    features["num_climbs"] = stage_row.get("num_climbs") or len(climbs)

    if climbs:
        steepness_vals = [c.get("steepness") or 0 for c in climbs if isinstance(c, dict)]
        length_vals = [c.get("length") or 0 for c in climbs if isinstance(c, dict)]
        cat_vals = []
        for c in climbs:
            if isinstance(c, dict):
                cat = str(c.get("category", ""))
                cat_vals.append(CLIMB_CAT_MAP.get(cat, 0))

        features["avg_climb_steepness"] = np.mean(steepness_vals) if steepness_vals else 0.0
        features["max_climb_steepness"] = max(steepness_vals) if steepness_vals else 0.0
        features["total_climb_length"] = sum(length_vals)
        features["avg_climb_length"] = np.mean(length_vals) if length_vals else 0.0
        features["max_climb_category"] = max(cat_vals) if cat_vals else 0
        features["num_hc_climbs"] = sum(1 for v in cat_vals if v == 5)
        features["num_cat1_plus"] = sum(1 for v in cat_vals if v >= 4)
    else:
        features["avg_climb_steepness"] = 0.0
        features["max_climb_steepness"] = 0.0
        features["total_climb_length"] = 0.0
        features["avg_climb_length"] = 0.0
        features["max_climb_category"] = 0
        features["num_hc_climbs"] = 0
        features["num_cat1_plus"] = 0

    return features


# List of all race feature names for consistent ordering
RACE_FEATURE_NAMES = [
    "distance_km", "vertical_meters", "profile_score", "profile_icon_num",
    "vert_per_km", "avg_speed_winner", "avg_temperature", "is_one_day_race",
    "is_itt", "is_ttt", "startlist_quality", "num_climbs",
    "avg_climb_steepness", "max_climb_steepness", "total_climb_length",
    "avg_climb_length", "max_climb_category", "num_hc_climbs", "num_cat1_plus",
]
