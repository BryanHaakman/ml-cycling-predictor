---
phase: 2
slug: name-resolver
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-11
audited: 2026-04-11
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (already in requirements.txt) |
| **Config file** | none — pytest discovers by convention |
| **Quick run command** | `pytest tests/test_name_resolver.py -v` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_name_resolver.py -v`
- **After every plan wave:** Run `pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 2-01-01 | 01 | 0 | NAME-01..05 | — | N/A | unit | `pytest tests/test_name_resolver.py -v` | ✅ | ✅ green |
| 2-01-02 | 01 | 1 | NAME-01 | — | N/A | unit | `pytest tests/test_name_resolver.py::TestExactMatch::test_resolve_exact_match -x` | ✅ | ✅ green |
| 2-01-03 | 01 | 1 | NAME-02 | — | N/A | unit | `pytest tests/test_name_resolver.py::TestNormalizedMatch::test_normalized_match_must_pass -x` | ✅ | ✅ green |
| 2-01-04 | 01 | 2 | NAME-03 | T-2-01 | Score < 90 returns None not a wrong match | unit | `pytest tests/test_name_resolver.py::TestFuzzyMatch -x` | ✅ | ✅ green |
| 2-01-05 | 01 | 2 | NAME-04 | T-2-02 | Atomic write prevents partial state corruption | unit | `pytest tests/test_name_resolver.py::TestCachePersistence::test_cache_persistence_after_accept -x` | ✅ | ✅ green |
| 2-01-06 | 01 | 2 | NAME-05 | — | N/A | unit | `pytest tests/test_name_resolver.py::TestUnresolvedContract::test_unresolved_result_contract -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_name_resolver.py` — stubs for NAME-01 through NAME-05
- [x] `rapidfuzz>=3.0.0` added to `requirements.txt` (pre-approved in STATE.md)

*Wave 0 creates test infrastructure before any implementation tasks run.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Unresolved pairs visible in log output | NAME-05 | No UI yet (Phase 4/5 will surface these) | Run resolver with an unknown name; verify WARNING log line contains the name |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 10s (16 tests in ~1s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** 2026-04-11 — 16/16 tests green, all requirements covered

---

## Validation Audit 2026-04-11
| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 6 |
| Escalated | 0 |

*Note: VALIDATION.md was pre-written as draft before implementation. Audit updated commands to match actual test class names (TestExactMatch, TestNormalizedMatch, TestCachePersistence, TestFuzzyMatch, TestUnresolvedContract) and marked all tasks green after confirming 16/16 tests pass.*
