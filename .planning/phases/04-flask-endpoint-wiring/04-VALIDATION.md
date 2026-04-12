---
phase: 04
slug: flask-endpoint-wiring
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-12
---

# Phase 04 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 |
| **Config file** | none (pytest auto-discovers tests/) |
| **Quick run command** | `pytest tests/test_pinnacle_bp.py -v` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_pinnacle_bp.py -v`
- **After every plan wave:** Run `pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | ODDS-04 | T-04-01 | _require_localhost blocks non-localhost before route logic | unit (RED) | `pytest tests/test_pinnacle_bp.py -v 2>&1 \| head -30` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | ODDS-04 | T-04-02/T-04-03 | /load returns locked schema; auth error returns 401+env_var; no 500 | unit (GREEN) | `pytest tests/test_pinnacle_bp.py -v -k "load"` | ❌ W0 | ⬜ pending |
| 04-01-03 | 01 | 1 | ODDS-04 | T-04-04/T-04-05 | /refresh-odds returns only odds fields; no NameResolver/stage_context | unit (GREEN) | `pytest tests/test_pinnacle_bp.py -v` | ❌ W0 | ⬜ pending |
| 04-01-04 | 01 | 1 | — | — | Schema frozen in docs/; D-08 logged in decision_log.md | file check | `grep -c "Phase 4: Frozen API Response Schemas" docs/pinnacle-api-notes.md && grep -c "diff_field_rank_quality" decision_log.md` | ✅ | ⬜ pending |
| 04-01-05 | 01 | 1 | ODDS-04 | T-04-01 through T-04-08 | Live curl confirms schema matches frozen contract | manual (blocking) | human verification | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_pinnacle_bp.py` — 10 failing tests (RED phase, all ImportError initially)
- [ ] `webapp/auth.py` — _require_localhost extracted before Blueprint is created

*Task 1 covers all Wave 0 requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live /api/pinnacle/load returns valid races[] JSON with correct schema | ODDS-04, SC-1 | Requires live PINNACLE_SESSION_COOKIE and real Pinnacle API | curl -X POST http://127.0.0.1:5001/api/pinnacle/load + compare to frozen schema in docs/pinnacle-api-notes.md |
| /api/pinnacle/refresh-odds returns updated odds (matchup_id stability confirmed) | ODDS-04, SC-2 | Requires two sequential live Pinnacle API calls | Note matchup_ids from /load, call /refresh-odds, confirm same IDs returned with (possibly updated) odds |
| Flask starts without circular import errors | ODDS-04 | Integration concern, not unit-testable | python -c "from webapp.app import app; print('OK')" |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (Tasks 1-4 all have automated verify)
- [x] Wave 0 covers all MISSING references (test_pinnacle_bp.py, webapp/auth.py)
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
