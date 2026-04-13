# 🚴 Cycling Head-to-Head Predictor

ML-powered prediction of head-to-head cycling race outcomes. Given two riders and a race profile, the system predicts which rider will finish ahead — mirroring cycling betting markets (e.g., "Pogačar vs Vingegaard in Stage 14").

The pipeline scrapes historical results from ProCyclingStats, engineers ~475 features per matchup, trains a Calibrated XGBoost model, and serves predictions through a Flask web app with Kelly Criterion staking advice and P&L tracking.

## How It Works

**Scrape → Build H2H Pairs → Engineer Features → Train Model → Serve Predictions**

1. **Scraper** pulls race results from ProCyclingStats into a local SQLite database (`data/cache.db`)
2. **Builder** generates head-to-head training pairs from race results
3. **Feature pipeline** computes ~475 features per matchup (rider form, variance/consistency, race profile, terrain affinity, H2H history, interactions, etc.)
4. **Training** trains XGBoost and Calibrated XGBoost (isotonic calibration for well-calibrated probabilities)
5. **Web app** serves predictions with Kelly Criterion staking advice, a results browser, and P&L tracking

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

# Incremental update — fetch new races since last scrape
python scripts/update_races.py

# Train models (builds pairs, engineers features, trains XGBoost)
python scripts/train.py

# Incremental fine-tune on new data (faster than full retrain)
python scripts/fine_tune.py

# Run feature ablation experiments
python scripts/experiment.py              # default 3-fold
python scripts/experiment.py --splits 5

# Evaluate model calibration
python scripts/eval_calibration.py --plot --json

# Export database tables to CSV
python scripts/export_data.py

# Precompute features to parquet cache
python scripts/precompute_features.py

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
data/           Scraper, pair builder, P&L tracking, cache.db
features/       Feature engineering pipeline (~475 features)
models/         XGBoost training, benchmarking, prediction, saved artifacts
scripts/        CLI entry points (scrape, train, fine-tune, experiment, export)
webapp/         Flask web application
tests/          Pytest test suite
```
