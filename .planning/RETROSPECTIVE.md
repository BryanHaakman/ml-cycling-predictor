# Retrospective

## Milestone: v1.0 — Pinnacle Preload

**Shipped:** 2026-04-15
**Phases:** 6 | **Plans:** 11
**Timeline:** 5 days (2026-04-11 to 2026-04-15)
**Commits:** ~97

### What Was Built
- Pinnacle guest API client — zero-auth H2H market fetch with audit logging
- 3-stage name resolver — Pinnacle ALL-CAPS to PCS rider URLs with persistent cache
- Stage context fetcher — Pinnacle race name to PCS metadata with 5s timeout and graceful degradation
- Flask endpoints — POST /api/pinnacle/load and /refresh-odds with frozen JSON schema
- Frontend — "Load from Pinnacle" button, race picker, auto-populated pairs, "Refresh Odds" with dirty tracking

### What Worked
- **TDD approach** paid off heavily — phases 1-3 each had comprehensive test suites that caught regressions during the guest API pivot
- **Strict build order** (API discovery → resolver/context → endpoints → frontend) eliminated integration surprises — Phase 4 wired everything together cleanly
- **Frozen JSON schema** before frontend work (documented in docs/pinnacle-api-notes.md) meant Phase 5 coded against a stable contract
- **Quick pivot on Phase 04.1** — recognized Playwright session manager was a dead end within hours, reverted cleanly and shipped guest API same day

### What Was Inefficient
- **Playwright experiment** (Phase 04.1 original plan) was a wasted cycle — investigating the guest API endpoint earlier would have saved the detour
- **Milestone audit ran too early** (2026-04-11) before most phases were complete — produced a stale `gaps_found` status that was misleading at close time
- **UAT never completed** — blocked on API key extraction blocker that was never resolved; 8 scenarios remain untested. The guest API pivot changed the auth model but UAT wasn't re-scoped to match

### Patterns Established
- `webapp/auth.py` for shared auth decorators (extracted to avoid circular imports)
- `data-source="auto"/"user"` attribute pattern for dirty-tracking in frontend
- `data-matchup-id` DOM attribute for row lookup (not positional array index)
- `intelligence/` package for non-training data fetchers

### Key Lessons
- **Spike before committing to auth strategies** — the Playwright session manager was architecturally sound but practically impossible (Pinnacle's JS bundle stopped exposing the API key). A 30-minute browser DevTools inspection would have surfaced the guest API earlier.
- **Run milestone audits after all phases complete, not during** — the v1.0 audit was stale by close time.
- **UAT should be re-scoped after pivots** — the 04.1 UAT was written for the Playwright flow and never updated for guest API reality.

---

## Cross-Milestone Trends

| Metric | v1.0 |
|--------|------|
| Phases | 6 |
| Plans | 11 |
| Days | 5 |
| Pivots | 1 (Playwright → guest API) |
| Deferred items | 3 |
