# Pinnacle Preload Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Load from Pinnacle" button to the existing batch prediction UI that auto-populates all today's H2H cycling matchups — odds, rider PCS URLs, and live stage context — so the user hits Calculate and gets predictions without any manual data entry.

**Architecture:** A single Flask endpoint (`POST /api/pinnacle/load`) fetches Pinnacle odds, resolves rider names to PCS URLs via fuzzy matching, fetches live stage details from PCS using the `procyclingstats` library, and returns a structured payload the existing batch prediction UI pre-fills. No new pages. No email. No GenAI. No VPS changes.

**Tech Stack:** `rapidfuzz` (name matching), `procyclingstats` (live stage fetch), `requests` (Pinnacle API), existing `models/predict.py`, existing Flask app.

---

## File Map

**New files:**
- `data/odds.py` — Pinnacle internal API client
- `data/name_resolver.py` — fuzzy Pinnacle name → PCS rider URL
- `data/name_mappings.json` — confirmed mappings cache (starts as `{}`)
- `intelligence/__init__.py` — package marker
- `intelligence/models.py` — OddsMarket, ResolvedMarket, StageContext dataclasses
- `intelligence/stage_context.py` — live PCS stage fetch via procyclingstats
- `tests/test_name_resolver.py`
- `tests/test_stage_context.py`
- `tests/test_pinnacle_load.py`

**Modified files:**
- `webapp/app.py` — add `POST /api/pinnacle/load` endpoint
- `webapp/templates/` — add "Load from Pinnacle" button to existing batch prediction UI
- `requirements.txt` — add `rapidfuzz`
- `.env.example` — add `PINNACLE_SESSION_COOKIE`, `PINNACLE_API_URL`

---

## Task 1: Data Models

**Files:**
- Create: `intelligence/__init__.py`
- Create: `intelligence/models.py`
- Create: `data/name_mappings.json`

- [ ] **Step 1: Create the intelligence package**

```python
# intelligence/__init__.py
# (empty)
```

```python
# intelligence/models.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class OddsMarket:
  """One H2H market as returned by Pinnacle."""
  market_id: str
  race_name: str       # Pinnacle display name e.g. "Tour de Romandie - Stage 4"
  stage_name: str
  rider_a_name: str    # Pinnacle display name
  rider_b_name: str
  odds_a: float        # decimal odds
  odds_b: float
  fetched_at: datetime


@dataclass
class ResolvedMarket:
  """OddsMarket with PCS rider URLs resolved."""
  market: OddsMarket
  rider_a_url: Optional[str]   # None if unresolved
  rider_b_url: Optional[str]
  rider_a_confidence: float    # 0.0–1.0
  rider_b_confidence: float
  resolved: bool               # True only if both riders resolved


@dataclass
class StageContext:
  """Live stage details from PCS, mapped to race_params for predict_manual()."""
  race_name: str
  stage_name: str
  race_date: str           # ISO e.g. "2026-05-01"
  distance: float          # km
  vertical_meters: float
  profile_icon: str        # "p0"–"p5"
  profile_score: float
  is_one_day_race: bool
  stage_type: str          # "RR" | "ITT" | "TTT"
  num_climbs: int
  uci_tour: str            # "1.UWT" | "2.UWT" etc.
  race_base_url: str       # PCS relative URL e.g. "race/tour-de-romandie"
  source: str              # "pcs" | "neutral_defaults"

  def to_race_params(self) -> dict:
    return {
      "distance": self.distance,
      "vertical_meters": self.vertical_meters,
      "profile_icon": self.profile_icon,
      "profile_score": self.profile_score,
      "is_one_day_race": self.is_one_day_race,
      "stage_type": self.stage_type,
      "race_date": self.race_date,
      "race_base_url": self.race_base_url,
      "num_climbs": self.num_climbs,
      "uci_tour": self.uci_tour,
    }
```

- [ ] **Step 2: Create empty name mappings cache**

```bash
echo '{}' > data/name_mappings.json
```

- [ ] **Step 3: Commit**

```bash
git add intelligence/__init__.py intelligence/models.py data/name_mappings.json
git commit -m "feat: add intelligence package with data models"
```

---

## Task 2: Pinnacle Odds Client

**Files:**
- Create: `data/odds.py`
- Create: `tests/test_odds.py`

**⚠️ This task requires a one-time manual research step first.**

- [ ] **Step 1: Discover Pinnacle's internal odds API endpoint**

Open Pinnacle in Chrome while logged in. Navigate to the cycling H2H betting section. Open DevTools (F12) → Network tab → filter by "Fetch/XHR". Reload or navigate to cycling H2H markets. Find the XHR request that returns H2H cycling matchups as JSON.

Record:
- Full request URL (including query params)
- Which request headers carry authentication (Cookie, X-Api-Key, etc.)
- JSON response structure: which fields contain race name, rider names, odds

Set two environment variables before continuing:
```bash
PINNACLE_API_URL=<the discovered URL>
PINNACLE_SESSION_COOKIE=<cookie header value from DevTools>
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_odds.py
import json
import pytest
from datetime import datetime
from unittest.mock import patch
from data.odds import fetch_cycling_markets, append_to_odds_log
from intelligence.models import OddsMarket


def _mock_raw():
  # Replace with one real item from the discovered API response format
  return [{"id": "123", "home": "Tadej Pogacar", "away": "Jonas Vingegaard",
           "homeOdds": 1.65, "awayOdds": 2.30, "league": "Tour de Romandie Stage 4"}]


def test_fetch_returns_odds_markets():
  with patch("data.odds._call_pinnacle_api", return_value=_mock_raw()):
    markets = fetch_cycling_markets("fake_cookie")
  assert isinstance(markets, list)
  assert all(isinstance(m, OddsMarket) for m in markets)


def test_fetch_raises_permission_error_on_401():
  with patch("data.odds._call_pinnacle_api", side_effect=PermissionError("expired")):
    with pytest.raises(PermissionError):
      fetch_cycling_markets("bad_cookie")


def test_append_to_odds_log(tmp_path):
  log_path = str(tmp_path / "odds.jsonl")
  market = OddsMarket("1", "TdR Stage 4", "Stage 4", "Rider A", "Rider B",
                      1.8, 2.0, datetime(2026, 5, 1, 17, 0))
  append_to_odds_log([market], path=log_path)
  data = json.loads(open(log_path).readline())
  assert data["market_id"] == "1"
  assert data["odds_a"] == 1.8
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_odds.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'data.odds'`

- [ ] **Step 4: Implement `data/odds.py`**

Fill in `_is_cycling_h2h()` and `_parse_market()` based on Step 1 discovery. Everything else is complete.

```python
# data/odds.py
"""
Pinnacle internal API client for H2H cycling markets.

Endpoint and response format discovered via browser DevTools (see Step 1).
Document your findings here after discovery:
  URL: <fill in>
  Auth: <fill in>
  Response structure: <fill in>
"""

import json
import logging
import os
from datetime import datetime, timezone

import requests

from intelligence.models import OddsMarket

log = logging.getLogger(__name__)

PINNACLE_API_URL = os.environ.get("PINNACLE_API_URL", "")
_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "odds_log.jsonl")


def fetch_cycling_markets(session_cookie: str) -> list[OddsMarket]:
  """
  Fetch all live H2H cycling markets from Pinnacle.

  Raises:
    PermissionError: Session cookie invalid/expired.
    RuntimeError: Other HTTP errors.
  """
  raw = _call_pinnacle_api(session_cookie)
  markets = [_parse_market(item) for item in raw if _is_cycling_h2h(item)]
  log.info("Fetched %d cycling H2H markets", len(markets))
  return markets


def _call_pinnacle_api(session_cookie: str) -> list[dict]:
  headers = {
    "Cookie": session_cookie,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
  }
  resp = requests.get(PINNACLE_API_URL, headers=headers, timeout=30)
  if resp.status_code in (401, 403):
    raise PermissionError("Pinnacle session expired — update PINNACLE_SESSION_COOKIE")
  resp.raise_for_status()
  return resp.json()


def _is_cycling_h2h(item: dict) -> bool:
  """Return True if this market is a cycling H2H. Fill in after Step 1 discovery."""
  raise NotImplementedError("fill in after API discovery")


def _parse_market(item: dict) -> OddsMarket:
  """Map one raw item to OddsMarket. Fill in after Step 1 discovery."""
  raise NotImplementedError("fill in after API discovery")


def append_to_odds_log(markets: list[OddsMarket], path: str = _LOG_PATH) -> None:
  """Append markets to append-only JSONL audit log."""
  with open(path, "a", encoding="utf-8") as f:
    for m in markets:
      f.write(json.dumps({
        "market_id": m.market_id,
        "race_name": m.race_name,
        "stage_name": m.stage_name,
        "rider_a_name": m.rider_a_name,
        "rider_b_name": m.rider_b_name,
        "odds_a": m.odds_a,
        "odds_b": m.odds_b,
        "fetched_at": m.fetched_at.isoformat(),
      }) + "\n")


def load_latest_markets(path: str = _LOG_PATH) -> list[OddsMarket]:
  """Load most recent fetch from log (same fetched_at timestamp)."""
  all_markets: list[OddsMarket] = []
  try:
    with open(path, encoding="utf-8") as f:
      for line in f:
        d = json.loads(line)
        all_markets.append(OddsMarket(
          market_id=d["market_id"], race_name=d["race_name"],
          stage_name=d["stage_name"], rider_a_name=d["rider_a_name"],
          rider_b_name=d["rider_b_name"], odds_a=d["odds_a"], odds_b=d["odds_b"],
          fetched_at=datetime.fromisoformat(d["fetched_at"]),
        ))
  except FileNotFoundError:
    return []
  if not all_markets:
    return []
  latest_ts = max(m.fetched_at for m in all_markets)
  return [m for m in all_markets if m.fetched_at == latest_ts]
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_odds.py -v
```
Expected: `test_fetch_returns_odds_markets`, `test_fetch_raises_permission_error_on_401`, `test_append_to_odds_log` all PASS. (`_is_cycling_h2h`/`_parse_market` stubs not tested until Step 1 complete.)

- [ ] **Step 6: Add to requirements and commit**

```
# requirements.txt — add:
rapidfuzz
```

```bash
pip install rapidfuzz
git add data/odds.py tests/test_odds.py requirements.txt
git commit -m "feat: add Pinnacle odds client (endpoint TBD after API discovery)"
```

---

## Task 3: Name Resolver

**Files:**
- Create: `data/name_resolver.py`
- Create: `tests/test_name_resolver.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_name_resolver.py
import json
import pytest
from data.name_resolver import normalize_name, resolve_name, resolve_all
from intelligence.models import OddsMarket
from datetime import datetime
from unittest.mock import patch


def test_normalize_strips_accents():
  assert normalize_name("Tadej Pogačar") == "pogacar tadej"


def test_normalize_handles_comma_last_first():
  assert normalize_name("Van der Poel, Mathieu") == "mathieu poel van der"


def test_normalize_lowercases_and_sorts():
  assert normalize_name("JONAS VINGEGAARD") == "jonas vingegaard"


def _riders():
  return [
    {"url": "rider/tadej-pogacar", "name": "Tadej Pogačar"},
    {"url": "rider/mathieu-van-der-poel", "name": "Mathieu van der Poel"},
    {"url": "rider/jonas-vingegaard", "name": "Jonas Vingegaard"},
  ]


def test_cache_hit_returns_full_confidence(tmp_path):
  cache = {"Tadej Pogacar": "rider/tadej-pogacar"}
  cp = str(tmp_path / "cache.json")
  open(cp, "w").write(json.dumps(cache))
  url, conf = resolve_name("Tadej Pogacar", riders=[], cache_path=cp)
  assert url == "rider/tadej-pogacar"
  assert conf == 1.0


def test_fuzzy_match_above_threshold(tmp_path):
  cp = str(tmp_path / "cache.json")
  open(cp, "w").write("{}")
  url, conf = resolve_name("Pogacar Tadej", riders=_riders(), cache_path=cp)
  assert url == "rider/tadej-pogacar"
  assert conf >= 0.85


def test_unknown_name_returns_none(tmp_path):
  cp = str(tmp_path / "cache.json")
  open(cp, "w").write("{}")
  url, conf = resolve_name("Completely Unknown XYZ", riders=_riders(), cache_path=cp)
  assert url is None
  assert conf < 0.70


def test_resolve_all_marks_both_resolved(tmp_path):
  cp = str(tmp_path / "cache.json")
  open(cp, "w").write("{}")
  market = OddsMarket("1", "TdR", "S4", "Tadej Pogacar", "Jonas Vingegaard",
                      1.65, 2.30, datetime.utcnow())
  with patch("data.name_resolver._load_riders_from_db", return_value=_riders()):
    results = resolve_all([market], db_path=":memory:", cache_path=cp)
  assert results[0].resolved is True
  assert results[0].rider_a_url == "rider/tadej-pogacar"
  assert results[0].rider_b_url == "rider/jonas-vingegaard"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_name_resolver.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'data.name_resolver'`

- [ ] **Step 3: Implement `data/name_resolver.py`**

```python
# data/name_resolver.py
"""
Maps Pinnacle display names to PCS rider URLs.

Confidence tiers:
  1.0   — exact cache hit
  ≥0.85 — fuzzy auto-accept, saved to cache
  0.70–0.84 — used as best guess, logged to unresolved_names.json
  <0.70 — returns None, matchup skipped
"""

import json
import logging
import os
import unicodedata
from typing import Optional

from rapidfuzz import fuzz, process

from data.scraper import get_db, DB_PATH
from intelligence.models import OddsMarket, ResolvedMarket

log = logging.getLogger(__name__)

_DIR = os.path.dirname(os.path.dirname(__file__))
DEFAULT_CACHE = os.path.join(_DIR, "data", "name_mappings.json")
UNRESOLVED_LOG = os.path.join(_DIR, "data", "unresolved_names.json")
AUTO_THRESHOLD = 0.85
LOW_THRESHOLD = 0.70


def normalize_name(name: str) -> str:
  """Strip accents, handle 'Last, First' ordering, lowercase, sort tokens."""
  nfkd = unicodedata.normalize("NFKD", name)
  ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
  if "," in ascii_str:
    parts = [p.strip() for p in ascii_str.split(",")]
    ascii_str = " ".join(reversed(parts))
  return " ".join(sorted(ascii_str.lower().split()))


def resolve_name(
  pinnacle_name: str,
  riders: list[dict],
  cache_path: str = DEFAULT_CACHE,
) -> tuple[Optional[str], float]:
  cache = _load_json(cache_path)
  if pinnacle_name in cache:
    return cache[pinnacle_name], 1.0

  if not riders:
    return None, 0.0

  norm_q = normalize_name(pinnacle_name)
  choices = {normalize_name(r["name"]): r["url"] for r in riders}
  result = process.extractOne(norm_q, choices.keys(), scorer=fuzz.token_sort_ratio)
  if not result:
    return None, 0.0

  matched_norm, score, _ = result
  confidence = score / 100.0
  url = choices[matched_norm]

  if confidence >= AUTO_THRESHOLD:
    cache[pinnacle_name] = url
    _save_json(cache, cache_path)
    log.info("Auto-resolved '%s' → %s (%.2f)", pinnacle_name, url, confidence)
    return url, confidence

  if confidence >= LOW_THRESHOLD:
    _log_unresolved(pinnacle_name, url, confidence)
    log.warning("Low-confidence '%s' → %s (%.2f)", pinnacle_name, url, confidence)
    return url, confidence

  log.warning("Could not resolve '%s' (best %.2f)", pinnacle_name, confidence)
  return None, confidence


def resolve_all(
  markets: list[OddsMarket],
  db_path: str = DB_PATH,
  cache_path: str = DEFAULT_CACHE,
) -> list[ResolvedMarket]:
  riders = _load_riders_from_db(db_path)
  out = []
  for m in markets:
    url_a, conf_a = resolve_name(m.rider_a_name, riders, cache_path)
    url_b, conf_b = resolve_name(m.rider_b_name, riders, cache_path)
    out.append(ResolvedMarket(
      market=m, rider_a_url=url_a, rider_b_url=url_b,
      rider_a_confidence=conf_a, rider_b_confidence=conf_b,
      resolved=url_a is not None and url_b is not None,
    ))
  return out


def _load_riders_from_db(db_path: str) -> list[dict]:
  conn = get_db(db_path)
  rows = conn.execute("SELECT url, name FROM riders WHERE name IS NOT NULL").fetchall()
  conn.close()
  return [{"url": r["url"], "name": r["name"]} for r in rows]


def _load_json(path: str) -> dict:
  try:
    return json.loads(open(path, encoding="utf-8").read())
  except (FileNotFoundError, json.JSONDecodeError):
    return {}


def _save_json(data: dict, path: str) -> None:
  open(path, "w", encoding="utf-8").write(
    json.dumps(data, indent=2, ensure_ascii=False)
  )


def _log_unresolved(name: str, best_guess: str, confidence: float) -> None:
  data = _load_json(UNRESOLVED_LOG)
  data[name] = {"best_guess": best_guess, "confidence": round(confidence, 3)}
  _save_json(data, UNRESOLVED_LOG)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_name_resolver.py -v
```
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add data/name_resolver.py tests/test_name_resolver.py
git commit -m "feat: add name resolver with fuzzy matching and persistent cache"
```

---

## Task 4: Live Stage Context Fetcher

**Files:**
- Create: `intelligence/stage_context.py`
- Create: `tests/test_stage_context.py`

These are upcoming races not yet in `cache.db`, so we fetch live from PCS using the `procyclingstats` library (same one the scraper uses).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_stage_context.py
import pytest
from unittest.mock import patch, MagicMock
from intelligence.stage_context import (
  fetch_stage_context, _neutral_defaults, _race_name_to_pcs_url
)
from intelligence.models import StageContext


def test_neutral_defaults_valid():
  ctx = _neutral_defaults("Tour de Romandie", "Stage 4", "2026-04-30")
  assert isinstance(ctx, StageContext)
  assert ctx.source == "neutral_defaults"
  assert ctx.stage_type in ("RR", "ITT", "TTT")
  assert 0 <= ctx.profile_icon[-1:] <= "5"


def test_to_race_params_has_required_keys():
  ctx = _neutral_defaults("R", "S", "2026-04-30")
  params = ctx.to_race_params()
  for key in ("distance", "vertical_meters", "profile_icon",
              "is_one_day_race", "stage_type", "race_date"):
    assert key in params, f"Missing key: {key}"


def test_race_name_to_pcs_url_tour_de_romandie():
  url = _race_name_to_pcs_url("Tour de Romandie")
  assert "tour-de-romandie" in url.lower()


def test_race_name_to_pcs_url_tour_de_france():
  url = _race_name_to_pcs_url("Tour de France")
  assert "tour-de-france" in url.lower()


def test_fetch_falls_back_to_neutral_on_pcs_error():
  with patch("intelligence.stage_context._fetch_from_pcs", side_effect=Exception("network error")):
    ctx = fetch_stage_context("Unknown Race XYZ", "Stage 1", "2026-04-30")
  assert ctx.source == "neutral_defaults"


def test_fetch_returns_pcs_data_on_success():
  mock_ctx = StageContext(
    race_name="TdR", stage_name="S4", race_date="2026-04-30",
    distance=178.0, vertical_meters=4200.0, profile_icon="p5",
    profile_score=180.0, is_one_day_race=False, stage_type="RR",
    num_climbs=5, uci_tour="1.UWT", race_base_url="race/tour-de-romandie",
    source="pcs",
  )
  with patch("intelligence.stage_context._fetch_from_pcs", return_value=mock_ctx):
    ctx = fetch_stage_context("Tour de Romandie", "Stage 4", "2026-04-30")
  assert ctx.source == "pcs"
  assert ctx.distance == 178.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_stage_context.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'intelligence.stage_context'`

- [ ] **Step 3: Implement `intelligence/stage_context.py`**

```python
# intelligence/stage_context.py
"""
Fetches live stage context from PCS for upcoming races.

Uses procyclingstats library (same as scraper). Falls back to neutral
defaults so the pipeline never hard-fails — predictions still run,
just with less accurate race features.
"""

import logging
import re
from typing import Optional

from intelligence.models import StageContext

log = logging.getLogger(__name__)

# PCS profile icon → profile score mapping (same as pipeline.py)
_ICON_SCORES = {"p0": 5, "p1": 5, "p2": 25, "p3": 60, "p4": 120, "p5": 180}

# UCI tour tier by race name fragment
_TOUR_TIERS = {
  "tour de france": "1.UWT", "giro d'italia": "1.UWT", "vuelta": "1.UWT",
  "tour de romandie": "2.UWT", "criterium du dauphine": "2.UWT",
  "paris-nice": "2.UWT", "tirreno": "2.UWT", "strade bianche": "1.UWT",
  "milan": "1.UWT", "liege": "1.UWT", "ronde": "1.UWT",
}


def fetch_stage_context(
  race_name: str,
  stage_name: str,
  race_date: str,
) -> StageContext:
  """
  Fetch stage details from PCS. Returns neutral defaults on any failure.
  Never raises.
  """
  try:
    return _fetch_from_pcs(race_name, stage_name, race_date)
  except Exception as exc:
    log.warning("PCS fetch failed for '%s': %s — using neutral defaults", race_name, exc)
    return _neutral_defaults(race_name, stage_name, race_date)


def _fetch_from_pcs(race_name: str, stage_name: str, race_date: str) -> StageContext:
  """Fetch stage from PCS using procyclingstats library."""
  from procyclingstats import Race, Stage

  race_url = _race_name_to_pcs_url(race_name)
  year = race_date[:4]

  # Fetch race overview to find stage URL
  race = Race(f"{race_url}/{year}")
  stages = race.stages()  # list of dicts with 'url', 'name', 'date', etc.

  # Match stage by name or date
  stage_row = _match_stage(stages, stage_name, race_date)
  if not stage_row:
    raise ValueError(f"Stage '{stage_name}' not found in {race_url}/{year}")

  stage = Stage(stage_row["url"])

  profile_icon = getattr(stage, "profile_icon", None) or "p2"
  distance = float(getattr(stage, "distance", 0) or 150.0)
  vertical = float(getattr(stage, "vertical_meters", 0) or 0.0)
  stage_type = getattr(stage, "stage_type", "RR") or "RR"
  num_climbs = int(getattr(stage, "num_climbs", 0) or 0)
  is_one_day = len(stages) == 1

  return StageContext(
    race_name=race_name,
    stage_name=stage_name,
    race_date=race_date,
    distance=distance,
    vertical_meters=vertical,
    profile_icon=profile_icon,
    profile_score=float(_ICON_SCORES.get(profile_icon, 25)),
    is_one_day_race=is_one_day,
    stage_type=stage_type,
    num_climbs=num_climbs,
    uci_tour=_guess_uci_tier(race_name),
    race_base_url=race_url,
    source="pcs",
  )


def _match_stage(stages: list[dict], stage_name: str, race_date: str) -> Optional[dict]:
  """Match a stage by date first, then by name fragment."""
  for s in stages:
    if s.get("date", "") == race_date:
      return s
  name_lower = stage_name.lower()
  for s in stages:
    if name_lower in str(s.get("name", "")).lower():
      return s
  return stages[0] if stages else None


def _race_name_to_pcs_url(race_name: str) -> str:
  """Convert 'Tour de Romandie' → 'race/tour-de-romandie'."""
  slug = re.sub(r"[^a-z0-9]+", "-", race_name.lower()).strip("-")
  return f"race/{slug}"


def _guess_uci_tier(race_name: str) -> str:
  name_lower = race_name.lower()
  for fragment, tier in _TOUR_TIERS.items():
    if fragment in name_lower:
      return tier
  return "2.UWT"


def _neutral_defaults(race_name: str, stage_name: str, race_date: str) -> StageContext:
  return StageContext(
    race_name=race_name, stage_name=stage_name, race_date=race_date,
    distance=150.0, vertical_meters=1500.0, profile_icon="p2",
    profile_score=25.0, is_one_day_race=False, stage_type="RR",
    num_climbs=2, uci_tour="2.UWT", race_base_url="", source="neutral_defaults",
  )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_stage_context.py -v
```
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add intelligence/stage_context.py tests/test_stage_context.py
git commit -m "feat: add live PCS stage context fetcher with neutral fallback"
```

---

## Task 5: Flask Endpoint + "Load from Pinnacle" Button

**Files:**
- Modify: `webapp/app.py`
- Modify: existing batch prediction template (find template name first)
- Create: `tests/test_pinnacle_load.py`

- [ ] **Step 1: Find the existing batch prediction template**

```bash
grep -rn "batch\|multi.*predict\|predict.*multi" webapp/templates/ --include="*.html" -l
```

Note the template filename — you'll add the button there.

- [ ] **Step 2: Write failing tests**

```python
# tests/test_pinnacle_load.py
import pytest
import os
from unittest.mock import patch
from datetime import datetime
from intelligence.models import OddsMarket, ResolvedMarket, StageContext


@pytest.fixture
def client():
  os.environ["PINNACLE_SESSION_COOKIE"] = "test-cookie"
  from webapp.app import app
  app.config["TESTING"] = True
  with app.test_client() as c:
    yield c


def _make_resolved():
  market = OddsMarket("1", "Tour de Romandie Stage 4", "Stage 4",
                      "Tadej Pogacar", "Jonas Vingegaard", 1.65, 2.30,
                      datetime.utcnow())
  return ResolvedMarket(market, "rider/tadej-pogacar", "rider/jonas-vingegaard",
                        0.95, 0.97, True)


def _make_stage():
  return StageContext("Tour de Romandie", "Stage 4", "2026-04-30",
                      178.0, 4200.0, "p5", 180.0, False, "RR", 5,
                      "2.UWT", "race/tour-de-romandie", "pcs")


def test_load_endpoint_returns_matchups(client):
  with patch("webapp.app.fetch_cycling_markets") as mock_fetch, \
       patch("webapp.app.resolve_all") as mock_resolve, \
       patch("webapp.app.fetch_stage_context", return_value=_make_stage()), \
       patch("webapp.app.append_to_odds_log"):
    mock_fetch.return_value = [_make_resolved().market]
    mock_resolve.return_value = [_make_resolved()]
    resp = client.post("/api/pinnacle/load")
  assert resp.status_code == 200
  data = resp.get_json()
  assert "matchups" in data
  assert len(data["matchups"]) == 1
  m = data["matchups"][0]
  assert m["rider_a_name"] == "Tadej Pogacar"
  assert m["odds_a"] == 1.65
  assert m["rider_a_url"] == "rider/tadej-pogacar"
  assert "stage" in m


def test_load_endpoint_skips_unresolved(client):
  unresolved = ResolvedMarket(
    _make_resolved().market, None, None, 0.3, 0.3, False
  )
  with patch("webapp.app.fetch_cycling_markets") as mock_fetch, \
       patch("webapp.app.resolve_all", return_value=[unresolved]), \
       patch("webapp.app.append_to_odds_log"), \
       patch("webapp.app.fetch_stage_context", return_value=_make_stage()):
    mock_fetch.return_value = [unresolved.market]
    resp = client.post("/api/pinnacle/load")
  data = resp.get_json()
  assert len(data["matchups"]) == 0
  assert len(data["unresolved"]) == 1


def test_load_endpoint_returns_401_without_cookie(client):
  del os.environ["PINNACLE_SESSION_COOKIE"]
  resp = client.post("/api/pinnacle/load")
  assert resp.status_code == 400
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_pinnacle_load.py -v
```
Expected: FAIL

- [ ] **Step 4: Add `POST /api/pinnacle/load` to `webapp/app.py`**

Add these imports near the top of `webapp/app.py` with the other imports:

```python
from data.odds import fetch_cycling_markets, append_to_odds_log
from data.name_resolver import resolve_all
from intelligence.stage_context import fetch_stage_context
```

Add the route near the end of `webapp/app.py`, before `if __name__ == "__main__"`:

```python
@app.route("/api/pinnacle/load", methods=["POST"])
def api_pinnacle_load():
  """
  Fetch today's H2H markets from Pinnacle, resolve rider names,
  and fetch live stage context. Returns pre-filled matchup data
  for the batch prediction UI.
  """
  cookie = os.environ.get("PINNACLE_SESSION_COOKIE", "")
  if not cookie:
    return jsonify({"error": "PINNACLE_SESSION_COOKIE not set"}), 400

  try:
    markets = fetch_cycling_markets(cookie)
  except PermissionError as exc:
    return jsonify({"error": "pinnacle_auth", "detail": str(exc)}), 502

  append_to_odds_log(markets)
  resolved_markets = resolve_all(markets)

  today = __import__("datetime").date.today().isoformat()

  matchups = []
  unresolved = []

  for rm in resolved_markets:
    if not rm.resolved:
      unresolved.append({
        "rider_a_name": rm.market.rider_a_name,
        "rider_b_name": rm.market.rider_b_name,
        "rider_a_confidence": round(rm.rider_a_confidence, 2),
        "rider_b_confidence": round(rm.rider_b_confidence, 2),
      })
      continue

    stage = fetch_stage_context(
      rm.market.race_name,
      rm.market.stage_name,
      today,
    )

    matchups.append({
      "market_id": rm.market.market_id,
      "race_name": rm.market.race_name,
      "stage_name": rm.market.stage_name,
      "rider_a_name": rm.market.rider_a_name,
      "rider_b_name": rm.market.rider_b_name,
      "rider_a_url": rm.rider_a_url,
      "rider_b_url": rm.rider_b_url,
      "odds_a": rm.market.odds_a,
      "odds_b": rm.market.odds_b,
      "rider_a_confidence": round(rm.rider_a_confidence, 2),
      "rider_b_confidence": round(rm.rider_b_confidence, 2),
      "stage": stage.to_race_params(),
      "stage_source": stage.source,
    })

  return jsonify({
    "matchups": matchups,
    "unresolved": unresolved,
    "market_count": len(markets),
  })
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_pinnacle_load.py -v
```
Expected: All 3 tests PASS.

- [ ] **Step 6: Add "Load from Pinnacle" button to the batch prediction template**

In the template file found in Step 1, add this button and JS before the existing batch prediction form or at the top of the form section:

```html
<!-- Load from Pinnacle button — add near top of batch prediction form -->
<div style="margin-bottom: 1rem;">
  <button type="button" id="btn-load-pinnacle" class="btn btn-primary">
    Load from Pinnacle
  </button>
  <span id="pinnacle-status" style="margin-left: 1rem; color: #666;"></span>
</div>

<div id="unresolved-warning" style="display:none; color: #b8860b; margin-bottom: 1rem;"></div>

<script>
document.getElementById('btn-load-pinnacle').addEventListener('click', async function() {
  const btn = this;
  const status = document.getElementById('pinnacle-status');
  const warning = document.getElementById('unresolved-warning');

  btn.disabled = true;
  status.textContent = 'Fetching from Pinnacle…';
  warning.style.display = 'none';

  try {
    const resp = await fetch('/api/pinnacle/load', { method: 'POST' });
    const data = await resp.json();

    if (!resp.ok) {
      status.textContent = 'Error: ' + (data.detail || data.error);
      btn.disabled = false;
      return;
    }

    status.textContent = `Loaded ${data.matchups.length} matchups from ${data.market_count} markets.`;

    if (data.unresolved.length > 0) {
      warning.style.display = 'block';
      warning.textContent = `⚠ ${data.unresolved.length} unresolved: ` +
        data.unresolved.map(u => `${u.rider_a_name} vs ${u.rider_b_name}`).join(', ');
    }

    // Pre-fill the existing batch prediction form rows.
    // Each matchup becomes one row: rider_a_url, rider_b_url, odds_a, odds_b, race_params.
    // Dispatches a custom event so existing form JS can react.
    document.dispatchEvent(new CustomEvent('pinnacle-loaded', { detail: data.matchups }));

  } catch (err) {
    status.textContent = 'Request failed: ' + err.message;
  } finally {
    btn.disabled = false;
  }
});
</script>
```

- [ ] **Step 7: Wire the `pinnacle-loaded` event to the existing form**

In the existing batch prediction JS (same template or linked JS file), add a listener that populates form rows from the matchup payload. The exact field names depend on the existing form structure — adapt to match:

```javascript
document.addEventListener('pinnacle-loaded', function(e) {
  const matchups = e.detail;
  // Clear existing rows first (call existing clear/reset function if available)
  // Then for each matchup, add a form row:
  matchups.forEach(function(m) {
    // addBatchRow() or equivalent existing function:
    addMatchupRow({
      rider_a: m.rider_a_url,
      rider_b: m.rider_b_url,
      odds_a: m.odds_a,
      odds_b: m.odds_b,
      race_params: m.stage,
      // rider display names for labels:
      rider_a_name: m.rider_a_name,
      rider_b_name: m.rider_b_name,
    });
  });
});
```

**Note:** Read the existing batch prediction template JS to find the actual function name that adds a row. Adapt the field mapping to match whatever that function expects.

- [ ] **Step 8: Run full test suite**

```bash
pytest tests/ -v
```
Expected: All tests PASS.

- [ ] **Step 9: Manual smoke test**

```bash
python webapp/app.py
```

Open `http://localhost:5001` → navigate to batch prediction → click "Load from Pinnacle". Verify:
- Button shows loading state during fetch
- Form rows populate with rider names and odds
- Unresolved names show warning if any
- Existing Calculate button still works on pre-filled rows

- [ ] **Step 10: Add `.env.example` and commit**

```bash
# .env.example — add:
PINNACLE_SESSION_COOKIE=   # from browser DevTools after logging into Pinnacle
PINNACLE_API_URL=          # discovered in Task 2 Step 1
```

```bash
git add webapp/app.py webapp/templates/ tests/test_pinnacle_load.py .env.example
git commit -m "feat: add Pinnacle preload endpoint and Load button to batch prediction UI"
```

---

## Self-Review

**Spec coverage:**
- [x] Fetch Pinnacle odds manually triggered — Task 5 button + Task 2 client
- [x] Resolve rider names → PCS URLs — Task 3
- [x] Fetch stage context live from PCS — Task 4
- [x] Pre-fill existing batch prediction UI — Task 5
- [x] Skip unresolved matchups with warning — Task 5 endpoint
- [x] Append-only odds audit log — Task 2 `append_to_odds_log`
- [x] Neutral defaults fallback if PCS fetch fails — Task 4
- [x] No email, no GenAI, no VPS changes — confirmed out of scope

**Type consistency:**
- `OddsMarket`, `ResolvedMarket`, `StageContext` defined in Task 1, used in Tasks 2–5 ✓
- `StageContext.to_race_params()` returns keys matching `build_feature_vector_manual()` signature ✓
- `resolve_all()` takes `list[OddsMarket]`, returns `list[ResolvedMarket]` ✓
- `fetch_cycling_markets()` imported in Task 5 endpoint matches Task 2 signature ✓

**Gap:** Task 5 Step 7 requires reading the existing batch prediction template JS before implementing — flagged explicitly as "read and adapt". ✓
