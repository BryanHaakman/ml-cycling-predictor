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
- **Features:** 284 features (20 race + 78×2 rider absolute + 78 rider diff + 5 H2H + 24 interaction)
- **Best model:** CalibratedXGBoost — 68.7% accuracy, 0.757 ROC-AUC
- **Train/test split:** Time-based, test years 2025–2026
- **Training time:** ~12 minutes (with pre-computed feature cache)
- **Feature cache:** `data/rider_features_cache.parquet` + `data/race_features_cache.parquet`

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

---

## 2026-03-26 — Feature cache integration

**Hypothesis:** Pre-computing rider/race features to parquet and loading at train time will dramatically reduce training time.

**Method:** `build_feature_matrix()` in pipeline.py now loads cached rider/race features from parquet. H2H and interaction features still computed live (pair-specific). Run `precompute_features.py` once after scraping (~18 min first time, ~1s incrementally), then training loads from cache.

**Results:**
| Step | Without cache | With cache |
|------|-------------|------------|
| Feature assembly | 15m 24s | 3m 44s |
| Model training | 8m 0s | 8m 0s |
| **Total** | **23m 25s** | **11m 44s** |

**Decision:** ✅ Kept. 2× faster training with identical accuracy. Enables rapid experimentation.

---

## 2026-03-26 — Incremental feature improvements (tested individually)

**Hypothesis:** Test fillna fix, race_tier, and new interaction features one at a time to find safe accuracy gains.

**Method:** Each change tested independently with cached features (~12 min per run). All use `caffeinate` to prevent macOS sleep throttling.

**Results:**
| Experiment | Accuracy | ROC-AUC | Brier | Note |
|-----------|----------|---------|-------|------|
| Baseline (cached) | 0.684 | 0.753 | 0.202 | — |
| + fillna fix | 0.687 | 0.754 | 0.201 | rank→50.0 default |
| + race_tier | 0.685 | 0.753 | 0.202 | neutral (90% WT data) |
| + interactions | **0.687** | **0.757** | **0.200** | quality×form = #2 feature |

New interaction features:
- `quality_x_form` = career_top10_rate × (1/form_90d_avg_rank) — **shot to #2 most important feature** (0.056 importance)
- `terrain_x_form` = terrain_same_profile_top10 × (1/form_90d_avg_rank) — made top 20
- `gc_x_profile` = spec_gc × profile_icon_num
- `climber_x_mountain` = spec_climber × (1/mountain_avg_rank) × profile

**Decision:** ✅ All three changes kept. Combined: 284 features, 68.7% acc, 0.757 AUC.

---

## 2026-03-26 — XGBoost hyperparameter search

**Hypothesis:** Default XGB params (depth=8, n=300, lr=0.05) may not be optimal for 238K samples / 284 features.

**Method:** Tested 8 configs varying depth (4-10), n_estimators (300-800), learning rate (0.02-0.05), subsample, colsample_bytree, min_child_weight.

**Results:**
| Config | Depth | N | LR | Accuracy | ROC-AUC |
|--------|-------|---|-----|----------|---------|
| Default | 8 | 300 | 0.050 | 0.680 | 0.750 |
| Best | 8 | 500 | 0.030 | 0.684 | 0.752 |
| Conservative | 4 | 800 | 0.020 | 0.678 | 0.745 |

**Decision:** Marginal improvement. Not worth changing default params since CalibratedXGBoost already outperforms raw XGBoost.

---

## 2026-03-26 — Neural network architecture search

**Hypothesis:** Different NN architectures might beat XGBoost on this dataset.

**Method:** Tested 8 configs: baseline (256-128-64-32), wider (512-256-128-64), deeper (5 layers), low dropout (0.15), big batch (2048), small LR (3e-4), wide+lowdrop, mega (512-512-256-128-64).

**Results:**
| Config | Accuracy | ROC-AUC | Epochs | Time |
|--------|----------|---------|--------|------|
| baseline | 0.685 | 0.753 | 25 | 59s |
| big_batch | 0.684 | **0.754** | 26 | 41s |
| wider | 0.683 | 0.752 | 14 | 46s |
| mega | 0.680 | 0.752 | 20 | 70s |

**Decision:** NN matches XGBoost accuracy (~68.5%) but doesn't beat it. big_batch (bs=2048, lr=2e-3) was marginally best.

---

## 2026-03-26 — XGBoost + NN ensemble

**Hypothesis:** Blending XGBoost and NN predictions may capture different patterns and improve accuracy.

**Method:** Trained XGBoost (n=500, depth=8, lr=0.03) and NN (big_batch config). Tested weighted average blends from 0.3/0.7 to 0.7/0.3.

**Results:**
| Blend (XGB/NN) | Accuracy | ROC-AUC | Brier |
|----------------|----------|---------|-------|
| XGBoost alone | 0.683 | 0.751 | — |
| NN alone | 0.681 | 0.748 | — |
| 0.5/0.5 | 0.687 | 0.755 | 0.201 |
| **0.6/0.4** | **0.687** | **0.755** | **0.201** |

**Decision:** Ensemble slightly better than either model alone (+0.4% AUC over XGB). However, CalibratedXGBoost with the new interactions already achieves 0.757 AUC, so the ensemble doesn't beat calibrated XGB.
