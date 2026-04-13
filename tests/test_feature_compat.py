"""
Regression tests for feature selection / prediction compatibility.

Verifies:
1. get_all_feature_names() returns expected prefixes and length.
2. build_feature_vector_manual produces a dict covering canonical feature names.
3. If models/trained/feature_names.json exists, every saved name is present in
   the manual vector (selected subset stays within the full feature set).
4. benchmark.run_benchmark saves CalibratedXGBoost.pkl for a synthetic dataset.
"""

import json
import os
import sqlite3
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from features.pipeline import build_feature_vector_manual, get_all_feature_names

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models", "trained")
FEATURE_NAMES_PATH = os.path.join(MODELS_DIR, "feature_names.json")

# ---------------------------------------------------------------------------
# Shared fixture: minimal in-memory SQLite DB with the correct schema
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_conn():
  """Return an in-memory SQLite connection with the riders/stages/results schema."""
  conn = sqlite3.connect(":memory:")
  conn.row_factory = sqlite3.Row
  conn.executescript("""
    CREATE TABLE riders (
      url TEXT PRIMARY KEY, name TEXT, nationality TEXT, birthdate TEXT,
      weight REAL, height REAL,
      specialty_one_day REAL, specialty_gc REAL, specialty_tt REAL,
      specialty_sprint REAL, specialty_climber REAL, specialty_hills REAL,
      points_history_json TEXT, scraped_at TEXT
    );
    CREATE TABLE stages (
      url TEXT PRIMARY KEY, race_url TEXT, stage_name TEXT, date TEXT,
      distance REAL, vertical_meters REAL, profile_score REAL,
      profile_icon TEXT, avg_speed_winner REAL, avg_temperature REAL,
      departure TEXT, arrival TEXT,
      stage_type TEXT, is_one_day_race INTEGER, race_category TEXT,
      startlist_quality_score TEXT, pcs_points_scale TEXT, uci_points_scale TEXT,
      num_climbs INTEGER, climbs_json TEXT, scraped_at TEXT
    );
    CREATE TABLE races (url TEXT PRIMARY KEY, uci_tour TEXT);
    CREATE TABLE results (
      id INTEGER PRIMARY KEY,
      stage_url TEXT NOT NULL, rider_url TEXT NOT NULL,
      rider_name TEXT, team_name TEXT, team_url TEXT,
      rank INTEGER, status TEXT, age INTEGER, nationality TEXT,
      time_str TEXT, bonus TEXT,
      pcs_points REAL, uci_points REAL, breakaway_kms REAL
    );
    INSERT INTO riders VALUES (
      'rider/test-a', 'Test A', 'BE', '1995-06-15',
      70.0, 1.80, 50.0, 60.0, 40.0, 30.0, 70.0, 45.0,
      '[]', '2026-01-01'
    );
    INSERT INTO riders VALUES (
      'rider/test-b', 'Test B', 'NL', '1993-03-22',
      68.0, 1.78, 40.0, 55.0, 35.0, 80.0, 20.0, 50.0,
      '[]', '2026-01-01'
    );
  """)
  return conn


@pytest.fixture()
def base_race_params():
  """Minimal race_params dict for build_feature_vector_manual."""
  return {
    "distance": 180.0,
    "vertical_meters": 2000.0,
    "profile_icon": "p3",
    "profile_score": 60.0,
    "is_one_day_race": False,
    "stage_type": "RR",
    "race_date": "2026-04-13",
  }


# ---------------------------------------------------------------------------
# Test 1: get_all_feature_names coverage
# ---------------------------------------------------------------------------

def test_get_all_feature_names_coverage():
  """get_all_feature_names returns >400 names with all expected prefix categories."""
  names = get_all_feature_names()

  assert len(names) > 400, (
    f"Expected >400 feature names, got {len(names)}. "
    "Feature set may have shrunk unexpectedly."
  )

  expected_prefixes = ["race_", "diff_", "a_", "b_", "h2h_", "interact_"]
  for prefix in expected_prefixes:
    matching = [n for n in names if n.startswith(prefix)]
    assert matching, (
      f"Expected at least one feature with prefix '{prefix}', found none."
    )


# ---------------------------------------------------------------------------
# Test 2: manual vector covers all canonical names
# ---------------------------------------------------------------------------

def test_manual_vector_covers_canonical_names(mock_conn, base_race_params):
  """
  build_feature_vector_manual output must be a superset of get_all_feature_names().

  Note: race_field_size and race_field_avg_quality are startlist-race-level
  features that require a live startlist; they are absent from the manual
  path by design. These two are the ONLY permitted exceptions.
  """
  fv = build_feature_vector_manual(
    mock_conn, "rider/test-a", "rider/test-b", base_race_params
  )
  assert fv is not None, "build_feature_vector_manual returned None unexpectedly."

  canonical = get_all_feature_names()

  # These two require a live startlist and are intentionally omitted from
  # build_feature_vector_manual.
  known_absent = {"race_field_size", "race_field_avg_quality"}

  missing = [
    n for n in canonical
    if n not in fv and n not in known_absent
  ]
  assert not missing, (
    f"{len(missing)} canonical feature(s) missing from build_feature_vector_manual:\n"
    + "\n".join(f"  - {n}" for n in missing)
  )


# ---------------------------------------------------------------------------
# Test 3: saved feature_names.json is a subset of the manual vector
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
  not os.path.exists(FEATURE_NAMES_PATH),
  reason="models/trained/feature_names.json not present (run train.py first)",
)
def test_saved_feature_names_subset_of_manual(mock_conn, base_race_params):
  """
  Every name in feature_names.json must be producible by build_feature_vector_manual.

  Ensures that feature selection (top-N subset saved to disk) does not silently
  include names that are absent from the live prediction path.
  """
  with open(FEATURE_NAMES_PATH) as f:
    saved_names = json.load(f)

  fv = build_feature_vector_manual(
    mock_conn, "rider/test-a", "rider/test-b", base_race_params
  )
  assert fv is not None

  # race_field_size and race_field_avg_quality require a live startlist and
  # are intentionally absent from build_feature_vector_manual (neutral 0.0
  # substitution is the documented behaviour for the manual/live prediction path).
  known_absent = {"race_field_size", "race_field_avg_quality"}

  missing = [n for n in saved_names if n not in fv and n not in known_absent]
  assert not missing, (
    f"{len(missing)} name(s) from feature_names.json are NOT produced by "
    "build_feature_vector_manual (they would default to 0.0 silently):\n"
    + "\n".join(f"  - {n}" for n in missing)
  )


# ---------------------------------------------------------------------------
# Test 4: benchmark saves CalibratedXGBoost.pkl
# ---------------------------------------------------------------------------

def test_benchmark_saves_calibrated_xgboost(tmp_path, monkeypatch):
  """
  run_benchmark must save CalibratedXGBoost.pkl when given a synthetic dataset.

  Uses monkeypatch to redirect MODELS_DIR to a temp directory so the test
  never pollutes models/trained/ and runs quickly with 10 features.
  """
  import models.benchmark as bm

  # Redirect artifact output to tmp_path
  monkeypatch.setattr(bm, "MODELS_DIR", str(tmp_path))

  rng = np.random.default_rng(42)
  n_rows = 200
  n_feats = 10
  feature_cols = [f"feat_{i}" for i in range(n_feats)]
  X = rng.standard_normal((n_rows, n_feats))
  y = rng.integers(0, 2, size=n_rows)

  feature_df = pd.DataFrame(X, columns=feature_cols)
  feature_df["label"] = y

  # Synthetic stage URLs (each row gets its own stage → 100% stratify works)
  stage_urls = pd.Series([f"race/test/2024/stage-{i}" for i in range(n_rows)])
  date_series = pd.Series(["2024-06-01"] * n_rows)

  result = bm.run_benchmark(
    feature_df=feature_df,
    date_series=date_series,
    select_features=0,
    stage_urls=stage_urls,
    split_mode="stratified",
  )

  # Verify CalibratedXGBoost is in returned models
  assert "CalibratedXGBoost" in result["models"], (
    "run_benchmark did not return CalibratedXGBoost in models dict."
  )

  # Verify .pkl was saved to disk
  pkl_path = os.path.join(str(tmp_path), "CalibratedXGBoost.pkl")
  assert os.path.exists(pkl_path), (
    f"CalibratedXGBoost.pkl was not written to {tmp_path}."
  )

  # Verify feature_names.json was saved
  json_path = os.path.join(str(tmp_path), "feature_names.json")
  assert os.path.exists(json_path), (
    f"feature_names.json was not written to {tmp_path}."
  )

  with open(json_path) as f:
    saved_names = json.load(f)
  assert saved_names == feature_cols, (
    f"feature_names.json content mismatch. Expected {feature_cols}, got {saved_names}."
  )
