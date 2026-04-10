# PaceIQ

Cycling H2H betting intelligence system. Predicts which rider finishes ahead in head-to-head matchups, detects edges against Pinnacle implied odds, and surfaces actionable bet signals via pre-race reports.

Forked from [lewis-mcgillion/cycling-predictor](https://github.com/lewis-mcgillion/cycling-predictor). Live data layer: [lewis-mcgillion/procyclingstats-mcp-server](https://github.com/lewis-mcgillion/procyclingstats-mcp-server).

## How It Works

**Scrape → Build H2H Pairs → Engineer Features → Train Models → Serve Predictions**

1. **Scraper** pulls historical race results from ProCyclingStats into a local SQLite database (`data/cache.db`)
2. **Pair builder** generates head-to-head training pairs from race results (World Tour only, top-50 finishers)
3. **Feature pipeline** computes ~295 features per matchup — rider form, race profile, terrain affinity, one-day vs stage form, startlist-relative strength, H2H history, and interaction features
4. **Benchmark** trains and evaluates 5 models: Logistic Regression, Random Forest, XGBoost, Neural Network, Calibrated XGBoost
5. **Web app** serves predictions with confidence-scaled Kelly staking, a results browser, and P&L tracking

Current best model: **CalibratedXGBoost** — ~69.8% accuracy, ~0.773 ROC-AUC (stratified stage split)

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

# Train models (builds pairs, engineers features, benchmarks 5 models)
python scripts/train.py

# Feature ablation experiments
python scripts/experiment.py            # default XGBoost, 5-fold
python scripts/experiment.py --model nn --splits 3

# Export database tables to CSV
python scripts/export_data.py

# Launch the web app (http://localhost:5001)
python webapp/app.py
```

## Tests

```bash
pytest tests/ -v
```

## Project Structure

```
data/           SQLite cache (cache.db), pair builder, P&L tracking
features/       Feature engineering pipeline (~295 features per matchup)
models/         Training, benchmarking, prediction, saved model artifacts
scripts/        CLI entry points — scrape, train, experiment, export
webapp/         Flask web app — predictions, Kelly staking, P&L, Elo leaderboard
tests/          Pytest test suite
notebooks/      Analysis and exploration
.planning/      GSD planning documents and codebase map
```

## Betting Logic

- Edge threshold: flag at >5%, act at >8%
- Bet sizing: half Kelly, max 10% bankroll per bet
- Confidence scaling: stakes reduced proportionally for low-confidence predictions
- Bet placement is always manual on Pinnacle — no automated execution
- CLV (closing line value) is the primary model validity signal

## Notes

- All scripts degrade gracefully when data sources are unavailable
- Model artifacts (`models/trained/`) are not committed — run `train.py` after a fresh clone
- The MCP server (`procyclingstats-mcp-server`) provides live pre-race data in supported environments
- See `decision_log.md` for full experiment history and rationale behind all model decisions
