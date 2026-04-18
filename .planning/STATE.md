---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Edge Validation & System Maturity
status: active
stopped_at: Roadmap created — ready to plan Phase 6
last_updated: "2026-04-18"
last_activity: 2026-04-18
progress:
  total_phases: 4
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-18)

**Core value:** Edge detection — surfacing when PaceIQ's win probability differs from Pinnacle's implied odds by enough (>5% flag, >8% act) to justify a bet.
**Current focus:** Phase 6 — Odds Scraping & CLV Infrastructure

## Current Position

Phase: 6 of 9 (Odds Scraping & CLV Infrastructure)
Plan: —
Status: Ready to plan
Last activity: 2026-04-18 — Roadmap created for v2.0

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: —
- Total execution time: —

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

*Updated after each plan completion*

## Accumulated Context

### From v1.0

- Pinnacle guest API (zero-auth) works reliably — no session management needed
- Name resolver handles most Pinnacle→PCS mappings; edge cases surface in UI for manual resolution
- Interaction features duplicated in 3 places in features/pipeline.py — carried forward as MODEL-01/02
- build_feature_vector_manual silently omits 4 interaction groups (importance-#2 feature) — MODEL-02
- diff_field_rank_quality hardcoded to 0.0 in manual path (importance-#3 feature) — MODEL-03
- Stratified split overestimates live performance by ~1.3% vs time-based split

### Key Gates

- **Phase 8 CLV gate:** CLV >= +1.5% over 100+ bets → proceed; CLV < 0 over 200 bets → kill Phase 8
- **Gray zone:** CLV 0-1.5% over 100 bets → continue collecting, defer Phase 8

### Blockers/Concerns

- Pinnacle guest API (data/odds.py) is broken — Phase 6 must rebuild scraper via BeautifulSoup first
- data/bets.csv vs bets table divergence: confirm which is authoritative before Phase 9 automation
- Race start timezone resolution needs empirical validation (10:00 UTC default is an approximation)

## Deferred Items

| Category | Item | Status | Rationale |
|----------|------|--------|-----------|
| uat | Phase 04.1: 8 pending scenarios | testing | Self-validates on first live race day use |
| verification | Phase 03: VERIFICATION.md | human_needed | Requires live WT race day with populated cache.db |

## Session Continuity

Last session: 2026-04-18
Stopped at: Roadmap created — 4 phases defined (6-9), 34/34 requirements mapped
Resume file: None
