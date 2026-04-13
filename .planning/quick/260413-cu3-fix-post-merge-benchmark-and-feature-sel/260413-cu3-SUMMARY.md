---
phase: quick-260413-cu3
plan: 01
subsystem: models/features
tags: [regression-test, feature-compat, benchmark, tdd]
dependency_graph:
  requires: []
  provides: [feature-compat-test-suite]
  affects: [models/benchmark.py, features/pipeline.py, models/predict.py]
tech_stack:
  added: []
  patterns: [in-memory SQLite fixture, monkeypatch MODELS_DIR, pytest.mark.skipif]
key_files:
  created:
    - tests/test_feature_compat.py
  modified: []
decisions:
  - race_field_size and race_field_avg_quality are documented as known-absent from build_feature_vector_manual by design (require live startlist); tests exempt them explicitly
metrics:
  duration: 12 minutes
  completed: 2026-04-13
---

# Quick Task 260413-cu3: Fix Post-Merge Benchmark and Feature Selection Summary

**One-liner:** 4 regression tests verifying CalibratedXGBoost training path and feature name superset relationship between build_feature_vector_manual and feature_names.json.

## Objective

Verify post-merge integrity of the training pipeline and prediction path after upstream integrated feature selection (top-150 by permutation importance). Two concerns: (1) CalibratedXGBoost still trains and saves correctly; (2) live prediction with a selected feature subset works because build_feature_vector_manual computes all features and subsets via dict.get().

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Audit benchmark.py for CalibratedXGBoost correctness | no-code-change | models/benchmark.py (read-only audit) |
| 2 | Create feature compatibility regression test | 2e793ec | tests/test_feature_compat.py |

## Task 1 Findings

CalibratedXGBoost is correctly implemented and preserved post-merge:
- `CalibratedClassifierCV(method="isotonic", cv=5)` wrapping `XGBClassifier` at lines 263-275
- Saved via `models dict loop` at lines 310-312
- `feature_names.json` saved at line 308
- `scaler.pkl` saved at lines 305-306
- `Predictor.__init__` in `models/predict.py` correctly limits supported models to `("CalibratedXGBoost", "XGBoost")`

No code changes required.

## Task 2: Tests Created

`tests/test_feature_compat.py` — 4 tests, all passing:

1. **test_get_all_feature_names_coverage** — get_all_feature_names() returns 474 names with all 6 expected prefix categories (race_, diff_, a_, b_, h2h_, interact_).

2. **test_manual_vector_covers_canonical_names** — build_feature_vector_manual with a mock DB produces a dict that is a superset of canonical names, with 2 documented exceptions (race_field_size, race_field_avg_quality require a live startlist and are intentionally absent from the manual prediction path).

3. **test_saved_feature_names_subset_of_manual** — If models/trained/feature_names.json exists, every saved name is present in build_feature_vector_manual output (same 2 exemptions). Skipped when file is absent. Currently PASSES with the existing trained artifact.

4. **test_benchmark_saves_calibrated_xgboost** — run_benchmark with a 200-row synthetic dataset saves CalibratedXGBoost.pkl and feature_names.json to tmp_path. Runs in ~4s.

## Verification

- `pytest tests/test_feature_compat.py -v` — 4 passed
- `pytest tests/ -v` — 90 passed, 0 failures

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Mock DB schema mismatch**
- **Found during:** Task 2 (RED phase)
- **Issue:** Plan's suggested mock schema for results table was missing columns (pcs_points, uci_points, breakaway_kms) and riders table was missing specialty/points columns that rider_features.py queries.
- **Fix:** Used PRAGMA table_info() on actual cache.db to extract both tables' full schemas and replicate them in the in-memory fixture.
- **Files modified:** tests/test_feature_compat.py
- **Commit:** 2e793ec

**2. [Rule 1 - Bug] test_saved_feature_names_subset_of_manual failing on known-absent features**
- **Found during:** Task 2 (GREEN phase)
- **Issue:** The test was not exempting race_field_size and race_field_avg_quality, which are intentionally absent from build_feature_vector_manual — same exemption needed as test 2.
- **Fix:** Added known_absent set in test 3 matching test 2's documented exemptions.
- **Files modified:** tests/test_feature_compat.py
- **Commit:** 2e793ec

## Self-Check: PASSED

- tests/test_feature_compat.py: FOUND
- Commit 2e793ec: FOUND
