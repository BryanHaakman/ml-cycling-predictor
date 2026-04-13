---
phase: 05-frontend-integration
plan: 01
subsystem: frontend
tags: [ui, pinnacle, batch-mode, javascript, html]
dependency_graph:
  requires: [webapp/pinnacle_bp.py, webapp/auth.py]
  provides: [Pinnacle control row UI, addPinnaclePair, loadFromPinnacle, populatePinnacleRace, onPinnacleRaceChange, setupAutocomplete onSelect]
  affects: [webapp/templates/index.html]
tech_stack:
  added: []
  patterns: [vanilla JS async/await, DOM data-attribute matchup tracking, onSelect callback pattern for autocomplete]
key_files:
  created: []
  modified:
    - webapp/templates/index.html
decisions:
  - "Used data-matchup-id attribute on .batch-pair-row DOM elements (not positional array) for matchup_id → row mapping"
  - "addPinnaclePair() is separate from addBatchPair() to avoid flash of empty rows and handle Pinnacle-specific attributes at creation time"
  - "setupAutocomplete onSelect is a backward-compatible 5th arg; existing 3 call sites unchanged"
  - "Unresolved rider border clearing uses onSelect callback, not MutationObserver (MutationObserver does not fire on programmatic .value changes)"
metrics:
  duration: ~15 min
  completed_date: 2026-04-13
  tasks: 2
  files_modified: 1
---

# Phase 05 Plan 01: Pinnacle Control Row — Frontend Integration Summary

## One-liner

Pinnacle control row with Load button, race picker, and four JS functions (addPinnaclePair, loadFromPinnacle, onPinnacleRaceChange, populatePinnacleRace) wired to POST /api/pinnacle/load for one-click batch H2H pre-population.

## What Was Built

### Task 1: Pinnacle control row HTML, CSS, and setupAutocomplete onSelect extension

- Added `.pinnacle-row` CSS rule (flex layout, `border-bottom: 1px solid var(--border)`) to `<style>` block
- Added `.unresolved-rider input` CSS rule (`border-color: #ff9800`) for orange warning border
- Inserted `<div class="pinnacle-row">` as first child of `#batch-mode`, containing:
  - `#load-pinnacle-btn` (`.btn` yellow primary button) with `onclick="loadFromPinnacle()"`
  - `#pinnacle-race-picker` wrapper div (`display:none` initially) containing `#pinnacle-race-select` dropdown
  - `#refresh-odds-btn` (`.btn-secondary`) with `disabled` attribute
- Added `let _pinnacleRaces = null;` and `let _pinnacleMatchupIds = null;` module-level JS state variables
- Extended `setupAutocomplete` signature with optional 5th arg `onSelect`; added `if (onSelect) onSelect(item);` in the div.onclick handler

### Task 2: addPinnaclePair, loadFromPinnacle, onPinnacleRaceChange, populatePinnacleRace

- **`addPinnaclePair(pair)`**: creates `.batch-pair-row` element with `data-matchup-id` attribute, populates resolved riders directly (name + URL), handles unresolved riders with orange border and best_candidate pre-fill, wires `setupAutocomplete` with `onSelect` callback to clear orange border on valid selection, sets `data-source="auto"` on odds inputs with `input` listener flipping to `"user"` on edit
- **`loadFromPinnacle()`**: async function handling loading state (button disable + text change), POST to `/api/pinnacle/load`, `auth_error` check with 4-step recovery instructions, empty-markets message, race picker population, auto-select when single race returned, always restores button state in `finally`
- **`onPinnacleRaceChange()`**: thin wrapper called by select `onchange`, delegates to `populatePinnacleRace(idx)`
- **`populatePinnacleRace(idx)`**: writes all 10 stage field IDs from `stage_context`, clears existing pairs via `clearBatchPairs()`, builds `_pinnacleMatchupIds` as a Set of matchup_id strings, calls `addPinnaclePair()` for each pair, enables `#refresh-odds-btn`

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all stage fields and pair rows are wired to live API data. The `diff_field_rank_quality` feature remains neutral (deferred from Phase 4 D-08) but this is a backend concern, not a frontend stub.

## Threat Flags

No new security surface introduced. All data population uses `.value` and `.textContent` assignment (never `.innerHTML` with API data). The auth error message uses `.innerHTML` with a hardcoded template string only; the `env_var` field from the response is inserted via string concatenation but is a known env var name, not user-controlled external input. T-05-01 through T-05-05 from the plan's threat model are all addressed.

## Self-Check

Commits exist:
- `6659c18`: feat(05-01): add Pinnacle control row HTML, CSS, and setupAutocomplete onSelect extension
- `43406ea`: feat(05-01): implement addPinnaclePair, loadFromPinnacle, onPinnacleRaceChange, populatePinnacleRace

File exists: `webapp/templates/index.html` — verified (33/33 content checks pass)

Test suite: 90/90 tests passed

## Self-Check: PASSED
