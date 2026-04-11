# State

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-04-11 — Milestone v1.0 started

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-11)

**Core value:** Edge detection — surfacing when PaceIQ's win probability differs from Pinnacle's implied odds by enough (>5% flag, >8% act) to justify a bet.
**Current focus:** v1.0 Pinnacle Preload — auto-populate batch prediction UI from live Pinnacle data

## Accumulated Context

- Codebase mapped: see `.planning/codebase/` (ARCHITECTURE.md, CONCERNS.md, CONVENTIONS.md, INTEGRATIONS.md, STACK.md, STRUCTURE.md, TESTING.md)
- Key known issue: `build_feature_vector_manual` silently omits 4 interaction feature groups vs training — silent accuracy bug for live predictions. Deferred to future milestone.
- Pinnacle API endpoint unknown — needs Playwright discovery as Phase 1 of implementation.
- `procyclingstats` lib already in requirements.txt (used by scraper); available for stage context fetch.
