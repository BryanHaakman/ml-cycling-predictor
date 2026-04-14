"""
Pinnacle cycling H2H market client.

Fetches today's active cycling H2H matchups from Pinnacle's public guest API
(guest.api.arcadia.pinnacle.com), normalizes American odds to decimal, and appends
a JSONL audit entry to data/odds_log.jsonl after every fetch (including empty fetches).

The guest API is publicly accessible with no authentication required. Two sport-level
calls are made per fetch (sport matchups + sport markets), rather than one call per
league. Matchups where either participant is "The Field" are filtered out — these are
outright bets, not H2H matchups.

X-Api-Key lookup order (courtesy header — not enforced by guest endpoints):
  1. data/.pinnacle_key_cache (disk cache from previous extraction)
  2. JS bundle extraction from www.pinnacle.com (slowest, refreshes cache)
  3. Raise PinnacleAuthError

On HTTP 401/403: cache is invalidated and extraction is retried exactly once.
A second consecutive 401/403 raises PinnacleAuthError immediately.

Public interface:
  - OddsMarket       — dataclass with decimal odds per H2H matchup
  - PinnacleAuthError — raised when X-Api-Key is missing or rejected
  - fetch_cycling_h2h_markets() — main entry point; returns list[OddsMarket]
"""

import dataclasses
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PINNACLE_API_BASE: str = "https://guest.api.arcadia.pinnacle.com/0.1"
PINNACLE_CYCLING_SPORT_ID: int = 45
REQUEST_TIMEOUT: int = 60  # seconds, matches data/scraper.py pattern
KEY_CACHE_PATH: str = os.path.join(os.path.dirname(__file__), ".pinnacle_key_cache")
ODDS_LOG_PATH: str = os.path.join(os.path.dirname(__file__), "odds_log.jsonl")
PINNACLE_HOME_URL: str = "https://www.pinnacle.ca/"

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PinnacleAuthError(Exception):
  """Raised when X-Api-Key cannot be extracted or is rejected by Pinnacle API.

  The guest API does not enforce authentication, so this error should be rare
  in practice. It may occur if Pinnacle changes their API structure and the
  JS bundle key extraction patterns no longer match.
  """


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class OddsMarket:
  """A single H2H cycling matchup with normalized decimal odds.

  Odds are always decimal (never American) — conversion happens inside
  fetch_cycling_h2h_markets() before any OddsMarket is created.
  """

  rider_a_name: str
  rider_b_name: str
  odds_a: float
  odds_b: float
  race_name: str
  matchup_id: str


# ---------------------------------------------------------------------------
# Odds conversion
# ---------------------------------------------------------------------------

def _american_to_decimal(american: int | float) -> float:
  """Convert American odds to decimal format.

  Private — do NOT import from models/predict.py (circular import risk).
  This uses the identical formula from models/predict.py::american_odds_to_decimal().

  Args:
    american: American odds value (e.g., +107, -154, or -154.5).

  Returns:
    Decimal odds rounded to 4 decimal places.

  Examples:
    +107 -> 2.07
    -154 -> 1.6494
    -100 -> 2.0
  """
  if american == 0:
    raise ValueError("American odds of 0 are invalid")
  if american > 0:
    return round(american / 100.0 + 1.0, 4)
  return round(100.0 / abs(american) + 1.0, 4)


# ---------------------------------------------------------------------------
# Key extraction from JS bundle
# ---------------------------------------------------------------------------

def _extract_key_from_bundle() -> Optional[str]:
  """Fetch Pinnacle's main JS bundle and regex-extract the 32-char API key.

  Method:
    1. GET https://www.pinnacle.ca/ HTML
    2. Find the main JS bundle <script src="..."> tag
    3. GET https://www.pinnacle.ca{bundle_path}
    4. Regex-match for the API key pattern (try multiple patterns)
    5. Return the first match, or None if not found

  Returns:
    The extracted 32-character API key, or None if extraction fails.

  Logs a warning on failure; does not raise — caller handles the None case.
  """
  try:
    home_resp = requests.get(PINNACLE_HOME_URL, timeout=REQUEST_TIMEOUT)
    home_resp.raise_for_status()
    html = home_resp.text

    # Find the main JS bundle path — try several common patterns
    bundle_patterns = [
      r'src="(/[^"]*main\.[a-f0-9]+\.chunk\.js)"',
      r'src="(/[^"]*\.[a-f0-9]+\.js)"',
      r'src="(/en/sports/[^"]*\.js)"',
    ]

    bundle_path: Optional[str] = None
    for pattern in bundle_patterns:
      match = re.search(pattern, html)
      if match:
        bundle_path = match.group(1)
        break

    if not bundle_path:
      log.warning("_extract_key_from_bundle: could not find main JS bundle in Pinnacle HTML")
      return None

    bundle_url = f"https://www.pinnacle.ca{bundle_path}"
    log.info("_extract_key_from_bundle: fetching bundle %s", bundle_url)
    bundle_resp = requests.get(bundle_url, timeout=REQUEST_TIMEOUT)
    bundle_resp.raise_for_status()
    js_content = bundle_resp.text

    # Try multiple key extraction patterns
    key_patterns = [
      r'"X-Api-Key"\s*:\s*"([A-Za-z0-9]{32})"',
      r'apiKey["\s:=]+([A-Za-z0-9]{32})',
      r'"x-api-key"\s*:\s*"([A-Za-z0-9]{32})"',
      r'X-Api-Key["\s:=]+([A-Za-z0-9]{32})',
    ]

    for pattern in key_patterns:
      match = re.search(pattern, js_content)
      if match:
        key = match.group(1)
        log.info("_extract_key_from_bundle: extracted API key via pattern %r", pattern)
        return key

    log.warning("_extract_key_from_bundle: no API key pattern matched in JS bundle")
    return None

  except requests.RequestException as e:
    log.warning("_extract_key_from_bundle: HTTP error during extraction: %s", e)
    return None
  except Exception as e:
    log.warning("_extract_key_from_bundle: unexpected error: %s", e)
    return None


# ---------------------------------------------------------------------------
# Key cache management
# ---------------------------------------------------------------------------

def _invalidate_key_cache() -> None:
  """Delete KEY_CACHE_PATH if it exists. Called on 401/403 before retry."""
  try:
    os.remove(KEY_CACHE_PATH)
    log.info("_invalidate_key_cache: deleted %s", KEY_CACHE_PATH)
  except FileNotFoundError:
    pass


# ---------------------------------------------------------------------------
# Key resolution
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
  """Resolve the X-Api-Key using the lookup chain: cache -> JS bundle.

  The X-Api-Key is sent as a courtesy header only — the guest API does not
  enforce it. Lookup order:
    1. KEY_CACHE_PATH disk cache — if file exists and is non-empty, return contents
    2. _extract_key_from_bundle() — if returns a key, write to cache and return it
    3. All paths exhausted -> raise PinnacleAuthError

  Returns:
    The API key string (stripped of whitespace).

  Raises:
    PinnacleAuthError: If all lookup paths are exhausted.
  """
  # 1. Disk cache
  if os.path.exists(KEY_CACHE_PATH):
    try:
      with open(KEY_CACHE_PATH, "r", encoding="utf-8") as f:
        cached = f.read().strip()
      if cached:
        log.info("_get_api_key: using cached key from %s", KEY_CACHE_PATH)
        return cached
    except OSError as e:
      log.warning("_get_api_key: could not read key cache: %s", e)

  # 2. JS bundle extraction
  log.info("_get_api_key: no cache — attempting JS bundle extraction")
  extracted = _extract_key_from_bundle()
  if extracted:
    try:
      with open(KEY_CACHE_PATH, "w", encoding="utf-8") as f:
        f.write(extracted)
      log.info("_get_api_key: wrote extracted key to cache %s", KEY_CACHE_PATH)
    except OSError as e:
      log.warning("_get_api_key: could not write key cache: %s", e)
    return extracted

  # 3. All paths exhausted
  raise PinnacleAuthError(
    "Pinnacle API key could not be extracted from JS bundle. "
    "Provide a cached key at data/.pinnacle_key_cache as a manual override."
  )


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

def _check_auth(response: requests.Response) -> None:
  """Raise PinnacleAuthError on HTTP 401 or 403.

  Args:
    response: The HTTP response from a Pinnacle API request.

  Raises:
    PinnacleAuthError: If response status is 401 or 403.
  """
  if response.status_code in (401, 403):
    raise PinnacleAuthError(
      f"Pinnacle API returned HTTP {response.status_code}. "
      "The guest API key may have changed — delete data/.pinnacle_key_cache to force re-extraction."
    )


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def _append_audit_log(
  markets: list,
  fetch_status: str,
  error: Optional[str] = None,
) -> None:
  """Append one JSONL record to ODDS_LOG_PATH after every fetch.

  Record is always written — including empty fetches. Markets are
  serialized as post-normalization decimal odds dicts.

  Args:
    markets: List of OddsMarket objects (may be empty).
    fetch_status: One of "ok", "empty", "auth_error", or "error".
    error: Optional error message string (only included when not None).
  """
  record: dict = {
    "fetched_at": datetime.now(timezone.utc).isoformat(),
    "status": fetch_status,
    "market_count": len(markets),
    "markets": [dataclasses.asdict(m) for m in markets],
  }
  if error is not None:
    record["error"] = error

  try:
    with open(ODDS_LOG_PATH, "a", encoding="utf-8") as f:
      f.write(json.dumps(record) + "\n")
  except OSError as e:
    log.warning("_append_audit_log: could not write to %s: %s", ODDS_LOG_PATH, e)


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def fetch_cycling_h2h_markets() -> list:
  """Fetch today's cycling H2H matchups from Pinnacle's public guest API.

  Uses the sport-level 2-call pattern:
    1. GET /sports/45/matchups — all cycling matchups with participant names
    2. GET /sports/45/markets/straight — all cycling odds, keyed by matchupId

  Matchups where either participant is "The Field" are filtered out (these are
  outright winner bets, not H2H matchups). The two responses are joined in
  memory on matchup["id"] == market["matchupId"].

  No session token or login is required — the guest API is publicly accessible.
  X-Api-Key is sent as a courtesy header only (not enforced by guest endpoints).

  Auth retry logic (defensive — unlikely on guest API):
    1. Call _get_api_key() — raises PinnacleAuthError if all paths exhausted
    2. Make API requests; on 401/403: invalidate cache, call _get_api_key() again
    3. If second attempt also 401/403: raise PinnacleAuthError immediately
       (retry is bounded to exactly one attempt — no infinite loop)

  Returns:
    list[OddsMarket]: Active H2H matchups with decimal odds. Empty list if no
    cycling markets are open today (never raises for empty results).

  Raises:
    PinnacleAuthError: If the API key is missing or rejected after one retry.
    requests.RequestException: On network errors (timeout, connection failure).
  """
  api_key = _get_api_key()
  retried = False

  while True:
    headers = {
      "X-Api-Key": api_key,
      "Referer": PINNACLE_HOME_URL,
      "Accept": "application/json",
    }
    # No X-Session header — the guest API requires no session token

    try:
      # Call 1: all cycling matchups (sport-level, single call)
      matchups_resp = requests.get(
        f"{PINNACLE_API_BASE}/sports/{PINNACLE_CYCLING_SPORT_ID}/matchups",
        params={"withSpecials": "false"},
        headers=headers,
        timeout=REQUEST_TIMEOUT,
      )

      # Auth check (unlikely on guest API, but defensive)
      if matchups_resp.status_code in (401, 403):
        if retried:
          _append_audit_log([], "auth_error", f"HTTP {matchups_resp.status_code} after retry")
          raise PinnacleAuthError(
            f"Pinnacle API returned HTTP {matchups_resp.status_code} after retry. "
            "Delete data/.pinnacle_key_cache to force key re-extraction."
          )
        log.warning(
          "fetch_cycling_h2h_markets: received HTTP %s, invalidating cache and retrying",
          matchups_resp.status_code,
        )
        _invalidate_key_cache()
        api_key = _get_api_key()
        retried = True
        continue

      _check_auth(matchups_resp)

      matchups_data = matchups_resp.json()
      if not isinstance(matchups_data, list):
        log.warning(
          "fetch_cycling_h2h_markets: matchups response was not a list, got %r",
          type(matchups_data).__name__,
        )
        _append_audit_log([], "empty")
        return []

      # Call 2: all cycling markets (sport-level, single call)
      markets_resp = requests.get(
        f"{PINNACLE_API_BASE}/sports/{PINNACLE_CYCLING_SPORT_ID}/markets/straight",
        params={"primaryOnly": "false", "withSpecials": "false"},
        headers=headers,
        timeout=REQUEST_TIMEOUT,
      )
      _check_auth(markets_resp)
      markets_resp.raise_for_status()
      markets_data = markets_resp.json()
      if not isinstance(markets_data, list):
        log.warning(
          "fetch_cycling_h2h_markets: markets response was not a list, got %r",
          type(markets_data).__name__,
        )
        _append_audit_log([], "empty")
        return []

      # Build lookup: matchupId -> market
      market_by_id: dict = {m["matchupId"]: m for m in markets_data}

      # Join matchups with markets; filter "The Field" outright bets
      markets_list: list = []
      for matchup in matchups_data:
        participants = matchup.get("participants", [])
        if len(participants) < 2:
          log.warning(
            "fetch_cycling_h2h_markets: matchup %s has fewer than 2 participants, skipping",
            matchup.get("id"),
          )
          continue

        rider_a = participants[0]["name"]
        rider_b = participants[1]["name"]

        # Filter outright bets (rider vs "The Field")
        if rider_a == "The Field" or rider_b == "The Field":
          continue

        market = market_by_id.get(matchup["id"])
        if not market or market.get("status") != "open":
          continue

        prices = {p["designation"]: p["price"] for p in market.get("prices", [])}
        home_price = prices.get("home")
        away_price = prices.get("away")
        if home_price is None or away_price is None:
          log.warning(
            "fetch_cycling_h2h_markets: matchup %s missing home/away prices, skipping",
            matchup["id"],
          )
          continue

        # race_name comes from the matchup's embedded league object
        race_name = matchup.get("league", {}).get("name", f"Matchup {matchup['id']}")

        markets_list.append(OddsMarket(
          rider_a_name=rider_a,
          rider_b_name=rider_b,
          odds_a=_american_to_decimal(home_price),
          odds_b=_american_to_decimal(away_price),
          race_name=race_name,
          matchup_id=str(matchup["id"]),
        ))

      status = "ok" if markets_list else "empty"
      _append_audit_log(markets_list, status)
      return markets_list

    except requests.RequestException as e:
      log.warning("fetch_cycling_h2h_markets: network error: %s", e)
      _append_audit_log([], "error", str(e))
      raise
