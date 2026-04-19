---
phase: 06-odds-scraping-clv-infrastructure
plan: 04
status: complete
started: 2026-04-18
completed: 2026-04-18
---

# Plan 06-04 Summary: Bet Booking UI

## What Was Built

Added bet booking flow to the batch prediction page (`webapp/templates/index.html`):

- **Editable stake inputs** pre-filled with quarter-Kelly recommended amount from `/api/pnl/total-bankroll`
- **Book Bet buttons** on every matchup row (not just value bets) with `window.confirm()` dialog showing rider, odds, stake
- **Non-value rows** prompt user to pick rider A or B before booking
- **Capture Snapshot button** POSTs to `/api/pinnacle/snapshot`, status bar shows timestamp + matchup count
- **Bankroll check** — Book Bet disabled with tooltip when bankroll is 0
- **Post-booking state** — button transitions to "Booked!" (green) then disables
- **Single H2H mode removed** — Batch H2H is now the only prediction workflow

## Key Files

### Created/Modified
- `webapp/templates/index.html` — Bet booking columns, snapshot status, Single H2H removed
- `webapp/app.py` — `stage_url` made optional in `/api/pnl/bet` (generates synthetic URL for Pinnacle flow)

## Deviations

1. **All rows bookable** (user feedback) — Originally only value bet rows had booking UI; changed to allow booking any matchup with rider selection prompt for non-value rows
2. **Single H2H removed** (user request) — Removed the Single H2H prediction mode entirely
3. **stage_url optional** (bug fix) — Pinnacle flow doesn't provide PCS stage URLs; backend now generates synthetic `pinnacle/{race-name}` URLs

## Self-Check: PASSED

- [x] Stake inputs and Book Bet buttons on all rows
- [x] Confirmation dialog with rider/odds/stake
- [x] Snapshot status bar updates after capture
- [x] Non-value rows allow rider selection
- [x] 107 tests pass, no regressions
