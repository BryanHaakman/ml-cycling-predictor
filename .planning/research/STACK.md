# Technology Stack: PaceIQ v1.0 — Pinnacle Preload

**Project:** PaceIQ v1.0 (Pinnacle Preload milestone)
**Researched:** 2026-04-11
**Scope:** New dependencies only — existing stack (Python 3.11, Flask, SQLite WAL, XGBoost, sklearn, PyTorch, pandas, numpy, requests, cloudscraper, procyclingstats) is validated and not re-researched here.

---

## New Libraries Required

### Core Additions

| Library | Version | Purpose | Why Chosen |
|---------|---------|---------|------------|
| `rapidfuzz` | `>=3.14.3` | Fuzzy name resolution: Pinnacle display names → PCS rider URLs | Pre-approved in plan. C++ backed, 10–100x faster than fuzzywuzzy, no external dependencies. `WRatio` scorer handles abbreviations and reordered names well. stdlib `unicodedata` (no new dep) handles accent normalization before fuzzy pass. |
| `playwright` | `>=1.58.0` | One-time API endpoint discovery: capture Pinnacle's internal XHR calls while navigating the site in a headed browser | Only viable tool for intercepting authenticated browser sessions. Network interception via `page.on("request")`/`page.on("response")` captures full headers + cookies. After endpoint is discovered and documented, production code uses `requests` only — Playwright is a dev/discovery tool, not a runtime dependency. |

### No New Library Required

| Need | Resolution | Reason |
|------|-----------|--------|
| Pinnacle API HTTP client | Use existing `requests` (already in requirements.txt) | `requests.Session()` with a `Cookie` header is sufficient for hitting a known internal REST endpoint. httpx offers no benefit here — the Pinnacle call is a single synchronous request, not concurrent. Adding httpx would be a new dependency for zero gain. |
| Unicode accent normalization | Use stdlib `unicodedata` (no new dep) | `unicodedata.normalize("NFKD", name)` + filter `Mn` category covers all cycling name variants (é→e, ñ→n, ü→u). Standard library, zero cost. |
| Stage context fetch | Use existing `procyclingstats` (already in requirements.txt, pinned `>=0.2.0`) | `Stage` class provides `distance()`, `vertical_meters()`, `profile_icon()`, `stage_type()`, `climbs()`, `date()`. Covers all fields in STGE-01. Latest version is 0.2.8 (March 2026). No new dep needed — upgrade pin to `>=0.2.8` to get latest fixes. |
| Name mapping persistence | Use stdlib `json` + flat file `data/name_mappings.json` (no new dep) | NAME-04 requires persistent cache. A JSON file read/written with stdlib json is sufficient — no database schema change, no ORM, no new library. |
| Odds audit log | Use stdlib `json` with append-write to `data/odds_log.jsonl` (no new dep) | ODDS-02 requires append-only audit log. JSONL (newline-delimited JSON) written with stdlib is the simplest compliant implementation. |

---

## Library Detail

### rapidfuzz `>=3.14.3`

**Current stable release:** 3.14.3 (November 2025). 3.14.4 and 3.14.5 were both published April 7, 2026 but 3.14.4 was yanked (broken CI). Pin to `>=3.14.3` to avoid the yanked release and pick up 3.14.5 or later.

**Key API for name resolution pipeline:**
```python
from rapidfuzz import process, fuzz

# Normalize first (stdlib, no dep)
import unicodedata
def normalize(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").lower().strip()

# Fuzzy match against known PCS names
match, score, _ = process.extractOne(
    query=normalize(pinnacle_name),
    choices=normalize_all(pcs_names),
    scorer=fuzz.WRatio,
)
# Auto-accept if score >= 85 (tune in practice)
```

**Why WRatio over token_sort_ratio:** WRatio combines multiple scorers and handles partial matches (e.g., "van der Poel" vs "Van der Poel M.") better than any single scorer. Token sort handles reordered name components automatically.

**Confidence threshold:** 85 is a reasonable starting point. Should be validated against a small labeled set of Pinnacle→PCS name pairs before shipping NAME-03.

---

### playwright `>=1.58.0`

**Current stable release:** 1.58.0 (January 30, 2026). Supports Python 3.9–3.13. Ubuntu 24.04 is officially supported.

**Usage scope:** Discovery only — not a runtime dependency of the Flask app.

**Install pattern for Ubuntu 24.04 VPS (one-time dev task):**
```bash
pip install playwright
playwright install chromium  # downloads ~120MB Chromium binary
```

**Network interception pattern for endpoint discovery:**
```python
from playwright.sync_api import sync_playwright

def discover_pinnacle_endpoint():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        captured = []
        page.on("response", lambda r: captured.append({
            "url": r.url,
            "status": r.status,
            "headers": dict(r.headers),
        }) if "pinnacle.com/api" in r.url else None)

        page.goto("https://www.pinnacle.com/en/cycling/matchups/")
        page.wait_for_timeout(5000)  # let XHR fire
        browser.close()
    return captured
```

Goal: identify the exact `/api/...` path, required headers, and cookie name. Once identified, hard-code the endpoint URL in `pinnacle_client.py` and drop Playwright from the active code path.

**Important:** Playwright is a dev/tooling dep. Add to a `[dev]` extras section or document separately — do not add to the main `requirements.txt` that runs on the VPS production path if it isn't needed there.

---

### procyclingstats (upgrade pin from `>=0.2.0` to `>=0.2.8`)

**Current stable release:** 0.2.8 (March 1, 2026). Already installed; only the pin needs updating.

**Stage fields available (confirmed from source):**

| Field | Method | Return type | Notes |
|-------|--------|-------------|-------|
| Distance | `distance()` | `float` | km |
| Elevation gain | `vertical_meters()` | `Optional[int]` | May be None for flat stages |
| Profile difficulty | `profile_icon()` | `Literal["p0"–"p5"]` | p0=flat, p5=very mountainous |
| Stage type | `stage_type()` | `Literal["ITT","TTT","RR"]` | Individual TT, Team TT, Road Race |
| Climbs | `climbs()` | `List[Dict]` | Categorized climbs with metadata |
| Date | `date()` | `str` | YYYY-MM-DD |
| How won | `won_how()` | `str` | e.g., "Sprint of small group" |

**Gap:** No direct `race_tier` method on `Stage`. Race tier (1.UWT, 2.UWT etc.) is available via the `Race` class (`race_scraper.py`) using the race URL. The implementation will need to construct the parent race URL from the stage URL and call `Race` separately, or accept tier as a manual input fallback per STGE-02.

**Fragility note:** procyclingstats parses HTML from procyclingstats.com. PCS layout changes have broken the library before (issue #56 in the repo). STGE-02 (graceful degradation) is the right mitigation — wrap all `Stage` calls in try/except and fall back to manual input fields.

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Fuzzy matching | rapidfuzz | fuzzywuzzy | fuzzywuzzy is a wrapper around python-Levenshtein; rapidfuzz is its C++ successor, 10–100x faster, same API, no GPL concerns |
| Fuzzy matching | rapidfuzz | thefuzz | thefuzz is the renamed fuzzywuzzy; same wrapper, same slowness |
| HTTP client (Pinnacle) | requests (existing) | httpx | httpx adds HTTP/2 and async, neither of which matters for a single synchronous cookie-auth request to a known endpoint; avoids new dependency |
| Accent normalization | stdlib unicodedata | unidecode | unidecode is a third-party transliteration library; unicodedata NFKD+Mn-filter achieves the same result for European names with zero new dependencies |
| Browser automation (discovery) | playwright | selenium | Playwright has a cleaner Python API, better network interception primitives, faster execution; selenium requires geckodriver/chromedriver separately |
| Browser automation (discovery) | playwright | puppeteer | puppeteer is Node.js only; this is a Python project |
| Stage context | procyclingstats (existing) | MCP server (procyclingstats-mcp-server) | MCP server is in-session only, not available on VPS; procyclingstats lib is self-contained |

---

## Updated requirements.txt Changes

```
# Upgrade existing pin:
procyclingstats>=0.2.8   # was >=0.2.0; 0.2.8 has HTML parser fixes

# New production dependency:
rapidfuzz>=3.14.3

# Dev/discovery only (document separately, NOT in requirements.txt):
# playwright>=1.58.0
# After install: playwright install chromium
```

---

## Integration Notes

**Existing Flask app integration:**
- `POST /api/pinnacle/load` and `POST /api/pinnacle/refresh-odds` call a new `pinnacle_client.py` module that uses `requests.Session` with a cookie header sourced from `os.environ["PINNACLE_SESSION_COOKIE"]`.
- Name resolver lives in a new `data/name_resolver.py` module. Reads `cache.db` riders table for exact match, applies `unicodedata` normalization, then calls `rapidfuzz.process.extractOne`. Writes confirmed mappings to `data/name_mappings.json`.
- Stage context fetch lives in a new `data/stage_context.py` module. Constructs a PCS stage URL from Pinnacle race/stage name (fuzzy-matched), instantiates `procyclingstats.Stage`, returns a dict of stage fields. Wraps all calls in try/except per STGE-02.
- All new routes protected by existing `_require_localhost` decorator.
- Thread safety: new modules do not use numpy/PyTorch, so `OMP_NUM_THREADS` concern does not apply to them directly.

**Pinnacle API status note:** Pinnacle's official public API was closed to general access July 23, 2025. The plan to use their internal web API (session cookie approach hitting their frontend's XHR endpoints) remains viable — it is the same technique used by their web app. The session cookie authenticates as the logged-in user. This is distinct from the defunct partner API. Playwright is the right tool to identify the exact endpoint URL during development.

---

## Confidence Assessment

| Area | Confidence | Basis |
|------|------------|-------|
| rapidfuzz version | HIGH | PyPI verified (3.14.3 stable, 3.14.5 latest as of April 7 2026) |
| playwright version | HIGH | PyPI verified (1.58.0, January 2026) |
| procyclingstats Stage fields | MEDIUM | Source file inspected via GitHub; 0.2.8 confirmed on PyPI |
| requests sufficient for Pinnacle | MEDIUM | Standard pattern for cookie-auth XHR; no Pinnacle-specific verification possible without live cookie |
| unicodedata sufficient for names | HIGH | Standard library, well-understood NFKD decomposition covers all European cycling name variants |
| Pinnacle internal API viability | LOW | Pinnacle official API closed July 2025; internal web API approach is reasonable but unverified without live access |

---

## Sources

- [rapidfuzz PyPI](https://pypi.org/project/rapidfuzz/) — version 3.14.3/3.14.5
- [playwright PyPI](https://pypi.org/project/playwright/) — version 1.58.0
- [Playwright Python docs — Installation](https://playwright.dev/python/docs/intro) — Ubuntu 24.04 support
- [Playwright Python docs — Network](https://playwright.dev/python/docs/network) — network interception API
- [procyclingstats PyPI](https://pypi.org/project/procyclingstats/) — version 0.2.8
- [procyclingstats GitHub](https://github.com/themm1/procyclingstats) — Stage class source
- [Pinnacle API shutdown — Arbusers thread](https://arbusers.com/access-to-pinnacle-api-closed-since-july-23rd-2025-t10682/) — official API closed July 23, 2025
- [httpx PyPI](https://pypi.org/project/httpx/) — version 0.28.1 (stable); not chosen
- [Python unicodedata docs](https://docs.python.org/3/library/unicodedata.html) — NFKD normalization
