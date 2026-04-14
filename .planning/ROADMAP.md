# Roadmap: PaceIQ v1.0 — Pinnacle Preload

## Overview

This milestone adds a live data ingestion layer to the existing batch prediction UI. The work proceeds in a strict build order: discover the Pinnacle internal API endpoint first (the only true unknown), then build the name resolver and stage context fetcher (parallel development possible), wire all three together into two Flask endpoints, and finally surface everything in the frontend. Each phase delivers a self-contained, testable capability that feeds directly into the next.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Pinnacle API Discovery and Client** - Discover internal endpoint via Playwright, implement data/odds.py with session-cookie auth and structured error handling
- [ ] **Phase 2: Name Resolver** - Implement data/name_resolver.py with exact/normalize/fuzzy/cache pipeline for Pinnacle-to-PCS name mapping
- [ ] **Phase 3: Stage Context Fetcher** - Implement intelligence/stage_context.py to fetch live stage details via procyclingstats lib with graceful degradation
- [x] **Phase 4: Flask Endpoint Wiring** - Integrate all three components into POST /api/pinnacle/load and POST /api/pinnacle/refresh-odds with locked response schema (completed 2026-04-12)
- [ ] **Phase 04.1: Guest API Pivot** - Revert failed Playwright experiment, switch to guest API (guest.api.arcadia.pinnacle.com) for zero-auth H2H odds (INSERTED, replanned 2026-04-13)
- [ ] **Phase 5: Frontend Integration** - Add "Load from Pinnacle" button, race selector, and "Refresh Odds" to batch H2H UI with per-cell dirty tracking

## Phase Details

### Phase 1: Pinnacle API Discovery and Client
**Goal**: A working Pinnacle API client that fetches today's cycling H2H markets from a live session, handles expired cookies clearly, and logs every fetch to an audit file
**Depends on**: Nothing (first phase)
**Requirements**: ODDS-01, ODDS-02, ODDS-03
**Success Criteria** (what must be TRUE):
  1. Calling fetch_cycling_h2h_markets() with a valid session cookie returns a non-empty list of OddsMarket objects containing at least one cycling H2H matchup with decimal odds
  2. Calling fetch_cycling_h2h_markets() with an expired or invalid session cookie raises PinnacleAuthError with the message specifying the PINNACLE_SESSION_COOKIE env var — it does not return an empty list or raise a generic exception
  3. Every successful fetch appends a complete, parseable JSON line to data/odds_log.jsonl (verified by json.loads on each line after the call)
  4. The discovered endpoint URL, required headers, sport/market IDs, odds format (decimal vs American), and a full example response are documented in docs/pinnacle-api-notes.md before any client code is written
**Plans**: TBD

### Phase 2: Name Resolver
**Goal**: A name resolver that maps every Pinnacle display name (SURNAME-FIRST, ALL-CAPS) to a PCS rider URL through a four-stage pipeline, caches accepted mappings persistently, and surfaces unresolved pairs for manual completion
**Depends on**: Phase 1
**Requirements**: NAME-01, NAME-02, NAME-03, NAME-04, NAME-05
**Success Criteria** (what must be TRUE):
  1. NameResolver.resolve() correctly maps rider names that differ only by accent, case, or word order — including at minimum: Primoz Roglic, Wout van Aert, Romain Bardet, Nairo Quintana — without requiring manual intervention
  2. A name that scores below the auto-accept threshold (90) returns None rather than a wrong match; the pair is flagged as unresolved rather than silently mis-mapped
  3. Accepted mappings are written to data/name_mappings.json and re-used on the next resolver instantiation without re-querying cache.db or re-running fuzzy logic
  4. name_mappings.json schema is validated on load (each value matches rider/[a-z0-9-]+); invalid entries are logged and skipped rather than crashing the resolver
**Plans:** 2 plans
Plans:
- [x] 02-01-PLAN.md — TDD: NameResolver with cache/exact/normalized stages + ResolveResult dataclass + persistent JSON cache
- [x] 02-02-PLAN.md — TDD: Fuzzy matching stage + unresolved contract verification

### Phase 3: Stage Context Fetcher
**Goal**: A stage context fetcher that takes a Pinnacle race name, finds the matching PCS stage URL, and returns a fully-populated StageContext dataclass ready to pass directly to build_feature_vector_manual — and degrades to manual input without blocking prediction when PCS is unavailable
**Depends on**: Phase 1
**Requirements**: STGE-01, STGE-02
**Success Criteria** (what must be TRUE):
  1. fetch_stage_context() called with a valid current-race Pinnacle name returns a StageContext with non-zero distance, vertical_meters, num_climbs, a valid profile_icon (p1-p5), a race_date matching today's date within +/-1 day, and is_resolved=True — confirmed against at least one live upcoming race
  2. fetch_stage_context() called with an unrecognized race name or when PCS is unreachable returns a StageContext with is_resolved=False within the configured timeout (5 seconds); the calling endpoint is not blocked and manual input fields remain available
**Plans:** 2 plans
Plans:
- [x] 03-01-PLAN.md — TDD: StageContext dataclass + fetch_stage_context with fuzzy race matching, PCS fetch, 5s timeout, graceful degradation
- [x] 03-02-PLAN.md — Live integration tests against real PCS + human verification checkpoint
**UI hint**: yes

### Phase 4: Flask Endpoint Wiring
**Goal**: Two new Flask endpoints — POST /api/pinnacle/load and POST /api/pinnacle/refresh-odds — that integrate the Pinnacle client, name resolver, and stage context fetcher into a locked JSON response schema, verified end-to-end against live data before the frontend is built
**Depends on**: Phase 2, Phase 3
**Requirements**: ODDS-04
**Success Criteria** (what must be TRUE):
  1. A curl or httpie call to POST /api/pinnacle/load with a valid session cookie returns the full ResolvedMarket JSON schema — including races[], each with stage_context, stage_resolved, and pairs[] containing rider_a_url/rider_b_url (null for unresolved), odds_a/odds_b, and resolved flags — and the response shape is frozen in docs/pinnacle-api-notes.md before Phase 5 begins
  2. A curl call to POST /api/pinnacle/refresh-odds returns updated odds for an already-loaded race without triggering a stage context re-fetch or name re-resolution; the response contains only the pairs[]{odds_a, odds_b} fields
  3. Both endpoints return a structured JSON error (including env_var field) when PINNACLE_SESSION_COOKIE is absent or expired; neither endpoint returns a 500 or crashes Flask on auth failure
  4. The explicit decision on whether to pass resolved rider URLs as a startlist to build_feature_vector_manual (fixing the diff_field_rank_quality neutral default) is documented in decision_log.md and either implemented or flagged as a known gap in the API response
**Plans:** 1/1 plans complete
Plans:
- [x] 04-01-PLAN.md — Blueprint skeleton + /load + /refresh-odds + schema freeze + decision log + live verification checkpoint

### Phase 04.1: Guest API Pivot — Replace failed Playwright experiment with direct guest API calls (INSERTED, replanned)

**Goal:** Revert all Playwright session manager code, switch PINNACLE_API_BASE to the guest subdomain (guest.api.arcadia.pinnacle.com), optimize to 2 sport-level API calls, and filter "The Field" outright bets — delivering a zero-auth odds client
**Requirements**: D-01, D-02, D-03, D-04, D-05, D-06, D-07, D-08, D-09, D-10, D-11, D-12
**Depends on:** Phase 4
**Plans:** 2 plans

Plans:
- [ ] 04.1-01-PLAN.md — Revert all Playwright experiment files, restore data/odds.py and dependencies to pre-04.1 state
- [ ] 04.1-02-PLAN.md — Guest API constant, sport-level 2-call fetch, "The Field" filter, updated tests

### Phase 5: Frontend Integration
**Goal**: The batch H2H prediction UI has a "Load from Pinnacle" button and race selector that auto-populate all stage fields and matchup rows from live Pinnacle data, plus a "Refresh Odds" button that updates odds without touching user-edited cells or stage context
**Depends on**: Phase 4
**Requirements**: UI-01, UI-02, UI-03, UI-04
**Success Criteria** (what must be TRUE):
  1. User can click "Load from Pinnacle", see a populated race selector dropdown, select a race, and have all stage fields (distance, elevation, profile, stage type) and all H2H pair rows (rider names, PCS URLs, odds) filled in automatically — without any manual data entry
  2. Any auto-populated field (stage detail, rider selection, odds value) remains individually editable after population; editing a field does not trigger a reload or reset other fields
  3. Pairs with unresolved riders show the existing rider autocomplete search in the unresolved cell, allowing the user to manually complete the match before running predictions
  4. User can click "Refresh Odds" in an already-loaded session; only odds fields tagged data-source="auto" are updated — cells the user has manually edited (data-source="user") are not overwritten, and stage context and rider selections are preserved
**Plans:** 2 plans
Plans:
- [ ] 05-01-PLAN.md — Pinnacle control row HTML/CSS + loadFromPinnacle() + populatePinnacleRace() with race picker, stage population, pair creation, and unresolved rider handling
- [ ] 05-02-PLAN.md — refreshOdds() with data-source dirty tracking + human verification checkpoint
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 04.1 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Pinnacle API Discovery and Client | 0/TBD | Not started | - |
| 2. Name Resolver | 0/2 | Planned | - |
| 3. Stage Context Fetcher | 0/2 | Planned | - |
| 4. Flask Endpoint Wiring | 1/1 | Complete   | 2026-04-12 |
| 04.1. Guest API Pivot | 0/2 | Replanned  | - |
| 5. Frontend Integration | 0/2 | Planned | - |
