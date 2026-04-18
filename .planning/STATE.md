---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Edge Validation & System Maturity
status: active
stopped_at: Defining requirements
last_updated: "2026-04-18"
last_activity: 2026-04-18
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-18)

**Core value:** Edge detection — surfacing when PaceIQ's win probability differs from Pinnacle's implied odds by enough (>5% flag, >8% act) to justify a bet.
**Current focus:** Defining requirements for v2.0

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-04-18 — Milestone v2.0 started

## Accumulated Context

### From v1.0

- Pinnacle guest API (zero-auth) works reliably — no session management needed
- Name resolver handles most Pinnacle→PCS mappings; edge cases surface in UI for manual resolution
- Stage context fetcher has 5s timeout with graceful degradation
- Interaction features duplicated in 3 places — technical debt carried forward
- `build_feature_vector_manual` silently omits 4 interaction groups (importance-#2 feature)
- `diff_field_rank_quality` hardcoded to neutral 0.0 in manual path (importance-#3 feature)
- Stratified split overestimates live performance by ~1.3% vs time-based split

### Deferred Items from v1.0

| Category | Item | Status | Rationale |
|----------|------|--------|-----------|
| uat | Phase 04.1: 8 pending scenarios | testing | Will self-validate on first real use during a live race day |
| verification | Phase 03: VERIFICATION.md | human_needed | Timing constraint — full pipeline test requires a live WT race day with cache.db populated |

## Session Continuity

Last session: 2026-04-18
Stopped at: Defining requirements for v2.0
