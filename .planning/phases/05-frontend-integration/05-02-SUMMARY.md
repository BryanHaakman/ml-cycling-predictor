---
phase: 05-frontend-integration
plan: 02
subsystem: frontend
tags: [ui, pinnacle, batch-mode, javascript, html, refresh-odds]
dependency_graph:
  requires: [webapp/pinnacle_bp.py, 05-01 (addPinnaclePair, _pinnacleMatchupIds, data-source attrs)]
  provides: [refreshOdds() JS function, Refresh Odds button wiring]
  affects: [webapp/templates/index.html]
tech_stack:
  added: []
  patterns: [DOM-based matchup_id lookup via data-matchup-id attribute, data-source dirty tracking]
key_files:
  created: []
  modified:
    - webapp/templates/index.html
decisions:
  - "Used DOM querySelectorAll + getAttribute('data-matchup-id') for row lookup — NOT positional array index (safe against row removal)"
  - "data-source='auto'/'user' attribute check gates each odds field update independently"
  - "refreshOdds() reuses same #batch-error div and same auth error format as loadFromPinnacle()"
metrics:
  duration: ~15 min
  completed_date: 2026-04-13
  tasks: 2
  files_modified: 1
---

# Phase 05 Plan 02: refreshOdds() Function — Frontend Integration Summary

## One-liner

refreshOdds() JS function with DOM-based data-matchup-id row lookup and data-source dirty-tracking wired to Refresh Odds button, completing the Pinnacle integration workflow.

## What Was Built

### Task 1: refreshOdds() function and button onclick wiring (COMPLETE)

- Added `onclick="refreshOdds()"` to `#refresh-odds-btn` button element
- Added `async function refreshOdds()` in the `<script>` block, inserted after `populatePinnacleRace()`

**Key behaviors implemented:**

- **Early-exit guard (D-03):** Returns immediately if `_pinnacleMatchupIds` is null or `size === 0`
- **Loading state:** Disables button, sets text to `⏳ Refreshing...`; restores both in `finally` block
- **Fetch:** `POST /api/pinnacle/refresh-odds` with `JSON.stringify({matchup_ids: ids})` where `ids = Array.from(_pinnacleMatchupIds)`
- **DOM-based row lookup (D-13):** Uses `document.querySelectorAll('#batch-pairs-container .batch-pair-row')` and `row.getAttribute('data-matchup-id')` — NOT positional array index. Handles manually-added rows (no `data-matchup-id`, skipped), removed rows (not in DOM, not visited), and closed markets (not in response, skipped silently)
- **data-source dirty tracking (D-13):** Checks `getAttribute('data-source') === 'auto'` on each odds input before updating. User-edited fields (`data-source='user'`, set by oninput handler from Plan 01) are preserved
- **Auth error handling (D-17/D-18):** Checks `data.type === 'auth_error'`, displays same 4-step fix message as `loadFromPinnacle()` including the `env_var` field from the response
- **Generic error handling:** Non-auth errors display `'Refresh failed: ' + (data.error || 'Unknown error')`

### Task 2: Human verification of complete Pinnacle integration (AWAITING HUMAN VERIFICATION)

Human verification has not yet been performed. The user must:

1. Ensure `PINNACLE_SESSION_COOKIE` is set in the environment
2. Start Flask: `python webapp/app.py`
3. Run 6 test scenarios in the browser (detailed in 05-02-PLAN.md Task 2):
   - Test 1: Load Flow (UI-01, UI-02)
   - Test 2: Editability (UI-03)
   - Test 3: Refresh Odds preserves user-edited fields (UI-04)
   - Test 4: Unresolved Riders orange border clears on selection
   - Test 5: Auth Error with 4-step instructions
   - Test 6: Race Switching updates stage fields and pairs

**Automated verification (pytest) run before checkpoint:** 90/90 tests passed.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — `refreshOdds()` is fully wired to live API data. All data-source tracking and DOM lookup are complete.

## Threat Flags

No new security surface introduced beyond what was analyzed in the plan's threat model (T-05-06, T-05-07, T-05-08 — all `accept` disposition). Odds values from the refresh response are written to input `.value` property only (no innerHTML injection).

## Self-Check

Commits exist:
- `ee45ec8`: feat(05-02): implement refreshOdds() function and wire Refresh Odds button

File exists: `webapp/templates/index.html` — verified (15/15 content checks pass)

Test suite: 90/90 tests passed

Automated verify command output: `PASS: refreshOdds function with DOM-based lookup present`

## Self-Check: PASSED
