# Phase 5: Frontend Integration - Context

**Gathered:** 2026-04-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire two new JavaScript-driven buttons — "Load from Pinnacle" and "Refresh Odds" — into the existing batch H2H prediction UI in `webapp/templates/index.html`. Clicking "Load from Pinnacle" calls `POST /api/pinnacle/load` and pre-populates all stage fields and all H2H pair rows. Clicking "Refresh Odds" calls `POST /api/pinnacle/refresh-odds` and updates only odds fields that the user has not manually edited.

**This phase does NOT:**
- Change the prediction logic or `/api/predict/batch` endpoint
- Add new backend endpoints (both endpoints were built in Phase 4)
- Build a new page — all changes are in the existing `batch-mode` div in `index.html`
- Add server-side session state

The user's flow after this phase:
1. Switch to Batch H2H mode
2. Click "Load from Pinnacle" → select a race → stage fields and pair rows populate
3. Review/edit any field (odds, riders, stage details)
4. Click "⚡ Predict All H2H" (existing button, unchanged)
5. Optionally click "Refresh Odds" to pull latest odds without disturbing edits

</domain>

<decisions>
## Implementation Decisions

### Pinnacle Control Row (button placement)

**D-01: New Pinnacle row always visible at top of batch-mode, above the existing Race Setup section.**
A dedicated row containing "Load from Pinnacle" (primary/accent button), a race picker dropdown (hidden until /load returns), and "Refresh Odds" (secondary button, disabled until /load succeeds). This row is always visible when the user is in batch mode — no toggle, no collapse.

**D-02: "Load from Pinnacle" and "Refresh Odds" live side-by-side in the same Pinnacle row.**
Load is the primary action (styled like the existing `.btn` accent/yellow). Refresh Odds is secondary (styled like `.btn-secondary`). Both are in the same row.

**D-03: "Refresh Odds" is disabled until a successful /load has been performed.**
On page load and after clearing, `refreshOddsBtn.disabled = true`. After `/load` succeeds and `_pinnacleMatchupIds` is populated, enable the button. This prevents confusion about refreshing before any data has been loaded.

### Race Picker Dropdown

**D-04: A new race picker `<select>` appears below the Load button after /load returns races.**
The dropdown is hidden (`display:none`) by default. After /load returns `races[]`, it populates with the race names and becomes visible. If only one race is returned, auto-select it immediately and populate the form without requiring user interaction. If multiple races, the user must explicitly select one.

**D-05: The race picker dropdown remains visible after a race is selected.**
The user can switch to a different race from the same /load session by changing the dropdown selection — no need to click Load again. The dropdown only resets/hides when Load is clicked again (new /load call begins).

**D-06: The existing "Saved Race" dropdown (`batch-saved-race-select`) is unchanged.**
Pinnacle and saved-race workflows co-exist independently. The Pinnacle row sits above the existing Race Setup section; the saved-race dropdown remains in place below it.

### Load Button State

**D-07: "Load from Pinnacle" button disables and shows "⏳ Loading from Pinnacle..." while awaiting /load response.**
Pattern matches the existing Predict button behavior. On complete (success or error), button re-enables and text resets to "Load from Pinnacle".

### Post-Load Population

**D-08: Selecting a race from the Pinnacle dropdown clears all existing pairs and replaces with Pinnacle pairs.**
All rows in `#batch-pairs-container` are removed. New rows are added for each pair in the selected race's `pairs[]`. No confirmation prompt — clear-and-replace is the primary use case. The user can still add manual pairs via "+ Add Pair" after loading.

**D-09: Stage fields are always replaced when a race is selected from the Pinnacle dropdown.**
`batch-race-name`, `batch-race-date`, `batch-distance`, `batch-vert`, `batch-profile`, `batch-stage-type`, `batch-oneday`, `batch-climbs`, `batch-uci-tour`, `batch-race-url` are all overwritten with values from the `/load` `stage_context` object. If `stage_resolved: false`, fields are set to their default/empty state. User can edit any field after loading.

**D-10: `matchup_id` values from /load are stored in JS as `_pinnacleMatchupIds` (array or mapping).**
Required for stateless `/refresh-odds` calls. Stored at the module level in the `<script>` block alongside other existing JS state variables (`batchPairCounter`, `_batchResults`, `_savedRaces`, etc.). Reset to `null`/empty on each new "Load from Pinnacle" click.

### Refresh Odds: data-source Tracking

**D-11: `data-source='auto'` attribute set on odds input elements when populated by /load.**
When populating pair rows from /load data, set `setAttribute('data-source', 'auto')` on both `bp-odds-a-{idx}` and `bp-odds-b-{idx}` inputs.

**D-12: `data-source='user'` set via `oninput` listener when user edits an odds field.**
Each odds input has an `oninput` handler: `this.setAttribute('data-source', 'user')`. Once set to `'user'`, Refresh Odds will skip that specific field.

**D-13: `/refresh-odds` call sends all stored `matchup_ids`; response updates only fields still tagged `data-source='auto'`.**
JS iterates the refresh response `pairs[]`, finds the matching row by `matchup_id`, and for each pair updates `bp-odds-a-{idx}` and `bp-odds-b-{idx}` only if their `data-source` attribute is `'auto'`. User-edited cells (`data-source='user'`) are untouched.

### Unresolved Pair Visual Treatment

**D-14: Unresolved rider autocomplete pre-filled with `best_candidate_name` hint if available.**
If `rider_a_resolved: false` and `best_candidate_a_name` is non-null (score 60–89), pre-fill `bp-a-input-{idx}` with `best_candidate_a_name` and set `bp-a-url-{idx}` to `best_candidate_a_url`. If no hint (score < 60 or null), leave the input empty with default placeholder "Search rider...".

**D-15: Unresolved rider cells get an orange/warning border via CSS.**
Apply `border-color: var(--accent)` (or an explicit orange `#ff9800`) to the `.autocomplete-wrap` or input element of any unresolved rider. Clears immediately when the user selects a valid rider from the autocomplete dropdown (i.e., when the hidden URL field is populated).

**D-16: Predict button is not blocked by unresolved rows.**
Unresolved pairs (missing rider URL) are silently skipped by the existing `getBatchPairs()` function, which already only pushes pairs where `aUrl && bUrl`. No change to prediction button behavior.

### Auth Error Display

**D-17: Auth errors shown in the existing `#batch-error` div below the Pinnacle row.**
Reuses the existing error display pattern. No new component needed.

**D-18: Auth error message is detailed with step-by-step instructions naming the specific env var.**
When `response.type === 'auth_error'`, display:
```
Session expired. To fix:
1. Open DevTools on pinnacle.ca → Network tab → any request
2. Copy the X-Session header value
3. Set PINNACLE_SESSION=<value> in your environment
4. Restart Flask (python webapp/app.py)
```
The `env_var` field from the response (`PINNACLE_SESSION_COOKIE`) is included in the message. Non-auth errors (network failure, 500) use a shorter message: "Load failed: {error text}".

### Claude's Discretion

- Exact CSS for the Pinnacle control row layout (flexbox, spacing, widths)
- Whether the race picker `<select>` is styled inline or via a CSS class
- Exact JS variable names beyond `_pinnacleMatchupIds`
- Whether to add a loading spinner SVG or use text only for the button loading state
- How `matchup_id` → row index mapping is stored (array, object, or data attribute on row)

</decisions>

<specifics>
## Specific Implementation Notes

- The frozen `/load` and `/refresh-odds` response schemas are in `docs/pinnacle-api-notes.md` §Phase 4. The planner MUST read this before writing any task involving the API response shape.
- The `data-source` attribute approach is explicitly named in ROADMAP.md success criteria SC4 — it is not a suggestion, it is the implementation contract.
- `matchup_id` stability across multiple Pinnacle API calls was confirmed in Phase 4 live verification — it is safe to use as the key for stateless refresh matching.
- The autocomplete pattern (`setupAutocomplete`) in `index.html` wires input → dropdown list → hidden URL field. Unresolved pair pre-fill must set both the visible input AND the hidden URL (if a candidate URL is available).
- Stage field IDs in the existing HTML: `batch-race-name`, `batch-race-date`, `batch-distance`, `batch-vert`, `batch-profile`, `batch-stage-type`, `batch-oneday`, `batch-climbs`, `batch-uci-tour`, `batch-race-url` — planner must use exact IDs when writing populate logic.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### API Response Schemas (frozen contract)
- `docs/pinnacle-api-notes.md` §Phase 4 — Frozen `/load` and `/refresh-odds` response schemas. Do not deviate from this shape.

### Requirements
- `.planning/REQUIREMENTS.md` §UI-01, §UI-02, §UI-03, §UI-04 — Acceptance criteria for this phase
- `.planning/REQUIREMENTS.md` §ODDS-03 — Auth error message must include env var name

### Existing Frontend (read before modifying)
- `webapp/templates/index.html` — Full existing batch-mode HTML and JS. Read the entire `#batch-mode` div (lines ~402–526) and the JS section (lines ~530+) before writing any modification tasks. Key functions: `addBatchPair()`, `getBatchPairs()`, `getBatchRaceParams()`, `batchPredict()`, `setupAutocomplete()`.

### Backend (Phase 4 outputs)
- `webapp/pinnacle_bp.py` — Blueprint with `/api/pinnacle/load` and `/api/pinnacle/refresh-odds` endpoints. Read to confirm exact request/response handling.
- `webapp/auth.py` — `_require_localhost` decorator (Phase 5 does not use this directly, but understanding the localhost gate is relevant for testing)

### Prior Phase Context
- `.planning/phases/04-flask-endpoint-wiring/04-CONTEXT.md` — D-01 through D-08 decisions that Phase 5 must respect
- `.planning/phases/04-flask-endpoint-wiring/04-01-SUMMARY.md` — Live API findings, confirmed URL, required headers, env vars

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `setupAutocomplete(inputId, listId, urlId, endpoint)` — existing function in index.html wires rider search. Use for unresolved pair rows (already called by `addBatchPair()`).
- `.btn` and `.btn-secondary` CSS classes — existing button styles. Use for Load (accent) and Refresh (secondary).
- `#batch-error` div — existing error display. Set `textContent` and `style.display='block'` to show errors; `style.display='none'` to hide.
- `addBatchPair()` — creates a new pair row with correct IDs and autocomplete setup. Phase 5's `populatePinnacleRace()` function will call or replicate this pattern.
- `clearBatchPairs()` — clears all rows and resets `batchPairCounter`. Phase 5's load handler calls this before populating Pinnacle pairs.

### Established Patterns
- JS state variables at module level (e.g., `_savedRaces`, `_batchResults`, `batchPairCounter`). Add `_pinnacleMatchupIds` and `_pinnacleRaces` to this pattern.
- Button disable pattern: `btn.disabled = true; btn.textContent = '⏳ ...'; ... finally { btn.disabled = false; btn.textContent = 'original'; }` — already used in `batchPredict()`.
- Fetch pattern: `const res = await fetch(url, { method: 'POST', headers: {...}, body: JSON.stringify({...}) }); const data = await res.json(); if (data.error) { ... }`.

### Integration Points
- New Pinnacle row inserts before the existing "Race Setup" `<div class="form-group full">` (line ~402 in index.html)
- `_pinnacleMatchupIds` consumed by the new `refreshOdds()` function, which calls `POST /api/pinnacle/refresh-odds`
- Race picker `onchange` event triggers `populatePinnacleRace(raceIdx)` which writes to all existing stage field IDs

</code_context>

<deferred>
## Deferred Ideas

- **PCS Startlist Fetch + `diff_field_rank_quality`** — Computing real field rank quality scores requires fetching the full startlist. Explicitly deferred per Phase 4 D-08. This is a future sub-phase.
- **Visual "source" indicator on auto-populated fields** — Showing a small Pinnacle icon or tinted background on auto-populated stage fields to distinguish them from manual entries. Discussed but out of scope for Phase 5 — would add visual complexity without changing behavior.

</deferred>

---

*Phase: 05-frontend-integration*
*Context gathered: 2026-04-12*
