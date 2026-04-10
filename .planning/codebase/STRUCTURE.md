# Codebase Structure

> Single-repo Python ML project organised as pipeline stages, each a package; scripts are thin CLI wrappers over those packages.

## Overview

The project root contains five Python packages (`data`, `features`, `models`, `scripts`, `tests`, `webapp`) plus documentation and configuration files. Every package has an `__init__.py`. Generated artefacts (trained models, feature caches, database, CSV exports) are gitignored and must be produced locally by running the relevant scripts.

## Directory Layout

```
ml-cycling-predictor/
├── .github/
│   └── workflows/
│       └── nightly-pipeline.yml    # Nightly DB update CI job
├── .planning/
│   └── codebase/                   # GSD analysis documents
├── data/                           # Data layer: scraper, builder, P&L, DB snapshot
│   ├── __init__.py
│   ├── scraper.py                  # ProCyclingStats scraper + SQLite schema
│   ├── builder.py                  # H2H pair generation from DB
│   ├── pnl.py                      # Bet tracking and bankroll management
│   └── db_snapshot.sql.gz          # Committed gzip SQL dump (nightly updated)
│   # (gitignored: cache.db, *_cache.parquet, exports/)
├── features/                       # Feature engineering layer
│   ├── __init__.py
│   ├── pipeline.py                 # Main build_feature_matrix() orchestrator
│   ├── race_features.py            # Stage/race → 20 numeric features
│   ├── rider_features.py           # Rider history → 100+ features per rider
│   └── feature_store.py            # Parquet-backed feature cache management
├── models/                         # ML layer: training, benchmarking, prediction
│   ├── __init__.py
│   ├── benchmark.py                # Multi-model train/eval/save pipeline
│   ├── neural_net.py               # PyTorch CyclingNet definition + train/predict
│   └── predict.py                  # Predictor class + Kelly Criterion
│   # (gitignored: trained/)
├── scripts/                        # CLI entry points — thin wrappers over packages
│   ├── __init__.py
│   ├── scrape_all.py               # Full historical scrape (2018–2026)
│   ├── update_races.py             # Incremental scrape since last run
│   ├── train.py                    # Full training pipeline (pairs→features→models)
│   ├── precompute_features.py      # Build parquet feature cache
│   ├── experiment.py               # Feature group ablation experiments
│   ├── feature_selection.py        # Permutation importance feature ranking
│   ├── simulate_pnl.py             # P&L backsimulation with Kelly variants
│   ├── settle.py                   # Settle pending bets from race results
│   ├── export_data.py              # Export SQLite tables to CSV
│   ├── dump_db.py                  # Dump SQLite to db_snapshot.sql.gz
│   └── load_db.py                  # Restore SQLite from db_snapshot.sql.gz
├── tests/
│   ├── __init__.py
│   └── test_export.py              # Pytest tests for export_data.py
├── webapp/
│   ├── __init__.py
│   ├── app.py                      # Flask application (routes, API, SSE)
│   └── templates/
│       ├── index.html              # Main prediction UI
│       ├── admin.html              # Admin panel
│       ├── pnl.html                # P&L dashboard
│       └── results.html            # Race results browser
├── .gitignore
├── .github/
├── decision_log.md                 # Design decisions log
├── README.md
└── requirements.txt
```

## Directory Purposes

**`data/`**
- Purpose: Data acquisition, storage schema, and P&L tracking
- Key files:
  - `data/scraper.py` — defines SQLite schema, `get_db()` factory, `scrape_years()`, `scrape_stage()`, `DB_PATH` constant (`data/cache.db`)
  - `data/builder.py` — `build_pairs_sampled()` returns a pandas DataFrame with columns `stage_url, rider_a_url, rider_b_url, label`
  - `data/pnl.py` — `bets` and `bankroll_history` SQLite tables (stored in same `cache.db`); `place_bet()`, `settle_bet()`, `auto_settle_from_results()`
  - `data/db_snapshot.sql.gz` — gzip-compressed SQL dump committed to git; restored by CI before each nightly update run
- Generated (gitignored): `data/cache.db`, `data/rider_features_cache.parquet`, `data/race_features_cache.parquet`, `data/exports/`

**`features/`**
- Purpose: All feature engineering logic; no ML, no web concerns
- Key files:
  - `features/pipeline.py` — `build_feature_matrix(pairs_df)` iterates all pairs and calls `build_feature_vector()` per row; exports `H2H_FEATURE_NAMES`, `STARTLIST_FEATURE_NAMES`
  - `features/rider_features.py` — `compute_rider_features(conn, rider_url, race_date, stage_url)` returns a dict; exports `RIDER_FEATURE_NAMES` list
  - `features/race_features.py` — `extract_race_features(stage_row)` returns a dict; exports `RACE_FEATURE_NAMES` list (20 names)
  - `features/feature_store.py` — `precompute_all()`, `load_rider_features_cache()`, `load_race_features_cache()` — cache paths are `data/rider_features_cache.parquet` and `data/race_features_cache.parquet`

**`models/`**
- Purpose: Model definitions, training, evaluation, and inference
- Key files:
  - `models/benchmark.py` — `run_benchmark(feature_df, date_series, ...)` trains 5 models and saves them to `models/trained/`; also exports `stratified_stage_split()` and `time_based_split()` for use by scripts
  - `models/neural_net.py` — `CyclingNet` (PyTorch `nn.Module`), `train_neural_net()`, `predict_neural_net()`; architecture is `[Linear→BatchNorm→ReLU→Dropout] × 4 → Sigmoid`
  - `models/predict.py` — `Predictor` class loads `models/trained/best_model.pkl` + scaler on init; `KellyResult` dataclass; odds conversion utilities
- Generated (gitignored): `models/trained/` — contains `*.pkl` files for each trained model, scaler, and feature names

**`scripts/`**
- Purpose: CLI orchestration; all scripts add the project root to `sys.path` and delegate to packages
- Scripts are executable (`chmod +x`); all accept `--help`
- Key scripts:
  - `scripts/train.py` — the main "rebuild everything" entry point; takes `--nn`, `--select-features N`, `--wt-only`, `--split` flags
  - `scripts/scrape_all.py` — wraps `data/scraper.scrape_years()`; `--all-tiers`, `--major-only`, `--years`, `--force` flags
  - `scripts/experiment.py` — feature group ablation; `--model`, `--splits`, `--feature-set` flags

**`webapp/`**
- Purpose: Flask web application serving predictions, P&L, and results browser
- `webapp/app.py` — 29,953 bytes; defines all routes, SSE streaming endpoint for log tailing, and the `Predictor` singleton
- `webapp/templates/` — Jinja2 HTML templates; `index.html` (61 KB) contains the bulk of the frontend JavaScript

**`tests/`**
- Purpose: Pytest suite
- Currently contains only `tests/test_export.py` — tests `scripts/export_data.py` with a temporary in-memory SQLite fixture

## File Naming Conventions

**Python modules**: `snake_case.py` — e.g. `scraper.py`, `rider_features.py`, `neural_net.py`

**HTML templates**: `lowercase.html` — e.g. `index.html`, `admin.html`, `pnl.html`, `results.html`

**Data files**:
- SQLite database: `data/cache.db` (gitignored)
- DB snapshot: `data/db_snapshot.sql.gz` (committed, updated nightly)
- Feature caches: `data/*_cache.parquet` (gitignored)
- CSV exports: `data/exports/<timestamp>/` and `data/exports/latest/` (gitignored)
- Analysis CSVs: `data/feature_rankings.csv`, `data/feature_selection_results.csv` (committed)

**Model artefacts**: `models/trained/*.pkl` (gitignored) — produced by `models/benchmark.py`

## Key Files and Their Roles

| File | Role |
|------|------|
| `data/scraper.py` | Defines `DB_PATH`, `get_db()`, SQLite schema, and all scraping logic |
| `data/builder.py` | Produces the labelled H2H pairs DataFrame fed into feature engineering |
| `features/pipeline.py` | Central feature orchestrator; `build_feature_matrix()` is called by `train.py` |
| `features/rider_features.py` | Houses `RIDER_FEATURE_NAMES` — the canonical list of per-rider feature names |
| `models/benchmark.py` | The only place that trains and saves models; defines the split functions |
| `models/predict.py` | Runtime inference; `Predictor` and `KellyResult` are consumed by `webapp/app.py` |
| `webapp/app.py` | All HTTP routes; the `_predictor` singleton is lazily initialised |
| `scripts/train.py` | Canonical "build the system" script; documents the 3-step pipeline |
| `requirements.txt` | Single flat dependency list; no version pinning beyond `>=` lower bounds |
| `.github/workflows/nightly-pipeline.yml` | Automated nightly scrape and snapshot commit |

## Configuration Files

| File | Purpose |
|------|---------|
| `requirements.txt` | Python package dependencies |
| `.gitignore` | Ignores `data/cache.db`, `models/trained/`, `data/*_cache.parquet`, `data/exports/`, `.venv/` |
| `.github/workflows/nightly-pipeline.yml` | GitHub Actions nightly CI |

There is no `setup.py`, `pyproject.toml`, or `setup.cfg` — the project is not installable as a package. Scripts use `sys.path.insert(0, project_root)` for imports.

There are no environment variable config files (no `.env`). Configuration is handled via constants inside modules (`DB_PATH` in `data/scraper.py`, `MODELS_DIR` in `models/benchmark.py` and `models/predict.py`, `STORE_DIR` in `features/feature_store.py`).

## Data Files and Formats

| File | Format | Committed | Generated by |
|------|--------|-----------|--------------|
| `data/cache.db` | SQLite | No | `data/scraper.py` |
| `data/db_snapshot.sql.gz` | gzip SQL dump | Yes | `scripts/dump_db.py` |
| `data/rider_features_cache.parquet` | Parquet | No | `scripts/precompute_features.py` |
| `data/race_features_cache.parquet` | Parquet | No | `scripts/precompute_features.py` |
| `data/feature_rankings.csv` | CSV | Yes | `scripts/feature_selection.py` |
| `data/feature_selection_results.csv` | CSV | Yes | `scripts/feature_selection.py` |
| `data/exports/<ts>/` | CSV per table | No | `scripts/export_data.py` |
| `models/trained/*.pkl` | Pickle | No | `scripts/train.py` |

## SQLite Schema (in `data/cache.db`)

Tables defined in `data/scraper.py`:
- `races` — race name, year, nationality, UCI tour tier, one-day flag
- `stages` — stage per race: date, distance, vertical_meters, profile_icon, climb data, stage type
- `results` — rider placements per stage: rider_url, rank, pcs_points
- `riders` — rider profile: name, nationality, birthdate, weight, height, specialties (JSON), PCS points
- `scrape_log` — which race URLs have been scraped (resume support)

Additional tables added by `data/pnl.py` (in the same `cache.db`):
- `bets` — placed bets with odds, stake, Kelly fractions, status (pending/won/lost/void)
- `bankroll_history` — timestamped bankroll snapshots
- `saved_races` — manually saved race profiles for reuse in the web UI

## Generated vs Source Files

**Source (committed to git):**
- All `.py` files in `data/`, `features/`, `models/`, `scripts/`, `tests/`, `webapp/`
- `webapp/templates/*.html`
- `data/db_snapshot.sql.gz`
- `data/feature_rankings.csv`, `data/feature_selection_results.csv`
- `requirements.txt`, `README.md`, `decision_log.md`, `.gitignore`
- `.github/workflows/nightly-pipeline.yml`

**Generated (gitignored, must be produced locally):**
- `data/cache.db` — restore with `python scripts/load_db.py`
- `data/*_cache.parquet` — rebuild with `python scripts/precompute_features.py`
- `models/trained/` — rebuild with `python scripts/train.py`
- `data/exports/` — generate with `python scripts/export_data.py`
- `.venv/` — create with `python -m venv .venv && pip install -r requirements.txt`

## Where to Add New Code

**New scraping target (new data source or table):**
- Add schema to `data/scraper.py` (`get_db()` → `CREATE TABLE IF NOT EXISTS`)
- Add scraping logic to `data/scraper.py` or a new `data/<source>.py` module

**New feature:**
- Add computation to `features/rider_features.py` (per-rider) or `features/race_features.py` (per-race)
- Add the name to the respective `*_FEATURE_NAMES` list at the bottom of that file
- The pipeline and feature store will automatically pick up the new column

**New model:**
- Add training and evaluation block inside `models/benchmark.py::run_benchmark()`
- Save with `pickle.dump()` to `MODELS_DIR`

**New web route:**
- Add `@app.route(...)` to `webapp/app.py`
- Add template to `webapp/templates/` if rendering HTML

**New CLI script:**
- Add to `scripts/`; include the `sys.path.insert(0, project_root)` preamble
- Add documentation to `README.md` under Commands

**New test:**
- Add `tests/test_<module>.py`; use `pytest.fixture` with `tmp_path` for DB-dependent tests

## Key Observations

- The project has **no package manager manifest** beyond `requirements.txt` — no `pyproject.toml`, no editable install
- **All cross-package imports use `sys.path.insert`** in scripts rather than relative imports, because the project is not installed as a package
- **`data/db_snapshot.sql.gz`** (~12 MB) is the only large binary committed to git; it is updated by automated CI daily
- **`webapp/templates/index.html`** is the largest single file (61 KB), containing substantial embedded JavaScript for the frontend
- **`models/trained/`** is always empty in the cloned repo — the first local task after cloning is to run `load_db.py` then `train.py`
- The **feature name lists** (`RIDER_FEATURE_NAMES`, `RACE_FEATURE_NAMES`, `H2H_FEATURE_NAMES`) in their respective modules are the canonical contracts between feature engineering and training/inference — adding a feature requires updating the list
- **No environment-specific config files** exist — all paths are computed relative to `__file__` using `os.path.dirname`

---

*Structure analysis: 2026-04-10*
