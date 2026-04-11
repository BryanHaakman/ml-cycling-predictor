# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-11)

**Core value:** Edge detection — surfacing when PaceIQ's win probability differs from Pinnacle's implied odds by enough (>5% flag, >8% act) to justify a bet.
**Current focus:** v1.0 Pinnacle Preload — Phase 1 ready to plan

## Current Position

Phase: 1 of 5 (Pinnacle API Discovery and Client)
Plan: — of — in current phase
Status: Ready to plan
Last activity: 2026-04-11 — Roadmap created, Phase 1 ready to plan

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**
- Last 5 plans: —
- Trend: —

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Pre-roadmap: procyclingstats lib for stage context (not MCP) — self-contained, VPS-safe
- Pre-roadmap: Manual "Load" button trigger, not auto-load on startup — cookie expiry safety
- Pre-roadmap: Separate refresh-odds endpoint — avoid wasteful PCS re-fetch on odds check
- Pre-roadmap: rapidfuzz for name resolution — free, no API key, token_sort_ratio order-invariant
- Pre-roadmap: PINNACLE_SESSION_COOKIE as env var — never committed

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 1 (CRITICAL): Pinnacle internal endpoint URL, headers, sport ID, and response schema are completely unknown until Playwright browser discovery. The entire milestone is at risk if cycling H2H markets do not exist under Pinnacle's taxonomy. Do not write the client until the real endpoint is confirmed.
- Phase 3 (MEDIUM): procyclingstats lib behavior for upcoming (not-yet-completed) races is unverified. A spike is needed to confirm the Stage class works with live race URLs. If it does not, the fallback path (cache.db historical lookup) becomes primary.
- Phase 4 (MEDIUM): build_feature_vector_manual currently has no startlist parameter, causing diff_field_rank_quality (#3 most important feature) to always be neutral via the preload path. Explicit decision required in Phase 4 — fix or document as known gap.

## Session Continuity

Last session: 2026-04-11
Stopped at: Roadmap created — Phase 1 not yet planned
Resume file: None
