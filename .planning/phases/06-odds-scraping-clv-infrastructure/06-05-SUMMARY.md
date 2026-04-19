---
phase: 06-odds-scraping-clv-infrastructure
plan: 05
status: complete
started: 2026-04-18
completed: 2026-04-18
---

# Plan 06-05 Summary: CLV Dashboard

## What Was Built

Added CLV metrics display to the P&L page (`webapp/templates/pnl.html`):

- **CLV Summary Cards** — 4-card row: Avg CLV, Vig-Free CLV, 95% CI, Settled w/ CLV. Color-coded green/red/muted.
- **Rolling CLV Chart** — Chart.js line chart with 50-bet rolling average (gold) and cumulative average (blue dashed), zero reference line. Hidden with empty state when < 5 bets.
- **Terrain CLV Breakdown** — Table with Stage Type, Bets, Avg CLV, Vig-Free CLV, CI columns. CI suppressed when N < 5. Color-coded values.
- **Per-bet CLV Column** — New "CLV" column in bet history table. Green for positive, red for negative, muted dash for null/pending.
- **Chart.js CDN** — `chart.js@4.4.4` loaded from jsdelivr.
- **Empty states** — Correct copy when no bets or fewer than 5 bets.

## Key Files

### Modified
- `webapp/templates/pnl.html` — CLV summary cards, rolling CLV chart, terrain table, per-bet CLV column

## API Endpoints Used
- `GET /api/pnl/clv-summary` — Avg CLV, vig-free CLV, CI, sample size
- `GET /api/pnl/clv-by-terrain` — Terrain breakdown with per-type CLV stats
- `GET /api/pnl/history` — Bet history with CLV fields
- `GET /api/pnl/summary` — Bankroll and summary stats

## Self-Check: PASSED

- [x] CLV summary cards with color coding
- [x] Rolling CLV chart with 50-bet rolling + cumulative lines
- [x] Terrain CLV breakdown table
- [x] Per-bet CLV column in bet history
- [x] Empty states for < 5 bets
- [x] 107 tests pass, no regressions
