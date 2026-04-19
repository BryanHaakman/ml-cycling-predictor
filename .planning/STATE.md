---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Edge Validation & System Maturity
status: ready
stopped_at: Phase 6 complete — advancing to Phase 7
last_updated: "2026-04-19T19:30:00Z"
last_activity: 2026-04-19 -- Phase 6 complete, human verification passed
progress:
  total_phases: 4
  completed_phases: 1
  total_plans: 5
  completed_plans: 5
  percent: 25
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-18)

**Core value:** Edge detection — surfacing when PaceIQ's win probability differs from Pinnacle's implied odds by enough (>5% flag, >8% act) to justify a bet.
**Current focus:** Phase 7 — Edge Analysis & Risk Controls

## Current Position

Phase: 7 of 9 (Edge Analysis & Risk Controls)
Plan: Not yet planned
Status: Ready to discuss
Last activity: 2026-04-19 -- Phase 6 complete

Progress: [██▓░░░░░░░] 25%

## Performance Metrics

**Velocity:**

- Total plans completed: 5
- Average duration: ~6m
- Total execution time: ~17m

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 06 | 5 | ~25m | ~5m |

*Updated after each plan completion*

## Accumulated Context

### From v1.0

- Pinnacle guest API (zero-auth) works reliably — no session management needed
- Name resolver handles most Pinnacle→PCS mappings; edge cases surface in UI for manual resolution
- Interaction features duplicated in 3 places in features/pipeline.py — carried forward as MODEL-01/02
- build_feature_vector_manual silently omits 4 interaction groups (importance-#2 feature) — MODEL-02
- diff_field_rank_quality hardcoded to 0.0 in manual path (importance-#3 feature) — MODEL-03
- Stratified split overestimates live performance by ~1.3% vs time-based split

### From Phase 6

- Pinnacle scraper uses Playwright headless browser (data/pinnacle_scraper.py)
- "The Field" entries skipped in name resolver (not a real rider)
- Bets stored in SQLite bets table (data/bets.csv deprecated)
- Race start times scraped from Pinnacle in EST
- Batch bet submission — user fills in stakes, submits all at once
- Odds editable on pending bets in P&L tracker
- Bankroll adjustable via clickable card on /pnl

### Key Gates

- **Phase 8 CLV gate:** CLV >= +1.5% over 100+ bets → proceed; CLV < 0 over 200 bets → kill Phase 8
- **Gray zone:** CLV 0-1.5% over 100 bets → continue collecting, defer Phase 8

### Blockers/Concerns

- None currently

## Deferred Items

| Category | Item | Status | Rationale |
|----------|------|--------|-----------|
| uat | Phase 04.1: 8 pending scenarios | testing | Self-validates on first live race day use |
| verification | Phase 03: VERIFICATION.md | human_needed | Requires live WT race day with populated cache.db |

## Session Continuity

Last session: 2026-04-19
Stopped at: Phase 6 complete — ready for Phase 7 discussion
Resume file: N/A
