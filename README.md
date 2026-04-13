# PaceIQ

Cycling H2H betting intelligence system. Predicts which rider finishes ahead in head-to-head matchups, detects edges against Pinnacle implied odds, and surfaces actionable bet signals via pre-race reports.

Forked from [lewis-mcgillion/cycling-predictor](https://github.com/lewis-mcgillion/cycling-predictor). Live data layer: [lewis-mcgillion/procyclingstats-mcp-server](https://github.com/lewis-mcgillion/procyclingstats-mcp-server).

The pipeline scrapes historical results from ProCyclingStats, engineers ~475 candidate features per matchup, selects the top 150 by permutation importance, and trains a Calibrated XGBoost model. Predictions are served through a Flask web app with Kelly Criterion staking advice and P&L tracking.

**Current model performance** (stratified stage split, test set ~57K pairs):

| Model | Accuracy | ROC-AUC | Brier Score |
|-------|----------|---------|-------------|
| CalibratedXGBoost | 70.0% | 0.774 | 0.194 |
| XGBoost | 69.8% | 0.771 | 0.194 |

## How It Works

**Scrape → Build H2H Pairs → Engineer Features → Select Top 150 → Train Model → Serve Predictions**

1. **Scraper** pulls race results from ProCyclingStats into a local SQLite database (`data/cache.db`)
2. **Builder** generates head-to-head training pairs from race results (top-50 finishers, up to 200 pairs per stage, random A/B swap to prevent ordering bias)
3. **Feature pipeline** computes ~475 candidate features per matchup across 6 categories:
   - **Rider features** (×2): form, consistency, terrain affinity, career stats, variance metrics (138 per rider)
   - **Race features**: profile, distance, elevation, race tier (20 features)
   - **Diff features**: A minus B differences for key rider stats
   - **Interaction features**: cross-terms (e.g., sprint ability × flat race)
   - **H2H features**: historical head-to-head record between the pair
4. **Feature selection** trains a throwaway XGBoost on all features, ranks by permutation importance, and keeps the top 150 (eliminates noise — accuracy improves slightly vs using all 475)
5. **Training** trains XGBoost and Calibrated XGBoost (isotonic calibration via `CalibratedClassifierCV` with 5-fold CV)
6. **Web app** serves predictions with Kelly Criterion staking advice, a results browser, and P&L tracking

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# macOS only (required for XGBoost):
brew install libomp
```

## Commands

```bash
# Scrape race data into data/cache.db
python scripts/scrape_all.py

# Incremental update — new races since last scrape only
python scripts/update_races.py

# Pre-compute feature cache (~18 min first run, ~1s incremental)
python scripts/precompute_features.py

# Train models (builds pairs, engineers features, selects top 150, trains XGBoost)
python scripts/train.py
python scripts/train.py --select-features 200  # override feature count

# Incremental fine-tune on new data (warm-start, faster than full retrain)
python scripts/fine_tune.py

# Feature ablation experiments
python scripts/experiment.py              # default 3-fold
python scripts/experiment.py --splits 5

# Run feature selection sweep
python scripts/feature_selection.py

# Evaluate model calibration
python scripts/eval_calibration.py --plot --json

# Export database tables to CSV
python scripts/export_data.py

# Dump/load database snapshots (used by CI)
python scripts/dump_db.py
python scripts/load_db.py

# Launch the web app (http://localhost:5001)
python webapp/app.py
```

## Tests

```bash
pytest tests/ -v                  # full suite
pytest tests/test_export.py -v    # single module
```

## Project Structure

```
data/              Scraper, pair builder, P&L tracking, cache.db
features/          Feature engineering pipeline (~475 candidates → 150 selected)
models/            XGBoost training, benchmarking, prediction, saved artifacts
  trained/         Model artifacts (pkl, scaler, feature_names.json)
scripts/           CLI entry points (scrape, train, fine-tune, experiment, export)
webapp/            Flask web application (port 5001)
tests/             Pytest test suite
.github/workflows/ Nightly data fetch (scrapes new results, commits snapshot)
.planning/         GSD planning documents and codebase map
```

## CI / Automation

A **nightly GitHub Actions workflow** runs at midnight UTC to:
1. Restore the database from the committed snapshot (`data/db_snapshot.sql.gz`)
2. Scrape the latest race results via `scripts/update_races.py`
3. Dump and commit the updated snapshot

This keeps the training data fresh without manual intervention. The workflow can also be triggered manually via `workflow_dispatch`.

## Betting Logic

- Edge threshold: flag at >5%, act at >8%
- Bet sizing: half Kelly, max 10% bankroll per bet
- Bet placement is always manual on Pinnacle — no automated execution
- CLV (closing line value) is the primary model validity signal

## Notes

- All scripts degrade gracefully when data sources are unavailable
- Model artifacts (`models/trained/`) are not committed — run `train.py` after a fresh clone
- The MCP server (`procyclingstats-mcp-server`) provides live pre-race data in supported environments
- See `decision_log.md` for full experiment history and rationale behind all model decisions
