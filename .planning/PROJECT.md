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

- Automated email reports — planned for v1.1 (Daily Intelligence Pipeline milestone)
- Claude API qualitative research — planned for v1.1
- VPS deployment changes — no infrastructure work in this milestone
- Automated bet placement — permanently manual on Pinnacle
- Feature registry refactor — deferred; does not block intelligence layer
- Real-time odds monitoring — once-daily or on-demand is sufficient
- Multi-user support — personal tool only

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
*Last updated: 2026-04-11 — Milestone v1.0 started*
