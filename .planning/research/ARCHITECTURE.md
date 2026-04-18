# Architecture: v2.0 Edge Validation & System Maturity (PaceIQ)

**Domain:** Adding CLV tracking, model upgrades, automation, and alerting to an existing Flask/SQLite/ML betting intelligence system
**Researched:** 2026-04-18
**Confidence:** HIGH — based on direct codebase audit of all affected modules
**Replaces:** v1.0 architecture doc (Pinnacle Preload, 2026-04-11)

---

## Executive Summary

v2.0 adds six new capability areas to the existing pipeline: (1) CLV tracking with closing-odds storage, (2) automated scheduling for closing-odds capture and post-race settlement, (3) pre-race report generation, (4) edge alerting, (5) model upgrades integrating new feature types, and (6) drift detection. None of these require changes to the core ML inference path (`models/predict.py`, `features/pipeline.py`). Integration is layered on top of what exists.

The existing architecture has two clean seams for v2.0 to attach to:
- `data/pnl.py` — the bets table already stores the bet placement odds; it needs new columns for closing odds and CLV, and a new module for CLV computation
- `data/odds.py` — the existing Pinnacle client (`fetch_cycling_h2h_markets()`) is reused unchanged to capture closing odds; no new API work needed

The scheduling question (APScheduler in-process vs external cron) is the primary architectural decision. Given the no-new-infrastructure constraint (SQLite, no Redis/Celery), `APScheduler 3.x BackgroundScheduler` attached to the Flask process is the right choice. It stores jobs in memory (not SQLite job store — avoids SQLAlchemy dependency) and survives the typical dev/VPS usage pattern where the Flask process runs continuously.

---

## Current Architecture Snapshot (Post-v1.0)

```
webapp/app.py (Flask, port 5001)
 ├── webapp/pinnacle_bp.py       POST /api/pinnacle/load, POST /api/pinnacle/refresh-odds
 ├── POST /api/predict            models/predict.py::Predictor.predict()
 ├── POST /api/predict/batch      models/predict.py::Predictor.predict_manual() (per pair)
 ├── POST /api/pnl/bet            data/pnl.py::place_bet() → cache.db::bets
 ├── POST /api/pnl/settle         data/pnl.py::settle_bet()
 ├── POST /api/pnl/auto-settle    data/pnl.py::auto_settle_from_results()
 └── /admin                       subprocess script runner (update_data, precompute, train)

data/pnl.py::bets table columns (existing):
  id, created_at, race_date, race_name, stage_url,
  rider_a_url, rider_a_name, rider_b_url, rider_b_name,
  selection, selection_name, decimal_odds, implied_prob,
  model_prob, edge, kelly_fraction, stake,
  bankroll_at_bet, status, payout, profit, settled_at,
  model_used, notes,
  is_one_day_race, stage_type, profile_icon,
  distance_km, vertical_meters, num_climbs

data/odds.py::fetch_cycling_h2h_markets() → list[OddsMarket]
  OddsMarket: rider_a_name, rider_b_name, odds_a, odds_b, race_name, matchup_id

data/pnl.py::auto_settle_from_results()
  — Queries cache.db::results for rank, settles pending bets
  — Currently does NOT compute CLV (no closing odds stored)
```

---

## New Capability Areas: Integration Map

### 1. CLV Tracking: Closing Odds Storage

**What changes:** The `bets` table needs three new columns. Settlement needs a CLV computation step. A new module handles the CLV math.

**Where closing odds go:** `cache.db::bets` — added via `ALTER TABLE` migration in `_create_pnl_tables()` (same idempotent pattern already used for race metadata columns at `data/pnl.py:71-83`).

**New columns (idempotent ALTER TABLE):**
```sql
closing_odds_a    REAL   -- Pinnacle closing line for rider A
closing_odds_b    REAL   -- Pinnacle closing line for rider B
closing_captured_at TEXT -- timestamp when captured
clv               REAL   -- computed: (model_odds / closing_odds) - 1, positive = good
```

**CLV formula** (no-vig approach): Strip the bookmaker margin from closing odds before computing CLV. For a 2-outcome market:
```
p_a_raw = 1 / closing_odds_a
p_b_raw = 1 / closing_odds_b
vig = p_a_raw + p_b_raw      -- typically 1.04-1.06 on Pinnacle H2H
fair_p_a = p_a_raw / vig     -- no-vig implied probability
# CLV for a bet on A at bet_odds_a:
clv = (1 / fair_p_a) / bet_odds_a - 1
# Positive CLV means you got better than fair price
```

**New file:** `data/clv.py`

| Function | Responsibility |
|----------|---------------|
| `compute_clv(bet: dict) -> float` | Given a settled bet row with closing_odds, return CLV |
| `capture_closing_odds(matchup_id: str) -> tuple[float, float] or None` | Call `data/odds.py::fetch_cycling_h2h_markets()`, find the matchup, return `(odds_a, odds_b)` — returns None if market closed |
| `capture_all_pending_closing_odds() -> int` | Iterate pending bets, call Pinnacle for each known matchup_id, write to bets table. Returns count updated. |
| `get_clv_summary() -> dict` | Aggregate CLV stats: avg, median, by-edge-bucket breakdown |

**Modified file:** `data/pnl.py`
- `_create_pnl_tables()` — add three new columns to the migration list (idempotent, follows existing pattern)
- `settle_bet()` — after settlement, call `compute_clv()` if closing_odds are present; write to `clv` column
- `auto_settle_from_results()` — unchanged structurally; CLV is written separately by the closing-odds capture job

**Modified file:** `webapp/app.py` (or new blueprint)
- `GET /api/pnl/clv-summary` — returns `get_clv_summary()` result
- `GET /api/pnl/history` — already returns all bet columns; adding CLV columns to the bets table makes them appear automatically

**Integration point:** `data/clv.py` imports `data/odds.py::fetch_cycling_h2h_markets()` and `data/pnl.py::get_pnl_db()`. No new dependencies.

---

### 2. Cron/Scheduling: APScheduler in Flask Process

**Decision: APScheduler 3.x BackgroundScheduler, in-process, memory job store.**

**Why not external cron:** The system constraint is no new infrastructure. OS cron (`crontab`) is an alternative, but requires the scripts to be individually invokable and introduces process management friction on VPS. APScheduler inside the Flask process is simpler and the Flask process is already expected to run continuously.

**Why not SQLite job store:** APScheduler's `SQLAlchemyJobStore` requires SQLAlchemy. Adding SQLAlchemy to `requirements.txt` is a heavyweight dependency for a personal tool. Memory job store is sufficient — jobs are re-registered on every Flask startup (the schedule is defined in code, not persisted state).

**Why not Flask-APScheduler extension:** The extension adds configuration-via-YAML overhead. Direct `BackgroundScheduler` is clearer for a small set of known jobs.

**Implementation:**

New file: `webapp/scheduler.py`

```python
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler(timezone="UTC")

def init_scheduler(app):
    """Register all scheduled jobs and start scheduler."""
    with app.app_context():
        # Job 1: Capture closing odds — T-5min before known race starts
        # (Triggered via one-shot DateTrigger when a bet is placed, not a standing cron)
        
        # Job 2: Post-race settlement — hourly check
        scheduler.add_job(
            func=_settlement_job,
            trigger="cron",
            hour="*", minute=30,
            id="post_race_settlement",
            replace_existing=True,
        )
        
        # Job 3: Pre-race briefing — daily at 06:00 UTC
        scheduler.add_job(
            func=_pre_race_briefing_job,
            trigger="cron",
            hour=6, minute=0,
            id="pre_race_briefing",
            replace_existing=True,
        )
        
        # Job 4: Drift monitor — weekly Sunday 08:00 UTC
        scheduler.add_job(
            func=_drift_monitor_job,
            trigger="cron",
            day_of_week="sun", hour=8,
            id="drift_monitor",
            replace_existing=True,
        )
        
    scheduler.start()
```

**Modified file:** `webapp/app.py`
- After `app.register_blueprint(pinnacle_bp)`, add:
  ```python
  from webapp.scheduler import init_scheduler
  init_scheduler(app)
  ```

**Closing-odds capture timing:** The "capture at race start" pattern requires knowing when each race starts. The approach is event-driven per-bet: when `place_bet()` is called, schedule a one-shot `DateTrigger` job for 5 minutes before the race_date + an estimated start time (default: 10:00 UTC for European cycling). The job calls `capture_closing_odds(matchup_id)` and writes to the bet row.

**Race start time estimation:** The `race_date` field in bets is a date string (e.g. `"2026-04-20"`). Assume 10:00 UTC as the default capture window for European cycling stages (race typically starts 10:00–12:00, H2H markets close at or just before start). This is a simplification — it can be refined later by reading PCS stage start times if needed. Store estimated capture time alongside each bet when it's placed.

**Thread safety note:** APScheduler jobs run in background daemon threads. Job functions must NOT share state with Flask request handlers except through the SQLite WAL database. All job functions must call `get_pnl_db()` to get their own connection — do not pass connections across thread boundaries. The existing WAL mode handles concurrent reads.

---

### 3. Pre-Race Reports

**What it does:** Generates a markdown (or JSON) report of today's H2H picks with model probabilities, edges, and Kelly stakes. Consumed by the Flask UI (new `/reports` page) and optionally sent via Discord webhook.

**New file:** `intelligence/reports.py`

| Function | Responsibility |
|----------|---------------|
| `generate_pre_race_report(race_name: str, stage_context: dict, pairs: list[dict]) -> dict` | Given resolved pairs with predictions already run, format a structured report |
| `report_to_markdown(report: dict) -> str` | Format report as markdown string |
| `save_report(report: dict, race_name: str) -> str` | Write to `data/reports/{date}-{race}.json`, return path |

**Data flow:**
```
_pre_race_briefing_job() [scheduler]
    │
    ├─► data/odds.py::fetch_cycling_h2h_markets()  — get today's markets
    ├─► data/name_resolver.py::NameResolver.resolve()  — resolve names
    ├─► intelligence/stage_context.py::fetch_stage_context()  — get stage
    ├─► models/predict.py::Predictor.predict_manual()  — run predictions (per pair)
    │       (uses existing inference path, no changes)
    ├─► intelligence/reports.py::generate_pre_race_report()
    └─► Save to data/reports/ + optionally POST to Discord webhook
```

**New route in `webapp/app.py`:**
- `GET /api/reports` — list saved reports
- `GET /api/reports/<date>` — serve a specific report as JSON
- `GET /reports` — render `reports.html` template (new page)

**Storage:** `data/reports/` directory, one JSON file per day per race. No new SQLite tables — file-based storage is fine for personal tool usage (low volume, easy to inspect).

---

### 4. Edge Alerts: Notification Dispatch

**What it does:** When the scheduler detects a bet with edge > threshold (default 8%), or when a refreshed odds check finds a new edge on a tracked matchup, send a Discord webhook message.

**New file:** `intelligence/alerts.py`

| Function | Responsibility |
|----------|---------------|
| `send_discord_alert(message: str) -> bool` | POST to `DISCORD_WEBHOOK_URL` env var; returns True on success |
| `format_edge_alert(pair_result: dict) -> str` | Format a bet signal as a markdown message |
| `check_and_alert(pairs: list[dict]) -> int` | Given batch prediction results, send alerts for edge > threshold. Returns count sent. |

**When alerts fire:**
1. After `_pre_race_briefing_job()` runs predictions — any pair with edge > 8% triggers an alert
2. After a manual "Refresh Odds" call in the UI — if the refreshed odds create a new edge, the frontend can optionally call a new `POST /api/pinnacle/alert-if-edge` endpoint

**No new dependencies needed:** Discord webhook dispatch is a plain `requests.post()` call. `requests` is already in `requirements.txt`.

**Configuration:**
- `DISCORD_WEBHOOK_URL` — env var, never committed
- `EDGE_ALERT_THRESHOLD` — env var, default 0.08 (8%)

**Failure handling:** Alert failures are logged as warnings, never raised. The system continues without alerts if the webhook is misconfigured or unreachable.

---

### 5. Model Upgrades: New Feature Types

The v2.0 model work adds three new feature types to the existing `~424-feature` pipeline. All integrate into `features/pipeline.py`.

#### 5a. Market Odds as Feature

**What it adds:** The Pinnacle implied probability for each rider is added as a feature to the model. This gives the model information about what the market already knows — a highly predictive signal in sports with efficient markets.

**Implementation:** New features added to `build_feature_vector_manual()` in `features/pipeline.py`:
```python
# Market signal features (passed via race_params or separate arg)
features["market_implied_prob_a"] = 1.0 / odds_a if odds_a else 0.5
features["market_implied_prob_b"] = 1.0 / odds_b if odds_b else 0.5
features["market_prob_diff"] = features["market_implied_prob_a"] - features["market_implied_prob_b"]
features["market_no_vig_prob_a"] = _compute_no_vig_prob(odds_a, odds_b, side="a") if (odds_a and odds_b) else 0.5
```

**Feature leakage check:** Market odds at bet placement time are pre-race and known before the race starts. This is NOT post-race data — it is permissible. However, training data for historical pairs does NOT have historical Pinnacle odds (no odds history available). This creates a training/serving distribution mismatch.

**Recommended approach:** Train two models — one with market features (for live prediction), one without (baseline). Compare on time-based validation split. Market features should NOT be used in the training set for historical pairs where odds are unavailable. Instead, use them only at inference time as an "override" feature added after the model's base prediction.

**Integration point:** `features/pipeline.py::build_feature_vector_manual()` — `odds_a`/`odds_b` are already passed to `predict_manual()` in `models/predict.py`; they just need to be threaded through to the feature builder.

**Known debt:** `build_feature_vector_manual`, `build_feature_vector`, and `build_feature_matrix` each compute interactions independently (documented in CLAUDE.md). Any new feature group added to one must be added to all three. Track this with a dedicated refactor task before adding market features to avoid the 3-location bug.

#### 5b. Live Startlist Resolution (Field Quality Fix)

**Current state:** `diff_field_rank_quality` is hardcoded to `0.0` in the manual prediction path because startlist data for upcoming races is not fetched at prediction time.

**Fix:** Add startlist fetching to the pre-race report job. When `_pre_race_briefing_job()` fetches stage context, also call `get_race_startlist(race_name)` via the MCP server (available in-session) or `procyclingstats` lib directly. Pass the startlist rider URLs to `build_feature_vector_manual()` so `field_rank_quality` can be computed properly.

**Integration point:** `features/pipeline.py::build_feature_vector_manual()` — takes `race_params` dict. Add a `startlist_urls: list[str]` key to `race_params`. Compute field quality percentile inside the function if startlist is provided, otherwise fall back to neutral 0.5.

#### 5c. DNF Probability Feature

**What it adds:** A pre-computed probability that each rider will not finish the stage, based on historical DNF rates in similar conditions (mountainous stages, stage races vs one-day, fatigue from prior days).

**New file:** `features/dnf_features.py`

| Function | Responsibility |
|----------|---------------|
| `compute_dnf_prob(conn, rider_url, race_params) -> float` | Query historical results for DNF rate in similar stage types |
| `DNF_FEATURE_NAMES: list[str]` | Feature name constants |

**Integration:** Added to `features/pipeline.py::build_feature_vector_manual()` alongside existing rider features. The diff form is `diff_dnf_prob = dnf_prob_a - dnf_prob_b`.

**Data source:** `cache.db::results` — `status` column already captures DNF/DNS/OTL. SQL query filters on similar `profile_icon` and `is_one_day_race` to estimate DNF rate.

---

### 6. Drift Detection

**What it does:** Weekly check of rolling calibration and CLV. Alert if either degrades below threshold.

**New file:** `intelligence/drift.py`

| Function | Responsibility |
|----------|---------------|
| `compute_rolling_calibration(window_bets: int = 100) -> dict` | Load last N settled bets from pnl.py, compute calibration by confidence bucket |
| `compute_rolling_clv(window_bets: int = 100) -> dict` | Average CLV over last N bets, broken down by edge bucket |
| `check_drift(thresholds: dict) -> DriftReport` | Run both checks; return DriftReport with alert flags |

**Thresholds:**
- Calibration: flag if any bin deviates > 5% from expected (was 3% on training set — using 5% for live to account for variance at small N)
- CLV: alert if 30-day rolling CLV drops below 0% (kill signal from PROJECT.md)

**Integration:** Called by `_drift_monitor_job()` in `webapp/scheduler.py`. If drift detected, calls `intelligence/alerts.py::send_discord_alert()`.

---

## Complete Component Map

### New Files

| File | Phase | Purpose |
|------|-------|---------|
| `data/clv.py` | 1 | CLV computation and closing-odds capture |
| `webapp/scheduler.py` | 3 | APScheduler init and job registration |
| `intelligence/reports.py` | 3 | Pre-race report generation |
| `intelligence/alerts.py` | 3 | Discord/email notification dispatch |
| `intelligence/drift.py` | 3 | Rolling calibration + CLV drift detection |
| `features/dnf_features.py` | 2 | DNF probability features |
| `data/reports/` | 3 | Directory for saved JSON reports |

### Modified Files

| File | Change | Risk |
|------|--------|------|
| `data/pnl.py` | Add CLV columns to bets table (idempotent migration), update settle_bet to write CLV | LOW — follows existing migration pattern |
| `webapp/app.py` | Add `init_scheduler()` call, add CLV/report routes, add new blueprint if needed | LOW — additive only |
| `features/pipeline.py` | Add market odds features, DNF features, startlist fix — in ALL THREE locations | MEDIUM — the 3-location duplication is the main risk |
| `features/pipeline.py` | Refactor interaction computation into shared helper before adding new features | MEDIUM — debt resolution before new feature work |
| `models/benchmark.py` | Support optional market-odds feature group; train two model variants | MEDIUM — new training configuration |
| `requirements.txt` | Add `apscheduler>=3.10.0` | LOW — single new dependency |

### Unchanged Files

| File | Why Unchanged |
|------|--------------|
| `data/scraper.py` | Historical scraper is not affected |
| `data/odds.py` | Reused as-is for closing odds capture |
| `data/name_resolver.py` | Reused as-is |
| `intelligence/stage_context.py` | Reused as-is; startlist fetching is separate |
| `models/predict.py` | Inference path unchanged |
| `data/builder.py` | Training pair generation unchanged |

---

## Data Flow: CLV Full Lifecycle

```
T-2h: _pre_race_briefing_job()
  → fetch_cycling_h2h_markets()
  → run predictions for all pairs
  → generate_pre_race_report()
  → check_and_alert() for edge > 8%
  → save report to data/reports/

T=0 (manual): User places bet via UI
  POST /api/pnl/bet
  → place_bet() writes to cache.db::bets
    [new] schedule one-shot closing-odds capture job at race_date + 10:00 UTC

T+0 to T+5min (scheduled):
  capture_all_pending_closing_odds()
  → fetch_cycling_h2h_markets() by matchup_id
  → write closing_odds_a, closing_odds_b, closing_captured_at to bets row

T+4h (estimated race end — hourly job):
  _settlement_job()
  → auto_settle_from_results()   [existing — checks cache.db::results]
    if newly settled and closing_odds present:
      → compute_clv(bet) → write clv to bets row

Weekly: _drift_monitor_job()
  → compute_rolling_clv(100)
  → compute_rolling_calibration(100)
  → check_drift() → send_discord_alert() if flagged
```

---

## Schema Changes

**Table: `bets` (existing in `cache.db`)** — new columns added via idempotent migration:

```sql
-- In data/pnl.py::_create_pnl_tables(), append to migrations list:
("closing_odds_a", "REAL"),
("closing_odds_b", "REAL"),
("closing_captured_at", "TEXT"),
("clv", "REAL"),
("clv_no_vig", "REAL"),   -- no-vig CLV (preferred metric)
```

No other schema changes. No new tables. Reports are stored as JSON files, not in SQLite.

---

## Dependency Graph (Build Order)

```
Phase 1 (CLV foundation — build first, everything else needs it):
  data/clv.py
    ├── data/pnl.py  (add columns)
    └── data/odds.py (reused, unchanged)
  data/pnl.py  (settle_bet CLV write)
  webapp/app.py  (GET /api/pnl/clv-summary)

Phase 2 (Model upgrades — independent of Phase 1 except startlist):
  features/pipeline.py  (refactor 3-location debt FIRST)
  features/dnf_features.py
  features/pipeline.py  (add market odds, DNF, startlist features)
  models/benchmark.py  (two-model training configuration)

Phase 3 (Automation — requires Phase 1):
  webapp/scheduler.py
    ├── data/clv.py  (closing odds capture job)
    └── data/pnl.py  (settlement job)
  intelligence/reports.py
  intelligence/alerts.py
  intelligence/drift.py
  webapp/app.py  (init_scheduler, report routes)
  requirements.txt  (add apscheduler)
```

---

## Recommended Build Order (with justification)

### Step 1 — Schema migration + CLV computation (no scheduler, manual only)

Build `data/clv.py` and extend `data/pnl.py` with schema migration. Add `GET /api/pnl/clv-summary`. At this stage, closing odds are captured manually via a new "Capture Closing Odds" button in the PnL UI — same pattern as the existing manual "Settle" button.

**Why first:** CLV tracking is Phase 1 and the kill/keep decision depends on it. Manual capture is sufficient to start collecting data. The scheduler can be added in Phase 3 once you have a data sample to validate the capture logic.

### Step 2 — Edge-bucket ROI analysis in UI

Extend `GET /api/pnl/summary` to include CLV breakdown by edge bucket (0-5%, 5-8%, 8%+). Add a CLV chart to the P&L page. No new files — extends existing `data/pnl.py` analysis functions.

**Why second:** This is the edge validation signal that determines whether Phase 2 model work is worthwhile.

### Step 3 — Feature pipeline refactor (resolve 3-location debt)

Extract interaction feature computation into a shared `_compute_interactions()` helper in `features/pipeline.py`. This is a prerequisite for adding any new feature groups safely.

**Why third:** Must happen before any model feature work. Touching `features/pipeline.py` without fixing the duplication first will create a 4-location problem.

### Step 4 — Market odds as feature + startlist fix (Phase 2 model work)

Only after Phase 1 CLV data shows positive signal (CLV >= 1.5% over 100+ bets). Add market odds and startlist features. Retrain. Compare against baseline on time-split validation.

### Step 5 — DNF model + team features

Build `features/dnf_features.py`. Add to pipeline. Benchmark. These are independent of Step 4 and can be parallelized if the CLV signal is strong enough to justify both.

### Step 6 — Scheduler + automation (Phase 3)

Add `webapp/scheduler.py` with `apscheduler`. Wire up closing-odds capture and settlement jobs. Add pre-race reports. Add drift monitoring. Add Discord alerts.

**Why last:** All the pieces need to exist before automation adds value. Automation of broken or untested components creates silent failures.

---

## Security and Operational Notes

**Thread safety in scheduled jobs:**
- All jobs run in APScheduler background threads
- Never pass SQLite connection objects across threads — each job calls `get_pnl_db()` independently
- `OMP_NUM_THREADS=1` / `MKL_NUM_THREADS=1` convention must be inherited by scheduler threads if any job calls ML inference — set these in the Flask startup env, not per-thread

**Discord webhook:**
- `DISCORD_WEBHOOK_URL` — env var only, never committed
- Failure to reach Discord is logged as WARNING, never raised — system continues

**Closing odds timing risk:**
- Pinnacle H2H markets for cycling close at race start — sometimes 30-60 min before nominal stage start
- The 10:00 UTC capture window is an approximation; markets may already be closed
- Mitigation: also attempt capture at T-30min (add a second job trigger); log "market closed" status distinctly from "network error"

**APScheduler single-worker requirement:**
- APScheduler 3.x with memory job store works correctly with one Flask worker
- If the VPS is ever configured for multiple gunicorn workers, scheduler must be moved to a separate process or switch to a persistent job store. Document this constraint in CLAUDE.md after implementation.

---

## Confidence Assessment

| Area | Confidence | Basis |
|------|------------|-------|
| CLV schema migration pattern | HIGH | Direct read of `data/pnl.py:71-83` — existing idempotent migration verified |
| `data/odds.py` reuse for closing capture | HIGH | `fetch_cycling_h2h_markets()` already returns `matchup_id` — exact field needed |
| APScheduler in-process pattern | HIGH | Well-documented for Flask, matches no-new-infrastructure constraint |
| 3-location feature duplication risk | HIGH | Confirmed in CLAUDE.md known issues + direct `features/pipeline.py` read |
| Market odds training distribution mismatch | HIGH | Historical pairs have no Pinnacle odds — mismatch is structural, not speculative |
| DNF feature signal | MEDIUM | Historical `status` column in results exists; signal quality unknown until trained |
| Race start time estimation for capture timing | MEDIUM | 10:00 UTC is a reasonable default for European cycling; needs empirical validation |
| Discord webhook reliability | MEDIUM | Standard pattern; Pinnacle's cycling schedule is predictable so failures are low-frequency |
| Drift detection thresholds | LOW | 5% calibration threshold is conservative guess; calibrate against first 100 live bets |

---

*Architecture research: 2026-04-18*
