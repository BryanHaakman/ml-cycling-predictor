# Research Summary: PaceIQ v1.0 — Pinnacle Preload

**Project:** PaceIQ v1.0 (Pinnacle Preload milestone)
**Domain:** Reverse-engineered internal API client + fuzzy name resolution + scraper-backed stage context, integrated into an existing Flask/SQLite/ML prediction app
**Researched:** 2026-04-11
**Confidence:** MEDIUM (stack and architecture are HIGH; Pinnacle endpoint viability is LOW until discovery step completes)

---

## Executive Summary

PaceIQ v1.0 adds a pre-fill layer to an already-functional batch prediction UI. The user clicks "Load from Pinnacle", the app fetches today's H2H cycling markets from Pinnacle's internal web API, maps the displayed rider names to PCS URLs in `cache.db`, pulls stage details via the `procyclingstats` lib, and populates the batch form ready for one-click prediction. Nothing in the ML inference path changes — this milestone is entirely data plumbing that feeds the existing `POST /api/predict/batch` endpoint. The recommended approach is a strict build-order: discover the Pinnacle endpoint first (the only true unknown), then build the name resolver and stage context fetcher independently in parallel, wire them together in Flask, then add the frontend.

The dominant risk is that Pinnacle's internal API endpoint structure is completely unknown until browser inspection is performed. Every other component can be built and tested in isolation with mocked data, but the Pinnacle client cannot be finalized until the real endpoint URL, required headers, and response schema are observed from a live browser session. A second systemic risk is name resolution accuracy: Pinnacle displays names in SURNAME-FIRST, ALL-CAPS format with ASCII-only rendering, which requires format normalization and accent stripping before fuzzy matching — if this is done wrong, mismatches are silently cached and corrupt future predictions. Both risks have clear mitigations and neither blocks starting work on the other components.

The net stack change for this milestone is minimal: one new production library (`rapidfuzz>=3.14.3`), one pin upgrade (`procyclingstats>=0.2.8`), and Playwright as a one-time dev discovery tool that never reaches the VPS. No new infrastructure, no schema changes to `cache.db`, and no ML code changes. The integration surface in `webapp/app.py` is narrow: two new routes and three new imports.

---

## Key Findings

### Recommended Stack

The existing stack (Python 3.11, Flask, SQLite WAL, XGBoost/sklearn, pandas, procyclingstats, requests, cloudscraper) handles all existing needs. Only two items change for this milestone.

**New or changed dependencies:**
- `rapidfuzz>=3.14.3` (NEW, production) — fuzzy name matching; C++ backed, no GPL issues, `token_sort_ratio` scorer is order-invariant and handles Pinnacle's SURNAME-FIRST format after lowercasing. Pin avoids yanked 3.14.4 release; 3.14.5 is the current stable.
- `procyclingstats>=0.2.8` (UPGRADE from `>=0.2.0`) — Stage class provides all fields needed by `build_feature_vector_manual`. 0.2.8 has HTML parser fixes that reduce silent parse failures.
- `playwright>=1.58.0` (DEV ONLY, not in `requirements.txt`) — one-time browser inspection to discover Pinnacle's internal API endpoint. After discovery it is not used again.
- `requests` (EXISTING) — sufficient for the Pinnacle HTTP client; no new dep needed.
- `unicodedata` stdlib (EXISTING) — handles NFC/NFKD normalization and diacritic stripping before fuzzy matching; no new dep needed.
- `json` stdlib (EXISTING) — handles `name_mappings.json` cache and `odds_log.jsonl` audit log; no new dep needed.

**Key constraint confirmed:** Pinnacle's official public API has been closed since July 23, 2025. The plan to call their internal web-frontend API via session cookie is viable but LOW confidence until a live browser session confirms the endpoint structure.

### Expected Features

The five feature groups have a hard linear dependency for testing (though Groups 2 and 3 can be developed in parallel):

**Must have (table stakes) — MVP cannot ship without these:**
- Pinnacle API client fetches cycling H2H markets, handles expired cookie with clear env-var-specific error, appends raw response to `data/odds_log.jsonl` (ODDS-01, ODDS-02, ODDS-03)
- Name resolver: exact DB match → unicode normalization → rapidfuzz fuzzy → persistent JSON cache; unresolved riders shown with manual search (NAME-01 through NAME-05)
- Stage context fetch via `procyclingstats` lib; graceful degradation on failure keeps manual fields available (STGE-01, STGE-02)
- `POST /api/pinnacle/load` endpoint wiring all three above; returns structured JSON with resolved/unresolved pairs separate (ODDS-01 integration)
- "Load from Pinnacle" button, race selector dropdown, auto-populated batch pairs; all fields remain individually editable (UI-01, UI-02, UI-03)

**Should have (second pass within the milestone, low risk if deferred):**
- `POST /api/pinnacle/refresh-odds` — re-fetches odds only without stage re-fetch (ODDS-04, UI-04). Workable substitute is a full re-load; cycling odds don't move much intraday.
- ODDS-02 audit log — good hygiene; add once load endpoint is confirmed working.
- "Loaded X minutes ago" freshness indicator — trivial, high UX value.
- Per-cell flash on odds refresh — makes changed values visible.

**Defer to v2+:**
- INTEL-01 through INTEL-04 (Daily Intelligence Pipeline) — Claude API qualitative research and email reports.
- BETLOG-01 — inline bet logging from prediction results.
- Startlist quality feature support in `build_feature_vector_manual` — the function currently zero-fills `diff_field_rank_quality`; adding startlist parameter is a separate improvement tracked in CONCERNS.md.

### Architecture Approach

The new components form a thin preprocessing pipeline that sits entirely in front of the existing inference path. The integration is additive: two new files in `data/`, two new files in a new `intelligence/` package, and two new routes appended to `webapp/app.py`. The existing ML inference chain (`models/predict.py` → `features/pipeline.py`) is untouched. The `race_params` dict that `build_feature_vector_manual` already accepts is the exact contract the stage context fetcher produces, making integration clean and well-defined.

**Major components and responsibilities:**
1. `data/odds.py` — Pinnacle API client; session-cookie auth via `PINNACLE_SESSION_COOKIE` env var; returns `list[OddsMarket]`; raises typed `PinnacleAuthError` on session expiry; appends to `data/odds_log.jsonl`
2. `data/name_resolver.py` — name-to-PCS-URL resolution; exact → normalize → rapidfuzz → `data/name_mappings.json` persistent cache; returns URL or None with per-match confidence score
3. `intelligence/stage_context.py` — race/stage context fetch via `procyclingstats`; maps Pinnacle race name to PCS URL via `cache.db` fuzzy lookup; returns `StageContext` dataclass or raises `StageContextUnavailable`
4. `intelligence/models.py` — shared dataclasses (`OddsMarket`, `StageContext`, `ResolvedMarket`, `ResolvedPair`); no logic, pure data shapes
5. `webapp/app.py` (modified) — two new routes (`/api/pinnacle/load`, `/api/pinnacle/refresh-odds`) after line 315; both wrapped with existing `_require_localhost` decorator
6. `webapp/templates/index.html` (modified) — "Load from Pinnacle" button, race selector, "Refresh Odds" button; JS state management with `data-source` attributes to protect manually-edited cells from refresh overwrites

**Data stores (new, both gitignored):**
- `data/name_mappings.json` — flat `{"Pinnacle Name": "rider/pcs-url"}` dict, owned by `name_resolver.py`
- `data/odds_log.jsonl` — append-only audit log, one JSON line per Pinnacle fetch, owned by `odds.py`

### Critical Pitfalls

1. **Pinnacle 200-with-HTML on session expiry** — The internal API returns HTTP 200 with an HTML login page (not 401/403) when the session cookie expires. Check `Content-Type: application/json` before JSON decode; on failure, inspect first 200 bytes and raise `PinnacleAuthError` with env var name. Never test session validity by status code alone.

2. **Pinnacle endpoint is completely unknown until browser discovery** — Do not write the client against guessed interfaces. Use Playwright to inspect `*.pinnacle.com/api` network traffic during a live cycling H2H browse session. Document the discovered URL, headers, sport ID, and a full example response in `docs/pinnacle-api-notes.md` before writing any production client code. Also confirm that cycling H2H "specials" markets actually exist under Pinnacle's taxonomy — if they don't, the feature is unviable.

3. **Pinnacle name format is SURNAME-FIRST, ALL-CAPS** — "VAN AERT Wout" vs PCS "Wout van Aert". This is systematic across every rider in every market. Apply `.lower()` and `token_sort_ratio` (order-invariant) before fuzzy matching. Set auto-accept threshold at 90 (not 85) to favour manual fallback over wrong auto-accept.

4. **Unicode normalization form mismatch (NFC vs NFD)** — RapidFuzz 3.0+ removed default preprocessing. Apply `unicodedata.normalize("NFKD", name)` + Mn-category filter on both Pinnacle names and PCS names before any comparison. Test with: Roglič, Bardet, van Aert, Quintana, Bernal, Kragh Andersen.

5. **Wrong fuzzy match silently cached forever** — `name_mappings.json` has no expiry and no schema validation on load. Validate each entry on load (key: non-empty string; value: matches `rider/[a-z0-9-]+`). Use a `threading.Lock()` for concurrent writes. Surface a "wrong?" correction link in the UI for resolved names.

6. **Stage URL construction fetches wrong stage silently** — `procyclingstats` requires a specific PCS URL (e.g., `race/tour-de-romandie/2026/stage-4`). A wrong URL either 404s or, worse, fetches the correct race but wrong stage year — producing subtly wrong features with no error. Cross-check fetched stage date against today's date; treat as a miss if off by more than 1 day and fall back to manual input.

7. **`diff_field_rank_quality` always 0.0 via preload path** — `build_feature_vector_manual` currently accepts no startlist parameter; the #3 most important feature group defaults to neutral. The preload path has startlist data available (all resolved rider URLs from the market). Explicitly decide in Phase 4 whether to add startlist support or document the silent accuracy gap. Do not ship without acknowledging this.

---

## Implications for Roadmap

Based on the dependency chain confirmed in both FEATURES.md and ARCHITECTURE.md, the natural phase structure is sequential (five phases, each depending on the prior), with Phases 2 and 3 parallelizable in practice:

### Phase 1: Pinnacle Endpoint Discovery and API Client
**Rationale:** The Pinnacle endpoint URL, required headers, sport ID, and response schema are completely unknown. No downstream code can be finalized without this. This is the only TRUE blocker in the milestone and must go first. The endpoint discovery step (Playwright browser inspection) is itself a non-trivial task that should be timebox-scoped.
**Delivers:** A working `data/odds.py` client that returns structured `OddsMarket` data from a live Pinnacle session, plus `intelligence/models.py` dataclasses, plus a documented endpoint reference in `docs/pinnacle-api-notes.md`.
**Addresses:** ODDS-01, ODDS-02, ODDS-03
**Avoids:** Pitfalls 1 and 2 (200-with-HTML auth failure; endpoint unknown until discovery)
**Research flag:** Needs discovery work before any implementation. Confirm cycling H2H markets exist under Pinnacle's taxonomy before committing to the design.

### Phase 2: Name Resolver
**Rationale:** Can be built and unit-tested independently using mocked Pinnacle name strings; does not need Phase 1 complete. However, integration testing (testing against real Pinnacle name formats) benefits from Phase 1 being done first. Parallel development with Phase 3 is viable.
**Delivers:** `data/name_resolver.py` with full exact → normalize → fuzzy → cache pipeline; `data/name_mappings.json` creation/save/validate logic; pre-seeded mappings for top-50 WT riders.
**Addresses:** NAME-01 through NAME-05
**Avoids:** Pitfalls 3, 4, 5 (wrong auto-accept; NFC/NFD mismatch; surname-first format)
**Research flag:** Standard string-matching pattern; no additional research needed. Threshold calibration (90 vs other values) should be validated empirically against a sample of real Pinnacle names from Phase 1.

### Phase 3: Stage Context Fetcher
**Rationale:** Fully independent of Phases 1 and 2 at the code level. Can be developed in parallel with Phase 2. The key spike is confirming that `procyclingstats` can fetch upcoming-race stage data (the lib is proven for historical stages; upcoming stage URL format needs verification in development).
**Delivers:** `intelligence/stage_context.py` with Pinnacle race name → PCS URL mapping (cache.db fuzzy lookup primary, hardcoded dict fallback) → `procyclingstats.Stage` fetch → `StageContext` dataclass; graceful degradation when PCS is unavailable.
**Addresses:** STGE-01, STGE-02
**Avoids:** Pitfall 6 (wrong stage fetched silently); Pitfall 7 (Flask thread blocking — set 3–5 second total timeout)
**Research flag:** One spike needed: confirm `procyclingstats` Stage class works with upcoming (not yet completed) race URLs. If it does not, the fallback is cache.db historical stage data for races already in the DB.

### Phase 4: Flask Endpoint Wiring
**Rationale:** Integration phase. Requires Phases 1–3 complete. Primarily orchestration code — call the client, resolver, stage fetcher, assemble `ResolvedMarket` response. The most important design decision here is agreeing on the final JSON response schema before the frontend is built, since the frontend has no flexibility once the schema is committed.
**Delivers:** `POST /api/pinnacle/load` and `POST /api/pinnacle/refresh-odds` routes in `webapp/app.py`; verified curl/httpie test against real Pinnacle data; explicit decision on startlist parameter for `build_feature_vector_manual` (add or document as gap).
**Addresses:** ODDS-04 (refresh endpoint); full integration of ODDS-01 through STGE-02
**Avoids:** Pitfall 7 (thread blocking — use `threaded=True`, separate rate limiter instance from scraper); Pitfall 8 (env var absent on startup — read at request time, not import time); Pitfall 10 (startlist neutral defaults — acknowledge or fix)
**Research flag:** Standard Flask orchestration; no additional research needed.

### Phase 5: Frontend Integration
**Rationale:** Final layer. Requires Phase 4 endpoints returning the correct shape. The JavaScript state management (tracking auto-populated vs user-edited cells so "Refresh Odds" does not overwrite manual changes) is the most complex part. The existing `index.html` is a single ~1200-line file — identify natural extraction points before adding significant new JS.
**Delivers:** "Load from Pinnacle" button, race selector dropdown, auto-populated batch pairs with resolved/unresolved handling, "Refresh Odds" button with odds-only update behavior; all fields individually editable; cookie error banner inline.
**Addresses:** UI-01 through UI-04
**Avoids:** Pitfall 13 (duplicate races in selector — normalize race names before deduplication); Pitfall 3 (wrong rider shown — surface "wrong?" correction link for resolved names)
**Research flag:** Standard Flask/JS pattern. The `data-source` attribute approach for protecting user-edited cells is a minor pattern decision that should be settled before writing the JS.

### Phase Ordering Rationale

- Phase 1 must be first because the endpoint is unknown and all integration testing depends on real data shapes.
- Phases 2 and 3 are ordered after Phase 1 for integration testing confidence, but their core logic can be developed in parallel using mocked Pinnacle data from day one.
- Phase 4 cannot start until Phases 1–3 are individually verified; it is purely integration work.
- Phase 5 cannot start until Phase 4 endpoints return the correct shape; the frontend has no way to develop against a contract that doesn't exist yet (unless an explicit mock endpoint is built in Phase 4).
- The MVP can drop `POST /api/pinnacle/refresh-odds` (ODDS-04, UI-04) to ship sooner — a full reload is an acceptable substitute.

### Research Flags

**Needs deeper work during planning/execution:**
- **Phase 1 (Pinnacle Discovery):** The endpoint structure is completely unknown. Allocate explicit timebox for Playwright discovery work. If the endpoint is obfuscated (e.g., requires non-reproducible tokens, uses WebSockets instead of REST, or cycling H2H markets do not exist), the entire feature approach needs to pivot. Confirm viability before writing any client code.
- **Phase 3 (Stage Context) spike:** Confirm `procyclingstats` Stage class works for upcoming races whose results pages don't yet exist on PCS. If not, the fallback path (cache.db lookup for races already scraped) becomes the primary path.

**Standard patterns (no additional research needed):**
- **Phase 2 (Name Resolver):** Fuzzy string matching with rapidfuzz is a well-documented, tested pattern. The implementation is straightforward once the Pinnacle name format is confirmed from Phase 1.
- **Phase 4 (Flask Wiring):** Adding routes with an existing decorator pattern to an existing Flask app is standard. The `_require_localhost` decorator, response shape design, and error handling patterns are all well-understood.
- **Phase 5 (Frontend):** The existing UI already does dynamic pair rows, autocomplete, and stage field population. Extending this pattern rather than rewriting is the right approach.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | rapidfuzz and procyclingstats verified on PyPI; requests/unicodedata stdlib confirmed sufficient; playwright is dev-only and well-supported |
| Features | HIGH | Dependency order and table-stakes vs nice-to-have grounded in direct codebase audit (`build_feature_vector_manual` contract confirmed at `features/pipeline.py:225`) |
| Architecture | HIGH | Based on direct code read of `webapp/app.py`, `features/pipeline.py`, `models/predict.py`; integration points confirmed at line numbers |
| Pitfalls | HIGH | Grounded in codebase audit (CONCERNS.md, actual function signatures) + confirmed library behaviour (rapidfuzz 3.0 preprocessing removal, SQLite WAL) |
| Pinnacle API viability | LOW | Official API closed July 2025; internal web API approach is reasonable but unverified without a live session; cycling H2H market availability unconfirmed |

**Overall confidence:** MEDIUM — all technical components are well-understood; the single LOW-confidence item (Pinnacle endpoint) is the project's make-or-break risk.

### Gaps to Address

- **Pinnacle endpoint URL, headers, sport ID, response schema:** Unknown until Phase 1 Playwright discovery. The entire feature is at risk until this is confirmed. Do not build the client against assumptions.
- **Cycling H2H market availability on Pinnacle:** Pinnacle may offer cycling as outright winner markets only (not H2H specials). Confirm during browser inspection before any other work.
- **Odds format (decimal vs American):** The internal API may return American odds (`-130 / +110`) rather than European decimal. The existing `kelly_criterion()` expects decimal. Determine format during discovery; write a converter and assert `1.01 <= decimal_odds <= 20.0` before passing to Kelly.
- **`procyclingstats` upcoming race support:** Confirm the Stage class can fetch data for races whose results page is not yet populated on PCS. If not, the cache.db lookup path becomes primary with `procyclingstats` as a fallback only for races not yet scraped.
- **`build_feature_vector_manual` startlist parameter:** The #3 most important feature group (`diff_field_rank_quality`) is always neutral via the preload path. Decide explicitly in Phase 4: add startlist parameter to `build_feature_vector_manual` (correct fix), or document as a known accuracy gap and defer to a later milestone.
- **rapidfuzz threshold calibration:** The 90 auto-accept threshold is a starting point. After Phase 1 produces real Pinnacle name samples, validate the threshold against those names before Phase 2 ships.

---

## Sources

### Primary (HIGH confidence)
- Codebase: `features/pipeline.py:225` — `build_feature_vector_manual` signature and `race_params` dict contract confirmed by direct read
- Codebase: `webapp/app.py:34, 226, 315` — `_require_localhost` decorator, `api_predict_batch` contract, insertion point for new routes confirmed by direct read
- Codebase: `data/scraper.py` — `_rate_limit()` global state and `REQUEST_DELAY=0.5s` confirmed
- Codebase: `.planning/codebase/CONCERNS.md` — startlist missing from `build_feature_vector_manual`, interaction feature duplication confirmed
- [rapidfuzz PyPI](https://pypi.org/project/rapidfuzz/) — 3.14.3 stable, 3.14.4 yanked, 3.14.5 current
- [playwright PyPI](https://pypi.org/project/playwright/) — 1.58.0 stable, Ubuntu 24.04 supported
- [procyclingstats PyPI](https://pypi.org/project/procyclingstats/) — 0.2.8 current; Stage class fields confirmed from GitHub source
- [RapidFuzz GitHub](https://github.com/rapidfuzz/RapidFuzz) — preprocessing removed by default in 3.0.0 (breaking change)
- [Python unicodedata docs](https://docs.python.org/3/library/unicodedata.html) — NFKD normalization + Mn-category filter

### Secondary (MEDIUM confidence)
- [procyclingstats GitHub](https://github.com/themm1/procyclingstats) — `ExpectedParsingError` ignored by default; Stage class source confirmed
- [Playwright Python Network docs](https://playwright.dev/python/docs/network) — network interception API for endpoint discovery
- [SQLite WAL concurrency](https://oldmoe.blog/2024/07/08/the-write-stuff-concurrent-write-transactions-in-sqlite/) — `SQLITE_BUSY` / busy_timeout behavior confirmed

### Tertiary (LOW confidence)
- [Arbusers thread](https://arbusers.com/access-to-pinnacle-api-closed-since-july-23rd-2025-t10682/) — Pinnacle official API closed July 23, 2025; page returned 403 during research but finding confirmed by multiple corroborating sources
- Internal Pinnacle web API viability — reasonable inference from standard browser-session cookie pattern; unverified without live access

---

*Research completed: 2026-04-11*
*Ready for roadmap: yes*
