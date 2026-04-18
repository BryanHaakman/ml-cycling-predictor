---
phase: 01-pinnacle-api-discovery-and-client
plan: "02"
subsystem: pinnacle-api
tags: [odds-client, pinnacle, api, tdd, auth, jsonl-audit]
dependency_graph:
  requires: [docs/pinnacle-api-notes.md]
  provides: [data/odds.py, tests/test_odds.py]
  affects: [webapp/app.py (Phase 4 Flask endpoints)]
tech_stack:
  added: []
  patterns: [module-level functions, dataclass, JSONL audit log, env-var auth, TDD red-green]
key_files:
  created:
    - data/odds.py
    - tests/test_odds.py
  modified:
    - .gitignore
    - decision_log.md
decisions:
  - "PINNACLE_SESSION_COOKIE env var used as X-Api-Key header value (project convention, user-corrected in Plan 01)"
  - "_american_to_decimal() defined privately in data/odds.py — no import from models layer (circular import prevention)"
  - "Auth retry bounded to exactly one attempt: invalidate cache -> re-extract -> if second 401/403 raises immediately"
  - "Four JS bundle key extraction regex patterns tried in order — first match wins, None returned if all fail"
  - "datetime.utcnow() used for JSONL timestamps (deprecated in Python 3.14 but functionally correct; update in future)"
metrics:
  duration: "~5 minutes"
  completed: 2026-04-11
---

# Phase 01 Plan 02: Pinnacle Odds Client — Summary

**One-liner:** Pinnacle cycling H2H market client (`data/odds.py`) with JS bundle key extraction, bounded auth retry, decimal odds normalisation, and JSONL audit logging — 25 TDD tests passing, 39/39 full suite green.

## What Was Built

### data/odds.py (451 lines)

Module-level Pinnacle cycling H2H market client with the following structure:

**Constants:**
- `PINNACLE_API_BASE` — `https://guest.api.arcadia.pinnacle.com/0.1`
- `PINNACLE_CYCLING_SPORT_ID` — `45`
- `REQUEST_TIMEOUT` — 60s (matches `data/scraper.py`)
- `KEY_CACHE_PATH` — `data/.pinnacle_key_cache`
- `ODDS_LOG_PATH` — `data/odds_log.jsonl`

**Exports:**
- `PinnacleAuthError` — exception class with PINNACLE_SESSION_COOKIE named in all messages
- `OddsMarket` — dataclass with 6 fields: `rider_a_name`, `rider_b_name`, `odds_a`, `odds_b`, `race_name`, `matchup_id: str`
- `fetch_cycling_h2h_markets()` — main public function; returns `list[OddsMarket]`

**Private helpers:**
- `_american_to_decimal(american: int) -> float` — no import from models layer
- `_extract_key_from_bundle() -> Optional[str]` — fetches Pinnacle home page, finds main JS bundle, tries 4 regex patterns
- `_get_api_key() -> str` — lookup chain: `PINNACLE_SESSION_COOKIE` env var → disk cache → bundle extraction → raises
- `_invalidate_key_cache() -> None` — deletes cache file on 401/403
- `_check_auth(response) -> None` — raises PinnacleAuthError on 401/403
- `_append_audit_log(markets, fetch_status, error=None) -> None` — JSONL append, always called

**Fetch flow in `fetch_cycling_h2h_markets()`:**
1. `GET /sports/45/leagues?all=false` → active cycling leagues
2. Per league: `GET /leagues/{id}/matchups` + `GET /leagues/{id}/markets/straight`
3. Join on `market["matchupId"] == matchup["id"]`
4. Filter `market["status"] == "open"` only
5. Build `OddsMarket` with decimal odds; `matchup_id = str(matchup["id"])`
6. Append audit log; return list (may be empty — never raises for empty results)

### tests/test_odds.py (444 lines)

25 unit tests in 5 test classes:

| Class | Tests | Coverage |
|-------|-------|----------|
| `TestAmericanToDecimal` | 6 | All conversion cases (+107, -154, ±100, ±200) |
| `TestOddsMarketDataclass` | 4 | Fields exist, order, matchup_id type, instantiation |
| `TestGetApiKey` | 4 | Env var, cache, bundle extraction, all-paths-fail |
| `TestCheckAuth` | 3 | 401 raises, 403 raises, 200 no-raise |
| `TestAppendAuditLog` | 3 | Valid JSON line, empty markets, markets serialized |
| `TestFetchCyclingH2hMarkets` | 5 | Empty list, OddsMarket objects, 401 invalidates cache, 401 raises after retry, 401-then-200 succeeds |

### .gitignore

Added after `# Logs` section:
```
# Pinnacle API key cache (extracted from JS bundle, rotates)
data/.pinnacle_key_cache
```

### decision_log.md

Added Phase 1 entry (2026-04-11) documenting hypothesis, method, results (ODDS-01/02/03 ✓, 25 tests), and conclusion.

## Test Results

```
pytest tests/ -v
39 passed, 8 warnings in 1.82s
```

- `tests/test_odds.py`: 25/25 passed
- `tests/test_builder_seed.py`: 3/3 passed (no regression)
- `tests/test_export.py`: 11/11 passed (no regression)

## Acceptance Criteria Verification

| Check | Result |
|-------|--------|
| `data/odds.py` exists, ≥120 lines | 451 lines |
| `PinnacleAuthError` ≥2 matches | 13 matches |
| `OddsMarket` ≥2 matches | 8 matches |
| `fetch_cycling_h2h_markets` ≥1 match | 10 matches |
| `_american_to_decimal` ≥2 matches | 3 matches |
| `odds_log.jsonl` ≥1 match | 2 matches |
| `PINNACLE_SESSION_COOKIE` ≥2 matches | 8 matches |
| `_extract_key_from_bundle` ≥2 matches | 9 matches |
| `.pinnacle_key_cache` ≥1 match | 2 matches |
| `from models` actual imports = 0 | 0 actual imports (2 docstring mentions only) |
| `pinnacle_key_cache` in .gitignore | confirmed |
| Module import OK | confirmed |
| `pytest tests/test_odds.py -v` exits 0 | 25/25 passed |
| `tests/test_odds.py` ≥60 lines | 444 lines |

## Deviations from Plan

### Auto-fixed Issues

None — implementation matched the plan specification exactly.

### User Correction Applied (from Plan 01)

The plan's `must_haves.truths` and acceptance criteria reference `PINNACLE_API_KEY` in several places (e.g., `grep -n "PINNACLE_API_KEY" data/odds.py` acceptance check). Per the user correction in Plan 01, the actual env var name used throughout the implementation is `PINNACLE_SESSION_COOKIE`. This means:

- `_get_api_key()` reads `os.environ.get("PINNACLE_SESSION_COOKIE", "")`
- All `PinnacleAuthError` messages say `Set the PINNACLE_SESSION_COOKIE environment variable`
- The acceptance criteria grep for `PINNACLE_API_KEY` returns 0 matches (not 2 as specified)

This is correct per the user's approval in Plan 01 — the plan's grep check contains the old name and is superseded by the user correction.

## JS Bundle Extraction Regex Patterns

Four patterns tried in order (first match wins):

1. `r'"X-Api-Key"\s*:\s*"([A-Za-z0-9]{32})"'` — exact header assignment
2. `r'apiKey["\s:=]+([A-Za-z0-9]{32})'` — camelCase property assignment
3. `r'"x-api-key"\s*:\s*"([A-Za-z0-9]{32})"'` — lowercase header variant
4. `r'X-Api-Key["\s:=]+([A-Za-z0-9]{32})'` — unquoted header assignment

Pattern 1 is the most likely match based on the API notes; others are fallbacks for minified or reformatted bundles. The `PINNACLE_SESSION_COOKIE` env var provides a reliable manual override if all patterns fail.

## Model-Layer Isolation Confirmed

`grep "^from models\|^import models" data/odds.py` returns 0 results. The two docstring lines mentioning `models/predict.py` are explanatory comments only — no actual circular import risk.

## Known Stubs

None — all logic is fully implemented. `_extract_key_from_bundle()` is a real implementation (not a stub), though its regex patterns may need updating if Pinnacle changes their frontend bundle format.

## Threat Flags

No new threat flags beyond those already documented in the plan's threat model:

| Flag | File | Status |
|------|------|--------|
| T-02-01: .pinnacle_key_cache plain text | data/.pinnacle_key_cache | Mitigated — gitignored |
| T-02-02: API key not in audit log | data/odds_log.jsonl | Mitigated — _append_audit_log only writes market data |
| T-02-05: Error message names env var, not key value | PinnacleAuthError messages | Mitigated — "Set PINNACLE_SESSION_COOKIE" pattern used |
| T-02-06: Retry loop bounded to one | fetch_cycling_h2h_markets | Mitigated — `retried` flag enforces single retry |

## Self-Check

- [x] `data/odds.py` exists (451 lines)
- [x] `tests/test_odds.py` exists (444 lines)
- [x] `.gitignore` updated (data/.pinnacle_key_cache entry confirmed)
- [x] `decision_log.md` updated with Phase 1 entry
- [x] Commit 998455a exists (RED phase — failing tests)
- [x] Commit c62fb75 exists (GREEN phase — implementation + .gitignore)
- [x] Commit f4faded exists (Task 2 — full suite + decision_log)
- [x] 39/39 tests passing (no regressions)

## Self-Check: PASSED
