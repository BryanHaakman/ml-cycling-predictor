---
phase: 3
slug: stage-context-fetcher
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-12
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (existing in project) |
| **Config file** | none — tests discovered via `tests/` directory |
| **Quick run command** | `pytest tests/test_stage_context.py -x` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~10 seconds (unit); ~30 seconds (with live integration) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_stage_context.py -x`
- **After every plan wave:** Run `pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds (unit); 30 seconds (live integration)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 3-01-01 | 01 | 0 | STGE-01 | — | N/A | wave0 | `pytest tests/test_stage_context.py --collect-only` | ❌ W0 | ⬜ pending |
| 3-01-02 | 01 | 1 | STGE-01 | — | N/A | unit | `pytest tests/test_stage_context.py::TestStageContextDataclass -x` | ❌ W0 | ⬜ pending |
| 3-01-03 | 01 | 1 | STGE-01 | — | N/A | unit | `pytest tests/test_stage_context.py::TestFetchStageContext::test_resolved -x` | ❌ W0 | ⬜ pending |
| 3-01-04 | 01 | 1 | STGE-01 | — | N/A | unit | `pytest tests/test_stage_context.py::TestIsOneDayRaceSource -x` | ❌ W0 | ⬜ pending |
| 3-01-05 | 01 | 1 | STGE-01 | — | N/A | unit | `pytest tests/test_stage_context.py::TestStageContextFields -x` | ❌ W0 | ⬜ pending |
| 3-01-06 | 01 | 2 | STGE-02 | — | N/A | unit | `pytest tests/test_stage_context.py::TestFallbacks::test_unresolved_race -x` | ❌ W0 | ⬜ pending |
| 3-01-07 | 01 | 2 | STGE-02 | — | N/A | unit | `pytest tests/test_stage_context.py::TestFallbacks::test_pcs_exception -x` | ❌ W0 | ⬜ pending |
| 3-01-08 | 01 | 2 | STGE-02 | — | N/A | unit | `pytest tests/test_stage_context.py::TestFallbacks::test_timeout -x` | ❌ W0 | ⬜ pending |
| 3-02-01 | 02 | 3 | STGE-01+02 | — | N/A | integration | `pytest tests/test_stage_context.py::TestLiveIntegration -v -s` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_stage_context.py` — test stubs for STGE-01, STGE-02 (all test classes and methods must be importable; bodies use `pytest.skip` until implementation exists)
- [ ] `intelligence/__init__.py` — empty package marker
- [ ] `intelligence/stage_context.py` — module with `StageContext` dataclass and `fetch_stage_context` stub (raises `NotImplementedError`)

*Wave 0 creates the test file and package skeleton so every subsequent task can run `pytest tests/test_stage_context.py -x` immediately.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live integration against real upcoming race | STGE-01 SC-1 | Requires live PCS network access and a race starting today or within ±1 day | Run `pytest tests/test_stage_context.py::TestLiveIntegration -v -s` — must pass on a day when a WT race is active |
| Pinnacle name format compatibility | STGE-01 | Pinnacle race name format unknown until Phase 1 completes | After Phase 1, test `fetch_stage_context("ACTUAL_PINNACLE_RACE_NAME")` and confirm `is_resolved=True` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
