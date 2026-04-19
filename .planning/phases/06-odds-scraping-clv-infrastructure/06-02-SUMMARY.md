---
phase: "06"
plan: "02"
subsystem: "data/pnl"
tags: [clv, betting, schema-migration, bootstrap-ci, settlement]
dependency_graph:
  requires: []
  provides: [compute_clv, clv_confidence_interval, get_total_bankroll, get_clv_summary, get_clv_by_terrain]
  affects: [data/pnl.py, tests/test_clv.py]
tech_stack:
  added: []
  patterns: [multiplicative-vig-removal, bootstrap-bca-ci, idempotent-migration, parameterized-sql-filters]
key_files:
  created:
    - tests/test_clv.py
  modified:
    - data/pnl.py
decisions:
  - "D-16 implemented as multiplicative vig removal (equal-margin method for H2H)"
  - "D-20 bankroll = cash + pending stakes via get_total_bankroll()"
  - "D-15 CLV computed atomically inside settle_bet() before conn.commit()"
  - "D-19 bet history filters use parameterized SQL WHERE clauses"
metrics:
  duration: "4m42s"
  completed: "2026-04-19T01:47:14Z"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 2
---

# Phase 06 Plan 02: CLV Computation & P&L Data Layer Summary

CLV computation with multiplicative vig removal, atomic settlement integration, bootstrap CI, total bankroll (cash+pending), SQL-filtered bet history, and terrain CLV breakdown -- all in data/pnl.py with 22 passing tests.

## Completed Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing tests for all CLV functions | 9e70aa1 | tests/test_clv.py |
| 1 (GREEN) | Implement CLV schema, functions, settlement integration | f838dd9 | data/pnl.py |

## What Was Built

### Schema Migration (D-13, D-14)
- 5 new columns on `bets` table: `closing_odds_a`, `closing_odds_b`, `clv`, `clv_no_vig`, `recommended_stake`
- `market_snapshots` table created in `_create_pnl_tables()` for test isolation (CREATE IF NOT EXISTS -- no conflict with plan 01)
- 3 indexes on market_snapshots (captured_at, race_name, rider pair)

### New Functions
- `compute_clv(bet_odds, closing_odds_a, closing_odds_b, selection)` -- raw CLV + vig-free CLV using multiplicative method
- `clv_confidence_interval(clv_values, confidence)` -- scipy.stats.bootstrap BCa, 10000 resamples, returns (0,0) for n<5
- `get_total_bankroll(db_path)` -- cash balance + pending stakes (D-20)
- `get_clv_summary(db_path)` -- avg_clv, avg_clv_no_vig, ci_low, ci_high, n_bets
- `get_clv_by_terrain(db_path)` -- groups by profile_type_label, per-terrain CLV + CI

### Modified Functions
- `place_bet()` -- new `recommended_stake` and `capture_timestamp` params
- `settle_bet()` -- atomic CLV: looks up closing odds from market_snapshots, computes CLV, writes in same transaction
- `get_bet_history()` -- SQL-level filters: status, race_name, stage_type, date_from, date_to (parameterized queries)

### Tests (22 passing)
- TestSchemaMigration: 3 tests (columns, idempotency, market_snapshots table)
- TestComputeClv: 4 tests (selection A/B, vig-free differs, negative CLV)
- TestClvConfidenceInterval: 3 tests (tuple return, <5 zeros, exactly 5)
- TestGetTotalBankroll: 2 tests (cash+pending, empty=0)
- TestPlaceBetRecommendedStake: 1 test
- TestSettleBetWithClv: 2 tests (populated, correct values)
- TestSettleBetWithoutClosingOdds: 1 test (NULL CLV, still settles)
- TestGetBetHistory: 4 tests (status, race_name, stage_type, no filter)
- TestGetClvSummary: 1 test
- TestGetClvByTerrain: 1 test

## Deviations from Plan

None -- plan executed exactly as written.

## Decisions Made

1. **Multiplicative vig removal (D-16):** Equal-margin method normalizes closing implied probabilities to sum=1. Standard for H2H markets where both sides are similarly priced.
2. **Bootstrap CI threshold:** 5-value minimum for BCa bootstrap. Below this, returns (0.0, 0.0) to avoid degenerate distributions.
3. **Closing odds lookup in settle_bet:** Queries market_snapshots WHERE snapshot_type='closing' ORDER BY captured_at DESC LIMIT 1. Falls back gracefully with log.warning when no closing odds exist.

## Verification

```
pytest tests/test_clv.py -x -v  -- 22 passed
pytest tests/ -v                -- 146 passed (no regressions)
python -c "from data.pnl import compute_clv, get_total_bankroll, get_clv_summary, get_clv_by_terrain; print('imports OK')"  -- OK
```

## Self-Check: PASSED

- [x] data/pnl.py exists and contains all new functions
- [x] tests/test_clv.py exists with 22 tests
- [x] Commit 9e70aa1 exists (RED)
- [x] Commit f838dd9 exists (GREEN)
- [x] All 146 tests pass
