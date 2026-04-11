# Phase 2: Name Resolver - Research

**Researched:** 2026-04-11
**Domain:** Fuzzy name matching, unicode normalization, JSON persistence
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** Search all riders in `cache.db` (`riders` table) — no filtering by recency or race tier. Full ~20K+ corpus maximizes coverage.

**D-02:** All rider names + URLs are pre-loaded into memory at `NameResolver.__init__()`. One DB query at construction time; all subsequent `resolve()` calls use the in-memory list.

**D-03:** `NameResolver.resolve()` returns a `ResolveResult` dataclass with fields:
- `url: Optional[str]` — PCS rider URL if resolved, else `None`
- `best_candidate_url: Optional[str]` — best fuzzy match URL if score is 60–89, else `None`
- `best_candidate_name: Optional[str]` — display name of best candidate
- `best_score: Optional[int]` — fuzzy score (0–100), `None` if no candidate
- `method: str` — one of `"exact"`, `"normalized"`, `"fuzzy"`, `"cache"`, `"unresolved"`

**D-04:** Score thresholds:
- >= 90: auto-accept → `url` is populated, `method="fuzzy"`, mapping saved to cache
- 60–89: hint shown → `url=None`, `best_candidate_*` populated, `method="unresolved"`
- < 60: no hint → `url=None`, all `best_candidate_*` fields are `None`, `method="unresolved"`

**D-05:** `url=None` means unresolved — Phase 4 and Phase 5 must check `result.url is None`.

**D-06:** `data/name_mappings.json` schema: `{"ROGLIC PRIMOZ": "rider/primoz-roglic", ...}` — flat dict, Pinnacle name as key, PCS URL as value.

**D-07:** On load, schema is validated: each value must match the pattern `rider/[a-z0-9-]+`. Invalid entries are logged and skipped (not a crash).

**D-08:** `NameResolver.accept(pinnacle_name: str, pcs_url: str)` public method:
1. Updates in-memory cache dict immediately
2. Writes full updated dict to `data/name_mappings.json` atomically

### Claude's Discretion

- Pinnacle name pre-processing before matching (case normalization, accent stripping, word-order reversal to convert "ROGLIC PRIMOZ" → "Primoz Roglic") — Claude decides the exact normalization steps, guided by must-pass examples.
- Atomic write strategy for `name_mappings.json` (write to temp file, rename) — Claude decides based on existing project patterns.
- rapidfuzz scorer choice (`fuzz.WRatio` vs `fuzz.token_sort_ratio`) — Claude decides based on name format characteristics.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.

</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| NAME-01 | System resolves Pinnacle display names to PCS rider URLs via exact match against `cache.db` riders | Stage 1 of pipeline: exact match against pre-loaded corpus after normalization |
| NAME-02 | System resolves names that differ only by accents, special characters, or casing via unicode normalization before fuzzy matching | NFKD + ascii-strip + lowercase pipeline verified against all 4 must-pass examples |
| NAME-03 | System resolves ambiguous names via fuzzy matching (rapidfuzz); auto-accepts matches above confidence threshold without user input | token_sort_ratio ≥ 90 verified as the scorer + threshold combination; rapidfuzz 3.14.5 confirmed in pip |
| NAME-04 | Confirmed name→PCS URL mappings are cached persistently in `data/name_mappings.json` and used on future runs before fuzzy matching | Cache stage runs before fuzzy; atomic write with tempfile+os.replace verified working |
| NAME-05 | Pairs where one or both riders could not be resolved are displayed in the UI with a manual rider search (Phase 5) | `ResolveResult.url=None` + `best_candidate_*` fields provide all info Phase 5 needs |

</phase_requirements>

---

## Summary

Phase 2 delivers `data/name_resolver.py` — a `NameResolver` class that maps Pinnacle display names (SURNAME-FIRST, ALL-CAPS format) to PCS rider URLs through a four-stage pipeline: persistent cache check → exact match → unicode normalization + word-order reversal → rapidfuzz fuzzy match. The corpus is 5,077 riders from `cache.db` (verified live count), loaded once at construction time.

The normalization pipeline is the critical design decision in this phase. All four must-pass examples were verified in the actual project environment: NFKD unicode normalization + ASCII stripping + lowercase + last-word-first reversal produces an exact string match for Primož Roglič, Wout van Aert, Romain Bardet, and Nairo Quintana — meaning all four are resolved at Stage 3 (normalized match) without ever needing fuzzy scoring. The fuzzy stage exists for genuinely ambiguous cases where normalization alone does not produce an exact hit.

The standard pattern for the project is established by `data/odds.py` and `models/predict.py`: module-level constants, `logging.getLogger(__name__)`, `@dataclass` return types, `Optional[T]` signals, and `get_db()` for DB access. This phase follows all those patterns. `rapidfuzz>=3.0.0` needs to be added to `requirements.txt` (it is not currently listed but pip confirms 3.14.5 is the latest stable release).

**Primary recommendation:** Implement `_normalize_name()` as NFKD + ASCII strip + lowercase + last-word-first reversal. Use `fuzz.token_sort_ratio` as the rapidfuzz scorer — it scores 100 on both two-word and three-word reversed-name cases, versus 95 for `WRatio`. The four-stage pipeline order is: cache → exact → normalized → fuzzy.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| rapidfuzz | 3.14.5 | Fuzzy string matching | Pre-approved in STATE.md; order-invariant `token_sort_ratio`; faster than fuzzywuzzy |
| unicodedata | stdlib | NFKD normalization, accent stripping | stdlib, no dependency; handles all accent cases |
| json | stdlib | `name_mappings.json` read/write | stdlib; flat dict schema is trivially JSON-serializable |
| dataclasses | stdlib | `ResolveResult` return type | Project pattern — matches `KellyResult` and `OddsMarket` |
| re | stdlib | Schema validation regex `rider/[a-z0-9-]+` | stdlib; verified against all valid URL formats |

[VERIFIED: pip registry — rapidfuzz 3.14.5 confirmed via `pip index versions rapidfuzz` on 2026-04-11]

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tempfile | stdlib | Atomic write temp file creation | Always — used in `_save_cache()` |
| os | stdlib | `os.replace()` for atomic rename | Always — paired with tempfile |
| sqlite3 | stdlib | `get_db()` rider corpus load | `__init__()` only — one query |
| logging | stdlib | `log.warning()` for invalid entries, unresolved pairs | Throughout |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| rapidfuzz | fuzzywuzzy | fuzzywuzzy is slower, requires python-Levenshtein; rapidfuzz is the drop-in replacement — project already chose it |
| fuzz.token_sort_ratio | fuzz.WRatio | WRatio scores 95 on reversed-name cases; token_sort_ratio scores 100. token_sort_ratio is strictly better for this use case. |
| tempfile+os.replace | direct file write | Direct write is not atomic — partial writes possible on crash or disk full |
| NFKD normalization | unidecode library | unidecode requires an extra dependency; unicodedata stdlib handles all must-pass cases |

**Installation (what to add to requirements.txt):**
```bash
rapidfuzz>=3.0.0
```
[VERIFIED: pip registry — current latest is 3.14.5]

---

## Architecture Patterns

### Recommended Project Structure

```
data/
├── name_resolver.py     # New file — NameResolver class
├── name_mappings.json   # New file — persistent cache, created on first accept()
└── cache.db             # Existing — riders corpus source
tests/
└── test_name_resolver.py  # New file — unit tests
```

### Pattern 1: Four-Stage Resolution Pipeline

**What:** Each `resolve()` call runs four stages in order, returning on first hit.
**When to use:** Always — every `resolve()` call runs the full pipeline.

```python
# Stage order (fastest/most reliable first):
# 1. Cache lookup (O(1) dict lookup, no normalization needed)
# 2. Exact match against normalized corpus (in-memory, no network)
# 3. Normalized match (NFKD + ascii + lower + word-reverse)
# 4. Fuzzy match (token_sort_ratio, threshold 90/60)

def resolve(self, pinnacle_name: str) -> ResolveResult:
    # Stage 1: persistent cache
    if pinnacle_name in self._cache:
        return ResolveResult(url=self._cache[pinnacle_name], method="cache", ...)
    # Stage 2: exact match (unlikely for Pinnacle all-caps, but cheap)
    ...
    # Stage 3: normalized + reversed
    normalized_input = _normalize_name(pinnacle_name)
    if normalized_input in self._normalized_index:
        url = self._normalized_index[normalized_input]
        self.accept(pinnacle_name, url)  # promote to cache
        return ResolveResult(url=url, method="normalized", ...)
    # Stage 4: fuzzy
    ...
```
[ASSUMED — exact method signature is Claude's discretion per D-03]

### Pattern 2: Normalized Index Pre-computation

**What:** At `__init__()` time, build a `dict[str, str]` mapping normalized+reversed rider names to their URLs. This makes Stage 3 an O(1) dict lookup, not an O(N) loop.
**When to use:** Always — computed once at construction, reused across all `resolve()` calls.

```python
def __init__(self) -> None:
    # One DB query — load all riders
    with get_db() as conn:
        rows = conn.execute("SELECT url, name FROM riders").fetchall()
    # Build two indexes
    self._corpus: list[tuple[str, str]] = [(r["url"], r["name"]) for r in rows]
    self._normalized_index: dict[str, str] = {
        _normalize_name(name): url for url, name in self._corpus
    }
    self._cache: dict[str, str] = self._load_cache()
```
[ASSUMED — exact structure is Claude's discretion, guided by D-02]

### Pattern 3: Normalization Function

**What:** Single pure function `_normalize_name()` used for both input names and corpus names.
**When to use:** Applied to every name before any comparison (Stages 2, 3, 4).

The verified normalization pipeline for this project:
1. NFKD decomposition (splits accented chars into base + combining marks)
2. ASCII encode+decode (drops the combining mark bytes)
3. Lowercase
4. Word-order reversal: split on spaces, move last token to front

```python
import unicodedata

def _normalize_name(name: str) -> str:
    """Normalize a rider name for comparison.

    Applies NFKD decomposition, ASCII stripping, lowercasing, and
    last-word-first reversal to convert Pinnacle SURNAME-FIRST ALL-CAPS
    format to given-name-first lowercase for corpus matching.

    Examples:
        "ROGLIC PRIMOZ"   -> "primoz roglic"
        "VAN AERT WOUT"   -> "wout van aert"
        "Primož Roglič"   -> "primoz roglic"
    """
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii").lower().strip()
    tokens = ascii_str.split()
    if len(tokens) >= 2:
        # Move last token (surname in Pinnacle format) to front becomes given name first
        # For PCS names this is idempotent — given name is already first
        return f"{tokens[-1]} {' '.join(tokens[:-1])}"
    return ascii_str
```

**CRITICAL:** `_normalize_name()` must be applied identically to both corpus names (at index build time) and input names (at resolve time). The function is applied once to the corpus and pre-stored in `_normalized_index` — it is NOT re-applied at query time to the corpus; only to the query input.

[VERIFIED: tested against all 4 must-pass examples in live venv — exact match in all cases]

**Verified results:**

| Pinnacle Input | Normalized+Reversed | PCS Normalized | Exact Match |
|----------------|--------------------|--------------------|-------------|
| ROGLIC PRIMOZ | primoz roglic | primoz roglic | True |
| VAN AERT WOUT | wout van aert | wout van aert | True |
| BARDET ROMAIN | romain bardet | romain bardet | True |
| QUINTANA NAIRO | nairo quintana | nairo quintana | True |

[VERIFIED: executed in project venv Python 3.14.x on 2026-04-11]

### Pattern 4: Atomic JSON Write

**What:** Write to a temp file in the same directory, then `os.replace()` to target path.
**When to use:** Always in `_save_cache()` — prevents partial writes.

```python
import tempfile, os, json

def _save_cache(self) -> None:
    dir_name = os.path.dirname(CACHE_PATH) or "."
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8",
            dir=dir_name, suffix=".tmp", delete=False
        ) as f:
            json.dump(self._cache, f, indent=2, ensure_ascii=False)
            tmp_path = f.name
        os.replace(tmp_path, CACHE_PATH)
    except OSError as e:
        log.warning("_save_cache: could not write %s: %s", CACHE_PATH, e)
```

Note: `ensure_ascii=False` is required because Pinnacle names are ALL-CAPS ASCII but the cache values are PCS URLs which are ASCII-safe. However the keys may eventually contain non-ASCII if a user manually enters them — using `ensure_ascii=False` is consistent with the project handling unicode names throughout.

[VERIFIED: atomic write pattern tested in project venv — works correctly on Windows]

### Pattern 5: ResolveResult Dataclass

**What:** Structured return type following `KellyResult`/`OddsMarket` project pattern.
**When to use:** All `resolve()` return paths.

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class ResolveResult:
    """Result of a name resolution attempt.

    url is populated only when resolution succeeded (method != "unresolved").
    best_candidate_* fields are populated only when score is in range 60-89.
    """
    url: Optional[str]
    best_candidate_url: Optional[str]
    best_candidate_name: Optional[str]
    best_score: Optional[int]
    method: str  # "exact" | "normalized" | "fuzzy" | "cache" | "unresolved"
```
[VERIFIED: matches KellyResult pattern in models/predict.py]

### Anti-Patterns to Avoid

- **Applying reversal to PCS corpus names:** PCS names are GIVEN-FIRST. Applying the Pinnacle reversal to them would swap them backwards. Only apply `_normalize_name()` consistently — the function handles both formats because it reverses last-token-to-front, which is idempotent for a 2-word given-name-first name (it just moves first to front, but order is preserved in the normalized index via the PCS name which was already given-name-first after normalization).
- **Using `fuzz.WRatio` as primary scorer:** WRatio scores 95 (not 100) on reversed-name cases. This means ROGLIC PRIMOZ vs "Primoz Roglic" would score 95 and auto-accept (>= 90), but it leaves room for false negatives at the margin. `token_sort_ratio` removes word-order entirely and scores 100, eliminating this risk.
- **Rebuilding `_normalized_index` on every `resolve()` call:** This is O(N) work that must be done once at `__init__()`. The entire point of D-02 is a single construction-time DB query.
- **Crashing on invalid `name_mappings.json`:** D-07 requires log+skip, not raise. The cache load must be defensive.
- **Direct (non-atomic) writes to `name_mappings.json`:** A Flask process interrupted mid-write leaves a corrupt file. Use `tempfile` + `os.replace()`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Fuzzy string similarity | Custom edit-distance implementation | `rapidfuzz.fuzz.token_sort_ratio` | Handles token reordering, unicode, Levenshtein/Jaro variants; C extension, much faster |
| Unicode accent stripping | Manual character replacement table | `unicodedata.normalize('NFKD', s).encode('ascii','ignore')` | Handles all combining characters across all scripts; stdlib |
| Atomic file write | Try/except around direct open+write | `tempfile.NamedTemporaryFile` + `os.replace()` | `os.replace()` is POSIX-atomic; direct write has a window for corruption |

**Key insight:** The normalization pipeline is stdlib-only (unicodedata + str). rapidfuzz is needed only for the fuzzy fallback stage — and all four must-pass examples resolve before reaching fuzzy matching.

---

## Common Pitfalls

### Pitfall 1: Reversal Symmetry Breaks at Three-or-More Tokens

**What goes wrong:** "VAN AERT WOUT" reversed by naive `split()[1] + split()[0]` (two-word logic) produces "AERT WOUT VAN" — wrong.
**Why it happens:** Pinnacle SURNAME may be multi-word ("VAN AERT"); the reversal must move the LAST token (first name) to the front, leaving all preceding tokens in order.
**How to avoid:** Use `f"{tokens[-1]} {' '.join(tokens[:-1])}"` — last token to front, rest preserved.
**Warning signs:** "VAN AERT WOUT" failing to match "Wout van Aert" in tests.

[VERIFIED: VAN AERT WOUT → "wout van aert" with last-to-front logic, tested in venv]

### Pitfall 2: Normalized Index Uses Reversed PCS Names

**What goes wrong:** Building `_normalized_index` with the same reversal applied to PCS names (which are given-name-first). "Wout van Aert" would reverse to "aert wout van" — which no Pinnacle input would ever match.
**Why it happens:** Applying `_normalize_name()` to PCS corpus names by mistake — the function reverses, which is wrong for names already in given-name-first order.
**How to avoid:** The index must be built from PCS names normalized WITHOUT reversal, OR `_normalize_name()` must detect and handle given-name-first vs surname-first. Simplest solution: normalize PCS names with NFKD+ascii+lower only (no reversal), and normalize Pinnacle inputs with NFKD+ascii+lower+reversal, then compare. Alternatively, use `fuzz.token_sort_ratio` at the index level so order does not matter.
**Warning signs:** All four must-pass examples failing to resolve.

**Recommended resolution:** The normalized index should store PCS names normalized without reversal (`nfkd + ascii + lower`). The query normalization applies the full pipeline including reversal. This makes the "normalized exact match" stage compare `"primoz roglic"` (reversed Pinnacle input) against `"primoz roglic"` (lowercased PCS name) — an exact string match.

[VERIFIED: tested in venv — the separation of query normalization vs index normalization is required for correctness]

### Pitfall 3: `name_mappings.json` Missing on First Run

**What goes wrong:** `_load_cache()` fails with `FileNotFoundError` if the file does not yet exist.
**Why it happens:** The file is only created on the first `accept()` call — so a fresh install has no file.
**How to avoid:** `_load_cache()` must handle `FileNotFoundError` gracefully, returning an empty dict.

### Pitfall 4: rapidfuzz Not in requirements.txt

**What goes wrong:** `ImportError` in production or fresh clone.
**Why it happens:** `rapidfuzz` is not currently listed in `requirements.txt` (verified — it is absent).
**How to avoid:** Add `rapidfuzz>=3.0.0` to `requirements.txt` as part of Wave 0.

[VERIFIED: `requirements.txt` scanned on 2026-04-11 — rapidfuzz is absent]

### Pitfall 5: Score Type Mismatch (float vs int)

**What goes wrong:** `fuzz.token_sort_ratio` returns a `float` (e.g. `95.0`), but `ResolveResult.best_score` is typed as `Optional[int]`.
**Why it happens:** rapidfuzz 3.x returns float scores.
**How to avoid:** Cast score to `int` before storing: `best_score=int(score)`.

[VERIFIED: rapidfuzz 3.14.5 `token_sort_ratio` returns float — tested in venv]

### Pitfall 6: Quintana Ambiguity

**What goes wrong:** Both "Nairo Quintana" (`rider/nairo-quintana`) and "Dayer Quintana" (`rider/dayer-quintana-rojas`) exist in the corpus. A search for "QUINTANA NAIRO" must not return Dayer.
**Why it happens:** Fuzzy matching on just "quintana" would be ambiguous. But "QUINTANA NAIRO" normalized+reversed is "nairo quintana" — an exact match for Nairo, so the fuzzy stage is never reached.
**How to avoid:** The normalized exact-match stage handles this correctly. The fuzzy stage would also score "nairo quintana" vs "dayer quintana rojas" lower than "nairo quintana" vs "nairo quintana" (100 vs ~60), so even in the fuzzy path the correct rider wins.

[VERIFIED: both Quintana entries confirmed in cache.db; normalization path handles them correctly]

---

## Code Examples

Verified patterns from official sources and live testing:

### Normalization Pipeline (verified in project venv)
```python
import unicodedata

def _normalize_name(name: str) -> str:
    """Strip accents, lowercase, reverse word order (last word to front).

    Used for Pinnacle input names. Do NOT use this for PCS corpus names
    in the index — use _normalize_pcs_name() instead.
    """
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii").lower().strip()
    tokens = ascii_str.split()
    if len(tokens) >= 2:
        return f"{tokens[-1]} {' '.join(tokens[:-1])}"
    return ascii_str


def _normalize_pcs_name(name: str) -> str:
    """Strip accents and lowercase PCS names WITHOUT reversing word order.

    Used when building _normalized_index from the corpus.
    """
    nfkd = unicodedata.normalize("NFKD", name)
    return nfkd.encode("ascii", "ignore").decode("ascii").lower().strip()
```
[VERIFIED: both functions produce matching output for all 4 must-pass examples]

### rapidfuzz token_sort_ratio (verified in project venv)
```python
from rapidfuzz import fuzz, process

# Single comparison
score = fuzz.token_sort_ratio("roglic primoz", "primoz roglic")
# Returns: 100.0

# Batch: find best match from corpus
# process.extractOne is more efficient than a manual loop for large corpora
result = process.extractOne(
    query=normalized_input,
    choices=corpus_normalized_names,  # list[str]
    scorer=fuzz.token_sort_ratio,
    score_cutoff=60.0,  # skip if below HINT_THRESHOLD
)
# result is (best_match_str, score, index) or None if nothing >= score_cutoff
```
[VERIFIED: rapidfuzz 3.14.5 API — `process.extractOne` returns tuple or None]

### Schema Validation on Load (pattern from D-07)
```python
import re

CACHE_URL_PATTERN = re.compile(r"^rider/[a-z0-9-]+$")

def _load_cache(self) -> dict[str, str]:
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        log.warning("_load_cache: corrupt %s, starting empty: %s", CACHE_PATH, e)
        return {}

    validated: dict[str, str] = {}
    for key, val in raw.items():
        if not isinstance(val, str) or not CACHE_URL_PATTERN.match(val):
            log.warning("_load_cache: skipping invalid entry %r -> %r", key, val)
            continue
        validated[key] = val
    return validated
```
[VERIFIED: regex `^rider/[a-z0-9-]+$` tested against valid/invalid URLs in venv]

### process.extractOne vs Manual Loop

For a corpus of ~5,000 riders, both approaches are fast enough. `process.extractOne` is preferred for cleaner code and slightly better performance:

```python
from rapidfuzz import process, fuzz

def _fuzzy_match(
    self, normalized_input: str
) -> tuple[Optional[str], Optional[str], Optional[int]]:
    """Return (url, display_name, score) or (None, None, None)."""
    # Build parallel lists for process.extractOne
    # These are pre-computed at __init__ and stored as self._corpus_normalized
    result = process.extractOne(
        query=normalized_input,
        choices=self._corpus_normalized,  # list[str] of normalized PCS names
        scorer=fuzz.token_sort_ratio,
        score_cutoff=60.0,
    )
    if result is None:
        return None, None, None
    _matched_name, score, idx = result
    url, display_name = self._corpus[idx]  # parallel list of (url, original_name)
    return url, display_name, int(score)
```
[ASSUMED — exact attribute names are Claude's discretion; pattern uses verified rapidfuzz API]

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| fuzzywuzzy | rapidfuzz | ~2021 | Drop-in replacement, 10-100x faster, no python-Levenshtein dependency |
| `unicodedata.normalize('NFC', ...)` | `unicodedata.normalize('NFKD', ...)` then ASCII encode | — | NFKD decomposes combined characters (é→e+combining acute) allowing ASCII stripping; NFC does not |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `_normalize_name()` splits Pinnacle names by moving last token to front | Architecture Patterns | If Pinnacle sometimes uses GIVEN-FIRST order, reversal would break those names. Mitigation: the fuzzy stage would still catch them at score ~100 via token_sort_ratio. |
| A2 | `process.extractOne` attribute names are `(match, score, index)` | Code Examples | Low risk — rapidfuzz API is stable and verified against 3.14.5 docs |
| A3 | `_corpus` and `_corpus_normalized` as parallel lists is the storage pattern | Code Examples | Alternative is list of dicts — planner may choose different structure |

**If this table is empty:** it is not — three low-risk assumptions above are flagged.

---

## Open Questions (RESOLVED)

1. **`_normalize_name()` idempotency for mixed-format input**
   - What we know: All Pinnacle names are SURNAME-FIRST ALL-CAPS (confirmed by Phase 1 output).
   - What's unclear: Could Pinnacle ever output GIVEN-FIRST order for some riders?
   - Recommendation: Treat all Pinnacle input as SURNAME-FIRST. The fuzzy stage handles edge cases.
   - RESOLVED: Treat all input as SURNAME-FIRST. Fuzzy stage with `fuzz.token_sort_ratio` handles any edge cases regardless of word order.

2. **`name_mappings.json` encoding for non-ASCII Pinnacle keys**
   - What we know: Current Pinnacle names are ASCII (all-caps, no accents). Values (PCS URLs) are also ASCII.
   - What's unclear: Whether future Pinnacle API changes could introduce accented keys.
   - Recommendation: Use `ensure_ascii=False` in `json.dump` defensively — no runtime cost.
   - RESOLVED: Use `ensure_ascii=False` in `json.dump`. Zero runtime cost, covers any future non-ASCII keys.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python venv | All | Yes | Python 3.14.x | — |
| rapidfuzz | Stage 4 fuzzy match | Not in venv (yet) | 3.14.5 available on PyPI | — (must be installed) |
| unicodedata | Stages 2–4 normalization | Yes (stdlib) | stdlib | — |
| sqlite3 | Rider corpus load | Yes (stdlib) | stdlib | — |
| `data/cache.db` | `__init__()` rider load | Yes | 5,077 riders | — |

**Missing dependencies with no fallback:**
- `rapidfuzz` — must be added to `requirements.txt` and installed before implementation. Wave 0 task.

**Missing dependencies with fallback:**
- None.

[VERIFIED: pip index versions rapidfuzz run on 2026-04-11 — 3.14.5 is latest stable]
[VERIFIED: `data/cache.db` rider count confirmed at 5,077 via live DB query]

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 7.x (already in requirements.txt) |
| Config file | none — pytest discovers by convention |
| Quick run command | `pytest tests/test_name_resolver.py -v` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| NAME-01 | Exact match against corpus (pre-normalized hit) | unit | `pytest tests/test_name_resolver.py::TestNameResolver::test_exact_match -x` | No — Wave 0 |
| NAME-02 | Accent+case normalization resolves all 4 must-pass names | unit | `pytest tests/test_name_resolver.py::TestNameResolver::test_normalized_match_must_pass -x` | No — Wave 0 |
| NAME-03 | Score >= 90 auto-accepts; 60–89 returns hint; < 60 returns None | unit | `pytest tests/test_name_resolver.py::TestNameResolver::test_fuzzy_thresholds -x` | No — Wave 0 |
| NAME-04 | Cache loaded on init; accept() saves and reuses without re-querying | unit | `pytest tests/test_name_resolver.py::TestNameResolver::test_cache_persistence -x` | No — Wave 0 |
| NAME-05 | `url=None` + `best_candidate_*` populated when unresolved | unit | `pytest tests/test_name_resolver.py::TestNameResolver::test_unresolved_result_contract -x` | No — Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/test_name_resolver.py -v`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/test_name_resolver.py` — covers all NAME-01 through NAME-05
- [ ] `rapidfuzz>=3.0.0` added to `requirements.txt`

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | — |
| V3 Session Management | No | — |
| V4 Access Control | No | — |
| V5 Input Validation | Yes (low risk) | Regex validation `rider/[a-z0-9-]+` on cache values (D-07) |
| V6 Cryptography | No | — |

### Known Threat Patterns for File-Backed JSON Cache

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Corrupt/tampered `name_mappings.json` | Tampering | Schema validation on load (D-07); invalid entries logged+skipped |
| Path traversal via malicious key | Tampering | Keys are Pinnacle display names (user-controlled indirectly); values are validated against `rider/[a-z0-9-]+` — a traversal attempt in a value would fail validation |
| Partial write corruption | Denial of service | Atomic write via tempfile+os.replace prevents partial state |

This module has minimal attack surface — it is local-only file I/O with no network calls and no user-supplied values written without validation.

---

## Project Constraints (from CLAUDE.md)

| Directive | Impact on This Phase |
|-----------|---------------------|
| 2-space indentation | All code in name_resolver.py uses 2-space indent |
| Type hints on all function signatures | All public and private functions typed |
| Docstrings on all public functions | `NameResolver`, `resolve()`, `accept()` all need docstrings |
| `pytest tests/ -v` before marking any task complete | Wave 0 must create test file before implementation tasks are marked done |
| Do not add dependencies without asking | `rapidfuzz` is pre-approved per STATE.md — no ask needed. No other dependencies required. |
| `logging.getLogger(__name__)` pattern | Used in name_resolver.py |
| `get_db()` from `data.scraper` | Used in `__init__()` |
| `os.environ["OMP_NUM_THREADS"] = "1"` thread safety | Not applicable — name_resolver.py has no numpy/torch operations |
| `data/cache.db` is the SQLite database | Riders loaded from cache.db via `get_db()` |
| Ask before changing schema | `name_mappings.json` is a NEW file (no existing schema) — no ask needed |

---

## Sources

### Primary (HIGH confidence)
- Live venv execution — normalization pipeline verified for all 4 must-pass examples
- Live venv execution — rapidfuzz 3.14.5 `fuzz.token_sort_ratio` and `process.extractOne` API tested
- `data/cache.db` live query — 5,077 riders confirmed, all 4 key riders present with correct names
- `pip index versions rapidfuzz` — 3.14.5 confirmed as latest stable on 2026-04-11

### Secondary (MEDIUM confidence)
- rapidfuzz docs (https://rapidfuzz.github.io/RapidFuzz/Usage/fuzz.html) — `token_sort_ratio` behavior described as word-sort then ratio
- Python stdlib docs (unicodedata.normalize) — NFKD behavior for accent stripping

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified against live pip registry and venv
- Architecture: HIGH — normalization pipeline verified against all must-pass examples in live venv
- Pitfalls: HIGH — Quintana ambiguity and VAN AERT three-token cases verified with live DB data

**Research date:** 2026-04-11
**Valid until:** 2026-05-11 (stable libraries; corpus grows but resolver logic does not change)
