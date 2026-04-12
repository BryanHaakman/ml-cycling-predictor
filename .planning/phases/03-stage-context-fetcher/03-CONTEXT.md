# Phase 3: Stage Context Fetcher - Context

**Gathered:** 2026-04-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement `intelligence/stage_context.py` — a module-level function `fetch_stage_context(pinnacle_race_name: str) -> StageContext` that maps a Pinnacle race name to a PCS stage URL (via cache.db fuzzy match + `Race.stages()` date lookup), fetches stage details via the `procyclingstats` lib, and returns a fully-populated `StageContext` dataclass ready to pass directly to `build_feature_vector_manual`. Degrades to `is_resolved=False` within 5 seconds when PCS is unavailable.

This phase delivers the fetcher module only — Flask endpoint wiring is Phase 4.

</domain>

<decisions>
## Implementation Decisions

### Pinnacle → PCS Race Matching
- **D-01:** Fuzzy-match the Pinnacle race name against races in `cache.db` to identify the PCS race base URL. Then call `Race.stages()` to list stages for the current year, and find today's stage by matching the stage date to today's date.
- **D-02:** Pinnacle name parsing is **lenient with a documented assumption**. The assumed format is `"RACE NAME - Stage N"` (or similar separator), but the exact format is unknown until Phase 1 discovery. The separator pattern must be a named constant (`PINNACLE_STAGE_SEPARATOR`) so it's easy to adjust after Phase 1 confirms the real format. The parser should log the assumption it used so mismatches are visible.
- **D-03:** When the race is not found in `cache.db`: return `StageContext(is_resolved=False)` immediately — **Claude's discretion** on exact fallback behavior, but `is_resolved=False` with no further resolution attempts is the recommended default.

### Cache.db Fallback on PCS Failure
- **D-04:** When PCS fetch times out (5 seconds) or raises an exception, return `StageContext(is_resolved=False)` immediately. **No** historical pre-fill from cache.db — past edition data could silently mislead on changed routes. Manual input fields in Phase 5 are the fallback.

### Module Location and Interface
- **D-05:** New `intelligence/` package: `intelligence/__init__.py` + `intelligence/stage_context.py`. This signals the beginning of the analysis layer (v1.1 Intelligence Pipeline will extend this package). Matches ROADMAP.md plan.
- **D-06:** Module-level function style: `fetch_stage_context(pinnacle_race_name: str) -> StageContext`. No class instantiation — this is a stateless network operation. Consistent with `data/odds.py` pattern.

### StageContext Dataclass Fields
- **D-07:** `StageContext` is a `dataclass` (consistent with `OddsMarket`, `ResolveResult`). Fields mirror what `build_feature_vector_manual` expects: `distance: float`, `vertical_meters: Optional[int]`, `profile_icon: str`, `profile_score: Optional[int]`, `is_one_day_race: bool`, `stage_type: str`, `race_date: str`, `race_base_url: str`, `num_climbs: int`, `avg_temperature: Optional[float]`, `uci_tour: str`, `is_resolved: bool`.
- **D-08:** Optional fields (`vertical_meters`, `avg_temperature`, `profile_score`) pass `None` through when PCS returns `None`. `build_feature_vector_manual` already zero-fills via `.get()` — no duplicate fallback logic in this module.
- **D-09:** `num_climbs = len(Stage.climbs())` — count all climbs returned, regardless of category. Matches how `num_climbs` is consumed by `build_feature_vector_manual`.

### Claude's Discretion
- Exact fuzzy matching strategy for Pinnacle name → `cache.db` race name (e.g., `rapidfuzz.token_sort_ratio` is already a project dependency and a natural choice).
- How `uci_tour` is obtained — likely from `Race.uci_tour()` if available; fallback to `""` if not.
- Request timeout implementation (5s cap per ROADMAP success criteria).
- `is_resolved=False` fallback behavior when race not found in `cache.db` (log warning, return minimal `StageContext` with `is_resolved=False` and zero-filled numerics).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Requirements
- `.planning/REQUIREMENTS.md` §Stage Context — STGE-01, STGE-02 are the acceptance criteria for this phase

### Codebase Patterns
- `data/scraper.py` — module-level function pattern, `get_db()` usage, constant definitions, logging, error handling
- `data/odds.py` — module-level function style, `OddsMarket` dataclass (reference for `StageContext` style)
- `data/name_resolver.py` — `ResolveResult` dataclass; also uses `rapidfuzz` which is available for the race name fuzzy match
- `features/pipeline.py` `build_feature_vector_manual()` (line 225) — exact `race_params` keys expected by the downstream consumer; `StageContext` fields must map to these keys

### procyclingstats lib (installed in .venv)
- `.venv/Lib/site-packages/procyclingstats/stage_scraper.py` — `Stage` class: `distance()`, `profile_icon()`, `stage_type()`, `vertical_meters()`, `avg_temperature()`, `climbs()`, `date()`, `profile_score()`, `race_startlist_quality_score()`, `uci_points_scale()`, `is_one_day_race()`
- `.venv/Lib/site-packages/procyclingstats/race_scraper.py` — `Race` class: `stages()` (returns list of dicts with `stage_url`, `date`, `profile_icon`, `stage_name`), `uci_tour()`

### Prior Phase Outputs (must exist at execution time)
- `data/odds.py` — `OddsMarket` dataclass (Phase 1 output); Phase 4 passes `OddsMarket.race_name` as input to `fetch_stage_context()`
- `data/name_resolver.py` — established dataclass style and `Optional[T]` conventions

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `data/scraper.py` `get_db()` — used to query `cache.db` for race name fuzzy matching
- `rapidfuzz` — already a dependency (added for Phase 2); natural choice for Pinnacle name → cache.db race name matching
- `races` table in `cache.db`: has `url`, `name`, `year` columns for fuzzy matching
- `stages` table: has `url`, `date`, `distance`, `profile_icon`, etc. for historical reference (not used for live fetch but useful for validation)

### Established Patterns
- Module-level constants: `TIMEOUT_SECONDS = 5`, `PINNACLE_STAGE_SEPARATOR = " - "` (adjustable after Phase 1)
- `_private` helpers: `_resolve_race_url()`, `_find_todays_stage()`, `_fetch_stage_data()`
- `logging.getLogger(__name__)` per module
- `Optional[T]` signals graceful failure; `is_resolved: bool` field in dataclass signals resolution status

### Integration Points
- `intelligence/stage_context.py` imported by Phase 4 (`webapp/app.py` endpoints)
- `cache.db` `races` table queried read-only during race resolution
- `procyclingstats` lib called directly (no MCP server dependency — self-contained, VPS-safe)
- Returns `StageContext` → Phase 4 converts to `race_params` dict → `build_feature_vector_manual()`

</code_context>

<specifics>
## Specific Ideas

- The ROADMAP success criteria require verifying against at least one **live upcoming race** (SC-1). This means Phase 3 execution must include a live integration test, not just unit tests with mocks.
- The ROADMAP flags a known risk (STATE.md Blockers/Concerns): `procyclingstats` lib behavior for upcoming (not-yet-completed) races is **unverified**. The research step must confirm whether `Stage` works with a live upcoming race URL before implementation begins.
- Phase 1 hasn't run yet, so the exact Pinnacle race name format is unknown. The `PINNACLE_STAGE_SEPARATOR` constant is the safety valve — documented clearly so it's the first thing to check if name parsing fails.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 03-stage-context-fetcher*
*Context gathered: 2026-04-12*
