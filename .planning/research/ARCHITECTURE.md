# Architecture: Pinnacle Preload Integration (PaceIQ v1.0)

**Domain:** Adding live Pinnacle odds ingestion to an existing Flask/SQLite/ML prediction app
**Researched:** 2026-04-11
**Confidence:** HIGH — based on direct codebase audit

---

## Executive Summary

The Pinnacle Preload milestone adds a live data ingestion layer that sits in front of the existing batch prediction path. The new components form a preprocessing pipeline: Pinnacle API → name resolver → stage context fetch → assembled payload → existing `/api/predict/batch` logic. No existing ML inference code changes. The integration point is the `race_params` dict already accepted by `predict_manual()` and the pairs array already accepted by `api_predict_batch()`.

The existing architecture has a strict one-way dependency: `webapp → models → features → data`. All new components live in `data/` and `intelligence/`, plus new routes appended to `webapp/app.py`. This layering is preserved.

---

## Existing Architecture Snapshot

```
webapp/app.py (Flask, port 5001)
 ├── POST /api/predict          → models/predict.py::Predictor.predict_manual()
 ├── POST /api/predict/batch    → models/predict.py::Predictor.predict_manual() (per pair)
 ├── GET  /api/riders           → data/cache.db::riders (autocomplete)
 ├── GET  /api/races            → data/cache.db::stages (stage search)
 └── POST /api/saved-races      → data/pnl.py (saved_races table in cache.db)

models/predict.py
 └── predict_manual(rider_a_url, rider_b_url, race_params: dict, odds_a, odds_b)
      └── features/pipeline.py::build_feature_vector_manual()
           ├── features/race_features.py   (distance, elevation, climbs, terrain, type)
           └── features/rider_features.py  (form, career stats, specialty — pre-race only)

data/
 ├── scraper.py     get_db() → data/cache.db (WAL SQLite)
 ├── builder.py     H2H pair generation
 └── pnl.py         Bet tracking, bankroll
```

### `race_params` dict contract (what `predict_manual` accepts)

`build_feature_vector_manual()` at `features/pipeline.py:225` reads these keys:

| Key | Type | Source after Preload |
|-----|------|----------------------|
| `distance` | float (km) | PCS stage fetch |
| `vertical_meters` | float | PCS stage fetch |
| `profile_icon` | str (p1–p5) | PCS stage fetch |
| `profile_score` | float | Estimated from icon if absent |
| `is_one_day_race` | bool | PCS race metadata |
| `stage_type` | str (RR/ITT/TTT) | PCS stage fetch |
| `race_date` | str ISO date | PCS stage fetch |
| `race_base_url` | str | PCS race URL |
| `num_climbs` | int | PCS stage fetch |
| `climbs_json` | str (JSON) | PCS stage fetch |
| `uci_tour` | str (e.g. "1.UWT") | PCS race fetch |
| `avg_temperature` | float | Optional, defaults to 0 |
| `startlist_quality_score` | float | Optional, from PCS startlist |

### Batch endpoint contract (what `api_predict_batch` accepts)

`webapp/app.py:226` — accepts:
```json
{
  "race_params": { ...race_params dict... },
  "pairs": [
    { "rider_a_url": "rider/tadej-pogacar", "rider_b_url": "rider/jonas-vingegaard", "odds_a": 1.85, "odds_b": 2.05 },
    ...
  ]
}
```

This is exactly the shape the Pinnacle load endpoint must produce.

---

## New Component Map

### Files to Create

| File | Status | Responsibility |
|------|--------|----------------|
| `data/odds.py` | NEW | Pinnacle API client — session-cookie auth, fetch H2H cycling markets, return structured `OddsMarket` list |
| `data/name_resolver.py` | NEW | Fuzzy name-to-PCS-URL resolution — exact → normalize → rapidfuzz → persistent JSON cache |
| `intelligence/__init__.py` | NEW | Package marker |
| `intelligence/models.py` | NEW | Dataclasses: `OddsMarket`, `ResolvedMarket`, `StageContext` |
| `intelligence/stage_context.py` | NEW | Fetch stage details from PCS via `procyclingstats` lib given a race name |
| `data/name_mappings.json` | NEW (runtime) | Persistent name→URL cache, created on first use, gitignored |
| `data/odds_log.jsonl` | NEW (runtime) | Append-only audit log for every raw Pinnacle fetch |

### Files to Modify

| File | Change |
|------|--------|
| `webapp/app.py` | Add `POST /api/pinnacle/load` and `POST /api/pinnacle/refresh-odds` routes; import new modules; wrap both with `_require_localhost` |
| `webapp/templates/index.html` | Add "Load from Pinnacle" button, race selector dropdown, "Refresh Odds" button to batch prediction section |

### Files Unchanged

All ML inference code (`models/predict.py`, `features/pipeline.py`, `features/rider_features.py`, `features/race_features.py`) is untouched. The Pinnacle Preload layer is pure data plumbing that feeds the existing batch endpoint shape.

---

## Data Flow: Pinnacle → Batch Form Pre-fill

```
User clicks "Load from Pinnacle"
        │
        ▼
POST /api/pinnacle/load
        │
        ├─► data/odds.py::fetch_cycling_h2h_markets()
        │       HTTP GET Pinnacle internal API (session cookie from env PINNACLE_SESSION_COOKIE)
        │       Returns: list of OddsMarket (race_name, matchups: [{rider_a, rider_b, odds_a, odds_b}])
        │       Appends raw JSON to data/odds_log.jsonl
        │       On expired cookie → returns structured error {error: "session_expired", env_var: "PINNACLE_SESSION_COOKIE"}
        │
        ├─► [For each unique race in response]:
        │       intelligence/stage_context.py::fetch_stage_context(race_name)
        │           Uses procyclingstats lib (already in requirements.txt)
        │           Returns: StageContext (distance, vert, profile, date, uci_tour, climbs, etc.)
        │           On failure → StageContext with is_resolved=False; manual fields remain editable
        │
        ├─► [For each rider name in all matchups]:
        │       data/name_resolver.py::resolve(pinnacle_name) → PCS URL or None
        │           1. Check data/name_mappings.json cache
        │           2. Exact match against cache.db::riders WHERE LOWER(name) = LOWER(pinnacle_name)
        │           3. Unicode normalize both sides (strip accents/diacritics) → exact match
        │           4. rapidfuzz.fuzz.token_sort_ratio against all riders.name → if score ≥ 85 → accept
        │           5. Return None if unresolved; caller marks pair as "needs_manual_resolution"
        │           Accepted mappings → persist to data/name_mappings.json
        │
        └─► Assemble response:
                {
                  "races": [
                    {
                      "pinnacle_race_name": "Tour de France - Stage 12",
                      "stage_context": { ...StageContext fields... },
                      "stage_resolved": true/false,
                      "pairs": [
                        {
                          "rider_a_name": "Tadej Pogacar",
                          "rider_a_url": "rider/tadej-pogacar",   // null if unresolved
                          "rider_b_name": "Jonas Vingegaard",
                          "rider_b_url": "rider/jonas-vingegaard",
                          "odds_a": 1.85,
                          "odds_b": 2.05,
                          "rider_a_resolved": true,
                          "rider_b_resolved": false   // triggers manual search UI
                        }
                      ]
                    }
                  ]
                }

        ▼
User selects a race from the dropdown
        │
        ▼
index.html JS populates batch prediction form:
  - Stage fields ← stage_context (distance, elevation, profile, etc.)
  - Each pair row ← rider_a_url, rider_b_url, odds_a, odds_b
  - Unresolved rider cells ← show rider-search autocomplete (same as existing /api/riders endpoint)
  - All fields remain individually editable

        ▼
User clicks "Run Batch Predictions"
        │
        ▼
POST /api/predict/batch  ← EXISTING ENDPOINT, NO CHANGES
  { "race_params": {...}, "pairs": [...] }
        │
        ▼
models/predict.py::Predictor.predict_manual()  ← EXISTING, NO CHANGES
```

### "Refresh Odds" flow (ODDS-04)

```
User clicks "Refresh Odds" in an already-loaded session
        │
        ▼
POST /api/pinnacle/refresh-odds
        │
        ├─► data/odds.py::fetch_cycling_h2h_markets()  (same call, no stage re-fetch)
        │       Returns current odds for the same race
        │
        └─► Response: { "pairs": [{odds_a, odds_b per pair}] }
                JS updates only odds fields — stage context, rider selections, manual overrides preserved
```

---

## Component Integration Points (File + Location Level)

### `webapp/app.py` — where new routes attach

- After line 315 (end of `api_predict_batch`) and before line 318 (`api_stats`), insert new route block
- Import at top of file (after existing imports, line 25–26 area):
  ```python
  from data.odds import fetch_cycling_h2h_markets
  from data.name_resolver import NameResolver
  from intelligence.stage_context import fetch_stage_context
  ```
- Both new routes decorated with `@_require_localhost` (decorator already defined at lines 34–41)

### `data/odds.py` — Pinnacle client

- Reads `os.environ.get("PINNACLE_SESSION_COOKIE")` — env var must be set locally, never committed
- Makes HTTP GET to Pinnacle internal API endpoint (endpoint URL to be discovered via Playwright inspection — this is Phase 1 work)
- Returns `list[OddsMarket]` from `intelligence/models.py`
- On HTTP 401/403 or invalid response structure → raises typed exception `PinnacleSessionExpired` with env var name in message
- Appends raw response to `data/odds_log.jsonl` (append mode, one JSON object per line) — satisfies ODDS-02
- No SQLite interaction — pure HTTP client

### `data/name_resolver.py` — name mapping

- Imports `get_db` from `data.scraper` to query `riders` table
- Reads/writes `data/name_mappings.json` — a flat `{"Pinnacle Name": "rider/pcs-url"}` dict
- Uses `rapidfuzz` (pre-approved dependency per PROJECT.md)
- Cache load happens once at class instantiation; writes back on `save()` call
- Confidence threshold 85 (token_sort_ratio) is a build-time constant, not a config value

### `intelligence/stage_context.py` — PCS stage fetch

- Uses `procyclingstats` lib (already in `requirements.txt` — used by `data/scraper.py`)
- Does NOT use MCP server (per key decision in PROJECT.md: "Self-contained, works on VPS without MCP server dependency")
- Takes a Pinnacle race name string, attempts to map to a PCS race URL (fuzzy match against `cache.db::races.name`, or a separate name-to-URL lookup)
- Calls `procyclingstats.Stage` or `procyclingstats.Race` objects
- Returns `StageContext` dataclass or raises `StageContextUnavailable`
- Does not write to `cache.db` — read-only against PCS; the historical scraper owns cache.db writes

### `intelligence/models.py` — shared dataclasses

```python
@dataclass
class OddsMarket:
    race_name: str          # Pinnacle's race name string
    matchups: list[Matchup] # each: rider_a, rider_b, odds_a, odds_b

@dataclass
class StageContext:
    distance: float
    vertical_meters: float
    profile_icon: str       # p1–p5
    stage_type: str         # RR/ITT/TTT
    race_date: str          # ISO
    race_base_url: str      # PCS URL
    uci_tour: str           # e.g. "1.UWT"
    num_climbs: int
    climbs_json: str        # JSON string
    is_resolved: bool

@dataclass
class ResolvedMarket:
    pinnacle_race_name: str
    stage_context: StageContext
    stage_resolved: bool
    pairs: list[ResolvedPair]

@dataclass
class ResolvedPair:
    rider_a_name: str
    rider_a_url: Optional[str]
    rider_b_name: str
    rider_b_url: Optional[str]
    odds_a: float
    odds_b: float
    rider_a_resolved: bool
    rider_b_resolved: bool
```

These map directly to the JSON shape the front end consumes. No transformation needed in `app.py`.

---

## Dependency Graph (Build Order Logic)

```
intelligence/models.py          (no deps — dataclasses only)
        │
        ├── data/odds.py        (depends on: intelligence/models.py, requests, env var)
        │
        ├── data/name_resolver.py (depends on: intelligence/models.py, data/scraper.py, rapidfuzz)
        │
        └── intelligence/stage_context.py (depends on: intelligence/models.py, procyclingstats)
                │
                └── webapp/app.py additions (depends on: all three above)
                        │
                        └── webapp/templates/index.html changes (depends on: new endpoints existing)
```

Each layer can be built and tested in isolation before wiring the next.

---

## Recommended Build Order

### Phase 1 — Pinnacle API Discovery and Client (ODDS-01, ODDS-02, ODDS-03)

**Build independently.** No other new components needed.

1. Use Playwright to inspect Pinnacle's web frontend and identify the internal H2H cycling markets API endpoint, request headers, and response schema
2. Build `data/odds.py` — session-cookie client, structured error on expiry, append to `odds_log.jsonl`
3. Build `intelligence/models.py` — `OddsMarket`, `Matchup` dataclasses
4. Manual test: call `fetch_cycling_h2h_markets()` directly in a REPL with real session cookie

**Why first:** The Pinnacle endpoint shape is unknown until inspected. Everything downstream depends on knowing what fields come back. This is the highest-risk unknown.

### Phase 2 — Name Resolver (NAME-01 through NAME-05)

**Build independently** (uses only `data/scraper.py` and `rapidfuzz`, both already present).

1. Build `data/name_resolver.py` with exact → normalize → fuzzy → cache pipeline
2. Build `data/name_mappings.json` creation/load/save logic
3. Unit test with known Pinnacle name variants (accent stripping, abbreviated names)
4. Test against live `cache.db` riders table

**Why second:** Can be developed in parallel with Phase 1 once the `OddsMarket` dataclass shape is known. Does not depend on Pinnacle endpoint being confirmed.

### Phase 3 — Stage Context Fetch (STGE-01, STGE-02)

**Build independently** (uses only `procyclingstats` lib, already in `requirements.txt`).

1. Investigate how `procyclingstats` exposes stage details for upcoming races (may require a PCS URL, not just a name — needs spike)
2. Build `intelligence/stage_context.py` with graceful degradation on failure
3. Build `StageContext` dataclass in `intelligence/models.py`
4. Test with a current race (manual PCS URL input first, then name-to-URL mapping)

**Why third:** Independent of Phases 1 and 2. Can be done in any order after the `intelligence/models.py` skeleton exists. The name-to-PCS-URL mapping for races may reuse patterns from Phase 2's name resolver.

### Phase 4 — Flask Endpoint Wiring (ODDS-04, partial UI-01 through UI-04)

**Integrates Phases 1–3.** Requires all three prior components to exist.

1. Add `POST /api/pinnacle/load` to `webapp/app.py` — calls odds client, name resolver, stage context, assembles `ResolvedMarket` response
2. Add `POST /api/pinnacle/refresh-odds` — calls odds client only, returns updated odds without clearing context
3. Both routes wrapped with `_require_localhost` (existing decorator at `app.py:34`)
4. Test with `curl` or `httpie` before touching the frontend

**Insertion point in `webapp/app.py`:** Add new route block between lines 315 and 317 (after `api_predict_batch`, before `api_stats`).

### Phase 5 — Frontend Integration (UI-01 through UI-04)

**Final layer.** Requires Phase 4 endpoints to exist and return correct shape.

1. Add "Load from Pinnacle" button to batch H2H section of `webapp/templates/index.html`
2. Race selector dropdown — populated from `response.races[].pinnacle_race_name`
3. On race selection: populate stage fields, populate pair rows (rider names + search, odds)
4. Unresolved rider cells show existing `/api/riders` autocomplete (already wired in the UI)
5. "Refresh Odds" button — calls `/api/pinnacle/refresh-odds`, updates odds fields only
6. Manual override: all auto-populated fields must remain individually editable (standard HTML form behavior)

---

## Integration Points: Existing Code That Is Touched

| Existing File | Lines Affected | Change |
|---------------|----------------|--------|
| `webapp/app.py` | Lines 18–25 (imports) | Add 3 new imports |
| `webapp/app.py` | After line 315 | Insert ~60 lines: 2 new route functions |
| `webapp/app.py` | No other changes | `api_predict_batch` and `predict_manual` are untouched |
| `webapp/templates/index.html` | Batch prediction section | Add button group, race selector, JS fetch logic |
| `requirements.txt` | +1 line | Add `rapidfuzz>=3.0.0` (pre-approved per PROJECT.md) |

**No changes to:**
- `models/predict.py` (prediction logic unchanged)
- `features/pipeline.py` (feature engineering unchanged)
- `data/scraper.py` (scraper unchanged)
- `data/pnl.py` (bet tracking unchanged)
- `data/cache.db` schema (no new tables needed)

---

## Data Stores: New vs Existing

| Store | Type | Owner | Notes |
|-------|------|-------|-------|
| `data/cache.db` | SQLite (existing) | `data/scraper.py` | Name resolver reads `riders` table; no writes from new code |
| `data/name_mappings.json` | JSON file (new) | `data/name_resolver.py` | Flat dict; created on first use; gitignored |
| `data/odds_log.jsonl` | JSONL append log (new) | `data/odds.py` | One JSON line per fetch; audit trail; gitignored |

No new SQLite tables. No schema changes to `cache.db`.

---

## Security Considerations

- `PINNACLE_SESSION_COOKIE` env var — never committed, never logged, never included in API responses
- Both new endpoints (`/api/pinnacle/load`, `/api/pinnacle/refresh-odds`) must be wrapped with `_require_localhost` — same pattern as all existing `/admin` and `/api/admin/*` routes
- `data/odds_log.jsonl` should be added to `.gitignore` — contains raw API responses that may include session-adjacent data
- `data/name_mappings.json` should also be gitignored — it's a local runtime cache

---

## Pitfalls Specific to This Integration

### Pinnacle endpoint shape is unknown
The internal Pinnacle API endpoint must be discovered via browser inspection before any client code can be written. This is the only true blocker. All other components can be stubbed/tested independently.

### `procyclingstats` lib requires a PCS URL, not a free-text name
The `procyclingstats` lib parses specific PCS page URLs (e.g., `race/tour-de-france/2026/stage-12`). A Pinnacle race name like "Tour de France - Stage 12" does not map trivially to that URL. `intelligence/stage_context.py` will need a name-to-URL fuzzy match step, likely against `cache.db::stages` first (most current races will already be in the DB from the nightly scrape), with PCS search as fallback.

### Name resolver confidence threshold needs empirical calibration
The 85 threshold for rapidfuzz `token_sort_ratio` is a starting point. Pinnacle uses abbreviated names (e.g., "T. Pogacar") or alternate spellings that may score lower than expected. Build the resolver with a flag on low-confidence matches and review a sample of real Pinnacle names against the DB before hardening the threshold.

### `odds_log.jsonl` grows unboundedly
The audit log has no rotation policy. For a personal tool used daily, this is low priority, but worth noting. Add a size check or daily rotation if the file grows unexpectedly.

### Thread safety on ML inference path is unchanged
The new endpoints do not call the `Predictor`. ML inference is still triggered by `POST /api/predict/batch` separately. The `OMP_NUM_THREADS=1` / `MKL_NUM_THREADS=1` convention does not need to change.

---

## Confidence Assessment

| Area | Confidence | Basis |
|------|------------|-------|
| Integration points in `webapp/app.py` | HIGH | Direct code read — routes, imports, `_require_localhost` all confirmed |
| `race_params` dict keys | HIGH | Direct read of `build_feature_vector_manual` signature at `features/pipeline.py:225` |
| `procyclingstats` lib availability | HIGH | Already in `requirements.txt`, used by `data/scraper.py` |
| `rapidfuzz` pre-approved | HIGH | Confirmed in PROJECT.md Key Decisions |
| Pinnacle API endpoint shape | LOW | Unknown — requires Playwright discovery in Phase 1 |
| `procyclingstats` API for upcoming races | MEDIUM | Lib is used for historical stages; upcoming stage URL format needs verification |
| Name resolver fuzzy threshold | MEDIUM | 85 is a reasonable default; needs empirical calibration against real Pinnacle names |

---

*Architecture analysis: 2026-04-11*
