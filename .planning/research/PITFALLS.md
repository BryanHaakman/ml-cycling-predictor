# Domain Pitfalls: PaceIQ v1.0 Pinnacle Preload

**Domain:** Reverse-engineered internal API integration + fuzzy name resolution + scraper-based stage context wired into an existing Flask/ML pipeline
**Researched:** 2026-04-11
**Overall confidence:** HIGH (pitfalls grounded in actual codebase + confirmed library behaviour)

---

## Quick Reference Table

| Risk | Likelihood | Impact | Phase |
|------|-----------|--------|-------|
| Pinnacle internal endpoint structure is unknown until discovery | HIGH | CRITICAL | API Discovery |
| Session cookie expiry not caught; returns 200 with HTML login page | HIGH | HIGH | API Discovery |
| Pinnacle API closed to public since July 2025; internal endpoint also undocumented | HIGH | HIGH | API Discovery |
| Name resolver auto-accepts wrong fuzzy match above threshold | HIGH | HIGH | Name Resolution |
| Unicode normalization form mismatch (NFC vs NFD) before fuzzy matching | HIGH | MEDIUM | Name Resolution |
| `name_mappings.json` cache persists a wrong mapping indefinitely | MEDIUM | HIGH | Name Resolution |
| Pinnacle name order: "Van Aert Wout" vs PCS "Wout van Aert"; surnames first | HIGH | HIGH | Name Resolution |
| Stage URL construction from display name fails on multi-stage race name variants | HIGH | HIGH | Stage Context |
| `procyclingstats` lib raises `ExpectedParsingError` silently by default | MEDIUM | MEDIUM | Stage Context |
| Stage context fetch blocks Flask request thread for up to 3s per PCS call | MEDIUM | HIGH | Stage Context |
| `build_feature_vector_manual` startlist features always neutral (no startlist passed from preload) | HIGH | MEDIUM | Prediction Integration |
| Feature vector column mismatch: preload path uses `predict_manual`, not `predict` | MEDIUM | HIGH | Prediction Integration |
| `fv.get(name, 0.0)` silently fills missing columns with zero; no mismatch warning | HIGH | MEDIUM | Prediction Integration |
| SQLite `SQLITE_BUSY` during concurrent Pinnacle load + active web request | LOW | MEDIUM | Flask Integration |
| Odds log `data/odds_log.jsonl` not flushed before process death on exception | MEDIUM | MEDIUM | Odds Ingestion |
| `PINNACLE_SESSION_COOKIE` env var not present on startup; Flask crashes or silently skips | MEDIUM | HIGH | Flask Integration |
| Pinnacle H2H market IDs are numeric; cycling sport ID is undocumented | HIGH | HIGH | API Discovery |

---

## Critical Pitfalls

Mistakes that require rewrites or silently corrupt results.

### Pitfall 1: Pinnacle Session Cookie Returns 200 with Login HTML, Not 401

**What goes wrong:** When a Pinnacle session cookie expires, the internal web-facing API does not return HTTP 401 or 403. It redirects to a login page and returns HTTP 200 with HTML. Code that only checks `response.status_code == 200` will parse the HTML body as if it were a valid JSON odds response — silently returning an empty market list or crashing on JSON decode.

**Why it happens:** Pinnacle's frontend API is not a REST API in the conventional sense. It is the same endpoint the browser calls, and browsers handle session expiry via page redirects, not HTTP error codes.

**Consequences:** The `/api/pinnacle/load` endpoint appears to succeed (returns 200), the UI receives an empty or malformed result, and the user has no indication that their session cookie is stale. ODDS-03 (clear error with env var name) is violated silently.

**Prevention:**
- After every request, check `Content-Type: application/json` before attempting JSON decode.
- Explicitly check response body for the presence of expected JSON keys (e.g., `"markets"` or the cycling sport ID key).
- Wrap JSON decode in a try/except; on failure, inspect first 200 chars of response body and raise a typed `PinnacleAuthError` with the env var name in the message.
- Do not retry on auth failure — surface immediately.

**Detection:** Log the first 200 bytes of any non-JSON response at WARNING level. In testing, exercise expired-cookie path explicitly.

---

### Pitfall 2: Pinnacle Internal Endpoint Structure Is Unknown Until Browser Discovery

**What goes wrong:** Pinnacle's public REST API (`api.pinnacle.com`) has been closed to new users since July 23rd, 2025. The internal web-frontend endpoint used by `www.pinnacle.com` is undocumented, has no published contract, and its URL structure, sport IDs, market IDs, and parameter names must be discovered by inspecting browser network traffic with Playwright or DevTools. If implementation begins before this discovery step, all downstream code is written against a guessed interface that may be completely wrong.

**Why it happens:** The PROJECT.md notes "Endpoint needs to be discovered via Playwright browser inspection — this is in scope for v1.0." This is a first-class unknown, not a minor detail. The cycling sport ID, H2H market type identifier, response schema, and required headers are all unknown until the discovery step is complete.

**Consequences:** If the endpoint structure is assumed (e.g., copied from the now-closed public API docs), every call will fail. If the endpoint uses WebSocket push rather than REST polling, the entire client architecture needs to change. If cycling is not a supported H2H market type, the whole feature is unviable.

**Prevention:**
- Make API discovery the first task in Phase 1. Do not write the client until the actual endpoint, response schema, required headers, and sport/market ID values are confirmed from a live browser session.
- Document the discovered endpoint URL, required headers, response shape, and at least one full example response in `docs/pinnacle-api-notes.md` before writing any production code.
- Confirm that cycling H2H (not just moneyline/winner) markets are available — "cycling" may only have outright winner markets, not H2H specials.

**Detection:** Playwright script that logs all `api.*.pinnacle.com` or `*.pinnacle.com/api` network requests during a session browsing to a cycling H2H market.

---

### Pitfall 3: Fuzzy Match Auto-Accepts Wrong Rider at High Threshold

**What goes wrong:** rapidfuzz `WRatio` or `token_sort_ratio` at a threshold like 85 will confidently match "Mathieu van der Poel" to "Mathieu van der Pol" (a different, hypothetical rider), or match "Tom Pidcock" to "Tom Pickford" above threshold if the PCS name database has a similarly-spelled entry. Once auto-accepted, the wrong PCS URL is cached in `name_mappings.json` and silently used for all future predictions for that matchup.

**Why it happens:** Fuzzy matching is probabilistic. A threshold that works for most names can fail on pairs that share a long common prefix or are genuinely similar. The persistent cache (`name_mappings.json`) has no expiry and no correction mechanism once written.

**Consequences:** Predictions for the mismatched rider use entirely wrong historical features — effectively random noise fed into the model. The Kelly staking will size bets on fabricated probabilities. This is a financial accuracy bug.

**Prevention:**
- Set the auto-accept threshold conservatively (90+, not 80). Prefer false negatives (falls back to manual search, NAME-05) over false positives (silently wrong).
- Log every fuzzy match with the score, the Pinnacle name, and the matched PCS name. Never silently accept — always write to log even when auto-accepting.
- Allow the user to invalidate a cache entry from the UI (e.g., a small "wrong?" link next to a resolved name). Without this, wrong mappings are permanent.
- Consider requiring the matched PCS name's nationality to be consistent with the Pinnacle market context (e.g., a French race is likely to have French/Belgian/Spanish riders).

**Detection:** Review the match log after the first live run. Flag any match scoring between 85–95 for manual review.

---

### Pitfall 4: Unicode Normalization Form Mismatch Before Fuzzy Matching

**What goes wrong:** A Pinnacle display name like "Romain Bardet" may be stored as NFC Unicode (single precomposed character `é`) while the PCS database stores it as NFD (base `e` + combining accent `\u0301`). These strings are visually identical but byte-different. Exact match will fail, and rapidfuzz will treat the strings as having edit distance > 0 even though they are semantically the same name.

**Why it happens:** From RapidFuzz 3.0.0, strings are no longer preprocessed by default (no lowercasing, no non-alphanumeric stripping, no Unicode normalization). This is a documented breaking change. If the normalization step is missing, accent-folding that appears to work on some names will silently fail on others depending on which Unicode form each source uses.

**Consequences:** NAME-02 (accent normalization before fuzzy) is implemented but ineffective. Riders like "Alejandro Valverde", "Nairo Quintana", "Primoz Roglic" will fail exact and fuzzy match, falling through to manual search even when correct matches exist.

**Prevention:**
- Apply `unicodedata.normalize("NFC", name)` AND `unicodedata.normalize("NFKD", name)` followed by ASCII-only encode/decode (diacritic stripping) as separate pre-pass before rapidfuzz.
- Normalize both the Pinnacle name and the PCS name in the same way before any comparison.
- Test the normalization layer explicitly with a fixture set: "Romain Bardet", "Primož Roglič", "Wout van Aert", "Søren Kragh Andersen", "Egan Bernal".

**Detection:** Unit test with names containing `ž`, `č`, `ø`, `ñ`, and `ú` from both NFC and NFD sources.

---

### Pitfall 5: Pinnacle Name Order is Surname-First, PCS is Given-First

**What goes wrong:** Pinnacle displays rider names in `SURNAME Firstname` format (e.g., "VAN AERT Wout", "POGACAR Tadej"). PCS stores them as `Wout van Aert`, `Tadej Pogacar`. Fuzzy matching `VAN AERT Wout` against `Wout van Aert` will score lower than expected because token order differs. `WRatio` or `token_sort_ratio` handles this better than `ratio`, but all-caps surnames further reduce scores.

**Why it happens:** Pinnacle follows a common betting display convention (surname-first, surname in caps). PCS uses natural Western name order. The difference is systematic and affects every single rider in every market.

**Consequences:** Fuzzy scores for all riders are depressed by 5–15 points compared to what they would be if names were in the same format. This pushes many correct matches below auto-accept threshold, causing unnecessary fallback to manual search (acceptable) or, worse, matching to a different rider whose name happens to score higher in the wrong order.

**Prevention:**
- Before fuzzy matching, normalize Pinnacle names: lowercase, then try both `{firstname} {surname}` and `{surname} {firstname}` tokenizations. Match against PCS names in both orderings and take the max score.
- Use `rapidfuzz.fuzz.token_sort_ratio` as the primary scorer, which is order-invariant, not `fuzz.ratio`.
- Strip all-caps formatting from Pinnacle names before comparison: `name.title()` or explicit `.lower()`.

**Detection:** Test with 10 real Pinnacle cycling names from a live browser session. Measure score before and after normalization.

---

## Moderate Pitfalls

### Pitfall 6: Stage URL Construction From Pinnacle Race Name Is Fragile

**What goes wrong:** Pinnacle displays race names like "Tour de Romandie - Stage 4" or "Liege-Bastogne-Liege". These must be converted to PCS stage URLs like `race/tour-de-romandie/2026/stage-4` or `race/liege-bastogne-liege/2026`. The mapping is not obvious: hyphens vs spaces, accent removal, year injection, stage number format (`stage-4` vs `etape-4`), and one-day races having no stage suffix.

**Why it happens:** There is no canonical mapping API. The conversion requires slug generation (lowercase, replace spaces with hyphens, strip accents, remove punctuation), year injection from context (today's date), and stage type detection (one-day vs stage race). Each of these steps can fail independently.

**Consequences:** `procyclingstats` Stage class raises `ValueError` or `ExpectedParsingError` on a bad URL. If the URL is almost-right (e.g., wrong year, wrong stage number), it fetches the wrong stage's data — different distance, profile, and elevation — producing subtly wrong feature vectors with no error raised.

**Prevention:**
- Build a slug-generation function and test it against a fixture set of 20 known Pinnacle names and their correct PCS URLs before the live integration.
- After constructing the URL, verify it fetches the correct stage by cross-checking the stage date against today's date. If the dates don't match within ±1 day, treat as a miss and fall back to manual input.
- The `procyclingstats` Stage class accepts the relative URL (e.g., `race/tour-de-romandie/2026/stage-4`). Never construct the full absolute URL — the lib prepends the domain internally.

**Detection:** Log the constructed URL and the fetched stage date on every call. Alert if fetched date differs from expected.

---

### Pitfall 7: `procyclingstats` Stage Fetch Blocks the Flask Request Thread

**What goes wrong:** The `procyclingstats` lib makes synchronous HTTP requests to PCS. With the 0.5s rate limiter enforced globally via `_rate_limit()` in `data/scraper.py`, and potentially 3 retries per stage, a single stage context fetch can block the Flask thread for 1.5–4.5 seconds. Flask's default development server is single-threaded. The user clicks "Load from Pinnacle", the browser shows a spinner, and Flask is completely blocked — including any concurrent requests (e.g., the user clicking something else).

**Why it happens:** The `_rate_limit()` global state in `data/scraper.py` is not aware of the new stage-context fetch path. If the user triggers a Pinnacle load while a background scrape is happening, the rate limiter will serialize both, making the load much slower. The Flask dev server runs in a single thread by default.

**Consequences:** Perceived hang of 3–10 seconds on "Load from Pinnacle" click. If `threaded=True` is not set on `app.run()`, all other routes are blocked during the fetch.

**Prevention:**
- Run the Flask app with `threaded=True` (already needed for the SSE streaming admin endpoints). Confirm this is set.
- Do not share the global `_rate_limit()` state between the scraper and the new stage-context client. Use a separate rate limiter instance for the preload path to avoid contention with background scrapes.
- Set a tight timeout on the stage context fetch (3–5 seconds total, not per retry). If it times out, return a partial result with manual fields empty and STGE-02 degradation.
- Consider returning from `/api/pinnacle/load` quickly with the Pinnacle odds and resolving stage context asynchronously — but only if the UI can handle a two-phase load.

**Detection:** Time the `/api/pinnacle/load` endpoint end-to-end. Flag if > 5 seconds.

---

### Pitfall 8: `build_feature_vector_manual` Receives No Startlist; `diff_field_rank_quality` Is Always 0.0

**What goes wrong:** `build_feature_vector_manual` sets `diff_field_rank_quality = 0.0` (neutral) when no startlist is provided. `diff_field_rank_quality` is the #3 most important feature (importance 0.014). The Pinnacle preload path will have the full startlist available from the market data (all riders in the H2H matchups are known). If the code doesn't pass the startlist to `build_feature_vector_manual`, predictions will be systematically less accurate than they need to be — and the feature already has neutral default logic written in, so this will fail silently.

**Why it happens:** `build_feature_vector_manual` currently takes no `startlist` parameter (the CONCERNS.md notes this as a missing piece). The Pinnacle preload integration, which does have startlist data, will naturally call `predict_manual` without adding the startlist — because the function signature doesn't accept it yet. This is a silent accuracy loss.

**Consequences:** Startlist-relative features (`diff_field_rank_quality`, `diff_field_rank_form`, `diff_field_strength_ratio`) are always neutral for all preloaded predictions. The model cannot distinguish between a sprinter in a weak field vs a strong field.

**Prevention:**
- When building the preload integration, explicitly check: does `build_feature_vector_manual` accept a `startlist` parameter? If not, adding startlist support should be scoped into this milestone or explicitly deferred with a note.
- The Pinnacle market response will contain all rider names for a given race. After name resolution, the set of resolved PCS URLs is the startlist. Pass it to the feature builder.
- If adding startlist support is deferred, document in the prediction response that field-quality features are using neutral defaults.

**Detection:** Add an assertion or log line in `build_feature_vector_manual` that logs when startlist features are defaulting to neutral. Make the silent default visible.

---

### Pitfall 9: `name_mappings.json` Cache Has No Schema Validation on Load

**What goes wrong:** `name_mappings.json` is a persistent JSON file that maps Pinnacle display names to PCS URLs. On every load, the code reads this file. If the file is manually edited, corrupted, or written with a wrong schema (e.g., a PCS URL from a different year's rider profile that is now 404), the code silently uses the wrong mapping. There is also no locking on concurrent writes from multiple Flask threads (if `threaded=True` is set).

**Why it happens:** JSON files read with `json.load()` have no built-in schema enforcement. File-level write concurrency is not handled in Python without explicit locking.

**Consequences:** A corrupted or out-of-date cache entry produces wrong rider URL → wrong features → wrong probabilities. This is indistinguishable from a correct prediction unless the user notices the wrong rider name in the UI.

**Prevention:**
- On load, validate each entry: key must be a non-empty string, value must match the PCS URL pattern (`rider/[a-z0-9-]+`). Log and skip invalid entries; do not crash.
- Use `filelock` or a threading lock around writes to prevent concurrent write corruption. A simple `threading.Lock()` is sufficient for single-process Flask.
- Include a version field in the JSON file. If the schema changes, the old file is ignored and rebuilt from scratch.

**Detection:** Add a `_validate_mappings()` call on startup that reports how many entries exist and flags any that don't match the expected pattern.

---

### Pitfall 10: Odds Audit Log Not Written Atomically; Partial Writes on Exception

**What goes wrong:** `data/odds_log.jsonl` is appended to after each successful Pinnacle fetch (ODDS-02). If the Flask endpoint raises an exception after fetching but before writing, or during writing (disk full, permission error), the log entry is missing. If the write is interrupted mid-line, the JSONL file has a corrupt last line that breaks all future JSON parsing of the file.

**Why it happens:** `file.write()` on a JSONL entry is not atomic. An exception mid-write leaves a partial JSON object. Standard `open(path, "a")` append mode does not guarantee the write completes before the Python process continues.

**Consequences:** Audit log is incomplete or unparseable. Any tooling that reads `odds_log.jsonl` for analysis will fail on the corrupt line.

**Prevention:**
- Write each JSONL entry as a complete line with `\n` in a single `file.write()` call (single syscall is atomic on most filesystems for small payloads).
- Wrap writes in try/except; log failure to `logging` but do not raise (the odds fetch itself succeeded — don't block the user because the audit log failed).
- Consider writing to a temp file and atomically renaming — but for append-only audit logs, this is overkill. Single-line writes of < 4KB are atomic on Linux/macOS.

**Detection:** After every test run, parse `odds_log.jsonl` with `json.loads()` on each line. Fail the test if any line is invalid.

---

## Minor Pitfalls

### Pitfall 11: `PINNACLE_SESSION_COOKIE` Env Var Absent at Startup

**What goes wrong:** If the env var is not set, `os.environ["PINNACLE_SESSION_COOKIE"]` raises `KeyError` at the point of use inside the endpoint. If this is called at module import time (e.g., in a module-level constant), Flask fails to start entirely. If called at request time, the first click of "Load from Pinnacle" raises an unhandled exception, returning a 500 with no useful message.

**Prevention:** Read the env var at request time (not import time). Use `os.environ.get("PINNACLE_SESSION_COOKIE")` and return a 503 with the message "Set PINNACLE_SESSION_COOKIE env var" if it is None. Add a startup check that logs a WARNING (not an error — the app should still start) if the var is absent.

---

### Pitfall 12: Pinnacle Odds Decode Vig Differently From the Existing Kelly Calculation

**What goes wrong:** Pinnacle internal odds may be returned as American odds (e.g., `-130 / +110`) or as European decimal odds, depending on what the browser session is configured to show. The existing `kelly_criterion()` in `models/predict.py` expects decimal odds. If the API returns American or fractional odds, the conversion must be applied before passing to Kelly — and forgetting this produces wildly wrong stake sizes (e.g., American `-130` interpreted as decimal `130.0` = impossible 99.2% implied probability).

**Prevention:** Determine the odds format returned by the internal API during the discovery step (Phase 1). Write a single `_to_decimal_odds(raw, format)` converter and test it. Never pass raw API odds directly to `kelly_criterion()`.

**Detection:** Add an assertion: `assert 1.01 <= decimal_odds <= 20.0` before passing to Kelly. Odds outside this range are almost certainly in the wrong format.

---

### Pitfall 13: Race Selector Shows Duplicate Races When Pinnacle Has Multiple H2H Markets Per Stage

**What goes wrong:** Pinnacle may offer multiple H2H markets for the same stage (different matchup groups, or both outright H2H and handicap H2H). The race selector UI deduplicates on the Pinnacle race name string. If the name is not exactly identical across market groups (e.g., "Tour de Romandie Stage 4" vs "Tour de Romandie - Stage 4 Handicap"), the selector shows two entries for the same stage, confusing the user.

**Prevention:** Deduplicate race selector options by normalizing Pinnacle race names (strip market type suffixes, normalize hyphens/dashes) before building the dropdown. Group all H2H pairs under the canonical race name.

---

### Pitfall 14: procyclingstats Stage URL Requires the Year; Year Inference From Race Name Can Be Wrong

**What goes wrong:** PCS stage URLs include the year: `race/tour-de-romandie/2026/stage-4`. The year must be inferred (today's year). If Pinnacle is offering markets on a race that started last year and finishes this year (e.g., a race running Dec 31 → Jan 1), the stage URL with today's year will 404.

**Prevention:** Use the current date to determine year. If the stage fetch returns an error, retry with `current_year - 1`. Log the year used.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Pinnacle API discovery | Endpoint unknown; cycling H2H markets may not exist as H2H specials | Confirm market existence and response schema before writing any client code |
| Pinnacle client implementation | 200-with-HTML on cookie expiry; American vs decimal odds | Check Content-Type + validate odds range; never check only status code |
| Name resolution | Surname-first format; NFC/NFD mismatch; wrong auto-accept | Normalize format and Unicode form before fuzzy; use token_sort_ratio; threshold >= 90 |
| Name cache persistence | Wrong mappings cached forever; file corruption | Validate schema on load; use threading lock on write; allow UI correction |
| Stage context fetch | URL construction failure; fetches wrong stage silently | Verify fetched date matches today's date; degrade gracefully via STGE-02 |
| Stage context performance | Blocks Flask thread 3–10 seconds | threaded=True; separate rate limiter; per-request timeout |
| Prediction integration | Startlist features always neutral; feature column silently zero-filled | Check if startlist can be passed; log when defaulting to neutral |
| Odds ingestion | Partial JSONL writes; missing env var | Single-line atomic writes; read env var at request time with clear error |

---

## Sources

- Codebase: `features/pipeline.py` — `build_feature_vector_manual` implementation, startlist neutral defaults, interaction feature groups (lines 225–396)
- Codebase: `data/scraper.py` — `_rate_limit()` global state, `REQUEST_DELAY=0.5s`, `fetch_with_retry` pattern (lines 27–76)
- Codebase: `models/predict.py` — `predict_manual` signature, feature vector assembly via `fv.get(name, 0.0)` (lines 242–301)
- Codebase: `.planning/codebase/CONCERNS.md` — confirmed `build_feature_vector_manual` startlist missing, interaction feature duplication, SQLite concurrency
- RapidFuzz docs: preprocessing removed by default in 3.0.0 (HIGH confidence — [GitHub](https://github.com/rapidfuzz/RapidFuzz))
- Pinnacle API closure: public API closed July 23rd, 2025 — [Arbusers thread](https://arbusers.com/access-to-pinnacle-api-closed-since-july-23rd-2025-t10682/) (MEDIUM confidence — page returned 403 but confirmed by multiple search results)
- SQLite WAL concurrency: `busy_timeout` required; single-writer constraint — [Oldmoe blog](https://oldmoe.blog/2024/07/08/the-write-stuff-concurrent-write-transactions-in-sqlite/) (HIGH confidence)
- procyclingstats lib: HTML parser, `ExpectedParsingError` ignored by default — [GitHub](https://github.com/themm1/procyclingstats) (HIGH confidence)
