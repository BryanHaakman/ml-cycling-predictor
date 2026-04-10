# Audit Fixes Plan — 2026-04-10

Source: post-scan code review of core ML pipeline.
Implement in priority order: CRITICAL first, then HIGH.

---

## CRITICAL — Fix immediately (affect every live prediction)

### C1: `race_tier` always = 2 in live predictions
**File:** `features/pipeline.py` ~line 264, `features/race_features.py` ~line 101
**Bug:** `build_feature_vector_manual` builds a synthetic `stage_row` dict from `race_params` but never sets `uci_tour`. `extract_race_features()` calls `tier_map.get(uci_tour, 2)` which always returns the default `2`. Training always has the correct tier from the DB join.
**Fix:** Map `race_params` fields to `uci_tour` in the synthetic `stage_row`. The existing `race_params` keys include enough info (the user passes race tier via the web UI form). Add `uci_tour` to the `stage_row` dict in `build_feature_vector_manual`, derived from `race_params.get("race_base_url", "")` or a new explicit `uci_tour` param.
**Verify:** Manual prediction for a WT race (`1.UWT`) should produce `race_tier = 5 or 6`, not `2`.

---

### C2: `train.py` date/stage alignment silently misaligns when pairs are skipped
**File:** `scripts/train.py` lines 88–90
**Bug:** `build_feature_matrix` skips pairs with missing stage data and drops those rows from anywhere in the DataFrame (not just the tail). `train.py` then does `dates.iloc[:len(feature_df)]` — taking the first N rows of `pairs_df` to match `feature_df`'s length. Since dropped rows can be anywhere, the surviving feature rows don't correspond to the first N pairs. Date and stage_url arrays are misaligned, causing incorrect train/test bucket assignment.
**Fix:** Return the surviving indices from `build_feature_matrix` (or align by index rather than truncation). Simplest fix: reset and align indices after filtering:
```python
# After build_feature_matrix returns feature_df:
# feature_df already has a reset integer index (0..N-1) but corresponds
# to an unknown subset of pairs_df rows.
# Fix: track which pair indices survived inside build_feature_matrix
# and return them, or filter pairs_df to match.
```
The cleanest approach: have `build_feature_matrix` return a filtered `pairs_df` aligned to `feature_df` rows, rather than having `train.py` guess alignment by length.
**Verify:** Add an assertion `len(feature_df) == len(dates)` and confirm it holds even when some pairs are skipped. Check that stratified split assigns stages to correct years.

---

## HIGH — Fix in same pass

### H1: `build_pairs()` non-sampled path has no seed
**File:** `data/builder.py` ~line 63
**Bug:** CONCERNS.md marks seeding as resolved, but only `build_pairs_sampled` was fixed. The original `build_pairs()` uses `random.random() < 0.5` for A/B swap with no seed.
**Fix:** Add `seed: int = 42` parameter to `build_pairs()` and call `random.seed(seed)` at entry, mirroring the fix applied to `build_pairs_sampled`. Update CONCERNS.md resolved note.

---

### H2: Startlist percentiles computed over cache-hit subset, `field_size` is full count
**File:** `features/pipeline.py` lines 502–512
**Bug:** `field_avg_quality`, `field_rank_quality`, `field_rank_form` percentiles only include riders present in the feature cache. But `field_size` is set to `len(riders_in_stage)` — the full count from the results table. Percentile ranks are therefore relative to a partial field.
**Fix:** Set `field_size` to `len(quality_vals)` (the count of cache-hit riders actually used in the computation), OR compute `field_size` separately from the percentile subset and document the distinction. The former is simpler and more consistent.

---

### H3: `auto_settle_from_results` leaves closed connection on exception path
**File:** `data/pnl.py` ~line 315
**Bug:** The loop does `conn.close()` then calls `settle_bet(...)`. If `settle_bet` raises, `conn` is still the closed object. Next iteration calls `conn.execute(...)` → `ProgrammingError`. Remaining bets are silently not settled.
**Fix:** Restructure the loop to reopen the connection before attempting `settle_bet`, or wrap in try/except to reopen on failure. Simplest: move `conn = get_pnl_db(db_path)` to the top of the loop body (before `settle_bet`) so it's always fresh.

---

### H4: Startlist feature defaults are `0.0` — should be neutral values
**File:** `features/pipeline.py` (in `build_feature_vector_manual`, missing startlist block)
**Bug:** `field_strength_ratio` defaults to `0.0` via `fv.get(name, 0.0)`. The neutral/average value is `1.0` (equal field quality). Percentile features (`field_rank_quality`, `field_rank_form`) default to `0.0` — neutral is `0.5`. This systematically misleads the model for every manual prediction.
**Fix:** In `build_feature_vector_manual`, explicitly set neutral defaults for the startlist features that can't be computed without a startlist:
```python
features["a_field_rank_quality"] = 0.5
features["b_field_rank_quality"] = 0.5
features["a_field_rank_form"] = 0.5
features["b_field_rank_form"] = 0.5
features["diff_field_rank_quality"] = 0.0
features["diff_field_rank_form"] = 0.0
features["field_strength_ratio_a"] = 1.0
features["field_strength_ratio_b"] = 1.0
```
Note: Exact feature key names should be verified against `feature_names.json` or the output of `build_feature_matrix`.
**Future improvement:** Accept an optional `startlist` param and compute real values when provided (documented in CONCERNS.md as the full fix).

---

## After Implementation

1. Run `pytest tests/ -v` — must be green
2. Retrain with `python scripts/train.py` and log results in `decision_log.md`
3. Compare new accuracy/AUC against baseline (69.6% / 0.769) — C2 fix may shift numbers if alignment was wrong
4. Update CONCERNS.md resolved section
5. Update CLAUDE.md if best model config changes

---

## Not In Scope Here

- Interaction feature refactor (`_compute_interactions()` helper) — tracked separately in CONCERNS.md
- CI failure alerting — separate infra task
- Full startlist param for `build_feature_vector_manual` — larger change, separate phase
- `p0` in flat-course bin vs PROFILE_MAP inconsistency — benign today, low priority
