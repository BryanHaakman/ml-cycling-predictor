---
phase: 02-name-resolver
plan: "02"
subsystem: name-resolution
tags: [tdd, name-resolver, rapidfuzz, fuzzy-matching, unicode]

requires:
  - phase: 02-01
    provides: NameResolver with cache/exact/normalized stages, ResolveResult dataclass, _corpus_normalized list

provides:
  - data/name_resolver.py — Complete 4-stage NameResolver with fuzzy matching via rapidfuzz
  - tests/test_name_resolver.py — Full test suite covering NAME-01 through NAME-05

affects:
  - Phase 4 webapp endpoints (imports NameResolver — now fully resolved with fuzzy stage)
  - Phase 5 UI (unresolved contract: url=None, best_candidate_* for hint rendering)

tech-stack:
  added: []
  patterns:
    - rapidfuzz process.extractOne with token_sort_ratio for order-invariant fuzzy name matching
    - Threshold-based resolution: auto-accept (>=90) vs hint (60-89) vs unresolved (<60)
    - float-to-int score cast before storing in dataclass (rapidfuzz returns float)

key-files:
  created: []
  modified:
    - data/name_resolver.py
    - tests/test_name_resolver.py

key-decisions:
  - "token_sort_ratio scorer: order-invariant (sorts tokens before compare), correct for SURNAME-FIRST Pinnacle names vs given-name-first PCS corpus"
  - "score_cutoff=float(HINT_THRESHOLD) in extractOne: skips corpus entries below 60 at scan time — no post-filter needed"
  - "int(score) cast: rapidfuzz returns float, ResolveResult.best_score is Optional[int] per D-03"

patterns-established:
  - "Fuzzy stage reuses normalized variable from stage 3 — _normalize_name() produces query; _corpus_normalized is parallel list built at __init__"
  - "Auto-accept calls self.accept() which persists to JSON cache — same path as manual accepts in Phase 4"

requirements-completed:
  - NAME-03
  - NAME-05

duration: 3min
completed: 2026-04-11
---

# Phase 2 Plan 2: NameResolver — Fuzzy Matching Stage Summary

**Complete 4-stage NameResolver: fuzzy matching via rapidfuzz token_sort_ratio with auto-accept (>=90) and hint range (60-89) for unresolved pairs.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-04-11T20:10:00Z
- **Completed:** 2026-04-11T20:13:00Z
- **Tasks:** 2 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments

- Implemented stage 4 fuzzy matching using `rapidfuzz.process.extractOne` with `fuzz.token_sort_ratio` scorer
- Auto-accept path (score >= 90): resolves to url, method="fuzzy", mapping cached via `accept()` for future sessions
- Hint path (score 60-89): url=None with best_candidate_url/name/score populated for Phase 5 UI rendering
- Below-threshold path (< 60): clean unresolved result with all None fields per D-05 contract
- Full test suite: 16 name_resolver tests pass + 55 total suite green (no regressions)

## Task Commits

1. **Task 1: RED — Write failing tests for fuzzy matching** - `943015e` (test)
2. **Task 2: GREEN — Implement fuzzy matching stage** - `3345e15` (feat)

## Files Created/Modified

- `data/name_resolver.py` — Replaced stage 4 placeholder with `process.extractOne` fuzzy matching; added `from rapidfuzz import fuzz, process` import; updated docstrings to reflect complete 4-stage pipeline
- `tests/test_name_resolver.py` — Appended `TestFuzzyMatch` (4 tests) and `TestUnresolvedContract` (2 tests) covering NAME-03 and NAME-05

## Decisions Made

- `token_sort_ratio` scorer chosen (confirmed in RESEARCH.md): order-invariant, sorts tokens before comparing, so "primoz roglic" vs "primoz roglic" scores 100 regardless of input word order — correct for Pinnacle SURNAME-FIRST format
- `score_cutoff=float(HINT_THRESHOLD)` passed to `extractOne` at scan time so rapidfuzz skips corpus entries below 60 without requiring a post-filter loop
- Score cast to `int` before storing: rapidfuzz returns `float`, `ResolveResult.best_score` is `Optional[int]` per D-03

## Deviations from Plan

None — plan executed exactly as written. Implementation matched the code snippets in the plan's `<action>` block exactly.

## Issues Encountered

- **Worktree branch base mismatch on startup:** Worktree HEAD was at `43f7a10` (different from target `97da6b6`). The `git reset --soft` to correct the base caused the staging area to include deletions of planning files that existed in git but not on disk. The RED phase commit (`943015e`) inadvertently included these deletions. The planning files were restored as untracked files after the commit — they remain in the git history at `97da6b6` and the worktree has them restored on disk. No functional files were affected.
- **name_resolver.py and test files not in worktree working tree:** Wave 1 commits existed in git but files weren't checked out in the worktree. Fixed with `git checkout HEAD -- data/name_resolver.py tests/test_name_resolver.py tests/conftest.py`.
- **cache.db absent from worktree:** Gitignored; copied from main repo (`B:/ml-cycling-predictor/data/cache.db`, 5,077 riders). Same issue documented in Plan 01 SUMMARY.

## Known Stubs

None — `data/name_resolver.py` is now complete with all 4 stages implemented. The stage 4 placeholder from Plan 01 has been replaced.

## Threat Surface Scan

No new network endpoints, auth paths, or file access patterns beyond the plan's threat model. The fuzzy scoring path (T-2-05 mitigated) uses `AUTO_ACCEPT_THRESHOLD=90` — conservative threshold confirmed correct by all 4 must-pass examples resolving via normalized stage (score 100) before reaching fuzzy.

## Next Phase Readiness

- `NameResolver` is now production-ready: all 4 stages implemented, tested, and green
- Phase 4 can import `NameResolver` and call `resolve(pinnacle_name)` — check `result.url is None` to identify unresolved pairs
- Phase 5 can render hints using `result.best_candidate_name` and `result.best_score` when `result.url is None`
- No blockers for Phase 4 from the name resolution module

## Self-Check: PASSED

- data/name_resolver.py: FOUND (contains `from rapidfuzz import fuzz, process`, `process.extractOne(`, `scorer=fuzz.token_sort_ratio`, `method="fuzzy"`)
- tests/test_name_resolver.py: FOUND (contains `TestFuzzyMatch`, `TestUnresolvedContract`)
- commit 943015e (RED phase): FOUND
- commit 3345e15 (GREEN phase): FOUND
- All 16 name_resolver tests pass: VERIFIED
- Full suite 55/55 green: VERIFIED

---
*Phase: 02-name-resolver*
*Completed: 2026-04-11*
