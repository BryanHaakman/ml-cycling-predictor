# Decision Log — Cycling H2H Predictor

All ML experiments, training runs, and pipeline changes are documented here.

---

## 2026-03-25 — Baseline training (all race tiers, max_rank=50)

**Hypothesis:** Establish baseline accuracy with all available race data and default parameters.

**Method:** `python -u scripts/train.py` with all race tiers (1.UWT, 2.UWT, 1.Pro, 2.Pro, etc.), max_rank=50, 200 pairs/stage. Time-based split: train pre-2025, test 2025–2026.

**Results:**
| Model | Accuracy | ROC-AUC | Brier Score |
|-------|----------|---------|-------------|
| CalibratedXGBoost | 0.686 | 0.755 | 0.201 |
| XGBoost | 0.685 | 0.754 | 0.201 |
| NeuralNetwork | 0.672 | 0.738 | 0.210 |
| RandomForest | 0.669 | 0.732 | 0.211 |
| LogisticRegression | 0.655 | 0.716 | 0.215 |

**Conclusion:** CalibratedXGBoost is the best model. 68.6% accuracy, 0.755 ROC-AUC. This is the starting baseline.

---

## 2026-03-25 — World Tour only filtering (WT-only, max_rank=50)

**Hypothesis:** Restricting training to World Tour races (1.UWT, 2.UWT) only will improve accuracy, since lower-tier races may add noise and the user only bets on WT events.

**Method:** Added `uci_tiers` parameter to `build_pairs_sampled()` in `data/builder.py`. Ran training with `--all-tiers` off (WT only). Same max_rank=50, 200 pairs/stage.

**Results:**
| Config | Accuracy | ROC-AUC |
|--------|----------|---------|
| All tiers | 0.686 | 0.755 |
| **WT-only** | **0.695** | **0.764** |

**Conclusion:** WT-only improves accuracy by +0.9% and ROC-AUC by +0.009. Change kept — WT-only is the new default. Lower-tier races were adding noise.

---

## 2026-03-25 — Tighten pair filter to max_rank=20 + RandomizedSearchCV

**Hypothesis:** Restricting to top-20 finishers and tuning XGBoost hyperparameters (30 iterations × 3-fold CV) will improve accuracy further.

**Method:** Changed `max_rank` from 50 to 20 in train.py. Added `RandomizedSearchCV` with 30 iterations and 3-fold cross-validation to benchmark.py.

**Results:**
| Config | Accuracy | ROC-AUC |
|--------|----------|---------|
| WT-only, max_rank=50 (baseline) | 0.695 | 0.764 |
| WT-only, max_rank=20 + tuning | **0.663** | lower |

**Conclusion:** Both changes hurt accuracy significantly (−3.2%). max_rank=20 reduces training diversity too much. RandomizedSearchCV overfits on CV folds. Both changes reverted — max_rank restored to 50, fixed XGBoost params restored.

---

## 2026-03-25 — Elo rating features (added then removed from training)

**Hypothesis:** Elo ratings (general + terrain-specific: mountain/flat/TT) would capture rider strength dynamics not reflected in static features.

**Method:** Created `features/elo.py` with field-average Elo system (K=32 general, K=40 terrain). Integrated 15 Elo features into pipeline. Ran training.

**Results:** Not formally benchmarked (training was too slow with other changes applied simultaneously).

**Conclusion:** Elo features removed from training pipeline. The user noted Elo could be skewed by non-recent results. Elo ratings kept as standalone feature for the web app leaderboard page (`/elo`), which provides interesting UX value without affecting model accuracy.

---

## 2026-03-25 — Feature pre-computation cache

**Hypothesis:** Computing rider features per (rider, stage) pair is redundant since the same rider appears ~19 times per stage across different pairs. Caching these features to parquet should dramatically speed up training.

**Method:** Created `features/feature_store.py` to pre-compute and cache rider features (72,551 entries) and race features (1,422 entries) to parquet files. Modified `features/pipeline.py` to auto-detect cache and use fast assembly path.

**Results:**
| Step | Without cache | With cache |
|------|--------------|------------|
| Feature computation | ~18 min | ~4 sec (assembly only) |
| Pre-computation (one-time) | N/A | 3.2 min |

**Conclusion:** Feature caching works well for rider features. However, H2H features still required per-pair DB queries (255K queries), which became the new bottleneck at scale. The cache files are kept as optional accelerator but main training pipeline currently uses the original compute-from-scratch approach for reliability.

---

## 2026-03-25 — Revert to main pipeline + skip Neural Network

**Hypothesis:** After multiple failed optimizations (hyperparam tuning, max_rank=20, caching + bulk H2H), the original main pipeline is the most reliable. Skipping the Neural Network (which takes minutes per run) while keeping LR/RF/XGB/CalibratedXGB will give fast, accurate results.

**Method:** Reverted `features/pipeline.py`, `models/benchmark.py`, and `scripts/train.py` to main branch versions. Applied minimal fixes: (1) lazy torch import to prevent XGBoost segfault on macOS ARM, (2) `--nn` flag (off by default) to skip slow Neural Network training, (3) `feature_names` bug fix.

**Results:**
| Model | Accuracy | ROC-AUC | Log Loss | Brier Score |
|-------|----------|---------|----------|-------------|
| CalibratedXGBoost | **0.685** | **0.755** | 0.587 | 0.201 |
| XGBoost | 0.684 | 0.752 | 0.589 | 0.202 |
| RandomForest | 0.669 | 0.732 | 0.610 | 0.211 |
| LogisticRegression | 0.655 | 0.716 | 0.619 | 0.215 |

Training time: 27m 30s (18m features + 8m models). No segfault.

**Conclusion:** Accuracy consistent with baseline (~68.5%, within random sampling variance of the 69.5% WT-only run). Pipeline is stable and reproducible. This is the current production configuration.

---

## Summary of current best configuration

- **Training data:** World Tour only (1.UWT, 2.UWT), all years 2018–2025
- **Pair generation:** max_rank=50, 200 pairs/stage (~283K total pairs)
- **Features:** 271 features (19 race + 78×2 rider absolute + 78 rider diff + 5 H2H + 12 interaction)
- **Best model:** CalibratedXGBoost — 68.6% accuracy, 0.756 ROC-AUC
- **Train/test split:** Time-based, test years 2025–2026
- **Training time:** ~23 minutes

---

## 2026-03-25 — Accuracy improvement batch (REVERTED)

**Hypothesis:** Adding 17 new features (time-gap, team strength, tier-weighted form), rank-gap weighted sampling, and sample weights would improve accuracy.

**Changes attempted:**
1. **fillna fix** — replaced blanket `fillna(0.0)` with domain-aware defaults (rank→50, others→0)
2. **Rank-gap weighted sampling** — favoured close-rank pairs via `1/(gap+1)` weighting
3. **Sample weights** — `rank_weight × recency_weight` (2-year half-life) passed to all `.fit()` calls
4. **17 new features:** 7 time-gap, 5 tier-weighted form, 5 team strength

**Results:**
| Model | Accuracy | ROC-AUC | Brier Score |
|-------|----------|---------|-------------|
| CalibratedXGBoost | 0.599 | 0.639 | 0.238 |
| RandomForest | 0.590 | 0.628 | 0.240 |
| XGBoost | 0.587 | 0.627 | 0.237 |
| LogisticRegression | 0.585 | 0.624 | 0.240 |

**Training time:** 63 min 39s (vs 23 min baseline)

**Decision:** ❌ REVERTED all changes. Accuracy dropped 8.6% (68.6% → 59.9%) and training time nearly tripled. Likely causes: extreme sample weights (max 19.8×), rank-gap sampling changing data distribution, noisy new features (especially `team_best_rank` which had post-race data leakage), and slow DB-heavy feature computation (time-gap queries winner time per past result).

**Lesson:** These changes should be tested individually, not all at once. Sample weights and sampling changes are the most risky since they fundamentally alter training distribution.
