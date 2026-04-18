# Phase 6: Odds Scraping & CLV Infrastructure - Context

**Gathered:** 2026-04-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Rebuild the Pinnacle scraper (broken guest API → Playwright HTML scraper), store daily market snapshots with model predictions, enrich bet records with CLV columns, auto-settle bets with CLV computation, add a bet booking flow to the batch prediction UI, and surface CLV metrics inline on the P&L page.

</domain>

<decisions>
## Implementation Decisions

### Scraper target & parsing
- **D-01:** Fully replace `data/odds.py` guest API code with a Playwright-based HTML scraper. No fallback to the broken API — delete the old code.
- **D-02:** Two-level scrape: (1) leagues index at `https://www.pinnacle.ca/en/cycling/leagues/` to discover active races, (2) each race's matchups page at `https://www.pinnacle.ca/en/cycling/{race-slug}/matchups/` to extract H2H pairs with odds.
- **D-03:** Scrape all cycling markets — men's, women's, all categories. No filtering by gender or tier.
- **D-04:** Pinnacle pages are JS-rendered (React SPA). Use Playwright headless browser to render pages, then parse the resulting DOM.
- **D-05:** Headless by default for VPS cron. Support a `--headed` flag for local debugging.
- **D-06:** Anti-bot resilience: 1-2s delays between page loads, retry with exponential backoff on 403/captcha. On persistent block, log the failure and alert — never crash the pipeline.
- **D-07:** Pinnacle.ca displays decimal odds natively — no American-to-decimal conversion needed.
- **D-08:** Researcher must investigate what data points are available per matchup in the DOM (rider names, odds, matchup type labels, timestamps, etc.).

### Market snapshot storage
- **D-09:** Claude's discretion on storage design (SQLite table vs enhanced JSONL). Should fit the existing `cache.db` architecture and support downstream queries (join with bets, filter by date/race).
- **D-10:** Two capture moments: (1) on-demand when user presses a button in the UI, (2) automated pre-race cron capture for closing odds used in CLV computation.
- **D-11:** Race start times are scraped from Pinnacle (displayed in EST on the page) to schedule the automated closing-odds capture.
- **D-12:** Model predictions (probability, edge, quarter-Kelly recommendation) are computed on all scraped matchups at snapshot time and stored alongside odds — enables missed-opportunity analysis (ODDS-04, ODDS-05).

### CLV computation & schema
- **D-13:** New CLV columns (`closing_odds_a`, `closing_odds_b`, `clv`, `clv_no_vig`) added via the existing idempotent migration pattern in `_create_pnl_tables()` — consistent with how `stage_type`, `profile_icon`, etc. were added.
- **D-14:** New `recommended_stake` column on the bets table to store the quarter-Kelly recommended amount alongside the actual stake the user entered.
- **D-15:** CLV is computed inside the settlement function (`settle_bet()` / `auto_settle_from_results()`), not as a separate post-settlement step. One atomic operation: settle → lookup closing odds → compute CLV → write.
- **D-16:** Vig-removal method: Claude's discretion (multiplicative/equal-margin is standard for H2H; Shin model is more theoretically correct for favorites).
- **D-17:** `data/bets.csv` is deprecated. SQLite `bets` table in `cache.db` is the single source of truth for all bet data going forward. No migration needed — both are currently empty.
- **D-18:** Existing `decimal_odds` column serves as the opening odds for CLV comparison — no new opening odds columns needed.
- **D-19:** Bet history filtering (BET-03) implemented at SQL level with dynamic WHERE clauses and query parameters — efficient with SQLite indexes.

### Bankroll & bet booking
- **D-20:** Bankroll = cash balance + value of all unsettled bets. This is the total bankroll used for Kelly sizing — unsettled bets are not deducted.
- **D-21:** Bet booking happens on the batch prediction page: editable stake input next to each matchup, pre-filled with the quarter-Kelly recommended amount based on total bankroll. User can override before booking.
- **D-22:** Confirmation dialog before booking: shows rider, odds, stake, and predicted edge. Prevents accidental bet placement.
- **D-23:** Booking writes to SQLite bets table only (not bets.csv). SQLite is the single source of truth.

### P&L UI: CLV display
- **D-24:** CLV metrics are displayed inline on the existing P&L page — no separate tab or section.
- **D-25:** CLV summary card added to the top of the P&L page alongside existing ROI/win rate/bankroll stats. Shows overall avg CLV, vig-free CLV, sample size, and 95% bootstrap CI.
- **D-26:** Per-bet CLV column in the bet history table, color-coded: green for positive CLV, red for negative.
- **D-27:** Rolling CLV chart using Chart.js (consistent with existing bankroll chart). Claude decides whether to show 50-bet rolling, cumulative, or both.
- **D-28:** Terrain CLV breakdown (CLV-07: flat/mountain/TT) displayed as a table with columns: stage type, N bets, avg CLV, CI, ROI.
- **D-29:** 95% bootstrap CI computed server-side in Python (scipy/numpy), sent to frontend as JSON.

### Claude's Discretion
- Market snapshot storage design (D-09): SQLite table structure, column choices, retention policy
- Vig-removal method (D-16): multiplicative vs Shin model for vig-free CLV
- Rolling CLV chart window (D-27): 50-bet rolling vs cumulative vs both lines
- Bankroll chart enhancements: whether existing bankroll_history chart needs updates
- Error state handling in bet booking flow

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Odds & scraping
- `.planning/REQUIREMENTS.md` §Odds Scraping — ODDS-01 through ODDS-05: scraper requirements, snapshot fields, historical preservation
- `data/odds.py` — Current broken guest API client to be fully replaced. Review for `OddsMarket` dataclass, audit logging pattern, and `_american_to_decimal()` (no longer needed since Pinnacle.ca shows decimal)

### CLV & bets
- `.planning/REQUIREMENTS.md` §CLV Tracking — CLV-01 through CLV-07: closing odds capture, schema migration, auto-settlement, CLV computation, UI display, terrain breakdown
- `.planning/REQUIREMENTS.md` §Bet Recording — BET-01 through BET-03: bet record enrichment, closing odds, queryable history
- `data/pnl.py` — Existing bet table schema, `_create_pnl_tables()` migration pattern, `settle_bet()`, `auto_settle_from_results()`, `get_pnl_summary()`, `profile_type_label()`

### Integration points
- `webapp/pinnacle_bp.py` — Flask blueprint for Pinnacle endpoints (needs updating for Playwright scraper)
- `webapp/app.py` — Flask app with P&L routes and batch prediction UI
- `data/name_resolver.py` — Reusable for Pinnacle→PCS name mapping in the new scraper
- `intelligence/stage_context.py` — Stage context fetcher (still used alongside scraper)

### Project context
- `.planning/PROJECT.md` §Current Milestone — v2.0 milestone goal, kill/keep CLV gate criteria
- `CLAUDE.md` §Betting Logic — Edge thresholds, quarter-Kelly sizing, max 5% bankroll cap

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `data/name_resolver.py` (NameResolver): 3-stage Pinnacle→PCS name mapping. Reuse directly in new scraper — no changes needed.
- `data/pnl.py` (`_create_pnl_tables()`): Idempotent migration pattern for schema changes. New CLV columns follow this same pattern.
- `data/pnl.py` (`auto_settle_from_results()`): Auto-settlement logic that compares rider ranks. Extend to also compute CLV at settlement time.
- `data/pnl.py` (`profile_type_label()`): Maps profile_icon/stage_type to terrain label (flat/hilly/mountain/tt/cobbles). Reuse for CLV-07 terrain breakdown.
- `webapp/pinnacle_bp.py`: Flask blueprint pattern for Pinnacle endpoints. Will need refactoring to use new Playwright scraper instead of `fetch_cycling_h2h_markets()`.
- `data/odds.py` (`OddsMarket` dataclass): Clean data model for H2H matchup. May be preserved or replaced by new scraper module.
- `data/odds.py` (`_append_audit_log()`): JSONL audit logging pattern. Consider reusing for snapshot audit trail.

### Established Patterns
- All DB access via `get_db()` from `data.scraper` (WAL mode, foreign keys, Row factory)
- `_require_localhost` decorator on all API endpoints
- Chart.js for frontend charts (bankroll history)
- Jinja2 templates for Flask UI
- 2-space indentation, type hints on all signatures

### Integration Points
- `webapp/app.py` P&L routes: `/pnl` page renders bet history, bankroll chart, summary stats. CLV additions go here.
- `webapp/app.py` batch prediction routes: where the "Load from Pinnacle" button lives. Bet booking UI additions go here.
- `models/predict.py` (`Predictor`): called to run predictions on scraped matchups at snapshot time.
- `data/scraper.py` (`get_db()`): database access for new snapshot table.

</code_context>

<specifics>
## Specific Ideas

- Race start times come from Pinnacle pages (displayed in EST) — not PCS or manual entry
- User wants to see and adjust bet amounts directly in the batch prediction UI, then book with a confirmation dialog
- Bankroll mental model: total bankroll = cash + unsettled bets (Kelly sizes off this total, not reduced by pending stakes)
- Color coding for CLV values: green = positive (beat the closing line), red = negative

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 06-odds-scraping-clv-infrastructure*
*Context gathered: 2026-04-18*
