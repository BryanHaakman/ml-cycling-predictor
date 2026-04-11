# Feature Landscape: PaceIQ v1.0 — Pinnacle Preload

**Domain:** Betting intelligence tool — "load from external source" pre-fill flow
**Researched:** 2026-04-11
**Scope:** Five feature groups in the Pinnacle Preload milestone only. Existing features (batch prediction, Kelly staking, P&L) are already built and not re-researched.

---

## Feature Groups (Build Order = Dependency Order)

The five feature groups have hard build dependencies. They must be sequenced:

```
[1] Pinnacle API Client
        |
        v
[2] Name Resolver          [3] Stage Context Fetcher
        \                         /
         v                       v
       [4] Flask Endpoints (load + refresh-odds)
                    |
                    v
             [5] Batch UI Updates
```

Group 1 is the foundation: nothing else can be built without verified odds data to work with. Groups 2 and 3 are independent of each other but both depend on Group 1 for realistic test data. Group 4 wires Groups 1–3 together. Group 5 is purely frontend and depends on Group 4.

---

## Group 1: Pinnacle Internal API Client

**Requirements:** ODDS-01, ODDS-02, ODDS-03, ODDS-04

### What It Does

Makes authenticated HTTP requests to Pinnacle's internal web frontend API to retrieve today's cycling H2H special markets. Returns structured data: market_id, race name, stage name, rider A name, rider B name, decimal odds A, decimal odds B.

### Table Stakes (must work or the feature is useless)

| Behavior | Why Non-Negotiable |
|----------|-------------------|
| Returns structured market data (market_id, riders, odds) | Everything downstream depends on this shape |
| Handles expired/invalid cookie with clear error | User must know which env var to update; silent failure wastes session |
| Appends raw response to `data/odds_log.jsonl` on success | Audit trail; required for debugging when market data looks wrong |
| Filters to cycling H2H markets only | Pinnacle has dozens of sports; returning all markets is noise |

### Differentiators (nice to have, lower priority)

| Behavior | Value | Complexity |
|----------|-------|-----------|
| Validates odds are sane (both sides > 1.01, sum < 2.10) | Catches API glitches before they corrupt a session | Low — one check |
| Returns market timestamp alongside odds | Enables staleness detection downstream | Low — extract from response |

### Anti-Features

| Anti-Feature | Why Avoid |
|--------------|-----------|
| Auto-discover the internal API endpoint at runtime | Fragile; adds Playwright/browser overhead. Endpoint discovered once via browser devtools, hardcoded. |
| Poll for odds changes on a timer | Out of scope per REQUIREMENTS.md; on-demand refresh is the design |
| Parse cycling result pages as fallback | Completely different domain; not a fallback, a different feature |

### Complexity Notes

**HIGH complexity.** The Pinnacle official public API was shut down in July 2025. The project uses the internal web frontend API instead, discovered via browser network inspection. This means:

1. The endpoint URL is unknown until Playwright/devtools inspection is performed — this discovery step is itself work and must be the first task in the phase.
2. The session cookie authentication mechanism must be reverse-engineered from browser requests. Standard HTTP Basic auth (used by the old public API) does not apply.
3. The response schema is undocumented and may change without notice.
4. Cycling H2H markets are "specials" in Pinnacle's taxonomy — they appear under a different endpoint or market type flag than match-winner markets.

**Risk flag:** The endpoint discovery work (inspecting Pinnacle's network traffic to find the correct internal API URL and authentication headers) is a prerequisite that cannot be parallelized with anything else in Phase 1. If Pinnacle obfuscates their frontend API heavily, this could take significantly longer than expected.

### Key Implementation Decisions

- Session cookie stored in `PINNACLE_SESSION_COOKIE` env var (never committed)
- Endpoint URL stored in `PINNACLE_API_URL` env var (allows update without code change if endpoint changes)
- Client returns a typed dataclass/NamedTuple, not raw dict, so downstream code is type-safe
- Error response includes the env var name: `"PINNACLE_SESSION_COOKIE is expired or missing. Update it and retry."`

### Edge Cases

| Case | Handling |
|------|----------|
| No cycling markets today (off-season, no races) | Return empty list with `{"markets": [], "message": "No cycling H2H markets found"}` — not an error |
| Partial market (one side missing odds) | Log and skip that pair; don't fail the whole fetch |
| Cookie works but returns wrong sport data | Odds log provides audit trail; user will notice on inspection |
| Rate limit / 429 response | Log warning, return error; do not retry automatically (manual retry via UI) |
| Pinnacle changes internal API endpoint | `PINNACLE_API_URL` env var allows operator to update without code change |

---

## Group 2: Name Resolver

**Requirements:** NAME-01, NAME-02, NAME-03, NAME-04, NAME-05

### What It Does

Maps Pinnacle display names (e.g., "T. Pogacar", "Van Aert W.") to PCS rider URLs (e.g., `rider/tadej-pogacar`) by querying `cache.db`, normalizing accents, and applying fuzzy matching as a fallback. Caches confirmed mappings to `data/name_mappings.json` for future reuse.

### Table Stakes

| Behavior | Why Non-Negotiable |
|----------|-------------------|
| Exact match against `cache.db` riders (fast path) | Most names resolve cleanly; this covers ~70% of cases |
| Unicode normalization before fuzzy matching | Pinnacle uses ASCII display names for accented riders (e.g., "Pogacar" not "Pogačar") |
| rapidfuzz token_sort_ratio for fuzzy matching | Handles "Firstname Lastname" vs "Lastname F." abbreviation patterns common on Pinnacle |
| Auto-accept matches above threshold (suggested: 90) | User should not have to confirm obvious matches |
| Persist confirmed mappings to `data/name_mappings.json` | Avoids re-running fuzzy logic on every load; name mappings are stable across weeks |
| Surface unresolved pairs in UI with manual search | Unresolved riders must not silently block prediction; user completes them manually |

### Differentiators

| Behavior | Value | Complexity |
|----------|-------|-----------|
| Pre-seed `name_mappings.json` with top-50 WT riders | Near-zero cold-start friction for the most common cases | Low — one-time data prep |
| Log ambiguous matches (score 75–89) separately for review | User can audit and correct borderline resolutions | Low — separate log entry |

### Anti-Features

| Anti-Feature | Why Avoid |
|--------------|-----------|
| ML-based name matching (hmni library) | Overkill; rapidfuzz handles abbreviation/accent variants reliably at far lower cost |
| External name lookup API | Adds dependency, latency, API key; not needed for a closed set of WT riders |
| Prompting user to confirm every fuzzy match | Friction for high-confidence matches defeats the purpose of automation |

### Complexity Notes

**MEDIUM complexity.** The algorithm is straightforward (exact → normalize → fuzzy → cache), but the edge cases require careful handling:

- Pinnacle abbreviates first names inconsistently ("T. Pogacar", "Tadej P.", "Pogacar Tadej") — token_sort_ratio handles reordering, but abbreviated first names need special treatment (match on last name + initial check)
- PCS URLs use slug format (`rider/tadej-pogacar`) which must be looked up in `cache.db`, not derived from the name
- `name_mappings.json` must be treated as append-only (never delete confirmed mappings; a rider's Pinnacle display name does not change within a season)
- The `riders` table in `cache.db` contains only riders who have appeared in WT race results 2018–2025; neo-pros or riders joining WT after the last scrape will not resolve

### Key Implementation Decision

Use `rapidfuzz.process.extractOne` with `scorer=rapidfuzz.fuzz.token_sort_ratio` and `score_cutoff=90` for auto-accept. Return the match with score for all results in the 75–89 range to the caller (not to the user directly — the Flask endpoint decides what to surface). This keeps the resolver logic clean and the Flask endpoint responsible for UI decisions.

### Edge Cases

| Case | Handling |
|------|----------|
| Rider not in cache.db (new WT pro, or lower-tier race) | Unresolved; shown in UI with manual search field |
| Two riders with same last name and initial (e.g., "A. Martin") | Both candidates returned; UI shows manual disambiguation |
| Fuzzy match score exactly at threshold | Treat as auto-accept (>= 90); bias toward accepting to reduce friction |
| `name_mappings.json` contains stale entry (rider retired, URL changed) | PCS URL lookup in cache.db validates the mapping; stale entries produce a warning, not a crash |
| Empty Pinnacle name string | Skip; log warning |

---

## Group 3: Stage Context Fetcher

**Requirements:** STGE-01, STGE-02

### What It Does

Given a Pinnacle race name string (e.g., "Tour de Romandie - Stage 3"), fetches stage details from PCS via the `procyclingstats` lib: distance, vertical meters, climb count/categories, profile_icon, race tier (UCI tour code), and stage type (flat/mountain/TT). These fields map directly to the `race_params` dict that `build_feature_vector_manual` already accepts.

### Table Stakes

| Behavior | Why Non-Negotiable |
|----------|-------------------|
| Maps Pinnacle race name to PCS race URL | Race names differ ("Tour de Romandie" vs "romandie") — mapping is required |
| Returns all fields consumed by `build_feature_vector_manual` | Missing fields cause silent feature gaps; must return complete `race_params` dict |
| Graceful degradation when fetch fails | Prediction must not be blocked; manual input remains available (STGE-02) |
| Strips stage number from Pinnacle name before race lookup | "Tour de Romandie - Stage 3" must resolve to the race, not fail on "Stage 3" |

### Differentiators

| Behavior | Value | Complexity |
|----------|-------|-----------|
| Cache stage context to memory for the session | PCS does not change intraday; avoids duplicate scrape on Refresh Odds | Low — dict keyed by race name |
| Return `pcs_stage_url` alongside `race_params` | Allows prediction to use DB stage path (more features) if available | Medium — requires cache.db lookup |

### Anti-Features

| Anti-Feature | Why Avoid |
|--------------|-----------|
| Using the MCP server for stage context | MCP is in-session only; pipeline on VPS uses `procyclingstats` lib directly |
| Fetching full startlist alongside stage context | Startlist data is not used by the prediction model in the current feature set |

### Complexity Notes

**MEDIUM complexity.** The `procyclingstats` library is an HTML scraper and is inherently fragile:

- HTML parsing can fail silently (missing fields return empty/None rather than raising)
- The library does not provide a "search by race name" function — the caller must construct the correct PCS URL from the Pinnacle race name. This requires a name-to-URL mapping (either a hardcoded dict for top races, a lookup in `cache.db`, or a PCS search call)
- Stage type (flat/mountain/TT) must be inferred from `profile_icon` string — the field is a filename fragment like `p1`, `p2`, `p5` where `p5` = mountain, `p1` = flat, `p7` = TT. This mapping must be documented and tested.
- `procyclingstats` enforces its own rate limit (0.5s between requests); the fetcher must respect this

**Key open question:** How to map Pinnacle race names to PCS race URL slugs. Three options:
1. Hardcode a dict for the ~20 most common WT races (fast, reliable for known races, fails on new/renamed races)
2. Search `cache.db` races table with fuzzy match (reuses existing data, no extra HTTP call)
3. Call PCS search endpoint (accurate but adds latency and a scrape dependency)

**Recommendation:** Option 2 (cache.db fuzzy lookup) first, falling back to Option 1 hardcoded dict for races not yet in cache.db. Option 3 is a differentiator for a later phase.

### Edge Cases

| Case | Handling |
|------|----------|
| Pinnacle race name has no match in cache.db | Return null stage context; UI shows manual fields unfilled |
| PCS stage page returns partial data (missing elevation) | Use whatever fields are available; leave missing fields as None for manual entry |
| Stage is a TTT or prologue (unusual profile types) | Profile icon mapping must include these; else falls back to "unknown" type |
| Race has multiple stages today (stage race with rest day catch-up — rare) | Return the stage matching today's date; if ambiguous, return all and let user select |

---

## Group 4: Flask Endpoints

**Requirements:** ODDS-01 through ODDS-04, plus integration of Name Resolver and Stage Context Fetcher

### What It Does

Two endpoints protected by `_require_localhost`:

- `POST /api/pinnacle/load` — fetches markets, resolves names, fetches stage context, returns structured payload for UI population
- `POST /api/pinnacle/refresh-odds` — re-fetches Pinnacle markets only (no PCS calls, no re-resolution), returns updated odds keyed by market_id

### Table Stakes

| Behavior | Why Non-Negotiable |
|----------|-------------------|
| Both endpoints protected by `_require_localhost` | Session cookie must not be exposed externally (per REQUIREMENTS.md security constraint) |
| `/load` response includes resolved and unresolved pairs separately | UI needs to know which pairs are actionable and which need manual completion |
| `/load` response includes `race_params` dict (or null) per market | UI populates stage fields directly from this |
| `/refresh-odds` accepts market_id list, returns odds deltas only | Re-fetching and re-resolving everything on odds refresh is wasteful and slow |
| Errors returned as structured JSON with actionable message | `{"error": "PINNACLE_SESSION_COOKIE expired", "env_var": "PINNACLE_SESSION_COOKIE"}` |

### Differentiators

| Behavior | Value | Complexity |
|----------|-------|-----------|
| `/load` includes a `loaded_at` timestamp in response | UI can show "loaded 4 minutes ago" to signal odds freshness | Trivial |
| `/load` accepts optional `race_filter` param | User can request a specific race without loading all markets | Low |

### Anti-Features

| Anti-Feature | Why Avoid |
|--------------|-----------|
| `/api/pinnacle/load` as a GET endpoint | Has side effects (external HTTP call, writes to odds log); POST is semantically correct |
| Combining load and refresh into one endpoint | Refresh-only is significantly cheaper; keeping them separate preserves the performance benefit |
| Blocking on PCS fetch if Pinnacle fetch failed | Endpoints must fail fast; no point fetching stage context if odds aren't available |

### Complexity Notes

**LOW complexity** once Groups 1–3 are built. These endpoints are mostly orchestration — call the client, call the resolver, call the stage fetcher, assemble the response shape the UI expects. The main design work is agreeing on the response schema before building the UI.

**Response schema for `/api/pinnacle/load` (proposed):**

```json
{
  "loaded_at": "2026-04-11T09:15:00Z",
  "races": [
    {
      "pinnacle_race_name": "Tour de Romandie - Stage 3",
      "race_params": { "distance": 180.4, "vertical_meters": 2800, ... },
      "markets": [
        {
          "market_id": "12345678",
          "rider_a": { "pinnacle_name": "T. Pogacar", "pcs_url": "rider/tadej-pogacar", "odds": 1.45 },
          "rider_b": { "pinnacle_name": "R. Vingegaard", "pcs_url": "rider/jonas-vingegaard", "odds": 2.85 },
          "resolved": true
        },
        {
          "market_id": "12345679",
          "rider_a": { "pinnacle_name": "A. Martin", "pcs_url": null, "odds": 1.90 },
          "rider_b": { "pinnacle_name": "B. Rider", "pcs_url": "rider/ben-healy", "odds": 1.95 },
          "resolved": false,
          "unresolved_names": ["A. Martin"]
        }
      ]
    }
  ]
}
```

### Edge Cases

| Case | Handling |
|------|----------|
| Pinnacle fetch succeeds but zero cycling markets | Return `{"races": [], "message": "No cycling H2H markets today"}` with HTTP 200 |
| PCS fetch times out | Return markets with `race_params: null`; do not fail the whole load |
| Concurrent load requests (user double-clicks) | Flask is single-threaded in dev mode; not an issue. If deployed with gunicorn, requests queue naturally |
| `/refresh-odds` called before `/load` was called | Return 400: "No session loaded. Call /api/pinnacle/load first." |

---

## Group 5: Batch UI Updates

**Requirements:** UI-01, UI-02, UI-03, UI-04

### What It Does

Adds "Load from Pinnacle" and "Refresh Odds" buttons to the existing batch H2H prediction UI. On load: race selector dropdown populates, selecting a race auto-fills stage fields and pair rows. On refresh: odds fields update in-place without clearing rider selections or stage fields. Unresolved riders show a manual search field instead of a resolved name.

### Table Stakes

| Behavior | Why Non-Negotiable |
|----------|-------------------|
| "Load from Pinnacle" button visible and labeled clearly in batch mode | Entry point for the feature; must be discoverable without explanation |
| Race dropdown populated from load response; selecting race fills all fields | Core workflow; if this is broken the feature does not exist |
| All auto-filled fields remain individually editable before running predictions | Non-negotiable per UI-03; user must be able to correct AI/resolver errors |
| "Refresh Odds" updates only odds cells; does not clear rider names or stage fields | Destructive refresh would reset manual corrections; this is a regression risk |
| Unresolved riders show inline manual search (same autocomplete as existing UI) | Unresolved pairs must be completable; can't just hide them |
| Clear loading states (spinner/disabled button) during async calls | Without this, double-clicks cause duplicate loads |
| Cookie error message displayed inline, not as a browser alert | Alerts are disruptive; an inline error banner in the batch section is sufficient |

### Differentiators

| Behavior | Value | Complexity |
|----------|-------|-----------|
| "Loaded X minutes ago" timestamp near Refresh Odds button | Helps user know if odds are fresh without checking | Trivial |
| Visual indicator on odds cells that were updated by refresh | Makes it clear which values changed (e.g., brief yellow flash) | Low |
| Count of resolved/unresolved pairs shown after load | Surfaces immediately how much manual cleanup is needed | Low |

### Anti-Features

| Anti-Feature | Why Avoid |
|--------------|-----------|
| Auto-loading Pinnacle markets on page load / tab switch | Cookie may be expired; silent background failure is worse than explicit button click |
| Locking all fields once loaded from Pinnacle | Defeats UI-03; user must always be able to edit |
| Replacing the entire batch pairs section on refresh | Destroys manual edits; only odds cells should update |
| Showing resolved PCS URLs directly to user | Technical detail; show rider names, not `rider/tadej-pogacar` URLs |

### Complexity Notes

**MEDIUM complexity** — the JavaScript state management is the hard part. The UI must track which cells were auto-populated vs manually edited, so "Refresh Odds" only updates auto-populated odds fields (not values the user has manually changed). This requires a per-cell `data-source` attribute or similar mechanism.

The existing batch UI already supports dynamic pair rows (add/remove), autocomplete rider search, and stage field population from the saved races selector. The Pinnacle preload extends this pattern rather than replacing it — the JS additions should feel like natural extensions of the existing code.

**Risk:** The existing `index.html` is a single ~1200-line file mixing HTML, CSS, and JS. Adding the Pinnacle load feature without refactoring risks making it unmaintainable. The phase should identify natural extraction points (e.g., the batch mode JS as a module) without requiring a full rewrite.

### Edge Cases

| Case | Handling |
|------|----------|
| User edits an odds field, then clicks Refresh Odds | Refresh should not overwrite user-edited odds. Use `data-user-edited="true"` attribute to skip those cells |
| User loads a race, manually fixes an unresolved rider, then refreshes | Rider selection must survive refresh; only odds cells update |
| Load returns zero races | Show message: "No cycling H2H markets found on Pinnacle today" |
| Load returns one race only | Auto-select that race (skip the dropdown step); still show race name for clarity |
| Stage fields already manually filled before load | Load should offer to overwrite with a warning, not silently replace |

---

## Feature Dependencies (Roadmap Build Order)

| Phase | Feature Group | Depends On | Can Parallelize With |
|-------|--------------|------------|---------------------|
| 1 | Pinnacle API Client (endpoint discovery + client) | Nothing | Nothing (must go first) |
| 2 | Name Resolver | Group 1 (real data for testing) | Stage Context Fetcher |
| 2 | Stage Context Fetcher | Group 1 (real race names for testing) | Name Resolver |
| 3 | Flask Endpoints | Groups 1, 2, 3 | Nothing |
| 4 | Batch UI Updates | Group 4 | Nothing |

Note: Groups 2 and 3 can be developed in parallel but both benefit from having real Pinnacle data from Group 1 to test against. Development can start with mocked data, but integration testing requires Group 1 to be working.

---

## MVP Recommendation

The minimum viable implementation that delivers the core value (one-click load of today's matchups with odds and stage context):

1. Pinnacle API client (ODDS-01, ODDS-03) — odds must load
2. Name resolver with exact + fuzzy, persistent cache (NAME-01 through NAME-05) — riders must resolve
3. Stage context fetcher via cache.db lookup + `procyclingstats` (STGE-01, STGE-02) — stage params must fill
4. `POST /api/pinnacle/load` endpoint (wires 1–3) — server side complete
5. "Load from Pinnacle" button + race selector + auto-populated pairs (UI-01, UI-02, UI-03)

Defer to second pass (low risk if missing from MVP):

- `POST /api/pinnacle/refresh-odds` (ODDS-04, UI-04) — useful but odds don't move much in cycling; manual reload via full "Load from Pinnacle" is a workable substitute
- ODDS-02 audit log — good hygiene but not blocking; add in the same phase once load is working

---

## Sources

- Pinnacle official API documentation: https://pinnacleapi.github.io/ (public API — shut down July 2025; internal web API requires browser inspection)
- rapidfuzz Python library: https://rapidfuzz.github.io/RapidFuzz/Usage/process.html
- procyclingstats library: https://procyclingstats.readthedocs.io/en/latest/api.html
- Fuzzy matching threshold guidance: https://dataladder.com/fuzzy-matching-101/
- JSONL audit log patterns: https://jsonltools.com/jsonl-for-developers
- Flask fetch/JSON patterns: https://flask.palletsprojects.com/en/stable/patterns/javascript/
- Pinnacle API shutdown notice (July 2025): https://arbusers.com/access-to-pinnacle-api-closed-since-july-23rd-2025-t10682/
