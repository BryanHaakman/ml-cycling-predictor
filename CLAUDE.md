# CLAUDE.md — PaceIQ

**PaceIQ** is a cycling H2H betting intelligence system. It predicts which rider finishes ahead in head-to-head matchups, detects edges against Pinnacle implied odds, and surfaces actionable bet signals via pre-race reports.

Forked from `lewis-mcgillion/cycling-predictor`. Live data layer: `lewis-mcgillion/procyclingstats-mcp-server`.

Owner: Bryan Haakman — bryan@haakman.ca

---

## Keeping This File Current

**Update this file whenever the project changes in a meaningful way.** It should always reflect how the project actually works, not how it worked when the file was written.

Update it when you:
- Add a new script, module, or component
- Change the architecture or data flow
- Update the best model configuration after a training run
- Add or remove a key convention
- Resolve a known issue (remove it from the list)
- Discover a new gotcha worth warning future Claude instances about
- Change commands, ports, flags, or file paths

Keep entries concise — this file is loaded on every conversation. Prefer updating existing sections over appending new ones.

---

## ⚠️ MANDATORY: Decision Log

**Every ML experiment, training run, or pipeline change MUST be documented in `decision_log.md`.**

This file is the single source of truth for all research decisions and will be used for a future academic write-up. Log an entry whenever you:

- Train or retrain a model (any architecture)
- Change hyperparameters, feature groups, or training configuration
- Run a feature ablation or experiment
- Add, remove, or modify features in the pipeline
- Change the train/test split strategy or evaluation methodology
- Benchmark or compare model performance
- Investigate a hypothesis about model accuracy or training speed
- Make any architectural decision about the ML pipeline

Each entry must include: **Date**, **Hypothesis**, **Method** (exact commands/code changes), **Results** (metrics with numbers), **Conclusion** (what was learned, kept or reverted).

**Do not skip this step.** Negative results and failed experiments are equally valuable.

---

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# macOS only: brew install libomp  (required for XGBoost)

python scripts/scrape_all.py          # scrape race data → data/cache.db
python scripts/train.py               # build pairs → engineer features → benchmark models
python webapp/app.py                  # Flask app at http://localhost:5001
```

Other scripts:
```bash
python scripts/update_races.py        # incremental scrape since last run
python scripts/experiment.py          # feature ablation (--model xgboost|nn, --splits N)
python scripts/export_data.py         # export SQLite tables to CSV
python scripts/precompute_features.py # cache features to parquet (~18 min first run, ~1s incremental)

pytest tests/ -v                      # full test suite (run before marking any task complete)
pytest tests/test_export.py -v        # single module
```

---

## Architecture

Pipeline: **Scrape → Build H2H Pairs → Engineer Features → Train Models → Serve Predictions**

| Component | File | Role |
|-----------|------|------|
| Scraper | `data/scraper.py` | Scrapes ProCyclingStats via `cloudscraper`, stores in `data/cache.db` (SQLite WAL). Rate-limited 0.5s/req, 60s timeout with retry/backoff. |
| Pair builder | `data/builder.py` | Generates H2H training pairs. Top-50 finishers, up to 200 pairs/stage, random A/B swap prevents ordering bias. WT-only by default (1.UWT, 2.UWT). |
| Feature pipeline | `features/` | ~295 features per matchup: `race_features.py` (20), `rider_features.py` (78/rider), `pipeline.py` (assembles diff/absolute/H2H/interaction/startlist-relative). `feature_store.py` provides optional parquet caching. |
| Benchmarking | `models/benchmark.py` | Trains 5 models (LogReg, RF, XGBoost, NN, CalibratedXGBoost) with stratified stage split. Saves artifacts to `models/trained/`. |
| Prediction | `models/predict.py` | Prediction + confidence-scaled Kelly staking. Default model: **CalibratedXGBoost**. |
| Neural net | `models/neural_net.py` | PyTorch: `256→128→64→32`, BatchNorm, ReLU, Dropout(0.3). |
| Web app | `webapp/app.py` | Flask, port 5001. Lazy-loads predictor. Prediction UI, results browser, P&L tracker, Elo leaderboard. |
| P&L tracking | `data/pnl.py` | Bankroll tracking. P&L tables live in `data/cache.db` (not a separate bets.db). |

---

## Current Best Model Configuration

From `decision_log.md` — do not change without a logged experiment:

- **Training data:** World Tour only (1.UWT, 2.UWT), all years 2018–2025
- **Pair generation:** max_rank=50, 200 pairs/stage (~255K WT pairs)
- **Features:** 424 columns (20 race + rider absolute/diff/interaction + startlist-relative + H2H + course-type + one-day form)
- **Split:** Stratified stage split (default `--split stratified`; time-based available via `--split time`)
- **Best model:** CalibratedXGBoost — ~69.6% accuracy, ~0.769 ROC-AUC
- **Training time:** ~84 min first run (27 min feature matrix + 12 min RF + 9 min XGBoost); incremental runs faster as cache is warm
- **Feature cache:** `data/rider_features_cache.parquet` + `data/race_features_cache.parquet`
- **NN skipped by default** (use `--nn` flag to include; adds ~1 min, no accuracy gain)
- **Pair sampling seed:** default `seed=42` in `build_pairs_sampled` — training is now reproducible

Top features by importance (2026-04-10 run): `diff_career_top10_rate` (0.148), `diff_field_strength_ratio` (0.030), `diff_form_180d_top10` (0.025), `interact_diff_sprint_x_flat` (0.018), `diff_terrain_same_profile_top10` (0.015).

---

## Data Rules

- `data/cache.db` is the SQLite database — **do not migrate to Postgres**
- `data/bets.csv` is append-only — **never delete or modify existing rows**
- All scripts must degrade gracefully when a data source is unavailable — log failure and continue, do not crash the pipeline
- **Ask before changing any schema** (cache.db tables or bets.csv columns)
- `scrape_log` table tracks resume state — do not truncate it

---

## MCP Server

`procyclingstats-mcp-server` is configured in this environment. Use it freely for **live pre-race data**.

| Tool | Purpose |
|------|---------|
| `discover_races` | Find races by year and tier |
| `get_race_overview` | Race metadata, dates, stage list |
| `get_stage_results` | Full results with metadata |
| `get_rider_profile` | Bio, physical stats, specialty scores, palmares |
| `get_race_startlist` | Startlist grouped by team |
| `search_pcs` | Free-text search for riders, races, teams |

Use MCP for live/upcoming data. Use `cache.db` for historical training data. The MCP server enforces a 0.5s delay between PCS requests — respect this.

---

## Betting Logic

- **Edge threshold:** flag at >5%, act at >8%
- **Bet sizing:** half Kelly, max 10% bankroll per bet (`max_fraction=0.20` in `kelly_criterion()`). Quarter Kelly shown as conservative alternative. No confidence scaling — raw Kelly for maximum long-run ROI.
- **Bet placement is always manual on Pinnacle** — no automated execution
- **CLV (closing line value)** is the primary model validity signal — track on every bet, not just wins
- Every bet logged to `data/bets.csv`: date, race, stage, matchup, rider_backed, odds_at_bet, stake, result, closing_odds, clv, pnl, notes

---

## Key Conventions

### Feature leakage prevention
All rider features use strictly pre-race data. SQL queries filter on `s.date < race_date`. Never use post-race data in feature computation.

### Thread safety
PyTorch + scikit-learn can deadlock on macOS. Always maintain single-threaded execution:
```python
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
torch.set_num_threads(1)
```
Random Forest uses `n_jobs=1`.

### Import pattern
Scripts inject the repo root into `sys.path`, then use absolute imports:
```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.scraper import get_db
from features.pipeline import build_feature_matrix
```

### Database access
Always use `get_db()` from `data.scraper` — it sets WAL mode, foreign keys, and `Row` factory.
Primary keys: `races.url`, `stages.url`, `riders.url`. Results: `UNIQUE(stage_url, rider_url)`.

### Scraper resilience
Stub rider records are inserted on parse failures to avoid infinite retries. One-day races require `/result` URL suffix.

### Neural net dtype
Labels must be explicitly `float32`: `y_train.values.astype(np.float32)`.

### Model artifacts
Saved to `models/trained/`: `.pkl` for sklearn, `.pt` for PyTorch, `feature_names.json` for column order, `scaler.pkl` for fitted StandardScaler. This directory is not committed — fresh clone requires a training run.

### Flask port
The app runs on **port 5001** (not 5000 as README states).

---

## Code Style

- Python 3.11+
- **2-space indentation**
- Type hints on all function signatures
- Docstrings on all public functions
- Run `pytest tests/ -v` before marking any task complete
- Do not add dependencies to `requirements.txt` without asking first

---

## Known Issues

- **Admin restricted to localhost** (`webapp/app.py`): `/admin` routes are protected by `_require_localhost` decorator (returns 403 for non-localhost). `debug=False` is set. Still no password auth — do not expose port 5001 externally.
- **Interaction features duplicated in 3 places** (`features/pipeline.py`): `build_feature_vector`, `build_feature_vector_manual`, and `build_feature_matrix` each compute interactions independently. Future interaction changes must be applied in all three places. Refactor: extract into a shared `_compute_interactions()` helper.
