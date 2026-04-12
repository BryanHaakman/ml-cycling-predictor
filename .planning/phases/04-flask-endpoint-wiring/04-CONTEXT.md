# Phase 4: Flask Endpoint Wiring — Context

**Gathered:** 2026-04-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement two new Flask endpoints — `POST /api/pinnacle/load` and `POST /api/pinnacle/refresh-odds` — in a new Blueprint (`webapp/pinnacle_bp.py`). These endpoints wire together `data/odds.py`, `data/name_resolver.py`, and `intelligence/stage_context.py` into a locked JSON response schema. The schema must be frozen in `docs/pinnacle-api-notes.md` before Phase 5 begins.

**This phase does NOT:**
- Run model predictions (that remains the user's manual trigger via existing `/api/predict/batch`)
- Fetch or validate the PCS race startlist (deferred to a future phase)
- Build any frontend UI (that is Phase 5)

**The user's trust-first flow:**
1. "Load from Pinnacle" button (Phase 5) → calls `/api/pinnacle/load`
2. Response pre-populates the existing batch H2H form
3. User reviews and edits the pre-populated form
4. User clicks existing "Run Batch Predictions" button → calls existing `/api/predict/batch`

</domain>

<decisions>
## Implementation Decisions

### Endpoint: POST /api/pinnacle/load

**D-01: Data only — no predictions inline.**
`/api/pinnacle/load` returns resolved market data (rider URLs, odds, stage context, resolved flags). It does NOT run model predictions. This is intentional: Bryan wants to review the resolved data before triggering predictions. Predictions stay a separate manual step via the existing `/api/predict/batch` endpoint.

Rationale: Incremental trust. The load + resolve pipeline is new and unverified. The user needs to see the resolved rider names, stage context, and odds before trusting the prediction output. Automating end-to-end before the data layer is trusted would hide errors.

**D-02: Pre-populate existing batch H2H form. No second screen.**
The `/load` response is designed to map directly onto the existing batch H2H form fields. Phase 5 JS takes the response and fills in rider URLs, stage fields, and odds without navigating to a new page.

### Response Schema (frozen before Phase 5)

The full schema must be written to `docs/pinnacle-api-notes.md` before Phase 5 begins. The locked structure:

```json
{
  "races": [
    {
      "race_name": "Tour de Romandie",
      "stage_resolved": true,
      "stage_context": {
        "distance": 156.0,
        "vertical_meters": 887,
        "profile_icon": "p1",
        "profile_score": 9,
        "is_one_day_race": false,
        "stage_type": "RR",
        "race_date": "2026-04-28",
        "race_base_url": "race/tour-de-romandie/2026",
        "num_climbs": 0,
        "avg_temperature": null,
        "uci_tour": "2.UWT",
        "is_resolved": true
      },
      "pairs": [
        {
          "pinnacle_name_a": "ROGLIC Primoz",
          "pinnacle_name_b": "VINGEGAARD Jonas",
          "rider_a_url": "rider/primoz-roglic",
          "rider_b_url": "rider/jonas-vingegaard",
          "rider_a_resolved": true,
          "rider_b_resolved": true,
          "best_candidate_a_name": null,
          "best_candidate_a_url": null,
          "best_candidate_b_name": null,
          "best_candidate_b_url": null,
          "odds_a": 1.85,
          "odds_b": 2.10,
          "matchup_id": "12345"
        }
      ]
    }
  ]
}
```

**D-03: Unresolved pairs include best candidate hint.**
When `NameResolver.resolve()` returns `url=None` with a hint (score 60–89), the response includes `best_candidate_a_name` and `best_candidate_a_url` (populated from `ResolveResult`). Phase 5 can pre-fill the autocomplete with the hint. When score < 60 or fully unresolved: `best_candidate_*` fields are `null`. The raw Pinnacle name is always included as `pinnacle_name_a`/`pinnacle_name_b` regardless of resolution status.

**D-04: Race grouping by `OddsMarket.race_name`.**
Pinnacle matchups are grouped into races by `OddsMarket.race_name` (exact string equality — Pinnacle uses consistent names within a market fetch). Each group becomes one entry in `races[]`. `fetch_stage_context()` is called once per race using the `race_name` string.

### Endpoint: POST /api/pinnacle/refresh-odds

**D-05: Stateless — client sends matchup_ids.**
`/refresh-odds` is fully stateless. The client (Phase 5 JS) sends back the `matchup_id` list it received from `/load`. The server re-fetches Pinnacle odds, matches by `matchup_id`, and returns only the updated `odds_a`/`odds_b` fields. No server-side state required — survives Flask restarts.

Request body:
```json
{"matchup_ids": ["12345", "67890"]}
```

Response:
```json
{
  "pairs": [
    {"matchup_id": "12345", "odds_a": 1.90, "odds_b": 2.05},
    {"matchup_id": "67890", "odds_a": 2.15, "odds_b": 1.75}
  ]
}
```

Stage context and name resolution are NOT re-run on refresh. Only odds change.

### Error Responses

**D-06: Structured JSON errors with `env_var` field.**
Both endpoints return a structured JSON error when auth fails (per ROADMAP SC-3). The error includes the `env_var` field so Phase 5 can surface a clear, actionable message:

```json
{
  "error": "Pinnacle session expired or missing",
  "env_var": "PINNACLE_SESSION_COOKIE",
  "type": "auth_error"
}
```

HTTP 401 for auth errors. HTTP 500 is never returned — all exceptions caught and mapped to structured JSON.

### Code Structure

**D-07: New Blueprint — `webapp/pinnacle_bp.py`.**
Both endpoints live in `webapp/pinnacle_bp.py` as a Flask Blueprint. Registered in `webapp/app.py` with a prefix (e.g., `app.register_blueprint(pinnacle_bp)`). The `_require_localhost` decorator from `webapp/app.py` is applied to both routes (session cookie must not be exposed externally).

### Feature Quality: diff_field_rank_quality

**D-08: Neutral defaults in Phase 4 — documented known gap.**
`build_feature_vector_manual` currently hardcodes `diff_field_rank_quality = 0.0` (neutral). Phase 4 does not fix this.

**Proper fix (deferred):** Fetch the full PCS race startlist via the `get_race_startlist` MCP tool or `procyclingstats` lib, validate that Pinnacle matchup riders appear in that list (overlap check — ensures the feature is computed from a meaningful field), then compute real percentile ranks. This is a future phase concern.

Log in `decision_log.md`: Phase 4 uses neutral `diff_field_rank_quality` defaults. Startlist fetch + Pinnacle rider overlap validation is explicitly deferred. The feature has 0.014 importance — predictions are valid without it but slightly degraded relative to training.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Requirements
- `.planning/REQUIREMENTS.md` §ODDS-04 — acceptance criteria for Phase 4 endpoints

### Prior Phase Outputs (must exist at execution time)
- `data/odds.py` — `OddsMarket` dataclass, `fetch_cycling_h2h_markets()`, `PinnacleAuthError` (Phase 1)
- `data/name_resolver.py` — `NameResolver` class, `ResolveResult` dataclass (Phase 2)
- `intelligence/stage_context.py` — `StageContext` dataclass, `fetch_stage_context()` (Phase 3)
- `docs/pinnacle-api-notes.md` — frozen Pinnacle API contract, endpoint URL, headers, auth behavior

### Codebase Patterns
- `webapp/app.py` — existing Flask app; `_require_localhost` decorator (apply to both new routes); `/api/predict/batch` (pattern for batch JSON endpoint); error handler pattern (`@app.errorhandler`)
- `features/pipeline.py` `build_feature_vector_manual()` (line 225) — called by Phase 5 for predictions; Phase 4 does NOT call this
- `data/scraper.py` — `get_db()` pattern (connection management)

### Schema Freeze Target
- `docs/pinnacle-api-notes.md` — append the frozen `/load` and `/refresh-odds` response schemas here before Phase 5 begins

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_require_localhost` decorator in `webapp/app.py` — apply to both new Blueprint routes
- `webapp/app.py` error handling pattern: structured JSON for `/api/` paths, HTML for page routes
- `NameResolver` is stateful (loads all riders at `__init__`). Phase 4 should instantiate once per request or cache at app level — Claude's discretion, but avoid per-request DB queries across all pairs.

### Integration Points
- Blueprint registered in `webapp/app.py`: `from webapp.pinnacle_bp import pinnacle_bp; app.register_blueprint(pinnacle_bp)`
- `/api/pinnacle/load` calls: `fetch_cycling_h2h_markets()` → `NameResolver.resolve()` per rider → `fetch_stage_context()` per race
- `/api/pinnacle/refresh-odds` calls: `fetch_cycling_h2h_markets()` only → match by `matchup_id` → return updated odds
- Both routes protected by `_require_localhost`

### Claude's Discretion
- Whether to instantiate `NameResolver` once at Blueprint level or per-request (per-request is simpler; app-level caching is faster for batch loads)
- Exact HTTP status codes for non-auth errors (400 for bad request, 503 for Pinnacle unavailable, etc.)
- Internal timeout handling if `fetch_stage_context()` or `fetch_cycling_h2h_markets()` blocks too long

</code_context>

<specifics>
## Specific Implementation Notes

- The `/load` response is the contract that Phase 5 will code against. It MUST be appended to `docs/pinnacle-api-notes.md` as a frozen schema before Phase 5 execution begins.
- End-to-end verification (ROADMAP SC-1) means running a real `curl` or `httpie` call against a live Pinnacle session and confirming the full response shape — not just unit tests with mocks.
- `stage_resolved: false` (when `StageContext.is_resolved = False`) means stage fields will be empty/default. Phase 5 must handle this gracefully by showing manual input fields.
- The `matchup_id` from `OddsMarket` is the key for stateless refresh-odds matching — confirm it's stable across multiple Pinnacle API calls for the same market before Phase 4 execution.

</specifics>

<deferred>
## Deferred Ideas

**PCS Startlist Fetch + Pinnacle Rider Overlap Validation** — Fetch the full race startlist from PCS (via `get_race_startlist` MCP tool or `procyclingstats` lib) and cross-check that Pinnacle matchup riders appear in that list. This enables real `diff_field_rank_quality` computation and acts as a data quality gate. Explicitly deferred from Phase 4 — implement as a dedicated future phase or sub-phase before the prediction pipeline is considered fully trusted.

</deferred>

---

*Phase: 04-flask-endpoint-wiring*
*Context gathered: 2026-04-12*
