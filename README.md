# 🚴 Cycling Head-to-Head Predictor

ML-powered prediction of head-to-head cycling race outcomes. Given two riders and a race profile, the system predicts which rider will finish ahead — mirroring cycling betting markets (e.g., "Pogačar vs Vingegaard in Stage 14").

The pipeline scrapes historical results from ProCyclingStats, engineers ~295 features per matchup, benchmarks 5 ML models, and serves predictions through a Flask web app with Kelly Criterion staking advice and P&L tracking.

## How It Works

**Scrape → Build H2H Pairs → Engineer Features → Train Models → Serve Predictions**

1. **Scraper** pulls race results from ProCyclingStats into a local SQLite database (`data/cache.db`)
2. **Builder** generates head-to-head training pairs from race results
3. **Feature pipeline** computes ~295 features per matchup (rider form, race profile, terrain affinity, H2H history, etc.)
4. **Benchmark** trains and evaluates 5 models — Logistic Regression, Random Forest, XGBoost, Neural Network, and Calibrated XGBoost
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

# Train models (builds pairs, engineers features, benchmarks 5 models)
python scripts/train.py

# Run feature ablation experiments
python scripts/experiment.py            # default XGBoost, 5-fold
python scripts/experiment.py --model nn --splits 3

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
features/       Feature engineering pipeline (~295 features)
models/         Model training, benchmarking, prediction, saved artifacts
scripts/        CLI entry points (scrape, train, experiment, export, AML sweep)
webapp/         Flask web application
tests/          Pytest test suite
deploy/         Azure setup scripts (Container Apps, ML workspace)
```

## Deployment

The app deploys to **Azure Container Apps** with automated retraining and a weekly hyperparameter sweep via **Azure ML**.

### Pipeline Flow

```
Nightly (midnight UTC)        Weekly (Sunday 03:00 UTC)
  └─ nightly-pipeline.yml       └─ weekly-sweep.yml
       ├─ Scrape latest data         ├─ Submit HyperDrive sweep to AML
       ├─ Dump DB snapshot           ├─ Bayesian search over XGBoost params
       └─ Commit to repo             ├─ Download best model
            └─ Triggers deploy.yml   └─ Commit if AUC > 0.75
                 ├─ Retrain model
                 ├─ Build Docker image
                 ├─ Deploy to staging
                 └─ Promote to production
```

### Quick Start (Azure)

```bash
# 1. Install Azure CLI + ML extension
az extension add -n ml

# 2. Create Container Apps infrastructure
./deploy/azure-setup.sh

# 3. Create Azure ML workspace + compute for sweeps
./deploy/azure-ml-setup.sh

# 4. Set GitHub secrets (printed by the setup scripts)
gh secret set AZURE_CLIENT_ID       --body "..."
gh secret set AZURE_TENANT_ID       --body "..."
gh secret set AZURE_SUBSCRIPTION_ID --body "..."
gh secret set AZURE_STORAGE_CONNECTION_STRING --body "..."
gh secret set APPINSIGHTS_CONNECTION_STRING   --body "..."

# 5. Deploy
gh workflow run deploy.yml

# 6. Run a hyperparameter sweep (~$3-5 on Azure)
python scripts/aml_sweep.py --max-trials 36
```

### Estimated Monthly Cost (~$50 of $150 budget)

| Resource | Cost |
|----------|------|
| Container Apps — production (2 CPU / 4GB, scale-to-zero) | ~$30 |
| Container Apps — staging (1 CPU / 2GB, scale-to-zero) | ~$10 |
| Application Insights + Log Analytics | ~$5 |
| Blob Storage (DB snapshots) | ~$1 |
| Azure ML compute (weekly sweep, 4x DS3_v2) | ~$5 |
| **Total** | **~$51** |
