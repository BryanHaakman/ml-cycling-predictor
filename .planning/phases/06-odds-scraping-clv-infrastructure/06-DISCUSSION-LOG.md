# Phase 6: Odds Scraping & CLV Infrastructure - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-18
**Phase:** 06-odds-scraping-clv-infrastructure
**Areas discussed:** Scraper target & parsing, Market snapshot storage, CLV computation & schema, P&L UI: CLV display

---

## Scraper target & parsing

| Option | Description | Selected |
|--------|-------------|----------|
| I have specific URLs | I know the exact page(s) where cycling H2H markets appear on Pinnacle | ✓ |
| Research needed | Researcher should figure out which pages list cycling H2H markets | |
| Keep trying API first | The guest API might still work with tweaks | |

**User's choice:** Has specific URLs — two-level: `/en/cycling/leagues/` index → `/en/cycling/{race-slug}/matchups/` per race
**Notes:** User provided screenshot of Pinnacle leagues page showing race links with matchup counts

---

| Option | Description | Selected |
|--------|-------------|----------|
| Playwright/headless browser | Render JS pages with Playwright, then parse DOM | ✓ |
| Intercept API calls | Find XHR endpoints from DevTools and call directly | |
| Try static HTML first | Try BeautifulSoup first, fall back to Playwright | |

**User's choice:** Playwright/headless browser

---

| Option | Description | Selected |
|--------|-------------|----------|
| Men's only | Only scrape men's race markets | |
| Both, but separate | Scrape both, flag women's races separately | |
| Everything | All cycling markets regardless of category | ✓ |

**User's choice:** Everything

---

| Option | Description | Selected |
|--------|-------------|----------|
| Respect delays, retry on block | 1-2s delays, retry with backoff on 403/captcha | ✓ |
| You decide | Claude decides resilience strategy | |

**User's choice:** Respect delays, retry on block

---

| Option | Description | Selected |
|--------|-------------|----------|
| Full replacement | Delete guest API code, replace with Playwright scraper | ✓ |
| Playwright primary, API fallback | Keep guest API as fallback | |
| Separate module | New module alongside odds.py | |

**User's choice:** Full replacement

---

| Option | Description | Selected |
|--------|-------------|----------|
| Headless only | Always headless | |
| Both modes | Headless default, --headed for debugging | ✓ |
| You decide | Claude picks | |

**User's choice:** Both modes

---

| Option | Description | Selected |
|--------|-------------|----------|
| Rider names + odds only | Just names and odds visible | |
| Names, odds, and more | Additional info visible | |
| Not sure, needs research | Researcher should investigate DOM | ✓ |

**User's choice:** Not sure — researcher should investigate

---

| Option | Description | Selected |
|--------|-------------|----------|
| Decimal on .ca | Pinnacle.ca shows decimal odds | ✓ |
| American on .ca | Shows American odds | |
| Not sure | Researcher should verify | |

**User's choice:** Decimal on .ca

---

## Market snapshot storage

| Option | Description | Selected |
|--------|-------------|----------|
| New SQLite table in cache.db | One row per matchup per scrape, queryable | |
| Keep JSONL log, add SQLite index | Extend odds_log.jsonl, add index table | |
| You decide | Claude picks storage approach | ✓ |

**User's choice:** You decide
**Notes:** Claude has discretion on storage design

---

| Option | Description | Selected |
|--------|-------------|----------|
| Once daily | One snapshot per day | |
| Multiple per day | 2-3 captures daily | |
| Match REQUIREMENTS exactly | T-24h, T-2h, T-30min per Phase 9 | |

**User's choice:** (Other) Upon request from user pressing button, and again before race time to capture CLV
**Notes:** Two capture moments: on-demand button + automated pre-race cron

---

| Option | Description | Selected |
|--------|-------------|----------|
| Manual entry per race | User enters race start time | |
| Scrape from PCS | procyclingstats lib for start times | |
| Fixed daily time | 10:00 UTC approximation | |
| You decide | Claude picks | |

**User's choice:** (Other) Scrape from Pinnacle — it shows times in EST
**Notes:** Pinnacle pages display race start times in EST

---

| Option | Description | Selected |
|--------|-------------|----------|
| At snapshot time | Run predictions on all matchups immediately | ✓ |
| On-demand only | Only compute when user views matchup | |
| You decide | Claude picks | |

**User's choice:** At snapshot time (recommended)

---

## CLV computation & schema

| Option | Description | Selected |
|--------|-------------|----------|
| Same pattern (idempotent migration) | Add columns via _create_pnl_tables() | ✓ |
| Standalone migration script | One-time migration script | |
| You decide | Claude picks | |

**User's choice:** Same pattern (recommended)

---

| Option | Description | Selected |
|--------|-------------|----------|
| Multiplicative (equal margin) | Standard for H2H markets | |
| Shin model | More theoretically correct for favorites | |
| You decide | Claude picks vig-removal method | ✓ |

**User's choice:** You decide

---

| Option | Description | Selected |
|--------|-------------|----------|
| Inside settlement | Extend settle_bet() to compute CLV atomically | ✓ |
| Separate step | Settlement and CLV computation decoupled | |
| You decide | Claude picks | |

**User's choice:** Inside settlement

---

| Option | Description | Selected |
|--------|-------------|----------|
| New column | Add recommended_stake column | ✓ |
| Compute from existing | Derivable from bankroll_at_bet * kelly_fraction | |
| You decide | Claude decides | |

**User's choice:** New column

---

| Option | Description | Selected |
|--------|-------------|----------|
| SQLite bets table only | Stop writing to bets.csv | ✓ |
| Both, CSV as export | SQLite primary, CSV generated on demand | |
| Keep both in sync | Continue dual-writing | |

**User's choice:** SQLite bets table only
**Notes:** bets.csv is deprecated as of this decision

---

| Option | Description | Selected |
|--------|-------------|----------|
| Already in SQLite | All bets placed through app | |
| Need to migrate CSV | Some bets manually logged in CSV | |
| Not sure | Need to check both | ✓ |

**User's choice:** Not sure — checked both, both are empty. No migration needed.

---

| Option | Description | Selected |
|--------|-------------|----------|
| SQL-level with query params | Dynamic WHERE clauses with indexes | ✓ |
| You decide | Claude picks filtering approach | |

**User's choice:** SQL-level with query params

---

| Option | Description | Selected |
|--------|-------------|----------|
| decimal_odds is the opening odds | Existing column suffices | ✓ |
| Add explicit opening_odds columns | Capture both sides at bet time | |
| You decide | Claude picks | |

**User's choice:** decimal_odds is the opening odds

---

## P&L UI: CLV display

| Option | Description | Selected |
|--------|-------------|----------|
| Inline on existing P&L page | Add CLV to existing page | ✓ |
| Separate CLV tab/section | Dedicated CLV section | |
| You decide | Claude decides layout | |

**User's choice:** Inline on existing P&L page

---

| Option | Description | Selected |
|--------|-------------|----------|
| Chart.js (consistent) | Same library as existing bankroll chart | ✓ |
| You decide | Claude picks charting approach | |

**User's choice:** Chart.js (consistent)

---

| Option | Description | Selected |
|--------|-------------|----------|
| Server-side Python | Compute bootstrap CI in pnl.py with scipy/numpy | ✓ |
| Client-side JS | Compute in browser | |
| You decide | Claude picks | |

**User's choice:** Server-side Python

---

| Option | Description | Selected |
|--------|-------------|----------|
| Table with key metrics | Simple table: stage type, N, avg CLV, CI, ROI | ✓ |
| Both table and chart | Table + grouped bar chart | |
| You decide | Claude picks | |

**User's choice:** Table with key metrics

---

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, color-coded | Green positive, red negative CLV | ✓ |
| Plain numbers | No color coding | |
| You decide | Claude picks styling | |

**User's choice:** Yes, color-coded

---

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, add CLV summary card | Card with avg CLV, vig-free CLV, CI, sample size | ✓ |
| Chart only, no summary card | CLV only in charts below | |
| You decide | Claude decides | |

**User's choice:** Yes, add CLV summary card

---

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed 50-bet window | Match EDGE-06 drift alert window | |
| All-time cumulative | Smoother long-term trend | |
| Both lines on same chart | Rolling + cumulative together | |
| You decide | Claude picks visualization | ✓ |

**User's choice:** You decide

---

## Bankroll & bet booking (user-initiated scope)

User raised additional requirements during P&L UI discussion:
1. Bankroll visualized and tracked on P&L page
2. Bet sizing calculated from current bankroll (total = cash + unsettled)
3. Ability to change bet amount directly in the UI and book bets

| Option | Description | Selected |
|--------|-------------|----------|
| On the batch prediction page | Stake input + Book Bet next to each matchup | ✓ |
| Dedicated bet slip/page | Separate page for reviewing and confirming bets | |
| You decide | Claude picks UX | |

**User's choice:** On the batch prediction page

---

| Option | Description | Selected |
|--------|-------------|----------|
| Pre-filled with Kelly rec | Quarter-Kelly amount pre-populated, editable | ✓ |
| Blank, Kelly shown as hint | Blank input, Kelly as placeholder | |
| You decide | Claude picks | |

**User's choice:** Pre-filled with Kelly rec

---

| Option | Description | Selected |
|--------|-------------|----------|
| Total minus all pending | Available = bankroll - all unsettled stakes | |
| Total minus today's pending | Available = bankroll - today's unsettled only | |
| You decide | Claude picks | |

**User's choice:** (Other) Total bankroll = remaining balance + value of unsettled bets. Kelly sizes off this total.
**Notes:** Unsettled bets are not deducted — the full bankroll is used for Kelly sizing.

---

| Option | Description | Selected |
|--------|-------------|----------|
| SQLite only | Consistent with earlier decision | ✓ |
| Both for now | Write to both during transition | |

**User's choice:** SQLite only

---

| Option | Description | Selected |
|--------|-------------|----------|
| One-click, no confirm | Speed over safety | |
| Confirmation dialog | Show rider, odds, stake before committing | ✓ |
| You decide | Claude picks | |

**User's choice:** Confirmation dialog

---

## Claude's Discretion

- Market snapshot storage design (table structure, retention)
- Vig-removal method for CLV (multiplicative vs Shin)
- Rolling CLV chart window (50-bet vs cumulative vs both)
- Bankroll chart enhancements
- Error state handling in bet booking

## Deferred Ideas

None — discussion stayed within phase scope
