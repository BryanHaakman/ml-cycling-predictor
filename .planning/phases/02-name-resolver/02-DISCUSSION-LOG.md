# Phase 2: Name Resolver - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-11
**Phase:** 02-name-resolver
**Areas discussed:** Fuzzy search scope, Below-threshold exposure, Manual resolution persistence

---

## Fuzzy Search Scope

| Option | Description | Selected |
|--------|-------------|----------|
| All riders in cache.db | ~20K+ riders, maximum coverage, one SQL query at init | ✓ |
| Recent WT riders only | Riders with results in past 2–3 seasons, faster matches | |
| Riders with WT results ever | Any rider who appeared in a WT race | |

**Follow-up — load strategy:**

| Option | Description | Selected |
|--------|-------------|----------|
| Pre-load into memory | Load all riders at __init__, fast repeated lookups | ✓ |
| Query per call | Hit cache.db on each resolve() | |

**User's choice:** All riders in cache.db, pre-loaded into memory at instantiation.
**Notes:** No follow-up. Moved to next area.

---

## Below-Threshold Exposure

| Option | Description | Selected |
|--------|-------------|----------|
| Rich result with hint | ResolveResult dataclass with best_candidate_url, best_candidate_name, best_score, method | ✓ |
| None only | Return None; Phase 5 shows blank search | |

**Follow-up — lower bound:**

| Option | Description | Selected |
|--------|-------------|----------|
| Suppress below 60 | Score ≥90: auto-accept; 60–89: hint; <60: no candidate | ✓ |
| No lower bound | Always show best candidate regardless of score | |

**User's choice:** Rich ResolveResult with hint, suppressed below score 60.
**Notes:** No follow-up. Moved to next area.

---

## Manual Resolution Persistence

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-save immediately | NameResolver.accept() called by Phase 4 when user confirms; written to name_mappings.json immediately | ✓ |
| Save only on explicit confirmation | Persist only if user clicks "Remember this" toggle | |

**Follow-up — in-memory update:**

| Option | Description | Selected |
|--------|-------------|----------|
| Update in-memory too | Write to disk AND update in-memory dict | ✓ |
| Disk only | Write to disk; next session picks it up | |

**User's choice:** Auto-save immediately, update both in-memory and disk.
**Notes:** No follow-up. Ready to create context.

---
