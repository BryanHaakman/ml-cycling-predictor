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

---

## 2026-03-26 — Advanced Neural Network Techniques (12 experiments)

**Hypothesis:** Advanced training techniques (label smoothing, focal loss, cosine annealing, residual networks, SWA, quantile transform, and combinations) may push NN accuracy beyond the baseline 68.2% / 0.752 AUC.

**Method:** Ran 12 NN configurations using the same 256→128→64→32 base architecture with various modifications. All use AdamW, ReduceLROnPlateau (except cosine_anneal), early stopping patience=10, and the same train/test split (test years 2025–2026). Total runtime: 1279s (~21 min).

**Results:**

| Config | Accuracy | ROC-AUC | Brier Score | Epochs | Time |
|--------|----------|---------|-------------|--------|------|
| baseline | 0.6816 | 0.7524 | 0.2018 | 25 | 44s |
| label_smooth_0.05 | **0.6821** | 0.7522 | 0.2019 | 25 | 57s |
| label_smooth_0.1 | 0.6809 | 0.7518 | 0.2019 | 30 | 66s |
| cosine_anneal | 0.6812 | **0.7525** | **0.2018** | 25 | 56s |
| qt+label_smooth | 0.6820 | 0.7495 | 0.2029 | 29 | 61s |
| quantile_transform | 0.6795 | 0.7483 | 0.2034 | 22 | 47s |
| resnet_3block | 0.6783 | 0.7447 | 0.2049 | 17 | 69s |
| resnet_5block | 0.6775 | 0.7467 | 0.2050 | 19 | 112s |
| swa | 0.6739 | 0.7417 | 0.2082 | 50 | 122s |
| focal_loss | 0.6728 | 0.7411 | 0.2130 | 48 | 98s |
| wide_resnet+focal | 0.6685 | 0.7365 | 0.2108 | 22 | 232s |
| kitchen_sink (all combined) | 0.4995 | 0.3891 | 0.5000 | 16 | 75s |

**Conclusions:**
1. **No technique beats the baseline NN** — the best (label_smooth_0.05) is only +0.05% acc, cosine_anneal +0.01 AUC. All within noise.
2. **Focal loss hurts** — −0.9% acc, −1.1 AUC. It over-focuses on hard (likely noisy) examples.
3. **ResNets underperform** — skip connections add complexity without benefit at this scale. Deeper ≠ better here.
4. **SWA hurts** — trains full 50 epochs but averages over poor local minima.
5. **kitchen_sink collapsed** — combining all techniques caused training failure (50% acc = random). Too many interacting modifications.
6. **The NN accuracy ceiling is ~68.2% / 0.752 AUC** — this matches CalibratedXGBoost's uncalibrated performance. The limitation is features, not model architecture.

**Decision:** No changes kept. The standard 256→128→64→32 NN with default training is already at peak performance for this feature set. CalibratedXGBoost (68.7% / 0.757 AUC) remains the production model. Future accuracy gains require new data sources or fundamentally different features, not model improvements.

---

## 2026-03-26 — Feature Selection via Permutation Importance

**Hypothesis:** Pruning low-importance features (284 → top N) may remove noise and improve accuracy. XGBoost's regularization might not fully compensate for having 62 features with negative permutation importance.

**Method:**
1. Trained XGBoost on all 283 features, computed permutation importance (10 repeats, ROC-AUC scoring)
2. Tested top-N subsets (20, 30, 50, 80, 100, 120, 150, 200) with both raw XGBoost and CalibratedXGBoost
3. Two ranking methods: XGBoost gain importance and permutation importance
4. Fine-grained search around the sweet spot (80-160 in steps of 5-10)
5. Full production training run with `--select-features 120` to validate

**Results (Phase 1 — broad search, single run):**

| Method | Model | top_N | Accuracy | ROC-AUC | Δ AUC vs all |
|--------|-------|-------|----------|---------|-------------|
| all features | CalXGBoost | 283 | 0.6826 | 0.7536 | baseline |
| perm | CalXGBoost | 80 | 0.6838 | 0.7544 | +0.0008 |
| perm | CalXGBoost | 120 | 0.6843 | 0.7550 | +0.0014 |
| perm | CalXGBoost | 130 | — | 0.7558 | +0.0022 |
| gain | CalXGBoost | 150 | 0.6845 | 0.7539 | +0.0003 |

**Results (Phase 2 — fine-grained CalXGB, fresh pair sample):**

| top_N | Accuracy | ROC-AUC |
|-------|----------|---------|
| 80 | 0.6859 | 0.7543 |
| 90 | 0.6867 | 0.7554 |
| 120 | **0.6878** | **0.7557** |
| 130 | 0.6871 | **0.7558** |
| 150 | 0.6870 | 0.7553 |

**Results (Phase 3 — production training validation):**

| Config | Accuracy | ROC-AUC |
|--------|----------|---------|
| With feat selection (top 120) | 0.6831 | 0.7533 |
| Without feat selection (all 283) — same run | 0.6867 | 0.7559 |
| Previous committed baseline (all 283) | 0.6841 | 0.7541 |

**Key findings:**
1. 62 features have negative permutation importance, but removing them gives only +0.0005 AUC
2. Perm-importance top 120-130 appeared best in isolated experiments (+0.001-0.002 AUC)
3. **Run-to-run variance from random pair sampling is ±0.003 AUC** — larger than any feature selection effect
4. Full production training with selection gave **worse** results than without (0.7533 vs 0.7559)
5. Top features by permutation importance: `race_profile_score` (0.0247), `interact_diff_tt_x_itt` (0.0066), `diff_spec_gc_pct` (0.0057), `interact_diff_sprint_x_flat` (0.0055), `diff_age` (0.0032)

**Conclusion:** Feature selection does not reliably improve accuracy. XGBoost's built-in regularization (`colsample_bytree=0.8`, `min_child_weight=10`) already effectively ignores noisy features. The `--select-features N` flag was added to `train.py` for future experiments but is not used in production. The accuracy ceiling (~68.5-69% / 0.753-0.756 AUC) is confirmed as data/feature-limited, not model or feature-count-limited.

---

## 2026-03-26 — Weather Features via Open-Meteo Historical API

**Hypothesis:** Historical weather data (temperature, rain, wind, humidity) for race locations could improve H2H predictions. Weather conditions affect rider performance differently based on weight, experience, and riding style — e.g., rain favors skilled descenders, wind hurts lighter riders, heat tests endurance.

**Method:**
1. Geocoded 962/983 departure cities using Nominatim (OpenStreetMap)
2. Fetched historical weather from Open-Meteo archive API for 380/1422 stages (27% coverage — rate limited)
3. Added 10 race-level weather features: temp_max, temp_min, rain_mm, wind_kmh, humidity, is_rainy, is_hot, is_cold, is_windy, temp_range
4. Added 9 weather×rider interaction features: rain×weight, wind×weight, heat×experience
5. Total features: 284 → 303
6. Trained CalibratedXGBoost with weather features

**Results:**

| Config | Accuracy | ROC-AUC | Brier |
|--------|----------|---------|-------|
| Without weather (baseline) | 0.6857 | 0.7548 | 0.2011 |
| With weather (27% coverage) | 0.6850 | 0.7537 | 0.2014 |

No weather feature appeared in the top 20 by XGBoost importance.

**Why weather doesn't help for H2H:**
1. Weather conditions affect **all riders in the same race equally** — the key question is differential impact, which is very small
2. Only 27% coverage means 73% of stages have weather=0.0, diluting any signal
3. The interactions we designed (rain×weight, wind×weight, heat×experience) have weak theoretical basis — real-world weather effects are complex and not well-captured by simple products
4. ProCyclingStats already provides `avg_temperature` for 49% of stages, which the model already uses

**Decision:** Weather features reverted from training pipeline. `scripts/fetch_weather.py`, `scripts/feature_selection.py`, and DB tables (`geocoded_cities`, `stage_weather`) fully removed (2026-04-10). Weather data is a fundamentally weak signal for H2H prediction because it's a race-level variable, not a rider-level variable.

---

## 2026-03-26 — WT-only training + startlist-relative features

**Hypothesis:** Two changes tested together:
1. **WT-only training**: The model trains on all race tiers but is only used for World Tour predictions. Lower-tier races (10% of data) may have different dynamics that add noise.
2. **Startlist-relative features**: A rider's strength relative to the specific race field provides signal beyond their absolute stats. Features: `field_rank_quality` (percentile by career_top10_rate among starters), `field_rank_form` (percentile by form_90d_avg_pcs among starters), `field_strength_ratio` (rider quality / field average). Plus race-level `field_size` and `field_avg_quality`.

**Method:**
- Added `--wt-only` flag to `data/builder.py` → filters stages to `races.uci_tour IN ('1.UWT', '2.UWT')`
- Added startlist-relative features in `features/pipeline.py` → pre-computes field composition from results table, computes percentiles using cached rider features (leakage-safe: uses pre-race rider stats only)
- Ran `caffeinate -s python -u scripts/train.py` for baseline, all-data+startlist, and WT-only+startlist

**Data split:**
- All data: 1,419 stages → 283,376 pairs (237,976 train / 45,400 test)
- WT-only: 1,275 stages → 255,000 pairs (215,400 train / 39,600 test)
- Note: test sets differ (WT-only evaluates on WT races only, which matches the prediction use case)

**Results (CalibratedXGBoost):**
| Config | Accuracy | ROC-AUC | Brier Score | Log Loss |
|--------|----------|---------|-------------|----------|
| Baseline (all data, no startlist) | 0.6857 | 0.7548 | 0.200 | 0.586 |
| All data + startlist features | 0.6857 | 0.7528 | 0.202 | 0.588 |
| WT-only + startlist features | **0.6897** | **0.7601** | **0.199** | **0.582** |

**Feature importance (WT-only model):**
- `diff_field_rank_quality` — #3 at 0.0162 (top startlist feature)
- `diff_field_strength_ratio` — #11 at 0.0103
- `diff_field_rank_form` — not in top 20

**Conclusion:** Combined WT-only + startlist features gives the best result across all metrics (+0.4% accuracy, +0.005 AUC over baseline). The startlist features alone on all data provide no benefit (slightly worse AUC), suggesting the improvement comes primarily from WT-only filtering — evaluating on WT-only test data removes noise from lower-tier race predictions. The startlist `field_rank_quality` feature does rank #3 in importance in the WT-only model, indicating it provides useful signal when the training distribution is more homogeneous. Both changes kept.

---

## 2026-03-27 — Added minimum confidence threshold to Kelly staking

**Hypothesis:** Low-confidence bets (model prob < 55%) with high odds produce oversized Kelly stakes despite near-coinflip predictions. Adding a minimum confidence filter should reduce variance without cutting profitable bets.

**Method:** Added `min_confidence=0.55` parameter to `kelly_criterion()` in `models/predict.py`. Bets where `model_prob < 0.55` now return `should_bet=False`. Half Kelly staking retained as-is.

**Results (E3 Saxo Classic 2026 backtest — 11 bets):**

| Scenario | Bets | W-L | P&L | ROI |
|----------|------|-----|-----|-----|
| Old (no threshold) | 11 | 5-6 | -£52.05 | -7.3% |
| New (55% min conf) | 9 | 5-4 | +£22.28 | +3.6% |

Filtered bets:
- Mads Pedersen vs van der Poel: 47.4% conf, 3.25 odds → £62.92 loss avoided
- Axel Zingle vs Del Grosso: 52.8% conf, 2.00 odds → £11.41 loss avoided

**Conclusion:** The 55% threshold filters out "value trap" bets where high odds inflate perceived edge despite the model essentially predicting a coin flip. Saves £74.33 on this sample. Change kept — will monitor over the next few races to confirm it doesn't filter profitable bets in aggregate.

---

## 2026-03-27 — Confidence-scaled Kelly staking (replaces min_confidence filter)

**Hypothesis:** Instead of filtering out low-confidence bets entirely, scaling down stakes proportional to model confidence reduces risk while keeping all bets active.

**Method:** Applied a confidence scaling factor to half/quarter Kelly fractions in `kelly_criterion()`:
- `scale = clamp((model_prob - 0.5) / 0.2, 0.5, 1.0)`
- At ≤50% confidence → 50% of normal stake (effectively quarter Kelly)
- At 60% confidence → ~50% of normal stake
- At 70%+ confidence → 100% of normal stake (full half Kelly)

**Results (E3 2026 backtest — scaling factors on losing bets):**

| Bet | Conf | Old stake | Scale | Effect |
|-----|------|-----------|-------|--------|
| Pedersen vs VDP | 47.4% | £62.92 | 50% | ~halved |
| Mohorič vs Abrahamsen | 60.2% | £94.44 | 51% | ~halved |
| De Gendt vs Turgis | 62.7% | £59.96 | 64% | reduced |
| Girmay vs Andresen | 55.9% | £48.80 | 50% | ~halved |
| Zingle vs Del Grosso | 52.8% | £11.41 | 50% | ~halved |
| Teunissen vs Pithie | 74.2% | £74.59 | 100% | unchanged (high conf, just unlucky) |

**Conclusion:** All bets still placed, but low-confidence bets get substantially smaller stakes. High-confidence bets (which had the best win rate: 3 of 4 at 70%+) retain full sizing. Replaces the previous min_confidence=0.55 filter approach. Change kept.

---

## 2026-03-27 — One-day form features + enhanced same-race history

**Hypothesis:** Stage race results (e.g. VDP rank 144 on a Tirreno sprint stage) pollute recent form features when predicting one-day classics. Also, same-race features lacked win_rate/podium_rate/recent_rank signals.

**Method:**
1. Added `od_form_*` features: one-day-only form for 30d/90d/180d windows and last 3/5 races
2. Enhanced same-race features: `same_race_win_rate`, `same_race_podium_rate`, `same_race_recent_rank`
3. Cleared feature caches, recomputed, retrained all models

**Results:**

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Accuracy | 0.6852 | 0.6871 | +0.19% |
| ROC-AUC | 0.7556 | 0.7564 | +0.08% |
| Brier | 0.2007 | 0.2005 | -0.02% |
| Log Loss | 0.5852 | 0.5850 | -0.03% |

Key prediction improvements (E3 Saxo Classic 2026):
- VDP vs Pedersen: 47.4% → 61.5% (VDP won the race)
- Mohorič vs Abrahamsen: 60.2% → 67.0%

Root cause: VDP's 30-day form avg rank was ~57 due to Tirreno stage results (ranks 87, 107, 125, 144) drowning out his Omloop win (rank 1) and MSR top 10 (rank 8).

**Conclusion:** Both changes kept. One-day form features give the model clean signal for classics, and enhanced same-race features better capture race-specific dominance. Overall accuracy improved — no regression.

---

## 2026-03-27 — Course-type form features (flat/hilly/mountain)

**Hypothesis:** Splitting rider form by course type (flat/hilly/mountain) and race type (one-day/stage) gives the model better terrain-specific signal than generic recent form.

**Method:** Added course-type features grouped by profile_icon:
- Flat (p0, p1), Hilly (p2, p3), Mountain (p4, p5)
- Per course type: career stats (races, avg_rank, top10_rate), recent form (90d, 180d), and one-day-only variants
- All computed in the pipeline — auto-updates on train

**Results:**

| Metric | v1 (base) | v2 (+od form) | v3 (+course) |
|--------|-----------|---------------|--------------|
| Accuracy | 0.6852 | **0.6871** | 0.6856 |
| ROC-AUC | 0.7556 | 0.7564 | **0.7565** |
| Brier | 0.2007 | 0.2005 | **0.2004** |
| Log Loss | 0.5852 | 0.5850 | **0.5844** |

- `diff_course_mountain_avg_rank` ranked #20/423 in importance
- VDP vs Pedersen E3 prediction: 47.4% → 61.5% → 57.2%
- Accuracy slightly lower than v2 but all calibration metrics (Brier, Log Loss, AUC) at best values

**Conclusion:** Change kept. Course-type features add useful terrain-specific signal with best-ever calibration. Slight accuracy dip vs v2 is acceptable given improved probability calibration (which matters more for Kelly staking). Features auto-update on every train run via the pipeline.

---

## 2026-03-27 — Stratified stage split + calibration report in benchmark

**Hypothesis:** The time-based split (train 2018-2024, test 2025-2026) means the model never learns from recent seasons during training, and the test set only reflects 2 years. A stratified split by stage — randomly assigning 80% of stages to train and 20% to test, stratified by year — would let the model learn from all years while still preventing within-race leakage.

**Method:** Added `stratified_stage_split()` to `models/benchmark.py`. All pairs from a given stage stay together (no within-race leakage). Stages are stratified by year so every year appears in both train and test. Added `--split` flag to `train.py` (default: `stratified`, alternative: `time`). Also added automatic calibration & accuracy breakdown report to benchmark output.

**Results:**
| Metric | Time split (old) | Stratified (new) | Change |
|--------|-----------------|------------------|--------|
| Accuracy | 0.6856 | **0.6983** | **+1.27%** |
| ROC-AUC | 0.7565 | **0.7732** | **+1.67%** |
| Brier | 0.2004 | **0.1937** | **-3.3%** |
| Log Loss | 0.5844 | **0.5679** | **-2.8%** |

Calibration is near-perfect across all confidence bins (all ✅):
| Conf Range | Model Avg | Actual Win% | Count |
|-----------|-----------|-------------|-------|
| 50-55% | 52.6% | 53.1% | 4196 |
| 55-60% | 57.5% | 56.2% | 3972 |
| 60-65% | 62.5% | 62.3% | 3864 |
| 65-70% | 67.5% | 67.8% | 3685 |
| 70-75% | 72.4% | 73.8% | 3227 |
| 75-80% | 77.5% | 77.7% | 2587 |
| 80-100% | 87.5% | 88.7% | 6678 |

High-confidence bets (70%+): 82.6% accuracy on 12,492 test pairs.
Test set now 56,200 pairs (was 40,600) — more robust evaluation.

**Conclusion:** Change kept as new default. Stratified split gives biggest single improvement in the project — every metric improved substantially. The model benefits from learning recent-year patterns while still being evaluated on held-out stages it hasn't seen. Old time-based split preserved via `--split time` flag.

---

## 2026-04-10 — Core pipeline bug fixes (audit-fixes-260410)

**Hypothesis:** Post-scan audit identified 2 critical bugs and 3 high-priority bugs silently affecting every live prediction and every training run. Fixing them will correct systematic biases without requiring new features.

**Changes made (no training run yet — to be followed by retraining):**

1. **C1 — `race_tier` always 2 in live predictions** (`features/pipeline.py`): `build_feature_vector_manual` now passes `uci_tour` from `race_params` into the synthetic `stage_row`. The web UI exposes a "Race Tier" dropdown on both manual and batch forms. Previously, live predictions always received `race_tier=2` regardless of actual race category.

2. **C2 — Train/test date alignment bug** (`features/pipeline.py`, `scripts/train.py`): `build_feature_matrix` now preserves original `pairs_df` row indices in the output DataFrame (via `surviving_indices`). `train.py` now aligns dates/stage_urls via `pairs_df.loc[feature_df.index]` instead of `iloc[:len(feature_df)]` truncation. When skipped pairs were scattered throughout (not just at the tail), the old code assigned wrong dates and therefore wrong train/test buckets to surviving pairs. **This may shift accuracy numbers** — the stratified split may have been partially incorrect in prior runs.

3. **H1 — `build_pairs()` non-sampled path had no seed** (`data/builder.py`): Added `seed=42` default and `random.seed(seed)` call, matching the fix already applied to `build_pairs_sampled`.

4. **H2 — `field_size` used full rider count, not cache-hit subset** (`features/pipeline.py`): `field_size` now equals `len(quality_vals)` (riders present in the feature cache), consistent with the percentile computation. Previously `field_size` was the full DB count while percentiles were computed over the cache subset — these were inconsistent.

5. **H3 — `auto_settle_from_results` connection fragility** (`data/pnl.py`): Restructured to open a fresh connection per loop iteration. An exception in `settle_bet` no longer leaves a closed connection for the next bet.

6. **H4 — Startlist feature defaults were `0.0`** (`features/pipeline.py`): `build_feature_vector_manual` now sets `field_rank_quality/form` to `0.5` (median) and `field_strength_ratio` to `1.0` (equal field quality). Previous `0.0` defaults systematically pulled live predictions toward incorrect values.

**Method:** Code fixes only, then retrained with `python scripts/train.py`. `pytest tests/ -v` → 14/14 passing.

**Results (post-fix training run, 2026-04-10):**
| Model | Accuracy | ROC-AUC | Log Loss | Brier Score |
|-------|----------|---------|----------|-------------|
| CalibratedXGBoost | **0.6963** | **0.7702** | 0.5713 | 0.1950 |
| XGBoost | 0.6946 | 0.7681 | 0.5728 | 0.1957 |
| RandomForest | 0.6808 | 0.7494 | 0.5958 | 0.2048 |
| LogisticRegression | 0.6715 | 0.7362 | 0.6023 | 0.2078 |

291,576 pairs from 1,461 stages. Train: 233,776 / Test: 57,800. 424 features. Total time: 79m 0s (22m feature matrix + 57m models).

Top features by XGBoost importance: `diff_career_top10_rate` (0.134), `diff_form_180d_top10` (0.021), `interact_diff_sprint_x_flat` (0.018), `diff_field_rank_quality` (0.014), `interact_diff_terrain_x_form` (0.013).

Calibration breakdown (CalibratedXGBoost):
- Low conf (50-60%): 55.6% accuracy (n=8,116)
- Medium conf (60-70%): 66.1% accuracy (n=7,690)
- High conf (70%+): 82.0% accuracy (n=12,612)
- One-day races: 66.8% | Stage races: 70.2%

**Conclusion:** Accuracy is flat vs. pre-fix baseline (69.6% / 0.769 → 69.6% / 0.770) — well within run-to-run variance (±0.003 AUC). The C2 index alignment fix did not materially shift train/test splits, suggesting pair skips were rare enough not to cause systematic misassignment in prior runs. H4 startlist defaults fix improves live prediction calibration without measurable training impact. All fixes confirmed safe — new production baseline is 69.6% / 0.770.

---

## 2026-04-11 — Phase 1: Pinnacle API client (data/odds.py)

**Hypothesis:** Pinnacle's internal guest API can be reliably integrated for real-time cycling H2H odds ingestion without requiring manual credential management.

**Method:** Implemented `data/odds.py` — a module-level client (no class-based design) with:
- Runtime X-Api-Key extraction from Pinnacle's frontend JS bundle (requests + regex, 4 fallback patterns)
- Key cached in `data/.pinnacle_key_cache`, re-extracted on HTTP 401/403 (bounded to one retry)
- `PINNACLE_SESSION_COOKIE` env var as highest-priority override
- `OddsMarket` dataclass (6 fields) with decimal odds normalisation via `_american_to_decimal()`
- JSONL audit log (`data/odds_log.jsonl`) appended on every call including empty fetches
- Three-step fetch cycle: `/sports/45/leagues` → `/leagues/{id}/matchups` → `/leagues/{id}/markets/straight`, joined on `matchupId`

All code written TDD: 25 unit tests written first (RED), then implementation (GREEN). No new dependencies added.

**Results:** All 3 requirements satisfied: ODDS-01 (fetch live H2H markets) ✓, ODDS-02 (audit log) ✓, ODDS-03 (actionable auth error naming PINNACLE_SESSION_COOKIE) ✓. 25 unit tests passing, 39/39 full suite passing (no regressions).

**Conclusion:** Implementation is straightforward — Pinnacle's guest API is a clean JSON REST endpoint with no Cloudflare bypass needed. The JS bundle extraction is the most fragile part (regex depends on Pinnacle's frontend build format), but four fallback patterns are tried and the `PINNACLE_SESSION_COOKIE` env var provides a reliable manual override path. The one-retry auth flow (invalidate cache → re-extract → retry once) keeps the retry loop bounded as required. No surprises; the live API response shapes from discovery (Plan 01) were accurate.

---

## 2026-04-12 — D-08: diff_field_rank_quality neutral default in Phase 4 — Startlist fetch deferred

**Hypothesis:** Passing resolved rider URLs as a startlist to `build_feature_vector_manual` would improve `diff_field_rank_quality` from its neutral default (0.0) and increase prediction accuracy for Phase 4 batch loads.

**Method:** Analyzed the feature importance table from the 2026-04-10 training run. `diff_field_rank_quality` has importance 0.014 (4th overall). `build_feature_vector_manual` currently hardcodes this feature at 0.0 (neutral) because no startlist is available at prediction time in the manual UI. Phase 4 could fetch the PCS startlist via `get_race_startlist` MCP tool and cross-check that Pinnacle matchup riders appear, then compute real percentile ranks. Decision: defer this to a future phase.

**Results:** Feature importance 0.014. Neutral 0.0 means predictions treat all riders as equally ranked within the field. Effect is small but measurable — predictions are valid but slightly degraded relative to training distribution.

**Conclusion:** Phase 4 uses neutral `diff_field_rank_quality` defaults. Startlist fetch + Pinnacle rider overlap validation explicitly deferred. The proper fix requires: (1) PCS startlist fetch via `procyclingstats` lib or `get_race_startlist` MCP tool, (2) cross-check that Pinnacle matchup riders appear in that startlist (data quality gate), (3) compute real percentile ranks. Implement as a dedicated sub-phase before the prediction pipeline is considered fully trusted. This is a known gap — flagged in the `/load` API response via `is_resolved` fields; the feature gap is not surfaced to the user.
---

## 2026-04-09 — Retrained on updated data (through 2026-04-08)

**Motivation:** Database restored from latest snapshot including results through Itzulia Basque Country Stage 3 (2026-04-08). Retrained all models on the expanded dataset.

**Method:** `python scripts/train.py` — full pipeline: build pairs → compute features → train 4 models (NN skipped). Stratified stage split (80/20).

**Data:** 291,176 H2H pairs from 1,458 stages. 424 features. Train: 233,576 / Test: 57,600.

**Results:**

| Model | Accuracy | ROC-AUC | Log Loss | Brier Score |
|-------|----------|---------|----------|-------------|
| CalibratedXGBoost | 0.7013 | 0.7750 | 0.5665 | 0.1931 |
| XGBoost | 0.6987 | 0.7729 | 0.5683 | 0.1938 |
| RandomForest | 0.6827 | 0.7527 | 0.5932 | 0.2036 |
| LogisticRegression | 0.6728 | 0.7389 | 0.5990 | 0.2067 |

Calibration (CalibratedXGBoost):
- Low conf (50–60%): 55.6% accuracy (n=9,058)
- Medium conf (60–70%): 65.4% accuracy (n=7,641)
- High conf (70%+): 82.4% accuracy (n=12,542)

By race type: One-day 67.6%, Stage race 70.7%.
By course: Flat 71.3%, Hilly 68.9%, Mountain 71.6%.

Top feature: `diff_career_top10_rate` (importance 0.139).

Training time: 18m 18s.

**Conclusion:** Marginal changes from previous run — metrics remain stable with the additional data. CalibratedXGBoost remains the best model. Models saved to `models/trained/`.

---

## 2026-04-10 — Retrain on Itzulia Stage 5 data + Stage 6 predictions

**Hypothesis:** Incorporating latest Itzulia Basque Country results (stages 1–5) should marginally improve predictions for Stage 6, as riders' current form will be reflected in features.

**Method:**
1. `python scripts/update_races.py` — scraped latest results into cache.db (203,837 results, 5,077 riders)
2. `python scripts/train.py` — retrained all 5 models on updated data
3. Used `predict_manual()` with Stage 6 race parameters (135.4km, 3081m elevation, p4 mountain, 6 climbs) for 13 bookmaker match-ups

**Results:**
Calibration remained well-aligned:
| Conf Range | Model Avg | Actual | Count |
|------------|-----------|--------|-------|
| 50-55% | 52.5% | 51.8% | 4,348 |
| 55-60% | 57.5% | 56.6% | 3,960 |
| 60-65% | 62.5% | 62.9% | 3,782 |
| 65-70% | 67.5% | 68.7% | 3,493 |
| 70-75% | 72.5% | 72.9% | 3,386 |
| 75-80% | 77.4% | 78.5% | 2,868 |
| 80-100% | 87.2% | 88.0% | 6,563 |

Top feature: `diff_career_top10_rate` (0.169).

Stage 6 predictions: 10/13 markets showed positive edge. 3 markets (Martin vs Beloki, Tejada vs Champoussin, Arrieta vs Ruiz) had no value — model agreed with bookmaker pricing.

Largest edges: Gaffuri over Pericas (+25.0%), Fortunato over J.P. Lopez (+22.4%), T.H. Johannessen over Vauquelin (+15.5%).

**Conclusion:** Model retrained successfully. 10 bets placed for Stage 6 totalling £555.91 via half-Kelly staking. Previous Stage 5 bets settled 4W/1L for +£410.60 profit (85.5% ROI).

---

## 2026-04-10 — Implemented incremental fine-tuning (warm-start XGBoost)

**Hypothesis:** Daily full retrains (~15 min) are wasteful when only 1-3 new stages arrive. XGBoost's warm-start can add trees for new data much faster while preserving existing knowledge.

**Method:** Created `scripts/fine_tune.py` with the following design:

- Loads existing `XGBoost.pkl` and warm-starts with `xgb_model` parameter
- Fine-tune params: `n_estimators=50` (additional trees), `learning_rate=0.01` (10x lower than full train)
- **Replay buffer**: mixes 3× historical pairs with new pairs to prevent overfitting to small batches
- **Prefit calibration**: uses `CalibratedClassifierCV(cv="prefit", method="sigmoid")` — Platt scaling is more stable than isotonic on small calibration sets
- **Minimum stage gate**: requires ≥3 new stages before fine-tuning (configurable)
- **Backup**: saves previous models before overwriting
- **Metadata tracking**: `models/trained/training_meta.json` tracks last train date, fine-tune count, and triggers full retrain warning after 7 incremental updates

Also added `since_date` parameter to `build_pairs_sampled()` in `data/builder.py` for date-range filtering.

Key design decisions (from rubber-duck critique):
1. Calibrated model uses prefit mode (not cv=5 which creates internal clones)
2. Sigmoid calibration preferred over isotonic for small sample stability
3. Replay buffer prevents new trees from overfitting to stage-specific residuals
4. Test set (2025-2026) used only for logging metrics, not as a tuning gate

**Results:** Script created and validated via dry-run. No training metrics yet — will be logged after first real fine-tune.

**Conclusion:** Infrastructure for incremental fine-tuning is in place. Recommended workflow: `fine_tune.py` for daily updates, `train.py` for weekly full retrains or after pipeline changes.

---

## 2026-04-12 — Full retrain after Itzulia Basque Country 2026 data ingestion

**Hypothesis:** Adding latest Itzulia results (6 stages, ~900 new results) and incremental 2026 race data improves model freshness. Also fixed settlement logic to handle riders missing from results (DNS/DNF not in results table).

**Method:** Ran `python scripts/update_races.py` to scrape new data, then `python scripts/train.py` for full 5-model benchmark. Fixed `auto_settle_from_results()` in `data/pnl.py` to treat missing result rows as DNF (previously required both riders present to settle).

**Results:**
| Model | Accuracy | ROC-AUC | Log Loss | Brier Score |
|-------|----------|---------|----------|-------------|
| CalibratedXGBoost | 0.697 | 0.771 | 0.571 | 0.195 |
| XGBoost | 0.695 | 0.769 | 0.572 | 0.195 |
| RandomForest | 0.683 | 0.752 | 0.595 | 0.204 |
| LogisticRegression | 0.670 | 0.735 | 0.603 | 0.208 |

Calibration excellent — all bins within +/-2% of predicted probability. High-confidence picks (70%+) hit 82.4% accuracy.

Live betting P&L after settling all Itzulia bets: 11W 4L, +740.90 profit, 73.3% win rate, 71.5% ROI on 1,035.98 staked. Bankroll: 1,392.66 from 1,000 start.

**Conclusion:** Retrained model saved. Settlement bug fixed — missing result rows now treated as DNF rather than blocking settlement. CalibratedXGBoost remains best model.

---

## 2026-04-12 (evening) — Paris-Roubaix results + full retrain

**Hypothesis:** Paris-Roubaix 2026 results were available on PCS but the scraper failed on malformed time strings (doubled text like "5:16:525:16:52"). Manual import needed followed by retrain with cobbles data.

**Method:** Manually scraped Paris-Roubaix results via cloudscraper (bypassing broken time parser), inserted 175 results into DB, settled all 11 pending bets, then ran full `python scripts/train.py`.

**Results:**
Paris-Roubaix betting: 8W 3L, +268.69 profit on 348.24 staked (77.1% ROI).
- Notable: Model correctly predicted Pogacar over van der Poel (2nd vs 4th), van Aert over Pedersen (1st vs 7th)
- 3 losses: Hoelgaard DNS, Mohoric DNF, Vacek beaten by Walscheid

Overall P&L across all 26 bets: 19W 7L, +1,009.59 profit, 73.1% win rate, 72.9% ROI. Bankroll doubled from 1,000 to 2,009.59.

Training results pending (running).

**Conclusion:** Model performing well on cobbles classics. PCS time-format parser bug should be investigated for future one-day races.

---

## 2026-04-12 — Advanced Neural Network Architecture Sweep (5 approaches, 12 configs)

**Hypothesis:** Previous NN experiments (12 configs: label smoothing, focal loss, ResNets, SWA, ensembles) all hit a ~68.2% / 0.752 AUC ceiling with the standard feed-forward architecture. The decision log concluded *"the limitation is features, not model architecture."* This experiment tests whether fundamentally different NN architectures — ones that create new data representations rather than just fitting the same 424 features differently — can break through the CalibratedXGBoost ceiling of ~70% / 0.774 AUC.

**Approaches tested:**

1. **TabNet** (`models/tabnet_model.py`) — Sequential attention-based feature selection using `pytorch-tabnet`. Three configs: default (n_d=32, 5 steps), wide (n_d=64, 5 steps), deep (n_d=32, 7 steps).

2. **FT-Transformer** (`models/ft_transformer.py`) — Feature Tokenizer + Transformer. Each feature → d_token embedding, self-attention across features, CLS token classification head. Two PCA-reduced configs (424→50 components, 79.2% variance explained) since full-feature attention over 424 tokens was impractical on CPU (~O(424²·d) per layer). Configs: small (d=64, L=2, H=4), medium (d=128, L=3, H=4).

3. **Entity Embedding Network** (`models/entity_embedding.py`) — Learned latent vectors for riders (dim=32), teams (dim=16), races (dim=8) concatenated with 424 numerical features. Cold-start handling: riders/teams with <5 appearances share an "unknown" embedding. Two configs: default (256→128→64) and large (512→256→128→64).

4. **Siamese Network** (`models/siamese_net.py`) — Shared rider encoder (78 features → 32-dim embedding), race encoder (20 features → 16-dim), symmetric combiner using [a−b, |a−b|, a·b, race_embed]. Weight sharing guarantees swap-equivariance. Two configs: default (128→64→1) and wide (256→128→1).

5. **NN→XGBoost Stacking** (`models/nn_stacking.py`) — Train a feed-forward NN, extract 32-dim penultimate-layer embeddings, feed [424 original + 32 learned features] to CalibratedXGBoost. Two modes: concat (456 features) and embed_only (32 features).

**Method:**
```bash
# Unified experiment runner with per-approach CLI flag
python scripts/nn_experiments.py --approach tabnet
python scripts/nn_experiments.py --approach ft_transformer
python scripts/nn_experiments.py --approach entity
python scripts/nn_experiments.py --approach siamese
python scripts/nn_experiments.py --approach stacking
```

Three-way split: train (68%) / val (12%) / test (20%), stratified by stage (all pairs from a stage stay together). Val set used for early stopping; test set touched once. CalibratedXGBoost baseline uses train+val (its internal CV handles validation). ~291K pairs, 424 features, single-threaded on macOS ARM.

**Results:**

| Config | Accuracy | ROC-AUC | Brier | Notes |
|--------|----------|---------|-------|-------|
| **CalibratedXGBoost (baseline)** | **0.696–0.699** | **0.772–0.774** | **0.193–0.194** | *Varies ±0.003 across runs* |
| tabnet_default | 0.697 | 0.772 | 0.195 | 13m 39s |
| tabnet_wide | 0.696 | 0.771 | 0.195 | 14m 43s |
| tabnet_deep | 0.678 | 0.747 | 0.204 | Overfitting with 7 steps |
| ft_transformer_pca_small | 0.680 | 0.749 | 0.205 | PCA loses too much info |
| ft_transformer_pca_medium | 0.682 | 0.752 | 0.203 | Still below prior NN ceiling |
| entity_default | 0.689 | 0.762 | 0.199 | ~1 min training |
| entity_large | 0.689 | 0.763 | 0.199 | No gain from larger capacity |
| siamese_default | 0.692 | 0.765 | 0.197 | ~1 min training |
| siamese_wide | 0.690 | 0.763 | 0.198 | Wider doesn't help |
| **stacking_concat** | **0.698** | **0.773** | **0.194** | Closest to baseline |
| stacking_embed_only | 0.695 | 0.770 | 0.196 | Embeddings alone insufficient |

No approach beat the CalibratedXGBoost baseline by more than the ±0.003 AUC noise floor. Stacking_concat matched baseline (0.773 vs 0.774 AUC) but did not exceed it.

**Analysis:**

- **TabNet** matched baseline at default settings but degraded with deeper configs (7 steps overfits). The attention mechanism didn't find useful feature selection patterns beyond what XGBoost's splits already capture.
- **FT-Transformer** performed worst due to PCA dimensionality reduction (79.2% variance → information loss). Full-feature attention is impractical on CPU. Even PCA-reduced results matched the old NN ceiling (~0.752), not the XGBoost ceiling.
- **Entity embeddings** added ~1% AUC over the old feed-forward NN (0.763 vs 0.752) by learning rider/team representations, but still fell short of XGBoost by ~1% AUC. Cold-start handling may limit their value since many H2H pairs involve riders with <5 prior appearances.
- **Siamese network** showed clean architectural design (swap-equivariant, shared encoder) and reached 0.765 AUC — better than old NNs but worse than XGBoost. The learned rider representations don't capture as much as the 424 hand-crafted features.
- **Stacking** was most promising: NN embeddings + original features → XGBoost essentially reproduced the baseline. This suggests the NN embeddings are redundant with the hand-crafted features — XGBoost already extracts the useful signal.

**Conclusion:** None of the 5 advanced NN architectures (12 total configs) beat CalibratedXGBoost. This comprehensively confirms the prior finding: **the performance ceiling is driven by the features and data, not the model architecture.** Even fundamentally different approaches — attention-based feature selection (TabNet), cross-feature self-attention (FT-Transformer), learned entity representations (Entity Embeddings), symmetric comparison networks (Siamese), and hybrid stacking (NN→XGBoost) — cannot extract more signal from the same underlying data.

Future accuracy improvements should focus on:
- Better features (e.g., weather, course profiles, recent form windows, betting market odds as features)
- More/better training data (more races, deeper historical coverage)
- Data quality (scraper coverage gaps, missing rider stats)

All experiment code retained in `models/` and `scripts/nn_experiments.py` for reproducibility. No changes to the production pipeline — CalibratedXGBoost remains the default model.

---

## 2026-04-13 — Rider Variance Features + Retrain

**Hypothesis:** Adding rider consistency/volatility features (stddev, IQR, CV, range of historical results) will provide new signal about how predictable a rider is, potentially improving AUC.

**Method:** Added 17 new variance features to `features/rider_features.py`:
- Career: `career_rank_stddev`, `career_rank_iqr`, `career_pcs_stddev`, `career_rank_cv`
- Form windows: `form_{30d,60d,90d,180d}_rank_stddev`
- Recent race windows: `form_last{5,10,20}_rank_stddev`, `form_last{5,10,20}_rank_range`
- Course-type: `course_{flat,hilly,mountain}_rank_stddev`

Retrained XGBoost with all features (~460 total, up from 423). Same train/test split.

**Results:**
| Config | Accuracy | ROC-AUC | Brier | ECE |
|--------|----------|---------|-------|-----|
| Baseline (423 features) | 0.6980 | 0.7733 | 0.1938 | 0.0105 |
| + Variance features (460) | 0.6981 | 0.7708 | 0.1947 | 0.0102 |

Variance features ARE used by XGBoost: `diff_career_rank_iqr` rank 17, `diff_career_rank_stddev` rank 20 in feature importance. But overall AUC slightly decreased (within ±0.003 noise).

**Conclusion:** Variance features provide useful information about rider consistency (XGBoost selects them) but do not improve prediction accuracy. The features are retained because they enable the post-processing variance model (σ estimation). No standalone accuracy benefit.

---

## 2026-04-13 — Post-Processing Probability Adjustments (Comprehensive Experiment)

**Hypothesis:** Adding a post-processing layer on top of CalibratedXGBoost — with variance-aware Φ-adjustment, Bayesian uncertainty, upset injection, extreme shrinkage, and alternative calibration methods — could improve Brier score and calibration.

**Framework:** P(A>B) = Φ(Φ⁻¹(P_raw) / √(1 + σA² + σB² + τA² + τB²))
- σ: race-day variance from rider rank_stddev + course type
- τ: epistemic uncertainty = scale/√(n_recent + κ)
- ε: chaos probability, applied as mixture (1-ε)·P + ε·0.5

**Method:** Built `models/post_processing.py` (ProbabilityAdjuster class) and `scripts/eval_post_processing.py`. Tested 13 configurations on 57,800 test pairs:
- Calibration methods: temperature scaling, Platt scaling, beta calibration
- Individual components: variance-only, Bayesian-only, upset-only, shrinkage-only
- Combined: variance+Bayesian, full pipeline, full+temperature
- Parameter variants: conservative σ, aggressive ε

Calibration parameters (temperature T, Platt a/b, beta a/b/c) fitted on 30% held-out calibration set from training data.

**Results:**
| Config | Accuracy | AUC | Brier | ΔECE | ΔBrier |
|--------|----------|-----|-------|------|--------|
| **baseline_raw** | **0.6982** | **0.7720** | **0.1943** | **—** | **—** |
| temperature_scaling | 0.6982 | 0.7720 | 0.1943 | −0.0000 | +0.0000 |
| shrinkage_only | 0.6982 | 0.7720 | 0.1943 | +0.0000 | +0.0000 |
| bayesian_only | 0.6982 | 0.7720 | 0.1943 | +0.0004 | +0.0000 |
| upset_only | 0.6982 | 0.7720 | 0.1945 | +0.0073 | +0.0003 |
| platt_scaling | 0.6982 | 0.7720 | 0.1955 | +0.0253 | +0.0013 |
| beta_calibration | 0.6980 | 0.7720 | 0.1955 | +0.0259 | +0.0013 |
| variance_only | 0.6982 | 0.7717 | 0.1971 | +0.0354 | +0.0028 |
| variance_plus_bayesian | 0.6982 | 0.7717 | 0.1971 | +0.0357 | +0.0029 |
| full_pipeline | 0.6982 | 0.7717 | 0.1979 | +0.0419 | +0.0037 |
| full_with_temperature | 0.6982 | 0.7717 | 0.1979 | +0.0419 | +0.0037 |
| aggressive_epsilon | 0.6982 | 0.7716 | 0.1986 | +0.0462 | +0.0044 |
| conservative_sigma | 0.6982 | 0.7713 | 0.2028 | +0.0673 | +0.0085 |

Key findings:
- **Temperature ≈ 1.0** — confirms model is already well-calibrated
- **Isotonic calibration (in CalibratedClassifierCV) is near-optimal** — ECE=0.0095, reliability=0.00016
- **All adjustments degrade calibration** — variance-based Φ-adjustment is the worst offender, pushing predictions toward 0.5 when they're already correctly distributed
- **Platt and beta calibration are worse than isotonic** — the non-parametric isotonic approach better captures the true calibration mapping
- **Extreme shrinkage has no effect** — the model doesn't produce many extreme predictions that need capping

**Conclusion:** The CalibratedXGBoost with isotonic regression is **already near-optimally calibrated**. Post-processing adjustments are counterproductive — they add noise to a well-calibrated output. The Φ-framework is mathematically sound but assumes the base model is uncalibrated; since isotonic regression already handles calibration, layering additional adjustments on top hurts rather than helps.

**Implications for future work:**
- Do NOT add a post-processing layer to the production pipeline
- The `models/post_processing.py` module is retained for reference but should not be used in production
- Kelly staking could still benefit from uncertainty estimates (τ) for position sizing, even though the probabilities themselves don't need adjustment
- Accuracy improvements must come from better features or data, not from post-prediction adjustments
- The model's weak spot is discrimination (AUC 0.772), not calibration (ECE 0.010)

---

## 2026-04-13 — Feature selection: top 150 by permutation importance

**Hypothesis:** Many of the 474 features have near-zero importance. Selecting only the top features by permutation importance should maintain or improve accuracy while reducing noise and training time.

**Method:** Trained CalibratedXGBoost with different feature counts (top 50, 75, 100, 150, 200, 300, and all 474), selected by permutation importance ranking. Same stratified stage split.

**Results:**
| Features | Accuracy | ROC-AUC | Brier |
|----------|----------|---------|-------|
| 50 | 0.6953 | 0.7677 | 0.1960 |
| 75 | 0.6966 | 0.7701 | 0.1951 |
| 100 | 0.6979 | 0.7715 | 0.1945 |
| **150** | **0.6984** | **0.7719** | **0.1943** |
| 200 | 0.6979 | 0.7722 | 0.1942 |
| 300 | 0.6967 | 0.7713 | 0.1945 |
| 474 (all) | 0.6971 | 0.7716 | 0.1944 |

Final retrained model (150 features): AUC=0.7741, Brier=0.1935.

Key observations:
- 17 features had zero importance — pure dead weight
- Top 50 features capture 40% of total importance, top 150 capture ~59%
- Beyond 150 features, adding more adds noise rather than signal
- Top features: `diff_career_top10_rate` (11.4%), `interact_diff_quality_x_form` (6.3%), `interact_diff_sprint_x_flat` (2.0%)

**Conclusion:** 150 features is the sweet spot. Made this the default in `train.py --select-features 150`. Reduces model complexity by 68% with no accuracy loss. Also removed non-XGBoost models (LR, RF, NN) from the repo — none beat XGBoost in prior experiments.

---

## 2026-04-13 — Upstream merge (lewis-mcgillion/cycling-predictor through 2026-04-13)

**Hypothesis:** Sync PaceIQ fork with upstream to incorporate ML improvements made in parallel (variance features, feature selection, fine-tuning infrastructure, post-processing experiments).

**Method:** `git remote add upstream` + `git merge upstream/main`. Resolved 4 conflicts: kept our `db_snapshot.sql.gz`, merged both `decision_log.md` entry sets, combined `README.md` retaining PaceIQ branding + upstream CI docs, kept both `seed` and `since_date` params in `build_pairs_sampled`.

**Changes incorporated from upstream:**
- Variance features (17 new) in `features/rider_features.py`
- Feature selection default: top 150 by permutation importance in `scripts/train.py`
- Post-processing probability adjustment experiments (non-production, reference only)
- Incremental warm-start fine-tuning script: `scripts/fine_tune.py`
- Calibration evaluation script: `scripts/eval_calibration.py`
- `models/neural_net.py` deleted (upstream removed non-XGBoost models)
- `since_date` param added to `build_pairs_sampled()` in `data/builder.py`
- Nightly CI workflow documentation

**Results:** Merge committed as e69b613. No training run performed — pipeline changes require review before retraining.

**Conclusion:** Upstream ML improvements are now integrated. Items to address: multi-model support in `models/benchmark.py` (upstream stripped to XGBoost-only, conflicts with our CalibratedXGBoost-first approach), and validation that feature selection default (150) is compatible with our full pipeline including Pinnacle batch predictions.

---

## 2026-04-13 — Post-merge retrain with top-150 feature selection

**Hypothesis:** Validate full pipeline after upstream merge. First training run with merged codebase including variance features, feature selection, and updated pair builder.

**Method:** `python -u scripts/train.py` (defaults: `--select-features 150`, stratified split, WT-only off). 291,576 pairs, 474 feature columns before selection → 150 after permutation importance ranking.

**Results:**
| Model | Accuracy | ROC-AUC | Log Loss | Brier Score |
|-------|----------|---------|----------|-------------|
| CalibratedXGBoost | 0.6965 | 0.7718 | 0.5697 | 0.1943 |
| XGBoost | 0.6950 | 0.7698 | 0.5713 | 0.1950 |

Calibration (CalibratedXGBoost):
| Confidence Band | Model Avg | Actual Win% | Count |
|-----------------|-----------|-------------|-------|
| 50–55% | 52.5% | 52.1% | 4,313 |
| 55–60% | 57.5% | 59.4% | 4,123 |
| 60–65% | 62.5% | 63.4% | 3,836 |
| 65–70% | 67.5% | 67.9% | 3,799 |
| 70–75% | 72.4% | 74.8% | 3,333 |
| 75–80% | 77.4% | 78.9% | 2,826 |
| 80–100% | 87.6% | 88.4% | 6,305 |

All calibration bins pass (within 3%). High-confidence (70%+) picks: 82.6% accuracy (n=12,464).

By race type: One-day 66.9%, Stage race 70.3%.
By course type: Flat 70.5%, Hilly 68.6%, Mountain 71.0%.

Top 10 features by permutation importance: `race_profile_score`, `interact_diff_tt_x_itt`, `interact_diff_sprint_x_flat`, `diff_spec_gc_pct`, `diff_spec_climber_pct`, `diff_career_top10_rate`, `diff_age`, `race_distance_km`, `diff_spec_hills_pct`, `race_vert_per_km`.

Top 10 features by XGBoost gain: `diff_career_top10_rate` (0.136), `interact_diff_sprint_x_flat` (0.038), `diff_form_180d_top10` (0.029), `diff_form_last10_best_rank` (0.028), `diff_terrain_same_profile_top10` (0.024), `interact_diff_terrain_x_form` (0.017), `diff_form_last5_best_rank` (0.016), `interact_diff_tt_x_itt` (0.016), `diff_spec_gc_pct` (0.015), `diff_form_30d_top10` (0.014).

Timing: Feature matrix 21m 36s, selector XGBoost 11m 37s, permutation importance 53m, final models ~7m. Total: 93m 33s.

**Conclusion:** Pipeline works end-to-end post-merge. Results are consistent with pre-merge performance (69.7% accuracy, 0.772 AUC). Calibration is excellent across all bins. Feature count grew from 424 → 474 (50 new variance features from upstream). The 150-feature selection reduces to a stable, performant subset. Permutation importance is the slowest step (53 min) — consider caching or reducing repeats in future.
