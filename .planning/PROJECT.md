# PaceIQ

## What This Is

PaceIQ is a personal cycling H2H betting intelligence system. It scrapes ProCyclingStats race data (2018–2025), engineers ~424 features per matchup, trains a CalibratedXGBoost classifier, and serves win probability predictions with Kelly Criterion staking recommendations through a Flask web app. The user opens the app, enters a matchup, and gets a model-derived edge signal against Pinnacle's implied odds — then places bets manually.

## Core Value

Edge detection: surfacing when PaceIQ's win probability differs from Pinnacle's implied odds by enough (>5% flag, >8% act) to justify a bet — with Kelly-sized stakes.

## Current Milestone: v1.0 — Pinnacle Preload

**Goal:** Add a "Load from Pinnacle" button to the batch H2H prediction UI that auto-populates today's cycling matchups — odds, rider PCS URLs, and live stage context — so the user selects a race and runs predictions without any manual data entry.

**Target features:**
- Pinnacle internal API discovery + client (session cookie, cycling H2H markets)
- Name resolver: exact → accent-normalized → fuzzy (rapidfuzz) → persistent cache; unresolved pairs shown with manual rider search
- Stage context fetch via `procyclingstats` lib (distance, elevation, climbs, race tier, profile)
- `POST /api/pinnacle/load` and `POST /api/pinnacle/refresh-odds` Flask endpoints
- "Load from Pinnacle" button + race selector + "Refresh Odds" in batch H2H UI; all fields editable before running predictions

## Requirements

### Validated

<!-- Shipped and confirmed valuable — inferred from existing codebase. -->

- ✓ Historical race data scraped from ProCyclingStats (2018–2025) into SQLite — initial scrape
- ✓ H2H pair builder for World Tour races (max_rank=50, 200 pairs/stage, ~292K pairs) — initial scrape
- ✓ ~424-feature engineering pipeline per matchup with parquet caching — feature build
- ✓ CalibratedXGBoost model (69.6% accuracy, 0.770 ROC-AUC) trained on stratified stage split — model training
- ✓ Flask web app (port 5001) with single and batch H2H prediction modes — webapp
- ✓ Kelly Criterion staking recommendations (half Kelly, 10% bankroll cap) — webapp
- ✓ P&L tracking and bet logging to bets.csv — webapp
- ✓ Results browser and Elo leaderboard — webapp

### Active

<!-- v1.0 Pinnacle Preload milestone scope. -->

- [ ] Pinnacle API client fetches today's H2H cycling markets via session cookie
- [ ] Name resolver maps Pinnacle display names to PCS rider URLs (exact → normalize → fuzzy → cache)
- [ ] Unresolved riders surfaced in UI with manual search fallback
- [ ] Stage context auto-fetched from PCS via `procyclingstats` lib
- [ ] "Load from Pinnacle" button + race selector auto-populates batch prediction UI
- [ ] "Refresh Odds" re-fetches Pinnacle odds without re-pulling stage context
- [ ] Expired session cookie shows clear, actionable error message

### Out of Scope

- Automated email reports — deferred to v2.0 Phase 3 (AUTO-03/04)
- Claude API qualitative research — deferred to backlog (INTEL-01); revisit after model upgrades prove value
- VPS deployment changes — no infrastructure work in v1.0
- Automated bet placement — permanently manual on Pinnacle
- Feature registry refactor — deferred; does not block current work
- Real-time odds monitoring — once-daily or on-demand is sufficient for v1.0; continuous polling in v2.0 Phase 3
- Multi-user support — personal tool only
- Monte Carlo race simulation — backlog (SIM-01); high effort, revisit if H2H edge is proven
- Sequence model (transformer) — backlog (SEQ-01); very high effort vs XGB baseline
- Live in-running markets — backlog (LIVE-01); mid-race data unreliable

## Context

- Forked from `lewis-mcgillion/cycling-predictor`. Live data MCP server: `lewis-mcgillion/procyclingstats-mcp-server` (in-session use only; pipeline uses `procyclingstats` lib directly).
- Deployed target: Hostinger VPS (Ubuntu 24.04, 8 GB RAM) — but v1.0 makes no VPS changes.
- Pinnacle API: internal endpoint called by their web frontend, authenticated via session cookie stored as env var `PINNACLE_SESSION_COOKIE`. Endpoint needs to be discovered via Playwright browser inspection — this is in scope for v1.0.
- Known technical debt: interaction features duplicated across 3 functions in `features/pipeline.py`; `build_feature_vector_manual` silently omits 4 interaction groups (including the #2 most important feature). Not addressed in this milestone.
- `data/cache.db` is SQLite (WAL mode) — do not migrate. `data/bets.csv` is append-only.

## Constraints

- **Tech stack**: Python 3.11, Flask, SQLite — no new infrastructure
- **Dependencies**: Ask before adding to `requirements.txt`; `rapidfuzz` is pre-approved from the plan
- **Data safety**: `data/bets.csv` is append-only, never modify existing rows; ask before changing any DB schema
- **Thread safety**: OMP_NUM_THREADS=1, MKL_NUM_THREADS=1 on all ML inference paths (macOS deadlock prevention)
- **Security**: `/api/pinnacle/load` and `/api/pinnacle/refresh-odds` protected by `_require_localhost` (session cookie must not be exposed externally)
- **Leakage**: All rider features use strictly pre-race data only

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| `procyclingstats` lib for stage context (not MCP) | Self-contained, works on VPS without MCP server dependency | — Pending |
| Manual "Load" button, not auto-load on startup | Cookie can expire; explicit trigger fails gracefully; user may be reviewing historical data | — Pending |
| Odds-only refresh endpoint separate from full load | Re-fetching PCS on every odds check is wasteful; stage context doesn't change intraday | — Pending |
| rapidfuzz for name resolution | Free, no API key, fast fuzzy string matching; sufficient for accent/abbreviation variants | — Pending |
| Session cookie stored as env var, never committed | Security; cookie expires regularly and must be manually refreshed | ✓ Good |

## Next Milestone: v2.0 — Edge Validation & System Maturity

**Goal:** Prove or disprove that PaceIQ has a real betting edge, then — if the edge is real — upgrade the model and automate the daily workflow.

**Prerequisite:** v1.0 (Phase 5: Frontend Integration) must be completed first.

**Validation strategy:** Forward CLV tracking on live bets (no historical backtest). The model's ability to beat Pinnacle's closing line is the primary signal.

### Phase Structure (90 days)

| Phase | Weeks | Focus | Gate |
|-------|-------|-------|------|
| 1. Validate the Edge | 1-3 | CLV tracking, edge-bucket ROI analysis, staking policy lock | CLV >= 1.5% over 100+ bets → Phase 2 |
| 2. Upgrade the Model | 4-8 | Startlist fix, market odds feature, DNF model, XGBRanker, team features, stage specialization | ROI improvement >= 2pp, no calibration regression |
| 3. Automate & Scale | 9-12 | Closing-odds scraper, auto-settlement, pre-race reports, edge alerts, drift detection, multi-book | < 5 min human effort/day end-to-end |

### Kill / Keep Criteria

- **Kill:** 200 live bets with average CLV < 0 → stop. No amount of feature engineering fixes a model the market has already priced.
- **Keep:** Backtest + live CLV both positive at >= 1.5% → invest in Phase 2. Calibration bins within 3% on out-of-sample → betting math works, focus on signal.
- **Gray zone:** CLV between 0-1.5% over 100 bets → continue collecting data, defer Phase 2 model upgrades until signal is clearer.

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
- 26 bets is statistically uninformative (95% CI ±17% on win rate)
- `simulate_pnl.py` is self-referential (synthetic odds from model probs) — not a real backtest; replace with forward CLV reporting
- Staking docs/code/behavior disagree — must reconcile in Phase 1
- Specialty scores are static PCS numbers, not learned — coarse signal
- No team/tactical features (attempted, reverted for leakage — correct fix is pre-race team roster features)

### Automation Jobs (extracted from assessment agent roster)

These are the *jobs* to automate as scripts/crons, not a multi-agent architecture:

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

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-14 — Phase 04.1 complete: guest API pivot, zero-auth odds client via guest.api.arcadia.pinnacle.com*
