---
phase: 03-stage-context-fetcher
plan: 01
subsystem: intelligence
tags: [tdd, stage-context, procyclingstats, fuzzy-match, timeout]

dependency_graph:
  requires:
    - data/scraper.py (get_db)
    - data/cache.db (races table, year-filtered)
    - rapidfuzz (fuzz.token_sort_ratio, process.extractOne)
    - procyclingstats (Race, Stage)
    - concurrent.futures (ThreadPoolExecutor, TimeoutError)
  provides:
    - intelligence/stage_context.py (StageContext dataclass, fetch_stage_context)
    - intelligence/__init__.py (package marker)
    - tests/test_stage_context.py (18 unit tests)
  affects:
    - Phase 04 Flask endpoints (consume StageContext via fetch_stage_context)

tech_stack:
  added: []
  patterns:
    - TDD: RED stubs -> GREEN parse/resolve -> GREEN PCS fetch wired
    - ThreadPoolExecutor with shutdown(wait=False) for non-blocking timeout
    - rapidfuzz token_sort_ratio at threshold 75 for race name fuzzy matching
    - Parameterized SQL query prevents injection (T-3-01)

key_files:
  created:
    - intelligence/__init__.py
    - intelligence/stage_context.py
    - tests/test_stage_context.py
  modified: []

decisions:
  - "executor.shutdown(wait=False) instead of 'with' context manager — prevents caller blocking when background thread times out"
  - "Race.is_one_day_race() inside _do_fetch (not passed as param) — Race() itself makes network call, must be covered by 5s timeout"
  - "process.extractOne with score_cutoff=75 returns None directly — no need to check score after the fact"

metrics:
  duration_minutes: 25
  completed_date: "2026-04-12"
  tasks_completed: 3
  tasks_total: 3
  files_created: 3
  files_modified: 0
---

# Phase 03 Plan 01: Stage Context Fetcher — Implementation Summary

**One-liner:** TDD implementation of StageContext dataclass and fetch_stage_context() pipeline — Pinnacle race name to PCS stage metadata with 5-second timeout, fuzzy cache.db resolution, and graceful degradation.

## What Was Built

`intelligence/stage_context.py` provides the stage intelligence layer for Phase 4's Flask endpoints. Given a Pinnacle race name string (e.g., "Tour de Romandie - Stage 3"), it:

1. Strips the stage suffix using `PINNACLE_STAGE_SEPARATOR = " - "`
2. Fuzzy-matches the race name against cache.db using `rapidfuzz.fuzz.token_sort_ratio` at threshold 75
3. Fetches Race + Stage details from PCS via `procyclingstats` lib inside a 5-second ThreadPoolExecutor timeout
4. Returns a `StageContext` dataclass populated with all fields that `build_feature_vector_manual` expects as `race_params`

On any failure (no DB match, PCS timeout, exception) returns `StageContext(is_resolved=False)` — never raises.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | RED — Write test file and implementation skeleton | 43006e9 | intelligence/__init__.py, intelligence/stage_context.py, tests/test_stage_context.py |
| 2 | GREEN — Implement race name parsing and cache.db resolution | f3e563c | intelligence/stage_context.py |
| 3 | GREEN — Implement PCS fetch with timeout and wire fetch_stage_context | 82ffb3d | intelligence/stage_context.py |

## Verification

All 18 unit tests pass:

```
tests/test_stage_context.py::TestStageContextDataclass::test_default_values PASSED
tests/test_stage_context.py::TestStageContextDataclass::test_fields_match_race_params_keys PASSED
tests/test_stage_context.py::TestParseRaceName::test_strips_stage_suffix PASSED
tests/test_stage_context.py::TestParseRaceName::test_no_separator_returns_full_name PASSED
tests/test_stage_context.py::TestParseRaceName::test_multiple_separators_splits_on_first PASSED
tests/test_stage_context.py::TestParseRaceName::test_logs_parsed_assumption PASSED
tests/test_stage_context.py::TestResolveRaceUrl::test_fuzzy_match_returns_url PASSED
tests/test_stage_context.py::TestResolveRaceUrl::test_below_threshold_returns_none PASSED
tests/test_stage_context.py::TestResolveRaceUrl::test_no_races_in_db_returns_none PASSED
tests/test_stage_context.py::TestResolveRaceUrl::test_logs_match_score PASSED
tests/test_stage_context.py::TestFetchStageContext::test_resolved_stage_race PASSED
tests/test_stage_context.py::TestFetchStageContext::test_resolved_one_day_race PASSED
tests/test_stage_context.py::TestFetchStageContext::test_is_one_day_uses_race_not_stage PASSED
tests/test_stage_context.py::TestFallbacks::test_unresolved_race_name PASSED
tests/test_stage_context.py::TestFallbacks::test_pcs_race_exception PASSED
tests/test_stage_context.py::TestFallbacks::test_pcs_stage_exception PASSED
tests/test_stage_context.py::TestFallbacks::test_timeout_returns_unresolved PASSED
tests/test_stage_context.py::TestFallbacks::test_no_stage_today PASSED

18 passed in 5.66s
```

Security checks passed:
- No `signal.alarm` / `signal.SIGALRM` (Windows-safe)
- `concurrent.futures.TimeoutError` used specifically (not bare `TimeoutError`)
- `Race.is_one_day_race()` used, never `Stage.is_one_day_race()`
- SQL query uses parameterized binding `WHERE year = ?` (T-3-01 mitigated)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] ThreadPoolExecutor context manager blocks caller on timeout**
- **Found during:** Task 3 test run
- **Issue:** Using `with concurrent.futures.ThreadPoolExecutor() as executor` blocks the caller until the background thread completes even after timeout. Test `test_timeout_returns_unresolved` measured 10s elapsed (not 5s) because the context manager's `__exit__` calls `shutdown(wait=True)`.
- **Fix:** Replaced `with` block with explicit `executor = ThreadPoolExecutor(max_workers=1)` + `finally: executor.shutdown(wait=False)`. The timed-out background thread is abandoned and finishes in the background without blocking the caller.
- **Files modified:** intelligence/stage_context.py
- **Commit:** 82ffb3d

**2. [Rule 2 - Missing critical functionality] Skeleton needed stub function exports for test collection**
- **Found during:** Task 1
- **Issue:** Test file imports `_parse_race_name` and `_resolve_race_url` at module level. The plan's skeleton only defined `fetch_stage_context`. Without stubs for these helpers, `pytest --collect-only` failed with `ImportError`.
- **Fix:** Added stub implementations for `_parse_race_name`, `_resolve_race_url`, `_extract_base_url`, `_do_fetch`, `_fetch_with_timeout` in the skeleton — all raising `NotImplementedError` so RED phase was preserved.
- **Files modified:** intelligence/stage_context.py
- **Commit:** 43006e9

## Known Stubs

None — all functions fully implemented.

## Threat Flags

None — all trust boundaries addressed:
- T-3-01 (SQL injection): parameterized query `WHERE year = ?`
- T-3-02 (DoS via timeout): `executor.shutdown(wait=False)` + 5s timeout
- T-3-03/T-3-04/T-3-05: accepted per threat register

## Self-Check: PASSED

- intelligence/__init__.py: EXISTS
- intelligence/stage_context.py: EXISTS (258 lines, >100 min)
- tests/test_stage_context.py: EXISTS (380 lines, >80 min)
- Commits: 43006e9, f3e563c, 82ffb3d all present in git log
- 18 tests collected and passing
