# Requirements: PaceIQ v1.0 — Pinnacle Preload

**Defined:** 2026-04-11
**Core Value:** Edge detection — surfacing when PaceIQ's win probability differs from Pinnacle's implied odds by enough (>5% flag, >8% act) to justify a bet.

## v1 Requirements

### Odds Ingestion

- [x] **ODDS-01**: System fetches today's H2H cycling markets from Pinnacle's internal API using a stored session cookie
- [x] **ODDS-02**: Raw odds data is appended to an audit log (`data/odds_log.jsonl`) after each successful fetch
- [x] **ODDS-03**: System shows a clear, actionable error message (including which env var to update) when the Pinnacle session cookie is expired or invalid
- [x] **ODDS-04**: System can re-fetch Pinnacle odds independently without re-loading stage context or re-resolving rider names

### Name Resolution

- [x] **NAME-01**: System resolves Pinnacle display names to PCS rider URLs via exact match against `cache.db` riders
- [x] **NAME-02**: System resolves names that differ only by accents, special characters, or casing via unicode normalization before fuzzy matching
- [x] **NAME-03**: System resolves ambiguous names via fuzzy matching (rapidfuzz); auto-accepts matches above confidence threshold without user input
- [x] **NAME-04**: Confirmed name→PCS URL mappings are cached persistently in `data/name_mappings.json` and used on future runs before fuzzy matching
- [x] **NAME-05**: Pairs where one or both riders could not be resolved are displayed in the UI with a manual rider search so the user can complete the match

### Stage Context

- [x] **STGE-01**: System fetches stage details (distance, elevation gain, climb counts/categories, race tier, stage type, profile icon) from PCS via the `procyclingstats` lib given a Pinnacle race name
- [x] **STGE-02**: Stage context fetch failure degrades gracefully — manual input fields remain available and prediction is not blocked

### Batch Prediction UI

- [x] **UI-01**: User can click "Load from Pinnacle" in the batch H2H prediction UI to fetch today's available cycling markets
- [x] **UI-02**: User can select a race from the fetched Pinnacle markets; selecting a race auto-populates all stage fields and all H2H pairs with odds
- [x] **UI-03**: All auto-populated fields (stage details, rider selections, odds) remain individually editable before running predictions
- [x] **UI-04**: User can click "Refresh Odds" to re-fetch current Pinnacle odds and update odds fields in an already-loaded session without clearing stage context or rider selections

## v2 Requirements — Edge Validation & System Maturity

*Derived from deep assessment (2026-04-17). Prioritized by impact x effort. Execution order: Phase 1 → gate decision → Phase 2 → Phase 3.*

### Phase 1: Validate the Edge (Weeks 1-3)

- **CLV-01**: System records closing odds (odds_a, odds_b) for every bet at race start time
- **CLV-02**: System computes CLV per bet as (closing_implied_prob - opening_implied_prob) and stores it with the bet record
- **CLV-03**: System generates a weekly CLV summary report (average CLV, CLV by edge bucket, CLV trend over time)
- **EDGE-01**: System produces an edge-bucket ROI analysis — bets grouped by model edge (5-8%, 8-12%, 12%+) with realized ROI per bucket
- **POLICY-01**: Single staking policy (quarter Kelly, max cap) documented in CLAUDE.md, enforced in code, with no competing definitions elsewhere

**Gate decision after Phase 1:**
- CLV >= 1.5% average over 100+ bets → proceed to Phase 2
- CLV < 0 average over 200 bets → kill the project
- Between 0-1.5% → continue collecting data, defer Phase 2

### Phase 2: Upgrade the Model (Weeks 4-8)

- **MODEL-01**: Live startlist resolution via PCS MCP at prediction time — fix the `field_rank_quality=0.5` hardcode in `build_feature_vector_manual` (recovers importance-#3 feature)
- **MODEL-02**: Pinnacle opening odds as a model input feature — learn the residual between model and market (requires sufficient forward odds collection from Phase 1)
- **MODEL-03**: DNF/finish probability model — P(rider finishes | race, conditions, historical DNF rate, course type) combined with H2H model for composite prediction
- **MODEL-04**: Pairwise ranking model (XGBRanker / LambdaMART) — optimize NDCG directly instead of binary cross-entropy; ensemble with current binary model if both add value
- **MODEL-05**: Pre-race team-strength features (protected rider, team climber/sprinter strength, team UCI ranking) keyed to team-season to avoid leakage
- **MODEL-06**: Stage-type specialization — train separate models for flat/hilly/mountain + ITT sub-model instead of one unified model

**Success criteria:** Backtest ROI improvement >= 2pp vs Phase 1 baseline. No regression in calibration (ECE < 0.015). CLV improvement >= 1pp.

### Phase 3: Automate & Scale (Weeks 9-12)

- **AUTO-01**: Closing-odds scraper — automated Pinnacle odds snapshot at race start time (cron/script)
- **AUTO-02**: Post-race automated settlement — results ingestion triggers CLV computation and bet settlement without manual intervention
- **AUTO-03**: Pre-race report generation — per-stage markdown with picks, confidence, reasoning highlights, bankroll exposure
- **AUTO-04**: Edge alerting — Discord/email notification when a live matchup exceeds edge threshold and passes model + calibration sanity checks
- **AUTO-05**: Drift detection — rolling calibration and CLV monitoring with alerts when model performance degrades beyond threshold
- **AUTO-06**: Multi-book odds polling — Pinnacle + Betfair exchange + one retail book for line shopping on large edges

**Success criteria:** End-to-end matchup-to-settlement in < 5 minutes human effort per day. Zero manual data reconciliation for a full 2-week block.

### Deferred / Backlog

- **INTEL-01**: Per-matchup qualitative research via Claude API (web search → signal extraction → flag) — moved from original v2 scope; revisit after Phase 2 model upgrades prove value
- **INTEL-02**: Daily HTML intelligence report via email — revisit after AUTO-03 (pre-race reports) is validated
- **BETLOG-01**: "Log this bet" button on prediction result row — convenience feature, implement when CLV tracking (CLV-01) is stable
- **SIM-01**: Monte Carlo race simulation (rider-level, 1000 races) — opens exacta/trifecta/stage-winner markets; high effort, revisit if H2H edge is proven
- **SEQ-01**: Sequence model over per-rider career (transformer on last 50 race embeddings) — likely +1-2% AUC but very high effort vs XGB baseline
- **LIVE-01**: Live in-running markets — huge EV upside but mid-race PCS data is unreliable; revisit only if static model proves profitable

## Out of Scope

| Feature | Reason |
|---------|--------|
| Automated bet placement | Permanently manual on Pinnacle — deliberate design choice |
| Auto-load on page startup | Session cookie expires regularly; explicit trigger is safer and more predictable |
| VPS deployment changes | v1.0 is local Flask only; VPS work deferred |
| Feature registry refactor | Does not block current work; deferred to avoid scope creep |
| Multi-user support | Personal tool — single user only |
| OAuth / Pinnacle API key | Session cookie / guest API approach is sufficient; official API access not available |
| Historical odds backtest | Forward CLV tracking chosen over historical odds reconstruction — cycling H2H historical odds are too sparse to backfill reliably |
| Multi-agent architecture | Automation jobs implemented as scripts/crons, not a formal agent system |
| Monte Carlo race simulation | Backlog (SIM-01) — high effort, revisit if H2H edge is proven |
| Sequence model (transformer) | Backlog (SEQ-01) — very high effort vs XGB baseline |
| Live in-running markets | Backlog (LIVE-01) — mid-race PCS data unreliable |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| ODDS-01 | Phase 1 | Complete |
| ODDS-02 | Phase 1 | Complete |
| ODDS-03 | Phase 1 | Complete |
| ODDS-04 | Phase 4 | Complete |
| NAME-01 | Phase 2 | Complete |
| NAME-02 | Phase 2 | Complete |
| NAME-03 | Phase 2 | Complete |
| NAME-04 | Phase 2 | Complete |
| NAME-05 | Phase 2 | Complete |
| STGE-01 | Phase 3 | Complete |
| STGE-02 | Phase 3 | Complete |
| UI-01 | Phase 5 | Complete |
| UI-02 | Phase 5 | Complete |
| UI-03 | Phase 5 | Complete |
| UI-04 | Phase 5 | Complete |

**Coverage:**
- v1 requirements: 15 total
- Mapped to phases: 15
- Complete: 15 ✓

---
*Requirements defined: 2026-04-11*
*Last updated: 2026-04-17 — all requirements complete, milestone ready for archival*
