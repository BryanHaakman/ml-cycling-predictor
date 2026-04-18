---
phase: 02-name-resolver
verified: 2026-04-11T20:30:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
gaps: []
gap_fix_note: "rapidfuzz>=3.0.0 restored to requirements.txt in commit 45813a7 — accidentally removed in plan 02-02 worktree"
---

# Phase 2: Name Resolver — Verification Report

**Phase Goal:** A name resolver that maps every Pinnacle display name (SURNAME-FIRST, ALL-CAPS) to a PCS rider URL through a four-stage pipeline, caches accepted mappings persistently, and surfaces unresolved pairs for manual completion
**Verified:** 2026-04-11T20:30:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | NameResolver.resolve() correctly maps Primoz Roglic, Wout van Aert, Romain Bardet, Nairo Quintana from Pinnacle ALL-CAPS format without manual intervention | VERIFIED | All 4 parametrized tests pass; live spot-check: `resolve("ROGLIC PRIMOZ")` returns `url='rider/primoz-roglic'`, `method='normalized'` |
| 2 | A name scoring below 90 returns url=None rather than a wrong match | VERIFIED | `test_fuzzy_hint_range` and `test_fuzzy_no_match` pass; spot-check: `resolve("ZZZZNOTARIDER XXXXX")` returns `url=None, method='unresolved'` |
| 3 | Accepted mappings persist in data/name_mappings.json and are re-used on next instantiation | VERIFIED | `test_cache_persistence_after_accept` and `test_fuzzy_auto_accept_cached` pass; atomic write via `tempfile + os.replace` confirmed in source |
| 4 | name_mappings.json schema is validated on load; invalid entries are logged and skipped | VERIFIED | `test_cache_invalid_entries_skipped` passes; `CACHE_URL_PATTERN = re.compile(r"^rider/[a-z0-9-]+$")` applied in `_load_cache()` |

**ROADMAP Success Criteria check (4 criteria):**

| SC | Criterion | Status |
|----|-----------|--------|
| SC-1 | Resolve Roglic, van Aert, Bardet, Quintana without manual intervention | VERIFIED |
| SC-2 | Score < 90 returns None, not wrong match | VERIFIED |
| SC-3 | Mappings persist to name_mappings.json and re-used on next instantiation | VERIFIED |
| SC-4 | name_mappings.json validated on load; invalid entries logged and skipped | VERIFIED |

All 4 ROADMAP success criteria are satisfied by the implementation. The gap is in the **artifact contract** (requirements.txt must declare the dependency), not in the runtime behavior.

**Score:** 4/4 truths verified — but a critical artifact gap means fresh-clone deploys break.

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `data/name_resolver.py` | NameResolver class with cache/exact/normalized/fuzzy stages | VERIFIED | 287 lines, exports `NameResolver` and `ResolveResult`, imports `get_db`, `unicodedata`, `rapidfuzz`, uses `os.replace` for atomic write |
| `tests/test_name_resolver.py` | Full test suite for NAME-01 through NAME-05 | VERIFIED | 203 lines, 16 tests across 5 classes, all pass |
| `requirements.txt` | Contains rapidfuzz>=3.0.0 | FAILED — MISSING LINE | File ends at `pytest>=7.0.0`; `rapidfuzz` line was added in commit b35666a then removed in commit 943015e (worktree git issue documented in 02-02-SUMMARY.md). Package is installed in local venv; fresh `pip install -r requirements.txt` will fail. |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `data/name_resolver.py` | `data/cache.db` | `get_db()` in `__init__()` | VERIFIED | `from data.scraper import get_db` present; `conn = get_db()` called in `__init__`; 5,077 riders loaded at runtime |
| `data/name_resolver.py` | `data/name_mappings.json` | `_load_cache()` and `_save_cache()` | VERIFIED | `CACHE_PATH` constant references `name_mappings.json`; both methods implemented with full error handling |
| `tests/test_name_resolver.py` | `data/name_resolver.py` | `from data.name_resolver import NameResolver, ResolveResult` | VERIFIED | Import present on line 10; all 16 tests collected and passing |
| `data/name_resolver.py` | `rapidfuzz` | `from rapidfuzz import fuzz, process` | WIRED (runtime) / BROKEN (install) | Import present and works because package is locally installed; `requirements.txt` does not declare the dependency so fresh install breaks the wiring |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `data/name_resolver.py` `resolve()` | `self._corpus` | `SELECT url, name FROM riders` via `get_db()` | Yes — 5,077 rows loaded at runtime | FLOWING |
| `data/name_resolver.py` `resolve()` | `self._cache` | `_load_cache()` from `name_mappings.json` | Yes — file read + regex validation | FLOWING |
| `data/name_resolver.py` fuzzy stage | `fuzzy_result` | `process.extractOne(query, self._corpus_normalized, scorer=fuzz.token_sort_ratio, score_cutoff=60.0)` | Yes — real rapidfuzz scan against normalized corpus | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Pinnacle ALL-CAPS name resolves via normalization | `python -c "from data.name_resolver import NameResolver; r = NameResolver(); print(r.resolve('ROGLIC PRIMOZ'))"` | `ResolveResult(url='rider/primoz-roglic', ..., method='normalized')` | PASS |
| Fuzzy auto-accept path | `python -c "from data.name_resolver import NameResolver; r = NameResolver(); print(r.resolve('ROGLICC PRIMOZ'))"` | `ResolveResult(url='rider/primoz-roglic', ..., method='fuzzy')` | PASS |
| Unresolved path returns clean None | `python -c "from data.name_resolver import NameResolver; r = NameResolver(); print(r.resolve('ZZZZNOTARIDER XXXXX'))"` | `ResolveResult(url=None, ..., method='unresolved')` | PASS |
| Exact match with accented name | `python -c "from data.name_resolver import NameResolver; r = NameResolver(); print(r.resolve('Primož Roglič'))"` | `ResolveResult(url='rider/primoz-roglic', ..., method='exact')` | PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| NAME-01 | 02-01-PLAN.md | Exact match against cache.db riders | SATISFIED | `test_resolve_exact_match` passes; `_name_to_url` dict checked in stage 2 |
| NAME-02 | 02-01-PLAN.md | Unicode normalization + word-order resolution | SATISFIED | 4 parametrized tests pass; `_normalize_name` (with reversal) + `_normalize_pcs_name` (without) |
| NAME-03 | 02-02-PLAN.md | Fuzzy matching with rapidfuzz; auto-accept >= 90 | SATISFIED | `TestFuzzyMatch` all 4 tests pass; `process.extractOne` with `token_sort_ratio` |
| NAME-04 | 02-01-PLAN.md | Persistent cache in name_mappings.json | SATISFIED | `TestCachePersistence` all 4 tests pass; atomic write via `tempfile + os.replace` |
| NAME-05 | 02-02-PLAN.md | Unresolved pairs surface enough info for Phase 5 UI | SATISFIED (Phase 2 contract) | `TestUnresolvedContract` passes; `best_candidate_url/name/score` populated in hint range; UI rendering is Phase 5 scope |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `requirements.txt` | n/a | Missing dependency `rapidfuzz>=3.0.0` | BLOCKER | `pip install -r requirements.txt` on fresh clone → `ModuleNotFoundError` when any code imports `NameResolver`. Works locally only because venv was manually populated. |
| `data/name_resolver.py` | 237 | `accept()` stores unvalidated URLs in `_cache` | WARNING | URLs that fail `CACHE_URL_PATTERN` survive in-memory but are silently dropped on next startup; confirmed mapping can disappear without error (documented in 02-REVIEW.md as WR-01) |
| `data/name_resolver.py` | 284-286 | Orphaned `.tmp` file when `os.replace` fails | WARNING | Accumulates `.tmp` files in `data/` on repeated write failures (documented in 02-REVIEW.md as WR-02) |
| `tests/test_name_resolver.py` | 149, 162 | `test_fuzzy_hint_range` and `test_fuzzy_no_match` use real `name_mappings.json` | WARNING | Tests will flake once production cache grows; consistent with PR review finding WR-03 |

---

### Human Verification Required

None — all phase-2 behaviors are programmatically verifiable. NAME-05 UI rendering is Phase 5 scope.

---

### Gaps Summary

**One gap blocks a clean deployment, though the runtime behavior is fully correct.**

The `rapidfuzz>=3.0.0` line was successfully added to `requirements.txt` in the Plan 01 RED commit (`b35666a`), then accidentally removed in the Plan 02 RED commit (`943015e`) as a documented side effect of a worktree git history issue (the commit inadvertently included deletions — see 02-02-SUMMARY.md "Issues Encountered"). The code, tests, and behavior all work because rapidfuzz is installed locally. The fix is a single-line addition to `requirements.txt`.

The three warnings from the code review (WR-01 accept() validation gap, WR-02 orphaned tmp file, WR-03 non-hermetic tests) are present but do not block the phase goal — they are quality improvements for a follow-up.

---

_Verified: 2026-04-11T20:30:00Z_
_Verifier: Claude (gsd-verifier)_
