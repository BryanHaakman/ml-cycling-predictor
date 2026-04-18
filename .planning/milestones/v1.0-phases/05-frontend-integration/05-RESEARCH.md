# Phase 5: Frontend Integration - Research

**Researched:** 2026-04-13
**Domain:** Vanilla JavaScript UI wiring in an existing Flask/Jinja2 single-page app
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01: New Pinnacle row always visible at top of batch-mode, above the existing Race Setup section.**
A dedicated row containing "Load from Pinnacle" (primary/accent button), a race picker dropdown (hidden until /load returns), and "Refresh Odds" (secondary button, disabled until /load succeeds). This row is always visible when the user is in batch mode.

**D-02: "Load from Pinnacle" and "Refresh Odds" live side-by-side in the same Pinnacle row.**
Load is primary (`.btn` yellow). Refresh Odds is secondary (`.btn-secondary`). Both in the same row.

**D-03: "Refresh Odds" is disabled until a successful /load has been performed.**
`refreshOddsBtn.disabled = true` on page load and after clearing. Enabled after `/load` succeeds and `_pinnacleMatchupIds` is populated.

**D-04: Race picker `<select>` appears below Load button after /load returns races.**
Hidden (`display:none`) by default. After /load returns `races[]`, populates with race names and becomes visible. Single race -> auto-select and populate immediately. Multiple races -> user must select.

**D-05: Race picker remains visible after a race is selected.**
User can switch races from same /load session by changing dropdown. Resets/hides only when Load is clicked again.

**D-06: Existing "batch-saved-race-select" dropdown is unchanged.**
Pinnacle and saved-race workflows co-exist independently.

**D-07: Load button disables and shows "Loading from Pinnacle..." while awaiting /load.**
On complete (success or error), re-enables and text resets.

**D-08: Selecting a race from Pinnacle dropdown clears all existing pairs and replaces with Pinnacle pairs.**
All rows in `#batch-pairs-container` removed. New rows added for each pair. No confirmation. User can still add manual pairs via "+ Add Pair" after loading.

**D-09: Stage fields are always replaced when a race is selected from the Pinnacle dropdown.**
All 10 stage field IDs overwritten: `batch-race-name`, `batch-race-date`, `batch-distance`, `batch-vert`, `batch-profile`, `batch-stage-type`, `batch-oneday`, `batch-climbs`, `batch-uci-tour`, `batch-race-url`. If `stage_resolved: false`, fields set to default/empty.

**D-10: `matchup_id` values stored in JS as `_pinnacleMatchupIds`.**
Module-level. Reset to `null`/empty on each new Load click.

**D-11: `data-source='auto'` set on odds inputs when populated by /load.**

**D-12: `data-source='user'` set via `oninput` listener when user edits an odds field.**

**D-13: `/refresh-odds` updates only fields still tagged `data-source='auto'`.**
JS iterates response pairs by `matchup_id`; skips `data-source='user'` cells.

**D-14: Unresolved rider autocomplete pre-filled with `best_candidate_name` hint if available.**
Score 60-89: pre-fill both visible input and hidden URL field. Score < 60 or null: leave empty.

**D-15: Unresolved rider cells get orange/warning border via CSS.**
`border-color: #ff9800` on `.autocomplete-wrap` or input. Clears when hidden URL field is populated (valid rider selected).

**D-16: Predict button is NOT blocked by unresolved rows.**
`getBatchPairs()` already silently skips pairs where `aUrl && bUrl` is false. No changes needed.

**D-17: Auth errors shown in existing `#batch-error` div.**

**D-18: Auth error message is detailed with step-by-step instructions.**
When `response.type === 'auth_error'`, display the 4-step fix referencing `PINNACLE_SESSION_COOKIE`. Non-auth errors: "Load failed: {error text}".

### Claude's Discretion

- Exact CSS for the Pinnacle control row layout (flexbox, spacing, widths)
- Whether the race picker `<select>` is styled inline or via a CSS class
- Exact JS variable names beyond `_pinnacleMatchupIds`
- Whether to add a loading spinner SVG or use text only for the button loading state
- How `matchup_id` -> row index mapping is stored (array, object, or data attribute on row)

### Deferred Ideas (OUT OF SCOPE)

- **PCS Startlist Fetch + `diff_field_rank_quality`** -- Requires fetching the full startlist. Explicitly deferred per Phase 4 D-08.
- **Visual "source" indicator on auto-populated fields** -- Discussed but out of scope.

</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UI-01 | User can click "Load from Pinnacle" in the batch H2H UI to fetch today's cycling markets | New `.pinnacle-row` HTML + `loadFromPinnacle()` JS function calling `POST /api/pinnacle/load` |
| UI-02 | User can select a race; selecting auto-populates all stage fields and all H2H pairs with odds | `populatePinnacleRace(idx)` JS function writing to 10 stage field IDs and creating pair rows |
| UI-03 | All auto-populated fields remain individually editable before running predictions | Existing inputs remain writable; `oninput` on odds sets `data-source='user'`; no form reset on edit |
| UI-04 | User can click "Refresh Odds" to update odds without clearing stage context or rider selections | `refreshOdds()` JS function calling `POST /api/pinnacle/refresh-odds`; only `data-source='auto'` odds updated |

</phase_requirements>

---

## Summary

Phase 5 is a pure frontend change -- no new backend endpoints, no new Python, no dependency additions. Both Flask endpoints (`POST /api/pinnacle/load`, `POST /api/pinnacle/refresh-odds`) were implemented and verified in Phase 4. The entire scope is wiring those endpoints into the existing batch-mode UI in `webapp/templates/index.html` using the same vanilla JavaScript patterns already present in the file.

The existing code provides everything needed as reusable primitives: `addBatchPair()` creates pair rows with correct IDs and autocomplete wiring, `clearBatchPairs()` resets the container, `setupAutocomplete()` wires the rider search, `.btn` and `.btn-secondary` CSS classes handle button styling, and `#batch-error` handles error display. Phase 5 adds one new `<div class="pinnacle-row">` in HTML, two new CSS rules, two new module-level JS state variables, and four new JS functions (`loadFromPinnacle()`, `populatePinnacleRace()`, `addPinnaclePair()`, `refreshOdds()`).

The most nuanced implementation concern is the `data-source` attribute tracking for Refresh Odds. Odds inputs must be tagged `data-source='auto'` on /load population, flipped to `data-source='user'` via `oninput`, and the refresh function must check this attribute per-field before overwriting. The `matchup_id`-to-row mapping must survive across an arbitrary number of pair additions after the initial load -- using a data attribute (`data-matchup-id`) on the pair row element is the safest approach.

**Primary recommendation:** Add the Pinnacle row HTML at line ~402 in index.html, two CSS rules in the `<style>` block, and four JS functions at the end of the `<script>` block following the established patterns exactly.

---

## Standard Stack

### Core

| Component | Source | Purpose | Why Standard |
|-----------|--------|---------|--------------|
| Vanilla JS (ES2020) | Already in index.html | All UI interaction | Project convention -- no framework |
| Fetch API | Browser built-in | HTTP calls to Flask endpoints | Already used throughout index.html |
| HTML5 `data-*` attributes | Browser built-in | `data-source` tracking, `data-matchup-id` | Clean DOM-tied state, no extra JS structures needed |
| CSS custom properties | Already in `:root` | Consistent token usage | Project convention -- all tokens declared |

[VERIFIED: webapp/templates/index.html -- no external JS dependencies, all interaction is vanilla]

### No New Dependencies

This phase adds zero new npm packages, zero new Python packages, zero new CDN imports. The constraint from CLAUDE.md "do not add dependencies to requirements.txt without asking" is trivially satisfied.

[VERIFIED: 05-CONTEXT.md -- "This phase does NOT: Add new backend endpoints... Build a new page"]

---

## Architecture Patterns

### Recommended Project Structure

No new files are created. All changes are in two existing files:

```
webapp/
├── templates/
│   └── index.html          <- all HTML + CSS + JS changes land here
└── pinnacle_bp.py          <- read-only reference (Phase 4 output, unchanged)
tests/
└── test_pinnacle_bp.py     <- already covers backend; Phase 5 adds frontend smoke test
```

### Pattern 1: Module-Level JS State

The existing `<script>` block maintains module-level state variables. Phase 5 adds two more following the existing convention exactly.

**Existing pattern (lines 882-883 of index.html):**
```javascript
// Source: webapp/templates/index.html lines 882-883
let batchPairCounter = 0;
let _batchResults = [];
```

**Phase 5 additions (insert after existing state declarations):**
```javascript
let _pinnacleRaces = null;      // Full /load response races[]
let _pinnacleMatchupIds = null; // Set of matchup_id strings for early-exit guard in refreshOdds()
```

### Pattern 2: Button Disable/Re-enable with Finally

The `batchPredict()` function establishes the pattern Phase 5 must follow exactly.

**Source: webapp/templates/index.html lines 1032-1058:**
```javascript
btn.disabled = true;
btn.textContent = `Predicting ${pairs.length} matchups...`;
try {
    const res = await fetch('/api/predict/batch', { ... });
    const data = await res.json();
    if (data.error) { err.textContent = data.error; err.style.display = 'block'; return; }
    // ... success handling
} catch(e) {
    err.textContent = 'Batch prediction failed: ' + e.message;
    err.style.display = 'block';
} finally {
    btn.disabled = false;
    btn.textContent = 'Predict All H2H';
}
```

**Phase 5 `loadFromPinnacle()` must follow this pattern:**
```javascript
// Source: established pattern from batchPredict()
async function loadFromPinnacle() {
    const btn = document.getElementById('load-pinnacle-btn');
    const err = document.getElementById('batch-error');
    _pinnacleRaces = null;
    _pinnacleMatchupIds = null;
    document.getElementById('refresh-odds-btn').disabled = true;
    document.getElementById('pinnacle-race-select').style.display = 'none';
    err.style.display = 'none';
    btn.disabled = true;
    btn.textContent = 'Loading from Pinnacle...';
    try {
        const res = await fetch('/api/pinnacle/load', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({})
        });
        const data = await res.json();
        if (res.status === 401 && data.type === 'auth_error') {
            err.innerHTML = `Session expired. To fix:<br>
1. Open DevTools on pinnacle.ca -> Network tab -> any request<br>
2. Copy the X-Session header value<br>
3. Set ${data.env_var}=&lt;value&gt; in your environment<br>
4. Restart Flask (python webapp/app.py)`;
            err.style.display = 'block';
            return;
        }
        if (data.error) {
            err.textContent = `Load failed: ${data.error}`;
            err.style.display = 'block';
            return;
        }
        // data.races[] available -- populate picker
        _pinnacleRaces = data.races;
        populateRacePicker(data.races);
    } catch(e) {
        err.textContent = 'Load failed: ' + e.message;
        err.style.display = 'block';
    } finally {
        btn.disabled = false;
        btn.textContent = 'Load from Pinnacle';
    }
}
```

### Pattern 3: addPinnaclePair() Helper (Not addBatchPair)

`addBatchPair()` creates pair rows by appending to `#batch-pairs-container` and calling `setupAutocomplete()`. Phase 5's `populatePinnacleRace()` must NOT call `addBatchPair()` directly because it needs to:
1. Pre-fill rider name inputs and hidden URL inputs with resolved data
2. Set `data-source='auto'` on odds inputs
3. Add an `oninput` handler on odds inputs
4. Add `data-matchup-id` attribute to the row element for refresh matching
5. Apply orange border class to unresolved rider cells
6. Pass `onSelect` callback to `setupAutocomplete()` for unresolved border clearing

**The required approach:** Write a new `addPinnaclePair(pair)` helper that mirrors `addBatchPair()`'s HTML structure exactly but accepts pair data and sets those additional attributes. This avoids modifying `addBatchPair()` while maintaining consistent row structure.

[VERIFIED: webapp/templates/index.html lines 916-948 -- addBatchPair() structure confirmed]

### Pattern 4: matchup_id Persistence via DOM Attribute

The `matchup_id` must survive: (a) the initial `/load` call, (b) user edits to rider cells, (c) additional pairs added via "+ Add Pair". Using `data-matchup-id` attribute on the `.batch-pair-row` element is the correct approach:

```javascript
// When creating a Pinnacle pair row in addPinnaclePair():
row.setAttribute('data-matchup-id', pair.matchup_id);

// In refreshOdds() — DOM-based lookup, NOT positional array:
document.querySelectorAll('#batch-pairs-container .batch-pair-row').forEach(row => {
    const mid = row.getAttribute('data-matchup-id');
    if (!mid) return; // manually-added rows have no matchup_id -- skip
    const updated = refreshData.find(p => p.matchup_id === mid);
    if (!updated) return; // market closed -- skip silently
    const oddsAEl = row.querySelector(`[id^="bp-odds-a-"]`);
    const oddsBEl = row.querySelector(`[id^="bp-odds-b-"]`);
    if (oddsAEl && oddsAEl.getAttribute('data-source') === 'auto') oddsAEl.value = updated.odds_a;
    if (oddsBEl && oddsBEl.getAttribute('data-source') === 'auto') oddsBEl.value = updated.odds_b;
});
```

This approach handles: manual pairs added after load (no `data-matchup-id`, safely skipped), closed markets (omitted from refresh response, safely skipped), and user-edited odds (tagged `data-source='user'`, safely skipped).

**`_pinnacleMatchupIds` is a Set of matchup_id strings** used ONLY as an early-exit guard in `refreshOdds()` (return immediately if null/empty) and for building the request body. It is NOT used for row-index lookup -- that is done via DOM `data-matchup-id` attributes.

### Pattern 5: Stage Field Population

`getBatchRaceParams()` (lines 995-1009) reads from 10 specific field IDs. `populatePinnacleRace()` must write to those same IDs. The `stage_context` response fields map as follows:

[VERIFIED: docs/pinnacle-api-notes.md Phase 4 + webapp/templates/index.html lines 995-1009]

| stage_context field | HTML element ID | Set method |
|---------------------|----------------|------------|
| `race_name` (from race entry) | `batch-race-name` | `.value = race.race_name` |
| `race_date` | `batch-race-date` | `.value = ctx.race_date` |
| `distance` | `batch-distance` | `.value = ctx.distance` |
| `vertical_meters` | `batch-vert` | `.value = ctx.vertical_meters` |
| `profile_icon` | `batch-profile` | `.value = ctx.profile_icon` |
| `stage_type` | `batch-stage-type` | `.value = ctx.stage_type` |
| `is_one_day_race` | `batch-oneday` | `.value = ctx.is_one_day_race ? '1' : '0'` |
| `num_climbs` | `batch-climbs` | `.value = ctx.num_climbs` |
| `uci_tour` | `batch-uci-tour` | `.value = ctx.uci_tour` |
| `race_base_url` | `batch-race-url` | `.value = ctx.race_base_url || ''` |

When `stage_resolved === false`, all `stage_context` fields will be zero/null defaults. The code must tolerate these gracefully -- `distance=0` maps to `.value = 0`, which is valid DOM behavior (user must manually fill before predicting).

### Pattern 6: Unresolved Rider Handling via setupAutocomplete onSelect Callback

The orange border requires knowing whether the rider is resolved at row-creation time and clearing it when the user makes a valid selection. The correct approach is to modify `setupAutocomplete` to accept an optional 5th `onSelect` callback:

```javascript
function setupAutocomplete(inputId, listId, hiddenId, endpoint, onSelect) {
    // ...existing code...
    div.onclick = () => {
        input.value = label;
        hidden.value = item.url;
        list.classList.remove('active');
        if (onSelect) onSelect(item);  // NEW -- guarded, backward-compatible
    };
}
```

Then `addPinnaclePair()` passes a callback that clears the unresolved border:
```javascript
const onResolve = () => aWrap.parentElement.classList.remove('unresolved-rider');
setupAutocomplete(`bp-a-input-${idx}`, `bp-a-list-${idx}`, `bp-a-url-${idx}`, '/api/riders', onResolve);
```

This is backward-compatible -- all existing `setupAutocomplete()` calls pass no 5th argument, `onSelect` is undefined, and the `if (onSelect)` guard prevents errors.

**DO NOT use MutationObserver** for this. MutationObserver watches DOM attribute changes, but programmatic `.value` property assignment does not trigger attribute change events. The `onSelect` callback is the only reliable mechanism.

[VERIFIED: webapp/templates/index.html lines 640-674 -- setupAutocomplete function, no existing 5th argument]

### Anti-Patterns to Avoid

- **Calling `addBatchPair()` directly from `populatePinnacleRace()`:** `addBatchPair()` appends a blank row to the container. It does not accept data parameters. Calling it and then setting values afterwards works but creates a flash of empty rows and complicates error handling. Write `addPinnaclePair(pair)` instead.
- **Using `innerHTML` to detect row existence:** `getBatchPairs()` uses `querySelectorAll` on `.batch-pair-row` class. Pinnacle pair rows must use this same class so `getBatchPairs()` works without modification.
- **Storing `_pinnacleMatchupIds` as an array parallel to DOM rows:** Row removal (user clicks X) shifts the array index. Use `data-matchup-id` on the DOM element -- it travels with the row.
- **Using MutationObserver to watch hidden URL field `.value` changes:** MutationObserver does not reliably fire on programmatic `.value` property changes (only attribute changes). Use `setupAutocomplete` `onSelect` callback instead.
- **Setting `batch-race-date` to `ctx.race_date` when `stage_resolved === false`:** The default value is `""` (empty string) or `null`. The input is `type="date"` -- an empty string is valid and preferable to a zero date string.
- **Using `.innerHTML` for multi-line auth error:** Set `.innerHTML` for the auth error message (it contains `<br>` tags per the copywriting contract). Set `.textContent` for all non-auth errors to prevent XSS from server error messages.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rider search | Custom search input | Existing `setupAutocomplete()` | Already handles debounce, dropdown, hidden URL field |
| Button loading state | Custom spinner component | Text + `disabled` pattern from `batchPredict()` | Consistent with existing UX |
| Pair row HTML | New layout | Clone structure from `addBatchPair()` exactly | `getBatchPairs()` depends on specific IDs and class |
| Error display | New error component | Existing `#batch-error.error-msg` | Already styled and positioned |
| CSS tokens | New variables | Existing `:root` CSS variables | Project convention -- no new variables |

---

## Common Pitfalls

### Pitfall 1: `batchPairCounter` Counter Misalignment

**What goes wrong:** `addBatchPair()` uses `batchPairCounter++` as the pair index for IDs. If `populatePinnacleRace()` calls `clearBatchPairs()` (which resets `batchPairCounter = 0`) and then creates pairs with its own indices, the counter and the DOM stay in sync. But if the user then clicks "+ Add Pair", the counter continues from where `addBatchPair()` left off -- which is correct only if `clearBatchPairs()` reset the counter before Pinnacle pairs were added.

**How to avoid:** Always call `clearBatchPairs()` first in `populatePinnacleRace()`. This resets `batchPairCounter = 0`. Then use the same `batchPairCounter++` pattern (or a local counter that also increments `batchPairCounter`) when creating Pinnacle pair rows.

[VERIFIED: webapp/templates/index.html lines 961-965 -- clearBatchPairs() resets batchPairCounter = 0]

### Pitfall 2: `data-source` Attribute Not Set Before `oninput` Fires

**What goes wrong:** If the `oninput` handler is wired before the `value` is programmatically set, and the browser fires `input` on programmatic value assignment in some browsers/scenarios, an auto-populated cell immediately becomes `data-source='user'`.

**How to avoid:** Set `setAttribute('data-source', 'auto')` on the odds input AFTER setting `.value`, THEN add the `oninput` listener. Or set the attribute unconditionally in the handler: `oninput="if(this.getAttribute('data-source') !== 'user') this.setAttribute('data-source','user')"` -- but this is redundant since user input always means user edit. The safe order is: (1) set `.value`, (2) set `data-source='auto'`, (3) attach `oninput` that sets `data-source='user'`.

**Warning signs:** Refresh Odds updates no fields despite user not having edited any -- means all cells got tagged `user` on population.

### Pitfall 3: Race Picker `onchange` Fires Before `_pinnacleRaces` Is Populated

**What goes wrong:** If `populateRacePicker()` adds options and makes the select visible, but `_pinnacleRaces` is assigned after this (async timing), then the `onchange` handler fires with a stale null value.

**How to avoid:** Assign `_pinnacleRaces = data.races` before calling `populateRacePicker()`. Both are synchronous after the `await fetch()`.

### Pitfall 4: Single-Race Auto-Select Bypasses Picker

**What goes wrong:** D-04 states that a single race is auto-selected immediately. If `populatePinnacleRace(0)` is called before the select element has its option added, the option won't have a matching value to highlight.

**How to avoid:** Call `populateRacePicker(races)` first (adds option, makes select visible, selects the value), then call `populatePinnacleRace(0)`. Or: if `races.length === 1`, skip adding to picker and call populate directly -- but keep the picker visible with the single item so user has context.

### Pitfall 5: HTTP Status vs. Response Body for Auth Errors

**What goes wrong:** Code checks `if (data.error)` to detect all errors, but the 401 response also has `data.type === 'auth_error'`. A generic error handler would show a terse message instead of the detailed 4-step fix.

**How to avoid:** Check `res.status` and `data.type` explicitly before the generic error handler:
```javascript
if (res.status === 401 && data.type === 'auth_error') {
    // Show detailed instructions with data.env_var
} else if (data.error) {
    // Show generic: "Load failed: {data.error}"
}
```

[VERIFIED: docs/pinnacle-api-notes.md Phase 4 Error Response Schemas -- 401 has type: 'auth_error' + env_var field]

### Pitfall 6: Autocomplete `setupAutocomplete` 5th-Argument Change Must Be Backward-Compatible

**What goes wrong:** If the signature change `setupAutocomplete(inputId, listId, hiddenId, endpoint, onSelect)` is not backward-compatible, the three existing calls at lines 676-678 that pass 4 arguments will crash.

**How to avoid:** Make `onSelect` optional with `if (onSelect) onSelect(item)` guard. The three existing calls are:
```javascript
// Lines 676-678 -- these pass 4 args, must still work
setupAutocomplete('rider-a-input', 'rider-a-list', 'rider-a-url', '/api/riders');
setupAutocomplete('rider-b-input', 'rider-b-list', 'rider-b-url', '/api/riders');
setupAutocomplete('race-input', 'race-list', 'stage-url', '/api/races');
```
[VERIFIED: webapp/templates/index.html lines 676-678]

---

## Code Examples

Verified patterns from the existing codebase:

### Existing clearBatchPairs()
```javascript
// Source: webapp/templates/index.html lines 961-965
function clearBatchPairs() {
    document.getElementById('batch-pairs-container').innerHTML = '';
    batchPairCounter = 0;
    updateBatchPairCount();
}
```

### Existing addBatchPair() -- Structure to Mirror
```javascript
// Source: webapp/templates/index.html lines 916-948
function addBatchPair() {
    const container = document.getElementById('batch-pairs-container');
    const idx = batchPairCounter++;
    const row = document.createElement('div');
    row.className = 'batch-pair-row';
    row.id = `batch-pair-${idx}`;
    row.innerHTML = `
        <div class="form-group">
            <div class="autocomplete-wrap">
                <input type="text" id="bp-a-input-${idx}" placeholder="Search rider A..." autocomplete="off">
                <div class="autocomplete-list" id="bp-a-list-${idx}"></div>
                <input type="hidden" id="bp-a-url-${idx}">
            </div>
        </div>
        ...
        <div class="form-group">
            <input type="number" id="bp-odds-a-${idx}" placeholder="e.g. 1.73" step="0.01" min="1.01">
        </div>
        ...
    `;
    container.appendChild(row);
    setupAutocomplete(`bp-a-input-${idx}`, `bp-a-list-${idx}`, `bp-a-url-${idx}`, '/api/riders');
    setupAutocomplete(`bp-b-input-${idx}`, `bp-b-list-${idx}`, `bp-b-url-${idx}`, '/api/riders');
    updateBatchPairCount();
}
```

### Existing Fetch Pattern
```javascript
// Source: webapp/templates/index.html lines 1036-1041
const res = await fetch('/api/predict/batch', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ pairs, race_params: raceParams }),
});
const data = await res.json();
if (data.error) { err.textContent = data.error; err.style.display = 'block'; return; }
```

### Frozen /load Response Schema (excerpt)
```json
{
  "races": [{
    "race_name": "Tour de Romandie",
    "stage_resolved": true,
    "stage_context": { "distance": 156.0, "profile_icon": "p1", ... },
    "pairs": [{
      "pinnacle_name_a": "ROGLIC Primoz",
      "rider_a_url": "rider/primoz-roglic",
      "rider_a_resolved": true,
      "best_candidate_a_name": null,
      "best_candidate_a_url": null,
      "odds_a": 1.85,
      "matchup_id": "12345"
    }]
  }]
}
```
[VERIFIED: docs/pinnacle-api-notes.md Phase 4 -- POST /api/pinnacle/load Response Schema]

### Frozen /refresh-odds Response Schema
```json
{
  "pairs": [
    {"matchup_id": "12345", "odds_a": 1.90, "odds_b": 2.05}
  ]
}
```
[VERIFIED: docs/pinnacle-api-notes.md Phase 4 -- POST /api/pinnacle/refresh-odds Response Schema]

### UI-SPEC New CSS Rules (verbatim from approved 05-UI-SPEC.md)
```css
.pinnacle-row {
    display: flex;
    gap: 0.5rem;
    align-items: flex-end;
    flex-wrap: wrap;
    margin-bottom: 1.5rem;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid var(--border);
}

.unresolved-rider input,
.unresolved-rider .autocomplete-wrap > input {
    border-color: #ff9800;
}
```
[VERIFIED: .planning/phases/05-frontend-integration/05-UI-SPEC.md -- "New CSS Required" section]

### UI-SPEC Layout Reference (verbatim from approved 05-UI-SPEC.md)
```
#batch-mode
+-- .pinnacle-row                         <- NEW (Phase 5)
|   +-- button#load-pinnacle-btn (.btn)
|   +-- select#pinnacle-race-select       <- hidden until /load succeeds
|   +-- button#refresh-odds-btn (.btn-secondary, disabled)
+-- .form-group.full "Race Setup"         <- existing, unchanged (line ~403)
+-- "H2H Pairs" header row                <- existing, unchanged
+-- #batch-pairs-container
+-- .batch-actions
+-- button#batch-predict-btn (.btn)
+-- #batch-error (.error-msg)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| N/A -- Phase 5 is net-new UI wiring | Vanilla JS + data attributes | N/A | No migration needed |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `setupAutocomplete` 5th-argument modification is the correct approach for unresolved border clearing | Architecture Patterns 6 | If the reviewer prefers a different mechanism, the implementation changes but the outcome is identical -- low impact |
| A2 | `batchPairCounter` is safe to increment within `addPinnaclePair()` because it's module-scoped and `clearBatchPairs()` resets it | Common Pitfalls 1 | If counter gets out of sync, pair IDs could collide -- verify `clearBatchPairs()` is always called first |

---

## Open Questions (RESOLVED)

1. **`addPinnaclePair()` vs. modifying `addBatchPair()`** -- RESOLVED
   - Decision: Create `addPinnaclePair(pair)` as a separate function. `addBatchPair()` creates blank rows and does not accept data parameters. Calling it and then post-filling values is an anti-pattern (flash of empty rows, counter sync risk). `addPinnaclePair()` mirrors the same HTML structure but accepts pair data, sets `data-matchup-id` on the row element, and handles `data-source`/unresolved-rider attributes at creation time. CONTEXT.md D-08 confirms "+ Add Pair" must remain functional after load -- keeping `addBatchPair()` unmodified satisfies this.

2. **How to handle `stage_resolved: false` for stage fields** -- RESOLVED
   - Decision: Set to empty string `''` for numeric fields when `stage_resolved === false`. This prevents `getBatchRaceParams()` from seeing `0` as valid distance (it checks `distance > 0`). The `|| ''` fallback in `populatePinnacleRace()` handles this naturally since `0` is falsy in JavaScript.

---

## Environment Availability

Step 2.6: SKIPPED -- Phase 5 is HTML/CSS/JS changes only. No external tools, CLIs, or services needed beyond the running Flask app (`python webapp/app.py`) that is already required for any UI work.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (confirmed in use) |
| Config file | none -- uses `tests/conftest.py` |
| Quick run command | `pytest tests/test_pinnacle_bp.py -v` |
| Full suite command | `pytest tests/ -v` |

[VERIFIED: tests/ directory listing -- pytest files confirmed present]

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UI-01 | Load button calls POST /api/pinnacle/load | Integration (backend already covered) | `pytest tests/test_pinnacle_bp.py -v` | Yes |
| UI-02 | Race selection populates stage fields and pairs | Manual visual test (frontend JS) | manual -- no JS test framework | N/A |
| UI-03 | Edited fields not reset by load | Manual visual test (frontend JS) | manual -- no JS test framework | N/A |
| UI-04 | Refresh Odds skips user-edited cells | Manual visual test (frontend JS) | manual -- no JS test framework | N/A |

**Note:** The existing test suite covers the backend endpoints thoroughly (`test_pinnacle_bp.py` -- 9 tests). Phase 5 changes are exclusively frontend JS behavior in `index.html`. The project has no frontend test framework (no Jest, no Playwright, no Cypress). Manual verification against the success criteria is the appropriate gate for UI behavior.

### Sampling Rate

- **Per task commit:** `pytest tests/test_pinnacle_bp.py -v` (confirm no backend regressions)
- **Per wave merge:** `pytest tests/ -v` (full suite green)
- **Phase gate:** `pytest tests/ -v` passes + manual visual verification of all 4 success criteria

### Wave 0 Gaps

None -- existing test infrastructure covers all backend phase requirements. Frontend behavior requires manual testing only.

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Localhost gate is backend-enforced (Phase 4, `_require_localhost`) |
| V3 Session Management | no | No server-side session added (explicitly excluded in CONTEXT.md boundary) |
| V4 Access Control | no | Backend-enforced via `_require_localhost` |
| V5 Input Validation | yes | All API response fields rendered as `.value` or `.textContent` -- no `innerHTML` from server data except auth error instructions (safe -- server controls the `env_var` field content) |
| V6 Cryptography | no | No crypto operations in frontend |

### Known Threat Patterns for Vanilla JS / Flask Frontend

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| XSS via server error messages in innerHTML | Tampering | Use `.textContent` for all `data.error` strings; only use `.innerHTML` for the static auth error message template |
| CSRF on POST endpoints | Spoofing | Flask endpoints are localhost-only (`_require_localhost`); CSRF is not a meaningful vector for localhost-only tools |
| Open Redirect via `race_base_url` field | Tampering | Field is set as `input.value` only -- never used in `window.location` or `href` |

**Key security note:** The auth error message uses `.innerHTML` and includes `data.env_var` from the server response. The `env_var` value is always `"PINNACLE_SESSION_COOKIE"` (hardcoded in `pinnacle_bp.py`). This is safe -- it cannot be injected by a third party. However, for defense-in-depth, the planner should use a template string with `data.env_var` escaped, not raw HTML interpolation.

[VERIFIED: webapp/pinnacle_bp.py lines 36, 107 -- env_var is always the literal string "PINNACLE_SESSION_COOKIE"]

---

## Sources

### Primary (HIGH confidence)
- `webapp/templates/index.html` -- Full existing batch-mode HTML (lines 402-526) and JS (lines 529-end). All function signatures, IDs, and patterns verified by direct read.
- `webapp/pinnacle_bp.py` -- Both endpoint implementations confirmed working (Phase 4 output).
- `docs/pinnacle-api-notes.md Phase 4` -- Frozen /load and /refresh-odds response schemas, HTTP status table, error schemas. Verified against live API data 2026-04-11.
- `.planning/phases/05-frontend-integration/05-CONTEXT.md` -- All 18 locked decisions (D-01 through D-18), reusable assets, integration points.
- `.planning/phases/05-frontend-integration/05-UI-SPEC.md` -- Approved design contract: CSS tokens, new CSS rules, component inventory, interaction states, copywriting, JS state contract.

### Secondary (MEDIUM confidence)
- `.planning/REQUIREMENTS.md` -- UI-01 through UI-04 acceptance criteria.
- `tests/test_pinnacle_bp.py` -- Backend test coverage confirmed (9 tests covering both endpoints, all error paths, localhost gate).

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new dependencies; all patterns directly read from existing code
- Architecture: HIGH -- all patterns verified from existing index.html + frozen API schemas
- Pitfalls: HIGH -- derived from direct code analysis of the exact functions being modified

**Research date:** 2026-04-13
**Valid until:** 2026-05-13 (stable -- no external dependencies that could change)
