# Pinnacle API Notes — Frozen Contract

**Status:** Verified 2026-04-11 via live API calls
**Purpose:** Sole source of truth for `data/odds.py` (Plan 02) and Phase 4 Flask endpoints
**Do not modify** without user review — this document is the gate before any client code.

---

## Section 1: Base URL and Authentication

**Base URL:** `https://guest.api.arcadia.pinnacle.com/0.1`

**Required Headers:**
```
X-Api-Key: {value — see Section 2: Key Extraction below}
Referer: https://www.pinnacle.com/
Accept: application/json
```

All four allowed headers per CORS response: `Accept`, `Content-Type`, `X-API-Key`, `X-Device-UUID`, `X-Session`, `X-Language`, `X-Customer-Culture`.

**Auth Behavior Summary:**

| Scenario | HTTP Status | Response Body |
|----------|-------------|---------------|
| No X-Api-Key + public league | 200 | Normal list response |
| No X-Api-Key + gated league | 401 | `{"status": 401, "detail": "No authorization token provided"}` |
| Invalid X-Api-Key | 403 | `{"status": 403, "title": "BAD_APIKEY"}` |
| Valid X-Api-Key | 200 | All 65 cycling H2H matchups accessible |

All four scenarios verified via live HTTP calls on 2026-04-11.

---

## Section 2: API Key Extraction (JS Bundle)

The `X-Api-Key` is a **guest token** — not a per-user credential. It is embedded in Pinnacle's
frontend JavaScript bundle and is accessible without logging in.

**Runtime extraction approach:**
1. Fetch `https://www.pinnacle.com/` HTML
2. Locate the main JS bundle `<script src="...">` tag (the largest/versioned bundle)
3. Fetch that JS source
4. Regex-match for a 32-character alphanumeric string that follows a known key-assignment pattern
   (e.g., a pattern like `apiKey\s*[:=]\s*["']([A-Za-z0-9]{32})["']` or similar — confirm exact
   pattern during first Playwright inspection run)
5. Store extracted key in `data/.pinnacle_key_cache` for reuse

**Cache file:** `data/.pinnacle_key_cache`
- Plain-text, one line (the raw key value)
- Gitignored — never committed to the repository

**Lookup order (in `data/odds.py`):**
1. `PINNACLE_SESSION_COOKIE` environment variable (highest priority)
2. `data/.pinnacle_key_cache` file (if env var absent)
3. JS bundle extraction via Playwright (if cache absent or key rejected)

**Key rotation:** The key may rotate when Pinnacle deploys frontend updates. When a 401 or 403 is
returned, the client must discard the cached key and re-extract from the JS bundle.

**Note:** Despite the name `PINNACLE_SESSION_COOKIE`, this value is used as the `X-Api-Key` header
— not a session cookie. The naming is a project convention established in CONTEXT.md (D-02).

---

## Section 3: Cycling Sport ID

**Sport ID:** `45`
Confirmed via `GET /0.1/sports` endpoint on 2026-04-11.

**Endpoint to list active cycling leagues:**
```
GET /0.1/sports/45/leagues?all=false
```
`all=false` returns only leagues with markets open today (not all-time history).

---

## Section 4: Fetch Endpoints

```
GET /0.1/sports
  -> list of all sports (use to confirm cycling sport ID)

GET /0.1/sports/45/leagues?all=false
  -> active cycling leagues (today only)
  -> returns: list of league objects with {id, name, ...}

GET /0.1/leagues/{league_id}/matchups
  -> rider names and matchupId for all H2H matchups in the league
  -> returns: list of matchup objects with {id, participants, startTime, status, ...}

GET /0.1/leagues/{league_id}/markets/straight
  -> moneyline odds by matchupId
  -> returns: list of market objects with {matchupId, prices, status, type, ...}
```

All four endpoints verified with live HTTP calls on 2026-04-11.

---

## Section 5: Active Cycling Leagues (as of 2026-04-11)

| League ID | Name | Matchup Count |
|-----------|------|---------------|
| 8227 | Paris-Roubaix | 24 |
| 234847 | Itzulia Basque Country | 14 |
| 263773 | Paris-Roubaix - Women | 14 |
| 234846 | Itzulia Basque Country - Stage 6 | 13 |

**Total active H2H matchups:** 65 (all confirmed open with valid X-Api-Key)

Note: League 263773 (Paris-Roubaix - Women) returns HTTP 401 without a valid `X-Api-Key`. This is
the specific league that confirmed auth is required for some cycling markets.

---

## Section 6: Odds Format

Pinnacle returns **American integer odds** (e.g., `-154`, `+107`).

**Conversion to decimal:**
```python
# American +107 -> decimal 2.07
# American -154 -> decimal 1.6494

if american > 0:
    decimal = american / 100.0 + 1.0       # +107 -> 2.07
else:
    decimal = 100.0 / abs(american) + 1.0  # -154 -> 1.6494
```

**Contract:**
- `data/odds.py` normalizes to decimal internally before returning `OddsMarket` objects
- `OddsMarket.odds_a` and `OddsMarket.odds_b` are always **decimal** — callers never see American odds
- `data/odds_log.jsonl` also records **post-normalization decimal odds** (never American)

---

## Section 7: Full Example Responses

### Matchup Response (id: 1628017725)

```json
{
  "id": 1628017725,
  "league": {
    "id": 8227,
    "name": "Paris-Roubaix",
    "sport": {"id": 45, "name": "Cycling"}
  },
  "participants": [
    {"alignment": "home", "name": "Tomas Kopecky", "order": 0},
    {"alignment": "away", "name": "Brent van Moer", "order": 1}
  ],
  "periods": [{"cutoffAt": "2026-04-12T08:50:00Z", "hasMoneyline": true, "status": "open"}],
  "startTime": "2026-04-12T08:50:00Z",
  "status": "pending",
  "type": "matchup"
}
```
[VERIFIED: live API response 2026-04-11]

### Straight Market Response (matchupId: 1628017725)

```json
{
  "cutoffAt": "2026-04-12T08:50:00+00:00",
  "isAlternate": false,
  "key": "s;0;m",
  "limits": [{"amount": 100, "type": "maxRiskStake"}],
  "matchupId": 1628017725,
  "period": 0,
  "prices": [
    {"designation": "home", "price": -154},
    {"designation": "away", "price": 107}
  ],
  "status": "open",
  "type": "moneyline",
  "version": 3546194568
}
```
[VERIFIED: live API response 2026-04-11]

**Interpretation:** Tomas Kopecky is `home` at American -154 (decimal 1.6494). Brent van Moer is
`away` at American +107 (decimal 2.07).

---

## Section 8: Join Key

**How matchups and markets connect:**
```
market["matchupId"] == matchup["id"]
```
Both are **integers** in the raw API response. Cast to `str` when building `OddsMarket.matchup_id`
(per decision D-06 — string type is safe regardless of Pinnacle's actual ID format):

```python
matchup_id=str(matchup["id"])
```

**Build an `OddsMarket` only when:**
1. The matchup exists in the matchups response
2. A market with the same `matchupId` exists in the straight markets response
3. `market.get("status") == "open"`

Silently skip unmatched or non-open entries.

---

## Section 9: Delta Updates (future use — ODDS-04)

The Pinnacle API supports incremental polling via version parameter:

```
GET /0.1/leagues/{league_id}/markets/straight?version={max_version}
```

- Returns only changed markets since `max_version`
- Returns **HTTP 204 (no content)** when nothing has changed
- `version` field is returned per market in the straight markets response (e.g., `"version": 3546194568`)

**Not used in Phase 1** — full fetch on every call. Relevant for Phase 4 `POST /api/pinnacle/refresh-odds`
endpoint (ODDS-04) where minimizing response latency matters.

---

## Section 10: Known Pitfalls

### Pitfall 1: Non-List Responses from Gated Leagues
Without a valid `X-Api-Key`, some leagues return a JSON dict (error) instead of a list. Code that
directly iterates the response crashes with `TypeError`. Always check `isinstance(response.json(), list)`
before iterating. Log a warning and skip, or raise `PinnacleAuthError` if auth is confirmed bad.

### Pitfall 2: Matchup/Market ID Mismatch
`market["matchupId"]` and `matchup["id"]` are both integers. Join carefully:
`market_by_id = {m["matchupId"]: m for m in markets_list}`. Only build `OddsMarket` when both sides
exist. Silently skip unmatched entries — Pinnacle sometimes has markets without matching matchups.

### Pitfall 3: Filtering Suspended Markets
Markets with `status != "open"` have no tradeable odds. Always filter on
`market.get("status") == "open"` before building `OddsMarket`. Returning suspended markets causes
downstream errors when computing Kelly stakes.

### Pitfall 4: Circular Import from models Layer
Do NOT import `american_odds_to_decimal` from `models/predict.py` into `data/odds.py`. The models
layer imports from the data layer — circular dependency. Define `_american_to_decimal()` as a private
helper in `data/odds.py` using the same formula.

### Pitfall 5: JSONL File Path
Use `os.path.join(os.path.dirname(__file__), "odds_log.jsonl")` for the path so it resolves to
`data/odds_log.jsonl` regardless of the calling script's working directory. Opening in `"a"` mode
safely creates the file on first write.

### Pitfall 6: Thread Safety
Flask runs with `debug=False` per CLAUDE.md — single-threaded access is the project convention.
No locking is needed for `odds_log.jsonl` writes in Phase 1. If debug mode is ever enabled, writes
may interleave and corrupt the JSONL file.

---

## Implementation Notes for `data/odds.py`

- Module-level functions (no class-based client) — per D-12
- `PINNACLE_SESSION_COOKIE` env var read with `os.environ.get("PINNACLE_SESSION_COOKIE", "")`
- `PinnacleAuthError` message must name the env var explicitly so user knows what to update
- `REQUEST_TIMEOUT = 60` seconds (matches `data/scraper.py` pattern)
- `MAX_RETRIES = 3` with exponential backoff (matches `data/scraper.py` pattern)
- `ODDS_LOG_PATH = os.path.join(os.path.dirname(__file__), "odds_log.jsonl")`

---

## Phase 4: Frozen API Response Schemas

> FROZEN: These schemas were verified against live Pinnacle data before Phase 5 execution.
> Do not modify these schemas without updating Phase 5 frontend code simultaneously.

Phase 5 frontend code against the exact schemas below. Every field listed must be present
in live responses. Extra fields are acceptable; missing fields are not.

---

### HTTP Status Code Table

| Status | Meaning | When |
|--------|---------|------|
| 200 | Success | Valid response returned |
| 400 | Bad Request | Missing or invalid request body (e.g. empty matchup_ids) |
| 401 | Auth Error | PINNACLE_SESSION_COOKIE missing or expired |
| 403 | Forbidden | Request not from localhost (127.0.0.1 or ::1) |
| 503 | Network Error | Pinnacle API unreachable or timed out |

---

### Error Response Schema (HTTP 401)

```json
{
  "error": "Pinnacle session expired or missing",
  "env_var": "PINNACLE_SESSION_COOKIE",
  "type": "auth_error"
}
```

The `env_var` field is always present on 401 responses so the Phase 5 frontend can surface
a clear, actionable error message to the user.

### Error Response Schema (HTTP 503)

```json
{
  "error": "Pinnacle API unavailable",
  "detail": "Connection timeout after 60s",
  "type": "network_error"
}
```

### Error Response Schema (HTTP 400)

```json
{
  "error": "matchup_ids must be non-empty",
  "type": "bad_request"
}
```

---

### POST /api/pinnacle/load — Response Schema

**Request:** `POST /api/pinnacle/load` with body `{}` (no parameters required)

**Response (HTTP 200):**

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

**Field notes:**

- `stage_resolved` mirrors `StageContext.is_resolved`. When `false`, `stage_context` fields
  will be zero/null defaults (distance=0, vertical_meters=0, etc.). Phase 5 frontend MUST
  show manual input fields when `stage_resolved` is `false`.
- `rider_a_url` / `rider_b_url`: PCS URL string (e.g. `"rider/primoz-roglic"`) when resolved,
  `null` when unresolved (name resolution score < 90).
- `rider_a_resolved` / `rider_b_resolved`: Boolean convenience field (true when url is non-null).
- `best_candidate_a_name` / `best_candidate_a_url`: Populated when fuzzy score is 60–89 (hint
  for Phase 5 autocomplete pre-fill). `null` when score < 60 or when rider is fully resolved.
- `pinnacle_name_a` / `pinnacle_name_b`: Always present — the raw Pinnacle display name
  regardless of resolution status. Format: "SURNAME Givenname" (e.g. "ROGLIC Primoz").
- `matchup_id`: String — stable Pinnacle market ID. Used as the key for `/refresh-odds`.
- `odds_a` / `odds_b`: Decimal odds (not American). Converted from Pinnacle's American integer
  format by `data/odds.py`.

**Race grouping:** Pinnacle matchups are grouped by `race_name` (exact string equality per D-04).
Each race entry has one `stage_context` object (fetched once per race, not per pair).

---

### POST /api/pinnacle/refresh-odds — Request and Response Schemas

**Request:** `POST /api/pinnacle/refresh-odds`

```json
{
  "matchup_ids": ["12345", "67890"]
}
```

- `matchup_ids`: Required. Non-empty array of string IDs received from a prior `/load` call.
- Validation: 400 returned if body is missing, `matchup_ids` key absent, or array is empty.

**Response (HTTP 200):**

```json
{
  "pairs": [
    {"matchup_id": "12345", "odds_a": 1.90, "odds_b": 2.05},
    {"matchup_id": "67890", "odds_a": 2.15, "odds_b": 1.75}
  ]
}
```

**Field notes:**

- Response contains ONLY `matchup_id`, `odds_a`, `odds_b` — no stage_context, no rider URLs,
  no resolution fields. Stage context and name resolution are not re-run on refresh (D-05).
- IDs not found in current Pinnacle response are silently omitted (market may have closed).
- The client (Phase 5 JS) reconciles the returned pairs against its local state by `matchup_id`.
- This endpoint is fully stateless — survives Flask restarts. The client re-sends the full
  `matchup_ids` list on every refresh call.

---

*Schemas frozen: 2026-04-12. Phase 5 execution must not begin until live verification is complete.*
