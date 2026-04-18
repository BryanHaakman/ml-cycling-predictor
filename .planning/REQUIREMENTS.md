# Requirements: PaceIQ v2.0

**Defined:** 2026-04-18
**Core Value:** Edge detection — surfacing when PaceIQ's win probability differs from Pinnacle's implied odds by enough (>5% flag, >8% act) to justify a bet.

## v2.0 Requirements

### Odds Scraping

- [ ] **ODDS-01**: Pinnacle H2H cycling markets are scraped reliably from public pages via BeautifulSoup/requests (replacing broken guest API)
- [ ] **ODDS-02**: Every H2H matchup Pinnacle offers for cycling is captured each day as a full market snapshot (not just user-selected matchups)
- [ ] **ODDS-03**: Each market snapshot records: matchup participants, decimal odds, implied probabilities, capture timestamp, race/stage context
- [ ] **ODDS-04**: Model predictions are run on all captured matchups and stored alongside odds (model prob, edge, quarter-Kelly recommendation)
- [ ] **ODDS-05**: Historical snapshots are preserved so the user can review all available markets, model recommendations, and missed opportunities

### CLV Tracking

- [ ] **CLV-01**: Closing odds are captured per market at race start time via automated snapshot
- [ ] **CLV-02**: Schema migration adds closing_odds_a, closing_odds_b, clv, clv_no_vig, settled_at columns to bets table in cache.db
- [ ] **CLV-03**: Bets are auto-settled after PCS results are ingested (won/lost/void)
- [ ] **CLV-04**: CLV is computed at settlement time using closing odds
- [ ] **CLV-05**: Vig-free CLV is computed by stripping Pinnacle margin before comparison
- [ ] **CLV-06**: P&L UI displays per-bet CLV, rolling average CLV, and 95% bootstrap confidence interval
- [ ] **CLV-07**: CLV is tracked separately by stage type (flat/mountain/TT) for terrain-specific edge analysis

### Edge Analysis & Risk

- [ ] **EDGE-01**: Edge-bucket ROI analysis groups bets by predicted edge (0-5%, 5-8%, 8-12%, 12%+) with sample count and Wilson CI per bucket
- [ ] **EDGE-02**: ROI display is suppressed when N < 30 per bucket to prevent false precision
- [ ] **EDGE-03**: Per-stage exposure cap limits aggregate stake to max 2x per-bet cap across correlated matchups from the same stage
- [ ] **EDGE-04**: All model recommendations (edge > 5%) are logged, not just placed bets, to prevent survivorship bias
- [ ] **EDGE-05**: simulate_pnl.py is clearly deprecated as evidence (labeled circular — synthetic odds from model probs)
- [ ] **EDGE-06**: Rolling 50-bet CLV drift alert warns when CLV drops below 0

### Bet Recording

- [ ] **BET-01**: When a bet is placed, the record includes: actual stake, recommended quarter-Kelly stake, model probability, Pinnacle implied probability, edge %, decimal odds, matchup details (riders, race, stage), and capture timestamp
- [ ] **BET-02**: Bet records include closing odds and CLV once settled
- [ ] **BET-03**: Complete bet history is queryable for post-hoc analysis (filter by date, race, edge bucket, stage type, outcome)

### Model Upgrades

- [ ] **MODEL-01**: Interaction features refactored into shared `_compute_interactions()` helper (resolving 3-location duplication in features/pipeline.py)
- [ ] **MODEL-02**: 4 missing interaction groups restored in `build_feature_vector_manual` (including importance-#2 feature interact_diff_quality_x_form)
- [ ] **MODEL-03**: `diff_field_rank_quality` computed from live startlist data instead of hardcoded 0.0
- [ ] **MODEL-04**: DNF heuristic adjustment integrated into H2H predictions (career DNF rate + stage danger proxy)
- [ ] **MODEL-05**: Market implied probability available as inference-time feature (not added to training data — leakage prevention)
- [ ] **MODEL-06**: XGBRanker benchmarked as alternative training objective (pairwise LambdaRank vs current CalibratedXGBoost)
- [ ] **MODEL-07**: Team strength features added from pre-race roster (team career top10 rate, team size, captain indicator)

### Automation

- [ ] **AUTO-01**: Pre-race briefing report generated T-2h before stage start with act/flag/watch tiers, saved to data/reports/
- [ ] **AUTO-02**: Automated closing-odds cron captures multi-snapshot (T-24h, T-2h, T-30min) with UTC-resolved timing
- [ ] **AUTO-03**: Discord edge alerts fire on bets with edge > 8%
- [ ] **AUTO-04**: Weekly drift monitor checks rolling CLV + calibration, alerts via Discord if degraded
- [ ] **AUTO-05**: Race timezone resolution maps PCS country metadata to IANA timezone for correct cron timing
- [ ] **AUTO-06**: Auto-settlement cron runs hourly post-race to ingest results and compute CLV

## Future Requirements

### Deferred from v2.0

- **STAGE-01**: Stage-type specialization (3 separate models: flat/mountain/TT) — 3x training cost; gate on positive CLV + terrain-specific CLV concentration
- **MKTRAIN-01**: Market odds as training feature — requires 500+ live bets with consistent pre-race odds snapshots
- **RETRAIN-01**: Auto-triggered retraining pipeline — alert and recommend only; human must approve
- **SIM-01**: Monte Carlo race simulation — backlog; high effort, revisit if H2H edge is proven
- **SEQ-01**: Sequence model (transformer) — backlog; very high effort vs XGB baseline
- **LIVE-01**: Live in-running markets — backlog; mid-race data unreliable

## Out of Scope

| Feature | Reason |
|---------|--------|
| Automated bet placement | Permanently manual on Pinnacle |
| Multi-user support | Personal tool only |
| Historical odds backtest | Forward CLV tracking chosen; historical odds not reliably available |
| Auto-load on page startup | Explicit trigger is safer with session expiry |
| Automated retraining without human review | Dangerous in betting context — bad retrain worse than stale model |
| statsmodels dependency | scipy 1.17.1 covers all statistical needs |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| ODDS-01 | — | Pending |
| ODDS-02 | — | Pending |
| ODDS-03 | — | Pending |
| ODDS-04 | — | Pending |
| ODDS-05 | — | Pending |
| CLV-01 | — | Pending |
| CLV-02 | — | Pending |
| CLV-03 | — | Pending |
| CLV-04 | — | Pending |
| CLV-05 | — | Pending |
| CLV-06 | — | Pending |
| CLV-07 | — | Pending |
| EDGE-01 | — | Pending |
| EDGE-02 | — | Pending |
| EDGE-03 | — | Pending |
| EDGE-04 | — | Pending |
| EDGE-05 | — | Pending |
| EDGE-06 | — | Pending |
| BET-01 | — | Pending |
| BET-02 | — | Pending |
| BET-03 | — | Pending |
| MODEL-01 | — | Pending |
| MODEL-02 | — | Pending |
| MODEL-03 | — | Pending |
| MODEL-04 | — | Pending |
| MODEL-05 | — | Pending |
| MODEL-06 | — | Pending |
| MODEL-07 | — | Pending |
| AUTO-01 | — | Pending |
| AUTO-02 | — | Pending |
| AUTO-03 | — | Pending |
| AUTO-04 | — | Pending |
| AUTO-05 | — | Pending |
| AUTO-06 | — | Pending |

**Coverage:**
- v2.0 requirements: 34 total
- Mapped to phases: 0
- Unmapped: 34 (pending roadmap creation)

---
*Requirements defined: 2026-04-18*
*Last updated: 2026-04-18 after initial definition*
