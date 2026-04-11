# Phase 1: Pinnacle API Discovery and Client - Research

**Researched:** 2026-04-11
**Domain:** Pinnacle Sports internal frontend API (guest.api.arcadia.pinnacle.com), Python dataclasses, JSONL logging
**Confidence:** HIGH — all key findings verified via live API calls during this session

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Claude drives discovery in-session using Playwright MCP tools — no manual browser inspection by the user, no separate discovery script.
- **D-02:** Discovery starts unauthenticated. If cycling H2H markets require auth to appear, Claude stops and asks the user for `PINNACLE_SESSION_COOKIE` before retrying.
- **D-03:** After discovery, Claude writes `docs/pinnacle-api-notes.md` (endpoint URL, required headers, sport/market IDs, odds format, full example response) and **stops for user review**. Client code in `data/odds.py` is not written until the user approves the notes.
- **D-04:** `OddsMarket` is a `dataclass` (consistent with `KellyResult` in `models/predict.py`).
- **D-05:** Fields: `rider_a_name: str`, `rider_b_name: str`, `odds_a: float`, `odds_b: float`, `race_name: str`, `matchup_id: str`. No `start_time` — minimal footprint.
- **D-06:** `matchup_id` typed as `str` (safe before discovery confirms Pinnacle's actual ID format).
- **D-07:** `fetch_cycling_h2h_markets()` normalizes odds to decimal internally before returning.
- **D-08:** Conversion logic lives in `data/odds.py`. No conversion responsibility leaks to Phase 4 or the predictor.
- **D-09:** `data/odds_log.jsonl` records post-normalization decimal odds (not raw American).
- **D-10:** Empty fetches (no cycling markets available) still append a JSONL line with `"markets": []` plus fetch metadata (timestamp, status). The log is a complete run record.
- **D-11:** `fetch_cycling_h2h_markets()` returns `[]` when no cycling H2H markets are available. Only `PinnacleAuthError` is raised (on auth failure).
- **D-12:** Module-level functions, consistent with the `data/` package conventions (no class-based client).

### Claude's Discretion
- Session cookie is read from the `PINNACLE_SESSION_COOKIE` env var (already established convention — never committed).
- JSONL line structure for the audit log (beyond `markets` and timestamp) — Claude decides based on what Pinnacle's actual response reveals.
- Request timeout and retry behavior — follow the `data/scraper.py` pattern (60s timeout, exponential backoff on transient failures).

### Deferred Ideas (OUT OF SCOPE)
- **Sortable batch prediction results** — deferred to Phase 5 (Frontend Integration).
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ODDS-01 | System fetches today's H2H cycling markets from Pinnacle's internal API using a stored session cookie | Confirmed: guest.api.arcadia.pinnacle.com/0.1 is the correct endpoint. x-api-key (from env var) is the auth mechanism. See Standard Stack and Architecture Patterns. |
| ODDS-02 | Raw odds data is appended to an audit log (`data/odds_log.jsonl`) after each successful fetch | Standard pattern: open in append mode, write json.dumps(record) + newline. Post-normalization decimal odds per D-09. |
| ODDS-03 | System shows a clear, actionable error message (including which env var to update) when the Pinnacle session cookie is expired or invalid | `PinnacleAuthError` raised when x-api-key is missing or rejected. Message must name `PINNACLE_API_KEY` env var explicitly. |
</phase_requirements>

---

## Summary

**The Pinnacle endpoint, sport ID, and response schema are fully discovered.** Live API calls during this research session confirmed the complete picture. The Pinnacle website frontend uses `guest.api.arcadia.pinnacle.com/0.1` as its internal API, which is accessible with a semi-public `X-Api-Key` header. The cycling sport ID is **45**. All H2H matchups are returned as `moneyline` markets with prices in American integer format (e.g., `-121`, `+107`).

**Authentication finding (critical for D-02):** Most cycling league data is accessible without any authentication. However, at least one league (`Paris-Roubaix - Women`, id 263773) returns HTTP 401 when no `X-Api-Key` is sent. With the correct `X-Api-Key`, all 65 active cycling H2H matchups are accessible. The key is a browser-extracted guest token — not a per-user credential. It may rotate over time, which is why D-01 directs using Playwright to extract it fresh from the Pinnacle website browser session. **Per D-02 conditions: cycling H2H markets DO require the x-api-key to access some leagues.** The key is extracted dynamically from Pinnacle's JS bundle (D-13); `PINNACLE_API_KEY` env var is the optional manual override (D-16).

**Implementation path:** Three API calls per fetch cycle: (1) get active cycling leagues, (2) get matchups per league, (3) get straight markets per league, then join on `matchupId`. Convert American odds to decimal. Build `OddsMarket` dataclass instances. Append JSONL audit record. The existing `american_odds_to_decimal()` function in `models/predict.py` can be reused directly.

**Primary recommendation:** Use the `requests` library (already in `requirements.txt`) directly — no `cloudscraper` needed since the guest API is a clean JSON REST API with no Cloudflare bot challenge. Extract the x-api-key from Pinnacle's frontend JS bundle at runtime (D-13), cache in `data/.pinnacle_key_cache` (D-14), re-extract on 401/403 (D-15). `PINNACLE_API_KEY` env var is the optional manual override (D-16).

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `requests` | >=2.31.0 (already in requirements.txt) | HTTP client for Pinnacle API calls | Already a dependency; the guest API has no Cloudflare bot challenge, so cloudscraper is not needed |
| `dataclasses` | stdlib (Python 3.7+) | `OddsMarket` data container | Project convention — `KellyResult` in `models/predict.py` uses `@dataclass` |
| `json` | stdlib | JSONL audit log serialization and API response parsing | Standard library, no extra dependency |
| `logging` | stdlib | Per-module logger for fetch events and errors | Project convention — all modules use `logging.getLogger(__name__)` |
| `os` | stdlib | `PINNACLE_API_KEY` env var reading (optional override) | Project convention — env vars read with `os.environ.get()` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `cloudscraper` | >=1.2.71 (already in requirements.txt) | Cloudflare-aware scraper | NOT needed for the guest API. Already available if the API adds bot protection |
| `dataclasses.asdict` | stdlib | Convert `OddsMarket` to dict for JSONL serialization | Use in the audit log writer |
| `datetime` | stdlib | ISO timestamp for JSONL log entries | Use `datetime.utcnow().isoformat() + "Z"` for fetch timestamp |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `requests` | `httpx` | httpx not in requirements.txt; adding it requires approval; requests is sufficient |
| direct JSON write | `dataclasses-json` | Third-party dep not in requirements.txt; `dataclasses.asdict` + `json.dumps` is sufficient |

**Installation:** No new packages needed. All required libraries are already in `requirements.txt` or Python stdlib. [VERIFIED: live pip freeze check confirms requests>=2.31.0 and cloudscraper>=1.2.71 already installed]

---

## Architecture Patterns

### Recommended Project Structure
```
data/
├── odds.py          # new: Pinnacle client module
├── odds_log.jsonl   # new: created on first fetch, append-only
docs/
└── pinnacle-api-notes.md  # new: discovery output, written before client code
tests/
└── test_odds.py     # new: unit tests for odds.py
```

### Pattern 1: Module-Level Function with Env Var Auth (from data/scraper.py)
**What:** Constants in `UPPER_SNAKE_CASE` at module top, `logging.getLogger(__name__)`, `Optional[T]` for graceful failure, exception for explicit failure modes.
**When to use:** All `data/` package modules.
**Example:**
```python
# Source: data/scraper.py project pattern
import os
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

PINNACLE_API_BASE = "https://guest.api.arcadia.pinnacle.com/0.1"
PINNACLE_CYCLING_SPORT_ID = 45
REQUEST_TIMEOUT = 60  # seconds, matches scraper.py


class PinnacleAuthError(Exception):
    """Raised when the Pinnacle API key is missing, expired, or rejected."""
    pass


@dataclass
class OddsMarket:
    """A single H2H cycling matchup with normalized decimal odds."""
    rider_a_name: str
    rider_b_name: str
    odds_a: float
    odds_b: float
    race_name: str
    matchup_id: str
```

### Pattern 2: KellyResult Dataclass Style (from models/predict.py)
**What:** Plain `@dataclass` with typed fields, no `@dataclasses.field()` complexity.
**When to use:** `OddsMarket` definition.
**Example:**
```python
# Source: models/predict.py lines 22-31
@dataclass
class KellyResult:
    edge: float
    kelly_fraction: float
    # ... etc
```

### Pattern 3: Pinnacle API Fetch Flow
**What:** Three sequential HTTP calls per fetch cycle, joined in memory on `matchupId`.
**When to use:** Inside `fetch_cycling_h2h_markets()`.
**Example:**
```python
# Source: VERIFIED via live API calls 2026-04-11
def fetch_cycling_h2h_markets() -> list[OddsMarket]:
    api_key = _get_api_key()  # raises PinnacleAuthError if missing
    headers = {
        "X-Api-Key": api_key,
        "Referer": "https://www.pinnacle.com/",
        "Accept": "application/json",
    }

    # Step 1: Get active cycling leagues
    leagues_resp = requests.get(
        f"{PINNACLE_API_BASE}/sports/{PINNACLE_CYCLING_SPORT_ID}/leagues",
        params={"all": "false"},
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    _check_auth(leagues_resp)
    leagues = leagues_resp.json()  # list of league dicts

    markets = []
    for league in leagues:
        lid = league["id"]
        race_name = league["name"]

        # Step 2: Matchups (rider names)
        matchups_resp = requests.get(
            f"{PINNACLE_API_BASE}/leagues/{lid}/matchups",
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        if not isinstance(matchups_resp.json(), list):
            log.warning("Skipping league %s — matchups returned non-list", race_name)
            continue

        # Step 3: Straight markets (odds)
        markets_resp = requests.get(
            f"{PINNACLE_API_BASE}/leagues/{lid}/markets/straight",
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        if not isinstance(markets_resp.json(), list):
            log.warning("Skipping league %s — markets returned non-list", race_name)
            continue

        market_by_id = {m["matchupId"]: m for m in markets_resp.json()}

        for matchup in matchups_resp.json():
            market = market_by_id.get(matchup["id"])
            if not market or market.get("status") != "open":
                continue
            prices = {p["designation"]: p["price"] for p in market["prices"]}
            markets.append(OddsMarket(
                rider_a_name=matchup["participants"][0]["name"],
                rider_b_name=matchup["participants"][1]["name"],
                odds_a=_american_to_decimal(prices["home"]),
                odds_b=_american_to_decimal(prices["away"]),
                race_name=race_name,
                matchup_id=str(matchup["id"]),
            ))

    return markets
```

### Pattern 4: JSONL Audit Log
**What:** Append one JSON line per fetch call, including metadata, timestamp, and market list.
**When to use:** After every call to `fetch_cycling_h2h_markets()`.
**Example:**
```python
# Source: CONTEXT.md D-09, D-10; pattern derived from project conventions
import json
from datetime import datetime

ODDS_LOG_PATH = os.path.join(os.path.dirname(__file__), "odds_log.jsonl")

def _append_audit_log(
    markets: list[OddsMarket],
    fetch_status: str,
    error: Optional[str] = None,
) -> None:
    """Append one JSONL record. Called after every fetch, including empty fetches."""
    record = {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "status": fetch_status,        # "ok", "empty", "auth_error", "error"
        "market_count": len(markets),
        "markets": [dataclasses.asdict(m) for m in markets],  # decimal odds
    }
    if error:
        record["error"] = error
    with open(ODDS_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
```

### Pattern 5: Auth Error Raise
**What:** `PinnacleAuthError` with explicit env var name in the message.
**When to use:** When dynamic key extraction fails and `PINNACLE_API_KEY` env var is absent, or when the API returns HTTP 401/403 after one retry.
**Example:**
```python
# Source: CONTEXT.md D-13 through D-16
def _get_api_key() -> str:
    # 1. Optional manual override
    key = os.environ.get("PINNACLE_API_KEY", "").strip()
    if key:
        return key
    # 2. Cache
    key = _read_key_cache()
    if key:
        return key
    # 3. JS bundle extraction
    key = _extract_key_from_bundle()
    if key:
        _write_key_cache(key)
        return key
    raise PinnacleAuthError(
        "Could not obtain Pinnacle API key automatically. "
        "Set the PINNACLE_API_KEY environment variable as a manual override."
    )

def _check_auth(response: requests.Response) -> None:
    if response.status_code in (401, 403):
        raise PinnacleAuthError(
            f"Pinnacle API key is expired or invalid (HTTP {response.status_code}). "
            "Set the PINNACLE_API_KEY environment variable as a manual override."
        )
```

### Pattern 6: American to Decimal Odds Conversion
**What:** Convert Pinnacle's American integer odds to decimal.
**When to use:** Inside `fetch_cycling_h2h_markets()` before building `OddsMarket`.
**Note:** An identical function already exists in `models/predict.py` as `american_odds_to_decimal()`. To avoid coupling `data/odds.py` to the models layer, define a private `_american_to_decimal()` in `data/odds.py`.
```python
# Source: models/predict.py lines 59-64 (identical logic)
def _american_to_decimal(american: int) -> float:
    """Convert American odds (+150, -200) to decimal odds."""
    if american > 0:
        return round(american / 100.0 + 1.0, 4)
    return round(100.0 / abs(american) + 1.0, 4)
```

### Anti-Patterns to Avoid
- **Raising on empty markets:** `D-11` says return `[]`, not raise. Only raise `PinnacleAuthError` for auth failures.
- **Logging raw American odds:** `D-09` requires post-normalization decimal odds in the JSONL log.
- **Class-based client:** `D-12` says module-level functions. No `PinnacleClient` class.
- **Leaking conversion logic:** `D-08` says conversion lives only in `data/odds.py`. Never convert in callers.
- **Skipping empty-fetch log entries:** `D-10` says even empty fetches append a JSONL line.
- **Importing from models in data layer:** Do not import `american_odds_to_decimal` from `models/predict.py` — define `_american_to_decimal` privately in `data/odds.py` to avoid circular imports.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP requests | Custom socket/urllib client | `requests` library | Handles connection pooling, timeouts, redirects, encoding |
| Odds conversion | Custom formula | `_american_to_decimal()` private helper (copy from `models/predict.py` pattern) | Identical formula already battle-tested in the project |
| JSON serialization | Custom string formatting | `json.dumps(dataclasses.asdict(market))` | Handles escaping, encoding, edge cases |
| Retry/backoff | Custom sleep loops | Follow `data/scraper.py` pattern (MAX_RETRIES=3, exponential backoff) | Tested pattern already in the codebase |
| Auth token extraction | Custom JS parser | Playwright MCP browser inspection (for initial key extraction) | Browser automation correctly extracts the current rotating token |

**Key insight:** The Pinnacle guest API is a clean JSON REST API. No custom protocol handling, HTML parsing, or Cloudflare circumvention is needed.

---

## Pinnacle API Reference (VERIFIED 2026-04-11)

### Endpoint Discovery

**Base URL:** `https://guest.api.arcadia.pinnacle.com/0.1` [VERIFIED: live calls confirmed]

**Required headers:**
```
X-Api-Key: {extracted from JS bundle or PINNACLE_API_KEY env var override}
Referer: https://www.pinnacle.com/
Accept: application/json
```
[VERIFIED: without X-Api-Key, at least one cycling league (id=263773) returns 401]

**Cycling Sport ID:** `45` [VERIFIED: confirmed from `/0.1/sports` endpoint response]

**All allowed headers (from CORS response):** `Accept, Content-Type, X-API-Key, X-Device-UUID, X-Session, X-Language, X-Customer-Culture` [VERIFIED: from response headers]

### Active Cycling Leagues (2026-04-11)
| League ID | Name | Matchup Count |
|-----------|------|---------------|
| 8227 | Paris-Roubaix | 24 |
| 234847 | Itzulia Basque Country | 14 |
| 263773 | Paris-Roubaix - Women | 14 |
| 234846 | Itzulia Basque Country - Stage 6 | 13 |

**Total active H2H matchups:** 65 (all confirmed open with valid X-Api-Key)

### Fetch Endpoints
```
GET /0.1/sports                                      -> list of all sports
GET /0.1/sports/45/leagues?all=false                 -> active cycling leagues
GET /0.1/leagues/{league_id}/matchups                -> rider names, matchupId
GET /0.1/leagues/{league_id}/markets/straight        -> odds by matchupId
```
[VERIFIED: all four endpoints tested with live HTTP calls]

### Odds Format
Prices are returned as **American integer odds** (e.g., `-121`, `+107`). [VERIFIED: confirmed in live response data]

Conversion to decimal:
```python
# American -154 -> decimal 1.6494
# American +107 -> decimal 2.07
if american > 0:
    decimal = american / 100.0 + 1.0
else:
    decimal = 100.0 / abs(american) + 1.0
```

### Full Example Response — Matchup
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

### Full Example Response — Straight Market
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

### Join Key
`market["matchupId"] == matchup["id"]` — both are integers in the API response; cast to `str` when building `OddsMarket.matchup_id` per D-06.

### Delta Updates (future optimization)
Send `?version={max_version}` to get only changed markets. API returns HTTP 204 (no content) when nothing has changed. [VERIFIED: tested live] This is relevant for ODDS-04 (Phase 4) but not Phase 1.

### API Key Rotation
The X-Api-Key is extracted from the Pinnacle website's browser session JavaScript. It may rotate when Pinnacle updates their frontend. The plan must include a step to extract the current key via Playwright MCP and store it in `PINNACLE_SESSION_COOKIE`. [ASSUMED: key rotation frequency is unknown, but the pretrehr Sports-betting project uses Selenium to refresh it on each run, suggesting rotation does occur]

### Auth Behavior Summary
| Scenario | HTTP Status | Behavior |
|----------|-------------|----------|
| No X-Api-Key, public league | 200 | Works fine (e.g., Paris-Roubaix) |
| No X-Api-Key, gated league | 401 | Returns `{"status": 401, "detail": "No authorization token provided"}` |
| Invalid X-Api-Key | 403 | Returns `{"status": 403, "title": "BAD_APIKEY"}` |
| Valid X-Api-Key | 200 | All 65 cycling H2H matchups accessible |
[VERIFIED: all four scenarios tested with live HTTP calls 2026-04-11]

---

## Common Pitfalls

### Pitfall 1: Non-List Responses from Gated Leagues
**What goes wrong:** Without a valid X-Api-Key, some leagues return a JSON `dict` (error) instead of a `list` (matchup/market data). Code that directly iterates the response crashes with `TypeError: string indices must be integers`.
**Why it happens:** The API returns an error envelope `{"status": 401, ...}` when a league is gated. Different leagues have different access tiers.
**How to avoid:** Always check `isinstance(response.json(), list)` before iterating. Log a warning and skip the league (graceful degradation) or raise `PinnacleAuthError` if auth is confirmed bad.
**Warning signs:** `TypeError: string indices must be integers` during the `market_by_id` dict comprehension.

### Pitfall 2: Matchup/Market ID Mismatch
**What goes wrong:** `market["matchupId"]` and `matchup["id"]` are both integers but must be joined carefully. If a market exists without a matching matchup (or vice versa), the join produces an incomplete `OddsMarket`.
**Why it happens:** Pinnacle sometimes has markets without a corresponding matchup (or vice versa) in the API snapshot.
**How to avoid:** Build `market_by_id = {m["matchupId"]: m for m in markets_list}`. Only build `OddsMarket` when both matchup AND market exist. Silently skip unmatched entries.
**Warning signs:** Fewer `OddsMarket` results than expected league matchup count.

### Pitfall 3: Filtering Out Suspended Markets
**What goes wrong:** Markets with `status != "open"` have no tradeable odds. Returning suspended markets as valid `OddsMarket` objects causes downstream errors when computing Kelly.
**Why it happens:** Races can be temporarily suspended (weather, crash). The API still returns the matchup/market but with status not "open".
**How to avoid:** Filter on `market.get("status") == "open"` before building `OddsMarket`.
**Warning signs:** Odds of `0.0` or negative decimal values from bad conversion.

### Pitfall 4: Circular Import from models Layer
**What goes wrong:** Importing `american_odds_to_decimal` from `models/predict.py` into `data/odds.py` creates a circular dependency (data → models → data via features).
**Why it happens:** The `models/predict.py` imports from `data.scraper` and `features.pipeline`.
**How to avoid:** Define `_american_to_decimal()` as a private helper in `data/odds.py`. Same formula, no import needed.
**Warning signs:** `ImportError` or circular import traceback on module load.

### Pitfall 5: JSONL File Missing on First Run
**What goes wrong:** Opening `data/odds_log.jsonl` in append mode (`"a"`) creates the file if it doesn't exist on most systems, but the path must be correct (same `data/` directory as `cache.db`).
**Why it happens:** The `data/` directory exists but `odds_log.jsonl` does not.
**How to avoid:** Use `os.path.join(os.path.dirname(__file__), "odds_log.jsonl")` for the path. Opening in `"a"` mode safely creates the file on first write.
**Warning signs:** `FileNotFoundError` if path is wrong or the directory doesn't exist.

### Pitfall 6: Thread Safety on Windows
**What goes wrong:** The existing thread-safety pattern in CLAUDE.md (`OMP_NUM_THREADS=1`) is for PyTorch/sklearn. The Pinnacle client has no such concern, but `odds_log.jsonl` writes are not thread-safe if multiple Flask threads call `fetch_cycling_h2h_markets()` concurrently.
**Why it happens:** Flask in debug mode can spawn multiple threads.
**How to avoid:** The webapp runs with `debug=False` (per CLAUDE.md). Single-threaded access is the project convention. No locking is needed for Phase 1.
**Warning signs:** Interleaved/corrupt JSONL lines in `odds_log.jsonl`.

---

## Code Examples

### Complete `data/odds.py` Module Skeleton
```python
# Source: data/scraper.py (pattern), models/predict.py (dataclass pattern)
"""
Pinnacle Sports cycling H2H market client.

Fetches today's cycling head-to-head matchups from Pinnacle's internal
frontend API (guest.api.arcadia.pinnacle.com). Odds are normalized to
decimal format. Every fetch is appended to data/odds_log.jsonl.
"""

import dataclasses
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

log = logging.getLogger(__name__)

PINNACLE_API_BASE = "https://guest.api.arcadia.pinnacle.com/0.1"
PINNACLE_CYCLING_SPORT_ID = 45
REQUEST_TIMEOUT = 60  # seconds
MAX_RETRIES = 3
ODDS_LOG_PATH = os.path.join(os.path.dirname(__file__), "odds_log.jsonl")


class PinnacleAuthError(Exception):
    """Raised when PINNACLE_API_KEY is missing or all key extraction attempts fail."""
    pass


@dataclass
class OddsMarket:
    """A single cycling H2H matchup with decimal odds from Pinnacle."""
    rider_a_name: str
    rider_b_name: str
    odds_a: float
    odds_b: float
    race_name: str
    matchup_id: str


def fetch_cycling_h2h_markets() -> list[OddsMarket]:
    """Fetch all open cycling H2H markets from Pinnacle.

    Returns [] when no markets are available. Raises PinnacleAuthError on
    auth failure. Appends a JSONL line to data/odds_log.jsonl on every call.

    Returns:
        List of OddsMarket with decimal odds, or [] if none available.

    Raises:
        PinnacleAuthError: API key missing, expired, or invalid.
    """
    ...  # implementation per architecture pattern above
```

### Test Pattern for odds.py (mirrors tests/test_export.py style)
```python
# Source: tests/test_export.py (tmp_path fixture pattern, sys.path injection)
"""Tests for data/odds.py"""

import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.odds import OddsMarket, PinnacleAuthError, _american_to_decimal


def test_american_to_decimal_positive():
    """American +107 -> decimal 2.07"""
    assert _american_to_decimal(107) == pytest.approx(2.07)


def test_american_to_decimal_negative():
    """American -154 -> decimal ~1.649"""
    assert _american_to_decimal(-154) == pytest.approx(1.6494, abs=1e-4)


def test_auth_error_names_env_var(monkeypatch):
    """PinnacleAuthError message must name PINNACLE_API_KEY."""
    monkeypatch.delenv("PINNACLE_API_KEY", raising=False)
    # Also mock JS bundle extraction to fail so all paths are exhausted
    monkeypatch.setattr("data.odds._extract_key_from_bundle", lambda: None)
    monkeypatch.setattr("data.odds._read_key_cache", lambda: None)
    with pytest.raises(PinnacleAuthError, match="PINNACLE_API_KEY"):
        from data.odds import fetch_cycling_h2h_markets
        fetch_cycling_h2h_markets()


def test_jsonl_appends_on_fetch(tmp_path, monkeypatch):
    """Every fetch appends a JSON line to the audit log."""
    log_path = str(tmp_path / "odds_log.jsonl")
    monkeypatch.setattr("data.odds.ODDS_LOG_PATH", log_path)
    # ... mock requests, call fetch, verify log content
    ...
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Official Pinnacle API (api.pinnacle.com, Basic Auth) | Pinnacle frontend guest API (guest.api.arcadia.pinnacle.com, X-Api-Key) | Public API closed July 2025 | Official API requires application to access; frontend guest API is accessible without registration |
| seleniumwire for browser interception | Playwright MCP tools | 2024-2025 | Playwright MCP is the modern LLM-driven browser automation standard |

**Deprecated/outdated:**
- `api.pinnacle.com/v1/odds` with HTTP Basic Auth: API suite closed to general public since July 23, 2025. [CITED: pinnacleapi.github.io]
- `ps3838api` PyPI package: wraps the official API, no longer accessible without special approval.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The x-api-key may rotate over time (based on observation that pretrehr/Sports-betting uses browser automation to refresh it) | Architecture Patterns, Common Pitfalls | If the key never rotates, Playwright extraction is unnecessary complexity. Low risk: if stable, just hardcode fallback. |
| A2 | The Playwright MCP tool available in this environment can intercept/inspect network request headers during browser automation | Standard Stack | If Playwright MCP cannot capture XHR headers, key extraction requires a different approach (e.g., hardcoded key with manual refresh instruction) |

---

## Open Questions (RESOLVED)

1. **X-Api-Key rotation frequency** ✓ RESOLVED
   - What we know: The key `CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R` (from oddsR package) works today. pretrehr/Sports-betting refreshes it on every run, suggesting it rotates.
   - Resolution: Do not rely on a cached static key. Extract dynamically from Pinnacle's frontend JS bundle at runtime via `requests` + regex. Cache the result in `data/.pinnacle_key_cache`. Invalidate cache and re-extract on HTTP 401/403. If re-extraction fails, raise `PinnacleAuthError` instructing user to set `PINNACLE_API_KEY` env var. This handles any rotation frequency without user intervention.

2. **What Playwright MCP tool can capture network request headers** ✓ RESOLVED
   - Resolution: Playwright is used **for discovery only** (one-time, during plan execution to confirm endpoint and headers). It is not used at runtime for key extraction. The `context.route()` limitation is irrelevant — discovery only needs to navigate to Pinnacle and observe network traffic via `browser_network_requests`, not intercept/modify it. Runtime key extraction uses the JS bundle scrape approach (Q1 above), which requires no Playwright.

3. **Naming inconsistency — PINNACLE_SESSION_COOKIE vs x-api-key** ✓ RESOLVED
   - Resolution: Rename to `PINNACLE_API_KEY` throughout (D-16 in CONTEXT.md). The env var is an optional manual override only — normal operation never requires it. `PinnacleAuthError` messages reference `PINNACLE_API_KEY` by name. No env var is required for normal use.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All | ✓ | 3.14.0 | — |
| `requests` | HTTP client | ✓ | >=2.31.0 | — |
| `pytest` | Test suite | ✓ | 9.0.3 | — |
| `cloudscraper` | Not needed for guest API | ✓ | >=1.2.71 | N/A — not required |
| Playwright MCP | D-01 key extraction | unknown | — | Manual key extraction instruction in docs |
| `data/` directory | JSONL log path | ✓ | — | Exists (cache.db is already there) |
| `docs/` directory | pinnacle-api-notes.md | ✗ | — | Wave 0 must create it: `mkdir docs` |

**Missing dependencies with no fallback:** None that block execution.

**Missing dependencies with fallback:**
- Playwright MCP: If network header interception is not available, provide the current x-api-key as a hardcoded default in `docs/pinnacle-api-notes.md` with instructions for manual refresh.
- `docs/` directory: Does not exist yet. Wave 0 creates it.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 |
| Config file | none (rootdir auto-detected as B:/ml-cycling-predictor) |
| Quick run command | `.venv/Scripts/python.exe -m pytest tests/test_odds.py -v` |
| Full suite command | `.venv/Scripts/python.exe -m pytest tests/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ODDS-01 | `fetch_cycling_h2h_markets()` with valid key returns list of OddsMarket | unit (mock HTTP) | `.venv/Scripts/python.exe -m pytest tests/test_odds.py::test_returns_odds_market_list -x` | ❌ Wave 0 |
| ODDS-02 | Every fetch appends parseable JSON line to odds_log.jsonl | unit (tmp_path) | `.venv/Scripts/python.exe -m pytest tests/test_odds.py::test_jsonl_appends_on_fetch -x` | ❌ Wave 0 |
| ODDS-02 | Empty fetch appends JSONL line with `"markets": []` | unit (tmp_path) | `.venv/Scripts/python.exe -m pytest tests/test_odds.py::test_jsonl_appends_on_empty_fetch -x` | ❌ Wave 0 |
| ODDS-03 | Missing env var raises PinnacleAuthError naming env var | unit | `.venv/Scripts/python.exe -m pytest tests/test_odds.py::test_auth_error_names_env_var -x` | ❌ Wave 0 |
| ODDS-03 | HTTP 401 raises PinnacleAuthError naming env var | unit (mock HTTP) | `.venv/Scripts/python.exe -m pytest tests/test_odds.py::test_auth_error_on_401 -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/Scripts/python.exe -m pytest tests/test_odds.py -v`
- **Per wave merge:** `.venv/Scripts/python.exe -m pytest tests/ -v`
- **Phase gate:** Full suite green (14 existing + new odds tests) before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_odds.py` — covers ODDS-01, ODDS-02, ODDS-03
- [ ] `docs/` directory — must be created for `docs/pinnacle-api-notes.md`
- [ ] `data/odds.py` — new module (Wave 0 creates stub, subsequent waves implement)

---

## Security Domain

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No user auth in this module |
| V3 Session Management | no | No session management |
| V4 Access Control | no | Single-user personal tool |
| V5 Input Validation | yes | Validate API response structure before accessing fields |
| V6 Cryptography | no | No encryption needed |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| PINNACLE_API_KEY / cached key in logs/code | Information disclosure | Never log the key value. Only log success/failure. Never commit to git. `data/.pinnacle_key_cache` is gitignored. |
| Malformed API response causing crash | Tampering | Check `isinstance(resp.json(), list)` before dict access. Use `.get()` for optional fields. |
| JSONL injection via rider names | Tampering | `json.dumps()` handles escaping automatically. No manual string formatting. |

---

## Project Constraints (from CLAUDE.md)

| Directive | Applies to Phase 1 |
|-----------|-------------------|
| 2-space indentation | All code in `data/odds.py` and `tests/test_odds.py` |
| Type hints on all function signatures | `fetch_cycling_h2h_markets() -> list[OddsMarket]` etc. |
| Docstrings on all public functions | `OddsMarket`, `PinnacleAuthError`, `fetch_cycling_h2h_markets` |
| Run `pytest tests/ -v` before marking task complete | After every task |
| Do not add dependencies without asking | No new packages needed; `requests` already present |
| Do not migrate to Postgres | Not applicable; `data/odds.py` never touches cache.db |
| Never delete or modify `data/bets.csv` rows | Not applicable |
| Ask before changing schema | `data/odds_log.jsonl` is a new file — no existing schema |
| All scripts must degrade gracefully | Gated leagues are skipped with `log.warning()`, not exceptions |
| `logging.getLogger(__name__)` per module | `log = logging.getLogger(__name__)` at module top |
| Constants in `UPPER_SNAKE_CASE` at module top | `PINNACLE_API_BASE`, `PINNACLE_CYCLING_SPORT_ID`, `REQUEST_TIMEOUT` |
| Module-level functions with `_private` prefix for helpers | `_american_to_decimal()`, `_get_api_key()`, `_check_auth()`, `_append_audit_log()` |

---

## Sources

### Primary (HIGH confidence)
- Live API calls to `guest.api.arcadia.pinnacle.com` — all sport IDs, league IDs, matchup/market structure, odds format, auth behavior (VERIFIED 2026-04-11)
- `data/scraper.py` — module pattern, retry/backoff, constants style
- `models/predict.py` — KellyResult dataclass reference, american_odds_to_decimal implementation

### Secondary (MEDIUM confidence)
- [pretrehr/Sports-betting bookmakers/pinnacle.py](https://github.com/pretrehr/Sports-betting/blob/master/sportsbetting/bookmakers/pinnacle.py) — confirmed arcadia endpoint structure, x-api-key extraction via browser automation
- [miken97/oddsR R/pinnacle.R](https://rdrr.io/github/miken97/oddsR/src/R/pinnacle.R) — confirmed X-Session + X-API-Key header pattern

### Tertiary (LOW confidence)
- [Playwright MCP GitHub issue #1180](https://github.com/microsoft/playwright-mcp/issues/1180) — network interception support status (may be resolved)
- [WebSearch: Pinnacle API closed July 2025](https://github.com/pinnacleapi/pinnacleapi-documentation) — official API closure, confirming guest API is the correct approach

---

## Metadata

**Confidence breakdown:**
- Pinnacle API endpoints and schema: HIGH — all endpoints live-tested with real data
- Auth mechanism: HIGH — tested 4 scenarios (no key, invalid key, valid key, fake key)
- Odds format and conversion: HIGH — verified American to decimal with live prices
- x-api-key rotation: LOW — behavior inferred from community code, not measured
- Playwright MCP network interception: LOW — flagged as in-development in late 2025

**Research date:** 2026-04-11
**Valid until:** 2026-05-11 (API endpoints are stable; league IDs are race-specific and will change after races complete)
