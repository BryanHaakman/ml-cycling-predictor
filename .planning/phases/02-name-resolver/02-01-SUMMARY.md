---
phase: 02-name-resolver
plan: "01"
subsystem: name-resolution
tags: [tdd, name-resolver, sqlite, unicode, rapidfuzz]
dependency_graph:
  requires:
    - data/scraper.py (get_db)
    - data/cache.db (riders table)
  provides:
    - data/name_resolver.py (NameResolver, ResolveResult)
    - data/name_mappings.json (persistent cache — created on first accept())
  affects:
    - Phase 4 webapp endpoints (will import NameResolver)
tech_stack:
  added:
    - rapidfuzz>=3.0.0
  patterns:
    - NFKD unicode normalization via stdlib unicodedata
    - atomic JSON write via tempfile + os.replace
    - dataclass return type (matches KellyResult/OddsMarket project pattern)
    - two-stage normalization index: separate functions for Pinnacle input vs PCS corpus
key_files:
  created:
    - data/name_resolver.py
    - tests/test_name_resolver.py
    - tests/conftest.py
  modified:
    - requirements.txt
decisions:
  - "Two separate normalize functions: _normalize_name() with word-order reversal for Pinnacle input; _normalize_pcs_name() without reversal for PCS corpus index — avoids incorrect double-reversal of given-name-first PCS names"
  - "Test isolation via monkeypatching CACHE_PATH with tmp_path in TestExactMatch and TestNormalizedMatch — prevents cache contamination between test runs since Stage 3 auto-promotes to cache via accept()"
  - "Worktree uses main repo cache.db (copied) — worktree DB was empty schema; real populated DB (5,077 riders) required for integration tests"
metrics:
  duration: "32 minutes"
  completed: "2026-04-11"
  tasks_completed: 2
  files_created: 3
  files_modified: 1
---

# Phase 2 Plan 1: NameResolver — Cache, Exact, and Normalized Stages Summary

**One-liner:** NameResolver with three-stage pipeline (cache/exact/normalized) using NFKD + word-order reversal to map Pinnacle SURNAME-FIRST ALL-CAPS to PCS rider URLs, persistent JSON cache with regex validation, atomic writes.

## What Was Built

`data/name_resolver.py` implements the core name resolution pipeline for mapping Pinnacle display names (e.g., "ROGLIC PRIMOZ") to PCS rider URLs (e.g., "rider/primoz-roglic").

**NameResolver class:**
- `__init__()`: loads all 5,077 riders from `cache.db` in one query; builds `_name_to_url` dict for exact match, `_normalized_index` dict for normalized match, loads persistent cache
- `resolve(pinnacle_name)`: runs 3 stages — cache O(1), exact O(1), normalized O(1) — returns `ResolveResult` with `url` and `method`
- `accept(pinnacle_name, pcs_url)`: updates in-memory cache and persists atomically to `name_mappings.json`
- `_load_cache()`: handles missing file, corrupt JSON, invalid URL patterns (validates against `rider/[a-z0-9-]+`)
- `_save_cache()`: atomic write via `tempfile.NamedTemporaryFile` + `os.replace`

**Two normalization functions (critical design decision):**
- `_normalize_name(name)`: NFKD + ASCII strip + lowercase + last-word-first reversal — for Pinnacle input "ROGLIC PRIMOZ" → "primoz roglic"
- `_normalize_pcs_name(name)`: NFKD + ASCII strip + lowercase, NO reversal — for PCS corpus "Primož Roglič" → "primoz roglic"

All four must-pass Pinnacle names resolve correctly at Stage 3:

| Pinnacle Input | Normalized Input | PCS Normalized | Match |
|----------------|-----------------|----------------|-------|
| ROGLIC PRIMOZ | primoz roglic | primoz roglic | True |
| VAN AERT WOUT | wout van aert | wout van aert | True |
| BARDET ROMAIN | romain bardet | romain bardet | True |
| QUINTANA NAIRO | nairo quintana | nairo quintana | True |

**Tests:** 10 new tests in `tests/test_name_resolver.py` covering `ResolveResult` fields, exact match, 4 normalized must-pass cases, cache hit, cache persistence after accept(), invalid entry skipping, missing file handling.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 (RED) | b35666a | test(02-01): add failing tests for name resolver — RED phase |
| 2 (GREEN) | a604e36 | feat(02-01): implement NameResolver with cache/exact/normalized stages — GREEN |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree cache.db was empty (0 riders)**
- **Found during:** Task 2 initial test run — all DB-dependent tests failed
- **Issue:** The worktree's `data/cache.db` is excluded by `.gitignore` and was created as an empty schema DB when the worktree was initialized. The main repo has 5,077 riders.
- **Fix:** Copied the populated `data/cache.db` from the main repo (`B:/ml-cycling-predictor/data/cache.db`, 66MB) to the worktree.
- **Files modified:** `data/cache.db` (not committed — gitignored)
- **Note:** Phase 4/5 executor agents will need to do the same if running in a fresh worktree.

**2. [Rule 1 - Bug] Test isolation: Stage 3 normalized match writes to real name_mappings.json**
- **Found during:** Task 2 second test run — ROGLIC PRIMOZ returned `method='cache'` instead of `method='normalized'` because a previous run had written it to the real cache
- **Issue:** `resolve()` calls `accept()` internally when a normalized match is found, persisting the mapping. Subsequent test runs load the real cache and find the entry, returning `method='cache'` which fails the `assert result.method in ("normalized", "exact")` check.
- **Fix:** Added `tmp_path` + `monkeypatch` fixtures to `TestExactMatch.test_resolve_exact_match` and `TestNormalizedMatch.test_normalized_match_must_pass` to isolate each test's cache from the real `data/name_mappings.json`. The plan's exact test code was adapted to include fixture parameters — behavior spec unchanged.
- **Files modified:** `tests/test_name_resolver.py`
- **Commit:** a604e36

## Known Stubs

- **Stage 4 (fuzzy matching):** `resolve()` returns `ResolveResult(url=None, method="unresolved")` when stages 1-3 fail. This is an intentional stub — fuzzy matching via `rapidfuzz.fuzz.token_sort_ratio` is added in Plan 02. Names that don't resolve via exact or normalized match return unresolved. This does NOT prevent Plan 01's goal (stages 1-3 working), but Plan 02 must wire stage 4 before the full pipeline is production-ready.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns beyond what was specified in the plan's threat model. The `name_mappings.json` write path (T-2-01, T-2-02) was mitigated as planned via regex validation and atomic write.

## Self-Check: PASSED

- data/name_resolver.py: FOUND
- tests/test_name_resolver.py: FOUND
- rapidfuzz in requirements.txt: FOUND
- commit b35666a (RED phase): FOUND
- commit a604e36 (GREEN phase): FOUND
- All 49 tests pass (10 new + 39 existing)
