# Architecture

> ML pipeline system that scrapes cycling data, engineers features, trains classifiers, and serves H2H predictions via a Flask web app.

## Overview

The system is a classic offline-training / online-serving ML pipeline. Data is scraped from ProCyclingStats into a local SQLite database, transformed into ~295-feature vectors per head-to-head matchup, used to train 5 competing classifiers, and then served through a Flask web app that provides win probability predictions and Kelly Criterion staking advice. The architecture is a single Python monorepo with clearly separated pipeline stages as packages.

## Pipeline Stages

The system operates in five sequential stages, each with distinct responsibility:

**Stage 1 — Data Collection** (`data/scraper.py`):
- Scrapes race results, rider profiles, and stage characteristics from ProCyclingStats using the `procyclingstats` library
- Persists everything to SQLite (`data/cache.db`) — schemas: `races`, `stages`, `results`, `riders`, `scrape_log`
- Rate-limited at 0.5s per request with exponential backoff on 4xx/5xx and Cloudflare blocks
- Entry point: `scripts/scrape_all.py` (full scrape 2018–2026) or `scripts/update_races.py` (incremental)

**Stage 2 — Pair Building** (`data/builder.py`):
- Reads SQLite results and generates binary-labelled head-to-head pairs: (rider_a, rider_b, stage_url, label)
- `build_pairs_sampled()` is the production path — randomly samples up to 200 pairs per stage to keep the dataset tractable
- Labels are randomly flipped (50% swap) to prevent the model from learning a positional bias

**Stage 3 — Feature Engineering** (`features/`):
- `features/pipeline.py` — orchestrates the full feature vector build for every pair; calls race and rider sub-modules, then assembles the result
- `features/race_features.py` — extracts 20 numeric features from a stage row: distance, elevation, climb counts/categories, race tier, stage type (RR/ITT/TTT), etc.
- `features/rider_features.py` — computes ~100+ per-rider features: physical attributes (BMI, age), form windows (30d/60d/90d/180d), career stats, specialty scores, terrain affinity; strictly uses only data prior to `race_date` to prevent leakage
- Feature representation: for each pair, rider features are stored three ways — `diff_*` (A minus B), `a_*` (absolute A), `b_*` (absolute B); plus `race_*` shared features and interaction terms
- `features/feature_store.py` — parquet-backed cache (`data/rider_features_cache.parquet`, `data/race_features_cache.parquet`) that converts the slow 18-minute compute step into a ~10-second lookup; supports incremental updates
- Entry point: `scripts/precompute_features.py`

**Stage 4 — Model Training & Benchmarking** (`models/benchmark.py`):
- Trains five classifiers on the feature matrix: Logistic Regression, Random Forest, XGBoost, CalibratedXGBoost, Neural Network (optional via `--nn`)
- Two split strategies configurable at train time: `stratified` (default — 80/20 by stage, year-stratified) and `time` (train pre-2025, test on 2025–2026)
- Evaluates each model on accuracy, ROC-AUC, log loss, and Brier score; prints calibration breakdown by confidence bin and course type
- Selects the best model by ROC-AUC and serialises all models + the scaler + feature names to `models/trained/` as pickle files
- Optional feature selection: permutation importance via `--select-features N` flag
- Entry point: `scripts/train.py`

**Stage 5 — Serving** (`webapp/app.py` + `models/predict.py`):
- Flask web app running on port 5001
- `models/predict.py` exposes a `Predictor` class that loads the best saved model and applies Kelly Criterion staking maths
- Supports two prediction modes: database-lookup (via `stage_url`) and manual race parameters (custom race profile without a DB entry)
- Kelly Criterion implemented with configurable max fraction cap; returns full/half/quarter Kelly fractions

## Key Components

| Component | File | Responsibility |
|-----------|------|----------------|
| SQLite cache / scraper | `data/scraper.py` | Data ingestion and persistence |
| Pair builder | `data/builder.py` | Training sample generation |
| Feature pipeline | `features/pipeline.py` | Assembles full 295-feature vectors |
| Race features | `features/race_features.py` | Stage/race characteristics (20 features) |
| Rider features | `features/rider_features.py` | Per-rider historical stats (~100+ features) |
| Feature store | `features/feature_store.py` | Parquet-backed feature cache |
| Benchmark / trainer | `models/benchmark.py` | Multi-model training and evaluation |
| Neural network | `models/neural_net.py` | PyTorch `CyclingNet` (256→128→64→32→1) |
| Predictor | `models/predict.py` | Inference + Kelly staking |
| P&L tracker | `data/pnl.py` | Bet management, bankroll, auto-settlement |
| Web app | `webapp/app.py` | Flask API + Jinja2 templates |

## Data Flow

```
ProCyclingStats (external)
        │
        ▼
  data/scraper.py   ──►  data/cache.db (SQLite)
                               │
                               ▼
                    data/builder.py  ──►  pairs DataFrame (in memory)
                               │
                               ▼
                   features/pipeline.py
                   ├── features/race_features.py
                   ├── features/rider_features.py  ◄── data/*_cache.parquet (optional)
                   └── H2H history (SQL query)
                               │
                               ▼
                     feature_df (pandas DataFrame, ~295 columns)
                               │
                               ▼
                    models/benchmark.py
                    ├── StandardScaler  ──►  models/trained/scaler.pkl
                    ├── LogisticRegression  ──►  models/trained/*.pkl
                    ├── RandomForest        ──►  models/trained/*.pkl
                    ├── XGBoost             ──►  models/trained/*.pkl
                    ├── CalibratedXGBoost   ──►  models/trained/*.pkl
                    └── NeuralNet (opt.)    ──►  models/trained/*.pkl
                               │
                               ▼
                    models/predict.py (Predictor)
                               │
                               ▼
                      webapp/app.py (Flask)
                      ├── GET  /api/riders       (autocomplete)
                      ├── GET  /api/races        (stage search)
                      ├── POST /api/predict      (H2H prediction + Kelly)
                      ├── GET  /api/pnl/*        (bet tracking)
                      └── POST /api/bets/*       (place/settle bets)
```

## Entry Points

**Training pipeline** (run sequentially):
- `scripts/scrape_all.py` — full historical scrape (2018–2026)
- `scripts/update_races.py` — incremental update since last scrape
- `scripts/precompute_features.py` — build parquet feature cache
- `scripts/train.py` — build pairs → compute features → train → save models

**Inference / web app**:
- `webapp/app.py` — Flask dev server on port 5001

**Experiments and analysis**:
- `scripts/experiment.py` — feature group ablation experiments
- `scripts/feature_selection.py` — permutation importance feature ranking
- `scripts/simulate_pnl.py` — P&L backsimulation with Kelly variants
- `scripts/settle.py` — settle pending bets from live results
- `scripts/export_data.py` — export SQLite tables to CSV
- `scripts/dump_db.py` / `scripts/load_db.py` — snapshot SQLite for CI

**Automated pipeline**:
- `.github/workflows/nightly-pipeline.yml` — runs nightly at 00:00 UTC; restores DB snapshot, runs `update_races.py`, dumps new snapshot, commits `data/db_snapshot.sql.gz`

## Design Patterns

**No-leakage feature computation**: `compute_rider_features()` in `features/rider_features.py` accepts a `race_date` parameter and restricts all SQL queries to `WHERE date < race_date`, ensuring no future information bleeds into training.

**Stage-level train/test split**: `stratified_stage_split()` in `models/benchmark.py` assigns whole stages (not individual pairs) to train or test, preventing within-race data leakage where pairs from the same stage could appear in both sets.

**Deterministic feature caching**: `features/feature_store.py` caches `(rider_url, stage_url)` → feature vector in parquet. Incremental updates only compute new pairs. Cache is invalidated only when the database changes.

**Lazy model loading**: `webapp/app.py` initialises the `Predictor` singleton on first request via `get_predictor()`, avoiding startup failure when no model is yet trained.

**Kelly Criterion staking**: `models/predict.py` implements full/half/quarter Kelly with a configurable `max_fraction` cap (default 25%) and an `edge` guard — bets are only recommended when model probability exceeds implied bookmaker probability.

**Multi-model benchmarking pattern**: All classifiers are trained, evaluated, and serialised in `models/benchmark.py::run_benchmark()`. The best model by ROC-AUC is also saved as `best_model.pkl` for the predictor to load.

## Module / Package Organisation

Each top-level directory is a Python package (has `__init__.py`):

- `data/` — data acquisition and storage layer; depends on nothing in the project
- `features/` — feature engineering; imports from `data/` only
- `models/` — ML layer; imports from `data/` and `features/`
- `webapp/` — presentation layer; imports from `data/`, `features/`, and `models/`
- `scripts/` — CLI orchestration; imports from all packages

Dependency direction is strictly one-way: `scripts → webapp → models → features → data`.

## Key Observations

- The system is a **linear ML pipeline monorepo**, not a service-oriented architecture
- **SQLite is the single source of truth** — `data/cache.db` is the database; `data/db_snapshot.sql.gz` is its versioned backup
- **Trained models are gitignored** (`models/trained/`) and must be regenerated locally with `scripts/train.py`
- The **feature cache** (`data/*_cache.parquet`) is also gitignored and rebuilt with `scripts/precompute_features.py`
- **Strict no-leakage discipline**: all historical queries are time-bounded by `race_date`
- The **nightly CI workflow** updates the DB snapshot daily but does not retrain models
- Two prediction modes exist: DB-backed (`stage_url`) and manual (`race_params`) — the manual mode enables prediction for races not yet in the database

---

*Architecture analysis: 2026-04-10*
