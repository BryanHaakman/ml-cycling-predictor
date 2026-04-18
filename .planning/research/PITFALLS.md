# Domain Pitfalls: PaceIQ v2.0 Edge Validation & System Maturity

**Domain:** CLV tracking, model upgrades, and automation added to an existing cycling H2H betting intelligence system
**Researched:** 2026-04-18
**Overall confidence:** HIGH (pitfalls grounded in actual codebase, confirmed tech debt, and established sports betting methodology)

---

## Quick Reference Table

| Risk | Likelihood | Impact | Phase |
|------|-----------|--------|-------|
| CLV captured too early — odds still moving | HIGH | HIGH | 1 (Validate Edge) |
| Closing odds not snapshotted at precise race start | HIGH | HIGH | 1 / 3 (Automate) |
| False precision: CLV reported to 3 decimal places on 26 bets | HIGH | MEDIUM | 1 (Validate Edge) |
| Edge-bucket ROI with N<30 per bucket looks definitive | HIGH | HIGH | 1 (Validate Edge) |
| Survivorship bias from only logging bets that felt good | HIGH | HIGH | 1 (Validate Edge) |
| Market odds as feature introduces look-ahead leakage in training | CRITICAL | CRITICAL | 2 (Model Upgrade) |
| `build_feature_vector_manual` silently missing 4 interaction groups | HIGH | HIGH | 2 (Model Upgrade) |
| Calibration regresses silently after model retraining | MEDIUM | HIGH | 2 (Model Upgrade) |
| Training/serving skew from `diff_field_rank_quality` always 0.0 in live path | HIGH | HIGH | 2 (Model Upgrade) |
| Race start timezone wrong → closing-odds cron fires late | HIGH | CRITICAL | 3 (Automate) |
| Cron silently skips on VPS due to venv not activated | HIGH | HIGH | 3 (Automate) |
| Settlement script marks DNF as loss instead of void | MEDIUM | MEDIUM | 3 (Automate) |
| Negative Kelly edge passed through, stake computed as positive | MEDIUM | HIGH | 1 (Validate Edge) |
| Correlated bets (same stage, multiple matchups) violate Kelly independence | HIGH | HIGH | All |
| Statistical significance: 200 bets is still under-powered for CLV signal | HIGH | HIGH | 1 (Validate Edge) |
| simulate_pnl.py used as evidence of edge — it uses model-derived synthetic odds | HIGH | CRITICAL | 1 (Validate Edge) |

---

## Critical Pitfalls

Mistakes that silently corrupt CLV, risk financial loss, or require rewrites.

---

### Pitfall 1: Market Odds as Feature Introduces Look-Ahead Leakage in Training

**What goes wrong:** Adding Pinnacle implied probability as a training feature (Priority 6 in the project plan) is the most dangerous operation in Phase 2. During training, you only have _historical_ odds if you've stored them. If you use any odds that were available at or after race completion, you are leaking future market information into the model. Even pre-race odds from a historical scrape can be leaky if they were recorded during a period when sharp money had already moved the line based on real-world information (rider injury news, team announcements).

**Why it happens:** The temptation is to use `implied_prob` already stored in `data/bets` (the `implied_prob` column at bet time). But that's a convenience field from your own bet log — not a systematic historical odds dataset. If you reconstruct historical implied probs from `odds_log.jsonl`, the timestamps may be after lineup news was already public, injecting soft future information.

**Consequences:** The model appears to gain 2–4% accuracy from market odds — but that gain is partially or fully spurious leakage. Live performance will regress because the feature is computed from _current_ odds at prediction time, while training saw odds that reflected pre-race information the feature pipeline didn't explicitly include. The calibration will also shift because the model has learned to trust market odds as a prior, but market odds at prediction time include sharp money the model hasn't been trained to replicate.

**Prevention:**
- Only use pre-bet-placement odds as a training feature — snapshot must be taken at a _consistent_ time horizon before race start (e.g., exactly T-2h) for all training rows and live predictions.
- For historical training rows, you have no systematic historical odds — meaning you cannot add this feature to training data until you have run the odds-snapshot cron for at least one full season and have a consistent dataset.
- Short-term safe alternative: include market odds _only_ at inference time as a calibration input, not as a model feature. Apply a post-prediction odds-informed Bayesian update rather than baking market odds into XGBoost.
- Log the Phase 2 decision in `decision_log.md` explicitly: "market odds feature deferred to Phase 2+ pending historical odds corpus."

**Detection:** Train two models: one with and one without the market odds feature. If the with-odds model shows > 3% accuracy gain on historical data but only 0.5% gain on forward bets, leakage is the likely cause.

---

### Pitfall 2: Closing Odds Not Captured at the Correct Moment

**What goes wrong:** CLV = (closing_odds / bet_odds - 1) is only meaningful if `closing_odds` is the true _closing_ line — the odds immediately before the race goes in-running and Pinnacle suspends the market. Capturing odds 60 minutes before race start is not closing odds; it is pre-race odds. Pinnacle's closing line is typically 30–5 minutes before the off, after lineup sheets are confirmed and sharp bettors have moved the line.

**Why it happens:** The cron trigger for "closing odds capture" is scheduled by race start time. But:
1. Race start times from PCS are the scheduled start time, not the actual off time — these can diverge by 5–30 minutes.
2. The Pinnacle market closes asynchronously — it may suspend before the official start, sometimes much earlier for H2H specials.
3. The guest API returns current offered odds, not a "last traded" price. If the market is already suspended when the cron runs, you get no data.

**Consequences:** CLV is computed against stale pre-race odds rather than true closing odds. The metric appears better (or worse) than reality. A model with genuine edge appears to have no CLV because the closing line was sharper than what you captured.

**Prevention:**
- Capture odds at multiple time points: T-24h (opening), T-2h (pre-race), T-30min (near-closing). Store all three. Use the latest non-suspended snapshot as "closing."
- Store a `market_suspended` boolean alongside each odds snapshot. If suspended, the last non-suspended snapshot is closing.
- For Phase 3 automation, build the closing-odds scraper to poll every 10 minutes in the 2-hour window before race start rather than a single snapshot.
- Cross-reference with stage context to get actual race start time — use PCS stage data not Pinnacle display string.

**Detection:** Query `odds_log.jsonl` for any record where the snapshot timestamp is > 90 minutes before race start. Flag as non-closing.

---

### Pitfall 3: `simulate_pnl.py` Used as Evidence of Real Edge

**What goes wrong:** `scripts/simulate_pnl.py` generates synthetic bookmaker odds by adding a 5% margin to model probabilities with noise: `simulate_market_odds(model_probs, margin=0.05, noise_std=0.08)`. This means the simulated CLV is circular — the model is betting against odds derived from its own probabilities. Any positive ROI from this simulation is mathematically guaranteed when the model has calibrated probabilities and the simulated margin is lower than your actual edge calculation.

**Why it happens:** The script was built as a development tool before real bets existed. Its primary failure mode is being referenced in a progress review as evidence that PaceIQ has a real edge, when in fact it proves nothing about real market behaviour.

**Consequences:** Proceeding to Phase 2 (model upgrade) based on `simulate_pnl.py` results rather than forward CLV is the most likely single cause of wasted Phase 2 effort. The kill/keep gate ("200 live bets with average CLV < 0 → stop") exists precisely because the simulation is not a substitute.

**Prevention:**
- Deprecate or clearly label `simulate_pnl.py` as a development tool only. Add a prominent warning comment at the top of the file: "SYNTHETIC ODDS — NOT A REAL BACKTEST. DO NOT USE AS EDGE EVIDENCE."
- Replace all references to simulation results in dashboards and reports with live CLV tracking.
- The Phase 1 gate (CLV >= 1.5% over 100+ bets) must be computed from real Pinnacle closing odds, not simulated odds.

**Detection:** Grep for `simulate_pnl` in any analysis or reporting code. Any reference outside the script itself is a red flag.

---

### Pitfall 4: Training/Serving Skew from `diff_field_rank_quality` Hardcoded to 0.0

**What goes wrong:** During training, `diff_field_rank_quality` is computed from actual startlist data (all riders in that stage from the results table) and ranges roughly -0.8 to +0.8, with importance rank #3. In the live serving path (`build_feature_vector_manual`), this feature is hardcoded to 0.0 — the model receives a value it almost never saw in training for this feature.

**Why it happens:** The hardcoded neutral is a deliberate temporary choice from v1.0, documented as a known issue. But when Phase 2 adds startlist resolution (Priority 4: "fix field_rank_quality=0.5"), there is a risk that the fix is partial — e.g., it resolves the startlist for one rider but not both, or resolves it from Pinnacle data but computes percentile against a different reference population than training used.

**Consequences:** If startlist resolution is implemented incorrectly, the feature goes from "always wrong but consistently wrong" (0.0 bias) to "sometimes right, sometimes wrong in unpredictable ways." A model trained on consistent-wrong is arguably more predictable than one receiving inconsistent features. Inconsistent features cause the model to misfire on exactly the high-confidence predictions where startlist quality matters most (favourite vs weak-field bet).

**Prevention:**
- When fixing `diff_field_rank_quality` in Phase 2, the percentile must be computed against the _same reference population_ used during training: all finishers in that stage from the results table. For live predictions, the equivalent is all resolved riders in the Pinnacle market for that race.
- Add a unit test: given a known startlist, verify that `diff_field_rank_quality` for Tadej Pogacar vs a domestique produces a value close to +0.8 (Pogacar is near the top of most fields).
- Log the exact field size and field quality values alongside every live prediction so skew is detectable in production.

**Detection:** Compare the distribution of `diff_field_rank_quality` in training data vs live predictions. If training shows a roughly uniform distribution and live shows all zeros, the fix hasn't landed yet.

---

### Pitfall 5: Kelly Criterion Applied to Correlated Bets on the Same Stage

**What goes wrong:** When you bet multiple H2H matchups from the same stage (e.g., Pogacar vs Vingegaard AND Roglic vs Hindley on the same mountain stage), the outcomes are correlated — a harder-than-expected climb affects all matchups in the same direction. Standard Kelly assumes bet outcomes are independent. Betting quarter Kelly on each of four correlated matchups in the same stage is effectively betting full Kelly on the stage outcome.

**Why it happens:** The Kelly implementation in `models/predict.py` computes `kelly_fraction` per matchup independently. There is no cross-matchup correlation adjustment. The batch prediction UI shows all matchups with independent Kelly sizes. A user following all recommendations from a single "Load from Pinnacle" session may be placing 4–6 bets on the same 4-hour event.

**Consequences:** Effective bankroll exposure on a single stage can be 3–5x the intended per-bet cap. A single stage outcome (mountain finish where all favourites blow up, or a bunch sprint that collapses) correlates all bets in the same direction and produces an amplified loss or gain.

**Prevention:**
- Add a per-stage exposure cap: total staked across all matchups for the same stage should not exceed 2x the per-bet cap (e.g., max 10% bankroll total for any single stage, regardless of how many matchups are bet).
- In the batch prediction UI, display aggregate stage exposure alongside individual Kelly sizes. Flag when total stage exposure exceeds 5% of bankroll.
- In `data/pnl.py`, add a query that returns active stake grouped by `stage_url`. If a new bet's stage already has > threshold active stake, surface a warning before placement.

**Detection:** Query `SELECT stage_url, SUM(stake) FROM bets WHERE status = 'pending' GROUP BY stage_url`. Any stage with total > 2x bet cap is over-exposed.

---

## Moderate Pitfalls

---

### Pitfall 6: Edge-Bucket ROI Analysis Overfits to Small Samples

**What goes wrong:** Grouping bets by edge bucket (5–8%, 8–12%, 12%+) and reporting ROI per bucket sounds like rigorous analysis. With fewer than 30 bets per bucket, the confidence intervals on ROI are so wide that every bucket's ROI is statistically consistent with zero. The natural variance of H2H cycling betting (roughly 50% win rate at even odds) means you need ~100 bets per bucket before bucket ROI estimates converge to within ±5%.

**Why it happens:** 26 total bets at project start means you have maybe 8–10 bets in the 8–12% bucket and 3–4 in the 12%+ bucket. A few wins or losses in the high-edge bucket swing ROI from -30% to +40% due to sampling noise, not signal.

**Consequences:** The Phase 1 gate ("CLV >= 1.5% over 100+ bets") can be satisfied by CLV even when ROI by bucket is noise-dominated. Reporting bucket ROI as if it shows edge concentration is misleading and may incorrectly validate or invalidate a segment of the edge.

**Prevention:**
- Always display the 95% confidence interval on ROI alongside the point estimate: `ROI ± 1.96 * sqrt(p*(1-p)/n)` (Wilson interval for win rate).
- Do not interpret bucket ROI until N >= 30 per bucket. Label buckets with N < 30 as "insufficient data."
- Prefer CLV as the primary signal for Phase 1 (it requires no outcome results and converges faster than ROI). Use ROI as a secondary, slower-converging confirmation.
- Separate the "is there any edge?" question (CLV > 0 over 100+ bets) from "where is the edge concentrated?" question (bucket ROI, requires 30+ per bucket).

**Detection:** Before any bucket ROI report, assert `len(bucket) >= 30`. If not, display "N={n}, insufficient for reliable estimate" rather than an ROI number.

---

### Pitfall 7: Survivorship Bias from Selective Bet Logging

**What goes wrong:** If only bets that were actually placed are logged, but the model surfaced edges on matchups that were skipped (e.g., "I didn't like this one" or "odds were gone when I checked"), then the sample of logged bets is not representative of all model-flagged edges. The logged bets are the ones that felt most confident — introducing survivorship bias into CLV analysis.

**Why it happens:** The bet logging flow requires manual action (the user clicks "Log Bet" in the Flask UI). Bets where the odds disappeared, where the user was uncertain, or where the edge was borderline are not logged — even though the model recommended them. The gap between model recommendations and logged bets is unmeasured.

**Consequences:** Average CLV in the log appears higher than the model's true CLV because the worst-case recommendations (where the market was efficient and your edge was an illusion) were never bet. A model with zero true edge can appear to have positive CLV if the user consistently avoids the recommendations where odds have already moved against them.

**Prevention:**
- Log all model predictions where edge > 5%, regardless of whether a bet was placed. Add a `recommendation_status` field: "bet_placed," "passed_no_odds," "passed_discretion," "passed_market_moved."
- CLV analysis should be run on the full recommendation log, not just placed bets. Compare CLV of placed vs passed recommendations — systematic divergence indicates cherry-picking.
- If the recommendation log shows that passed bets have lower closing-line implied probability (the market moved further against you on skipped ones), that is evidence of information leakage in your bet selection.

**Detection:** Add a separate table or JSONL log for model recommendations (edge > 5%), distinct from placed bets. Query for divergence between recommended and placed sets.

---

### Pitfall 8: Calibration Regresses After Retraining Without Bin-Level Validation

**What goes wrong:** The current model passes calibration ("all bins within 3%"). Phase 2 retraining (adding new features, changing train/test split, retraining on additional 2025–2026 data) can silently break calibration. The most common pattern: calibration is only checked on the held-out test set, not on the specific probability ranges where bets are actually placed (65–80% probability).

**Why it happens:** `sklearn.metrics.brier_score_loss` and ROC-AUC are reported globally. Calibration at the tails (very high or very low predicted probability) can be fine globally but broken specifically in the 60–75% range where Pinnacle H2H markets sit. A model can have good global calibration and bad local calibration in the betting range.

**Consequences:** The Kelly staking math assumes calibrated probabilities. If the model says 72% but true frequency is 63%, Kelly sizes are systematically too large and expected ROI is negative even if there appears to be edge against the market.

**Prevention:**
- After every retraining run, run `scripts/eval_calibration.py` and verify calibration at the specific bins that overlap with your betting range: [0.55, 0.60], [0.60, 0.65], [0.65, 0.70], [0.70, 0.75], [0.75, 0.80].
- Add a calibration gate to the Phase 2 completion criteria: "no bin in the 55–80% range deviates by more than 3 percentage points." Block deployment if calibration fails.
- Log calibration bin results in `decision_log.md` after every training run.
- Compare calibration on time-based test split specifically (2025–2026), not only on the stratified split — the stratified split can show better calibration than time-based due to data distribution differences.

**Detection:** Plot reliability diagram (predicted vs actual frequency per 10-bin quantile) for every retrained model. Save the plot to `models/trained/calibration_plot_{date}.png`.

---

### Pitfall 9: CLV False Precision — Reporting 1.87% When You Mean "Probably Positive"

**What goes wrong:** With 26 bets (and realistically 80–100 bets through most of Phase 1), the 95% confidence interval on mean CLV is roughly ±2–3 percentage points. Reporting "average CLV = 1.87%" implies precision that doesn't exist. The true CLV could be anywhere from -0.5% to +4.2% with 95% confidence.

**Why it happens:** Mean CLV per bet is trivial to compute (`mean(closing_implied_prob / bet_implied_prob - 1)`). The confidence interval requires bootstrap sampling or a standard error estimate that most dashboard implementations omit.

**Consequences:** The Phase 1 kill gate ("CLV < 0 → stop") may be triggered or ignored incorrectly based on a point estimate that is inside the confidence interval of zero. You stop a viable system or continue a non-viable one based on noise.

**Prevention:**
- Compute and display 95% bootstrap confidence interval on mean CLV alongside the point estimate.
- The kill gate should be: "lower bound of 95% CI on mean CLV < 0 at N >= 200" (not just "mean CLV < 0 at any point").
- The keep gate should be: "lower bound of 95% CI on mean CLV >= 1.0% at N >= 100."
- Display a "data maturity" indicator in the P&L dashboard: "Insufficient data (N < 50)," "Preliminary (N 50–100)," "Indicative (N 100–200)," "Reliable (N 200+)."

**Detection:** Any CLV report that omits a confidence interval or sample size is a red flag. Enforce N display on every CLV number.

---

### Pitfall 10: Race Timezone Errors Cause Cron to Fire After Market Suspension

**What goes wrong:** PCS race start times are listed in local race time with no explicit timezone metadata. A stage in Spain starts at 12:00 CEST (UTC+2). If the closing-odds cron is scheduled assuming UTC, it fires at 12:00 UTC — two hours after the market has already been suspended. The closing odds record is empty or shows suspended market.

**Why it happens:** The VPS runs on UTC. `scrape_log` and `stages` table dates are stored as `TEXT` without timezone. Race times from PCS HTML are scraped as local-time strings with no TZ annotation. The automation layer must derive UTC time from (local time, race location, calendar date) — all of which require a lookup that doesn't currently exist in the pipeline.

**Consequences:** The closing-odds cron either never captures real closing odds (fires too late) or fires too early (market still moving, not true closing odds). Both destroy the validity of CLV analysis.

**Prevention:**
- Build a timezone resolution layer for Phase 3 automation. Map race country/region to a timezone. PCS includes country data in race metadata — use it with the `pytz` or `zoneinfo` standard library.
- Store UTC timestamps in `odds_log.jsonl` for every snapshot. Include both the local-time string from PCS and the UTC timestamp.
- Run the closing-odds poll on a schedule relative to race UTC start time, not local time. Cross-check with a second source (Pinnacle shows suspension status in the API response).
- Add an integration test: for a past stage with known local start time, verify the computed UTC timestamp is correct.

**Detection:** After each closing-odds capture, log `"captured_at_utc": "...", "stage_start_utc": "..."` and compute time delta. Flag if delta > 30 minutes before start or if market was already suspended.

---

### Pitfall 11: `build_feature_vector_manual` Silently Missing 4 Interaction Groups

**What goes wrong:** This is an existing confirmed bug. `build_feature_vector_manual` computes interactions for climber×profile, climber×vert, tt×itt, and sprint×flat — but is missing the four groups added later to `build_feature_vector`: gc×profile, quality×form, terrain×form, and climber×mountain. These four groups include `interact_diff_quality_x_form` — the #2 most important feature (XGBoost gain 0.038).

**Why it happens:** Interaction features were added to `build_feature_vector` and `build_feature_matrix` without being propagated to `build_feature_vector_manual`. The CLAUDE.md and PROJECT.md document this as known technical debt. The feature uses `fv.get(name, 0.0)` in the serving path, so missing features silently default to zero.

**Consequences:** Every live prediction through the Pinnacle preload path is made with `interact_diff_quality_x_form = 0.0` instead of the actual value. This is not the training distribution — the model was trained seeing this feature with values spanning roughly -0.3 to +0.3. Defaulting to zero for a top-2 importance feature degrades prediction quality on every single live bet.

**Prevention:**
- This must be fixed in Phase 2 as part of the "startlist fix" ticket. Refactor all three interaction computation sites into a single `_compute_interactions(race_feats, rider_a_feats, rider_b_feats)` helper function. Call it from all three paths.
- Add a regression test: given the same rider pair and race params, `build_feature_vector` and `build_feature_vector_manual` must produce identical interaction feature values (modulo startlist-relative features which are legitimately different).
- Until fixed, log a WARNING on every `build_feature_vector_manual` call: "4 interaction groups unavailable in manual path — predictions may be degraded."

**Detection:** `diff(set(build_feature_vector(...).keys()), set(build_feature_vector_manual(...).keys()))` — the difference should be empty except for startlist-relative features. Currently it is not.

---

### Pitfall 12: Auto-Settlement Silently Marks DNF as Loss

**What goes wrong:** `data/pnl.py:auto_settle_from_results()` handles DNF by checking `if rank_a is None: a_ahead = False` (rank_a DNF = rider B wins). But for H2H bets, if the rider you backed DNFs, Pinnacle typically voids the market (no action). The current settlement logic settles a DNF as a loss rather than a void, taking money from the bankroll that should be returned.

**Why it happens:** The implementation predates live betting and was written to resolve ambiguous results from the scraper (DNF riders have null rank). The distinction between "DNF = void bet" (Pinnacle rule) and "DNF = loss" (settlement code assumption) was not reconciled.

**Consequences:** Every DNF on a backed rider creates a false loss in the P&L record. Bankroll decreases incorrectly. CLV computation on that bet is valid (CLV uses closing odds, not outcome), but ROI is understated because a void should return stake, not lose it.

**Prevention:**
- Add a `dnf_policy` parameter to `auto_settle_from_results()` with a default of `"void_on_dnf"` to match Pinnacle's actual settlement rules for H2H markets.
- Verify Pinnacle's specific rule for cycling H2H when one rider DNFs: is it void, or does the other rider win? Document this in `docs/pinnacle-settlement-rules.md` before implementing.
- The `void_bet()` function already exists in `data/pnl.py` — use it when a DNF is detected with `dnf_policy = "void_on_dnf"`.

**Detection:** Query `SELECT * FROM bets WHERE status = 'lost' AND notes LIKE '%DNF%'`. Any such record may be a mis-settlement.

---

### Pitfall 13: Cron Jobs on VPS Fail Silently When Venv Not Activated

**What goes wrong:** All Python scripts require the `.venv` virtualenv to be active. A cron entry that runs `python scripts/settle.py` without activating the venv will use the system Python (3.x, likely without XGBoost, pandas, procyclingstats), raise `ModuleNotFoundError` on the first import, and exit with code 1. Cron logs this as a failure, but there is no alerting — the job simply does not run.

**Why it happens:** crontab entries don't inherit shell environment. The standard fix (`source .venv/bin/activate`) does not work in sh-based crontabs (cron uses `/bin/sh`, not bash). The correct pattern is to call the venv Python directly: `/path/to/.venv/bin/python scripts/settle.py`.

**Consequences:** Auto-settlement, closing-odds capture, and drift detection all fail silently on the VPS. The Flask app still runs (it was started with the venv), but scheduled jobs do not. The user notices only after checking `data/bets` and finding no settlements, by which time several races have passed and CLV data is lost forever (closing odds not captured).

**Prevention:**
- All cron entries must use the absolute path to the venv Python: `/home/user/ml-cycling-predictor/.venv/bin/python /home/user/ml-cycling-predictor/scripts/settle.py >> /home/user/logs/settle.log 2>&1`
- Every cron script must write a sentinel log line on start and exit: `[2026-04-18 12:00:01] settle.py started`, `[2026-04-18 12:00:03] settle.py done: 3 bets settled`.
- Add a data-freshness cron job (listed in the project plan) that alerts if `scrape_log` shows no activity in the past 24 hours. This catches venv failures, network failures, and other silent errors.
- Test all cron scripts by running them as the cron user: `sudo -u www-data /home/user/.venv/bin/python scripts/settle.py` before deploying the crontab.

**Detection:** Every scheduled script must exit with code 0 on success and non-zero on failure. Add `set -e` at the shell level and wrap Python calls in error-checking. Monitor cron exit codes in the daily health report.

---

## Minor Pitfalls

---

### Pitfall 14: Negative Kelly Edge Bypasses `should_bet=False` Due to Calibration Rounding

**What goes wrong:** `kelly_criterion()` returns `should_bet=False` when `kelly_f <= 0`. But the edge displayed in the UI is `model_prob - implied_prob`, computed independently of Kelly. If model_prob = 0.5001 and implied_prob = 0.5000 (edge = +0.01%), Kelly also returns a tiny positive stake. The user sees "edge = 1 basis point" and Kelly = 0.01% as a bet recommendation. This is noise, not signal.

**Prevention:** Add a minimum edge threshold check in Kelly: if `edge < 0.02` (2 percentage points), return `should_bet=False` regardless of Kelly sign. This matches the project's stated "flag at >5%, act at >8%" thresholds and prevents micro-edge noise from reaching the bet log.

---

### Pitfall 15: Stratified Split Accuracy (69.7%) Cited in Live Reporting as Expected Performance

**What goes wrong:** The CLAUDE.md and `decision_log.md` document that stratified split overestimates live performance by ~1.3% vs time-based split. The time-based estimate (~68.5% / 0.755 AUC) is closer to real-world expectation. If the pre-race briefing reports or edge-alert system displays "model accuracy: 69.7%", users (and future contributors) will have miscalibrated expectations for live performance.

**Prevention:** All user-facing displays, alerts, and reports must show the time-based split accuracy as the headline figure. Label it: "Live estimate: ~68.5% (time-based split)." Reserve the 69.7% figure for internal model comparison only.

---

### Pitfall 16: Pre-Race Report Cron Fetches Stale PCS Data If Scraper Hasn't Run

**What goes wrong:** The pre-race briefing cron runs T-2h before stage start and calls `build_feature_vector_manual` with the latest rider features from `cache.db`. If `update_races.py` hasn't run recently (e.g., VPS network issue overnight), the rider features reflect form from a week ago — missing a recent DNF, a sprint win that changes form_last10, or a new team leader assignment.

**Prevention:** The pre-race briefing script must check `scrape_log` for the most recent successful scrape. If the most recent scrape is > 36 hours old, include a warning in the pre-race report: "STALE DATA: rider form last updated {n} hours ago." Do not silently serve predictions on stale data without flagging it.

---

### Pitfall 17: `data/bets.csv` and `data/bets` (SQLite) Diverge If Settlement Path Is Different

**What goes wrong:** The CLAUDE.md references `data/bets.csv` as the bet log. `data/pnl.py` uses the `bets` table in `cache.db`. These are two different storage mechanisms. If some workflows write to CSV and others write to SQLite, or if the auto-settlement cron only updates SQLite but the user checks the CSV, the two records will diverge.

**Prevention:** The v2.0 automated settlement path (`auto_settle_from_results`) only operates on SQLite (`data/pnl.py`). Before building Phase 3 automation, confirm that `data/bets.csv` is deprecated (no code paths write to it) or that both are updated atomically. Do not build automation that writes to one without the other.

---

## Phase-Specific Warnings

| Phase | Topic | Likely Pitfall | Mitigation |
|-------|-------|---------------|------------|
| 1 — Validate Edge | CLV infrastructure | Closing odds captured too early or after suspension | Multi-snapshot polling; store suspension status |
| 1 — Validate Edge | CLV analysis | False precision on N < 100; CI omitted | Always display CI and N alongside CLV point estimate |
| 1 — Validate Edge | simulate_pnl.py | Used as edge evidence — circular (synthetic odds from model) | Deprecate as evidence source; label clearly |
| 1 — Validate Edge | Staking policy | Negative edge produces tiny positive Kelly due to rounding | Add 2pp minimum edge floor in Kelly UI |
| 1 — Validate Edge | Stage exposure | Multiple correlated bets per stage exceed intended risk | Per-stage bankroll cap in UI and log query |
| 1 — Validate Edge | Bet logging | Survivorship bias from selective logging | Log all recommendations, not just placed bets |
| 2 — Model Upgrade | Market odds feature | Look-ahead leakage if used in training on historical data | Only use at inference, or defer until historical odds corpus exists |
| 2 — Model Upgrade | Interaction feature fix | 4 groups missing from manual path (`interact_diff_quality_x_form` = 0.0) | Refactor into shared `_compute_interactions()` helper first |
| 2 — Model Upgrade | Calibration | Regresses in 55–80% range after retraining without bin-level check | Run `eval_calibration.py` on time-based split; gate on 3pp tolerance |
| 2 — Model Upgrade | Training/serving skew | `diff_field_rank_quality` fix uses different reference population than training | Match reference population exactly; add unit test |
| 3 — Automate | Race timezone | Cron fires in UTC but race starts in CEST — closes 2h late | Resolve race timezone from PCS country metadata; store UTC |
| 3 — Automate | Cron reliability | Venv not activated on VPS; all jobs fail silently | Absolute venv Python path in crontab; sentinel log lines |
| 3 — Automate | DNF settlement | Auto-settlement marks DNF as loss instead of void | Implement `void_on_dnf` policy matching Pinnacle rules |
| 3 — Automate | Stale data | Pre-race report runs on rider features > 36h old | Check `scrape_log` freshness before generating report |

---

## Sources

- Codebase: `features/pipeline.py` — interaction feature groups in `build_feature_vector` (lines 157–221) vs `build_feature_vector_manual` (lines 320–396); confirmed 4 missing groups
- Codebase: `data/pnl.py` — `auto_settle_from_results()` DNF logic (lines 327–344); `settle_bet()` bankroll deduction on loss (lines 187–198)
- Codebase: `models/predict.py` — `kelly_criterion()` implementation; `kelly_f <= 0` guard (lines 100–117)
- Codebase: `scripts/simulate_pnl.py` — `simulate_market_odds()` generates synthetic odds from model probs (line 58)
- Codebase: `models/benchmark.py` — stratified vs time-based split implementations; confirmed ~1.3% accuracy gap documented in `decision_log.md`
- PROJECT.md — Phase structure, kill/keep gates, known weaknesses, technical debt list
- CLAUDE.md — Known issues, interaction feature duplication confirmed, `diff_field_rank_quality` hardcoded 0.0 confirmed
- Kelly Criterion mathematics: correlation adjustment requirement — standard sports betting literature (HIGH confidence; Kelly (1956) assumes independent bets)
- Closing line value methodology: CLV = closing implied prob / bet implied prob - 1; must use true closing line — Joseph Buchdahl, "Squares & Sharps" (MEDIUM confidence via established sports betting methodology)
- Statistical significance for CLV: N=200 bets at 50% win rate requires ~200 observations for ±3% CI at 95% confidence — standard frequentist sample size calculation (HIGH confidence)
- Timezone handling for sports events: pytz/zoneinfo standard library (HIGH confidence — Python 3.9+ ships `zoneinfo`)
- Cron venv activation: cron uses `/bin/sh`, `source` not available — absolute path to venv Python is canonical fix (HIGH confidence — standard Linux cron behaviour)
