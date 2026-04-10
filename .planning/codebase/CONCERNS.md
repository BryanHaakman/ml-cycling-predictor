# Concerns & Technical Debt
> Stable ML pipeline with good documentation, but carrying significant structural risks around model artifact management, web app security, single-point-of-failure dependencies, and test coverage gaps.

## Overview

The codebase is a well-documented solo ML project that has been thoughtfully iterated on, with a decision log capturing every experiment and its rationale. The core ML pipeline is solid and the data scraping layer handles edge cases carefully. However, the project carries three meaningful structural risks: trained model artifacts are not version-controlled, the Flask web app has no authentication, and the entire prediction capability depends on a third-party scraping target (ProCyclingStats) that can block or change its structure at any time. Test coverage is almost entirely absent outside a single export utility.

---

## Critical Concerns

### No authentication on the Flask web app
- Risk: The admin panel at `/admin` exposes the ability to trigger arbitrary Python subprocesses (`update_races.py`, `precompute_features.py`, `train.py`) from a browser. There is zero authentication or access control on any route.
- Files: `webapp/app.py` lines 683–833
- Impact: Anyone who can reach port 5001 can run a full model retrain (12+ minutes, high CPU), delete bets, or corrupt the bankroll. The `admin_run_script` endpoint launches subprocesses with the full environment.
- Current mitigation: Only runs on localhost (`app.run(debug=True, port=5001)`) by default — but `debug=True` means the Werkzeug debugger is exposed, which allows arbitrary code execution via the debug console.
- Fix approach: Disable `debug=True` for any non-development usage; add at minimum HTTP basic auth or a session secret on admin routes.

### Trained model artifacts not committed or reproducibly generated
- Risk: `models/trained/` does not exist in the repository. The web app's `Predictor` class will silently fail (`FileNotFoundError` → `return None`) if models haven't been trained locally.
- Files: `models/predict.py` lines 19, 156–174; `webapp/app.py` lines 44–51
- Impact: A fresh clone is completely non-functional for predictions until a ~12 minute training run completes. There is no CI step to train models, and no model versioning.
- Fix approach: Either commit a minimal trained artifact, use Git LFS for model files, or add a `Makefile`/setup script that makes the cold-start requirement explicit. At minimum, document this in the README.

### Full dependency on ProCyclingStats scraping
- Risk: The entire data pipeline scrapes `procyclingstats.com` via `cloudscraper` to bypass Cloudflare. PCS could update their HTML structure, change their Cloudflare rules, or block the scraper's IP/UA, silently breaking data ingestion.
- Files: `data/scraper.py` lines 53–83, 263–268
- Impact: If PCS blocks the scraper, the nightly GitHub Actions pipeline fails silently (it commits no new data), and the model becomes stale without any alert being raised. The workflow has no failure notification step.
- Fix approach: Add a CI failure step that emails/Slacks on scrape failure; monitor `scrape_log` for anomalies; consider caching a complete recent export.

### `SIGALRM` timeout mechanism is non-portable
- Risk: `data/scraper.py` uses `signal.SIGALRM` and `signal.alarm()` for request timeouts (lines 57–59). `SIGALRM` does not exist on Windows.
- Files: `data/scraper.py` lines 42–83
- Impact: Any developer or CI runner on Windows will get `AttributeError: module 'signal' has no attribute 'SIGALRM'` the first time a scrape is triggered. The GitHub Actions workflow runs on `ubuntu-latest` so CI is unaffected, but Windows local development is broken.
- Fix approach: Replace with `requests` timeout parameter or `concurrent.futures.ThreadPoolExecutor` with a timeout, which is cross-platform.

---

## Technical Debt

### Massive interaction feature duplication between `build_feature_vector` and `build_feature_matrix`
- Issue: The interaction feature computation block (climber×profile, tt×itt, sprint×flat, gc×profile, quality×form, terrain×form, climber×mountain) is copy-pasted identically into both `build_feature_vector()` and `build_feature_matrix()` — approximately 60 lines each.
- Files: `features/pipeline.py` lines 159–222 and lines 583–645
- Impact: Any change to interaction feature logic must be applied in two places. This has already created a divergence: `build_feature_vector` (used for live prediction) computes `build_feature_vector_manual` which has a third copy in lines 319–347 that is missing the GC×profile, quality×form, terrain×form, and climber×mountain interactions — meaning manual race predictions use **fewer features** than training used.
- Fix approach: Extract interaction feature computation into a standalone `_compute_interactions(race_feats, rider_a_feats, rider_b_feats)` helper function. This is the highest-priority code quality fix.

### `build_feature_vector_manual` produces inconsistent feature vectors
- Issue: `build_feature_vector_manual` in `features/pipeline.py` (lines 225–347) omits 4 interaction feature groups that are present in both `build_feature_vector` and `build_feature_matrix`: `interact_*_gc_x_profile`, `interact_*_quality_x_form`, `interact_*_terrain_x_form`, and `interact_*_climber_x_mountain`.
- Files: `features/pipeline.py` lines 319–347 vs lines 159–222
- Impact: When a user predicts on a manual/upcoming race (the primary use case), the feature vector will have zeros where the model expects interaction features. These include `interact_diff_quality_x_form`, which the decision log notes was the #2 most important feature (0.056 importance). This is a silent accuracy bug for the production use case.
- Fix approach: Extend `build_feature_vector_manual` to include all interaction groups, or refactor into the shared helper noted above.

### Startlist-relative features are absent from `build_feature_vector` (live prediction)
- Issue: `build_feature_vector` in `features/pipeline.py` (lines 71–222) computes startlist features by fetching all riders in the stage from the DB (lines 126–155). This only works when the stage has results stored. For an upcoming race, the startlist is empty, so `field_size=0` and all percentiles default. The manual path in `build_feature_vector_manual` doesn't attempt startlist features at all.
- Files: `features/pipeline.py` lines 125–155, 225–347
- Impact: `diff_field_rank_quality` is ranked #3 in feature importance in the current production model (0.0162). Live predictions will always receive 0 for this feature, creating a systematic bias.
- Fix approach: Accept an optional `startlist` parameter (list of rider URLs) to `build_feature_vector_manual` so the web UI can pass a startlist for upcoming races.

### Random pair sampling introduces non-deterministic training
- Issue: `build_pairs_sampled` in `data/builder.py` uses `random.random()` and `random.randint()` without a fixed seed (lines 147–155, 161).
- Files: `data/builder.py` lines 139–175
- Impact: Two training runs on the same data will produce different datasets and therefore different model weights. The decision log acknowledges "run-to-run variance from random pair sampling is ±0.003 AUC". This makes reproducing a specific trained model impossible without the exact random state.
- Fix approach: Add a `seed` parameter (defaulting to 42) and call `random.seed(seed)` at the start of `build_pairs_sampled`.

### SQLite used for everything including concurrent multi-user scenarios
- Issue: All data (scraped results, P&L, bets) lives in a single SQLite file at `data/cache.db`. The `get_db()` function creates a new connection per call with WAL mode, but the web app opens connections per-request without connection pooling.
- Files: `data/scraper.py` lines 90–96; `data/pnl.py` lines 72–75; `webapp/app.py` throughout
- Impact: Write contention during a scrape (which holds many write transactions) concurrent with a web request will cause `SQLITE_BUSY` errors. The `auto_settle_from_results` function opens and closes the connection repeatedly inside a loop (lines 314–317), which is particularly fragile.
- Fix approach: Use a single connection per request with context management; consolidate bet settlement to use a single transaction.

### `db_snapshot.sql.gz` committed to git as a binary blob
- Issue: The nightly pipeline commits `data/db_snapshot.sql.gz` to the main branch. The current workflow compresses the SQLite binary directly (not SQL text), meaning git cannot diff it.
- Files: `.github/workflows/nightly-pipeline.yml` lines 43–55; `scripts/dump_db.py` lines 44–46
- Impact: The repository will grow unboundedly as each nightly commit adds a new binary. Git history becomes non-inspectable for data changes. After a year of daily snapshots, the repo could be 365× the size of one snapshot.
- Fix approach: Use `sqlite3 .dump` to produce text SQL, or store snapshots in a separate branch / external storage (S3, GitHub Releases) rather than in main history. Alternatively, use `git lfs`.

### `PredictionResult.feature_importances` is always `None`
- Issue: The `PredictionResult` dataclass in `models/predict.py` (line 145) has a `feature_importances` field declared but `predict()` and `predict_manual()` always set it to `None` (lines 237, 299).
- Files: `models/predict.py` lines 135–146, 237, 299
- Impact: Feature importance is advertised as part of the prediction API but is never populated. Any caller checking `result.feature_importances` will always get `None`. No UI currently uses this, but it represents dead/misleading code.

### `caffeinate` hardcoded into the admin training command
- Issue: The training command in the admin panel SCRIPTS dict includes `caffeinate -s` as the first argument (line 697 of `webapp/app.py`). `caffeinate` is a macOS-only utility that prevents system sleep.
- Files: `webapp/app.py` line 697
- Impact: Running the admin "Train Models" button on Linux or Windows will fail with `FileNotFoundError: [Errno 2] No such file or directory: 'caffeinate'`. The GitHub Actions CI runner is Linux-based, so this is also broken there.
- Fix approach: Remove `caffeinate` from the command list or make it conditional on `sys.platform == "darwin"`.

---

## Missing Pieces

### No tests for core ML pipeline
- The only test file is `tests/test_export.py`, which tests the CSV export utility. There are zero tests for:
  - Feature engineering (`features/pipeline.py`, `features/rider_features.py`, `features/race_features.py`)
  - Model prediction (`models/predict.py`)
  - Data builder (`data/builder.py`)
  - Scraper logic (`data/scraper.py`)
  - P&L calculations (`data/pnl.py`)
  - Kelly criterion (`models/predict.py::kelly_criterion`)
- Files: `tests/` — only `tests/test_export.py` exists
- Risk: Any regression in feature computation, Kelly staking math, or bet settlement would go undetected.

### No `.gitignore` for generated artifacts
- The `models/trained/` directory and parquet cache files (`data/rider_features_cache.parquet`, `data/race_features_cache.parquet`) appear to not be committed, but there is no explicit `.gitignore` entry excluding them. If a developer runs training, they may accidentally commit large binary model files.
- Fix approach: Verify and add explicit `.gitignore` entries for `models/trained/`, `data/*.parquet`, `data/cache.db`, and `data/*.db`.

### No model versioning or experiment tracking
- Trained models in `models/trained/` are overwritten on every training run with no version tracking. The `decision_log.md` records results manually, but there is no programmatic record linking a specific model file to the training config and dataset that produced it.
- Fix approach: Save model metadata (training timestamp, config, feature count, AUC) to `models/trained/metadata.json` during training.

### No rate-limit handling in nightly CI pipeline
- The GitHub Actions nightly workflow calls `python scripts/update_races.py --all-tiers --no-settle`, which hits all four race calendar tiers. If PCS rate-limits the IP (GitHub Actions uses shared IPs), the scrape silently drops races. There is no alerting or retry strategy at the CI level.
- Files: `.github/workflows/nightly-pipeline.yml`

### No input validation on the `/api/predict` endpoint
- The prediction API accepts `rider_a_url` and `rider_b_url` as strings passed directly to SQLite queries and the feature pipeline. While parameterised queries prevent SQL injection, there is no validation that these are valid PCS URL formats, and no rate limiting on the prediction endpoint.
- Files: `webapp/app.py` lines 128–212

### `features/elo.py` referenced but does not exist
- The decision log (line 66) states "Elo ratings kept as standalone feature for the web app leaderboard page (`/elo`)". No `/elo` route exists in `webapp/app.py`, and no `features/elo.py` file exists in the codebase. This feature was planned but never completed or was removed without updating documentation.
- Files: `decision_log.md` line 66; `webapp/app.py` (missing `/elo` route)

---

## Risks

### Scraped rider stubs masquerade as real data
- When rider profile scraping fails, `data/scraper.py` inserts a stub record with the rider's name derived from their URL slug (lines 497–505). This stub has `NULL` for all physical and specialty fields. Feature computation will silently use all-zero defaults for these riders, making them appear equally matched on all specialty metrics.
- Files: `data/scraper.py` lines 494–506; `features/rider_features.py` lines 130–146
- Impact: If a key rider has a stub record, their predictions will be systematically degraded with no warning to the user.

### Model serialised with `pickle` — unsafe to load from untrusted sources
- All models except the Neural Network are saved and loaded via `pickle` (e.g. `models/predict.py` lines 173–175). The `db_snapshot.sql.gz` is committed to git; if model files were ever committed, loading them from a compromised repository would allow arbitrary code execution.
- Files: `models/predict.py` lines 173–175; `models/benchmark.py` lines 351–358
- Current exposure: Low (models not committed), but worth noting as a policy to maintain.

### H2H feature computation performs an O(N²) join per pair at training time
- `compute_h2h_history` in `features/pipeline.py` (lines 22–50) runs a self-join on the `results` table for every training pair. At 255K pairs, this is 255K individual SQL queries even with caching, since H2H features are "always computed live" (pipeline.py line 570). The decision log notes this was "the new bottleneck at scale" with 255K queries.
- Files: `features/pipeline.py` lines 22–50, 570
- Impact: Training time remains limited. Any scale-up in training data will make this worse. A pre-computed H2H matrix would resolve this.

### Feature cache can become stale after incremental scrapes
- The parquet feature caches (`rider_features_cache.parquet`, `race_features_cache.parquet`) are computed incrementally — only new rider-stage pairs are added. If historical results are corrected in the DB (e.g. a stage result is re-scraped via `scrape_since_last`), the cache is not invalidated for those entries. The stale cached features would silently persist.
- Files: `features/feature_store.py` lines 98–116; `data/scraper.py` lines 622–631
- Impact: The `scrape_since_last` function deletes and re-scrapes stages with updated results, but `precompute_features.py` only adds new pairs, so corrected results from re-scrapes are never reflected in the cache until a full rebuild.

### Stratified split may overestimate real-world accuracy
- The current production split mode is `stratified` (80/20 random by stage across all years). The decision log reports a +1.27% accuracy improvement vs time-based split when switching to this mode. However, real-world deployment is fundamentally a temporal prediction problem: always predicting future races from past data. A model tested on historic stages from years it trained on may be over-optimistic.
- Files: `models/benchmark.py` lines 56–95; `scripts/train.py` line 49
- Impact: The reported 69.8% accuracy / 0.773 AUC may overstate live performance. The time-based split (preserved via `--split time`) likely gives a more honest estimate for out-of-sample, forward-looking performance.

---

## Positive Observations

- **Excellent decision log**: `decision_log.md` documents every experiment, hypothesis, result, and reasoning. This is rare and valuable — it prevents re-running failed experiments and makes the ML history auditable.
- **Leakage-safe feature engineering**: Every rider feature query correctly uses `s.date < ?` to exclude future data. The feature cache incremental logic respects this constraint.
- **Graceful degradation in scraping**: The scraper retries on server errors, handles `cloudscraper` absence gracefully, inserts stubs for failed rider profiles, and uses `scrape_log` for resume support after interruptions.
- **Well-structured interaction features**: The ML feature engineering thoughtfully captures terrain×specialist interactions (climber×mountain profile, sprinter×flat race, TT specialist×ITT) that align with domain knowledge.
- **WAL mode on SQLite**: `conn.execute("PRAGMA journal_mode=WAL")` is set on every connection, which significantly improves concurrent read performance.
- **Kelly Criterion implementation is correct**: The staking math in `models/predict.py` uses the standard formula with appropriate caps (`max_fraction=0.25`), half/quarter Kelly variants, and confidence-scaled sizing per the decision log.
- **Calibration is genuinely good**: The decision log's calibration table shows near-perfect probability calibration across all confidence bins (all within ±3%), which is essential for Kelly staking to work as expected.
- **Feature cache dramatically accelerates iteration**: The two-tier parquet cache (rider features + race features) reduces training from 18+ minutes to ~4 minutes for feature assembly, enabling rapid experimentation.

---

## Key Observations

Prioritised by impact on reliability and correctness:

1. **Fix `build_feature_vector_manual` missing interaction features** — this is a silent accuracy bug affecting every production prediction made via the web UI's manual race entry. `interact_diff_quality_x_form` (the #2 most important feature) is always zero for manual predictions. (`features/pipeline.py`)

2. **Extract shared interaction feature logic** — the 60-line interaction computation block is duplicated three times. This is the root cause of the bug above and will cause future divergences. (`features/pipeline.py`)

3. **Remove `debug=True` and add admin authentication** — the Flask app runs with the Werkzeug debugger and zero auth. At minimum, disable debug mode and add a secret-based gate to `/admin` routes. (`webapp/app.py`)

4. **Fix `caffeinate` in the admin training command** — the "Train Models" button is broken on any non-macOS system. (`webapp/app.py` line 697)

5. **Replace `SIGALRM` with cross-platform timeout** — Windows developer environments will crash on first scrape attempt. (`data/scraper.py`)

6. **Add a seed to pair sampling** — training is non-reproducible without a fixed seed, making it impossible to reproduce a specific model. (`data/builder.py`)

7. **Add `.gitignore` entries** — prevent accidental commit of `models/trained/`, `data/*.parquet`, `data/cache.db`. Verify current state of `.gitignore`.

8. **Add tests for core pipeline** — Kelly criterion, bet settlement math, and feature extraction have no test coverage. A bug in `kelly_criterion()` would directly cause financial miscalculation. (`tests/`)

9. **Invalidate feature cache on re-scrape** — stale cached features silently persist when historical results are corrected. (`features/feature_store.py`, `data/scraper.py`)

10. **Add CI failure alerting** — the nightly pipeline has no notification on failure; a broken scraper would be invisible until the next training run. (`.github/workflows/nightly-pipeline.yml`)

---

*Concerns audit: 2026-04-10*
