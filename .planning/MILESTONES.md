# Milestones

## v1.0 — Pinnacle Preload

**Shipped:** 2026-04-15
**Phases:** 6 (1, 2, 3, 4, 04.1, 5) | **Plans:** 11

**Delivered:** Live Pinnacle H2H odds ingestion with one-click "Load from Pinnacle" in the batch prediction UI — zero-auth guest API client, 3-stage name resolver, PCS stage context fetcher, and refresh-odds with dirty tracking.

**Accomplishments:**
1. Pinnacle guest API client (`data/odds.py`) — zero-auth H2H market fetch with American-to-decimal odds conversion and JSONL audit logging
2. Name resolver (`data/name_resolver.py`) — 3-stage pipeline (cache/exact/NFKD-normalized) mapping Pinnacle ALL-CAPS names to PCS rider URLs with persistent JSON cache
3. Stage context fetcher (`intelligence/stage_context.py`) — Pinnacle race name to PCS stage metadata with 5s timeout and graceful degradation
4. Flask endpoints (`webapp/pinnacle_bp.py`) — POST `/api/pinnacle/load` and `/refresh-odds` with frozen JSON schema
5. Frontend integration — "Load from Pinnacle" button, race picker, auto-populated H2H pairs, and "Refresh Odds" with dirty-tracking
6. Guest API pivot — reverted failed Playwright experiment, switched to zero-auth guest.api.arcadia.pinnacle.com

**Known deferred items at close:** 3 (see STATE.md Deferred Items)

**Archive:** [v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md) | [v1.0-REQUIREMENTS.md](milestones/v1.0-REQUIREMENTS.md)
