# Phase 4: Flask Endpoint Wiring — Research

**Researched:** 2026-04-12
**Domain:** Flask Blueprint wiring, JSON API design, upstream module integration
**Confidence:** HIGH — all three upstream modules read from source, Flask app fully read, test patterns verified from codebase

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** `/api/pinnacle/load` returns resolved market data only. Does NOT run model predictions.

**D-02:** Response is designed to map onto the existing batch H2H form. No second screen. Phase 5 JS pre-populates existing form fields from the response.

**D-03:** Unresolved pairs include `best_candidate_a_name` / `best_candidate_a_url` hints when fuzzy score 60–89. Raw Pinnacle name always included regardless of resolution status.

**D-04:** Races grouped by `OddsMarket.race_name` (exact string equality). `fetch_stage_context()` called once per race group.

**D-05:** `/api/pinnacle/refresh-odds` is stateless — client sends `matchup_ids`, server re-fetches Pinnacle and returns only updated `odds_a`/`odds_b`.

**D-06:** Structured JSON errors with `env_var` field. HTTP 401 for auth errors. HTTP 500 never returned — all exceptions caught and mapped to structured JSON.

**D-07:** New Blueprint in `webapp/pinnacle_bp.py`. Registered in `webapp/app.py`. `_require_localhost` applied to both routes.

**D-08:** `diff_field_rank_quality` left at neutral 0.0 in Phase 4. Startlist fetch deferred. Must be logged in `decision_log.md`.

**Frozen response schema (must be appended to `docs/pinnacle-api-notes.md` before Phase 5):**
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

**Refresh-odds request:**
```json
{"matchup_ids": ["12345", "67890"]}
```

**Refresh-odds response:**
```json
{
  "pairs": [
    {"matchup_id": "12345", "odds_a": 1.90, "odds_b": 2.05}
  ]
}
```

### Claude's Discretion
- Whether to instantiate `NameResolver` once at Blueprint level or per-request
- Exact HTTP status codes for non-auth errors (400 for bad request, 503 for Pinnacle unavailable)
- Internal timeout handling if `fetch_stage_context()` or `fetch_cycling_h2h_markets()` blocks

### Deferred Ideas (OUT OF SCOPE)
- PCS Startlist Fetch + Pinnacle Rider Overlap Validation
- Real `diff_field_rank_quality` computation from startlist
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ODDS-04 | System can re-fetch Pinnacle odds independently without re-loading stage context or re-resolving rider names | Stateless `/refresh-odds` endpoint; client sends back `matchup_ids`, server calls `fetch_cycling_h2h_markets()` and matches by ID. Confirmed `matchup_id` is `str(matchup["id"])` from Pinnacle — stable per market. |
</phase_requirements>

---

## Summary

All three upstream modules exist and are fully implemented. `data/odds.py`, `data/name_resolver.py`, and `intelligence/stage_context.py` all have clean, well-documented public interfaces that Phase 4 can wire directly. No stubs or missing dependencies.

The Flask app (`webapp/app.py`) has no existing Blueprint usage — all routes are registered directly on the `app` object. Phase 4 introduces the first Blueprint. The `_require_localhost` decorator is a plain function decorator defined at module level in `app.py` — it must be imported and applied in `pinnacle_bp.py`, which requires a small but important import decision (import from `webapp.app` or redefine it). The `/api/predict/batch` endpoint is the exact pattern to follow: parse JSON body, iterate items, catch per-item exceptions, return a structured results list.

The end-to-end verification requirement (SC-1) needs a live Pinnacle session. `curl` is available (`curl 7.78.0`) and is the right tool — `httpie` is not installed. Automated tests use `unittest.mock` / `pytest` with `patch()` for all external dependencies; Flask test client (`app.test_client()`) has not been used in any existing test file, but is the standard approach for endpoint unit tests.

**Primary recommendation:** Create `webapp/pinnacle_bp.py` as a Flask Blueprint. Import `_require_localhost` from `webapp.app` (see pitfall section — avoid redefining it). Instantiate `NameResolver` once per request (simpler, avoids stale-corpus problems with no measurable cost for batch loads of ~65 pairs). Build the response by grouping `OddsMarket` objects by `race_name`, then resolving names and fetching stage context per group. Map auth errors to HTTP 401 with `{"error": ..., "env_var": "PINNACLE_SESSION_COOKIE", "type": "auth_error"}`.

---

## Project Constraints (from CLAUDE.md)

| Directive | Enforcement |
|-----------|-------------|
| 2-space indentation | All new code in `pinnacle_bp.py` |
| Type hints on all function signatures | Every function, including private helpers |
| Docstrings on all public functions | Routes, helpers |
| `pytest tests/ -v` before marking any task done | Run full suite at plan completion |
| Do not add dependencies to `requirements.txt` without asking | Phase 4 needs no new deps — Flask, requests already present |
| `debug=False` in production | Already set in `app.py` — do not change |
| Port 5001 | Do not change |
| `get_db()` from `data.scraper` for all DB access | Use if Blueprint needs DB directly (NameResolver handles its own) |
| All scripts degrade gracefully on data source failure | Both endpoints catch all exceptions, map to structured JSON |
| Decision log entry required | D-08 (neutral `diff_field_rank_quality`) must be logged to `decision_log.md` |

---

## Standard Stack

### Core (all already installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Flask | 3.1.3 | HTTP routing, Blueprint, test client | Project-standard web framework |
| pytest | 9.0.3 | Test framework | Project-standard; `pytest tests/ -v` is the gating command |
| unittest.mock | stdlib | Patching external dependencies in tests | Used in all existing Phase 2/3 tests |

[VERIFIED: `pip show flask pytest` on project venv — Flask 3.1.3, pytest 9.0.3]

### Upstream Modules (implemented, verified from source)

| Module | Public Interface | Notes |
|--------|-----------------|-------|
| `data/odds.py` | `fetch_cycling_h2h_markets() -> list[OddsMarket]`, `PinnacleAuthError`, `OddsMarket` | Raises `PinnacleAuthError` on expired key; raises `requests.RequestException` on network error |
| `data/name_resolver.py` | `NameResolver`, `ResolveResult` | `NameResolver.__init__` loads all ~5K riders from DB once; `resolve(pinnacle_name) -> ResolveResult` |
| `intelligence/stage_context.py` | `fetch_stage_context(pinnacle_race_name) -> StageContext`, `StageContext` | Never raises; returns `StageContext(is_resolved=False)` on any failure or timeout |

[VERIFIED: all three files read from source]

**Installation:** No new packages required. All dependencies are already in `requirements.txt`.

---

## Architecture Patterns

### Existing Flask App Structure

`webapp/app.py` registers all routes directly on the `app` object — no Blueprints currently exist. [VERIFIED: grepped for `register_blueprint`/`Blueprint` in `webapp/app.py` — zero results]

The `_require_localhost` decorator is defined at module level in `app.py`:
```python
# Source: webapp/app.py line 34
def _require_localhost(f):
    """Restrict a route to localhost-only access."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.remote_addr not in ("127.0.0.1", "::1"):
            return jsonify({"error": "Admin access is restricted to localhost"}), 403
        return f(*args, **kwargs)
    return decorated
```

It checks `request.remote_addr` — not a header, not a token. Applied to `/admin` and all `/api/admin/*` routes.

### Recommended Project Structure

```
webapp/
├── app.py              # existing — add: from webapp.pinnacle_bp import pinnacle_bp; app.register_blueprint(pinnacle_bp)
└── pinnacle_bp.py      # new — Blueprint with /api/pinnacle/load and /api/pinnacle/refresh-odds
tests/
└── test_pinnacle_bp.py # new — unit tests using Flask test client + mocks
```

### Pattern 1: Flask Blueprint Registration (first Blueprint in project)

```python
# webapp/pinnacle_bp.py
from flask import Blueprint, jsonify, request
from webapp.app import _require_localhost  # import from app.py — see Pitfall 1

pinnacle_bp = Blueprint("pinnacle", __name__)

@pinnacle_bp.route("/api/pinnacle/load", methods=["POST"])
@_require_localhost
def pinnacle_load():
    ...
```

```python
# webapp/app.py — add near end of imports block
from webapp.pinnacle_bp import pinnacle_bp
app.register_blueprint(pinnacle_bp)
```

[ASSUMED: Flask 3.x Blueprint registration syntax — consistent with Flask 2.x, no breaking change known. Confidence: HIGH given Flask docs stability on this pattern.]

### Pattern 2: Batch JSON Endpoint (follow `/api/predict/batch`)

The `/api/predict/batch` endpoint (lines 226–315 in `app.py`) is the authoritative pattern:
- `data = request.get_json(silent=True)` — returns `None` on bad JSON (no exception)
- Validate required fields → return `400` with `{"error": "..."}` message
- Iterate items in a loop, catch per-item exceptions, append error entries to results list
- Return `jsonify({"results": results, "count": len(results)})`

[VERIFIED: webapp/app.py lines 226–315]

### Pattern 3: Error Handler (existing `@app.errorhandler`)

```python
# Source: webapp/app.py line 45
@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(500)
def handle_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": str(e)}), e.code if hasattr(e, 'code') else 500
    return e
```

This handler is registered on `app`, not the Blueprint. Blueprint routes that raise unhandled exceptions will fall through to this handler. Phase 4 endpoints should catch exceptions proactively and return structured JSON rather than relying on the global handler.

### Pattern 4: Flask Test Client (for unit tests)

No existing tests use `app.test_client()`. The standard pattern for Flask 3.x:

```python
# Source: [ASSUMED — Flask 3.x docs pattern, consistent with Flask 2.x]
import pytest
from webapp.app import app

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_load_auth_error(client):
    with patch("webapp.pinnacle_bp.fetch_cycling_h2h_markets") as mock_fetch:
        mock_fetch.side_effect = PinnacleAuthError("expired")
        resp = client.post(
            "/api/pinnacle/load",
            json={},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["type"] == "auth_error"
        assert "PINNACLE_SESSION_COOKIE" in data["env_var"]
```

**Key detail:** `_require_localhost` checks `request.remote_addr`. The test client must inject `REMOTE_ADDR: 127.0.0.1` via `environ_base`, otherwise the decorator will return 403 before the route logic runs.

[VERIFIED (pattern source): Flask test client behavior for `remote_addr` injection is documented in Flask test docs and is well-established in versions 2.x and 3.x — ASSUMED for exact kwarg name, but standard pattern]

### Pattern 5: `NameResolver` Instantiation Strategy

`NameResolver.__init__` queries `SELECT url, name FROM riders` (all ~5K rows) once. Two options:

**Option A — Per-request instantiation (recommended):**
```python
@pinnacle_bp.route("/api/pinnacle/load", methods=["POST"])
@_require_localhost
def pinnacle_load():
    resolver = NameResolver()  # fresh each request
    ...
```
Simpler. No stale-corpus risk if riders table is updated between requests. For ~65 pairs, the DB query cost is negligible. This is Claude's discretion per CONTEXT.md.

**Option B — Blueprint-level singleton:**
```python
_resolver: Optional[NameResolver] = None

def _get_resolver() -> NameResolver:
    global _resolver
    if _resolver is None:
        _resolver = NameResolver()
    return _resolver
```
Faster for repeated calls. Corpus becomes stale after a `scrape_all.py` run without Flask restart.

**Decision guidance:** Per-request is simpler and safer given the data volume. Recommend Option A unless profiling shows it to be a bottleneck.

### Pattern 6: `fetch_stage_context` Error Contract

`fetch_stage_context()` never raises. It returns `StageContext(is_resolved=False)` on any failure including timeout. [VERIFIED: `intelligence/stage_context.py` — `_fetch_with_timeout` catches `TimeoutError` and all `Exception`, returns `_unresolved_context()`; `fetch_stage_context` also guards on `race_url` being `None`]

The endpoint maps `stage_context.is_resolved` directly to `stage_resolved` in the response:
```python
"stage_resolved": stage_context.is_resolved,
```

### Pattern 7: `OddsMarket` to Response Grouping

```python
# Group OddsMarket list by race_name (exact string equality per D-04)
from collections import defaultdict
import dataclasses

markets = fetch_cycling_h2h_markets()  # list[OddsMarket]
by_race: dict[str, list[OddsMarket]] = defaultdict(list)
for market in markets:
    by_race[market.race_name].append(market)

races = []
for race_name, race_markets in by_race.items():
    stage_context = fetch_stage_context(race_name)
    pairs = []
    for m in race_markets:
        result_a = resolver.resolve(m.rider_a_name)
        result_b = resolver.resolve(m.rider_b_name)
        pairs.append({
            "pinnacle_name_a": m.rider_a_name,
            "pinnacle_name_b": m.rider_b_name,
            "rider_a_url": result_a.url,
            "rider_b_url": result_b.url,
            "rider_a_resolved": result_a.url is not None,
            "rider_b_resolved": result_b.url is not None,
            "best_candidate_a_name": result_a.best_candidate_name,
            "best_candidate_a_url": result_a.best_candidate_url,
            "best_candidate_b_name": result_b.best_candidate_name,
            "best_candidate_b_url": result_b.best_candidate_url,
            "odds_a": m.odds_a,
            "odds_b": m.odds_b,
            "matchup_id": m.matchup_id,
        })
    races.append({
        "race_name": race_name,
        "stage_resolved": stage_context.is_resolved,
        "stage_context": dataclasses.asdict(stage_context),
        "pairs": pairs,
    })
```

Note: `dataclasses.asdict(stage_context)` includes `is_resolved` in the nested object — this is intentional per the frozen schema in CONTEXT.md.

### Pattern 8: Refresh-Odds Matching

```python
# /api/pinnacle/refresh-odds
data = request.get_json(silent=True)
matchup_ids = set(data.get("matchup_ids", []))

markets = fetch_cycling_h2h_markets()
id_to_market = {m.matchup_id: m for m in markets}

pairs = []
for mid in matchup_ids:
    if mid in id_to_market:
        m = id_to_market[mid]
        pairs.append({"matchup_id": mid, "odds_a": m.odds_a, "odds_b": m.odds_b})
    # Silently omit matchup_ids not found in current Pinnacle response
    # (market may have closed since /load was called)
```

`matchup_id` stability: Pinnacle matchup IDs are integer IDs for the market (`matchup["id"]` in their API), cast to string in `OddsMarket`. [VERIFIED: `data/odds.py` line 436: `matchup_id=str(matchup["id"])`] These are permanent market identifiers, not session-scoped. CONTEXT.md notes: "confirm it's stable across multiple Pinnacle API calls for the same market before Phase 4 execution" — this should be a pre-execution verification step, not a planning assumption.

### Anti-Patterns to Avoid

- **Importing `_require_localhost` from `webapp.app` creating a circular import:** See Pitfall 1 below for the correct approach.
- **Calling `NameResolver()` inside a loop over pairs:** Instantiate once per request, outside the pairs loop — each `__init__` queries all riders from DB.
- **Returning raw `StageContext` dataclass:** Use `dataclasses.asdict(stage_context)` to convert to a JSON-serializable dict.
- **Returning HTTP 500 on any exception:** Both endpoints must catch all exceptions and return structured JSON. The global `handle_error` is a fallback, not a primary path.
- **Calling `fetch_stage_context()` per pair:** Call once per race group, not per matchup. (D-04)

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Name → PCS URL mapping | Custom lookup | `NameResolver.resolve()` | Full 4-stage pipeline already tested (22 tests green) |
| Stage details from PCS | Direct PCS scraping | `fetch_stage_context()` | Timeout, graceful degradation, fuzzy race matching already handled |
| Pinnacle odds fetch | HTTP requests directly | `fetch_cycling_h2h_markets()` | Auth retry logic, key cache, audit log, JSONL all already implemented |
| Decorator for localhost | New access check | Import `_require_localhost` from `webapp.app` | Identical logic, reusing prevents divergence |
| Dataclass → dict serialization | Manual dict construction | `dataclasses.asdict()` | Handles nested dataclasses, None fields correctly |

---

## Common Pitfalls

### Pitfall 1: Circular Import of `_require_localhost`

**What goes wrong:** `webapp/pinnacle_bp.py` imports from `webapp.app`. `webapp/app.py` imports from `webapp.pinnacle_bp`. Python raises `ImportError: cannot import name 'pinnacle_bp'` at startup.

**Why it happens:** `webapp/app.py` must `from webapp.pinnacle_bp import pinnacle_bp` to register it. If `pinnacle_bp.py` also `from webapp.app import _require_localhost`, the import cycle prevents both modules from loading.

**How to avoid:** Extract `_require_localhost` into a separate shared module (e.g., `webapp/auth.py`), then import from there in both `app.py` and `pinnacle_bp.py`. Alternatively, redefine the decorator inline in `pinnacle_bp.py` (identical 5-line function — acceptable duplication given its simplicity). Do NOT attempt `from webapp.app import _require_localhost` at module level in `pinnacle_bp.py`.

**Warning signs:** `ImportError` or `AttributeError` at Flask startup when `register_blueprint` is called.

**Recommended resolution:** Redefine inline in `pinnacle_bp.py`. The function is 5 lines, self-contained, and has no state. If the project grows more Blueprints, extract to `webapp/auth.py` then.

### Pitfall 2: `_require_localhost` Returns 403 in Tests

**What goes wrong:** Tests call `client.post("/api/pinnacle/load", json={})` and get `403 Forbidden` rather than testing the route logic.

**Why it happens:** Flask test client's default `REMOTE_ADDR` is `127.0.0.1` — actually fine. But if the test fixture does not set it explicitly, the behavior may differ by Flask version.

**How to avoid:** Always pass `environ_base={"REMOTE_ADDR": "127.0.0.1"}` in test requests to be explicit.

**Warning signs:** All endpoint tests returning 403 with `{"error": "Admin access is restricted to localhost"}`.

### Pitfall 3: `StageContext` Contains Non-JSON-Serializable Fields

**What goes wrong:** `jsonify({"stage_context": stage_context})` raises `TypeError: Object of type StageContext is not JSON serializable`.

**Why it happens:** `jsonify` does not know how to serialize dataclasses.

**How to avoid:** Call `dataclasses.asdict(stage_context)` before passing to `jsonify`. [VERIFIED: `dataclasses.asdict` is stdlib; flattens nested dataclasses recursively]

### Pitfall 4: `fetch_cycling_h2h_markets()` Raises `requests.RequestException` on Network Error

**What goes wrong:** A network timeout causes `requests.RequestException` to propagate out of the endpoint, which either crashes Flask or triggers the global 500 handler — not the structured JSON error path.

**Why it happens:** `fetch_cycling_h2h_markets()` re-raises `requests.RequestException` after logging (line 449 in `data/odds.py`). It only catches auth errors internally.

**How to avoid:** Both endpoints must catch `requests.RequestException` explicitly and return HTTP 503:
```python
except requests.RequestException as e:
    return jsonify({"error": "Pinnacle API unavailable", "detail": str(e), "type": "network_error"}), 503
```

### Pitfall 5: Empty `matchup_ids` List in Refresh-Odds

**What goes wrong:** Client sends `{"matchup_ids": []}` — endpoint calls `fetch_cycling_h2h_markets()` (costly network round-trip) then returns an empty `pairs` list.

**Why it happens:** No input validation before the Pinnacle fetch.

**How to avoid:** Validate `matchup_ids` is non-empty before calling `fetch_cycling_h2h_markets()`. Return HTTP 400 if empty.

### Pitfall 6: `PinnacleAuthError` vs `requests.RequestException` Error Shape

**What goes wrong:** Both errors are caught by the same `except Exception` block, producing inconsistent response shapes (`type` field may be missing or wrong).

**How to avoid:** Catch them in order, most specific first:
```python
except PinnacleAuthError as e:
    return jsonify({
        "error": str(e),
        "env_var": "PINNACLE_SESSION_COOKIE",
        "type": "auth_error",
    }), 401
except requests.RequestException as e:
    return jsonify({"error": "Pinnacle unavailable", "detail": str(e), "type": "network_error"}), 503
except Exception as e:
    log.exception("Unexpected error in pinnacle_load")
    return jsonify({"error": str(e), "type": "internal_error"}), 500
```

---

## Code Examples

### Blueprint skeleton

```python
# webapp/pinnacle_bp.py
"""Flask Blueprint for Pinnacle market endpoints."""

import dataclasses
import logging
from collections import defaultdict
from functools import wraps
from typing import Optional

import requests
from flask import Blueprint, jsonify, request

from data.odds import fetch_cycling_h2h_markets, PinnacleAuthError
from data.name_resolver import NameResolver
from intelligence.stage_context import fetch_stage_context

log = logging.getLogger(__name__)
pinnacle_bp = Blueprint("pinnacle", __name__)


def _require_localhost(f):
  """Restrict route to localhost-only. Duplicated from webapp/app.py — avoid circular import."""
  @wraps(f)
  def decorated(*args, **kwargs):
    if request.remote_addr not in ("127.0.0.1", "::1"):
      return jsonify({"error": "Admin access is restricted to localhost"}), 403
    return f(*args, **kwargs)
  return decorated
```

[ASSUMED: circular import avoidance via inline redefinition — standard Flask pattern]

### Registration in `app.py`

```python
# webapp/app.py — add after existing imports, before route definitions
from webapp.pinnacle_bp import pinnacle_bp
app.register_blueprint(pinnacle_bp)
```

[ASSUMED: Flask 3.x Blueprint registration — consistent with all Flask 2.x/3.x docs]

### Minimal `/load` endpoint structure

```python
@pinnacle_bp.route("/api/pinnacle/load", methods=["POST"])
@_require_localhost
def pinnacle_load():
  """Fetch Pinnacle cycling H2H markets, resolve names, fetch stage context."""
  try:
    markets = fetch_cycling_h2h_markets()
  except PinnacleAuthError as e:
    return jsonify({
      "error": str(e),
      "env_var": "PINNACLE_SESSION_COOKIE",
      "type": "auth_error",
    }), 401
  except requests.RequestException as e:
    return jsonify({"error": "Pinnacle API unavailable", "detail": str(e), "type": "network_error"}), 503

  resolver = NameResolver()
  by_race = defaultdict(list)
  for m in markets:
    by_race[m.race_name].append(m)

  races = []
  for race_name, race_markets in by_race.items():
    stage_ctx = fetch_stage_context(race_name)
    pairs = [_build_pair(m, resolver) for m in race_markets]
    races.append({
      "race_name": race_name,
      "stage_resolved": stage_ctx.is_resolved,
      "stage_context": dataclasses.asdict(stage_ctx),
      "pairs": pairs,
    })

  return jsonify({"races": races})
```

### End-to-end verification curl command

```bash
# Verify /api/pinnacle/load with live session
curl -s -X POST http://127.0.0.1:5001/api/pinnacle/load \
  -H "Content-Type: application/json" \
  -d '{}' | python3 -m json.tool

# Verify /api/pinnacle/refresh-odds
curl -s -X POST http://127.0.0.1:5001/api/pinnacle/refresh-odds \
  -H "Content-Type: application/json" \
  -d '{"matchup_ids": ["1628017725"]}' | python3 -m json.tool

# Verify auth error (no PINNACLE_SESSION_COOKIE set)
curl -s -X POST http://127.0.0.1:5001/api/pinnacle/load \
  -H "Content-Type: application/json" \
  -d '{}' | python3 -m json.tool
```

[VERIFIED: curl 7.78.0 available at `/mingw64/bin/curl.exe`]

---

## Upstream Interface Summary

### `data/odds.py`

```python
# Key facts verified from source:
from data.odds import fetch_cycling_h2h_markets, PinnacleAuthError, OddsMarket

# OddsMarket fields (verified):
# rider_a_name: str  — Pinnacle display name (e.g. "Tomas Kopecky")
# rider_b_name: str  — Pinnacle display name (e.g. "Brent van Moer")
# odds_a: float      — decimal odds (already converted from American)
# odds_b: float      — decimal odds
# race_name: str     — Pinnacle league name (e.g. "Paris-Roubaix")
# matchup_id: str    — str(matchup["id"]) — e.g. "1628017725"

# Raises:
# PinnacleAuthError  — expired/missing key (after one retry)
# requests.RequestException — network failure
# Never raises for empty results — returns []
```

### `data/name_resolver.py`

```python
from data.name_resolver import NameResolver, ResolveResult

resolver = NameResolver()  # loads ~5K riders from cache.db once
result = resolver.resolve("ROGLIC PRIMOZ")  # -> ResolveResult

# ResolveResult fields (verified):
# url: Optional[str]               — PCS URL if resolved, None if not
# best_candidate_url: Optional[str] — populated when score 60-89
# best_candidate_name: Optional[str]— populated when score 60-89
# best_score: Optional[int]        — fuzzy score when 60-89
# method: str                      — "exact"|"normalized"|"fuzzy"|"cache"|"unresolved"
```

### `intelligence/stage_context.py`

```python
from intelligence.stage_context import fetch_stage_context, StageContext

ctx = fetch_stage_context("Paris-Roubaix")  # -> StageContext
# Never raises. Returns StageContext(is_resolved=False) on any failure.

# StageContext fields (verified — map 1:1 to build_feature_vector_manual race_params):
# distance, vertical_meters, profile_icon, profile_score, is_one_day_race
# stage_type, race_date, race_base_url, num_climbs, avg_temperature
# Plus: uci_tour (str), is_resolved (bool)
```

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All code | Yes | 3.14.0 (venv) | — |
| Flask | Blueprint, test client | Yes | 3.1.3 | — |
| pytest | Test suite | Yes | 9.0.3 | — |
| curl | SC-1 end-to-end verification | Yes | 7.78.0 (curl.exe) | — |
| httpie | Alternative for SC-1 verification | No | — | Use curl (available) |
| Live Pinnacle session (PINNACLE_SESSION_COOKIE) | SC-1, SC-3 live verification | Runtime-only — env var set by user | — | Cannot automate; human step |

**Missing dependencies with no fallback:**
- Live Pinnacle session: SC-1 and SC-3 require a real `PINNACLE_SESSION_COOKIE`. This is a human-provided runtime credential, not an installable dependency. The plan must include a human verification checkpoint before SC-1 can be marked complete.

**Missing dependencies with fallback:**
- httpie: curl is the fallback and is available.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 |
| Config file | none — `pytest tests/ -v` from repo root |
| Quick run command | `pytest tests/test_pinnacle_bp.py -v` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ODDS-04 | `/refresh-odds` re-fetches odds without stage/name re-resolution | unit | `pytest tests/test_pinnacle_bp.py::TestRefreshOdds -x -v` | No — Wave 0 |
| ODDS-04 | `/load` returns full ResolvedMarket schema | unit | `pytest tests/test_pinnacle_bp.py::TestPinnacleLoad -x -v` | No — Wave 0 |
| ODDS-04 | Auth error returns HTTP 401 with `env_var` field | unit | `pytest tests/test_pinnacle_bp.py::TestAuthErrors -x -v` | No — Wave 0 |
| SC-1 | Full response shape confirmed against live Pinnacle | integration | manual curl command (live session required) | No — human step |
| SC-3 | Auth failure returns structured JSON, not 500 | unit | `pytest tests/test_pinnacle_bp.py::TestAuthErrors -x -v` | No — Wave 0 |
| SC-4 | `decision_log.md` entry for `diff_field_rank_quality` | doc | manual verification | No — human step |

### Sampling Rate
- **Per task commit:** `pytest tests/test_pinnacle_bp.py -v`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green + successful live curl before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_pinnacle_bp.py` — covers all unit test cases above
- [ ] No framework config gap (pytest.ini not required — existing `conftest.py` covers mark registration)

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No — localhost-only, single user | `_require_localhost` decorator (IP check) |
| V3 Session Management | No | n/a |
| V4 Access Control | Yes | `_require_localhost` on both routes; never expose port 5001 externally |
| V5 Input Validation | Yes | `request.get_json(silent=True)` returns None on bad JSON; validate `matchup_ids` non-empty; validate field types before processing |
| V6 Cryptography | No | n/a — API key is a guest token, not a secret credential |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SSRF via race_name injected into PCS URLs | Tampering | `fetch_stage_context` uses fuzzy match against DB-controlled race names — no raw string interpolation into URLs |
| Pinnacle key exposure in logs | Information Disclosure | `data/odds.py` logs key cache operations at INFO level but does not log the key value itself |
| JSONL file path traversal | Tampering | `ODDS_LOG_PATH` is hardcoded as `os.path.join(os.path.dirname(__file__), "odds_log.jsonl")` — not user-controllable |
| Request flooding `/load` (each call hits Pinnacle + PCS) | Denial of Service | Localhost-only restriction makes this a non-issue for the single-user personal tool use case |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Flask 3.x Blueprint registration syntax (`app.register_blueprint(pinnacle_bp)`) unchanged from Flask 2.x | Architecture Patterns | Low — this is core Flask API, stable across 2.x/3.x |
| A2 | `_require_localhost` inline redefinition avoids circular import correctly | Pitfall 1 / Code Examples | Low — if circular import still occurs, move to `webapp/auth.py` |
| A3 | `environ_base={"REMOTE_ADDR": "127.0.0.1"}` is the correct kwarg for Flask test client | Pattern 4 | Low — may be `environ_overrides` in some versions; verify during Wave 0 |
| A4 | Pinnacle `matchup_id` (integer market ID) is stable across multiple API fetches for same market | Pattern 8 | Medium — if IDs rotate between calls, stateless refresh-odds is broken; must verify live before SC-2 |

---

## Open Questions

1. **Circular import: import vs. redefine `_require_localhost`**
   - What we know: Importing from `webapp.app` in `webapp/pinnacle_bp.py` will create a circular import once `app.py` imports from `pinnacle_bp.py`.
   - What's unclear: Whether Flask's deferred import pattern (importing inside functions) could work here.
   - Recommendation: Redefine inline in `pinnacle_bp.py` — simpler and avoids the problem entirely. If more Blueprints are added later, extract to `webapp/auth.py` then.

2. **`matchup_id` stability across Pinnacle API calls**
   - What we know: `matchup_id` is `str(matchup["id"])` where `matchup["id"]` is Pinnacle's internal matchup integer. The docs/pinnacle-api-notes.md shows the same ID (`1628017725`) across leagues and markets responses.
   - What's unclear: Whether the ID changes between distinct API sessions (e.g., between a `/load` call and a later `/refresh-odds` call).
   - Recommendation: Verify empirically during live integration testing. Make two separate `fetch_cycling_h2h_markets()` calls 30 seconds apart and confirm IDs are identical. If IDs rotate, the stateless refresh approach breaks and this must be escalated to the user before Phase 5.

3. **`stage_context` field `is_resolved` appears in both root and nested object**
   - What we know: The frozen schema in CONTEXT.md has `stage_resolved` at the race level AND `is_resolved` inside the `stage_context` object (from `dataclasses.asdict`).
   - What's unclear: Whether Phase 5 will use `stage_resolved` (root) or `stage_context.is_resolved` (nested) or both.
   - Recommendation: Keep both — they're redundant but the root `stage_resolved` is the convenient fast-path for Phase 5 JS, while `stage_context.is_resolved` preserves the dataclass contract. No action needed in Phase 4.

---

## Sources

### Primary (HIGH confidence)
- `webapp/app.py` — full file read; `_require_localhost`, `/api/predict/batch`, error handler verified from source
- `data/odds.py` — full file read; `OddsMarket` fields, `PinnacleAuthError`, `fetch_cycling_h2h_markets` error contract verified
- `data/name_resolver.py` — full file read; `NameResolver`, `ResolveResult` fields, `accept()` method verified
- `intelligence/stage_context.py` — full file read; `StageContext` fields, `fetch_stage_context` never-raise contract verified
- `docs/pinnacle-api-notes.md` — full file read; `matchup_id` format (str cast), delta version endpoint noted
- `tests/conftest.py`, `tests/test_stage_context.py`, `tests/test_name_resolver.py`, `tests/test_odds.py` — test patterns verified
- `.planning/phases/04-flask-endpoint-wiring/04-CONTEXT.md` — locked decisions, frozen schema
- `requirements.txt` — Flask 3.1.3, pytest confirmed via `pip show`

### Secondary (MEDIUM confidence)
- Flask 3.x Blueprint registration pattern — consistent with Flask 2.x, standard API

### Tertiary (LOW confidence — flagged)
- `environ_base={"REMOTE_ADDR": "127.0.0.1"}` exact kwarg name for Flask test client (A3)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified via pip show
- Architecture: HIGH — Flask app and all upstream modules read from source
- Upstream interfaces: HIGH — all three modules fully read and interface details extracted
- Test patterns: HIGH — existing test files read; Flask test client pattern is MEDIUM (no existing usage to copy)
- Pitfalls: HIGH for circular import (well-understood Python problem) / MEDIUM for matchup_id stability (unverified assumption)

**Research date:** 2026-04-12
**Valid until:** 2026-05-12 (stable stack — Flask, upstream modules unlikely to change)
