---
phase: "06"
plan: "03"
subsystem: "webapp"
tags: [flask, api, pinnacle, clv, betting, predictions]
dependency_graph:
  requires: [pinnacle-scraper, compute_clv, get_total_bankroll, get_clv_summary, get_clv_by_terrain]
  provides: [pinnacle-load-with-predictions, snapshot-api, closing-snapshot-api, clv-summary-api, clv-terrain-api, total-bankroll-api, filtered-bet-history]
  affects: [webapp/templates/predictions.html, webapp/templates/pnl.html]
tech_stack:
  added: []
  patterns: [lazy-predictor, snapshot-enrichment, parameterized-sql-filters]
key_files:
  created:
    - tests/test_pinnacle_bp.py
  modified:
    - webapp/pinnacle_bp.py
    - webapp/app.py
decisions:
  - "Lazy Predictor pattern in pinnacle_bp.py mirrors webapp/app.py get_predictor()"
  - "Snapshot enrichment updates most recent row via subquery (SQLite has no ORDER BY in UPDATE)"
  - "Added @_require_localhost to auto-settle POST endpoint (was missing, T-06-07)"
  - "predict_manual with empty race_params for /load -- features degrade gracefully when no stage context"
metrics:
  duration: "~4m"
  completed: "2026-04-19T01:57:00Z"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 3
---

# Phase 06 Plan 03: Flask API Layer Rewiring Summary

Rewired pinnacle blueprint to Playwright scraper with model predictions at snapshot time, added CLV/bankroll/terrain API endpoints, enhanced bet history with SQL-level filters.

## Completed Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Rewire pinnacle_bp.py to Playwright scraper with predictions | aa4f47e | webapp/pinnacle_bp.py, tests/test_pinnacle_bp.py |
| 2 | Add CLV and enhanced bet API endpoints to app.py | 80c0eef | webapp/app.py |

## What Was Built

### Task 1: Pinnacle Blueprint Rewiring

**webapp/pinnacle_bp.py** completely rewritten:
- Replaced `data.odds` imports with `data.pinnacle_scraper` (scrape_cycling_markets, save_snapshot, MatchupSnapshot, PinnacleScrapeError)
- Removed `import requests` (no longer needed)
- `/api/pinnacle/load` (POST): scrapes markets, resolves names via NameResolver, runs model predictions via lazy-loaded Predictor, computes quarter-Kelly recommended stakes, returns grouped JSON with model_prob/edge/recommended_stake/should_bet per pair
- `/api/pinnacle/snapshot` (POST, new): scrapes and saves snapshot to market_snapshots table, enriches rows with model predictions
- `/api/pinnacle/snapshot/closing` (POST, new): same as snapshot but with snapshot_type="closing" for CLV-01 closing line capture
- Removed `/api/pinnacle/refresh-odds` (relied on deleted matchup_id concept)
- All routes protected with `@_require_localhost` (T-06-07)

**tests/test_pinnacle_bp.py** created (9 tests):
- TestPinnacleLoad: 4 tests (successful load, scrape error 503, generic error 500, localhost enforcement)
- TestPinnacleSnapshot: 3 tests (save+count, scrape error, localhost enforcement)
- TestPinnacleSnapshotClosing: 2 tests (passes closing type, localhost enforcement)

### Task 2: CLV and Enhanced API Endpoints

**webapp/app.py** modified:
- Added imports: `get_clv_summary`, `get_clv_by_terrain`, `get_total_bankroll`
- `/api/pnl/clv-summary` (GET, new): returns avg_clv, avg_clv_no_vig, ci_low, ci_high, n_bets
- `/api/pnl/clv-by-terrain` (GET, new): returns CLV breakdown by terrain type
- `/api/pnl/total-bankroll` (GET, new): returns cash + pending stakes per D-20
- `/api/pnl/history` (GET, enhanced): added status, race_name, stage_type, date_from, date_to query parameter filters (D-19/BET-03)
- `/api/pnl/bet` (POST, enhanced): added recommended_stake and capture_timestamp to place_bet call (BET-01/D-14)
- `/api/pnl/auto-settle` (POST): added missing `@_require_localhost` decorator (T-06-07)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Security] Added @_require_localhost to auto-settle endpoint**
- **Found during:** Task 2
- **Issue:** The existing `/api/pnl/auto-settle` POST endpoint was missing the `@_require_localhost` decorator, allowing remote triggering of bet settlement
- **Fix:** Added `@_require_localhost` decorator per T-06-07 threat mitigation
- **Files modified:** webapp/app.py
- **Commit:** 80c0eef

**2. [Rule 1 - Bug] Fixed SQLite UPDATE with ORDER BY**
- **Found during:** Task 1
- **Issue:** Initial snapshot enrichment used `UPDATE ... ORDER BY id DESC LIMIT 1` which SQLite does not support
- **Fix:** Changed to subquery pattern: `UPDATE ... WHERE id = (SELECT id ... ORDER BY id DESC LIMIT 1)`
- **Files modified:** webapp/pinnacle_bp.py
- **Commit:** aa4f47e

## Verification

```
pytest tests/test_pinnacle_bp.py -x -v  -- 9 passed
pytest tests/ -x -v                     -- 107 passed (no regressions)
Flask test client GET /api/pnl/clv-summary  -- 200
Flask test client GET /api/pnl/clv-by-terrain -- 200
Flask test client GET /api/pnl/total-bankroll -- 200
```

## Threat Surface Verification

| Threat ID | Mitigation | Verified |
|-----------|-----------|----------|
| T-06-06 (SQL injection in history filters) | All filters passed as parameterized SQL via get_bet_history() | Yes |
| T-06-07 (Remote snapshot triggering) | @_require_localhost on all POST endpoints (load, snapshot, closing, auto-settle) | Yes |

## Self-Check: PASSED

- [x] webapp/pinnacle_bp.py exists
- [x] webapp/app.py exists
- [x] tests/test_pinnacle_bp.py exists (9 tests)
- [x] Commit aa4f47e exists (Task 1)
- [x] Commit 80c0eef exists (Task 2)
- [x] 107 tests pass (no regressions)
