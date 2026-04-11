# Requirements: PaceIQ v1.0 — Pinnacle Preload

**Defined:** 2026-04-11
**Core Value:** Edge detection — surfacing when PaceIQ's win probability differs from Pinnacle's implied odds by enough (>5% flag, >8% act) to justify a bet.

## v1 Requirements

### Odds Ingestion

- [ ] **ODDS-01**: System fetches today's H2H cycling markets from Pinnacle's internal API using a stored session cookie
- [ ] **ODDS-02**: Raw odds data is appended to an audit log (`data/odds_log.jsonl`) after each successful fetch
- [ ] **ODDS-03**: System shows a clear, actionable error message (including which env var to update) when the Pinnacle session cookie is expired or invalid
- [ ] **ODDS-04**: System can re-fetch Pinnacle odds independently without re-loading stage context or re-resolving rider names

### Name Resolution

- [ ] **NAME-01**: System resolves Pinnacle display names to PCS rider URLs via exact match against `cache.db` riders
- [ ] **NAME-02**: System resolves names that differ only by accents, special characters, or casing via unicode normalization before fuzzy matching
- [ ] **NAME-03**: System resolves ambiguous names via fuzzy matching (rapidfuzz); auto-accepts matches above confidence threshold without user input
- [ ] **NAME-04**: Confirmed name→PCS URL mappings are cached persistently in `data/name_mappings.json` and used on future runs before fuzzy matching
- [ ] **NAME-05**: Pairs where one or both riders could not be resolved are displayed in the UI with a manual rider search so the user can complete the match

### Stage Context

- [ ] **STGE-01**: System fetches stage details (distance, elevation gain, climb counts/categories, race tier, stage type, profile icon) from PCS via the `procyclingstats` lib given a Pinnacle race name
- [ ] **STGE-02**: Stage context fetch failure degrades gracefully — manual input fields remain available and prediction is not blocked

### Batch Prediction UI

- [ ] **UI-01**: User can click "Load from Pinnacle" in the batch H2H prediction UI to fetch today's available cycling markets
- [ ] **UI-02**: User can select a race from the fetched Pinnacle markets; selecting a race auto-populates all stage fields and all H2H pairs with odds
- [ ] **UI-03**: All auto-populated fields (stage details, rider selections, odds) remain individually editable before running predictions
- [ ] **UI-04**: User can click "Refresh Odds" to re-fetch current Pinnacle odds and update odds fields in an already-loaded session without clearing stage context or rider selections

## v2 Requirements

### Intelligence Pipeline

- **INTEL-01**: System runs per-matchup qualitative research via Claude Haiku (web search → signal extraction → flag)
- **INTEL-02**: System assembles and emails an HTML intelligence report once daily after the nightly data pipeline completes
- **INTEL-03**: Report includes per-matchup qual flags (domestique, fatigue, injury, protected) with source citations
- **INTEL-04**: System triggers automatically via GitHub Actions webhook after nightly data fetch succeeds

### Bet Logging Integration

- **BETLOG-01**: User can click "Log this bet" on a batch prediction result row, pre-filled with Pinnacle odds, recommended stake, and matchup details

## Out of Scope

| Feature | Reason |
|---------|--------|
| Automated bet placement | Permanently manual on Pinnacle — deliberate design choice |
| Auto-load on page startup | Session cookie expires regularly; explicit trigger is safer and more predictable |
| Real-time odds monitoring | Once-daily or on-demand is sufficient for this workflow |
| VPS deployment changes | v1.0 is local Flask only; VPS work deferred to Intelligence Pipeline milestone |
| Feature registry refactor | Does not block this milestone; deferred to avoid scope creep |
| Claude API qualitative research | Planned for v1.1 Intelligence Pipeline milestone |
| Multi-user support | Personal tool — single user only |
| OAuth / Pinnacle API key | Session cookie approach is sufficient; official API access not available |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| ODDS-01 | Phase 1 | Pending |
| ODDS-02 | Phase 1 | Pending |
| ODDS-03 | Phase 1 | Pending |
| ODDS-04 | Phase 4 | Pending |
| NAME-01 | Phase 2 | Pending |
| NAME-02 | Phase 2 | Pending |
| NAME-03 | Phase 2 | Pending |
| NAME-04 | Phase 2 | Pending |
| NAME-05 | Phase 2 | Pending |
| STGE-01 | Phase 3 | Pending |
| STGE-02 | Phase 3 | Pending |
| UI-01 | Phase 5 | Pending |
| UI-02 | Phase 5 | Pending |
| UI-03 | Phase 5 | Pending |
| UI-04 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 15 total
- Mapped to phases: 15
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-11*
*Last updated: 2026-04-11 — traceability mapped (roadmap created)*
