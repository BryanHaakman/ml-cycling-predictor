# Phase 1: Pinnacle API Discovery and Client - Context

**Gathered:** 2026-04-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Discover the Pinnacle internal API endpoint via Playwright browser inspection, document it in `docs/pinnacle-api-notes.md`, then implement `data/odds.py` — a client module that fetches today's cycling H2H markets using a session cookie, normalizes odds to decimal, raises `PinnacleAuthError` on auth failure, and appends a JSONL audit entry to `data/odds_log.jsonl` after every fetch (including empty fetches).

**The endpoint URL, required headers, sport/market IDs, and response schema are completely unknown before discovery.** No client code is written until `docs/pinnacle-api-notes.md` is reviewed and approved by the user.

</domain>

<decisions>
## Implementation Decisions

### Endpoint Discovery
- **D-01:** Claude drives discovery in-session using Playwright MCP tools — no manual browser inspection by the user, no separate discovery script.
- **D-02:** Discovery starts unauthenticated. If cycling H2H markets require auth to appear, Claude stops and asks the user for `PINNACLE_SESSION_COOKIE` before retrying.
- **D-03:** After discovery, Claude writes `docs/pinnacle-api-notes.md` (endpoint URL, required headers, sport/market IDs, odds format, full example response) and **stops for user review**. Client code in `data/odds.py` is not written until the user approves the notes.

### OddsMarket Dataclass
- **D-04:** `OddsMarket` is a `dataclass` (consistent with `KellyResult` in `models/predict.py`).
- **D-05:** Fields: `rider_a_name: str`, `rider_b_name: str`, `odds_a: float`, `odds_b: float`, `race_name: str`, `matchup_id: str`. No `start_time` — minimal footprint.
- **D-06:** `matchup_id` typed as `str` (safe before discovery confirms Pinnacle's actual ID format; cast to int in callers if needed).

### Odds Format
- **D-07:** `fetch_cycling_h2h_markets()` normalizes odds to decimal internally before returning. `OddsMarket.odds_a` and `odds_b` are always decimal — callers never see American odds.
- **D-08:** Conversion logic lives in `data/odds.py`. No conversion responsibility leaks to Phase 4 or the predictor.

### Audit Logging
- **D-09:** `data/odds_log.jsonl` records **post-normalization decimal odds** (not raw American).
- **D-10:** Empty fetches (no cycling markets available) still append a JSONL line with `"markets": []` plus fetch metadata (timestamp, status). The log is a complete run record.

### Empty Market Behavior
- **D-11:** `fetch_cycling_h2h_markets()` returns `[]` when no cycling H2H markets are available. It does **not** raise an exception for empty results — only `PinnacleAuthError` is raised (on auth failure).

### Client Interface
- **D-12:** Module-level functions, consistent with the `data/` package conventions (no class-based client). `fetch_cycling_h2h_markets()` is the primary public function.

### Claude's Discretion
- Session cookie is read from the `PINNACLE_SESSION_COOKIE` env var (already established convention — never committed).
- JSONL line structure for the audit log (beyond `markets` and timestamp) — Claude decides based on what Pinnacle's actual response reveals.
- Request timeout and retry behavior — follow the `data/scraper.py` pattern (60s timeout, exponential backoff on transient failures).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Requirements
- `.planning/REQUIREMENTS.md` §Odds Ingestion — ODDS-01, ODDS-02, ODDS-03 are the acceptance criteria for this phase

### Codebase Patterns
- `data/scraper.py` — module-level function pattern, env var reading, error handling (catch-and-log with graceful degradation), rate limiting, module docstring style
- `models/predict.py` — `KellyResult` dataclass (reference for `OddsMarket` dataclass style)
- `webapp/app.py` — `_require_localhost` and env var reading patterns

### Discovery Output (written during execution, must exist before client code)
- `docs/pinnacle-api-notes.md` — endpoint URL, headers, sport/market IDs, odds format, full example response. **This file does not exist yet — it is the first deliverable of Phase 1.**

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `data/scraper.py` `get_db()` — not directly used in this phase, but the module-level function pattern and env var handling are the templates to follow
- `cloudscraper` — already a dependency; may be useful for bypassing Cloudflare if Pinnacle's API is protected (check during discovery)

### Established Patterns
- Module-level functions with `_private` prefix for helpers (not class-based clients)
- Constants in `UPPER_SNAKE_CASE` at module top (e.g., `PINNACLE_API_URL`, `REQUEST_TIMEOUT`)
- `Optional[T]` return types signal graceful failure; exception raising reserved for explicit failure modes
- `logging.getLogger(__name__)` per module; `log.warning()` for recoverable problems

### Integration Points
- `data/odds.py` will be imported by Phase 4 (`webapp/app.py` endpoints)
- `data/odds_log.jsonl` is a new file — no existing schema to preserve
- `docs/pinnacle-api-notes.md` is a new file — will be the frozen contract for Phase 4's response schema

</code_context>

<specifics>
## Specific Ideas

- The discovery phase must confirm whether cycling H2H markets exist under Pinnacle's taxonomy before any client code is written — the roadmap identifies this as the highest-risk unknown in the entire milestone.
- `PinnacleAuthError` message must specify the `PINNACLE_SESSION_COOKIE` env var by name so the user knows exactly what to update.

</specifics>

<deferred>
## Deferred Ideas

- **Sortable batch prediction results** — user wants to sort batch H2H results by edge %, Kelly stake, win probability, or rider name after running predictions. Deferred to Phase 5 (Frontend Integration) where the batch UI lives.

</deferred>

---

*Phase: 01-pinnacle-api-discovery-and-client*
*Context gathered: 2026-04-11*
