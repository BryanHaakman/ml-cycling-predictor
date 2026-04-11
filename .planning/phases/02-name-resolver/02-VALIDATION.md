---
phase: 2
slug: name-resolver
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-11
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
| 2-01-01 | 01 | 0 | NAME-01..05 | — | N/A | unit | `pytest tests/test_name_resolver.py -v` | ❌ W0 | ⬜ pending |
| 2-01-02 | 01 | 1 | NAME-01 | — | N/A | unit | `pytest tests/test_name_resolver.py::TestNameResolver::test_exact_match -x` | ❌ W0 | ⬜ pending |
| 2-01-03 | 01 | 1 | NAME-02 | — | N/A | unit | `pytest tests/test_name_resolver.py::TestNameResolver::test_normalized_match_must_pass -x` | ❌ W0 | ⬜ pending |
| 2-01-04 | 01 | 2 | NAME-03 | T-2-01 | Score < 90 returns None not a wrong match | unit | `pytest tests/test_name_resolver.py::TestNameResolver::test_fuzzy_thresholds -x` | ❌ W0 | ⬜ pending |
| 2-01-05 | 01 | 2 | NAME-04 | T-2-02 | Atomic write prevents partial state corruption | unit | `pytest tests/test_name_resolver.py::TestNameResolver::test_cache_persistence -x` | ❌ W0 | ⬜ pending |
| 2-01-06 | 01 | 2 | NAME-05 | — | N/A | unit | `pytest tests/test_name_resolver.py::TestNameResolver::test_unresolved_result_contract -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_name_resolver.py` — stubs for NAME-01 through NAME-05
- [ ] `rapidfuzz>=3.0.0` added to `requirements.txt` (pre-approved in STATE.md)

*Wave 0 creates test infrastructure before any implementation tasks run.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Unresolved pairs visible in log output | NAME-05 | No UI yet (Phase 4/5 will surface these) | Run resolver with an unknown name; verify WARNING log line contains the name |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
