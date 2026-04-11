---
phase: 1
slug: pinnacle-api-discovery-and-client
status: verified
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-11
audited: 2026-04-11
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 |
| **Config file** | none (rootdir auto-detected as B:/ml-cycling-predictor) |
| **Quick run command** | `.venv/Scripts/python.exe -m pytest tests/test_odds.py -v` |
| **Full suite command** | `.venv/Scripts/python.exe -m pytest tests/ -v` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/Scripts/python.exe -m pytest tests/test_odds.py -v`
- **After every plan wave:** Run `.venv/Scripts/python.exe -m pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green (14 existing + new odds tests)
- **Max feedback latency:** ~10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-T1 | 01-01 | 1 | — | T-01-02 | `docs/pinnacle-api-notes.md` contains no actual API key value | manual | `grep -c "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R" docs/pinnacle-api-notes.md` should return `0` | ✅ exists | ✅ green |
| 01-01-T2 | 01-01 | 1 | — | — | User approves notes before code is written | checkpoint | `cat .planning/phases/01-pinnacle-api-discovery-and-client/01-01-SUMMARY.md` contains "approved" | ✅ exists | ✅ green |
| 01-02-T1 | 01-02 | 2 | ODDS-01, ODDS-02, ODDS-03 | T-02-01 to T-02-06 | All unit tests green | unit | `.venv/Scripts/python.exe -m pytest tests/test_odds.py -v` | ✅ exists | ✅ green |
| 01-02-T2 | 01-02 | 2 | ODDS-01, ODDS-02, ODDS-03 | — | Full suite still green after integration | integration | `.venv/Scripts/python.exe -m pytest tests/ -v` | ✅ exists | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_odds.py` — unit tests covering ODDS-01, ODDS-02, ODDS-03 (created by Plan 02 Task 1 TDD)
- [x] `docs/` directory — must be created before `docs/pinnacle-api-notes.md` (created by Plan 01 Task 1)
- [x] `data/odds.py` — new module (created by Plan 02 Task 1)
- [x] `data/.pinnacle_key_cache` — gitignored key cache (excluded from repo via .gitignore)

---

## Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command |
|--------|----------|-----------|-------------------|
| ODDS-01 | `fetch_cycling_h2h_markets()` with valid key returns list of OddsMarket with decimal odds | unit (mock HTTP) | `.venv/Scripts/python.exe -m pytest tests/test_odds.py::TestFetchCyclingH2hMarkets::test_returns_odds_market_objects -x` |
| ODDS-02 | Every fetch appends parseable JSON line to `data/odds_log.jsonl` | unit (tmp_path) | `.venv/Scripts/python.exe -m pytest tests/test_odds.py::TestAppendAuditLog::test_writes_valid_json_line -x` |
| ODDS-02 | Empty fetch appends JSONL line with `"markets": []` | unit (tmp_path) | `.venv/Scripts/python.exe -m pytest tests/test_odds.py::TestAppendAuditLog::test_empty_markets_writes_empty_list -x` |
| ODDS-03 | All key paths exhausted raises PinnacleAuthError naming PINNACLE_SESSION_COOKIE | unit | `.venv/Scripts/python.exe -m pytest tests/test_odds.py::TestGetApiKey::test_raises_pinnacle_auth_error_when_all_paths_fail -x` |
| ODDS-03 | HTTP 401 → invalidate cache → retry → second 401 → raises PinnacleAuthError | unit (mock HTTP) | `.venv/Scripts/python.exe -m pytest tests/test_odds.py::TestFetchCyclingH2hMarkets::test_auth_401_raises_after_one_retry -x` |
| ODDS-03 | HTTP 401 → retry → 200 → returns markets (bounded retry success path) | unit (mock HTTP) | `.venv/Scripts/python.exe -m pytest tests/test_odds.py::TestFetchCyclingH2hMarkets::test_auth_401_then_200_succeeds -x` |

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `docs/pinnacle-api-notes.md` contains accurate live endpoint data | D-03 | Requires human review of content quality | Read the file; confirm endpoint URL, X-Api-Key header, sport ID 45, example response are all present |
| JS bundle extraction works with live Pinnacle site | D-13 | Requires live network access | Run `python -c "from data.odds import _extract_key_from_bundle; print(_extract_key_from_bundle())"` and confirm non-empty string returned |

---

## Validation Audit 2026-04-11

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |
| Tests passing | 25/25 (test_odds.py), 39/39 (full suite) |
| nyquist_compliant | true |
