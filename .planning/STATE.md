---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Phase 04.1 context gathered
last_updated: "2026-04-14T03:24:35.047Z"
last_activity: 2026-04-14
progress:
  total_phases: 6
  completed_phases: 6
  total_plans: 11
  completed_plans: 11
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-11)

**Core value:** Edge detection — surfacing when PaceIQ's win probability differs from Pinnacle's implied odds by enough (>5% flag, >8% act) to justify a bet.
**Current focus:** Phase 04.1 — playwright-session-manager-replace-manual-pinnacle-session-c

## Current Position

Phase: 05
Plan: Not started
Status: Executing Phase 04.1
Last activity: 2026-04-14

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**

- Total plans completed: 2
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
| Phase 04-flask-endpoint-wiring P01 | 45 | 5 tasks | 7 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Pre-roadmap: procyclingstats lib for stage context (not MCP) — self-contained, VPS-safe
- Pre-roadmap: Manual "Load" button trigger, not auto-load on startup — cookie expiry safety
- Pre-roadmap: Separate refresh-odds endpoint — avoid wasteful PCS re-fetch on odds check
- Pre-roadmap: rapidfuzz for name resolution — free, no API key, token_sort_ratio order-invariant
- Pre-roadmap: PINNACLE_SESSION_COOKIE as env var — never committed
- [Phase 04-flask-endpoint-wiring]: _require_localhost extracted to webapp/auth.py to avoid circular import between pinnacle_bp and app.py
- [Phase 04-flask-endpoint-wiring]: Live Pinnacle API: api.arcadia.pinnacle.com (not guest subdomain), X-Session header required, Referer must be pinnacle.ca for Canadian users
- [Phase 04-flask-endpoint-wiring]: diff_field_rank_quality remains neutral 0.0 in Phase 4 — startlist fetch deferred (D-08)

### Roadmap Evolution

- Phase 04.1 inserted after Phase 04: Playwright Session Manager — replace manual PINNACLE_SESSION_COOKIE with automated browser-based session acquisition (URGENT)

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 1 (CRITICAL): Pinnacle internal endpoint URL, headers, sport ID, and response schema are completely unknown until Playwright browser discovery. The entire milestone is at risk if cycling H2H markets do not exist under Pinnacle's taxonomy. Do not write the client until the real endpoint is confirmed.
- Phase 3 (MEDIUM): procyclingstats lib behavior for upcoming (not-yet-completed) races is unverified. A spike is needed to confirm the Stage class works with live race URLs. If it does not, the fallback path (cache.db historical lookup) becomes primary.
- Phase 4 (MEDIUM): build_feature_vector_manual currently has no startlist parameter, causing diff_field_rank_quality (#3 most important feature) to always be neutral via the preload path. Explicit decision required in Phase 4 — fix or document as known gap.

## Session Continuity

Last session: 2026-04-13T19:19:46.962Z
Stopped at: Phase 04.1 context gathered
Resume file: .planning/phases/04.1-playwright-session-manager-replace-manual-pinnacle-session-c/04.1-CONTEXT.md
