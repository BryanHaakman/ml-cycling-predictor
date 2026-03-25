# Copilot Instructions — Cycling Head-to-Head Predictor

## ⚠️ Decision Log — MANDATORY

**Every ML experiment, test, or change MUST be documented in `decision_log.md` at the project root.** This file is the single source of truth for all research decisions and will be used for a future academic write-up.

You must add an entry to `decision_log.md` whenever you:

- Train or retrain a model (any architecture)
- Change hyperparameters, feature groups, or training configuration
- Run a feature ablation or experiment (`scripts/experiment.py` or ad-hoc)
- Add, remove, or modify features in the pipeline
- Change the train/test split strategy or evaluation methodology
- Benchmark or compare model performance
- Investigate a hypothesis about model accuracy or training speed
- Make any architectural decision about the ML pipeline

Each entry must include:

- **Date** (YYYY-MM-DD)
- **What** was tested or changed
- **Why** — the hypothesis or motivation
- **Method** — what was run, with exact commands or code changes
- **Results** — metrics (accuracy, ROC-AUC, Brier score, log loss, training time) with numbers
- **Conclusion** — what was learned, whether the change was kept or reverted

Example format:

```markdown
## 2026-03-25 — Removed physical features from training

**Hypothesis:** Physical stats (weight, height, BMI) add noise based on ablation results showing `no_physical` AUC of 0.843 vs `all_features` AUC of 0.840.

**Method:** Ran `python scripts/experiment.py --splits 5` with and without physical feature group.

**Results:**
| Config | Accuracy | ROC-AUC | Brier Score |
|--------|----------|---------|-------------|
| All features | 0.762 | 0.840 | 0.158 |
| No physical | 0.765 | 0.843 | 0.155 |

**Conclusion:** Removing physical features marginally improves all metrics. Change kept — physical features excluded from default pipeline.
```

**Do not skip this step.** Even negative results or failed experiments must be logged — they are equally valuable for the write-up.

---

## Build & Run Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# macOS only: brew install libomp  (required for XGBoost)

# Full pipeline
python scripts/scrape_all.py      # scrape race data → data/cache.db
python scripts/train.py           # build pairs → engineer features → benchmark 5 models
python webapp/app.py              # Flask app on http://localhost:5001

# Other scripts
python scripts/update_races.py    # incremental scrape since last run
python scripts/experiment.py      # feature ablation (--model xgboost|nn, --splits N)
python scripts/export_data.py     # export SQLite tables to CSV
python scripts/precompute_features.py  # cache features to parquet
```

### Tests

```bash
pytest tests/ -v                  # full suite (11 tests)
pytest tests/test_export.py -v    # single module
pytest tests/test_export.py::TestExportTable::test_csv_created -v  # single test
```

Test framework is **pytest**. Tests use `tmp_path` fixtures and create temporary SQLite databases.

---

## Architecture

The pipeline flows: **Scrape → Build H2H Pairs → Engineer Features → Train Models → Serve Predictions**

- **`data/scraper.py`** — scrapes ProCyclingStats via `cloudscraper` (Cloudflare bypass), stores everything in `data/cache.db` (SQLite with WAL mode). Rate-limited at 0.5s/request with 60s timeout and retry/backoff.
- **`data/builder.py`** — generates head-to-head training pairs from race results. Top-50 finishers only, up to 200 pairs per stage, random A/B swap to prevent ordering bias.
- **`features/`** — 270-feature pipeline. `race_features.py` (19 features), `rider_features.py` (78 per rider), `pipeline.py` (assembles diff/absolute/H2H/interaction features). `feature_store.py` provides optional parquet caching.
- **`models/benchmark.py`** — trains 5 models (LogReg, RF, XGBoost, Neural Net, Calibrated XGBoost) with time-based split (test years: 2025–2026). Saves artifacts to `models/trained/`.
- **`models/predict.py`** — prediction + Kelly Criterion staking. Default model is **CalibratedXGBoost** (calibrated probabilities matter for Kelly).
- **`models/neural_net.py`** — PyTorch feed-forward: `256→128→64→32` with BatchNorm, ReLU, Dropout(0.3).
- **`webapp/app.py`** — Flask app. Lazy-loads the predictor. Serves prediction UI, results browser, and P&L tracker.
- **`data/pnl.py`** — P&L/bankroll tracking. Despite README mentioning `bets.db`, P&L tables live in `data/cache.db`.

All scripts in `scripts/` are CLI entry points using `argparse` and `sys.path.insert(0, repo_root)` for imports.

---

## Key Conventions

### Feature leakage prevention
All rider features use strictly pre-race data: SQL queries filter on `s.date < race_date`. Never use post-race data in feature computation.

### Thread safety
PyTorch + scikit-learn can deadlock on macOS. Training forces single-threaded execution:
```python
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
torch.set_num_threads(1)
```
Random Forest uses `n_jobs=1`. Always maintain this pattern.

### Import pattern
Scripts inject the repo root into `sys.path`, then use absolute imports:
```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.scraper import get_db
from features.pipeline import build_feature_matrix
```

### Database access
- Always use `get_db()` from `data.scraper` — it sets WAL mode, foreign keys, and `Row` factory.
- Primary keys: `races.url`, `stages.url`, `riders.url`. Results use `UNIQUE(stage_url, rider_url)`.

### Scraper resilience
- Stub rider records are inserted on parse failures to avoid infinite retries.
- One-day races require `/result` URL suffix.
- Resume is tracked via `scrape_log` table.

### Neural net dtype
Labels must be explicitly `float32`: `y_train.values.astype(np.float32)`.

### Model artifacts
Saved to `models/trained/`: `.pkl` for sklearn models, `.pt` for PyTorch, `feature_names.json` for column order, `scaler.pkl` for the fitted StandardScaler.

### Web app port
The Flask app runs on **port 5001** (not 5000 as README states).
