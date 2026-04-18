# Project Research Summary

**Project:** PaceIQ v2.0 -- Edge Validation & System Maturity
**Domain:** Sports betting intelligence -- CLV tracking, model upgrades, workflow automation for cycling H2H prediction
**Researched:** 2026-04-18
**Confidence:** HIGH

## Executive Summary

PaceIQ v2.0 is a maturity and validation milestone for an existing, production-ready cycling H2H betting system. The v1.0 system achieved 69.7% prediction accuracy (0.772 ROC-AUC) on historical data using a CalibratedXGBoost model with 150 permutation-selected features from a 292K-pair training corpus -- but with only 26 live bets logged and no closing-odds infrastructure, it is impossible to determine whether that accuracy translates to a real edge against Pinnacle. The core research finding is unambiguous: CLV tracking against the Pinnacle closing line is the single most important capability to build first, and every other v2.0 feature should be sequenced around it. Closing Line Value is the industry-standard leading indicator for betting model validity, converging on actionable signal at 100-200 bets versus the thousands needed to confirm edge via win rate alone.

The recommended approach is a three-phase layered build. Phase 1 establishes the measurement infrastructure (closing odds capture, CLV computation, edge-bucket ROI analysis) using only two new packages -- APScheduler 3.x for in-process scheduling and discord-webhook for alerts -- with all statistical analysis handled by the already-installed scipy 1.17.1. This is intentionally a data-collection phase: no model changes, no new features, no increased betting velocity until the CLV signal is confirmed. Phase 2 conditionally upgrades the ML pipeline (fix the known diff_field_rank_quality = 0.0 serving bug, resolve the 4 missing interaction groups in the manual prediction path, add DNF heuristic adjustment) only after Phase 1 establishes positive CLV. Phase 3 automates the workflow: pre-race briefings, scheduled closing-odds capture, and drift monitoring.

The dominant risks are technical precision risks, not architectural unknowns. Three stand out. First, market odds added to model training introduces look-ahead leakage if historical Pinnacle odds are not available at a consistent pre-race time horizon -- the safe mitigation is to use market odds only at inference time until a systematic historical odds corpus exists. Second, the existing build_feature_vector_manual function is silently missing four interaction groups including interact_diff_quality_x_form (the second most important feature by XGBoost gain) -- every live bet placed today is degraded by this bug, and it must be fixed before any new features are added to the pipeline. Third, automated closing-odds capture must resolve race start timezones correctly (local race time vs UTC) or the market will be suspended before the cron fires and CLV data is permanently lost for those races.

## Key Findings

### Recommended Stack

The existing stack (Python 3.11, Flask, SQLite WAL, XGBoost 3.2.0, scikit-learn 1.8.0, pandas, pyarrow, scipy, rapidfuzz) covers all v2.0 needs except scheduling and notifications. Only two packages need to be added to requirements.txt. All statistical analysis (Wilson CI, binomtest, pearsonr, calibration checks) is covered by the already-installed scipy 1.17.1 -- statsmodels should not be added. XGBRanker is already included in the installed xgboost 3.2.0. Jinja2 is available as a Flask dependency. The no-new-infrastructure constraint (no Redis, no Celery, no external message broker) is fully achievable.

**Core technologies:**
- APScheduler 3.x (>=3.10.0,<4.0): In-process background scheduling -- chosen over OS cron because jobs share the SQLite WAL connection pool and loaded model state; <4.0 pin prevents silent API break from the 4.x async rewrite
- discord-webhook 1.x (>=1.3.0): Edge alerts and drift notifications -- adds embed formatting and retry logic over raw requests; fire-and-forget, never raises on failure
- scipy 1.17.1 (already installed): All CLV significance testing -- Wilson CI, binomtest, pearsonr, chi2_contingency; no statsmodels needed
- XGBRanker (already in xgboost 3.2.0): Phase 2 pairwise ranking experiment, no additional install
- Jinja2 (already via Flask): Pre-race report markdown generation, standalone (no Flask app context required)

### Expected Features

**Must have (table stakes) -- Phase 1:**
- Closing-odds snapshot capture per pending bet, timed to race start -- without this, CLV cannot be computed retroactively
- Schema migration: add closing_odds_a, closing_odds_b, closing_captured_at, clv, clv_no_vig columns to bets table in cache.db (idempotent ALTER TABLE, same pattern as v1.0 race metadata migration)
- Post-race auto-settlement with CLV computation written at settlement time
- CLV display in P&L tracker: per-bet CLV, rolling average, 95% bootstrap confidence interval alongside every point estimate
- Edge-bucket ROI analysis (0-5%, 5-8%, 8-12%, 12%+) with sample count and Wilson CI per bucket; suppress ROI display when N < 30

**Must have (table stakes) -- Phase 2:**
- Fix diff_field_rank_quality = 0.0 hardcode in build_feature_vector_manual -- this is the #3 most important feature by XGBoost gain; live predictions are degraded on every single bet today
- Refactor interaction feature computation into a shared _compute_interactions() helper -- prerequisite before any other pipeline changes; currently 4 interaction groups including the #2 feature are missing from the manual path

**Must have (table stakes) -- Phase 3:**
- Pre-race briefing report with act/flag/watch tiers generated T-2h before stage start, saved to data/reports/
- Rolling CLV drift alert (50-bet window CLV < 0 triggers Discord notification)
- Automated closing-odds cron with multi-snapshot polling (T-24h, T-2h, T-30min), UTC-resolved from race country timezone

**Should have (differentiators -- add after Phase 1 CLV is positive):**
- Vig-free CLV computation (strip Pinnacle margin before comparison -- cleaner edge signal)
- DNF probability heuristic adjustment to H2H predictions (career DNF rate + stage danger proxy)
- Live startlist team strength features (team career top10 rate, team size, captain indicator)
- Market implied probability as inference-time feature (not training feature -- leakage risk if added to historical training data)
- PSI monitoring on prediction score distribution (Kolmogorov-Smirnov test, scipy.stats)
- XGBRanker as alternative training objective (pairwise LambdaRank -- benchmark vs current 69.7%)

**Defer (v2+, after sufficient live data):**
- Stage-type specialization (three separate models: flat / mountain / TT) -- highest-leverage model upgrade but 3x training cost; gate on CLV being confirmed positive and terrain-specific CLV breakdown showing concentration
- Market odds as training feature -- requires 500+ live bets with consistent pre-race odds snapshots at a fixed time horizon before training
- Auto-triggered retraining pipeline -- alert and recommend only; human must approve any retraining
- Monte Carlo P&L simulation -- circular (synthetic odds from model probs); deprecated as evidence of edge

### Architecture Approach

v2.0 is entirely additive to the existing pipeline. The ML inference path (models/predict.py, features/pipeline.py) is not structurally changed -- new features are threaded through the existing function signatures. The architecture has two clean integration seams: data/pnl.py (bets table, settlement logic) for CLV infrastructure, and data/odds.py (existing Pinnacle client, zero changes) for closing-odds capture. APScheduler 3.x BackgroundScheduler runs inside the Flask process with a memory job store -- no SQLAlchemy dependency, jobs re-registered from code on each startup. New intelligence modules are isolated from the ML core. Reports are stored as JSON files in data/reports/, not SQLite.

**Major components:**
1. data/clv.py (new) -- CLV computation, closing-odds capture via existing data/odds.py, get_clv_summary() for UI
2. webapp/scheduler.py (new) -- APScheduler init, four registered jobs: settlement (hourly), pre-race briefing (06:00 UTC daily), drift monitor (Sunday 08:00 UTC), closing-odds capture (DateTrigger per placed bet)
3. intelligence/reports.py (new) -- Pre-race report generation: fetch markets, resolve names, fetch stage context, run predictions, format markdown
4. intelligence/alerts.py (new) -- Discord webhook dispatch, fire-and-forget, never raises
5. intelligence/drift.py (new) -- Rolling CLV check + calibration bin check; calls alerts on threshold breach
6. features/dnf_features.py (new) -- DNF probability from historical results table, diff feature for pipeline
7. data/pnl.py (modified) -- Schema migration for CLV columns, CLV write in settle_bet()
8. features/pipeline.py (modified) -- Refactor 3-location interaction debt, add market odds / DNF / startlist features in all three locations

### Critical Pitfalls

1. **Market odds as training feature introduces look-ahead leakage** -- historical training pairs have no systematic Pinnacle odds history. Prevention: use market odds only at inference time; do not add to historical training until 500+ live bets with consistent T-2h snapshots. Detection: if historical accuracy improves >3% with market odds but forward accuracy does not, leakage is the cause.

2. **build_feature_vector_manual silently missing 4 interaction groups** -- interact_diff_quality_x_form (XGBoost gain #2) and three other groups are absent from the manual prediction path, defaulting to 0.0. This degrades every live bet made today. Prevention: refactor all three computation sites into _compute_interactions() as the first Phase 2 task; add regression test asserting both paths produce identical interaction values for the same inputs.

3. **Closing odds captured too early or after market suspension** -- Pinnacle H2H cycling markets sometimes close 30-60 min before the nominal race start. Race start times from PCS are local-time strings with no timezone annotation; a VPS running UTC will compute capture time incorrectly for European races (CEST = UTC+2). Prevention: multi-snapshot polling at T-24h, T-2h, T-30min; resolve timezone from PCS race country metadata using zoneinfo stdlib; distinguish market-closed from network-error in capture logs.

4. **CLV false precision on small samples** -- with 26 current bets, the 95% CI on mean CLV is plus or minus 2-3 percentage points. Reporting CLV = 1.87% implies precision that does not exist. Prevention: always display 95% bootstrap CI alongside every CLV point estimate; implement kill gate as lower bound of 95% CI < 0 at N >= 200; add data maturity indicator (Insufficient / Preliminary / Indicative / Reliable) to P&L dashboard.

5. **Correlated bets on the same stage violate Kelly independence** -- multiple H2H matchups from the same stage are correlated; betting quarter-Kelly on four matchups per stage is effectively full-Kelly on the stage outcome. Prevention: add a per-stage exposure cap (max 2x per-bet cap across all matchups for the same stage_url); display aggregate stage exposure in batch prediction UI.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Validate Edge (CLV Infrastructure)

**Rationale:** With 26 live bets, no closing odds stored, and simulate_pnl.py as the only backtest (which uses synthetic odds derived from model probabilities -- circular by construction), there is no current evidence of real edge against Pinnacle. All Phase 2 model work is predicated on this evidence existing. Build measurement first. The Phase 1 gate is: CLV >= +1.5% (lower CI bound) over 100+ bets to proceed; CLV < 0% over 200 bets to kill.

**Delivers:** Closing-odds capture mechanism (manual first, automated in Phase 3), CLV computation and storage, edge-bucket ROI analysis in P&L UI, per-stage exposure warnings, DNF void settlement policy, simulate_pnl.py clearly labeled as non-evidence. A fully instrumented betting operation where every bet generates a CLV signal.

**Features addressed:** CLV tracking (all table stakes), edge-bucket ROI analysis (all table stakes), negative Kelly floor fix, correlated-bet stage cap, bet recommendation log (survivorship bias prevention)

**Pitfalls avoided:** CLV false precision (CI always displayed), simulate_pnl circular evidence (deprecated as evidence source), DNF mis-settlement (void policy), stage over-exposure

**Research flag:** Standard patterns -- CLV computation is well-documented methodology; schema migration follows the existing data/pnl.py pattern directly; no research phase needed

### Phase 2: Model Upgrade (Conditional on Phase 1 Gate)

**Rationale:** Phase 2 only begins if Phase 1 CLV gate is passed. The build order within Phase 2 is dictated by a technical dependency: the 3-location interaction feature duplication must be resolved before any new features are added to the pipeline. After the refactor, startlist resolution fixes the highest-impact known serving bug. Market odds and DNF adjustment follow as independent additions.

**Delivers:** A corrected live prediction pipeline (interaction features no longer missing from manual path, diff_field_rank_quality no longer hardcoded 0.0), DNF heuristic adjustment integrated, market odds available at inference time, retrained model benchmarked on time-based split with calibration validation in the 55-80% betting range.

**Features addressed:** Interaction feature refactor (prerequisite), live startlist resolution, market odds as inference feature, DNF heuristic adjustment, calibration gate on retraining, XGBRanker experiment (if time permits)

**Pitfalls avoided:** Market odds leakage (inference-only, not training), training/serving skew from diff_field_rank_quality, calibration regression (bin-level validation gate)

**Research flag:** Needs deeper planning research -- XGBRanker probability calibration (converting ranking scores to probabilities for Kelly staking) and conditional market odds column handling in the serving feature vector need explicit implementation planning

### Phase 3: Automate (Scheduling, Reports, Drift Monitoring)

**Rationale:** Automation adds value only after the pieces it automates are working correctly and validated. By Phase 3, closing-odds capture logic has been manually validated, settlement and CLV computation are confirmed correct, and predictions are running through the fixed pipeline. Automating broken components creates silent failures -- the worst outcome for a betting system.

**Delivers:** webapp/scheduler.py with APScheduler 3.x BackgroundScheduler running four scheduled jobs; daily pre-race briefing reports generated T-2h before stage start with act/flag/watch tiers and CLV status line; automated closing-odds capture with multi-snapshot polling; weekly drift monitoring (rolling CLV + calibration check) with Discord alerts; Discord edge alerts on bets with edge > 8%.

**Features addressed:** Pre-race report generation (all table stakes), automated closing-odds cron, drift detection (rolling CLV alert + monthly calibration check), Discord edge alerts

**Stack used:** APScheduler 3.x (webapp/scheduler.py), discord-webhook (intelligence/alerts.py), Jinja2 standalone (intelligence/reports.py), zoneinfo stdlib (timezone resolution)

**Pitfalls avoided:** Cron venv activation (APScheduler in-process, not OS crontab); race timezone errors (zoneinfo lookup from PCS country metadata); pre-race report on stale data (scrape_log freshness check before generating); closing odds after suspension (multi-snapshot polling)

**Research flag:** Timezone resolution from PCS country metadata to IANA zone names needs a lookup table -- confirm PCS race country codes are consistent enough to build against during Phase 3 task breakdown

### Phase Ordering Rationale

- **Measurement before optimization:** The CLV kill/keep gate is the only honest arbiter of model value. Starting Phase 2 model work before Phase 1 CLV evidence exists wastes engineering effort on a system that may have no edge.
- **Fix before extend:** The interaction feature duplication and diff_field_rank_quality bug are existing defects affecting live bets today. They must be resolved before new features are layered on.
- **Validate before automate:** Phase 3 automation is only reliable after those functions have been manually validated in Phases 1 and 2. Silent automation failures on a betting system have direct financial consequences.
- **Dependency chain respected:** CLV data is required by drift detection (Phase 3); settled CLV is required for edge-bucket analysis (Phase 1); interaction refactor is required before any Phase 2 feature additions; startlist resolution is required before team features.

### Research Flags

Phases needing deeper research during planning:
- **Phase 2:** XGBRanker probability calibration -- converting ranking scores to calibrated probabilities for Kelly staking (Platt scaling vs isotonic regression, score distribution shape from LambdaRank)
- **Phase 2:** Conditional market odds column handling -- when adding mkt_implied_prob at inference only, confirm the serving feature vector still aligns with feature_names.json from the trained model
- **Phase 3:** PCS country code to IANA timezone mapping -- confirm PCS country metadata is consistently structured enough to build a static lookup

Phases with standard patterns (no research phase needed):
- **Phase 1:** CLV computation and SQLite migration -- entirely within existing patterns (data/pnl.py idempotent migration, data/odds.py reuse, scipy Wilson CI). Well-documented methodology.
- **Phase 3:** APScheduler 3.x Flask integration -- well-documented pattern, confirmed stable API, <4.0 pin prevents regression. Discord webhook integration is straightforward.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All libraries verified via PyPI and local pip inspection; two-package addition confirmed; scipy coverage of all stats needs verified against specific function signatures |
| Features | HIGH | Feature scope derived from PROJECT.md gates, codebase audit, and industry CLV methodology literature; leakage risk on market odds is structural and well-understood |
| Architecture | HIGH | Based on direct codebase read of all affected modules (data/pnl.py, features/pipeline.py, data/odds.py, webapp/app.py); integration seams confirmed by existing code patterns |
| Pitfalls | HIGH | Grounded in confirmed codebase defects (interaction duplication confirmed in CLAUDE.md, diff_field_rank_quality confirmed in CLAUDE.md), established sports betting methodology (CLV, Kelly), and standard operational patterns (cron venv, timezone) |

**Overall confidence:** HIGH

### Gaps to Address

- **Drift detection thresholds:** The 5% calibration deviation threshold for live bets is a conservative starting guess (vs the 3% seen on the training set). Calibrate against the first 100 settled live bets.
- **Race start time estimation:** The 10:00 UTC default for European cycling stage starts needs empirical validation. Check whether the stage context fetcher can provide actual start times reliably enough to replace the default assumption.
- **DNF signal quality:** The historical status column in cache.db::results captures DNF/DNS/OTL, but reliability of DNF records across race types and years has not been audited. Run a coverage query before building the DNF feature.
- **data/bets.csv vs bets table divergence:** CLAUDE.md references data/bets.csv as the bet log, but data/pnl.py operates on SQLite. Before Phase 3 automation, confirm which is authoritative and whether the CSV is actively maintained or deprecated.
- **Pinnacle H2H DNF settlement rule:** Whether Pinnacle voids or settles as a win when the non-backed rider DNFs needs to be confirmed against published rules before implementing the void_on_dnf policy.

## Sources

### Primary (HIGH confidence)
- Local codebase audit: features/pipeline.py, data/pnl.py, data/odds.py, models/predict.py, models/benchmark.py, scripts/simulate_pnl.py
- CLAUDE.md and PROJECT.md -- confirmed known issues, phase gates, kill/keep thresholds, decision_log.md current best model configuration
- APScheduler PyPI 3.11.2 (https://pypi.org/project/APScheduler/) -- stable version, <4.0 API guarantee
- discord-webhook PyPI 1.4.1 (https://pypi.org/project/discord-webhook/) -- embed support confirmed
- XGBoost 3.0 changelog (https://xgboost.readthedocs.io/en/latest/changes/v3.0.0.html) -- Python sklearn API backward-compatible in 3.x
- XGBoost Learning to Rank docs (https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html) -- XGBRanker API confirmed in 3.2.0
- scipy.stats.binomtest docs (https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html) -- CLV significance testing

### Secondary (MEDIUM confidence)
- OddsJam CLV guide (https://oddsjam.com/betting-education/closing-line-value) -- CLV methodology, +1-2% benchmark for sharp markets
- Sports Insights statistical significance (https://www.sportsinsights.com/sports-investing-statistical-significance/) -- 200+ bet sample size for CLV precision at 95% CI
- NannyML PSI guide (https://www.nannyml.com/blog/population-stability-index-psi) -- PSI thresholds (0.1/0.2) from credit scoring literature applied to prediction monitoring
- ML in sports betting arXiv 2410.21484 (https://arxiv.org/html/2410.21484v1) -- calibration finding supporting CalibratedXGBoost choice

### Tertiary (LOW confidence)
- Race start time estimation (10:00 UTC default for European cycling) -- reasonable approximation; needs empirical validation
- Drift detection calibration threshold (5% for live vs 3% for training) -- conservative starting guess; calibrate against first 100 live settled bets

---
*Research completed: 2026-04-18*
*Ready for roadmap: yes*
