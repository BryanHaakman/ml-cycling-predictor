---
phase: 02-name-resolver
reviewed: 2026-04-11T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - data/name_resolver.py
  - tests/test_name_resolver.py
  - tests/conftest.py
  - requirements.txt
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-04-11
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Reviewed the name resolver implementation (`data/name_resolver.py`), its test suite, shared conftest, and `requirements.txt`. The core resolution pipeline is well-structured: four stages, atomic cache writes via `tempfile + os.replace`, and graceful degradation on missing/corrupt cache. The normalization logic and fuzzy matching integration are correct.

There is one critical defect: `rapidfuzz` is a hard dependency but is absent from `requirements.txt`, causing an import-time crash on any fresh install. Three warnings cover: a write/read inconsistency in `accept()` where unvalidated URLs survive in-memory but are silently dropped on the next process startup; an orphaned temp file left on disk when `os.replace` fails; and two tests that read the live `name_mappings.json` without isolation, making them non-hermetic. Two info items cover: no input guard on `resolve()` for non-string input, and duplicate assertion in the test suite.

---

## Critical Issues

### CR-01: `rapidfuzz` missing from `requirements.txt`

**File:** `requirements.txt:1-14`
**Issue:** `data/name_resolver.py` line 23 imports `from rapidfuzz import fuzz, process`. `rapidfuzz` is not listed in `requirements.txt`. Any environment built from `pip install -r requirements.txt` will raise `ModuleNotFoundError` the first time `NameResolver` is imported. This is a hard runtime crash with no fallback.

**Fix:**
```
rapidfuzz>=3.0.0
```
Add this line to `requirements.txt`. (The project uses `>=`-pinned minimums for all other packages; follow the same convention.)

---

## Warnings

### WR-01: `accept()` writes unvalidated URLs — silent data loss on round-trip

**File:** `data/name_resolver.py:237`
**Issue:** `accept()` stores `pcs_url` directly into `self._cache` without validating it against `CACHE_URL_PATTERN`. The in-memory cache then contains an entry that does not pass the `_load_cache` validator (line 261). When the process restarts, `_load_cache` silently drops that entry and logs a warning. This means a manually confirmed mapping from a Phase 4 UI call can disappear after restart with no error surfaced to the caller.

The asymmetry: `_load_cache` validates on read (line 261), but `accept()` does not validate on write (line 237). `_save_cache` writes whatever is in memory — including invalid entries — so the JSON file is correct, but on next load those entries are stripped.

**Fix:** Add URL validation in `accept()` before storing:
```python
def accept(self, pinnacle_name: str, pcs_url: str) -> None:
    if not CACHE_URL_PATTERN.match(pcs_url):
        raise ValueError(f"accept: invalid PCS URL {pcs_url!r}; must match rider/[a-z0-9-]+")
    self._cache[pinnacle_name] = pcs_url
    self._save_cache()
```
Raising here is preferable to logging-and-continuing because the caller (Phase 4 endpoint) has user-provided input and should receive an immediate error rather than a silent failure at next startup.

---

### WR-02: Orphaned temp file left on disk when `os.replace` fails

**File:** `data/name_resolver.py:284-286`
**Issue:** `_save_cache` uses `delete=False` on the `NamedTemporaryFile` and calls `os.replace(tmp_path, CACHE_PATH)` outside the `with` block but inside the `try`. If `os.replace` raises `OSError` (e.g., permissions error, filesystem boundary on some platforms), the except at line 285 fires and logs a warning — but the temp file at `tmp_path` is never removed. Over repeated failures, `.tmp` files accumulate in `data/`.

**Fix:** Remove the orphaned file in the except handler:
```python
    except OSError as e:
      log.warning("_save_cache: could not write %s: %s", CACHE_PATH, e)
      try:
          os.unlink(tmp_path)
      except OSError:
          pass
```
Note: `tmp_path` may not be defined if the `NamedTemporaryFile` creation itself failed, so the cleanup should only run if `tmp_path` is bound. Alternatively, assign `tmp_path = None` before the `with` block and guard with `if tmp_path:` in the except.

---

### WR-03: Two fuzzy tests read live `name_mappings.json` — non-hermetic

**File:** `tests/test_name_resolver.py:149, 162`
**Issue:** `test_fuzzy_hint_range` (line 149) and `test_fuzzy_no_match` (line 162) construct `NameResolver()` without monkeypatching `CACHE_PATH`. Both tests call `resolver.resolve(...)` and assert `result.method == "unresolved"`. If the real `data/name_mappings.json` already contains a mapping for `"ROGLIC P"` or if a previous test run left one there, `resolve()` returns `method="cache"` and the assertion fails.

The production cache grows over time via `accept()` calls — this test isolation gap will cause intermittent failures in CI once the project accumulates real mappings.

**Fix:** Add the same `monkeypatch` fixture pattern used by every other test in the file:
```python
def test_fuzzy_hint_range(self, tmp_path, monkeypatch):
    cache_file = tmp_path / "name_mappings.json"
    monkeypatch.setattr("data.name_resolver.CACHE_PATH", str(cache_file))
    resolver = NameResolver()
    ...

def test_fuzzy_no_match(self, tmp_path, monkeypatch):
    cache_file = tmp_path / "name_mappings.json"
    monkeypatch.setattr("data.name_resolver.CACHE_PATH", str(cache_file))
    resolver = NameResolver()
    ...
```

---

## Info

### IN-01: `resolve()` has no guard against non-string input

**File:** `data/name_resolver.py:142`
**Issue:** `resolve()` is typed `pinnacle_name: str` but has no runtime check. Passing `None` raises `TypeError` at line 155 (`None in self._cache`). Passing an integer raises `TypeError` in `_normalize_name` at the `unicodedata.normalize` call. For an internal-only class this is acceptable, but the docstring suggests Phase 4/5 callers will pass values from external API responses where the type is not guaranteed.

**Fix:** Add a guard at the top of `resolve()`:
```python
if not isinstance(pinnacle_name, str) or not pinnacle_name.strip():
    return ResolveResult(url=None, best_candidate_url=None,
                         best_candidate_name=None, best_score=None,
                         method="unresolved")
```

---

### IN-02: Duplicate assertion in `test_unresolved_result_contract`

**File:** `tests/test_name_resolver.py:183`
**Issue:** Line 183 asserts `assert result.url is None` which is identical to the assertion on line 182. The duplicate assertion on line 183 carries a comment `# Phase 5 checks: result.url is None` but adds no test coverage. It appears to be a copy-paste artifact.

**Fix:** Remove line 183 or replace it with a distinct assertion (e.g., `assert result.best_candidate_url is None`) to improve test coverage of the unresolved contract.

---

_Reviewed: 2026-04-11_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
