---
phase: 06-odds-scraping-clv-infrastructure
verified: 2026-04-18T23:30:00Z
status: human_needed
score: 5/5
overrides_applied: 0
human_verification:
  - test: "Bet booking flow end-to-end"
    expected: "Load Pinnacle markets, see stake inputs and Book Bet buttons, confirm dialog with rider/odds/stake, bet saves to SQLite"
    why_human: "Requires live Pinnacle cycling markets, browser interaction, visual confirmation of button states"
  - test: "CLV dashboard rendering"
    expected: "P&L page shows CLV summary cards, rolling CLV chart (or empty state), terrain table, per-bet CLV column"
    why_human: "Visual layout, Chart.js rendering, color coding cannot be verified programmatically"
  - test: "Snapshot capture and status bar"
    expected: "Click Capture Snapshot, status bar updates with timestamp and matchup count"
    why_human: "Requires live Pinnacle markets and browser interaction"
---

# Phase 6: Odds Scraping & CLV Infrastructure Verification Report

**Phase Goal:** Every bet placed carries a closing-line value signal -- odds scraped reliably, full market snapshots stored daily, bets enriched with model recommendations, and CLV computed at settlement
**Verified:** 2026-04-18T23:30:00Z
**Status:** human_needed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths (from ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Pinnacle H2H cycling pages are scraped successfully and all offered matchups are captured as a daily snapshot stored in cache.db | VERIFIED | `data/pinnacle_scraper.py` uses Playwright (not BS4/requests as ROADMAP says -- deliberate pivot per D-01/D-04 due to React SPA). `scrape_cycling_markets()` does two-level scrape (leagues -> matchups), `save_snapshot()` persists to `market_snapshots` table in cache.db with parameterized queries. 21 tests pass including mocked Playwright scraping. |
| 2 | Each bet record includes actual stake, recommended quarter-Kelly stake, model probability, Pinnacle implied probability, edge %, decimal odds, matchup details, and capture timestamp at the moment of logging | VERIFIED | `place_bet()` in pnl.py accepts and stores: `stake`, `recommended_stake`, `model_prob`, `implied_prob` (computed from decimal_odds), `edge`, `decimal_odds`, `rider_a/b_name/url`, `race_name`, `stage_url`, `stage_type`, `profile_icon`. `created_at` column auto-captures timestamp. Test `test_recommended_stake_stored` confirms. |
| 3 | Closing odds are captured per market at race start time; the bets table has closing_odds_a, closing_odds_b, clv, clv_no_vig, and settled_at columns | VERIFIED | `scripts/schedule_closing_odds.py` reads start times from snapshots and triggers `scrape_odds.py --closing` at race start time. `/api/pinnacle/snapshot/closing` endpoint also available. Schema migration adds `closing_odds_a`, `closing_odds_b`, `clv`, `clv_no_vig` columns; `settled_at` was already in original schema. Tests `test_clv_columns_added` and `test_migration_idempotent` confirm. |
| 4 | After PCS results are ingested, bets are auto-settled and CLV (raw and vig-free) is computed and written to the bets table | VERIFIED | `auto_settle_from_results()` calls `settle_bet()` which atomically (D-15) looks up closing odds from `market_snapshots WHERE snapshot_type='closing'`, calls `compute_clv()` with multiplicative vig removal, and writes CLV alongside won/lost status. Tests `test_clv_populated_on_settle`, `test_clv_correct_value`, `test_settles_without_clv` confirm behavior. |
| 5 | The P&L UI shows per-bet CLV, rolling average CLV, 95% bootstrap confidence interval, and a CLV breakdown by stage type | VERIFIED | `pnl.html` contains: CLV summary cards (Avg CLV, Vig-Free CLV, 95% CI, Settled w/ CLV), Chart.js rolling CLV chart with 50-bet rolling + cumulative average lines, terrain CLV table with per-type CLV/CI, per-bet CLV column in bet history. API endpoints `/api/pnl/clv-summary` and `/api/pnl/clv-by-terrain` return data from `get_clv_summary()` and `get_clv_by_terrain()` which use `clv_confidence_interval()` with scipy BCa bootstrap. |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `data/pinnacle_scraper.py` | Playwright scraper module | VERIFIED | 508 lines, exports MatchupSnapshot, PinnacleScrapeError, scrape_cycling_markets, save_snapshot, parse_american_odds, _american_to_decimal, get_upcoming_start_times. Imports from playwright.sync_api, data.scraper. |
| `scripts/scrape_odds.py` | CLI entry point | VERIFIED | --headed and --closing flags, imports from data.pinnacle_scraper, --help exits 0 |
| `scripts/schedule_closing_odds.py` | Closing-odds scheduler | VERIFIED | --dry-run flag, imports get_upcoming_start_times, subprocess call to scrape_odds.py --closing, time.sleep for scheduling |
| `tests/test_pinnacle_scraper.py` | Scraper unit tests | VERIFIED | 21 tests passing, covers odds conversion, parsing, dataclass, SQLite persistence, mocked Playwright |
| `data/pnl.py` | CLV computation and data layer | VERIFIED | Contains compute_clv, clv_confidence_interval, get_total_bankroll, get_clv_summary, get_clv_by_terrain. Schema migration for 5 CLV columns. settle_bet atomically computes CLV. |
| `tests/test_clv.py` | CLV unit tests | VERIFIED | 22 tests passing, covers schema migration, CLV formula, bootstrap CI, bankroll, settlement with/without closing odds, bet history filters, terrain grouping |
| `webapp/pinnacle_bp.py` | Rewired Flask blueprint | VERIFIED | Imports from data.pinnacle_scraper (not data.odds), lazy Predictor, /api/pinnacle/load with predictions, /api/pinnacle/snapshot, /api/pinnacle/snapshot/closing. All routes @_require_localhost. |
| `webapp/app.py` | CLV API endpoints | VERIFIED | Imports get_clv_summary, get_clv_by_terrain, get_total_bankroll. Routes: /api/pnl/clv-summary, /api/pnl/clv-by-terrain, /api/pnl/total-bankroll. History endpoint accepts status/race_name/stage_type/date filters. place_bet accepts recommended_stake. |
| `tests/test_pinnacle_bp.py` | Blueprint tests | VERIFIED | 9 tests passing, mocks data.pinnacle_scraper (not data.odds), tests load/snapshot/closing endpoints with localhost enforcement |
| `webapp/templates/index.html` | Bet booking UI | VERIFIED | Contains Book Bet buttons, stake-input fields, window.confirm dialog, fetch to /api/pnl/bet, snapshot-status div, Capture Snapshot button, fetch to /api/pnl/total-bankroll, uses pair.odds_a/odds_b |
| `webapp/templates/pnl.html` | CLV dashboard | VERIFIED | Contains Avg CLV/Vig-Free CLV/95% CI/Settled w/ CLV cards, clvChart canvas, chart.js@4.4.4 CDN, Rolling CLV chart, CLV by Stage Type table, per-bet CLV column, fetches /api/pnl/clv-summary and /api/pnl/clv-by-terrain, color-coded with var(--green)/var(--red) |
| `data/odds.py` | Deleted | VERIFIED | File does not exist (confirmed) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| data/pinnacle_scraper.py | data/scraper.py | `from data.scraper import get_db, DB_PATH` | WIRED | Line 35 |
| scripts/scrape_odds.py | data/pinnacle_scraper.py | `from data.pinnacle_scraper import scrape_cycling_markets, save_snapshot` | WIRED | Verified via --help exit 0 |
| scripts/schedule_closing_odds.py | data/pinnacle_scraper.py | `from data.pinnacle_scraper import get_upcoming_start_times` | WIRED | Verified via --help exit 0 |
| scripts/schedule_closing_odds.py | scripts/scrape_odds.py | subprocess call with --closing | WIRED | Contains `scrape_odds.py` and `--closing` |
| webapp/pinnacle_bp.py | data/pinnacle_scraper.py | `from data.pinnacle_scraper import PinnacleScrapeError, scrape_cycling_markets, save_snapshot, MatchupSnapshot` | WIRED | Line 16-18 |
| webapp/pinnacle_bp.py | models/predict.py | Predictor lazy-load + predict_manual | WIRED | Lines 36-45, 76 |
| webapp/app.py | data/pnl.py | `from data.pnl import ... get_clv_summary, get_clv_by_terrain, get_total_bankroll` | WIRED | Line 23-25 |
| data/pnl.py compute_clv() | data/pnl.py settle_bet() | Called inside settle_bet after status update | WIRED | Line 360-361 |
| data/pnl.py get_clv_by_terrain() | data/pnl.py profile_type_label() | Groups by terrain label | WIRED | Line 709 |
| data/pnl.py clv_confidence_interval() | scipy.stats.bootstrap | BCa bootstrap 95% CI | WIRED | Line 195-206, `from scipy.stats import bootstrap` |
| webapp/templates/index.html | /api/pnl/bet | fetch POST on Book Bet | WIRED | 3 fetch calls to /api/pnl/bet found |
| webapp/templates/index.html | /api/pnl/total-bankroll | fetch GET for bankroll | WIRED | Line 1563 |
| webapp/templates/pnl.html | /api/pnl/clv-summary | fetch GET | WIRED | Line 358 |
| webapp/templates/pnl.html | /api/pnl/clv-by-terrain | fetch GET | WIRED | Line 379 |
| webapp/templates/pnl.html | chart.js CDN | Script include | WIRED | Line 194, chart.js@4.4.4 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| pnl.html CLV cards | clv-avg, clv-no-vig | /api/pnl/clv-summary -> get_clv_summary() -> SQL query on bets WHERE clv IS NOT NULL | Real DB query | FLOWING |
| pnl.html terrain table | terrain-clv-body | /api/pnl/clv-by-terrain -> get_clv_by_terrain() -> SQL query + profile_type_label grouping | Real DB query | FLOWING |
| pnl.html rolling CLV chart | clvChart | /api/pnl/history -> get_bet_history() -> SQL query, client-side rolling average | Real DB query + client computation | FLOWING |
| index.html bet booking | pair data | /api/pinnacle/load -> scrape_cycling_markets() -> Playwright scrape + model predictions | Real scrape + model | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase tests pass | `pytest tests/test_pinnacle_scraper.py tests/test_clv.py tests/test_pinnacle_bp.py -v` | 52 passed, 0 failed | PASS |
| Full test suite | `pytest tests/ -v` | 107 passed, 0 failed | PASS |
| scrape_odds.py CLI | `python scripts/scrape_odds.py --help` | Exit 0, shows --headed and --closing | PASS |
| schedule_closing_odds.py CLI | `python scripts/schedule_closing_odds.py --help` | Exit 0, shows --dry-run | PASS |
| CLV summary API | Flask test client GET /api/pnl/clv-summary | 200 OK | PASS |
| CLV terrain API | Flask test client GET /api/pnl/clv-by-terrain | 200 OK | PASS |
| Total bankroll API | Flask test client GET /api/pnl/total-bankroll | 200 OK | PASS |
| data/odds.py deleted | `ls data/odds.py` | File not found | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-----------|-------------|--------|----------|
| ODDS-01 | 06-01 | Pinnacle H2H cycling markets scraped reliably | SATISFIED | Playwright scraper with retry/backoff, graceful degradation. 21 tests. |
| ODDS-02 | 06-01 | Every H2H matchup captured as full market snapshot | SATISFIED | Two-level scrape discovers all races, scrapes all matchups per race. save_snapshot persists all. |
| ODDS-03 | 06-01 | Snapshot records: participants, decimal odds, implied probs, capture timestamp, race/stage context | SATISFIED | market_snapshots schema has all fields: rider names, odds, implied_prob, captured_at, race_name, race_slug, start_time, start_date. |
| ODDS-04 | 06-03 | Model predictions run on all captured matchups and stored alongside odds | SATISFIED | _enrich_snapshots_with_predictions() in pinnacle_bp.py runs Predictor on each snapshot, UPDATEs model_prob_a/b, edge_a/b, recommended_stake_a/b. /api/pinnacle/load returns model_prob, edge, recommended_stake per pair. |
| ODDS-05 | 06-01 | Historical snapshots preserved for review | SATISFIED | Snapshots are INSERT-only (never deleted), indexed by date/race/riders. |
| CLV-01 | 06-01 | Closing odds captured at race start time via automated snapshot | SATISFIED | schedule_closing_odds.py reads start times and triggers --closing scrape. /api/pinnacle/snapshot/closing endpoint. snapshot_type="closing" tag. |
| CLV-02 | 06-02 | Schema migration adds closing_odds_a, closing_odds_b, clv, clv_no_vig, settled_at | SATISFIED | 5 new columns added via idempotent migration. settled_at was already in schema. Tests confirm. |
| CLV-03 | 06-02 | Bets auto-settled after PCS results ingested | SATISFIED | auto_settle_from_results() queries pending bets, looks up results, calls settle_bet(). /api/pnl/auto-settle endpoint with @_require_localhost. |
| CLV-04 | 06-02 | CLV computed at settlement time using closing odds | SATISFIED | settle_bet() atomically queries market_snapshots for closing odds, calls compute_clv(), writes CLV in same transaction. |
| CLV-05 | 06-02 | Vig-free CLV computed by stripping Pinnacle margin | SATISFIED | compute_clv() implements multiplicative vig removal: total_implied = 1/odds_a + 1/odds_b, fair_prob = closing_implied / total_implied. |
| CLV-06 | 06-05 | P&L UI displays per-bet CLV, rolling average, 95% bootstrap CI | SATISFIED | pnl.html has CLV summary cards, per-bet CLV column, rolling CLV chart (50-bet + cumulative), 95% CI card. APIs wired. |
| CLV-07 | 06-02, 06-05 | CLV tracked separately by stage type | SATISFIED | get_clv_by_terrain() groups by profile_type_label with bootstrap CI. pnl.html terrain CLV table fetches from /api/pnl/clv-by-terrain. |
| BET-01 | 06-02, 06-04 | Bet record includes stake, recommended stake, model prob, implied prob, edge, odds, matchup details, capture timestamp | SATISFIED | place_bet() stores all required fields. index.html sends recommended_stake in POST body. created_at captures timestamp. |
| BET-02 | 06-02 | Bet records include closing odds and CLV once settled | SATISFIED | settle_bet() writes closing_odds_a, closing_odds_b, clv, clv_no_vig at settlement time. |
| BET-03 | 06-02 | Bet history queryable by date, race, edge bucket, stage type, outcome | SATISFIED | get_bet_history() supports status, race_name, stage_type, date_from, date_to filters. Edge bucket filtering is Phase 7 scope (EDGE-01). |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| data/pnl.py | 270 | `capture_timestamp` parameter accepted but not stored in INSERT | Info | Dead parameter -- `created_at` column auto-captures timestamp, so functional impact is nil. Could be cleaned up. |

### Human Verification Required

### 1. Bet Booking Flow End-to-End

**Test:** Start Flask app, open batch prediction page, load Pinnacle markets, verify stake inputs and Book Bet buttons appear, edit stake, click Book Bet, confirm dialog, verify bet saves.
**Expected:** Confirmation dialog shows rider name, odds, stake. Button transitions to "Booked!" after confirmation. Non-value rows allow rider selection.
**Why human:** Requires live Pinnacle cycling markets being available, browser interaction, visual confirmation of button state transitions.

### 2. CLV Dashboard Rendering

**Test:** Open /pnl page, verify CLV summary cards render, check rolling CLV chart (or empty state if < 5 bets), verify terrain CLV table, check per-bet CLV column.
**Expected:** Cards show values (or dashes for empty state), Chart.js chart renders with gold rolling + blue dashed cumulative lines, terrain table groups correctly, CLV values color-coded green/red.
**Why human:** Chart.js rendering, CSS color coding, layout spacing, empty state copy correctness require visual inspection.

### 3. Snapshot Capture and Status Bar

**Test:** Click "Capture Snapshot" button on batch prediction page.
**Expected:** Status bar updates with timestamp and matchup count. Snapshot saved to market_snapshots table.
**Why human:** Requires live Pinnacle markets and browser interaction to verify real-time status bar update.

### Gaps Summary

No gaps found. All 5 ROADMAP success criteria are verified against actual codebase evidence. All 15 requirement IDs (ODDS-01 through ODDS-05, CLV-01 through CLV-07, BET-01 through BET-03) have supporting implementation. 107 tests pass with 0 failures. The only note is the ROADMAP SC #1 mentions "BeautifulSoup/requests" but the implementation correctly uses Playwright due to Pinnacle's React SPA requiring JS rendering -- this is an intentional, documented pivot (D-01, D-04) that better achieves the requirement's intent.

Three items require human verification: the bet booking UI flow, CLV dashboard visual rendering, and snapshot capture -- all require a live browser with active Pinnacle markets.

---

_Verified: 2026-04-18T23:30:00Z_
_Verifier: Claude (gsd-verifier)_
