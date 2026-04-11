---
phase: 01-pinnacle-api-discovery-and-client
plan: "01"
subsystem: pinnacle-api
tags: [api-discovery, documentation, pinnacle, odds]
dependency_graph:
  requires: []
  provides: [docs/pinnacle-api-notes.md]
  affects: [data/odds.py (Plan 02), webapp/app.py (Phase 4)]
tech_stack:
  added: []
  patterns: [frozen API contract doc, human-review gate]
key_files:
  created:
    - docs/pinnacle-api-notes.md
  modified: []
decisions:
  - "API key is a guest token from JS bundle (not session cookie) — env var PINNACLE_API_KEY with PINNACLE_SESSION_COOKIE backward compat"
  - "Lookup order: PINNACLE_API_KEY env var -> data/.pinnacle_key_cache -> JS bundle extraction"
  - "Key rotation: discard cache and re-extract on 401/403"
metrics:
  duration: "~5 minutes"
  completed: 2026-04-11
---

# Phase 01 Plan 01: Pinnacle API Notes Gate - Summary

**One-liner:** Frozen Pinnacle API contract doc (docs/pinnacle-api-notes.md) from verified live research — endpoint, auth, sport ID 45, 4 leagues, American odds conversion, example JSON responses.

## What Was Built

`docs/pinnacle-api-notes.md` — 272 lines covering all 10 required sections:

1. **Base URL and Authentication** — `https://guest.api.arcadia.pinnacle.com/0.1`, required headers (`X-Api-Key`, `Referer`, `Accept`), 4-row auth behavior table verified via live calls
2. **API Key Extraction (JS Bundle)** — runtime extraction steps, `data/.pinnacle_key_cache` gitignored plain-text cache, lookup order (`PINNACLE_API_KEY` env var → cache → JS bundle), key rotation behavior
3. **Cycling Sport ID** — sport ID `45` confirmed via `/0.1/sports` endpoint
4. **Fetch Endpoints** — all 4 endpoints: sports, leagues, matchups, straight markets
5. **Active Cycling Leagues** — 4 leagues as of 2026-04-11 (Paris-Roubaix 24, Itzulia Basque Country 14, Paris-Roubaix Women 14, Itzulia Basque Country Stage 6 13 — total 65 matchups)
6. **Odds Format** — American integer odds, decimal conversion formula with examples (+107 → 2.07, -154 → 1.6494)
7. **Full Example Responses** — verbatim matchup (id: 1628017725, Kopecky vs van Moer) and straight market JSON
8. **Join Key** — `market["matchupId"] == matchup["id"]`, cast to `str` for `OddsMarket.matchup_id`
9. **Delta Updates** — `?version={max_version}` polling for Phase 4 (not Phase 1)
10. **Known Pitfalls** — all 6 pitfalls: non-list gated responses, ID mismatch, suspended markets, circular import, JSONL path, thread safety

## Status

**CHECKPOINT REACHED** — awaiting user review and approval.

`data/odds.py` has NOT been written. No client code exists. Per plan decision D-03, Plan 02 must not
start until the user explicitly approves this document.

## User Approval

**PENDING** — user must review docs/pinnacle-api-notes.md and confirm or request corrections before
Plan 02 (data/odds.py implementation) proceeds.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — this plan produced only a documentation file.

## Threat Flags

None — docs/pinnacle-api-notes.md documents the key-extraction mechanism but contains no actual
key values. The file does not introduce any new network endpoints or trust boundaries.

## Self-Check

- [x] docs/pinnacle-api-notes.md exists (272 lines)
- [x] All automated validation checks pass (guest.api.arcadia.pinnacle.com, X-Api-Key, 45, 1628017725, data/.pinnacle_key_cache, PINNACLE_API_KEY, matchupId, prices)
- [x] Commit 84ac654 exists

## Self-Check: PASSED
