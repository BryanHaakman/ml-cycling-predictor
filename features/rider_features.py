"""
Rider feature computation from cached data.

All features are computed using only data available BEFORE the target race
(no data leakage). Features capture form, specialty, terrain affinity, etc.
"""

import json
import sqlite3
import numpy as np
from datetime import datetime, timedelta
from typing import Optional


def _rider_age_at_date(birthdate_str: Optional[str], race_date_str: str) -> float:
    """Calculate rider age in years at a given date."""
    if not birthdate_str or not race_date_str:
        return 28.0  # default fallback
    try:
        parts = birthdate_str.split("-")
        bd = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
        rd = datetime.fromisoformat(race_date_str)
        return (rd - bd).days / 365.25
    except (ValueError, IndexError):
        return 28.0


def compute_rider_features(
    conn: sqlite3.Connection,
    rider_url: str,
    race_date: str,
    stage_url: str,
    manual_race: dict = None,
) -> dict:
    """
    Compute features for a single rider relative to a target race.
    Only uses historical data (before race_date).

    Args:
        manual_race: Optional dict with keys like profile_score, profile_icon,
                     distance, vertical_meters, is_one_day_race, stage_type,
                     race_base_url.  When provided, terrain-affinity and
                     same-race-history features are derived from it instead
                     of looking up stage_url in the database.

    Returns dict of feature_name → float.
    """
    features = {}

    # --- Rider profile (static) ---
    rider = conn.execute(
        "SELECT * FROM riders WHERE url = ?", (rider_url,)
    ).fetchone()

    if rider:
        features["weight"] = rider["weight"] or 70.0
        features["height"] = rider["height"] or 1.80
        features["bmi"] = features["weight"] / (features["height"] ** 2) if features["height"] > 0 else 22.0
        features["age"] = _rider_age_at_date(rider["birthdate"], race_date)

        # Specialty scores
        features["spec_one_day"] = rider["specialty_one_day"] or 0.0
        features["spec_gc"] = rider["specialty_gc"] or 0.0
        features["spec_tt"] = rider["specialty_tt"] or 0.0
        features["spec_sprint"] = rider["specialty_sprint"] or 0.0
        features["spec_climber"] = rider["specialty_climber"] or 0.0
        features["spec_hills"] = rider["specialty_hills"] or 0.0

        # Derived specialty
        total_spec = sum([
            features["spec_one_day"], features["spec_gc"], features["spec_tt"],
            features["spec_sprint"], features["spec_climber"], features["spec_hills"]
        ])
        if total_spec > 0:
            features["spec_climber_pct"] = features["spec_climber"] / total_spec
            features["spec_sprint_pct"] = features["spec_sprint"] / total_spec
            features["spec_gc_pct"] = features["spec_gc"] / total_spec
            features["spec_tt_pct"] = features["spec_tt"] / total_spec
            features["spec_one_day_pct"] = features["spec_one_day"] / total_spec
            features["spec_hills_pct"] = features["spec_hills"] / total_spec
        else:
            for k in ["spec_climber_pct", "spec_sprint_pct", "spec_gc_pct",
                       "spec_tt_pct", "spec_one_day_pct", "spec_hills_pct"]:
                features[k] = 0.0

        # Points trajectory from history
        pts_json = rider["points_history_json"]
        if pts_json:
            try:
                pts_history = json.loads(pts_json)
                race_year = int(race_date[:4]) if race_date else 2024
                recent_pts = [
                    h["points"] for h in pts_history
                    if isinstance(h, dict) and h.get("season", 0) < race_year
                       and h.get("season", 0) >= race_year - 3
                ]
                features["avg_season_points_3yr"] = np.mean(recent_pts) if recent_pts else 0.0
                features["max_season_points_3yr"] = max(recent_pts) if recent_pts else 0.0

                recent_ranks = [
                    h["rank"] for h in pts_history
                    if isinstance(h, dict) and h.get("season", 0) < race_year
                       and h.get("season", 0) >= race_year - 3 and h.get("rank")
                ]
                features["best_ranking_3yr"] = min(recent_ranks) if recent_ranks else 500.0
                features["avg_ranking_3yr"] = np.mean(recent_ranks) if recent_ranks else 500.0

                # Trend: last year vs 2 years ago
                pts_by_year = {
                    h["season"]: h["points"]
                    for h in pts_history
                    if isinstance(h, dict) and h.get("season")
                }
                last_yr = pts_by_year.get(race_year - 1, 0)
                prev_yr = pts_by_year.get(race_year - 2, 0)
                features["points_trend"] = last_yr - prev_yr

            except (json.JSONDecodeError, TypeError):
                features["avg_season_points_3yr"] = 0.0
                features["max_season_points_3yr"] = 0.0
                features["best_ranking_3yr"] = 500.0
                features["avg_ranking_3yr"] = 500.0
                features["points_trend"] = 0.0
        else:
            features["avg_season_points_3yr"] = 0.0
            features["max_season_points_3yr"] = 0.0
            features["best_ranking_3yr"] = 500.0
            features["avg_ranking_3yr"] = 500.0
            features["points_trend"] = 0.0
    else:
        # Unknown rider — fill defaults
        features["weight"] = 70.0
        features["height"] = 1.80
        features["bmi"] = 22.0
        features["age"] = 28.0
        for k in ["spec_one_day", "spec_gc", "spec_tt", "spec_sprint",
                   "spec_climber", "spec_hills"]:
            features[k] = 0.0
        for k in ["spec_climber_pct", "spec_sprint_pct", "spec_gc_pct",
                   "spec_tt_pct", "spec_one_day_pct", "spec_hills_pct"]:
            features[k] = 0.0
        features["avg_season_points_3yr"] = 0.0
        features["max_season_points_3yr"] = 0.0
        features["best_ranking_3yr"] = 500.0
        features["avg_ranking_3yr"] = 500.0
        features["points_trend"] = 0.0

    # --- Historical results (only before race_date) ---
    past_results = conn.execute("""
        SELECT r.rank, r.pcs_points, r.uci_points, r.breakaway_kms,
               s.date, s.distance, s.vertical_meters, s.profile_score,
               s.profile_icon, s.is_one_day_race, s.stage_type, s.race_url
        FROM results r
        JOIN stages s ON r.stage_url = s.url
        WHERE r.rider_url = ? AND s.date < ? AND r.rank IS NOT NULL
        ORDER BY s.date DESC
    """, (rider_url, race_date)).fetchall()

    if past_results:
        ranks = [r["rank"] for r in past_results]
        pcs_pts = [r["pcs_points"] or 0 for r in past_results]
        uci_pts = [r["uci_points"] or 0 for r in past_results]

        features["career_races"] = len(ranks)
        features["career_avg_rank"] = np.mean(ranks)
        features["career_median_rank"] = np.median(ranks)
        features["career_wins"] = sum(1 for r in ranks if r == 1)
        features["career_podiums"] = sum(1 for r in ranks if r <= 3)
        features["career_top10"] = sum(1 for r in ranks if r <= 10)
        features["career_win_rate"] = features["career_wins"] / len(ranks) if ranks else 0
        features["career_podium_rate"] = features["career_podiums"] / len(ranks) if ranks else 0
        features["career_top10_rate"] = features["career_top10"] / len(ranks) if ranks else 0
        features["career_avg_pcs_pts"] = np.mean(pcs_pts)
        features["career_avg_uci_pts"] = np.mean(uci_pts)

        # Recent form (last 30/60/90 days and last 5/10/20 races)
        for window_name, window_days in [("30d", 30), ("60d", 60), ("90d", 90), ("180d", 180)]:
            cutoff = (datetime.fromisoformat(race_date) - timedelta(days=window_days)).isoformat()
            window_results = [r for r in past_results if (r["date"] or "") >= cutoff]
            w_ranks = [r["rank"] for r in window_results]
            w_pcs = [r["pcs_points"] or 0 for r in window_results]
            features[f"form_{window_name}_races"] = len(w_ranks)
            features[f"form_{window_name}_avg_rank"] = np.mean(w_ranks) if w_ranks else 50.0
            features[f"form_{window_name}_wins"] = sum(1 for r in w_ranks if r == 1)
            features[f"form_{window_name}_top10"] = sum(1 for r in w_ranks if r <= 10)
            features[f"form_{window_name}_avg_pcs"] = np.mean(w_pcs) if w_pcs else 0.0

        for n_name, n_races in [("last5", 5), ("last10", 10), ("last20", 20)]:
            recent = past_results[:n_races]
            r_ranks = [r["rank"] for r in recent]
            r_pcs = [r["pcs_points"] or 0 for r in recent]
            features[f"form_{n_name}_avg_rank"] = np.mean(r_ranks) if r_ranks else 50.0
            features[f"form_{n_name}_best_rank"] = min(r_ranks) if r_ranks else 50
            features[f"form_{n_name}_avg_pcs"] = np.mean(r_pcs) if r_pcs else 0.0

        # Terrain affinity: performance on similar profiles
        if manual_race:
            target_profile = manual_race.get("profile_score") or 0
            target_icon = manual_race.get("profile_icon") or "p1"
            target_dist = manual_race.get("distance") or 0
            target_vert = manual_race.get("vertical_meters") or 0
            _has_terrain = True
        else:
            target_stage = conn.execute(
                "SELECT * FROM stages WHERE url = ?", (stage_url,)
            ).fetchone()
            if target_stage:
                target_profile = target_stage["profile_score"] or 0
                target_icon = target_stage["profile_icon"] or "p1"
                target_dist = target_stage["distance"] or 0
                target_vert = target_stage["vertical_meters"] or 0
                _has_terrain = True
            else:
                _has_terrain = False

        if _has_terrain:

            # Same profile icon races
            same_profile = [
                r for r in past_results
                if r["profile_icon"] == target_icon
            ]
            sp_ranks = [r["rank"] for r in same_profile]
            features["terrain_same_profile_races"] = len(sp_ranks)
            features["terrain_same_profile_avg_rank"] = np.mean(sp_ranks) if sp_ranks else 50.0
            features["terrain_same_profile_top10"] = sum(1 for r in sp_ranks if r <= 10)

            # Similar distance races (within 30%)
            if target_dist > 0:
                sim_dist = [
                    r for r in past_results
                    if r["distance"] and abs(r["distance"] - target_dist) / target_dist < 0.3
                ]
                sd_ranks = [r["rank"] for r in sim_dist]
                features["terrain_sim_dist_races"] = len(sd_ranks)
                features["terrain_sim_dist_avg_rank"] = np.mean(sd_ranks) if sd_ranks else 50.0
            else:
                features["terrain_sim_dist_races"] = 0
                features["terrain_sim_dist_avg_rank"] = 50.0

            # Mountain affinity (profile_score > 100)
            mountain = [r for r in past_results if (r["profile_score"] or 0) > 100]
            mt_ranks = [r["rank"] for r in mountain]
            features["mountain_races"] = len(mt_ranks)
            features["mountain_avg_rank"] = np.mean(mt_ranks) if mt_ranks else 50.0

            # Flat affinity (profile_score < 20)
            flat = [r for r in past_results if (r["profile_score"] or 0) < 20]
            fl_ranks = [r["rank"] for r in flat]
            features["flat_races"] = len(fl_ranks)
            features["flat_avg_rank"] = np.mean(fl_ranks) if fl_ranks else 50.0

            # One-day vs stage performance
            oneday = [r for r in past_results if r["is_one_day_race"]]
            od_ranks = [r["rank"] for r in oneday]
            features["one_day_races"] = len(od_ranks)
            features["one_day_avg_rank"] = np.mean(od_ranks) if od_ranks else 50.0

            # ITT performance
            itt = [r for r in past_results if (r["stage_type"] or "").upper() == "ITT"]
            itt_ranks = [r["rank"] for r in itt]
            features["itt_races"] = len(itt_ranks)
            features["itt_avg_rank"] = np.mean(itt_ranks) if itt_ranks else 50.0

        # Race-specific history (same race in previous years)
        race_base = None
        if manual_race and manual_race.get("race_base_url"):
            race_base = manual_race["race_base_url"]
        else:
            target_stage_row = conn.execute(
                "SELECT race_url FROM stages WHERE url = ?", (stage_url,)
            ).fetchone()
            if target_stage_row:
                race_base = target_stage_row["race_url"].rsplit("/", 1)[0]

        if race_base:
            same_race = conn.execute("""
                SELECT r.rank, r.pcs_points FROM results r
                JOIN stages s ON r.stage_url = s.url
                WHERE r.rider_url = ? AND s.race_url LIKE ? AND s.date < ?
                AND r.rank IS NOT NULL
            """, (rider_url, f"{race_base}%", race_date)).fetchall()
            sr_ranks = [r["rank"] for r in same_race]
            features["same_race_history_count"] = len(sr_ranks)
            features["same_race_avg_rank"] = np.mean(sr_ranks) if sr_ranks else 50.0
            features["same_race_best_rank"] = min(sr_ranks) if sr_ranks else 50
        else:
            features["same_race_history_count"] = 0
            features["same_race_avg_rank"] = 50.0
            features["same_race_best_rank"] = 50

        # DNF rate (approximate: count stages where rider appeared vs total
        # stages in races where they started)
        features["breakaway_rate"] = np.mean(
            [1 if (r["breakaway_kms"] or 0) > 0 else 0 for r in past_results]
        )

    else:
        # No historical results — fill defaults
        features["career_races"] = 0
        features["career_avg_rank"] = 50.0
        features["career_median_rank"] = 50.0
        features["career_wins"] = 0
        features["career_podiums"] = 0
        features["career_top10"] = 0
        features["career_win_rate"] = 0.0
        features["career_podium_rate"] = 0.0
        features["career_top10_rate"] = 0.0
        features["career_avg_pcs_pts"] = 0.0
        features["career_avg_uci_pts"] = 0.0

        for w in ["30d", "60d", "90d", "180d"]:
            features[f"form_{w}_races"] = 0
            features[f"form_{w}_avg_rank"] = 50.0
            features[f"form_{w}_wins"] = 0
            features[f"form_{w}_top10"] = 0
            features[f"form_{w}_avg_pcs"] = 0.0

        for n in ["last5", "last10", "last20"]:
            features[f"form_{n}_avg_rank"] = 50.0
            features[f"form_{n}_best_rank"] = 50
            features[f"form_{n}_avg_pcs"] = 0.0

        features["terrain_same_profile_races"] = 0
        features["terrain_same_profile_avg_rank"] = 50.0
        features["terrain_same_profile_top10"] = 0
        features["terrain_sim_dist_races"] = 0
        features["terrain_sim_dist_avg_rank"] = 50.0
        features["mountain_races"] = 0
        features["mountain_avg_rank"] = 50.0
        features["flat_races"] = 0
        features["flat_avg_rank"] = 50.0
        features["one_day_races"] = 0
        features["one_day_avg_rank"] = 50.0
        features["itt_races"] = 0
        features["itt_avg_rank"] = 50.0
        features["same_race_history_count"] = 0
        features["same_race_avg_rank"] = 50.0
        features["same_race_best_rank"] = 50
        features["breakaway_rate"] = 0.0

    return features


# Ordered list of all rider feature names
RIDER_FEATURE_NAMES = [
    "weight", "height", "bmi", "age",
    "spec_one_day", "spec_gc", "spec_tt", "spec_sprint", "spec_climber", "spec_hills",
    "spec_climber_pct", "spec_sprint_pct", "spec_gc_pct",
    "spec_tt_pct", "spec_one_day_pct", "spec_hills_pct",
    "avg_season_points_3yr", "max_season_points_3yr",
    "best_ranking_3yr", "avg_ranking_3yr", "points_trend",
    "career_races", "career_avg_rank", "career_median_rank",
    "career_wins", "career_podiums", "career_top10",
    "career_win_rate", "career_podium_rate", "career_top10_rate",
    "career_avg_pcs_pts", "career_avg_uci_pts",
    "form_30d_races", "form_30d_avg_rank", "form_30d_wins", "form_30d_top10", "form_30d_avg_pcs",
    "form_60d_races", "form_60d_avg_rank", "form_60d_wins", "form_60d_top10", "form_60d_avg_pcs",
    "form_90d_races", "form_90d_avg_rank", "form_90d_wins", "form_90d_top10", "form_90d_avg_pcs",
    "form_180d_races", "form_180d_avg_rank", "form_180d_wins", "form_180d_top10", "form_180d_avg_pcs",
    "form_last5_avg_rank", "form_last5_best_rank", "form_last5_avg_pcs",
    "form_last10_avg_rank", "form_last10_best_rank", "form_last10_avg_pcs",
    "form_last20_avg_rank", "form_last20_best_rank", "form_last20_avg_pcs",
    "terrain_same_profile_races", "terrain_same_profile_avg_rank", "terrain_same_profile_top10",
    "terrain_sim_dist_races", "terrain_sim_dist_avg_rank",
    "mountain_races", "mountain_avg_rank",
    "flat_races", "flat_avg_rank",
    "one_day_races", "one_day_avg_rank",
    "itt_races", "itt_avg_rank",
    "same_race_history_count", "same_race_avg_rank", "same_race_best_rank",
    "breakaway_rate",
]
