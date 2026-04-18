# Roadmap: PaceIQ

## Milestones

- SHIPPED **v1.0 Pinnacle Preload** — Phases 1-5 + 04.1 (shipped 2026-04-15)
- **v2.0 Edge Validation & System Maturity** — Phases 6-9 (in progress)

## Phases

<details>
<summary>v1.0 Pinnacle Preload (6 phases) — SHIPPED 2026-04-15</summary>

- [x] Phase 1: Pinnacle API Discovery and Client (2/2 plans) — completed 2026-04-12
- [x] Phase 2: Name Resolver (2/2 plans) — completed 2026-04-13
- [x] Phase 3: Stage Context Fetcher (2/2 plans) — completed 2026-04-13
- [x] Phase 4: Flask Endpoint Wiring (1/1 plan) — completed 2026-04-12
- [x] Phase 04.1: Guest API Pivot (2/2 plans, INSERTED) — completed 2026-04-14
- [x] Phase 5: Frontend Integration (2/2 plans) — completed 2026-04-15

</details>

### v2.0 Edge Validation & System Maturity (In Progress)

**Milestone Goal:** Prove or disprove that PaceIQ has a real betting edge against Pinnacle's closing line. If the edge is real (CLV >= +1.5% over 100+ bets), upgrade the model and automate the daily workflow. If not (CLV < 0 over 200 bets), stop model investment.

- [ ] **Phase 6: Odds Scraping & CLV Infrastructure** - Rebuild the Pinnacle scraper and instrument every bet with a closing-line value signal
- [ ] **Phase 7: Edge Analysis & Risk Controls** - Surface edge-bucket ROI, cap stage exposure, and build the CLV drift early-warning system
- [ ] **Phase 8: Model Upgrades** - Fix known serving bugs and extend the feature pipeline (gated by Phase 6 CLV signal)
- [ ] **Phase 9: Automation** - Schedule pre-race reports, closing-odds capture, settlement, and Discord alerts end-to-end

## Phase Details

### Phase 6: Odds Scraping & CLV Infrastructure
**Goal**: Every bet placed carries a closing-line value signal — odds scraped reliably, full market snapshots stored daily, bets enriched with model recommendations, and CLV computed at settlement
**Depends on**: Phase 5 (v1.0 shipped)
**Requirements**: ODDS-01, ODDS-02, ODDS-03, ODDS-04, ODDS-05, CLV-01, CLV-02, CLV-03, CLV-04, CLV-05, CLV-06, CLV-07, BET-01, BET-02, BET-03
**Success Criteria** (what must be TRUE):
  1. Pinnacle H2H cycling pages are scraped successfully via BeautifulSoup/requests and all offered matchups are captured as a daily snapshot stored in cache.db
  2. Each bet record includes actual stake, recommended quarter-Kelly stake, model probability, Pinnacle implied probability, edge %, decimal odds, matchup details, and capture timestamp at the moment of logging
  3. Closing odds are captured per market at race start time; the bets table in cache.db has closing_odds_a, closing_odds_b, clv, clv_no_vig, and settled_at columns
  4. After PCS results are ingested, bets are auto-settled and CLV (raw and vig-free) is computed and written to the bets table
  5. The P&L UI shows per-bet CLV, rolling average CLV, 95% bootstrap confidence interval, and a CLV breakdown by stage type (flat/mountain/TT)
**Plans**: TBD
**UI hint**: yes

### Phase 7: Edge Analysis & Risk Controls
**Goal**: The user can see whether predicted edges are translating to real returns, with guardrails preventing correlated over-exposure and an early warning when the CLV signal degrades
**Depends on**: Phase 6
**Requirements**: EDGE-01, EDGE-02, EDGE-03, EDGE-04, EDGE-05, EDGE-06
**Success Criteria** (what must be TRUE):
  1. The P&L UI groups bets by predicted edge bucket (0-5%, 5-8%, 8-12%, 12%+) and displays ROI and Wilson CI per bucket; buckets with fewer than 30 bets show no ROI to prevent false precision
  2. All model recommendations with edge > 5% are logged regardless of whether a bet is placed, so the user can audit missed opportunities without survivorship bias
  3. The batch prediction UI enforces a per-stage aggregate stake cap (max 2x per-bet cap across all matchups from the same stage) and warns when the cap would be breached
  4. simulate_pnl.py is clearly labeled as circular evidence (synthetic odds from model probs, not a real backtest) so it cannot be mistaken for validation
  5. A rolling 50-bet CLV drift alert fires when average CLV drops below 0, surfacing model degradation before large capital is deployed
**Plans**: TBD
**UI hint**: yes

### Phase 8: Model Upgrades
**Goal**: The live prediction pipeline uses correct interaction features and real startlist data, and is extended with DNF adjustment, market odds at inference, team strength, and an XGBRanker benchmark — gated by confirmed positive CLV from Phase 6
**Depends on**: Phase 6 (CLV gate: >= +1.5% over 100+ bets to proceed; < 0 over 200 bets kills this phase)
**Requirements**: MODEL-01, MODEL-02, MODEL-03, MODEL-04, MODEL-05, MODEL-06, MODEL-07
**Success Criteria** (what must be TRUE):
  1. Interaction features are computed by a single shared _compute_interactions() helper used in build_feature_vector, build_feature_vector_manual, and build_feature_matrix — no duplication across three locations
  2. The manual prediction path includes all 4 previously missing interaction groups (including interact_diff_quality_x_form, the #2 feature by XGBoost gain) and both prediction paths produce identical interaction values for the same inputs
  3. diff_field_rank_quality is computed from live startlist data instead of being hardcoded to 0.0, and predictions for races with a resolved startlist differ measurably from the neutral default
  4. DNF heuristic adjustment is applied at inference time using career DNF rate and stage danger proxy, with the adjustment logged alongside the base prediction
  5. XGBRanker is benchmarked against CalibratedXGBoost on the time-based split and the result is logged in decision_log.md; the current best model is updated if XGBRanker wins on ROC-AUC without calibration regression
**Plans**: TBD

### Phase 9: Automation
**Goal**: The daily betting workflow runs with less than 5 minutes of human effort — pre-race report is waiting before the stage, closing odds are captured without manual action, bets are auto-settled, and Discord alerts fire on edges and drift
**Depends on**: Phase 7, Phase 8
**Requirements**: AUTO-01, AUTO-02, AUTO-03, AUTO-04, AUTO-05, AUTO-06
**Success Criteria** (what must be TRUE):
  1. A pre-race briefing report with act/flag/watch tiers is generated and saved to data/reports/ automatically at T-2h before stage start — no manual trigger required on race day
  2. Closing-odds snapshots are captured automatically at T-24h, T-2h, and T-30min per race with race start time resolved to UTC from PCS country metadata; the scheduler correctly targets the Pinnacle market window before suspension
  3. Discord alerts fire on bets with edge > 8% and on weekly drift-monitor findings (rolling CLV + calibration check); alerts are fire-and-forget and never crash the Flask process
  4. Bets are auto-settled and CLV is computed within one hour of PCS results being ingested, with no manual settlement step required
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 6 → 7 → 8 (gated) → 9

**CLV Kill/Keep Gate (between Phase 6 and Phase 8):**
- Keep: CLV >= +1.5% over 100+ bets → proceed to Phase 8
- Kill: CLV < 0 over 200 bets → halt Phase 8, no further model investment
- Gray zone: CLV 0-1.5% over 100 bets → continue collecting, defer Phase 8

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 6. Odds Scraping & CLV Infrastructure | v2.0 | 0/? | Not started | - |
| 7. Edge Analysis & Risk Controls | v2.0 | 0/? | Not started | - |
| 8. Model Upgrades | v2.0 | 0/? | Not started | - |
| 9. Automation | v2.0 | 0/? | Not started | - |
