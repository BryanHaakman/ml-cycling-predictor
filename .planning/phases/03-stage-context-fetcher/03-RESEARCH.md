# Phase 3: Stage Context Fetcher - Research

**Researched:** 2026-04-12
**Domain:** procyclingstats lib (Stage/Race scrapers), SQLite fuzzy matching, Windows-safe timeout
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Fuzzy-match Pinnacle race name against `races` table in `cache.db`. Call `Race.stages()` to list stages for current year. Find today's stage by matching the `MM-DD` date field to today's date.
- **D-02:** Pinnacle name parsing is lenient with a documented assumption. Assumed format: `"RACE NAME - Stage N"`. Separator must be a named constant `PINNACLE_STAGE_SEPARATOR` for easy adjustment post-Phase-1. Parser must log the assumption used.
- **D-03:** Race not found in `cache.db` → return `StageContext(is_resolved=False)` immediately. No further resolution attempts.
- **D-04:** PCS fetch timeout (5s) or exception → return `StageContext(is_resolved=False)` immediately. No historical pre-fill from `cache.db`.
- **D-05:** New `intelligence/` package: `intelligence/__init__.py` + `intelligence/stage_context.py`.
- **D-06:** Module-level function: `fetch_stage_context(pinnacle_race_name: str) -> StageContext`. Stateless. Matches `data/odds.py` pattern.
- **D-07:** `StageContext` dataclass fields: `distance: float`, `vertical_meters: Optional[int]`, `profile_icon: str`, `profile_score: Optional[int]`, `is_one_day_race: bool`, `stage_type: str`, `race_date: str`, `race_base_url: str`, `num_climbs: int`, `avg_temperature: Optional[float]`, `uci_tour: str`, `is_resolved: bool`.
- **D-08:** Optional fields pass `None` through when PCS returns `None`. `build_feature_vector_manual` zero-fills via `.get()` — no duplicate fallback.
- **D-09:** `num_climbs = len(Stage.climbs())` — count all climbs returned, regardless of category.

### Claude's Discretion

- Exact fuzzy matching strategy for Pinnacle name → `cache.db` race name (rapidfuzz.token_sort_ratio is already available)
- How `uci_tour` is obtained — likely `Race.uci_tour()` if available; fallback to `""` if not
- Request timeout implementation (5s cap per ROADMAP success criteria)
- `is_resolved=False` fallback: log warning, return minimal `StageContext` with `is_resolved=False` and zero-filled numerics

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STGE-01 | System fetches stage details (distance, elevation gain, climb counts/categories, race tier, stage type, profile icon) from PCS via the `procyclingstats` lib given a Pinnacle race name | All fields verified to work on upcoming stages via live testing — see Critical Finding #1 |
| STGE-02 | Stage context fetch failure degrades gracefully — manual input fields remain available and prediction is not blocked | Timeout must use `concurrent.futures.ThreadPoolExecutor` (signal.alarm unavailable on Windows) — see Critical Finding #2 |
</phase_requirements>

---

## Summary

Phase 3 is a greenfield module: `intelligence/stage_context.py` with a single public function `fetch_stage_context(pinnacle_race_name: str) -> StageContext`. The function fuzzy-matches a Pinnacle race name against `cache.db`'s `races` table, uses `Race.stages()` to identify today's stage by date, then fetches full stage details via `Stage(stage_url)`.

All core procyclingstats lib methods (`distance()`, `profile_icon()`, `stage_type()`, `vertical_meters()`, `climbs()`, `date()`, `profile_score()`, `avg_temperature()`, `is_one_day_race()`) work correctly on upcoming (not-yet-started) stages — **this is the key risk from STATE.md and it is now resolved as GREEN**. However, two important behavioral differences exist for upcoming stages versus completed stages: (1) `Stage.is_one_day_race()` always returns `True` for upcoming stages because result tabs are absent; it must be derived from `Race.is_one_day_race()` instead. (2) `Stage.climbs()` returns an empty list for upcoming stages because KOM ranking tables don't exist pre-race; `num_climbs` should fall back to climb count from the `Climbs` header list, but in practice will be 0 until after the race.

The 5-second timeout constraint requires `concurrent.futures.ThreadPoolExecutor` on Windows — `signal.alarm` is not available (Win32 platform confirmed). The procyclingstats lib's `_make_request` has a hardcoded `timeout=30` with `max_retries=3` and exponential backoff, meaning worst-case uncapped it could block for ~102 seconds.

**Primary recommendation:** Wrap the entire `Stage()` constructor call (which triggers the network fetch) in `ThreadPoolExecutor(max_workers=1).submit(...).result(timeout=5)`. If `TimeoutError` is raised, return `StageContext(is_resolved=False)`.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| procyclingstats | installed in .venv | Scrapes PCS race/stage pages, returns typed Python values | Project-native; confirmed working for upcoming stages |
| rapidfuzz | 3.14.5 [VERIFIED: pip show] | Fuzzy race name matching (Pinnacle name → cache.db race name) | Already a project dependency (added Phase 2) |
| sqlite3 | stdlib | Read-only query against `cache.db` races table | Project pattern via `get_db()` |
| concurrent.futures | stdlib | ThreadPoolExecutor-based 5-second timeout (Windows-safe) | signal.alarm unavailable on win32 [VERIFIED: live test] |
| dataclasses | stdlib | `StageContext` dataclass | Project pattern (OddsMarket, ResolveResult) |
| logging | stdlib | `logging.getLogger(__name__)` per module | Project pattern |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| datetime | stdlib | Date arithmetic (today's `MM-DD`, year extraction) | Stage date matching logic |

**No new dependencies required.** All libraries are already in `.venv` or stdlib.

---

## Architecture Patterns

### Module Structure
```
intelligence/
├── __init__.py          # empty or minimal — marks package
└── stage_context.py     # StageContext dataclass + fetch_stage_context()
tests/
└── test_stage_context.py  # unit tests (mock PCS) + live integration test
```

### Pattern 1: Stateless Module-Level Function (matches data/odds.py)
**What:** All logic lives in module-level `_private` helpers called by one public function.
**When to use:** Stateless network operations with no persistent state.
```python
# Source: data/odds.py (project pattern)
TIMEOUT_SECONDS: int = 5
PINNACLE_STAGE_SEPARATOR: str = " - "
log = logging.getLogger(__name__)

@dataclass
class StageContext:
    distance: float
    ...
    is_resolved: bool

def fetch_stage_context(pinnacle_race_name: str) -> StageContext:
    race_name = _parse_race_name(pinnacle_race_name)
    race_url = _resolve_race_url(race_name)
    if not race_url:
        return StageContext(is_resolved=False, ...)
    return _fetch_with_timeout(race_url)
```

### Pattern 2: ThreadPoolExecutor Timeout (Windows-safe, signal-free)
**What:** Wrap blocking PCS fetch in a thread with a 5-second deadline.
**When to use:** Any blocking I/O that must not block the Flask worker on Windows.
```python
# Source: Python stdlib docs, concurrent.futures [ASSUMED from stdlib knowledge]
import concurrent.futures

def _fetch_with_timeout(race_url: str, is_one_day: bool) -> StageContext:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_do_fetch, race_url, is_one_day)
        try:
            return future.result(timeout=TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            log.warning("fetch_stage_context: PCS fetch timed out after %ss", TIMEOUT_SECONDS)
            return _unresolved_context()
        except Exception as exc:
            log.warning("fetch_stage_context: PCS fetch failed: %s", exc)
            return _unresolved_context()
```

### Pattern 3: Race.stages() Date Matching
**What:** `Race.stages()` returns `MM-DD` dates. Match against `today.strftime('%m-%d')`.
**When to use:** Finding today's stage from a stage race overview page.
```python
# Source: live procyclingstats verification 2026-04-12 [VERIFIED]
from datetime import date as _date
today_mmdd = _date.today().strftime('%m-%d')
stages = race.stages()
todays_stage = next((s for s in stages if s['date'] == today_mmdd), None)
```

### Pattern 4: is_one_day_race Derivation
**What:** Use `Race.is_one_day_race()`, NOT `Stage.is_one_day_race()`, for upcoming stages.
**Why:** `Stage.is_one_day_race()` returns `True` for all upcoming stages because result tabs (`.restabs`, `.resultTabs`) are absent in the HTML before the race runs. [VERIFIED: live test on Tour de Romandie 2026 stages, Giro d'Italia 2026 stages]
```python
# Source: live procyclingstats verification 2026-04-12 [VERIFIED]
race = Race(race_year_url)          # e.g. "race/tour-de-romandie/2026"
is_one_day = race.is_one_day_race() # authoritative for upcoming stages
```

### Pattern 5: One-Day Race Stage URL
**What:** One-day races use `race/{slug}/{year}/result`, not `stage-1`.
**Why:** `Race.stages()` returns `[]` for one-day races; the stage page uses `/result` suffix. [VERIFIED: Paris-Roubaix 2026 live test]
```python
# Source: CLAUDE.md "Scraper resilience" + live verification
if race.is_one_day_race():
    stage_url = f"{race_base_url}/{year}/result"
else:
    # find today's stage via Race.stages() date matching
    stage_url = todays_stage['stage_url']
```

### Pattern 6: Fuzzy Race Name Matching
**What:** `rapidfuzz.fuzz.token_sort_ratio` against all race names in `cache.db`.
**Why:** `token_sort_ratio` is order-invariant — handles "Tour de Romandie" vs "TOUR DE ROMANDIE". Already used in Phase 2 (name_resolver.py). Scores verified live:
- `'Tour de Romandie'` vs `'Tour de Romandie'` → 100.0
- `'Paris Roubaix'` vs `'Paris - Roubaix'` → 92.9
- `'Giro dItalia'` vs `"Giro d'Italia"` → 96.0
[VERIFIED: rapidfuzz 3.14.5 live test 2026-04-12]
```python
# Source: data/name_resolver.py (project pattern), rapidfuzz [VERIFIED]
from rapidfuzz import fuzz, process
RACE_MATCH_THRESHOLD: int = 75  # Claude's discretion — conservative for race names

def _resolve_race_url(race_name: str) -> Optional[str]:
    conn = get_db()
    rows = conn.execute("SELECT url, name, year FROM races WHERE year = ?",
                        (current_year,)).fetchall()
    conn.close()
    names = [r['name'] for r in rows]
    result = process.extractOne(race_name, names, scorer=fuzz.token_sort_ratio,
                                score_cutoff=RACE_MATCH_THRESHOLD)
    if result:
        matched_name, score, idx = result
        return rows[idx]['url']
    return None
```

### Recommended StageContext Dataclass
```python
# Source: CONTEXT.md D-07, matching build_feature_vector_manual race_params keys [VERIFIED]
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class StageContext:
    distance: float = 0.0
    vertical_meters: Optional[int] = None
    profile_icon: str = "p1"
    profile_score: Optional[int] = None
    is_one_day_race: bool = False
    stage_type: str = "RR"
    race_date: str = ""
    race_base_url: str = ""
    num_climbs: int = 0
    avg_temperature: Optional[float] = None
    uci_tour: str = ""
    is_resolved: bool = False
```

### Anti-Patterns to Avoid
- **Using `Stage.is_one_day_race()` for upcoming stages:** Always returns `True` for stages not yet run. Use `Race.is_one_day_race()` instead.
- **Using `signal.alarm` for timeout:** Not available on Windows (win32). Use `concurrent.futures.ThreadPoolExecutor.result(timeout=...)`.
- **Comparing `Stage.date()` (`YYYY-MM-DD`) against `Race.stages()['date']` (`MM-DD`) directly:** They are different formats. Use `today.strftime('%m-%d')` for matching against `Race.stages()` output.
- **Building stage URL as `race_url + /stage-N`:** The `stage_url` field from `Race.stages()` is already the correct relative URL (e.g., `race/tour-de-romandie/2026/stage-1`).
- **Calling `Stage()` with a nonexistent URL without exception handling:** The lib does not raise `ValueError` for 404 pages — it silently creates an object, but method calls then raise `AttributeError: 'NoneType' object has no attribute 'css'`. Wrap in `try/except Exception`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Race name fuzzy matching | Custom string distance | `rapidfuzz.fuzz.token_sort_ratio` | Already a project dependency; verified working for race names |
| PCS page scraping | HTTP + HTML parsing | `procyclingstats.Stage`, `procyclingstats.Race` | Handles cloudscraper, retries, field extraction |
| 5-second timeout on Windows | Threading primitives | `concurrent.futures.ThreadPoolExecutor.result(timeout=N)` | stdlib, safe on Windows, clean cancellation |
| DB access | Raw sqlite3 | `get_db()` from `data.scraper` | Sets WAL mode, Row factory — project pattern |

---

## Critical Findings

### Critical Finding #1: procyclingstats lib WORKS for upcoming stages (risk RESOLVED)
[VERIFIED: live testing against Tour de Romandie 2026 and Giro d'Italia 2026 — both upcoming as of 2026-04-12]

All methods work on upcoming (not-yet-started) stage pages:
- `Stage.distance()` — returns correct float
- `Stage.profile_icon()` — returns `p1`–`p5`
- `Stage.stage_type()` — returns `RR`, `ITT`, or `TTT`
- `Stage.vertical_meters()` — returns `Optional[int]`, works correctly
- `Stage.profile_score()` — returns `Optional[int]`, works correctly
- `Stage.date()` — returns `YYYY-MM-DD`, correct
- `Stage.avg_temperature()` — returns `None` for upcoming (no weather data yet), expected

**Exception: `Stage.climbs()`** — returns `[]` for upcoming stages because the KOM ranking table (`.today` section) doesn't exist before the race. `num_climbs` will be 0 for all upcoming stages. This is acceptable per D-09.

**Exception: `Stage.is_one_day_race()`** — returns `True` for ALL upcoming stages, even stages within a stage race. See Critical Finding #3.

### Critical Finding #2: signal.alarm NOT available on Windows
[VERIFIED: live test on win32 — `hasattr(signal, 'SIGALRM')` is `False`]

The 5-second timeout (D-04, STGE-02) MUST be implemented via `concurrent.futures.ThreadPoolExecutor.result(timeout=5)`. The `signal.alarm` approach (common in Unix code) will silently fail to import on this Windows machine.

The procyclingstats lib has `max_retries=3` with exponential backoff (0s, 2s, 4s delays) plus 30s per-request timeout. Worst-case uncapped blocking time: ~102 seconds. The ThreadPoolExecutor timeout is the only reliable cap.

**Note on ThreadPoolExecutor cancellation:** `future.cancel()` does NOT interrupt in-progress threads in Python. The background thread may continue running after `TimeoutError` is raised to the caller. This is acceptable — the caller gets `is_resolved=False` within 5 seconds, and the background thread will eventually complete or error out on its own.

### Critical Finding #3: is_one_day_race() behavior difference for upcoming stages
[VERIFIED: live testing 2026-04-12]

| Stage State | `Stage.is_one_day_race()` | `Race.is_one_day_race()` |
|-------------|--------------------------|--------------------------|
| Completed (TDF 2025 Stage 1) | `False` (correct) | `False` (correct) |
| Upcoming (Romandie 2026 Stage 3) | `True` (WRONG) | `False` (correct) |
| One-day race (Paris-Roubaix 2026) | `True` (correct) | `True` (correct) |

**Resolution:** Always derive `is_one_day_race` from `Race.is_one_day_race()`, not from `Stage.is_one_day_race()`.

### Critical Finding #4: Race.stages() date format is MM-DD
[VERIFIED: live test — Tour de Romandie 2026 returned `'04-28'`, `'04-29'`, etc.]

The `date` field in `Race.stages()` dicts is `MM-DD` format, NOT `YYYY-MM-DD`. The year is implicit from the race URL.

**Matching logic:** `today.strftime('%m-%d')` vs `stage['date']`.

`Stage.date()` returns `YYYY-MM-DD` — these are different formats. Do not compare them directly.

### Critical Finding #5: Race.uci_tour() works on upcoming races
[VERIFIED: live test — Tour de Romandie 2026 returned `'2.UWT'`, Paris-Roubaix 2026 returned `'1.UWT'`]

`Race.uci_tour()` parses from `.list > li > div:nth-child(2)` at index [3]. Works for both upcoming stage races and one-day races.

### Critical Finding #6: One-day race uses /result suffix
[VERIFIED: Paris-Roubaix 2026 — `Stage('race/paris-roubaix/2026')` raises AttributeError on method calls; `Stage('race/paris-roubaix/2026/result')` works correctly]

`Race.stages()` returns `[]` for one-day races. The stage URL for a one-day race must be constructed as `f"{race_base_url}/{year}/result"`.

This matches the CLAUDE.md note: "One-day races require `/result` URL suffix."

---

## Common Pitfalls

### Pitfall 1: Trusting Stage.is_one_day_race() for upcoming stages
**What goes wrong:** `StageContext.is_one_day_race` is set to `True` for every upcoming stage in a stage race, causing `build_feature_vector_manual` to compute wrong features.
**Why it happens:** The `is_one_day_race()` method checks for `.restabs` and `.resultTabs` HTML elements, which only appear after race results are published.
**How to avoid:** Always derive `is_one_day_race` from `Race.is_one_day_race()`, fetched once per race, not from `Stage`.
**Warning signs:** All stages of a multi-day race return `is_one_day_race=True`.

### Pitfall 2: Stage.climbs() always returns [] for upcoming stages
**What goes wrong:** `num_climbs` is always 0 for upcoming stages even when climbs are listed.
**Why it happens:** `climbs()` depends on the KOM ranking table (`.today` section), which is only populated post-race. The `_find_header_list("Climbs")` approach is used to get climb names but `climbs()` returns `[]` when the KOM tab's `today` section doesn't exist.
**How to avoid:** Accept that `num_climbs = 0` for upcoming stages. This is consistent with D-09. Document in module docstring.
**Warning signs:** N/A — this is expected behavior, not a bug.

### Pitfall 3: Timeout not wrapping Race() constructor
**What goes wrong:** `Race()` constructor makes an HTTP request. If only `Stage()` is wrapped in the timeout, a slow `Race()` call can block for 30+ seconds before the timeout context even starts.
**Why it happens:** The 5-second budget covers the entire fetch operation including the `Race()` call to get `uci_tour` and `is_one_day_race`.
**How to avoid:** The entire `_do_fetch()` helper (which calls both `Race()` and `Stage()`) must run inside the `ThreadPoolExecutor.submit()` call.
**Warning signs:** Timeouts only fire on the Stage fetch, not the Race fetch.

### Pitfall 4: Nonexistent stage URL raises AttributeError, not ValueError
**What goes wrong:** Calling `Stage('race/nonexistent/2026/stage-1')` does not raise a helpful error at construction time; method calls like `distance()` raise `AttributeError: 'NoneType' object has no attribute 'css'`.
**Why it happens:** `_html_valid()` returns `True` for 404 pages whose HTML doesn't contain the expected error markers, so no `ValueError` is raised.
**How to avoid:** Always wrap all `Stage()` + method calls in a broad `try/except Exception` inside `_do_fetch()`.
**Warning signs:** Unexpected `AttributeError` from inside procyclingstats methods.

### Pitfall 5: Race name year mismatch in cache.db query
**What goes wrong:** The fuzzy match finds a race from a wrong year (e.g., Giro 2025 when looking for Giro 2026).
**Why it happens:** Multiple editions of the same race exist in `cache.db` with identical names but different years.
**How to avoid:** Filter the `races` query to `WHERE year = ?` using the current year. If no match in current year, optionally expand to all years.
**Warning signs:** `race_date` in returned `StageContext` is from a prior year.

---

## Code Examples

### Complete fetch flow (verified pattern)
```python
# Source: live procyclingstats verification 2026-04-12 [VERIFIED]
from procyclingstats import Race, Stage
from datetime import date as _date

# Step 1: Instantiate Race page (fetches HTML)
race = Race("race/tour-de-romandie/2026")

# Step 2: Get metadata from Race
is_one_day = race.is_one_day_race()        # False for stage race
uci_tour = race.uci_tour()                 # "2.UWT"

# Step 3: Find today's stage
if is_one_day:
    # Extract race slug + year from URL
    stage_url = "race/tour-de-romandie/2026/result"
else:
    today_mmdd = _date.today().strftime('%m-%d')
    stages = race.stages()
    # stages[0] = {'profile_icon': 'p1', 'stage_name': '...', 'stage_url': '...', 'date': '04-28'}
    todays = next((s for s in stages if s['date'] == today_mmdd), None)
    stage_url = todays['stage_url']  # e.g. "race/tour-de-romandie/2026/stage-1"

# Step 4: Fetch Stage details
stage = Stage(stage_url)
context = StageContext(
    distance=stage.distance(),              # 3.0
    vertical_meters=stage.vertical_meters(),# 58 (or None)
    profile_icon=stage.profile_icon(),      # "p1"
    profile_score=stage.profile_score(),    # 9 (or None)
    is_one_day_race=is_one_day,            # False — from Race, NOT stage.is_one_day_race()
    stage_type=stage.stage_type(),          # "RR"
    race_date=stage.date(),                 # "2026-04-28"
    race_base_url="race/tour-de-romandie", # stripped of year
    num_climbs=len(stage.climbs()),         # 0 for upcoming stages
    avg_temperature=stage.avg_temperature(),# None for upcoming
    uci_tour=uci_tour,                      # "2.UWT"
    is_resolved=True,
)
```

### Race base URL extraction
```python
# Source: analysis of cache.db url format [VERIFIED]
# cache.db races.url format: "race/tour-de-romandie/2026"
# race_base_url for build_feature_vector_manual: "race/tour-de-romandie"
def _extract_base_url(race_url: str) -> str:
    # race_url from cache.db: "race/{slug}/{year}"
    parts = race_url.rsplit('/', 1)
    return parts[0]  # "race/{slug}"
```

### Cache.db race query pattern
```python
# Source: data/name_resolver.py pattern + stages table schema [VERIFIED]
from data.scraper import get_db
from rapidfuzz import fuzz, process

def _resolve_race_url(race_name: str, year: int) -> Optional[str]:
    conn = get_db()
    rows = conn.execute(
        "SELECT url, name FROM races WHERE year = ?", (year,)
    ).fetchall()
    conn.close()
    if not rows:
        return None
    names = [r['name'] for r in rows]
    result = process.extractOne(race_name, names, scorer=fuzz.token_sort_ratio,
                                score_cutoff=75)
    if result:
        _, _, idx = result
        log.info("_resolve_race_url: matched %r -> %r (score %s)", race_name, rows[idx]['url'], result[1])
        return rows[idx]['url']
    log.warning("_resolve_race_url: no match found for %r in year %d", race_name, year)
    return None
```

---

## build_feature_vector_manual Key Mapping

The `race_params` dict expected by `build_feature_vector_manual` (line 225 `features/pipeline.py`) maps directly to `StageContext` fields:

| `race_params` key | `StageContext` field | Notes |
|-------------------|---------------------|-------|
| `distance` | `distance` | float, km |
| `vertical_meters` | `vertical_meters` | Optional[int]; zero-filled by `.get()` in pipeline |
| `profile_icon` | `profile_icon` | str, `p1`–`p5` |
| `profile_score` | `profile_score` | Optional[int]; estimated from icon if None |
| `is_one_day_race` | `is_one_day_race` | bool |
| `stage_type` | `stage_type` | str: `RR`, `ITT`, `TTT` |
| `race_date` | `race_date` | str `YYYY-MM-DD` |
| `race_base_url` | `race_base_url` | str e.g. `"race/tour-de-romandie"` |
| `num_climbs` | `num_climbs` | int; 0 for upcoming stages |
| `avg_temperature` | `avg_temperature` | Optional[float]; None for upcoming |
| `uci_tour` | `uci_tour` | str e.g. `"1.UWT"`, `"2.UWT"` |

Phase 4 converts `StageContext` → `race_params` dict by calling `dataclasses.asdict()` or building the dict manually. The field names are already aligned.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| procyclingstats lib | Stage/Race scraping | Yes | installed in .venv | None — core dependency |
| rapidfuzz | Race name fuzzy match | Yes | 3.14.5 | None — already required by Phase 2 |
| concurrent.futures | 5s timeout | Yes | stdlib | None — replaces signal.alarm (unavailable on win32) |
| signal.SIGALRM | timeout (Unix) | No | — | concurrent.futures.ThreadPoolExecutor |
| cache.db | Race URL lookup | Yes | present | None — is_resolved=False if absent |

**Missing dependencies with no fallback:** None — all required dependencies are available.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing in project) |
| Config file | none — discovered via `tests/` directory |
| Quick run command | `pytest tests/test_stage_context.py -v` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STGE-01 | `fetch_stage_context()` returns populated `StageContext` with all fields | unit (mocked Race/Stage) | `pytest tests/test_stage_context.py::TestFetchStageContext::test_resolved -x` | No — Wave 0 |
| STGE-01 | Fields map correctly to `build_feature_vector_manual` `race_params` keys | unit | `pytest tests/test_stage_context.py::TestStageContextFields -x` | No — Wave 0 |
| STGE-01 | `Race.uci_tour()` and `Race.is_one_day_race()` used (not Stage equivalents) | unit | `pytest tests/test_stage_context.py::TestIsOneDayRaceSource -x` | No — Wave 0 |
| STGE-02 | Unrecognized race name returns `is_resolved=False` without raising | unit | `pytest tests/test_stage_context.py::TestFallbacks::test_unresolved_race -x` | No — Wave 0 |
| STGE-02 | PCS exception returns `is_resolved=False` within 5 seconds | unit (patched timeout) | `pytest tests/test_stage_context.py::TestFallbacks::test_pcs_exception -x` | No — Wave 0 |
| STGE-01 + STGE-02 | Live integration: real PCS call on known upcoming race | integration (live) | `pytest tests/test_stage_context.py::TestLiveIntegration -v -s` | No — Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_stage_context.py -x`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_stage_context.py` — covers STGE-01, STGE-02
- [ ] `intelligence/__init__.py` — package marker
- [ ] `intelligence/stage_context.py` — implementation file

---

## Open Questions (RESOLVED)

1. **Pinnacle race name format (exact separator)**
   - What we know: CONTEXT.md D-02 assumes `"RACE NAME - Stage N"` format with `" - "` separator
   - What's unclear: The actual Pinnacle format is unknown until Phase 1 completes. The race name portion may differ from the PCS canonical name.
   - Recommendation: Implement with `PINNACLE_STAGE_SEPARATOR = " - "` as named constant. Parse by splitting on separator and taking the first part. Log the parsed assumption. If Phase 1 reveals a different format, update only the constant.

2. **Fuzzy match threshold for race names**
   - What we know: `token_sort_ratio` gives 92+ for `'Paris Roubaix'` vs `'Paris - Roubaix'`, 96+ for Giro name variations, 100 for exact matches [VERIFIED]
   - What's unclear: Whether Pinnacle uses shortened names that might score below 75
   - Recommendation: Start at `RACE_MATCH_THRESHOLD = 75`. Log the score on every match so it can be tuned after Phase 1 data is available.

3. **ThreadPoolExecutor thread leak on timeout**
   - What we know: When `future.result(timeout=5)` raises `TimeoutError`, the background thread continues executing (Python cannot kill threads)
   - What's unclear: Whether this causes meaningful resource pressure under repeated timeout failures
   - Recommendation: Acceptable for a personal tool. The thread will terminate when the underlying `requests` socket timeout fires (30s max). No thread pool reuse — create a new executor per call to ensure clean state.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `RACE_MATCH_THRESHOLD = 75` is appropriate for fuzzy race name matching | Architecture Patterns #6 | Too low: wrong race matched; too high: valid race missed → `is_resolved=False` |
| A2 | Pinnacle race names contain the PCS race name as a recognizable substring (fuzzy-matchable) | Architecture Patterns #6 | If Pinnacle uses heavily abbreviated names, fuzzy matching fails → manual input always required |
| A3 | `concurrent.futures.ThreadPoolExecutor.result(timeout=5)` raises `TimeoutError` (not `concurrent.futures.TimeoutError`) | Architecture Patterns #2 | Code catches wrong exception; timeout never fires |
| A4 | `Stage()` constructor for a 404 page does not raise but produces unusable HTML (methods raise AttributeError) | Common Pitfalls #4 | If the lib is updated to raise ValueError on 404, the broad `except Exception` still catches it |

**Note on A3:** The correct exception is `concurrent.futures.TimeoutError`, which is a subclass of `TimeoutError` in Python 3.11+. The code should catch `concurrent.futures.TimeoutError` specifically to be explicit.

---

## Sources

### Primary (HIGH confidence)
- procyclingstats `stage_scraper.py` and `race_scraper.py` — read directly from `.venv/Lib/site-packages/procyclingstats/`
- procyclingstats `scraper.py` — base class, HTTP behavior, timeout settings
- `features/pipeline.py` lines 225-350 — `build_feature_vector_manual` race_params keys verified directly
- `data/name_resolver.py` — rapidfuzz usage pattern, `ResolveResult` dataclass style
- `data/odds.py` — `OddsMarket` dataclass style, module-level function pattern

### Live Verification (HIGH confidence)
- `Race('race/tour-de-romandie/2026')` — `uci_tour()`, `is_one_day_race()`, `stages()` date format verified 2026-04-12
- `Stage('race/tour-de-romandie/2026/stage-1')` through `stage-3` — all methods tested on upcoming stages 2026-04-12
- `Stage('race/giro-d-italia/2026/stage-1')` — upcoming stage, `is_one_day_race()` behavioral difference confirmed
- `Stage('race/paris-roubaix/2026/result')` — one-day race with `/result` suffix, all methods verified
- `signal` module on win32 — `SIGALRM` and `alarm` confirmed absent
- rapidfuzz 3.14.5 race name fuzzy scoring — verified live

### Tertiary (ASSUMED)
- A1-A4 in Assumptions Log above

---

## Metadata

**Confidence breakdown:**
- procyclingstats lib behavior: HIGH — all key methods tested live against 2026 races
- Timeout mechanism (ThreadPoolExecutor): HIGH — signal.alarm absence confirmed live
- Fuzzy match threshold: MEDIUM — scores verified but Pinnacle format unknown until Phase 1
- StageContext field mapping: HIGH — verified against build_feature_vector_manual source

**Research date:** 2026-04-12
**Valid until:** 2026-05-12 (procyclingstats lib is locally installed; stable unless manually updated)
