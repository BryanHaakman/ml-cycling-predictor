# Phase 2: Name Resolver - Context

**Gathered:** 2026-04-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement `data/name_resolver.py` — a `NameResolver` class that maps Pinnacle display names (SURNAME-FIRST, ALL-CAPS format, e.g. "ROGLIC PRIMOZ") to PCS rider URLs through a four-stage pipeline: exact match → unicode normalization → fuzzy match (rapidfuzz) → persistent cache. Accepted mappings are stored in `data/name_mappings.json` and re-used on future resolver instantiations. Unresolved pairs are surfaced with enough information for Phase 5 to render a hint or a blank search field.

This phase delivers the resolver module only — UI rendering of unresolved pairs is Phase 5.

</domain>

<decisions>
## Implementation Decisions

### Fuzzy Search Scope
- **D-01:** Search all riders in `cache.db` (`riders` table) — no filtering by recency or race tier. Full ~20K+ corpus maximizes coverage and avoids missing riders returning from injury or retirement.
- **D-02:** All rider names + URLs are pre-loaded into memory at `NameResolver.__init__()`. One DB query at construction time; all subsequent `resolve()` calls use the in-memory list. Fast for batch resolution of dozens of Pinnacle names per load (Phase 4 use case).

### Resolve Result Contract
- **D-03:** `NameResolver.resolve()` returns a `ResolveResult` dataclass (not just `Optional[str]`), with fields:
  - `url: Optional[str]` — PCS rider URL if resolved, else `None`
  - `best_candidate_url: Optional[str]` — best fuzzy match URL if score is 60–89, else `None`
  - `best_candidate_name: Optional[str]` — display name of best candidate
  - `best_score: Optional[int]` — fuzzy score (0–100), `None` if no candidate
  - `method: str` — one of `"exact"`, `"normalized"`, `"fuzzy"`, `"cache"`, `"unresolved"`
- **D-04:** Score thresholds:
  - ≥ 90: auto-accept → `url` is populated, `method="fuzzy"`, mapping saved to cache
  - 60–89: hint shown → `url=None`, `best_candidate_*` populated, `method="unresolved"`
  - < 60: no hint → `url=None`, all `best_candidate_*` fields are `None`, `method="unresolved"`
- **D-05:** `url=None` means unresolved — Phase 4 and Phase 5 must check `result.url is None` to identify pairs needing manual completion.

### Persistent Cache
- **D-06:** `data/name_mappings.json` schema: `{"ROGLIC PRIMOZ": "rider/primoz-roglic", ...}` — flat dict, Pinnacle name as key, PCS URL as value. Simple and sufficient.
- **D-07:** On load, schema is validated: each value must match the pattern `rider/[a-z0-9-]+`. Invalid entries are logged and skipped (not a crash).
- **D-08:** `NameResolver.accept(pinnacle_name: str, pcs_url: str)` is the public method for recording a manual resolution. It:
  1. Updates the in-memory cache dict immediately (so `resolve()` finds it in the same session)
  2. Writes the full updated dict to `data/name_mappings.json` atomically
  - Called by Phase 4 endpoint when the user confirms a manual match in the UI

### Claude's Discretion
- Pinnacle name pre-processing before matching (case normalization, accent stripping, word-order reversal to convert "ROGLIC PRIMOZ" → "Primoz Roglic") — Claude decides the exact normalization steps, guided by the must-pass examples in success criteria (Roglič, van Aert, Bardet, Quintana).
- Atomic write strategy for `name_mappings.json` (write to temp file, rename) — Claude decides based on the existing project's file I/O patterns.
- rapidfuzz scorer choice (`fuzz.WRatio` vs `fuzz.token_sort_ratio`) — Claude decides based on the name format characteristics.
- Request timeout / retry: not applicable (no network calls in this module).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Requirements
- `.planning/REQUIREMENTS.md` §Name Resolution — NAME-01 through NAME-05 are the acceptance criteria for this phase

### Codebase Patterns
- `data/scraper.py` — module structure, `get_db()` usage, constant definitions, `_private` helper convention, logging pattern
- `models/predict.py` — `KellyResult` dataclass (reference for `ResolveResult` dataclass style)
- `data/odds.py` — `OddsMarket` dataclass (Phase 1 output; same style to follow)

### Phase 1 Output (must exist before Phase 2 executes)
- `data/odds.py` — `OddsMarket` dataclass; `NameResolver` will receive `OddsMarket.rider_a_name` / `rider_b_name` as input

No external specs — requirements fully captured in decisions above.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `data/scraper.py` `get_db()` — used in `NameResolver.__init__()` to load riders from `cache.db`
- `riders` table: `url TEXT PRIMARY KEY, name TEXT` — the primary lookup corpus
- `rapidfuzz` — pre-approved dependency; already in requirements or approved for addition

### Established Patterns
- Module-level constants in `UPPER_SNAKE_CASE`: `AUTO_ACCEPT_THRESHOLD = 90`, `HINT_THRESHOLD = 60`, `CACHE_PATH`
- Private helpers with `_` prefix: `_normalize_name()`, `_load_cache()`, `_save_cache()`
- `logging.getLogger(__name__)` per module; `log.warning()` for recoverable problems
- `dataclass` for structured return types (matches `KellyResult`, `OddsMarket`)
- `Optional[T]` return signals graceful failure to callers

### Integration Points
- `data/name_resolver.py` imported by Phase 4 (`webapp/app.py` endpoints)
- `data/name_mappings.json` — new file, no existing schema to preserve
- `NameResolver` instantiated once per Flask app startup (or per request — Phase 4 decides), not per name lookup

</code_context>

<specifics>
## Specific Ideas

- Must-pass examples from success criteria (used for validation): Primož Roglič, Wout van Aert, Romain Bardet, Nairo Quintana — these specific names must resolve correctly without manual intervention.
- Pinnacle format is SURNAME-FIRST, ALL-CAPS: "ROGLIC PRIMOZ", "VAN AERT WOUT", "QUINTANA NAIRO". Word-order reversal is required before matching.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 02-name-resolver*
*Context gathered: 2026-04-11*
