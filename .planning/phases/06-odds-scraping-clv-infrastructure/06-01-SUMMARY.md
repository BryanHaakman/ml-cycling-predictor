---
phase: "06"
plan: "01"
subsystem: odds-scraping
tags: [playwright, scraper, pinnacle, odds, sqlite, cli]
dependency_graph:
  requires: []
  provides: [pinnacle-scraper, market-snapshots-table, scrape-odds-cli, schedule-closing-odds]
  affects: [webapp/pinnacle_bp.py, tests/test_odds.py, tests/test_pinnacle_bp.py]
tech_stack:
  added: []
  patterns: [playwright-sync-api, prefix-css-selectors, american-to-decimal-conversion, parameterized-sql]
key_files:
  created:
    - data/pinnacle_scraper.py
    - scripts/scrape_odds.py
    - scripts/schedule_closing_odds.py
    - tests/test_pinnacle_scraper.py
  modified:
    - decision_log.md
  deleted:
    - data/odds.py
decisions:
  - "Playwright prefix CSS selectors for DOM parsing (not exact class matches)"
  - "American odds converted to decimal before any storage or return"
  - "market_snapshots table with 3 indexes in cache.db"
  - "Audit log via JSONL at data/scrape_log.jsonl"
metrics:
  duration: "~8 min"
  completed: "2026-04-19"
  tasks_completed: 2
  tasks_total: 2
  test_count: 21
---

# Phase 6 Plan 1: Pinnacle Playwright Scraper Summary

Playwright-based Pinnacle scraper replacing broken guest API, with CLI entry points and automated closing-odds scheduler.

## Task Results

### Task 1: Create data/pinnacle_scraper.py (TDD)

**Commits:** `644db32` (RED), `bcc476b` (GREEN)

Created `data/pinnacle_scraper.py` as a full replacement for the broken `data/odds.py` guest API client. The module uses Playwright sync API to navigate Pinnacle.ca's React SPA with prefix-based CSS selectors.

**Key exports:**
- `MatchupSnapshot` dataclass with decimal odds, race metadata, start times
- `PinnacleScrapeError` exception
- `scrape_cycling_markets(headed, snapshot_type)` -- two-level scrape (leagues -> matchups)
- `save_snapshot(snapshots, db_path)` -- SQLite persistence with parameterized queries
- `parse_american_odds(text)` -- string parsing from DOM to decimal
- `_american_to_decimal(american)` -- numeric conversion moved from odds.py
- `get_upcoming_start_times(db_path)` -- query for closing-odds scheduling

**Anti-bot resilience:** 1-2s random delays between pages, exponential backoff retry (2s base, 3 max), try/finally browser cleanup.

**SQLite schema:** `market_snapshots` table with 22 columns including model prediction placeholders. 3 indexes: `idx_snapshots_date`, `idx_snapshots_race`, `idx_snapshots_riders`.

**Tests:** 21 unit tests in `tests/test_pinnacle_scraper.py` covering odds conversion, string parsing, dataclass fields, SQLite persistence, table idempotency, implied prob computation, and mocked Playwright Page for discover/scrape functions.

**decision_log.md** updated per CLAUDE.md mandate documenting the scraper replacement.

### Task 2: Create CLI scripts and delete data/odds.py

**Commit:** `5fb86b3`

- `scripts/scrape_odds.py` -- CLI with `--headed` (D-05) and `--closing` (D-10) flags
- `scripts/schedule_closing_odds.py` -- reads start times from snapshots, sleeps until race start, triggers closing-odds scrape via subprocess with 300s timeout (CLV-01)
- `data/odds.py` deleted per D-01 (fully replaced)

## Deviations from Plan

None -- plan executed exactly as written.

## Downstream Impact

The deletion of `data/odds.py` breaks two existing test files:
- `tests/test_odds.py` -- imports from deleted module
- `tests/test_pinnacle_bp.py` -- imports `OddsMarket` and `PinnacleAuthError` from deleted module

Per plan instructions: "Do NOT delete tests/test_odds.py yet -- that will be updated in Plan 03 when pinnacle_bp.py is rewired." These are expected breakages that Plan 03 will resolve.

## Threat Surface Verification

| Threat ID | Mitigation | Verified |
|-----------|-----------|----------|
| T-06-01 (SQL injection) | All INSERTs use parameterized `VALUES (?, ?, ?)` | Yes |
| T-06-02 (Chromium leak) | `browser.close()` in `finally` block, `with sync_playwright()` context manager | Yes |
| T-06-03 (Anti-bot) | `time.sleep(random.uniform(1.0, 2.0))` after each page load | Yes |
| T-06-12 (Hung scrape) | `subprocess.run(..., timeout=300)` in scheduler | Yes |

## Self-Check: PASSED

- [x] `data/pinnacle_scraper.py` exists
- [x] `scripts/scrape_odds.py` exists
- [x] `scripts/schedule_closing_odds.py` exists
- [x] `tests/test_pinnacle_scraper.py` exists
- [x] `data/odds.py` does NOT exist
- [x] Commits `644db32`, `bcc476b`, `5fb86b3` found in git log
- [x] 21 tests pass
