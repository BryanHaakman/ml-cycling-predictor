# Feature Landscape: PaceIQ v2.0 — Edge Validation & System Maturity

**Domain:** Sports betting intelligence — validation, model upgrades, and workflow automation for cycling H2H betting
**Researched:** 2026-04-18
**Scope:** Five feature domains for v2.0 only. Existing features (batch prediction, Kelly staking, P&L, Pinnacle load, name resolution, stage context) are already built and not re-researched here.

---

## Existing Pipeline Context

The pipeline being extended:
- ~424-feature XGBoost classifier (diff/absolute/H2H/interaction/startlist-relative)
- `bets` table in `cache.db` with schema: race_date, stage_url, rider_a/b_url, selection, decimal_odds, implied_prob, model_prob, edge, kelly_fraction, stake, status (pending/won/lost/void), payout, profit, model_used
- No `closing_odds`, `clv`, or `settled_at` columns exist yet
- `diff_field_rank_quality` is hardcoded to neutral 0.0 in the manual prediction path — a known calibration gap
- Interaction features duplicated in 3 places in `features/pipeline.py` — refactor required before adding new ones

---

## Feature Domain 1: CLV Tracking

### What It Does

Closing Line Value (CLV) measures whether model predictions beat Pinnacle's closing odds — the last market price before the race starts. The closing line is the sharpest, most information-dense price Pinnacle publishes, incorporating all publicly available information: sharp money, injury news, late scratches, weather. Positive CLV over a large sample is the industry-standard proof that a betting model has a real edge independent of short-term win/loss variance.

### Why It Matters for PaceIQ

With only 26 bets logged, PaceIQ cannot determine from win rate alone whether it has edge (95% CI of ±17% on win rate at that sample). CLV is a leading indicator: if the model consistently identifies value before the market, it has edge regardless of variance. If CLV is negative, no amount of feature engineering will fix it — the market already prices what the model knows.

The v2.0 kill criterion is: 200 live bets with average CLV < 0 → stop. CLV tracking is the primary instrument for this test.

### CLV Calculation

**Standard approach (vig-included CLV):**
```
CLV% = (model_implied_prob - closing_implied_prob) / closing_implied_prob * 100
```
where `closing_implied_prob = 1 / closing_decimal_odds`

**Preferred approach (vig-free CLV):**
Strip Pinnacle's margin from the closing odds before computing implied probability. For a two-outcome market:
```
vig_free_prob_A = raw_prob_A / (raw_prob_A + raw_prob_B)
CLV% = (model_prob - vig_free_closing_prob) / vig_free_closing_prob * 100
```
Vig-free CLV removes the bookmaker's take from the comparison, giving a cleaner signal on whether the model beats the true market consensus rather than just the padded price.

**Why Pinnacle closing line:** Pinnacle is the industry benchmark for closing line accuracy. They operate as a market maker with the sharpest bettors in the world, high limits, and minimal vig. Their closing line is more efficient than any other sportsbook. If PaceIQ beats Pinnacle's closing line, it has genuine edge. (HIGH confidence — corroborated by Pinnacle's own published research and industry consensus.)

### Table Stakes

| Behavior | Why Non-Negotiable | Complexity |
|----------|-------------------|------------|
| Capture closing odds snapshot per market at race start time | Without closing odds stored, CLV cannot be computed retroactively | Medium — cron job timed to race start |
| Add `closing_odds_a`, `closing_odds_b`, `clv`, `settled_at` columns to `bets` table | Data must exist for reporting; schema migration required | Low — ALTER TABLE |
| Auto-settle bets after results are ingested (won/lost from PCS results) | Manual settlement does not scale; CLV must be computed at settlement | Medium — post-race cron |
| CLV display in P&L tracker UI: per-bet CLV, rolling average CLV, CLV by edge bucket | The metric must be visible to inform staking decisions | Medium — SQL + Jinja templates |
| Alert when rolling 50-bet CLV drops below 0 | Early warning on model degradation; prevents continuing to bet on a broken system | Low — threshold check in cron |

### Differentiators

| Behavior | Value | Complexity |
|----------|-------|-----------|
| Vig-free CLV (strip margin before comparison) | More accurate edge measurement; removes Pinnacle's ~2.5% vig from the signal | Low — math only |
| CLV tracked separately by stage type (flat/mountain/TT) | Identifies whether edge is terrain-specific; informs model specialization decision | Low — GROUP BY |
| CLV vs time-to-race (e.g., bet placed 24h before vs 2h before) | Tests whether earlier bets capture more value before sharp money closes lines | Low — timestamp diff |

### Anti-Features

| Anti-Feature | Why Avoid |
|--------------|-----------|
| Historical odds reconstruction (backfill CLV on past bets) | Pinnacle historical odds are not freely available; self-computed odds from model are circular; the project explicitly chose forward CLV over backtest |
| Using book odds from non-Pinnacle sources as closing line benchmark | Introduces comparison error; soft books (DraftKings, FanDuel) have much wider margins and their closing lines are less efficient |
| CLV-based automated staking adjustment | Out of scope; staking policy is locked in Phase 1. CLV is an observation tool, not a controller in v2.0 |

### Dependencies on Existing Pipeline

- Requires: `bets` table (exists), schema migration to add `closing_odds_a`, `closing_odds_b`, `clv`, `settled_at`
- Requires: Closing-odds capture cron (new) — must fetch Pinnacle odds at race start time, not on-demand
- Requires: Post-race settlement cron (new) — reads PCS results, marks bets won/lost, computes CLV at settlement
- The existing `data/odds.py` Pinnacle client can be reused by the closing-odds cron

### Benchmarks

| Metric | Threshold | Source |
|--------|-----------|--------|
| Average CLV (vig-free) for sharp bettors | +1% to +2% in major markets; +3-5% in niche/prop markets | Industry consensus (Pinnacle research, OddsJam, Sharp Football Analysis) |
| PaceIQ kill threshold | CLV < 0% over 200 bets | PROJECT.md |
| PaceIQ keep threshold | CLV >= +1.5% over 100 bets | PROJECT.md |
| % of bets beating closing line (profitable threshold) | 55-60% for vig-free CLV | Multiple CLV guides |
| Sample size for statistical significance on CLV | 200+ bets for ±3% precision at 95% CI | Sports Insights |

---

## Feature Domain 2: Edge-Bucket ROI Analysis

### What It Does

Groups bets by predicted edge size (e.g., 5-8%, 8-12%, 12%+) and computes ROI, CLV, and win rate per bucket. This answers: "Is our edge real, and does it scale with predicted edge size?" A genuine edge model should show higher ROI in higher-edge buckets. A random-noise model will show flat or negative ROI across all buckets.

### Table Stakes

| Behavior | Why Non-Negotiable | Complexity |
|----------|-------------------|------------|
| Edge-bucket grouping in P&L report (0-5%, 5-8%, 8-12%, 12%+) | Core analysis; tells user where to set bet threshold and whether to widen the criteria | Low — SQL CASE WHEN |
| Sample count and ROI per bucket | Small buckets (N<20) are statistical noise; must show N prominently | Low — SQL aggregation |
| Win rate per bucket alongside ROI | ROI depends on odds; win rate is easier to interpret and validates edge independently | Low — SQL |
| Running/rolling ROI chart by time (weekly or monthly) | Stable ROI vs trending-down ROI are different risk profiles; time dimension is required | Medium — chart rendering |

### Differentiators

| Behavior | Value | Complexity |
|----------|-------|-----------|
| Confidence interval shown per bucket (±% at 95% CI) | Communicates statistical uncertainty; prevents overinterpreting small buckets | Low — scipy.stats |
| Edge-bucket breakdown by stage type (flat/mountain/TT) | Tests whether edge is terrain-specific; high value if stage specialization is planned | Low — add dimension |
| Profit factor (gross profit / gross loss) per bucket | Additional robustness metric used by professional sports bettors alongside ROI | Low — SQL |
| Kelly sizing efficiency: actual stake vs optimal stake per edge level | Tests whether quarter-Kelly is appropriately sized for different edge levels | Medium — requires historical Kelly amounts |

### Anti-Features

| Anti-Feature | Why Avoid |
|--------------|-----------|
| Monte Carlo simulation of expected profit curves | False precision; the project explicitly avoided synthetic backtesting in favor of forward CLV. Simulation results are self-referential (model probs → simulated odds → simulated P&L) |
| Automated bet threshold adjustment based on bucket ROI | Out of scope for Phase 1; staking policy lock is a human decision, not an automated optimization |

### Statistical Significance Requirements

A genuine edge at the 5-8% bucket requires approximately:
- 200+ bets to establish ±5% ROI precision at 95% CI
- 500+ bets to reduce that to ±3% precision
- 1000+ bets for reliable bucket-level analysis when bets are spread across 4+ buckets

This means Phase 1 (1-3 weeks) will produce preliminary signal only. The analysis report should always display confidence intervals and warn when N < 50 per bucket. (MEDIUM confidence — statistical power calculations are standard but exact thresholds depend on variance of cycling H2H odds.)

### Dependencies on Existing Pipeline

- Requires: `bets` table (exists), `edge` column (exists), `status` and `profit` columns (exist)
- Requires: CLV tracking (Domain 1) for full analysis; CLV per bucket is a key metric
- The `edge` column in `bets` is already computed as `model_prob - implied_prob` at bet placement — bucket grouping is purely a reporting layer

---

## Feature Domain 3: Model Features for Phase 2

### 3a. Market Odds as a Feature (Reverse Line Movement / Sharp Signal)

**What it is:** Add Pinnacle's opening odds (or pre-race odds at bet time) as a feature in the ML model, allowing the model to learn from the market's own probability estimate.

**Why it matters:** Pinnacle's implied probability encodes all publicly available information plus sharp bettor money flow. The difference between the model's prediction and the implied probability is exactly the edge being bet. Adding market odds lets the model learn: "When my raw prediction is X% but the market says Y%, which domain should I trust more?" Reverse Line Movement (when odds move against the betting direction — i.e., money comes in on side A but odds on A lengthen) is a sharp money signal.

**Table Stakes:**

| Behavior | Why Non-Negotiable | Complexity |
|----------|-------------------|------------|
| Opening Pinnacle implied probability as raw feature (`mkt_implied_prob_a`) | Directly encodes market consensus; the model can learn to agree or disagree with market | Low — already stored in bets; need to add to training features |
| Odds-model disagreement feature (`model_prob - mkt_prob`) | Captures the signal that prompted the bet; model can learn when disagreement is reliable vs noise | Low — derived feature |
| Line movement direction feature (opening vs closing: `closing_prob - opening_prob`) | Captures whether sharp money agreed or disagreed with the initial line | Medium — requires both opening and closing odds in training data |

**Differentiators:**

| Behavior | Value | Complexity |
|----------|-------|-----------|
| Time-of-day odds feature (hours before race that bet was placed) | Sharp money moves lines in the final 2-4 hours; earlier bets may have different characteristics | Low — timestamp diff |
| Multiple book consensus (if multi-book added in Phase 3) | Cross-book implied probability removes book-specific noise | High — requires Phase 3 multi-book infrastructure |

**Critical caveat — leakage risk:** Market odds at bet time are NOT available for historical training pairs (pre-v1.0 bets). This feature can only be used in a re-training run after sufficient live bets have been logged with associated odds. Attempting to use historical Pinnacle odds as training features requires historical odds data that does not exist in the current pipeline. Recommended approach: start using `mkt_implied_prob_a` as a live prediction feature first (zero leakage risk for live bets), then add it to re-training only when 500+ live bets with associated odds have been accumulated. (HIGH confidence on the leakage risk; MEDIUM confidence on the sample size threshold.)

**Dependencies on Existing Pipeline:**
- Requires: Pinnacle odds stored at bet placement time (partially exists — `decimal_odds` is stored; need to confirm opening vs closing distinction)
- Requires: Historical odds in training pairs — does NOT exist; this is a Phase 2 feature that needs forward data collection first
- Risk: Training/serving feature gap — if market odds are used in serving but not in training, model is seeing a novel feature distribution at inference

### 3b. Live Startlist Resolution (Fix `diff_field_rank_quality`)

**What it is:** Fix the known bug where `diff_field_rank_quality` is hardcoded to 0.0 (neutral) in the manual prediction path. Replace with real startlist-derived field quality computed from the actual riders registered for today's race.

**Why it matters:** `diff_field_rank_quality` is the #3 most important feature by XGBoost gain (after career_top10_rate and sprint×flat interaction). Setting it to neutral for every live prediction is a calibration error of known magnitude. In strong-field stages (Tour de France, Giro), the field percentile rank of a rider matters enormously.

**Table Stakes:**

| Behavior | Why Non-Negotiable | Complexity |
|----------|-------------------|------------|
| Fetch today's startlist via PCS for the race being predicted | Source of truth for who's actually in the race | Medium — `procyclingstats` startlist API |
| Look up each startlist rider in `cache.db` to get their career_top10_rate | Requires matching startlist names to DB rider URLs | Medium — name resolution (same pattern as Pinnacle name resolver) |
| Compute field percentile rank for rider A and rider B from startlist | Same logic already exists in the historical training path; extract as shared function | Low — refactor existing |
| Fall back to neutral 0.0 if startlist fetch fails | Graceful degradation; do not block prediction on PCS unavailability | Low |

**Differentiators:**

| Behavior | Value | Complexity |
|----------|-------|-----------|
| Cache startlist resolution for the session | Startlist does not change intraday; avoid re-fetching on each prediction | Low |
| Team-level features from startlist (team GC priority, number of helpers) | New feature class; see 3c below | High |

**Dependencies on Existing Pipeline:**
- Requires: Fix the 3-location interaction feature duplication in `features/pipeline.py` first — otherwise adding a new startlist path creates a 4th duplication
- Uses: Existing name resolver patterns from `data/name_resolver.py`
- Uses: Existing `build_feature_vector_manual` path — this is the path that needs fixing

### 3c. Team Strength Features

**What it is:** Features derived from the team composition present in today's startlist: team GC priority (is the team defending a classification lead?), teammate quality (are the domestiques strong enough to shelter the captain?), team numerical advantage in a mountain stage breakaway scenario.

**Why it matters:** Cycling is uniquely team-dependent compared to other sports. A rider with strong teammates in a mountain stage has materially different win probability than the same rider solo. Current model has no team features after the team features were reverted for leakage risk in an earlier experiment. The leakage was in post-race team data; pre-race roster data is safe.

**Table Stakes:**

| Behavior | Why Non-Negotiable | Complexity |
|----------|-------------------|------------|
| Team career_top10_rate (average of teammates from startlist) | Proxy for team quality; pre-race, no leakage | Medium — startlist + DB lookup |
| Team size in startlist (riders from same team registered today) | Larger teams can provide more protection; direct feature | Low — count from startlist |
| Team captain indicator (is this rider the team's highest-ranked by career_top10_rate?) | Captures whether rider has team support or is a domestique | Low — derived from above |

**Differentiators:**

| Behavior | Value | Complexity |
|----------|-------|-----------|
| Historical team success on terrain type (team flat/mountain win rate) | Team tactics vary by terrain; GC teams are strong in mountains, sprint trains in flat | High — requires team history aggregation |
| Team budget as proxy for team quality (WorldTour budget tiers) | Correlates with rider quality; static data, no leakage | Low — lookup table |

**Anti-Features:**

| Anti-Feature | Why Avoid |
|--------------|-----------|
| Post-race team result aggregation as feature | Leakage; this was the cause of the previous revert. Use pre-race roster only |
| Intra-race tactical decisions (breakaway composition, peloton control) | Not available pre-race; requires in-running data out of scope |

**Complexity:** HIGH. Team name resolution from startlist is a new name resolution problem (team names differ between PCS and Pinnacle's team display). Requires: startlist with team assignments, team→DB lookup, aggregation. Recommend implementing as a separate `features/team_features.py` module.

**Dependencies:** Requires 3b (live startlist) as a prerequisite.

### 3d. DNF Probability Model

**What it is:** A binary classifier that predicts probability of a rider not finishing (DNF) a stage, separate from the H2H win prediction. Used to adjust H2H predictions: if rider A has 15% DNF probability, the model's H2H prediction should be discounted accordingly.

**Why it matters:** H2H markets settle on the finisher placing higher. A DNF by one rider is typically a void or a push (depending on Pinnacle's rules). High-DNF stages (cobblestone classics, extreme mountain stages) have materially different dynamics than normal stages. The current model ignores DNF probability entirely.

**Table Stakes:**

| Behavior | Why Non-Negotiable | Complexity |
|----------|-------------------|------------|
| Historical DNF rate per rider (career DNF rate, recent DNF rate in last 12 months) | Primary DNF predictors; can be computed from existing `results` table | Low — SQL on existing data |
| Stage danger features: cobblestone flag, extreme profile, weather proxy | DNF rates spike on dangerous stages; existing race features partially capture this | Medium — add cobblestone/danger feature to race_features.py |
| DNF adjustment to H2H probability: `adjusted_prob = model_prob * (1 - dnf_prob_diff)` | Simple adjustment; full DNF classifier is Phase 2 work, adjustment is Phase 1 | Low — post-prediction math |

**Differentiators:**

| Behavior | Value | Complexity |
|----------|-------|-----------|
| Full DNF binary classifier (separate XGBoost) trained on historical DNF labels | More accurate than heuristic; captures interactions between rider DNF history and stage danger | High — new training pipeline |
| DNF probability displayed in prediction UI alongside H2H probability | Transparency; user sees when a prediction is high-edge but high-DNF-risk | Medium — UI change |

**Anti-Features:**

| Anti-Feature | Why Avoid |
|--------------|-----------|
| DNF prediction as the primary market to bet | PaceIQ is H2H only; DNF model is an adjustment, not a primary signal |
| Real-time DNF probability update during race | In-running data; out of scope |

**Complexity:** MEDIUM for heuristic DNF adjustment (use career_dnf_rate from existing data); HIGH for a full separate DNF classifier.

**Dependencies:** Uses existing `results` table (status column or rank=0/null for DNF). Check that DNF records are accurately captured in the current scraper before building on them.

### 3e. Stage Specialization (Separate Models per Stage Type)

**What it is:** Train separate models for flat stages, mountain stages, and time trials rather than a single model across all stage types. Each stage type favors different rider attributes (sprint power vs climbing vs TTing), and a single model must approximate this with interaction features.

**Why it matters:** Current model uses interaction features (e.g., `interact_diff_sprint_x_flat`) to capture terrain-specificity. Separate models would instead allow the feature selection and weighting to be fully terrain-specific. The top feature `interact_diff_sprint_x_flat` (0.038 gain) suggests the model is capturing terrain signal but through a rough proxy.

**Table Stakes (if implemented):**

| Behavior | Why Non-Negotiable | Complexity |
|----------|-------------------|------------|
| Stage type classification from existing `profile_icon` field | Already available; `p1`=flat, `p5`=mountain, `p7`=TT, `p2/p3/p4`=medium | Low — lookup table |
| Separate training sets per stage type with minimum sample size check | Small sample types (TTT, prologue) fall back to the global model | Low — filter + fallback |
| Routing logic at prediction time: select model based on stage type | Prediction UI must know which model to load | Low — model registry |

**Differentiators:**

| Behavior | Value | Complexity |
|----------|-------|-----------|
| Stage-type-specific feature selection (top 150 features per model) | Different features matter on flat vs mountain; single model must use one feature set for all | High — 3x training time |
| CLV tracked separately per model (flat/mountain/TT) | Tests whether edge is concentrated in a specific terrain type | Low — GROUP BY in reporting |

**Anti-Features:**

| Anti-Feature | Why Avoid |
|--------------|-----------|
| Sub-specialization beyond 3 types (e.g., "hilly classics" vs "sprint stages") | Sample size becomes insufficient; diminishing returns vs complexity |
| Separate models for one-day races vs stage races | Sample imbalance; one-day races are already captured by existing features |

**Complexity:** HIGH. Tripling training infrastructure, model artifacts, and routing logic. Best deferred to Phase 2 after Phase 1 validates that edge exists at all. If CLV is positive in Phase 1, this is the highest-leverage model improvement.

**Dependencies:** Requires Phase 1 CLV tracking to validate whether specialization is even warranted.

### 3f. XGBRanker (Pairwise Ranking Objective)

**What it is:** Replace the binary classification objective (`binary:logistic`) with a pairwise ranking objective (`rank:pairwise` or `rank:ndcg` via XGBRanker). Instead of predicting P(A beats B), the model learns to rank all riders in a stage by predicted finishing position, then H2H predictions are derived from the ranking.

**Why it matters:** H2H prediction is fundamentally a ranking problem. A binary classifier treats each pair independently; a ranker can see that "A ranks above B, B ranks above C, therefore A ranks above C" and maintain transitivity. XGBRanker also trains on more information per stage (all possible orderings of finishers vs just paired samples).

**Table Stakes (if implemented):**

| Behavior | Why Non-Negotiable | Complexity |
|----------|-------------------|------------|
| Reformulate training data as per-stage ranking groups | XGBRanker requires `group` argument specifying stage membership | Medium — data restructuring |
| Calibrate ranking scores to probabilities | Raw ranker scores are not probabilities; calibration layer required | Medium — Platt scaling or isotonic regression |
| Accuracy and ROC-AUC benchmark vs current CalibratedXGBoost | Must improve on 69.7% accuracy / 0.772 ROC-AUC to justify added complexity | Medium — benchmark run |

**Anti-Features:**

| Anti-Feature | Why Avoid |
|--------------|-----------|
| XGBRanker without probability calibration | Kelly criterion requires probabilities, not ranking scores; uncalibrated ranker is unusable for staking |
| Deploying XGBRanker before validating CLV on current model | Phase 2 model upgrade is gated on Phase 1 CLV validation |

**Complexity:** HIGH. Requires data pipeline restructuring, calibration layer, and benchmarking. Priority 7 in PROJECT.md — behind startlist fix, DNF model, and market odds feature.

---

## Feature Domain 4: Pre-Race Reports

### What It Does

Automated markdown report generated 2 hours before a stage start. Contains: today's H2H matchups with model predictions, edge assessment, staking recommendations, stage context, and key risk flags (DNF-prone pairs, low-sample matchups, line movement alerts).

### Table Stakes

| Behavior | Why Non-Negotiable | Complexity |
|----------|-------------------|------------|
| Trigger via cron at T-2h before stage start | Report must exist before user sits down to bet; manual generation is failure-prone | Medium — cron scheduling with stage start time lookup |
| List of all today's H2H matchups with: model probability, Pinnacle implied probability, edge %, recommended stake | The core decision-making data; everything else is context | Medium — run prediction pipeline + format output |
| Act signals highlighted (edge > 8%), flag signals noted (edge > 5%), no-bet shown without stake | User should be able to scan and act in < 5 minutes | Low — threshold formatting |
| Stage context summary (distance, profile, climb count, key climbs) | Context for interpreting predictions; already available from stage context fetcher | Low — reformat existing data |
| Save to `reports/YYYY-MM-DD-stage-name.md` for audit trail | Historical report archive; useful for post-race review | Low — file write |

### Differentiators

| Behavior | Value | Complexity |
|----------|-------|-----------|
| CLV summary from most recent 30 bets in report header | Running status check; user sees if model is performing before placing new bets | Low — SQL query |
| Line movement alert: odds moved >3% since report generation | Sharp money moving lines is a signal; late-moving lines are higher risk | Medium — compare report-time odds vs current odds |
| DNF risk flag on matchups where either rider has career DNF rate > 10% | Contextual risk; user can decide whether to bet high-DNF pairs | Low — lookup from bets/results |
| Historical H2H record for the matchup pair | Narrative context; not a strong signal statistically but user-facing value | Low — SQL on results table |

### Anti-Features

| Anti-Feature | Why Avoid |
|--------------|-----------|
| LLM-generated narrative text per matchup | Adds dependency, latency, API cost, and hallucination risk. Structured data is more reliable and faster to scan |
| Email/SMS delivery of report | Adds external service dependency. Discord webhook is simpler if push notification is needed; Markdown file to a watched directory is the simplest |
| Report generated from live MCP server data (not `procyclingstats` lib) | MCP server is in-session only; VPS cron cannot use it. Pipeline must use `procyclingstats` lib directly |

### Report Structure (Recommended)

```
# PaceIQ Pre-Race Report — 2026-04-18: Tour de Romandie Stage 3

**Stage:** 185km, Flat (p1), 3 climbs, 1200m vert
**Status:** CLV trailing 30 bets: +2.1% | Bets pending: 3 | Bankroll: $983

## Act Now (Edge > 8%)
| Matchup | Model | Market | Edge | Stake |
| A. Jakobsen vs B. Ewan | 62.1% | 54.3% | +7.8% | $24 (2.4%) |

## Worth Watching (Edge 5-8%)
...

## All Markets
...

## Risk Flags
- A. Jakobsen: career DNF rate 8.2% (above average for sprinters)
- Low sample: K. Lazkano vs T. Geoghegan Hart — 0 prior H2H meetings
```

### Dependencies on Existing Pipeline

- Requires: Stage context fetcher (exists in `intelligence/stage_context.py`)
- Requires: CLV tracking (Domain 1) for the status line
- Requires: Pinnacle odds fetch (exists in `data/odds.py`)
- Requires: Model prediction pipeline (exists in `models/predict.py`)
- Does NOT require: Any Phase 2 model upgrades; the report can use the current CalibratedXGBoost

---

## Feature Domain 5: Drift Detection

### What It Does

Automated monitoring that detects when the model's calibration or CLV performance has deteriorated from baseline. Triggers an alert when degradation is detected, enabling the user to investigate before continuing to bet on a degraded model.

### Why Drift Happens in This Domain

Three drift mechanisms are relevant to PaceIQ:

1. **Concept drift:** The relationship between cycling features and race outcomes changes (new dominant teams, rule changes, race calendars shifting). The model trained on 2018-2025 data may become stale as the sport evolves.
2. **Covariate drift:** The distribution of input features shifts (e.g., race calendar moves to cobblestone classics, model sees more mountain features than it trained on).
3. **Market efficiency improvement:** Pinnacle's model gets better over time, shrinking or eliminating the exploitable gap. CLV trending toward 0 is the signal for this.

### Table Stakes

| Behavior | Why Non-Negotiable | Complexity |
|----------|-------------------|------------|
| Rolling CLV alert: 50-bet rolling average CLV < 0 triggers alert | Primary performance signal; catches model degradation before it costs money | Low — SQL window function + threshold |
| Calibration check: compare model probability bins vs actual win rates on recent bets | Monthly check; bins should be within ±5%. Wider deviation = recalibration needed | Medium — requires 200+ settled bets for meaningful calibration check |
| Weekly cron that runs both checks and logs results to `data/drift_log.jsonl` | Automated monitoring; no manual effort required | Low — script + cron |

### Differentiators

| Behavior | Value | Complexity |
|----------|-------|-----------|
| Population Stability Index (PSI) on input features: compare recent live prediction features vs training distribution | Catches covariate drift before it manifests in CLV decline; early warning | Medium — requires storing feature values at prediction time |
| Kolmogorov-Smirnov test on prediction score distribution (recent vs training) | Detects shift in model score distribution; complements CLV tracking | Low — scipy.stats |
| Auto-trigger retraining when drift thresholds exceeded (PSI > 0.2, CLV 50-bet < -1%) | Full automation; removes human monitoring burden | High — requires retraining pipeline to be automated, which requires fresh data and compute |

### Anti-Features

| Anti-Feature | Why Avoid |
|--------------|-----------|
| Automated retraining without human review | Model could retrain on bad data; in betting, a bad model is worse than no model. Alert and recommend, but require human decision to retrain |
| CUSUM chart on prediction scores without calibration context | CUSUM detects score distribution shift but cannot distinguish calibration drift from concept drift. CLV is a more actionable signal |
| Monitoring every feature individually (all 150 features) | Feature-level PSI monitoring at 150 features generates noise; monitor key feature groups (career quality, form, terrain) or the score distribution |

### PSI Thresholds (Standard Industry Values)

| PSI Value | Interpretation | Action |
|-----------|---------------|--------|
| < 0.1 | No significant change | Monitor, no action |
| 0.1 – 0.2 | Moderate shift | Investigate, consider retraining |
| > 0.2 | Significant shift | Recommend retraining |

PSI thresholds are from credit scoring industry where the method originated. They apply directly to prediction score monitoring. (HIGH confidence — well-documented standard across ML monitoring literature.)

### Dependencies on Existing Pipeline

- Requires: CLV tracking (Domain 1) — drift detection is downstream of CLV computation
- Requires: Sufficient settled bets (calibration check needs 200+)
- Optional: Feature value logging at prediction time (not currently stored) — needed for PSI on input features

---

## Feature Priority Summary

### Table Stakes (must have in v2.0)

| Feature | Domain | Complexity | Phase |
|---------|--------|------------|-------|
| Closing-odds capture cron | CLV Tracking | Medium | 1 |
| `bets` table schema migration (add CLV columns) | CLV Tracking | Low | 1 |
| Post-race settlement + CLV computation cron | CLV Tracking | Medium | 1 |
| CLV display in P&L UI | CLV Tracking | Medium | 1 |
| Edge-bucket ROI report with sample counts | Edge Buckets | Low | 1 |
| Rolling CLV chart by time | Edge Buckets | Medium | 1 |
| Live startlist resolution (fix field_rank_quality=0.0) | Startlist Fix | Medium | 2 |
| Market odds as prediction feature (live serving only) | Market Odds | Low | 2 |
| Pre-race report generation with act/flag/watch tiers | Pre-Race Reports | Medium | 3 |
| Rolling CLV drift alert (50-bet window) | Drift Detection | Low | 3 |
| Monthly calibration check cron | Drift Detection | Medium | 3 |

### Differentiators (add if Phase 1 CLV is positive)

| Feature | Domain | Complexity | Phase |
|---------|--------|------------|-------|
| Vig-free CLV computation | CLV Tracking | Low | 1 |
| Team strength features from startlist | Team Features | High | 2 |
| DNF probability adjustment | DNF Model | Medium | 2 |
| Stage-type specialization (3 models) | Stage Specialization | High | 2 |
| XGBRanker as alternative objective | Ranking Model | High | 2 |
| Market odds in training (after 500+ live bets) | Market Odds | Medium | 3 |
| PSI monitoring on score distribution | Drift Detection | Low | 3 |
| Line movement alert in pre-race report | Pre-Race Reports | Medium | 3 |

### Anti-Features (explicitly excluded)

| Anti-Feature | Reason |
|--------------|--------|
| Historical odds backtest / synthetic CLV reconstruction | Circular; project explicitly chose forward CLV |
| Automated bet placement | Permanently manual on Pinnacle |
| LLM narrative text in reports | Hallucination risk, latency, API cost |
| Automated retraining without human review | Betting on a bad model is worse than not betting |
| CLV tracking against non-Pinnacle closing lines | Less efficient markets give misleading CLV signal |
| Full CUSUM monitoring on 150 individual features | Noise; monitor score distribution and CLV instead |

---

## Feature Dependencies (Build Order)

```
Schema migration (CLV columns)
        |
        v
Closing-odds capture cron ──────────────────────────────────┐
        |                                                    |
        v                                                    v
Post-race settlement + CLV computation              Edge-bucket ROI report
        |
        v
CLV display in P&L UI
        |
        v
[PHASE 1 GATE: CLV >= +1.5% over 100 bets]
        |
        v
Fix interaction feature duplication (pipeline.py)
        |
        ├─→ Live startlist resolution
        │         |
        │         └─→ Team strength features (optional)
        │
        ├─→ Market odds as serving feature
        │
        └─→ DNF heuristic adjustment
                  |
                  └─→ Full DNF classifier (optional)
                            |
                            └─→ Stage specialization (3 models)
        |
        v
Pre-race report generation
        |
        v
Drift detection cron (rolling CLV alert + calibration check)
```

---

## Sources

- CLV methodology: [Closing Line Value (CLV) demystified — Pinnacle Odds Dropper](https://www.pinnacleoddsdropper.com/blog/closing-line-value--clv-demystified-by-expert-joseph-buchdahl), [OddsJam CLV guide](https://oddsjam.com/betting-education/closing-line-value), [Sharp Football Analysis CLV guide](https://www.sharpfootballanalysis.com/sportsbook/clv-betting/)
- CLV benchmarks: [Bettor Edge CLV](https://www.bettoredge.com/post/what-is-closing-line-value-in-sports-betting), [Gambling Nerd CLV](https://www.gamblingnerd.com/nerd-nook/closing-line-value/), [VigFree Analytics CLV Calculator](https://vigfreeanalytics.com/calculators/closing-line-value)
- Edge-bucket analysis and sample size: [Sports Insights statistical significance](https://www.sportsinsights.com/sports-investing-statistical-significance/), [Punter2Pro sample size](https://punter2pro.com/sample-size-betting-results-analysis/)
- Cycling features: [Determinants of Cycling Performance — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC7271082/), [Weighted team contributor analysis — arXiv](https://arxiv.org/html/2602.11831)
- ML in sports betting: [Systematic Review of ML in Sports Betting — arXiv](https://arxiv.org/html/2410.21484v1)
- Sharp money and line movement: [SignalOdds odds movement](https://signalodds.com/blog/mastering-odds-movement-decoding-line-shifts-with-signalodds-realtime-tracker), [Bettor Edge line movement](https://www.bettoredge.com/post/tracking-line-movement-for-market-inefficiencies)
- Drift detection and PSI: [NannyML PSI guide](https://www.nannyml.com/blog/population-stability-index-psi), [Towards Data Science drift detection](https://towardsdatascience.com/how-to-detect-model-drift-in-mlops-monitoring-7a039c22eaf9/), [arXiv calibration CUSUM](https://arxiv.org/abs/2510.25573)
- XGBRanker: [XGBoost Learning to Rank docs](https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html)
- Calibration and model performance: [ML in sports betting — model calibration finding: 69.86% higher returns](https://arxiv.org/html/2410.21484v1)
