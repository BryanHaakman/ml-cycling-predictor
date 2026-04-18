# Phase 6: Odds Scraping & CLV Infrastructure - Research

**Researched:** 2026-04-18
**Domain:** Web scraping (Playwright), betting math (CLV/vig), SQLite schema, Flask UI
**Confidence:** HIGH

## Summary

Phase 6 replaces the broken Pinnacle guest API client (`data/odds.py`) with a Playwright-based headless browser scraper, stores daily market snapshots in SQLite, enriches bet records with CLV columns, auto-settles bets with atomic CLV computation, adds bet booking to the batch prediction UI, and surfaces CLV metrics on the P&L page.

The primary technical challenge is scraping a React SPA (Pinnacle.ca) reliably. Live investigation confirms: Pinnacle.ca renders all content client-side via React into a `#root` div; static HTTP fetches return only a loading spinner. Playwright 1.58.0 is already installed with Chromium browsers working. The DOM structure uses CSS module hashed classes (e.g., `matchupMetadata-ghPeUsb2MR`) but has stable `data-test-id` attributes and predictable class name prefixes (e.g., `matchupMetadata-`, `matchupDate-`, `gameInfoLabel-`) that can be matched with `[class*=prefix]` selectors.

**Primary recommendation:** Build a new `data/pinnacle_scraper.py` module using Playwright sync API with prefix-based CSS selectors, converting American odds to decimal (the page displays American by default despite D-07's assumption), storing snapshots in a `market_snapshots` SQLite table, and extending `data/pnl.py` with CLV columns via the existing idempotent migration pattern.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- D-01: Fully replace `data/odds.py` guest API code with Playwright-based HTML scraper. No fallback.
- D-02: Two-level scrape: leagues index -> race matchups page.
- D-03: Scrape all cycling markets (men's, women's, all categories).
- D-04: Pinnacle pages are JS-rendered (React SPA). Use Playwright headless browser.
- D-05: Headless by default for VPS cron. Support `--headed` flag for local debugging.
- D-06: Anti-bot: 1-2s delays between page loads, retry with exponential backoff on 403/captcha.
- D-07: Pinnacle.ca displays decimal odds natively. **RESEARCH CORRECTION: page actually shows American odds by default -- conversion still needed.**
- D-08: Researcher must investigate DOM data points (done -- see Architecture Patterns).
- D-09: Claude's discretion on snapshot storage (SQLite table in cache.db).
- D-10: Two capture moments: on-demand button + automated cron.
- D-11: Race start times from Pinnacle (EST).
- D-12: Model predictions computed on all matchups at snapshot time.
- D-13: CLV columns via idempotent migration in `_create_pnl_tables()`.
- D-14: New `recommended_stake` column on bets table.
- D-15: CLV computed inside settlement function (atomic).
- D-16: Vig-removal method: Claude's discretion.
- D-17: `data/bets.csv` deprecated. SQLite bets table is source of truth.
- D-18: Existing `decimal_odds` column serves as opening odds for CLV.
- D-19: Bet history filtering at SQL level with dynamic WHERE clauses.
- D-20: Bankroll = cash + unsettled bets.
- D-21: Bet booking on batch prediction page with editable stakes.
- D-22: Confirmation dialog before booking.
- D-23: Booking writes to SQLite only.
- D-24-D-29: CLV metrics inline on P&L page.

### Claude's Discretion
- Market snapshot storage design (D-09)
- Vig-removal method (D-16)
- Rolling CLV chart window (D-27)
- Bankroll chart enhancements
- Error state handling in bet booking flow

### Deferred Ideas (OUT OF SCOPE)
None

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ODDS-01 | Pinnacle H2H cycling markets scraped reliably | Playwright scraper with prefix-based CSS selectors on verified DOM structure |
| ODDS-02 | Every H2H matchup captured as daily snapshot | Two-level scrape (leagues -> each race matchups page) captures all markets |
| ODDS-03 | Snapshot records: participants, odds, implied probs, timestamp, race/stage | DOM provides rider names, American odds (convert to decimal), time, race name from breadcrumb |
| ODDS-04 | Model predictions stored alongside odds | Call `Predictor` at snapshot time, store in snapshot table |
| ODDS-05 | Historical snapshots preserved | `market_snapshots` table with no TTL, indexed by capture date |
| CLV-01 | Closing odds captured at race start time | Automated cron triggers scrape at race start time (from Pinnacle EST display) |
| CLV-02 | Schema migration adds CLV columns | Idempotent ALTER TABLE in `_create_pnl_tables()` |
| CLV-03 | Bets auto-settled after results | Extend existing `auto_settle_from_results()` |
| CLV-04 | CLV computed at settlement | Atomic: settle -> lookup closing odds -> compute CLV -> write |
| CLV-05 | Vig-free CLV computed | Multiplicative method (equal-margin) for H2H markets |
| CLV-06 | P&L UI: per-bet CLV, rolling avg, 95% CI | `scipy.stats.bootstrap` (v1.17.1 installed), Chart.js CDN for rolling chart |
| CLV-07 | CLV by stage type | Extend `profile_type_label()` grouping with CLV aggregation |
| BET-01 | Rich bet records | Add `recommended_stake`, capture timestamp fields to bets table |
| BET-02 | Closing odds and CLV on settled bets | `closing_odds_a`, `closing_odds_b`, `clv`, `clv_no_vig` columns |
| BET-03 | Queryable bet history | SQL WHERE with dynamic filters + indexes |

</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Odds scraping (Playwright) | Backend (Python script/cron) | -- | Headless browser runs server-side; no browser-tier component |
| Market snapshot storage | Database (SQLite) | -- | cache.db is the single data store |
| CLV computation | Backend (pnl.py) | -- | Math happens at settlement time in Python |
| Bet booking flow | Frontend (Jinja2/JS) | Backend (Flask API) | UI form + confirmation dialog, API writes to SQLite |
| P&L CLV display | Frontend (Jinja2/JS) | Backend (Flask API) | Server computes stats + bootstrap CI, frontend renders charts |
| Bankroll calculation (D-20) | Backend (pnl.py) | -- | SQL aggregation: cash + pending stakes |
| Name resolution | Backend (name_resolver.py) | -- | Reuse existing 4-stage pipeline |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| playwright | 1.58.0 | Headless browser for SPA scraping | [VERIFIED: pip show] Already installed, Chromium browsers working |
| scipy | 1.17.1 | Bootstrap confidence intervals | [VERIFIED: python import] `scipy.stats.bootstrap` for 95% CI |
| numpy | 2.4.4 | Array operations for CLV math | [VERIFIED: python import] Already in use throughout project |
| flask | 3.0.0+ | Web framework | [VERIFIED: requirements.txt] Existing stack |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Chart.js | 4.4.x (CDN) | Rolling CLV chart | [ASSUMED] CDN include for interactive line charts; existing bankroll chart uses vanilla Canvas |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Chart.js CDN | Vanilla Canvas (like bankroll chart) | Chart.js gives tooltips, legends, responsive scaling for free; vanilla Canvas is already used but is more work for interactive charts |
| Playwright | Selenium | Playwright is already installed, faster, better auto-wait; Selenium would require new dependency |

**Installation:**
```bash
# playwright already installed -- no new pip packages needed
# Chart.js via CDN in template (no pip install)
playwright install chromium  # only if browsers missing on VPS
```

**Version verification:**
- playwright: 1.58.0 [VERIFIED: `pip show playwright`]
- scipy: 1.17.1 [VERIFIED: `python -c "import scipy; print(scipy.__version__)"`]
- No new pip dependencies required

## Architecture Patterns

### System Architecture Diagram

```
                    +-------------------+
                    |  Pinnacle.ca SPA  |
                    +--------+----------+
                             |
                    Playwright headless
                             |
                    +--------v----------+
                    | pinnacle_scraper  |
                    | (data/ module)    |
                    +--------+----------+
                             |
              +--------------+--------------+
              |                             |
     +--------v--------+          +--------v--------+
     | market_snapshots |          |   name_resolver  |
     | (cache.db table) |          | (Pinnacle->PCS)  |
     +---------+--------+          +-----------------+
               |
     +---------v---------+
     |    Predictor       |    <-- model predictions at snapshot time
     | (models/predict)   |
     +---------+----------+
               |
     +---------v----------+
     | bets table          |    <-- enriched with CLV columns
     | (cache.db)          |
     +----------+----------+
                |
     +----------v----------+
     |  Flask webapp        |
     |  - Batch prediction  |  <-- bet booking UI
     |  - P&L page          |  <-- CLV metrics + charts
     +----------------------+
```

### Recommended Project Structure
```
data/
  pinnacle_scraper.py    # NEW: Playwright-based scraper (replaces odds.py)
  odds.py                # DELETE: broken guest API client
  pnl.py                 # MODIFY: add CLV columns, closing odds lookup, vig-free CLV
  name_resolver.py       # REUSE: no changes needed
webapp/
  pinnacle_bp.py         # MODIFY: rewire to use pinnacle_scraper
  app.py                 # MODIFY: add CLV API endpoints, bet booking API
  templates/
    pnl.html             # MODIFY: add CLV summary card, per-bet CLV column, rolling chart, terrain breakdown
    predictions.html     # MODIFY: add bet booking with editable stakes + confirmation
scripts/
  scrape_odds.py         # NEW: CLI entry point for cron (--headed flag)
tests/
  test_pinnacle_scraper.py  # NEW: replaces test_odds.py
  test_clv.py               # NEW: CLV computation + vig removal tests
```

### Pattern 1: Playwright SPA Scraping with Prefix Selectors
**What:** Navigate to Pinnacle pages, wait for React to render, extract data via CSS prefix selectors
**When to use:** Every scrape operation (leagues discovery + matchup extraction)
**Example:**
```python
# Source: Live Playwright investigation of pinnacle.ca (2026-04-18)
from playwright.sync_api import sync_playwright, Page
import random
import time

def scrape_matchups(page: Page, race_url: str) -> list[dict]:
  """Scrape H2H matchups from a race matchups page."""
  page.goto(race_url, wait_until="networkidle", timeout=30000)
  # Wait for matchup metadata to appear (React render complete)
  page.wait_for_selector('[class*=matchupMetadata]', timeout=15000)

  matchups = []
  metadata_els = page.query_selector_all('[class*=matchupMetadata]')
  for el in metadata_els:
    names = el.query_selector_all('[class*=gameInfoLabel] span')
    time_el = el.query_selector('[class*=matchupDate]')
    if len(names) >= 2:
      matchups.append({
        'rider_a': names[0].inner_text().strip(),
        'rider_b': names[1].inner_text().strip(),
        'start_time': time_el.inner_text().strip() if time_el else None,
      })

  # Odds buttons are sibling to metadata in the row
  # Each row has moneyline buttons: first = rider A, second = rider B
  moneyline_els = page.query_selector_all('[data-test-id="moneyline"]')
  # Skip the header row (first moneyline is "MONEY LINE" label)
  odds_rows = [el for el in moneyline_els if el.inner_text().strip() not in ('MONEY LINE', '')]
  for i, odds_el in enumerate(odds_rows):
    btns = odds_el.query_selector_all('.market-btn')
    if len(btns) >= 2 and i < len(matchups):
      matchups[i]['odds_a_american'] = btns[0].inner_text().strip()
      matchups[i]['odds_b_american'] = btns[1].inner_text().strip()

  # Anti-bot delay
  time.sleep(random.uniform(1.0, 2.0))
  return matchups
```

### Pattern 2: Idempotent Schema Migration
**What:** Add new columns to existing tables without breaking existing code
**When to use:** Adding CLV columns to bets table
**Example:**
```python
# Source: data/pnl.py existing pattern (verified in codebase)
existing = {row[1] for row in conn.execute("PRAGMA table_info(bets)").fetchall()}
clv_migrations = [
    ("closing_odds_a", "REAL"),
    ("closing_odds_b", "REAL"),
    ("clv", "REAL"),
    ("clv_no_vig", "REAL"),
    ("recommended_stake", "REAL"),
    ("capture_timestamp", "TEXT"),
]
for col_name, col_type in clv_migrations:
    if col_name not in existing:
        conn.execute(f"ALTER TABLE bets ADD COLUMN {col_name} {col_type}")
```

### Pattern 3: CLV Computation (Multiplicative Vig Removal)
**What:** Compute closing line value with and without vig
**When to use:** At settlement time, atomically with bet settlement
**Example:**
```python
# Source: Standard sports betting math [CITED: oddsjam.com/betting-education/closing-line-value]
def compute_clv(
    bet_odds: float,          # decimal odds at time of bet
    closing_odds_a: float,    # closing decimal odds rider A
    closing_odds_b: float,    # closing decimal odds rider B
    selection: str,           # 'A' or 'B'
) -> tuple[float, float]:
    """Compute raw CLV and vig-free CLV.

    Returns (clv_raw, clv_no_vig) as percentages.
    """
    # Raw CLV: compare implied prob at bet vs closing
    bet_implied = 1.0 / bet_odds
    closing_odds = closing_odds_a if selection == 'A' else closing_odds_b
    closing_implied = 1.0 / closing_odds
    clv_raw = (closing_implied - bet_implied) / bet_implied

    # Vig-free CLV: remove margin via multiplicative method
    total_implied = (1.0 / closing_odds_a) + (1.0 / closing_odds_b)
    fair_prob = closing_implied / total_implied  # normalize to sum=1
    clv_no_vig = (fair_prob - bet_implied) / bet_implied

    return clv_raw, clv_no_vig
```

### Pattern 4: Bootstrap Confidence Interval
**What:** Compute 95% CI for mean CLV using scipy.stats.bootstrap
**When to use:** P&L summary statistics
**Example:**
```python
# Source: scipy.stats.bootstrap docs [CITED: docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html]
from scipy.stats import bootstrap
import numpy as np

def clv_confidence_interval(clv_values: list[float], confidence: float = 0.95) -> tuple[float, float]:
    """Compute bootstrap 95% CI for mean CLV."""
    if len(clv_values) < 5:
        return (0.0, 0.0)
    data = (np.array(clv_values),)
    result = bootstrap(data, np.mean, confidence_level=confidence,
                       n_resamples=10000, random_state=42, method='BCa')
    return (float(result.confidence_interval.low),
            float(result.confidence_interval.high))
```

### Anti-Patterns to Avoid
- **CSS class exact match:** Never use `class="matchupMetadata-ghPeUsb2MR"` -- the hash suffix changes on every Pinnacle deploy. Always use `[class*=matchupMetadata]` prefix matching.
- **Storing American odds:** Always convert to decimal before storage. The project standard is decimal throughout.
- **Separate CLV computation step:** D-15 requires CLV is computed inside `settle_bet()`, not as a post-processing step. Separating them creates a window where bets are settled but CLV is missing.
- **Opening separate DB connections per bet in loops:** The existing `auto_settle_from_results()` opens a fresh connection per iteration -- when extending with CLV, keep this pattern to avoid lock contention but ensure each iteration is atomic.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Headless browser | Custom puppeteer wrapper | Playwright sync API | Auto-wait, stable API, already installed |
| Bootstrap CI | Manual resampling loop | `scipy.stats.bootstrap` | BCa method handles skewed distributions correctly |
| Odds conversion | Inline arithmetic | Shared `american_to_decimal()` function | Edge cases (0, negative, float) already handled in `data/odds.py` |
| Name resolution | New matching logic | `data/name_resolver.py` | 4-stage pipeline with fuzzy matching, persistent cache, already proven |
| Chart rendering | Vanilla Canvas for complex chart | Chart.js CDN | Tooltips, legends, responsive behavior, rolling window -- too complex for raw canvas |

**Key insight:** The project already has solutions for odds conversion and name resolution. The new scraper module should import and reuse these rather than reimplementing.

## Common Pitfalls

### Pitfall 1: CSS Class Hash Instability
**What goes wrong:** Selectors break after Pinnacle redeploys their React app (new CSS module hashes).
**Why it happens:** React CSS modules append random hashes to class names (e.g., `matchupMetadata-ghPeUsb2MR`).
**How to avoid:** Use prefix selectors: `[class*=matchupMetadata]`, `[class*=gameInfoLabel]`, `[class*=matchupDate]`. Also use stable `data-test-id` attributes where available (e.g., `[data-test-id="moneyline"]`).
**Warning signs:** Scraper returns 0 matchups when Pinnacle clearly has active markets.

### Pitfall 2: American vs Decimal Odds
**What goes wrong:** Odds stored as American format, breaking all downstream math (CLV, Kelly, implied prob).
**Why it happens:** D-07 assumed Pinnacle.ca shows decimal odds, but live investigation shows American odds by default (e.g., "-231", "+160"). The odds format toggle says "American Odds" on the page.
**How to avoid:** Parse the American odds string, convert to decimal using the existing `_american_to_decimal()` function from `data/odds.py` before any storage or computation.
**Warning signs:** Odds values like -231 or +160 appearing in the database instead of 1.43 or 2.60.

### Pitfall 3: SPA Content Not Loaded
**What goes wrong:** Scraper gets empty results because React hasn't finished rendering.
**Why it happens:** `page.goto()` with `wait_until="load"` returns before React hydration completes.
**How to avoid:** Use `wait_until="networkidle"` plus `wait_for_selector('[class*=matchupMetadata]')` to confirm content is rendered. Add a safety `time.sleep(2)` for slow network conditions.
**Warning signs:** Page title loads correctly but zero matchup elements found.

### Pitfall 4: Playwright Context Leak on VPS
**What goes wrong:** Chromium processes accumulate, consuming VPS memory.
**Why it happens:** Browser/context not properly closed on errors or timeouts.
**How to avoid:** Always use context managers (`with sync_playwright() as p:`) and try/finally blocks. Single browser instance per scrape session, closed in finally.
**Warning signs:** Multiple `chromium` processes in `ps aux`, growing memory usage.

### Pitfall 5: CLV Computed Without Closing Odds
**What goes wrong:** Settlement runs before closing odds are captured, writing NULL CLV.
**Why it happens:** Race finishes, results are ingested, auto-settlement fires before the closing-odds cron ran.
**How to avoid:** In the settlement function, if `closing_odds_a` or `closing_odds_b` is NULL for a bet, log a warning but still settle the bet (won/lost). CLV can be backfilled later when closing odds become available.
**Warning signs:** Settled bets with `clv IS NULL` in the database.

### Pitfall 6: Bankroll Double-Counting
**What goes wrong:** Kelly sizing uses wrong bankroll value.
**Why it happens:** D-20 says bankroll = cash + unsettled bets, but existing `get_current_bankroll()` tracks cash only (latest bankroll_history entry). Unsettled bets have already been subtracted from cash.
**How to avoid:** New bankroll calculation: `cash_balance + SUM(stake) WHERE status='pending'`. This recovers the "total bankroll" including money at risk.
**Warning signs:** Kelly recommendations shrink dramatically as more bets are pending.

## Code Examples

### American Odds Parsing from DOM
```python
# Source: Live Pinnacle investigation (2026-04-18)
import re

def parse_american_odds(text: str) -> float | None:
    """Parse American odds string from Pinnacle DOM to decimal odds.

    Handles formats: '-231', '+160', '-102', 'EV', empty string.
    Returns None if unparseable.
    """
    text = text.strip()
    if not text or text == 'EV':
        return 2.0 if text == 'EV' else None
    match = re.match(r'^([+-]?\d+\.?\d*)$', text)
    if not match:
        return None
    american = float(match.group(1))
    if american == 0:
        return None
    if american > 0:
        return round(american / 100.0 + 1.0, 4)
    return round(100.0 / abs(american) + 1.0, 4)
```

### Market Snapshot Table Schema
```sql
-- Source: Design based on ODDS-03 requirements + D-09 discretion
CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT DEFAULT (datetime('now')),
    race_name TEXT NOT NULL,
    race_slug TEXT,
    rider_a_name TEXT NOT NULL,
    rider_b_name TEXT NOT NULL,
    rider_a_pcs_url TEXT,
    rider_b_pcs_url TEXT,
    odds_a REAL NOT NULL,           -- decimal odds
    odds_b REAL NOT NULL,           -- decimal odds
    implied_prob_a REAL,
    implied_prob_b REAL,
    start_time TEXT,                -- HH:MM EST from Pinnacle
    start_date TEXT,                -- YYYY-MM-DD derived from page context
    -- Model predictions (ODDS-04)
    model_prob_a REAL,
    edge_a REAL,
    recommended_stake_a REAL,
    model_prob_b REAL,
    edge_b REAL,
    recommended_stake_b REAL,
    -- Metadata
    snapshot_type TEXT DEFAULT 'manual',  -- 'manual' or 'closing'
    source_url TEXT
);

CREATE INDEX IF NOT EXISTS idx_snapshots_date ON market_snapshots(captured_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_race ON market_snapshots(race_name);
CREATE INDEX IF NOT EXISTS idx_snapshots_riders ON market_snapshots(rider_a_name, rider_b_name);
```

### Vig-Free Odds (Multiplicative Method)
```python
# Source: Standard betting math [CITED: oddsjam.com/betting-education/closing-line-value]
def remove_vig_multiplicative(odds_a: float, odds_b: float) -> tuple[float, float]:
    """Remove vig using multiplicative (equal-margin) method.

    For H2H markets this is the standard approach.
    Returns (fair_odds_a, fair_odds_b) as decimal odds.
    """
    implied_a = 1.0 / odds_a
    implied_b = 1.0 / odds_b
    total = implied_a + implied_b  # overround (e.g., 1.04 = 4% vig)
    fair_a = 1.0 / (implied_a / total)
    fair_b = 1.0 / (implied_b / total)
    return round(fair_a, 4), round(fair_b, 4)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Guest API (`guest.api.arcadia.pinnacle.com`) | Playwright HTML scraping | 2026-04 (API broken) | Must render SPA, parse DOM, handle anti-bot |
| `data/bets.csv` flat file | SQLite `bets` table in cache.db | Phase 6 (D-17) | Single source of truth, queryable, joinable |
| Manual bet logging | UI-integrated bet booking | Phase 6 (D-21) | Editable stakes in batch prediction UI |
| No CLV tracking | Automated CLV at settlement | Phase 6 (D-15) | Primary model validation signal |

**Deprecated/outdated:**
- `data/odds.py`: Entire module to be deleted (D-01). The `_american_to_decimal()` function should be preserved (moved to `pinnacle_scraper.py` or a shared utils module) since it's still needed.
- `data/bets.csv`: Deprecated as source of truth (D-17). Both are currently empty so no migration needed.
- `data/.pinnacle_key_cache`: No longer needed (API key was for guest API).
- `data/odds_log.jsonl`: Replaced by `market_snapshots` table in SQLite.

## DOM Structure Reference (Pinnacle.ca)

Verified via live Playwright scraping on 2026-04-18.

### Leagues Page (`/en/cycling/leagues/`)
| Element | Selector | Content |
|---------|----------|---------|
| Leagues container | `[data-test-id="Browse-Leagues"]` or `[data-test-id="Leagues-Container-AllLeagues"]` | All active leagues with matchup counts |
| Race links | `a[href*="/cycling/"][href*="/matchups/"]` | URL pattern: `/en/cycling/{race-slug}/matchups/` |
| Race name | Link text (excludes trailing number) | e.g., "Amstel Gold", "Tour Of the Alps - Stage 1" |
| Matchup count | Number after race name | e.g., "19", "14" |

### Matchups Page (`/en/cycling/{race-slug}/matchups/`)
| Element | Selector | Content |
|---------|----------|---------|
| Race breadcrumb | `[data-test-id="Breadcrumb-Item-League"]` | Race display name |
| Date grouping | `[data-test-id="Events.DateBar"]` | "TOMORROW", "TODAY", date string |
| Matchup metadata | `[class*=matchupMetadata]` | Contains rider names + start time |
| Rider A name | `[class*=matchupMetadata] [class*=gameInfoLabel]:first-child span` | e.g., "Alex Aranburu" |
| Rider B name | `[class*=matchupMetadata] [class*=gameInfoLabel]:nth-child(2) span` | e.g., "Christian Scaroni" |
| Start time | `[class*=matchupDate]` | HH:MM format in EST (e.g., "05:10") |
| Moneyline odds | `[data-test-id="moneyline"] .market-btn` | Two buttons per row: odds A, odds B (American format: "-231", "+160") |

**Critical finding:** Odds are displayed in American format (not decimal). The page header shows "American Odds" as the selected format. Conversion to decimal is required before storage.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Chart.js 4.4.x CDN is appropriate for rolling CLV chart | Standard Stack | Low -- could use vanilla Canvas instead; Chart.js just reduces effort |
| A2 | Multiplicative vig removal is adequate for H2H markets | Architecture Patterns | Low -- Shin model is more accurate for heavy favorites but overkill for H2H where both riders are typically close in odds |
| A3 | CSS prefix selectors (`[class*=matchupMetadata]`) will remain stable across Pinnacle deploys | Common Pitfalls | Medium -- if Pinnacle renames the prefix (not just the hash), selectors break. Mitigation: monitor and alert on zero-matchup scrapes |
| A4 | Pinnacle start times are in Eastern Time (based on page showing "GMT -04:00" = EDT) | DOM Structure | Medium -- could vary by user location/cookies. Mitigation: parse the timezone offset from page if available |

## Open Questions

1. **Full date resolution for matchups**
   - What we know: Matchup rows show only HH:MM times (e.g., "05:10"). Date grouping headers say "TOMORROW" or "TODAY".
   - What's unclear: How to derive the full YYYY-MM-DD date for scheduling closing-odds cron.
   - Recommendation: Combine the date bar text ("TOMORROW" = today + 1 day) with the HH:MM time. Store as ISO datetime with EST timezone offset.

2. **Odds format toggle persistence**
   - What we know: Default display is American odds. There's an odds format selector on the page.
   - What's unclear: Whether setting the toggle to "Decimal" persists via cookies or requires clicking each session.
   - Recommendation: Don't rely on the toggle -- always parse American odds and convert. This is more robust than assuming the toggle state.

3. **VPS Playwright browser installation**
   - What we know: Playwright 1.58.0 is installed locally with Chromium working.
   - What's unclear: Whether Chromium browsers are installed on the Hostinger VPS.
   - Recommendation: Include `playwright install chromium` in VPS setup instructions. The `--with-deps` flag installs system dependencies on Linux.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| playwright | Odds scraping | Yes | 1.58.0 | -- |
| Chromium (playwright) | Odds scraping | Yes | (bundled) | -- |
| scipy | Bootstrap CI | Yes | 1.17.1 | -- |
| numpy | CLV math | Yes | 2.4.4 | -- |
| flask | Web UI | Yes | 3.0.0+ | -- |
| Chart.js | Rolling CLV chart | No (CDN) | -- | Vanilla Canvas or add CDN link |

**Missing dependencies with no fallback:** None

**Missing dependencies with fallback:**
- Chart.js: Not installed (will be loaded via CDN `<script>` tag in template)

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 7.0.0+ |
| Config file | none (conftest.py registers custom marks) |
| Quick run command | `pytest tests/test_pinnacle_scraper.py tests/test_clv.py -x -v` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ODDS-01 | Scraper extracts matchups from DOM HTML | unit (mock page) | `pytest tests/test_pinnacle_scraper.py::test_parse_matchups -x` | Wave 0 |
| ODDS-02 | Two-level scrape discovers all races | unit | `pytest tests/test_pinnacle_scraper.py::test_discover_races -x` | Wave 0 |
| ODDS-03 | Snapshot contains all required fields | unit | `pytest tests/test_pinnacle_scraper.py::test_snapshot_fields -x` | Wave 0 |
| ODDS-04 | Model predictions stored with snapshot | integration | `pytest tests/test_pinnacle_scraper.py::test_predictions_stored -x` | Wave 0 |
| ODDS-05 | Historical snapshots preserved | unit | `pytest tests/test_pinnacle_scraper.py::test_snapshot_persistence -x` | Wave 0 |
| CLV-01 | Closing odds captured | unit | `pytest tests/test_clv.py::test_closing_odds_capture -x` | Wave 0 |
| CLV-02 | Schema migration adds columns | unit | `pytest tests/test_clv.py::test_schema_migration -x` | Wave 0 |
| CLV-03 | Auto-settlement works | unit | `pytest tests/test_clv.py::test_auto_settle -x` | Wave 0 |
| CLV-04 | CLV computed at settlement | unit | `pytest tests/test_clv.py::test_clv_at_settlement -x` | Wave 0 |
| CLV-05 | Vig-free CLV correct | unit | `pytest tests/test_clv.py::test_vig_free_clv -x` | Wave 0 |
| CLV-06 | Bootstrap CI computed | unit | `pytest tests/test_clv.py::test_bootstrap_ci -x` | Wave 0 |
| CLV-07 | CLV by terrain type | unit | `pytest tests/test_clv.py::test_clv_by_terrain -x` | Wave 0 |
| BET-01 | Enriched bet record | unit | `pytest tests/test_clv.py::test_enriched_bet_record -x` | Wave 0 |
| BET-02 | Closing odds on settled bets | unit | `pytest tests/test_clv.py::test_closing_odds_on_settled -x` | Wave 0 |
| BET-03 | Queryable history | unit | `pytest tests/test_clv.py::test_queryable_history -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_pinnacle_scraper.py tests/test_clv.py -x -v`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_pinnacle_scraper.py` -- covers ODDS-01 through ODDS-05
- [ ] `tests/test_clv.py` -- covers CLV-01 through CLV-07, BET-01 through BET-03
- [ ] Existing `tests/test_odds.py` will need updating (imports from deleted module)
- [ ] Existing `tests/test_pinnacle_bp.py` will need updating (mocks for new scraper)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | N/A -- localhost-only app, no user auth |
| V3 Session Management | No | N/A -- no sessions |
| V4 Access Control | Yes | `_require_localhost` decorator on all API endpoints |
| V5 Input Validation | Yes | Validate scraped data types before DB insert; parameterized SQL queries |
| V6 Cryptography | No | N/A -- no secrets stored |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via scraped data | Tampering | Parameterized queries (never f-string SQL with scraped values) |
| XSS via rider names in templates | Tampering | Jinja2 auto-escaping (already enabled by default in Flask) |
| Browser fingerprinting / IP ban | Information Disclosure | Random delays (1-2s), single concurrent session, headless mode |
| Stale Playwright browser exploits | Elevation | Keep `playwright install chromium` in update routine |

## Project Constraints (from CLAUDE.md)

- **2-space indentation** -- all new Python files
- **Type hints on all function signatures**
- **Docstrings on all public functions**
- **Run `pytest tests/ -v` before marking any task complete**
- **Do not add dependencies to `requirements.txt` without asking first** -- Playwright is already listed implicitly (it's installed); Chart.js is CDN only
- **All DB access via `get_db()` from `data.scraper`**
- **`_require_localhost` decorator on all API endpoints**
- **Ask before changing any schema** -- CLV columns are pre-approved in D-13/D-14
- **All scripts must degrade gracefully** -- scraper failures log and continue, never crash
- **Decision log** -- no ML experiments in this phase, but document any pipeline changes

## Sources

### Primary (HIGH confidence)
- Live Playwright scrape of pinnacle.ca (2026-04-18) -- DOM structure, CSS classes, odds format, page layout
- `data/odds.py` -- existing OddsMarket dataclass, American-to-decimal conversion
- `data/pnl.py` -- existing schema migration pattern, settlement logic, profile_type_label
- `webapp/pinnacle_bp.py` -- existing Flask blueprint pattern for Pinnacle endpoints
- `pip show playwright` -- version 1.58.0 confirmed installed
- `scipy 1.17.1` -- bootstrap function confirmed available

### Secondary (MEDIUM confidence)
- [scipy.stats.bootstrap docs](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html) -- BCa method, API
- [OddsJam CLV guide](https://oddsjam.com/betting-education/closing-line-value) -- CLV formula, vig removal
- [Playwright Python docs](https://context7.com/microsoft/playwright-python) -- goto, wait_for_selector, launch options

### Tertiary (LOW confidence)
- Chart.js 4.4.x CDN availability -- not verified, standard CDN assumed available

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all dependencies verified installed and working
- Architecture: HIGH -- DOM structure verified via live scraping, patterns derived from existing codebase
- Pitfalls: HIGH -- American odds issue discovered through live testing, not assumption

**Research date:** 2026-04-18
**Valid until:** 2026-05-02 (Pinnacle DOM structure may change on any deploy; re-verify if scraper fails)
