# 🚴 Cycling Head-to-Head Predictor

ML-powered prediction of head-to-head cycling race outcomes. Given two riders and a race profile, the system predicts which rider will finish ahead — directly mirroring cycling betting markets (e.g., "Pogačar vs Vingegaard in Stage 14").

The pipeline scrapes historical results from ProCyclingStats, engineers **270 features** per matchup, benchmarks **5 ML models**, and serves predictions through a Flask web app with **Kelly Criterion** staking advice and a full **P&L tracker**.

---

## Table of Contents

- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Setup](#setup)
- [Usage](#usage)
  - [1. Scrape Race Data](#1-scrape-race-data)
  - [2. Incremental Updates](#2-incremental-updates)
  - [3. Train Models](#3-train-models)
  - [4. Run Feature Experiments](#4-run-feature-experiments)
  - [5. Launch Web App](#5-launch-web-app)
- [Web Application](#web-application)
  - [Prediction Page](#prediction-page-)
  - [P&L Tracker](#pl-tracker-pnl)
- [API Reference](#api-reference)
- [Data Pipeline](#data-pipeline)
  - [Data Source](#data-source)
  - [Database Schema](#database-schema)
  - [Races Covered](#races-covered)
  - [Scraper Details](#scraper-details)
- [Feature Engineering](#feature-engineering)
  - [Race Features (19)](#race-features-19)
  - [Rider Features (78 per rider)](#rider-features-78-per-rider)
  - [Derived Feature Groups](#derived-feature-groups)
  - [Complete Feature Breakdown (270 total)](#complete-feature-breakdown-270-total)
- [Models](#models)
  - [Model Architectures](#model-architectures)
  - [Training Pipeline](#training-pipeline)
  - [Model Persistence](#model-persistence)
  - [Feature Ablation Results](#feature-ablation-results)
- [Kelly Criterion & Staking](#kelly-criterion--staking)
- [P&L Tracking System](#pl-tracking-system)
- [Project Structure](#project-structure)
- [Dependencies](#dependencies)
- [Technical Notes & Gotchas](#technical-notes--gotchas)
- [Limitations](#limitations)

---

## Features

- **5 ML models** benchmarked: Logistic Regression, Random Forest, XGBoost, Neural Network, Calibrated XGBoost
- **270 engineered features**: race profile, rider form (multiple time windows), specialty scores, terrain affinity, career stats, head-to-head history, interaction terms
- **Kelly Criterion** staking with full/half/quarter Kelly recommendations
- **P&L tracker** with bankroll management, bet history, ROI/win-rate stats, bankroll chart, and auto-settle from scraped results
- **Dark-themed web UI** with rider/race autocomplete search
- **Time-based train/test split** — trains on earlier years, tests on recent years (no data leakage)
- **Feature ablation study** — systematic comparison of 20 feature group combinations
- **Periodic update script** — fetch new races incrementally since last scrape
- **SQLite caching** — all scraped data persisted locally, no re-scraping needed
- **Rate-limited scraping** — ~1.2s between requests to avoid Cloudflare blocks
- **Model persistence** — trained models saved to disk and reloaded automatically

---

## Architecture Overview

```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│ ProCycling   │────▶│  Scraper      │────▶│  SQLite Cache  │────▶│  Builder     │
│ Stats (web)  │     │ (cloudscraper)│     │  (cache.db)    │     │  (H2H pairs) │
└─────────────┘     └──────────────┘     └───────────────┘     └──────┬───────┘
                                                                       │
                                                                       ▼
┌──────────────┐     ┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│  Flask Web   │◀────│  Predictor   │◀────│  Trained       │◀────│  Feature     │
│  Application │     │  + Kelly     │     │  Models (.pkl) │     │  Pipeline    │
└──────────────┘     └──────────────┘     └───────────────┘     └──────────────┘
       │
       ▼
┌──────────────┐
│  P&L Tracker │
│  (bets.db)   │
└──────────────┘
```

---

## Setup

### Prerequisites
- Python 3.10+
- macOS: `brew install libomp` (required for XGBoost)

### Installation

```bash
cd cycling-predictor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Quick Start (full pipeline)

```bash
# 1. Scrape data (takes several hours due to rate limiting)
python scripts/scrape_all.py

# 2. Train models
python scripts/train.py

# 3. Launch web app
python webapp/app.py
# Open http://localhost:5000
```

---

## Usage

### 1. Scrape Race Data

```bash
python scripts/scrape_all.py
```

- Scrapes **35 major races** × years **2018–2026**
- Each race: overview → stages → results → rider profiles
- Data cached in `data/cache.db` (SQLite) — re-running skips already-scraped pages
- Rate limited to **~1.2 seconds** between requests
- Expect **several hours** for a full scrape due to rate limiting
- Progress bars shown via `tqdm`

### 2. Incremental Updates

```bash
python scripts/update_races.py
```

- Fetches only races with dates **after the last scrape**
- Falls back to `2025-01-01` if no prior scrape log exists
- If run in January–March, also checks the previous year
- Ideal for a weekly cron job:
  ```
  0 3 * * 1 cd /path/to/cycling-predictor && .venv/bin/python scripts/update_races.py
  ```

### 3. Train Models

```bash
python scripts/train.py
```

Pipeline steps:
1. **Build H2H pairs** — `build_pairs_sampled(max_rank=50, pairs_per_stage=200)` generates training pairs from race results
2. **Engineer features** — builds 270-dimensional feature vectors for each pair
3. **Benchmark models** — trains 5 models with time-based split, saves best artifacts

Training outputs saved to `models/trained/`:
- `scaler.pkl` — fitted StandardScaler
- `feature_names.json` — ordered feature list
- `LogisticRegression.pkl`, `RandomForest.pkl`, `XGBoost.pkl`, `CalibratedXGBoost.pkl`
- `neural_net.pt` — PyTorch state dict
- `benchmark_results.csv` — all model metrics

### 4. Run Feature Experiments

```bash
# XGBoost ablation (default)
python scripts/experiment.py

# Neural network ablation
python scripts/experiment.py --model nn

# More evaluation splits
python scripts/experiment.py --splits 5
```

CLI arguments:
| Argument | Default | Choices | Description |
|----------|---------|---------|-------------|
| `--model` | `xgboost` | `xgboost`, `nn` | Model type to evaluate |
| `--splits` | `3` | any int | Number of random train/test splits |

Runs **20 experiments** comparing different feature group combinations, reports accuracy, ROC-AUC, and Brier score for each.

### 5. Launch Web App

```bash
python webapp/app.py
```

- Runs Flask in debug mode on `http://localhost:5000`
- Requires trained models in `models/trained/`
- Requires scraped data in `data/cache.db`

---

## Web Application

### Prediction Page (`/`)

1. **Search Rider A** — autocomplete from database (min 2 chars, max 20 results)
2. **Search Rider B** — same autocomplete
3. **Search Race/Stage** — autocomplete by race name or stage name
4. **Enter Bookmaker Odds** (optional) — decimal odds for each rider
5. Click **Predict Head-to-Head**

Results display:
- **Win probability** for each rider (percentage)
- **Winner highlight** — green border on the favoured rider
- **Kelly Analysis** (if odds provided):
  - Bookmaker odds & implied probability
  - Model edge (model prob − implied prob)
  - Expected value per £1
  - Full Kelly, Half Kelly fractions
  - Value bet verdict (✅ or ❌)
- **Log This Bet** button — appears on value bets, auto-calculates stake from ½ Kelly × bankroll

### P&L Tracker (`/pnl`)

- **Initial bankroll setup** — prompted on first visit
- **Dashboard stats**: bankroll, total profit, ROI, win rate, settled bets, pending bets, avg edge, total staked
- **Bankroll chart** — canvas line graph (green if up, red if down)
- **Bet history table**: date, race, selection, odds, edge, stake, P&L, status
- **Action buttons** on pending bets: Won / Lost / Void
- **Auto-Settle** — automatically settles pending bets when matching race results exist in the database

---

## API Reference

### Prediction & Data Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Prediction page |
| `GET` | `/api/riders?q=pog` | Rider autocomplete (min 2 chars, max 20 results) |
| `GET` | `/api/races?q=tour&year=2024` | Race/stage search |
| `POST` | `/api/predict` | Make H2H prediction |
| `GET` | `/api/stats` | Database statistics |

### P&L Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/pnl` | P&L tracker page |
| `GET` | `/api/pnl/summary` | P&L summary (bankroll, ROI, win rate, etc.) |
| `GET` | `/api/pnl/history?limit=50` | Bet history (most recent first) |
| `POST` | `/api/pnl/bankroll` | Set initial bankroll |
| `POST` | `/api/pnl/bet` | Place a bet |
| `POST` | `/api/pnl/settle` | Settle a bet (won/lost) |
| `POST` | `/api/pnl/void` | Void a bet (stake returned) |
| `POST` | `/api/pnl/auto-settle` | Auto-settle from scraped results |

### Prediction Request/Response

**Request** (`POST /api/predict`):
```json
{
  "rider_a_url": "rider/tadej-pogacar",
  "rider_b_url": "rider/jonas-vingegaard",
  "stage_url": "race/tour-de-france/2024/stage-14",
  "odds_a": 1.65,
  "odds_b": 2.40
}
```

**Response**:
```json
{
  "rider_a": {
    "name": "Pogačar Tadej",
    "url": "rider/tadej-pogacar",
    "win_probability": 0.723,
    "win_pct": "72.3%",
    "kelly": {
      "edge": 0.117,
      "edge_pct": "11.7%",
      "full_kelly": 0.180,
      "half_kelly": 0.090,
      "quarter_kelly": 0.045,
      "expected_value": 0.070,
      "should_bet": true,
      "bookmaker_odds": 1.65,
      "implied_prob": 0.606,
      "summary": "..."
    }
  },
  "rider_b": {
    "name": "Vingegaard Jonas",
    "url": "rider/jonas-vingegaard",
    "win_probability": 0.277,
    "win_pct": "27.7%"
  },
  "model": "CalibratedXGBoost"
}
```

### Place Bet Request

**Request** (`POST /api/pnl/bet`):
```json
{
  "stage_url": "race/tour-de-france/2024/stage-14",
  "race_name": "Tour de France Stage 14",
  "race_date": "2024-07-13",
  "rider_a_url": "rider/tadej-pogacar",
  "rider_a_name": "Pogačar Tadej",
  "rider_b_url": "rider/jonas-vingegaard",
  "rider_b_name": "Vingegaard Jonas",
  "selection": "rider/tadej-pogacar",
  "decimal_odds": 1.65,
  "model_prob": 0.723,
  "kelly_fraction": 0.09,
  "stake": 90.0,
  "model_used": "CalibratedXGBoost",
  "notes": ""
}
```

**Response**:
```json
{
  "bet_id": 1,
  "bankroll": 910.0
}
```

---

## Data Pipeline

### Data Source

All data scraped from [ProCyclingStats](https://www.procyclingstats.com/) using the [`procyclingstats`](https://procyclingstats.readthedocs.io/) Python library. The library requires [`cloudscraper`](https://pypi.org/project/cloudscraper/) to bypass Cloudflare protection — it auto-detects cloudscraper if installed.

### Database Schema

All data stored in `data/cache.db` (SQLite).

#### `races`
| Column | Type | Description |
|--------|------|-------------|
| `url` | TEXT PK | PCS race URL (e.g., `race/tour-de-france/2024`) |
| `name` | TEXT | Race name |
| `year` | INTEGER | Race year |
| `nationality` | TEXT | Country code |
| `is_one_day_race` | INTEGER | 0 = stage race, 1 = one-day classic |
| `category` | TEXT | Race category |
| `uci_tour` | TEXT | UCI classification (WorldTour, ProSeries, etc.) |
| `startdate` | TEXT | ISO date |
| `enddate` | TEXT | ISO date |
| `scraped_at` | TEXT | Timestamp of scrape |

#### `stages`
| Column | Type | Description |
|--------|------|-------------|
| `url` | TEXT PK | PCS stage URL |
| `race_url` | TEXT | FK to races |
| `stage_name` | TEXT | Stage name/number |
| `date` | TEXT | ISO date |
| `distance` | REAL | Distance in km |
| `vertical_meters` | REAL | Total elevation gain |
| `profile_score` | REAL | PCS profile score (higher = harder) |
| `profile_icon` | TEXT | `p1` (flat) to `p5` (mountain) |
| `avg_speed_winner` | REAL | Winner's average speed (km/h) |
| `avg_temperature` | REAL | Temperature (°C) |
| `departure` | TEXT | Start city |
| `arrival` | TEXT | Finish city |
| `stage_type` | TEXT | `RR`, `ITT`, `TTT` |
| `is_one_day_race` | INTEGER | Inherited from race |
| `race_category` | TEXT | Inherited from race |
| `startlist_quality_score` | TEXT | JSON — quality of the start list |
| `pcs_points_scale` | TEXT | PCS points scale |
| `uci_points_scale` | TEXT | UCI points scale |
| `num_climbs` | INTEGER | Number of categorised climbs |
| `climbs_json` | TEXT | JSON array of climb objects (category, steepness, length) |
| `scraped_at` | TEXT | Timestamp |

#### `results`
| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `stage_url` | TEXT | FK to stages |
| `rider_url` | TEXT | FK to riders |
| `rider_name` | TEXT | Full name |
| `team_name` | TEXT | Team at time of race |
| `team_url` | TEXT | PCS team URL |
| `rank` | INTEGER | Finishing position (NULL = DNF/DNS) |
| `status` | TEXT | Finish status |
| `age` | INTEGER | Rider age at race |
| `nationality` | TEXT | Country code |
| `time_str` | TEXT | Finish time string |
| `bonus` | TEXT | Time bonus |
| `pcs_points` | REAL | PCS points earned |
| `uci_points` | REAL | UCI points earned |
| `breakaway_kms` | REAL | Kilometres in breakaway |

Unique constraint: `(stage_url, rider_url)`

#### `riders`
| Column | Type | Description |
|--------|------|-------------|
| `url` | TEXT PK | PCS rider URL (e.g., `rider/tadej-pogacar`) |
| `name` | TEXT | Full name |
| `nationality` | TEXT | Country code |
| `birthdate` | TEXT | ISO date |
| `weight` | REAL | Weight in kg |
| `height` | REAL | Height in metres |
| `specialty_one_day` | REAL | PCS one-day specialist score |
| `specialty_gc` | REAL | PCS GC specialist score |
| `specialty_tt` | REAL | PCS time trial score |
| `specialty_sprint` | REAL | PCS sprinter score |
| `specialty_climber` | REAL | PCS climber score |
| `specialty_hills` | REAL | PCS hills/puncheur score |
| `points_history_json` | TEXT | JSON: `[{season, points, rank}, ...]` |
| `scraped_at` | TEXT | Timestamp |

#### `scrape_log`
| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `action` | TEXT | Scrape action type |
| `detail` | TEXT | Race/stage URL |
| `timestamp` | TEXT | Auto-set via `datetime('now')` |

#### `bets` (P&L system)
| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `created_at` | TEXT | Auto-set |
| `race_date` | TEXT | Race date |
| `race_name` | TEXT | Race display name |
| `stage_url` | TEXT | Stage URL for auto-settling |
| `rider_a_url` | TEXT | Rider A URL |
| `rider_a_name` | TEXT | Rider A name |
| `rider_b_url` | TEXT | Rider B URL |
| `rider_b_name` | TEXT | Rider B name |
| `selection` | TEXT | Selected rider URL |
| `selection_name` | TEXT | Selected rider name |
| `decimal_odds` | REAL | Bookmaker odds |
| `implied_prob` | REAL | `1 / decimal_odds` |
| `model_prob` | REAL | Model's predicted probability |
| `edge` | REAL | `model_prob - implied_prob` |
| `kelly_fraction` | REAL | Recommended Kelly fraction |
| `stake` | REAL | Actual stake placed |
| `bankroll_at_bet` | REAL | Bankroll at time of bet |
| `status` | TEXT | `pending`, `won`, `lost`, `void` |
| `payout` | REAL | Amount returned (0 if lost) |
| `profit` | REAL | `payout - stake` |
| `settled_at` | TEXT | Settlement timestamp |
| `model_used` | TEXT | Model name used |
| `notes` | TEXT | Free-text notes |

#### `bankroll_history`
| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `timestamp` | TEXT | Auto-set |
| `bankroll` | REAL | Bankroll after event |
| `event` | TEXT | `initial`, `bet_placed`, `bet_settled` |

### Database Indexes
- `idx_results_stage` — `results(stage_url)`
- `idx_results_rider` — `results(rider_url)`
- `idx_stages_race` — `stages(race_url)`
- `idx_stages_date` — `stages(date)`
- `idx_bets_status` — `bets(status)`
- `idx_bets_date` — `bets(race_date)`

### Races Covered

35 major professional races are scraped by default:

**Grand Tours:**
- Tour de France, Giro d'Italia, Vuelta a España

**Stage Races:**
- Paris-Nice, Tirreno-Adriatico, Volta a Catalunya, Itzulia Basque Country, Tour de Romandie, Critérium du Dauphiné, Tour de Suisse, Tour de Pologne, Tour Down Under, UAE Tour, Renewi Tour, Tour de Wallonie, Deutschland Tour, BinckBank Tour

**Monuments & Classics:**
- Milano-Sanremo, Strade Bianche, E3 Harelbeke, Gent-Wevelgem, Dwars door Vlaanderen, Ronde van Vlaanderen, Paris-Roubaix, Amstel Gold Race, La Flèche Wallonne, Liège-Bastogne-Liège, Il Lombardia

**Other One-Day Races:**
- Clásica Ciclista San Sebastián, Bretagne Classic, Cyclassics Hamburg, GP Québec, GP Montréal, Omloop Het Nieuwsblad, Paris-Tours

### Scraper Details

- **Rate limiting**: Global limiter at **1.2 seconds** between requests (`REQUEST_DELAY = 1.2`)
- **Cloudflare bypass**: Uses `cloudscraper` package (auto-detected by `procyclingstats`)
- **Error handling**: Individual stage/rider scrape failures are logged and skipped (no crash on partial failures)
- **One-day races**: Results use `/result` URL suffix (e.g., `race/paris-roubaix/2024/result`)
- **Rider parsing issues**: Some rider profile pages fail with "list index out of range" — gracefully skipped
- **Result filtering**: Only riders with a numeric finishing `rank` are included (DNF/DNS excluded)

---

## Feature Engineering

### Race Features (19)

Extracted from each stage/race record. Shared between both riders in a pair.

| Feature | Description | Source |
|---------|-------------|--------|
| `distance_km` | Race distance in km | PCS stage data |
| `vertical_meters` | Total elevation gain in metres | PCS stage data |
| `profile_score` | PCS difficulty score (higher = harder) | PCS stage data |
| `profile_icon_num` | Encoded profile: p1=1 (flat) to p5=5 (mountain) | PCS profile_icon |
| `vert_per_km` | Vertical metres per km (terrain difficulty ratio) | Computed: `vertical_meters / distance_km` |
| `avg_speed_winner` | Winner's average speed (km/h) | PCS stage data |
| `avg_temperature` | Race temperature (°C) | PCS stage data |
| `is_one_day_race` | 1.0 if one-day classic, 0.0 if stage race | PCS race type |
| `is_itt` | 1.0 if individual time trial | PCS stage_type |
| `is_ttt` | 1.0 if team time trial | PCS stage_type |
| `startlist_quality` | Quality score of the start list | PCS data |
| `num_climbs` | Number of categorised climbs | PCS climbs data |
| `avg_climb_steepness` | Mean steepness of all climbs (%) | Computed from climbs_json |
| `max_climb_steepness` | Steepest climb gradient (%) | Computed from climbs_json |
| `total_climb_length` | Total length of all climbs (km) | Computed from climbs_json |
| `avg_climb_length` | Mean climb length (km) | Computed from climbs_json |
| `max_climb_category` | Highest climb category (HC=5, Cat1=4, ..., Cat4=1) | Mapped from climbs_json |
| `num_hc_climbs` | Number of Hors Catégorie climbs | Count from climbs_json |
| `num_cat1_plus` | Number of Cat 1 or HC climbs | Count from climbs_json |

**Climb category encoding**: `Cat4=1, Cat3=2, Cat2=3, Cat1=4, HC=5`

### Rider Features (78 per rider)

Computed per rider using **only data available before the target race** (no data leakage).

#### Physical / Profile (4)
| Feature | Description | Default |
|---------|-------------|---------|
| `weight` | Weight in kg | 70.0 |
| `height` | Height in metres | 1.80 |
| `bmi` | Body Mass Index | 22.0 |
| `age` | Age at race date (years, fractional) | 28.0 |

#### Specialty Scores (6)
From PCS rider profile — measure rider's points in each discipline:
- `spec_one_day`, `spec_gc`, `spec_tt`, `spec_sprint`, `spec_climber`, `spec_hills`

#### Specialty Percentages (6)
Each specialty as a proportion of total specialty points:
- `spec_climber_pct`, `spec_sprint_pct`, `spec_gc_pct`, `spec_tt_pct`, `spec_one_day_pct`, `spec_hills_pct`

#### Season Points & Rankings (5)
3-year lookback from rider's `points_per_season_history`:
| Feature | Description | Default |
|---------|-------------|---------|
| `avg_season_points_3yr` | Mean season points over last 3 years | 0.0 |
| `max_season_points_3yr` | Peak season points in last 3 years | 0.0 |
| `best_ranking_3yr` | Best world ranking in last 3 years | 500.0 |
| `avg_ranking_3yr` | Mean world ranking in last 3 years | 500.0 |
| `points_trend` | Points year-over-year change (last year − year before) | 0.0 |

#### Career Statistics (11)
Computed from all historical results before the target race:
| Feature | Description | Default |
|---------|-------------|---------|
| `career_races` | Total races completed | 0 |
| `career_avg_rank` | Mean finishing position | 50.0 |
| `career_median_rank` | Median finishing position | 50.0 |
| `career_wins` | Total victories | 0 |
| `career_podiums` | Total podium finishes (top 3) | 0 |
| `career_top10` | Total top-10 finishes | 0 |
| `career_win_rate` | Win percentage | 0.0 |
| `career_podium_rate` | Podium percentage | 0.0 |
| `career_top10_rate` | Top-10 percentage | 0.0 |
| `career_avg_pcs_pts` | Mean PCS points per race | 0.0 |
| `career_avg_uci_pts` | Mean UCI points per race | 0.0 |

#### Recent Form — Time Windows (20)
For each of **30d, 60d, 90d, 180d** windows before race date:
| Feature | Description | Default |
|---------|-------------|---------|
| `form_{N}d_races` | Races completed in window | 0 |
| `form_{N}d_avg_rank` | Mean rank in window | 50.0 |
| `form_{N}d_wins` | Wins in window | 0 |
| `form_{N}d_top10` | Top-10s in window | 0 |
| `form_{N}d_avg_pcs` | Mean PCS points in window | 0.0 |

#### Recent Form — Last N Races (9)
For **last 5, 10, 20** races:
| Feature | Description | Default |
|---------|-------------|---------|
| `form_last{N}_avg_rank` | Mean rank in last N | 50.0 |
| `form_last{N}_best_rank` | Best rank in last N | 50 |
| `form_last{N}_avg_pcs` | Mean PCS points in last N | 0.0 |

#### Terrain Affinity (14)
Performance on similar terrain types:
| Feature | Description | Default |
|---------|-------------|---------|
| `terrain_same_profile_races` | Races on same profile icon (p1–p5) | 0 |
| `terrain_same_profile_avg_rank` | Avg rank on same profile | 50.0 |
| `terrain_same_profile_top10` | Top-10s on same profile | 0 |
| `terrain_sim_dist_races` | Races within ±30% distance | 0 |
| `terrain_sim_dist_avg_rank` | Avg rank at similar distances | 50.0 |
| `mountain_races` | Races with profile_score > 100 | 0 |
| `mountain_avg_rank` | Avg rank in mountains | 50.0 |
| `flat_races` | Races with profile_score < 20 | 0 |
| `flat_avg_rank` | Avg rank on flat | 50.0 |
| `one_day_races` | One-day race count | 0 |
| `one_day_avg_rank` | Avg rank in one-day races | 50.0 |
| `itt_races` | Individual time trial count | 0 |
| `itt_avg_rank` | Avg rank in ITTs | 50.0 |

#### Same-Race History (3)
Performance in the same race in previous years:
| Feature | Description | Default |
|---------|-------------|---------|
| `same_race_history_count` | Times rider has done this race before | 0 |
| `same_race_avg_rank` | Avg rank in this race | 50.0 |
| `same_race_best_rank` | Best-ever rank in this race | 50 |

#### Breakaway (1)
| Feature | Description | Default |
|---------|-------------|---------|
| `breakaway_rate` | Proportion of races with breakaway kms > 0 | 0.0 |

### Derived Feature Groups

The pipeline creates several views of the 78 rider features:

| Group | Prefix | Count | Description |
|-------|--------|-------|-------------|
| **Diff features** | `diff_` | 78 | Rider A value minus Rider B value |
| **Absolute A** | `a_` | 78 | Raw values for Rider A |
| **Absolute B** | `b_` | 78 | Raw values for Rider B |

#### Head-to-Head History (5)
Direct historical matchup between the two riders:
| Feature | Description |
|---------|-------------|
| `h2h_total_races` | Shared race count |
| `h2h_a_win_rate` | Rider A's win rate vs B (default 0.5) |
| `h2h_a_wins` | Rider A's wins vs B |
| `h2h_b_wins` | Rider B's wins vs A |
| `h2h_avg_rank_diff` | Mean (rank_A − rank_B) |

#### Interaction Features (12)
Cross-terms between rider specialty and race terrain:
| Feature | Formula |
|---------|---------|
| `interact_a_climber_x_profile` | `spec_climber(A) × profile_icon_num` |
| `interact_b_climber_x_profile` | `spec_climber(B) × profile_icon_num` |
| `interact_diff_climber_x_profile` | A minus B |
| `interact_a_climber_x_vert` | `spec_climber(A) × (vertical_meters / 1000)` |
| `interact_b_climber_x_vert` | `spec_climber(B) × (vertical_meters / 1000)` |
| `interact_diff_climber_x_vert` | A minus B |
| `interact_a_tt_x_itt` | `spec_tt(A) × is_itt` |
| `interact_b_tt_x_itt` | `spec_tt(B) × is_itt` |
| `interact_diff_tt_x_itt` | A minus B |
| `interact_a_sprint_x_flat` | `spec_sprint(A) × max(0, 1 − profile/3)` |
| `interact_b_sprint_x_flat` | `spec_sprint(B) × max(0, 1 − profile/3)` |
| `interact_diff_sprint_x_flat` | A minus B |

### Complete Feature Breakdown (270 total)

| Group | Count | Description |
|-------|-------|-------------|
| Race features (`race_*`) | 19 | Shared race/stage characteristics |
| Diff rider features (`diff_*`) | 78 | Rider A − Rider B differences |
| Absolute rider A (`a_*`) | 78 | Raw rider A features |
| Absolute rider B (`b_*`) | 78 | Raw rider B features |
| H2H history | 5 | Head-to-head record |
| Interaction terms | 12 | Specialty × terrain cross-features |
| **Total** | **270** | |

---

## Models

### Model Architectures

#### 1. Logistic Regression
- `max_iter=1000`, `C=1.0`, `random_state=42`
- Simple linear baseline

#### 2. Random Forest
- `n_estimators=200`, `max_depth=15`, `min_samples_leaf=10`
- `n_jobs=1` (required to avoid PyTorch thread deadlock)
- `random_state=42`

#### 3. XGBoost
- `n_estimators=300`, `max_depth=8`, `learning_rate=0.05`
- `subsample=0.8`, `colsample_bytree=0.8`, `min_child_weight=10`
- `reg_alpha=0.1`, `reg_lambda=1.0`
- `eval_metric="logloss"`, `random_state=42`

#### 4. Neural Network (PyTorch)
- Architecture: `Input → [Linear → BatchNorm → ReLU → Dropout] × 4 → Sigmoid`
- Hidden layers: `256 → 128 → 64 → 32`
- Dropout: `0.3`
- Optimizer: Adam (`lr=1e-3`, `weight_decay=1e-5`)
- LR Scheduler: `ReduceLROnPlateau(factor=0.5, patience=5)`
- Loss: `BCELoss`
- Batch size: `512`
- Early stopping: patience `10` epochs
- Max epochs: `100`

#### 5. Calibrated XGBoost *(default for predictions)*
- Same XGBoost hyperparameters as above
- Wrapped with `CalibratedClassifierCV(method="isotonic", cv=5)`
- Produces well-calibrated probabilities — essential for Kelly Criterion

### Training Pipeline

1. **Data split**: Time-based — trains on earlier years, tests on 2025–2026
   - Dates extracted from stage data; missing dates default to year 2020
2. **Scaling**: All features standardised with `StandardScaler` (fit on train only)
3. **Evaluation metrics**: Accuracy, ROC-AUC, Log Loss, Brier Score
4. **Best model selection**: Highest ROC-AUC on test set
5. **Thread safety**: Forces single-threaded execution (`OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `torch.set_num_threads(1)`) to prevent sklearn/PyTorch deadlock

### Model Persistence

All artifacts saved to `models/trained/`:

| File | Contents |
|------|----------|
| `scaler.pkl` | Fitted `StandardScaler` |
| `feature_names.json` | Ordered list of 270 feature names |
| `LogisticRegression.pkl` | Pickled sklearn model |
| `RandomForest.pkl` | Pickled sklearn model |
| `XGBoost.pkl` | Pickled XGBoost model |
| `CalibratedXGBoost.pkl` | Pickled calibrated model |
| `neural_net.pt` | PyTorch `state_dict` |
| `benchmark_results.csv` | All model comparison metrics |

Models are loaded lazily by the web app — no re-training needed between runs.

### Feature Ablation Results

20 experiments tested with both XGBoost and Neural Network across multiple splits:

| Experiment | Groups Used | XGB AUC | NN AUC |
|---|---|---|---|
| `all_features` | All 270 | 0.840 | 0.832 |
| `no_physical` | Drop weight/height/BMI/age | **0.843** | 0.834 |
| `no_interactions` | Drop interaction terms | 0.841 | 0.835 |
| `no_absolute` | Drop abs rider features | 0.839 | 0.833 |
| `no_h2h` | Drop H2H history | 0.840 | **0.838** |
| `diff_only` | Only diff features | 0.838 | 0.830 |
| `race_only` | Only race features | 0.49 | 0.49 |
| `random_baseline` | No features | 0.50 | 0.50 |

**Key findings:**
- **Diff features carry ~95% of signal** — rider A minus rider B differences are the most predictive
- **Physical stats add noise** — dropping weight/height/BMI/age improved XGBoost by 0.003 AUC
- **Interactions are unnecessary** — XGBoost/NN learn these implicitly
- **Race features alone ≈ random** (0.49 AUC) but improve predictions when combined with rider context
- **H2H history is noisy** with limited data — NN benefits from dropping it
- **Top features**: `diff_form_90d_top10`, `diff_career_top10_rate`, `diff_form_60d_top10`

---

## Kelly Criterion & Staking

The system uses the [Kelly Criterion](https://en.wikipedia.org/wiki/Kelly_criterion) to calculate optimal bet sizing.

### Formula

```
f* = (bp − q) / b

where:
  b = decimal_odds − 1       (net profit per unit bet if won)
  p = model's probability     (estimated chance of winning)
  q = 1 − p                   (estimated chance of losing)
```

### Implementation Details

- **Edge**: `model_prob − implied_prob` where `implied_prob = 1 / decimal_odds`
- **Expected Value**: `p × b − q` (per unit staked)
- **Max cap**: Full Kelly capped at **25%** of bankroll (`max_fraction=0.25`)
- **Half Kelly** (recommended): `f* / 2` — reduces variance significantly
- **Quarter Kelly** (conservative): `f* / 4`
- **Bet signal**: Only recommend betting when Kelly fraction > 0 (positive edge)

### Odds Conversion Utilities

The system includes converters for all major odds formats:
- `decimal_odds_to_implied_prob(decimal_odds)` — e.g., 2.50 → 0.40
- `fractional_odds_to_decimal(fractional)` — e.g., "3/1" → 4.00
- `american_odds_to_decimal(american)` — e.g., +250 → 3.50, −200 → 1.50

---

## P&L Tracking System

### Bet Lifecycle

```
Place Bet → Pending → [Won / Lost / Void]
              │
              └─── Auto-settle (matches against scraped race results)
```

### Bankroll Management

- **Initial bankroll** set once (stored in `bankroll_history`)
- **Stake deducted** when bet placed
- **Payout added** when bet settled as won (`stake × decimal_odds`)
- **Stake refunded** when bet voided
- Full audit trail in `bankroll_history` table

### Auto-Settlement

When `auto_settle_from_results()` is called:
1. Finds all pending bets
2. Looks up both riders' results for the bet's `stage_url`
3. If both riders have finishing ranks, settles based on who placed higher
4. Returns count of settled bets

### P&L Summary Fields

| Field | Description |
|-------|-------------|
| `bankroll` | Current bankroll |
| `total_bets` | Settled bet count |
| `pending_bets` | Unsettled bet count |
| `pending_stake` | Total pending stake |
| `wins` / `losses` | Win/loss counts |
| `win_rate` | `wins / total_bets` |
| `total_staked` | Sum of all settled stakes |
| `total_returned` | Sum of all payouts |
| `total_profit` | `total_returned − total_staked` |
| `roi` | `total_profit / total_staked` |
| `avg_edge` | Mean model edge across settled bets |
| `avg_odds` | Mean decimal odds of settled bets |
| `bankroll_history` | Time-series of bankroll changes |

---

## Project Structure

```
cycling-predictor/
├── data/
│   ├── __init__.py
│   ├── scraper.py              # PCS scraper with SQLite cache + rate limiting
│   │                           # - 35 major races, 1.2s rate limit
│   │                           # - Tables: races, stages, results, riders, scrape_log
│   ├── builder.py              # H2H pair generation from race results
│   │                           # - Top-50 finishers, 200 pairs/stage sampling
│   ├── pnl.py                  # P&L tracker backend
│   │                           # - Tables: bets, bankroll_history
│   │                           # - Bet lifecycle: place → settle/void
│   └── cache.db                # SQLite database (generated by scraper)
│
├── features/
│   ├── __init__.py
│   ├── race_features.py        # 19 race features (distance, elevation, climbs, profile)
│   ├── rider_features.py       # 78 rider features per rider (form, specialty, terrain, career)
│   └── pipeline.py             # Full 270-feature pipeline (race + diff + absolute + H2H + interactions)
│
├── models/
│   ├── __init__.py
│   ├── benchmark.py            # Train & compare 5 models, save artifacts
│   ├── neural_net.py           # PyTorch 4-layer NN (256→128→64→32, BatchNorm, Dropout)
│   ├── predict.py              # Predictor class + Kelly Criterion + odds converters
│   └── trained/                # Saved model artifacts (generated by training)
│       ├── scaler.pkl
│       ├── feature_names.json
│       ├── LogisticRegression.pkl
│       ├── RandomForest.pkl
│       ├── XGBoost.pkl
│       ├── CalibratedXGBoost.pkl
│       ├── neural_net.pt
│       └── benchmark_results.csv
│
├── scripts/
│   ├── scrape_all.py           # Full scrape: 2018–2026
│   ├── update_races.py         # Incremental update since last scrape
│   ├── train.py                # Training orchestrator (pairs → features → benchmark)
│   └── experiment.py           # Feature ablation study (20 experiments, --model, --splits)
│
├── webapp/
│   ├── __init__.py
│   ├── app.py                  # Flask app (14 routes, port 5000, debug mode)
│   └── templates/
│       ├── index.html          # Prediction page (autocomplete, Kelly display, log bet)
│       └── pnl.html            # P&L dashboard (bankroll chart, bet history, auto-settle)
│
├── notebooks/                  # Empty — for future Jupyter analysis
├── requirements.txt            # All dependencies (minimum versions)
└── README.md                   # This file
```

---

## Dependencies

| Package | Min Version | Purpose |
|---------|-------------|---------|
| `procyclingstats` | ≥0.2.0 | Parse ProCyclingStats pages |
| `cloudscraper` | ≥1.2.71 | Bypass Cloudflare protection |
| `pandas` | ≥2.0.0 | DataFrames for features and training data |
| `numpy` | ≥1.24.0 | Numerical operations |
| `scikit-learn` | ≥1.3.0 | ML models, preprocessing, calibration |
| `xgboost` | ≥2.0.0 | Gradient boosting model |
| `torch` | ≥2.1.0 | Neural network (PyTorch) |
| `flask` | ≥3.0.0 | Web application |
| `requests` | ≥2.31.0 | HTTP requests |
| `tqdm` | ≥4.66.0 | Progress bars |
| `joblib` | ≥1.3.0 | Model serialisation |
| `matplotlib` | ≥3.8.0 | Plotting (experiment results) |

---

## Technical Notes & Gotchas

### macOS XGBoost
XGBoost requires OpenMP on macOS:
```bash
brew install libomp
```

### Thread Deadlock Prevention
PyTorch and scikit-learn's `n_jobs=-1` cause thread deadlocks on macOS. Training scripts force single-threaded execution:
```python
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
torch.set_num_threads(1)
```
Random Forest uses `n_jobs=1` explicitly.

### PyTorch ReduceLROnPlateau
Newer PyTorch versions removed the `verbose` parameter from `ReduceLROnPlateau`. The code avoids using it.

### Neural Network Data Types
Labels must be explicitly cast to `float32`:
```python
y_train.values.astype(np.float32)
```

### ProCyclingStats Scraping
- Some rider pages fail with "list index out of range" (e.g., Vlasov, Girmay) — these are logged and skipped
- One-day race results need `/result` suffix: `race/paris-roubaix/2024/result`
- Cloudflare blocks plain `requests` — `cloudscraper` is mandatory
- Rate limiting at 1.2s is sufficient to avoid blocks in practice

### H2H Pair Generation
- Only pairs where both riders finished in **top 50** (`MAX_RANK_CUTOFF = 50`)
- Up to **200 pairs per stage** sampled to keep dataset manageable
- Random 50/50 swap of rider A/B to prevent ordering bias

### Feature Leakage Prevention
All rider features use **strictly pre-race data only** — the SQL queries filter on `s.date < race_date`.

---

## Limitations

- **Data volume matters** — model accuracy scales with scrape depth. 2 races ≈ 0.84 AUC; more data expected to improve
- **ProCyclingStats availability** — scraper depends on PCS being accessible and Cloudflare not blocking
- **No real-time odds** — bookmaker odds must be manually entered
- **Rate limiting** — full scrape takes several hours
- **CPU training** — neural network benefits from GPU but runs on CPU
- **Calibration quality** — isotonic calibration with `cv=5` may overfit on small datasets
- **No team tactics** — model doesn't capture domestique behaviour, sprint lead-outs, or team GC strategy
- **Weather not dynamic** — uses historical avg temperature, not forecast
- **Injuries/form news** — model only sees results, not news about injuries, illness, or motivation
