# PaceIQ

## What This Is

PaceIQ is a personal cycling H2H betting intelligence system. It scrapes ProCyclingStats race data (2018–2025), engineers ~424 features per matchup, trains a CalibratedXGBoost classifier, and serves win probability predictions with Kelly Criterion staking recommendations through a Flask web app. The user clicks "Load from Pinnacle" to auto-populate today's cycling H2H matchups — odds, rider PCS URLs, and live stage context — then runs predictions and places bets manually on Pinnacle.

## Core Value

Edge detection: surfacing when PaceIQ's win probability differs from Pinnacle's implied odds by enough (>5% flag, >8% act) to justify a bet — with Kelly-sized stakes.

## Current State

Shipped v1.0 (Pinnacle Preload) on 2026-04-15 with ~9,800 LOC Python.

**Tech stack:** Python 3.11, Flask, SQLite, XGBoost, PyTorch, procyclingstats lib, rapidfuzz
**Key components shipped in v1.0:**
- `data/odds.py` — Pinnacle guest API client (zero-auth, H2H markets)
- `data/name_resolver.py` — 3-stage name resolution pipeline with persistent cache
- `intelligence/stage_context.py` — PCS stage context fetcher with 5s timeout
- `webapp/pinnacle_bp.py` — Flask blueprint with `/api/pinnacle/load` and `/refresh-odds`
- Frontend "Load from Pinnacle" + "Refresh Odds" in batch H2H UI

**Known technical debt:**
- Interaction features duplicated in 3 places in `features/pipeline.py`
- `build_feature_vector_manual` silently omits 4 interaction groups (including importance-#2 feature)
- `diff_field_rank_quality` hardcoded to neutral 0.0 in manual path (importance-#3 feature)
- Stratified split overestimates live performance by ~1.3% vs time-based split

## Requirements

### Validated

- ✓ Historical race data scraped from ProCyclingStats (2018–2025) into SQLite — initial scrape
- ✓ H2H pair builder for World Tour races (max_rank=50, 200 pairs/stage, ~292K pairs) — initial scrape
- ✓ ~424-feature engineering pipeline per matchup with parquet caching — feature build
- ✓ CalibratedXGBoost model (69.7% accuracy, 0.772 ROC-AUC) trained on stratified stage split — model training
- ✓ Flask web app (port 5001) with single and batch H2H prediction modes — webapp
- ✓ Kelly Criterion staking recommendations (quarter Kelly, 5% bankroll cap) — webapp
- ✓ P&L tracking and bet logging to bets.csv — webapp
- ✓ Results browser and Elo leaderboard — webapp
- ✓ Pinnacle guest API client fetches today's H2H cycling markets (zero-auth) — v1.0
- ✓ Name resolver maps Pinnacle display names to PCS rider URLs (exact → normalize → fuzzy → cache) — v1.0
- ✓ Unresolved riders surfaced in UI with manual search fallback — v1.0
- ✓ Stage context auto-fetched from PCS via procyclingstats lib — v1.0
- ✓ "Load from Pinnacle" button + race selector auto-populates batch prediction UI — v1.0
- ✓ "Refresh Odds" re-fetches Pinnacle odds without re-pulling stage context — v1.0
- ✓ Odds audit logging to data/odds_log.jsonl — v1.0

### Active

(Defined in REQUIREMENTS.md — v2.0 Edge Validation & System Maturity)

### Out of Scope

- Automated bet placement — permanently manual on Pinnacle
- Multi-user support — personal tool only
- Auto-load on page startup — explicit trigger is safer with session expiry
- Monte Carlo race simulation — backlog (SIM-01); high effort, revisit if H2H edge is proven
- Sequence model (transformer) — backlog (SEQ-01); very high effort vs XGB baseline
- Live in-running markets — backlog (LIVE-01); mid-race data unreliable
- Historical odds backtest — forward CLV tracking chosen over historical odds reconstruction

## Context

- Forked from `lewis-mcgillion/cycling-predictor`. Live data MCP server: `lewis-mcgillion/procyclingstats-mcp-server` (in-session use only; pipeline uses `procyclingstats` lib directly).
- Deployed target: Hostinger VPS (Ubuntu 24.04, 8 GB RAM) — but v1.0 made no VPS changes.
- Pinnacle API: guest.api.arcadia.pinnacle.com (zero-auth guest API, sport ID 45). No session cookie needed after v1.0 guest API pivot.
- `data/cache.db` is SQLite (WAL mode) — do not migrate. `data/bets.csv` is append-only.

## Constraints

- **Tech stack**: Python 3.11, Flask, SQLite — no new infrastructure
- **Dependencies**: Ask before adding to `requirements.txt`
- **Data safety**: `data/bets.csv` is append-only, never modify existing rows; ask before changing any DB schema
- **Thread safety**: OMP_NUM_THREADS=1, MKL_NUM_THREADS=1 on all ML inference paths (macOS deadlock prevention)
- **Security**: `/api/pinnacle/*` endpoints protected by `_require_localhost`
- **Leakage**: All rider features use strictly pre-race data only

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| `procyclingstats` lib for stage context (not MCP) | Self-contained, works on VPS without MCP server dependency | ✓ Good — reliable, no external service needed |
| Manual "Load" button, not auto-load on startup | Cookie can expire; explicit trigger fails gracefully | ✓ Good — clean UX, no surprise failures |
| Separate refresh-odds endpoint | Re-fetching PCS on every odds check is wasteful | ✓ Good — fast odds refresh without stage re-fetch |
| rapidfuzz for name resolution | Free, no API key, fast fuzzy string matching | ✓ Good — handles accents/abbreviations well |
| Guest API pivot (guest.api.arcadia.pinnacle.com) | Playwright session manager experiment failed; guest API is zero-auth | ✓ Good — eliminated auth complexity entirely |
| _require_localhost for API security | No password auth; restrict to localhost only | ⚠️ Revisit — adequate for local use, needs auth for VPS |
| diff_field_rank_quality neutral default | Startlist resolution deferred to v2.0 | — Pending v2.0 MODEL-01 |
| Session cookie as env var | Security — never committed | ✓ Good (superseded by guest API, no cookie needed) |

## Current Milestone: v2.0 Edge Validation & System Maturity

**Goal:** Prove or disprove that PaceIQ has a real betting edge, then — if the edge is real — upgrade the model and automate the daily workflow.

**Validation strategy:** Forward CLV tracking on live bets (no historical backtest). The model's ability to beat Pinnacle's closing line is the primary signal.

### Phase Structure (90 days)

| Phase | Weeks | Focus | Gate |
|-------|-------|-------|------|
| 1. Validate the Edge | 1-3 | CLV tracking, edge-bucket ROI analysis, staking policy lock | CLV >= 1.5% over 100+ bets -> Phase 2 |
| 2. Upgrade the Model | 4-8 | Startlist fix, market odds feature, DNF model, XGBRanker, team features, stage specialization | ROI improvement >= 2pp, no calibration regression |
| 3. Automate & Scale | 9-12 | Closing-odds scraper, auto-settlement, pre-race reports, edge alerts, drift detection, multi-book | < 5 min human effort/day end-to-end |

### Kill / Keep Criteria

- **Kill:** 200 live bets with average CLV < 0 -> stop. No amount of feature engineering fixes a model the market has already priced.
- **Keep:** Backtest + live CLV both positive at >= 1.5% -> invest in Phase 2. Calibration bins within 3% on out-of-sample -> betting math works, focus on signal.
- **Gray zone:** CLV between 0-1.5% over 100 bets -> continue collecting data, defer Phase 2 model upgrades until signal is clearer.

### Priority-Ranked Opportunities (from assessment)

| Priority | Opportunity | Impact | Effort | Phase |
|----------|-------------|--------|--------|-------|
| 1 | CLV tracking + closing-odds capture | 10 | 2 | 1 |
| 2 | Edge-bucket ROI analysis | 8 | 3 | 1 |
| 3 | Staking policy reconciliation | 10 | 1 | 1 |
| 4 | Live startlist resolution (fix field_rank_quality=0.5) | 8 | 3 | 2 |
| 5 | DNF/finish probability model | 8 | 3 | 2 |
| 6 | Market odds as feature | 10 | 2 | 2 |
| 7 | Pairwise ranking (XGBRanker) | 7 | 5 | 2 |
| 8 | Team-strength features | 7 | 5 | 2 |
| 9 | Stage-type specialization (3 models) | 7 | 5 | 2 |
| 10 | Automated settlement + CLV computation | 8 | 3 | 3 |
| 11 | Pre-race report generation | 7 | 4 | 3 |
| 12 | Edge alerting (Discord/email) | 7 | 4 | 3 |
| 13 | Multi-book odds polling | 8 | 8 | 3 |
| 14 | Drift detection + auto-retraining | 7 | 5 | 3 |

### Known Weaknesses (from assessment, to address)

- Stratified split overestimates live performance by ~1.3% — time-based number (~68.5% / 0.755 AUC) is closer to reality
- 26 bets is statistically uninformative (95% CI +/-17% on win rate)
- `simulate_pnl.py` is self-referential (synthetic odds from model probs) — not a real backtest; replace with forward CLV reporting
- Staking docs/code/behavior disagree — must reconcile in Phase 1
- Specialty scores are static PCS numbers, not learned — coarse signal
- No team/tactical features (attempted, reverted for leakage — correct fix is pre-race team roster features)

### Automation Jobs (extracted from assessment agent roster)

| Job | Trigger | What it does |
|-----|---------|-------------|
| Closing-odds capture | Cron at race start time | Snapshot Pinnacle odds, store as closing line |
| Post-race settlement | Cron after race ends | Ingest results, compute CLV, settle bets |
| Pre-race briefing | Cron T-2h before stage | Generate markdown report with picks + confidence |
| Edge alert | Event: odds change with edge > threshold | Discord/email notification |
| Drift monitor | Weekly cron | Rolling calibration + CLV check, alert if degraded |
| Data freshness | Hourly cron | Check scrape_log for gaps, alert on coverage failures |

## Evolution

This document evolves at phase transitions and milestone boundaries.

---
*Last updated: 2026-04-18 after v2.0 milestone start*
