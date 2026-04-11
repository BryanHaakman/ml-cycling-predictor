# Daily Intelligence Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an autonomous nightly pipeline that fetches Pinnacle H2H cycling odds, runs model predictions on every matchup, performs per-matchup qualitative research via Claude API, and emails a structured HTML report — replacing a 30-minute manual workflow with zero daily effort.

**Architecture:** Standalone Python script (`scripts/intelligence_pipeline.py`) orchestrates all components and sends email directly via SMTP. Flask app gains a `/api/pipeline/run` trigger endpoint secured with a shared secret, called by GitHub Actions after the nightly data fetch completes. All intelligence components live in a new `intelligence/` package.

**Tech Stack:** Python 3.11, `anthropic` SDK (Claude Haiku), `duckduckgo_search` (free web search, no API key), `rapidfuzz` (name matching), `playwright` (Pinnacle API discovery), `smtplib` (email), existing `models/predict.py` + `data/pnl.py`.

---

## File Map

**New files:**
- `intelligence/__init__.py` — package marker
- `intelligence/models.py` — all shared dataclasses (OddsMarket, StageContext, RiderFlag, MatchupIntel, ResolvedMarket, MatchupResult)
- `intelligence/stage_context.py` — fetch stage details from cache.db, fall back to PCS
- `intelligence/qualitative.py` — per-matchup web search + Claude Haiku analysis
- `intelligence/report.py` — assemble HTML report, save archive, send email
- `data/odds.py` — Pinnacle internal API client
- `data/name_resolver.py` — fuzzy name → PCS URL mapping with persistent cache
- `data/name_mappings.json` — confirmed name mappings cache (starts empty `{}`)
- `data/reports/` — archived HTML reports (directory)
- `scripts/intelligence_pipeline.py` — top-level orchestrator
- `systemd/paceiq.service` — systemd unit for Flask on VPS
- `tests/test_name_resolver.py`
- `tests/test_qualitative.py`
- `tests/test_report.py`
- `tests/test_pipeline_endpoint.py`

**Modified files:**
- `webapp/app.py` — add `POST /api/pipeline/run` + `GET /bets/prefill`
- `.github/workflows/nightly-pipeline.yml` — add trigger step
- `requirements.txt` — add `rapidfuzz`, `duckduckgo-search`, `playwright`
- `.env.example` — document new env vars

---

## Task 1: Shared Data Models

**Files:**
- Create: `intelligence/__init__.py`
- Create: `intelligence/models.py`
- Create: `data/name_mappings.json`
- Bash: `mkdir -p data/reports`

- [ ] **Step 1: Create the intelligence package and data models**

```python
# intelligence/__init__.py
# (empty)
```

```python
# intelligence/models.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from models.predict import PredictionResult


@dataclass
class OddsMarket:
  """Raw H2H market as returned by Pinnacle."""
  market_id: str
  race_name: str
  stage_name: str
  rider_a_name: str   # Pinnacle display name
  rider_b_name: str
  odds_a: float       # decimal odds for rider A
  odds_b: float
  fetched_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class StageContext:
  """Race/stage details used to build the race_params dict for predict_manual."""
  race_name: str
  stage_name: str
  race_date: str            # ISO date e.g. "2026-04-30"
  distance: float           # km
  vertical_meters: float
  profile_icon: str         # "p0"–"p5"
  profile_score: float
  is_one_day_race: bool
  stage_type: str           # "RR" | "ITT" | "TTT"
  num_climbs: int
  uci_tour: str             # "1.UWT" | "2.UWT" | etc.
  race_base_url: str        # e.g. "race/tour-de-romandie"
  source: str               # "db" | "pcs" | "neutral_defaults"

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


@dataclass
class RiderFlag:
  """Qualitative signal for a single rider."""
  rider_url: str
  flag_type: str          # "domestique"|"fatigue"|"injury"|"protected"|"none"
  flag_detail: str        # human-readable explanation
  confidence: str         # "high"|"medium"|"low"
  sources: list[str]      # URLs or source names
  qual_recommendation: str  # "skip"|"reduce"|"proceed"|"boost"|"no signal"
  qual_adjustment_factor: float = 1.0  # reserved for future quantitative use


@dataclass
class MatchupIntel:
  """Qualitative research output for one H2H matchup."""
  rider_a_url: str
  rider_b_url: str
  rider_a_flag: RiderFlag
  rider_b_flag: RiderFlag
  search_queries_used: list[str] = field(default_factory=list)
  error: Optional[str] = None  # set if qual research failed


@dataclass
class ResolvedMarket:
  """OddsMarket with PCS rider URLs resolved."""
  market: OddsMarket
  rider_a_url: Optional[str]    # None if unresolved
  rider_b_url: Optional[str]
  rider_a_confidence: float     # 0.0–1.0
  rider_b_confidence: float
  resolved: bool                # True only if both riders resolved


@dataclass
class MatchupResult:
  """Full output for one H2H matchup: prediction + qual intelligence."""
  resolved_market: ResolvedMarket
  stage_context: StageContext
  prediction: Optional[PredictionResult]
  intel: Optional[MatchupIntel]
  edge: float             # model_prob_a - implied_prob_a (positive = edge on A)
  edge_tier: str          # "ACT"|"FLAG"|"MONITOR"|"NO EDGE"
  kelly_dollars: Optional[float]  # half Kelly × current bankroll

  @property
  def implied_prob_a(self) -> float:
    return 1.0 / self.resolved_market.market.odds_a if self.resolved_market.market.odds_a > 1 else 1.0

  @staticmethod
  def tier_for_edge(edge: float) -> str:
    if edge > 0.08:
      return "ACT"
    if edge > 0.05:
      return "FLAG"
    if edge > 0.0:
      return "MONITOR"
    return "NO EDGE"
```

- [ ] **Step 2: Create empty name mappings cache and reports directory**

```bash
echo '{}' > data/name_mappings.json
mkdir -p data/reports
```

- [ ] **Step 3: Commit**

```bash
git add intelligence/__init__.py intelligence/models.py data/name_mappings.json data/reports/.gitkeep
git commit -m "feat: add intelligence package with shared data models"
```

---

## Task 2: Pinnacle Odds Discovery + Client

**Files:**
- Create: `data/odds.py`
- Modify: `requirements.txt` (add `playwright`)

**⚠️ This task requires a manual research step before writing the client.**

- [ ] **Step 1: Discover Pinnacle's internal odds API endpoint**

Open Pinnacle in Chrome while logged in. Navigate to the cycling H2H section. Open DevTools → Network tab → filter by "Fetch/XHR". Reload the page and find the API call that returns H2H cycling markets (look for JSON responses containing odds and rider names).

Record the following:
- The full URL (including query params)
- Required request headers (especially `Cookie`, `X-Api-Key`, or similar auth headers)
- Response JSON structure (which fields contain race name, rider names, odds)

Document findings in a comment at the top of `data/odds.py` before implementing.

- [ ] **Step 2: Install playwright and add to requirements**

```bash
pip install playwright
playwright install chromium
```

Add to `requirements.txt`:
```
playwright
rapidfuzz
duckduckgo-search
```

- [ ] **Step 3: Write the failing test**

```python
# tests/test_odds.py
import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from data.odds import fetch_cycling_markets, append_to_odds_log


def test_fetch_returns_odds_market_list():
  """fetch_cycling_markets returns a list of OddsMarket objects."""
  mock_response = [
    {
      "market_id": "123",
      "race_name": "Tour de Romandie",
      "stage_name": "Stage 4",
      "rider_a_name": "Tadej Pogacar",
      "rider_b_name": "Jonas Vingegaard",
      "odds_a": 1.65,
      "odds_b": 2.30,
    }
  ]
  with patch("data.odds._call_pinnacle_api", return_value=mock_response):
    markets = fetch_cycling_markets("fake_session_cookie")
  assert len(markets) == 1
  assert markets[0].rider_a_name == "Tadej Pogacar"
  assert markets[0].odds_a == 1.65


def test_fetch_raises_on_auth_failure():
  with patch("data.odds._call_pinnacle_api", side_effect=PermissionError("session expired")):
    with pytest.raises(PermissionError, match="session expired"):
      fetch_cycling_markets("bad_cookie")


def test_append_to_odds_log(tmp_path):
  from intelligence.models import OddsMarket
  log_path = tmp_path / "odds_log.jsonl"
  market = OddsMarket(
    market_id="abc", race_name="Race", stage_name="S1",
    rider_a_name="A", rider_b_name="B", odds_a=1.8, odds_b=2.0,
    fetched_at=datetime(2026, 4, 30, 21, 0),
  )
  append_to_odds_log([market], path=str(log_path))
  lines = log_path.read_text().strip().split("\n")
  assert len(lines) == 1
  data = json.loads(lines[0])
  assert data["market_id"] == "abc"
```

- [ ] **Step 4: Run test to verify it fails**

```bash
pytest tests/test_odds.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'data.odds'`

- [ ] **Step 5: Implement `data/odds.py`**

Fill in `PINNACLE_API_URL` and `_parse_response()` based on your Step 1 discovery. The structure below is correct — only the URL and parser need to be filled in.

```python
# data/odds.py
"""
Pinnacle internal API client for H2H cycling markets.

Discovered endpoint (fill in after Step 1 discovery):
  URL: <discovered URL here>
  Auth: session cookie passed as Cookie header
  Response: <document structure here>
"""

import json
import logging
import os
from datetime import datetime
from typing import Any

import requests

from intelligence.models import OddsMarket

log = logging.getLogger(__name__)

# Fill in after discovery:
PINNACLE_API_URL = os.environ.get("PINNACLE_API_URL", "")
ODDS_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "odds_log.jsonl")


def fetch_cycling_markets(session_cookie: str) -> list[OddsMarket]:
  """
  Fetch all live H2H cycling markets from Pinnacle.

  Args:
    session_cookie: Value of the Pinnacle session cookie.

  Returns:
    List of OddsMarket objects.

  Raises:
    PermissionError: If the session cookie is invalid/expired (401/403 response).
    RuntimeError: For other HTTP errors.
  """
  raw = _call_pinnacle_api(session_cookie)
  markets = [_parse_market(item) for item in raw if _is_cycling_h2h(item)]
  log.info("Fetched %d cycling H2H markets from Pinnacle", len(markets))
  return markets


def _call_pinnacle_api(session_cookie: str) -> list[dict]:
  """Make the HTTP request to Pinnacle's internal API."""
  headers = {
    "Cookie": session_cookie,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
  }
  resp = requests.get(PINNACLE_API_URL, headers=headers, timeout=30)
  if resp.status_code in (401, 403):
    raise PermissionError("session expired — update PINNACLE_SESSION_COOKIE env var")
  resp.raise_for_status()
  return resp.json()


def _is_cycling_h2h(item: dict) -> bool:
  """Return True if this market is a H2H cycling matchup. Fill in after discovery."""
  # Example: return item.get("sport") == "cycling" and item.get("type") == "h2h"
  raise NotImplementedError("fill in after API discovery in Step 1")


def _parse_market(item: dict) -> OddsMarket:
  """Map one raw API response item to OddsMarket. Fill in after discovery."""
  raise NotImplementedError("fill in after API discovery in Step 1")


def append_to_odds_log(markets: list[OddsMarket], path: str = ODDS_LOG_PATH) -> None:
  """Append markets to the append-only JSONL audit log."""
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


def load_odds_log(path: str = ODDS_LOG_PATH) -> list[OddsMarket]:
  """Load all markets from the odds log (for bet prefill lookup)."""
  markets = []
  try:
    with open(path, encoding="utf-8") as f:
      for line in f:
        d = json.loads(line)
        markets.append(OddsMarket(
          market_id=d["market_id"],
          race_name=d["race_name"],
          stage_name=d["stage_name"],
          rider_a_name=d["rider_a_name"],
          rider_b_name=d["rider_b_name"],
          odds_a=d["odds_a"],
          odds_b=d["odds_b"],
          fetched_at=datetime.fromisoformat(d["fetched_at"]),
        ))
  except FileNotFoundError:
    pass
  return markets
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_odds.py -v
```
Expected: `test_fetch_returns_odds_market_list` PASS, `test_fetch_raises_on_auth_failure` PASS, `test_append_to_odds_log` PASS. (`_is_cycling_h2h` / `_parse_market` tests skipped until Step 1 discovery is complete.)

- [ ] **Step 7: Commit**

```bash
git add data/odds.py tests/test_odds.py requirements.txt
git commit -m "feat: add Pinnacle odds client skeleton (endpoint TBD after API discovery)"
```

---

## Task 3: Name Resolver

**Files:**
- Create: `data/name_resolver.py`
- Create: `tests/test_name_resolver.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_name_resolver.py
import json
import pytest
from unittest.mock import patch
from data.name_resolver import normalize_name, resolve_name, resolve_all
from intelligence.models import OddsMarket
from datetime import datetime


def test_normalize_strips_accents():
  assert normalize_name("Tadej Pogačar") == "pogacar tadej"


def test_normalize_handles_comma_ordering():
  assert normalize_name("Van der Poel, Mathieu") == "mathieu poel van der"


def test_normalize_lowercases():
  assert normalize_name("JONAS VINGEGAARD") == "jonas vingegaard"


def _make_riders():
  return [
    {"url": "rider/tadej-pogacar", "name": "Tadej Pogačar"},
    {"url": "rider/mathieu-van-der-poel", "name": "Mathieu van der Poel"},
    {"url": "rider/jonas-vingegaard", "name": "Jonas Vingegaard"},
  ]


def test_resolve_exact_cache_hit(tmp_path):
  cache = {"Tadej Pogacar": "rider/tadej-pogacar"}
  cache_path = tmp_path / "name_mappings.json"
  cache_path.write_text(json.dumps(cache))
  url, confidence = resolve_name("Tadej Pogacar", riders=[], cache_path=str(cache_path))
  assert url == "rider/tadej-pogacar"
  assert confidence == 1.0


def test_resolve_fuzzy_above_threshold(tmp_path):
  cache_path = tmp_path / "name_mappings.json"
  cache_path.write_text("{}")
  riders = _make_riders()
  url, confidence = resolve_name("Pogacar Tadej", riders=riders, cache_path=str(cache_path))
  assert url == "rider/tadej-pogacar"
  assert confidence >= 0.85


def test_resolve_returns_none_below_threshold(tmp_path):
  cache_path = tmp_path / "name_mappings.json"
  cache_path.write_text("{}")
  riders = _make_riders()
  url, confidence = resolve_name("Completely Unknown Rider XYZ", riders=riders, cache_path=str(cache_path))
  assert url is None
  assert confidence < 0.70


def test_resolve_all_marks_both_resolved(tmp_path):
  cache_path = tmp_path / "name_mappings.json"
  cache_path.write_text("{}")
  riders = _make_riders()
  market = OddsMarket(
    market_id="1", race_name="TdR", stage_name="S1",
    rider_a_name="Tadej Pogacar", rider_b_name="Jonas Vingegaard",
    odds_a=1.8, odds_b=2.0, fetched_at=datetime.utcnow(),
  )
  with patch("data.name_resolver._load_riders_from_db", return_value=riders):
    results = resolve_all([market], db_path=":memory:", cache_path=str(cache_path))
  assert results[0].resolved is True
  assert results[0].rider_a_url == "rider/tadej-pogacar"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_name_resolver.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'data.name_resolver'`

- [ ] **Step 3: Install rapidfuzz**

```bash
pip install rapidfuzz
```

- [ ] **Step 4: Implement `data/name_resolver.py`**

```python
# data/name_resolver.py
"""
Maps Pinnacle display names to PCS rider URLs using fuzzy matching.

Strategy:
  1. Cache hit in name_mappings.json → confidence 1.0
  2. Fuzzy match score ≥ 0.85 → auto-accept, save to cache
  3. Fuzzy match score 0.70–0.84 → use best guess, log to unresolved_names.json
  4. Fuzzy match score < 0.70 → return None
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
DEFAULT_CACHE_PATH = os.path.join(_DIR, "data", "name_mappings.json")
UNRESOLVED_PATH = os.path.join(_DIR, "data", "unresolved_names.json")

AUTO_ACCEPT_THRESHOLD = 0.85
LOW_CONFIDENCE_THRESHOLD = 0.70


def normalize_name(name: str) -> str:
  """Strip accents, lowercase, sort tokens alphabetically."""
  nfkd = unicodedata.normalize("NFKD", name)
  ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
  # Handle "Last, First" comma ordering
  if "," in ascii_name:
    parts = [p.strip() for p in ascii_name.split(",")]
    ascii_name = " ".join(reversed(parts))
  tokens = sorted(ascii_name.lower().split())
  return " ".join(tokens)


def resolve_name(
  pinnacle_name: str,
  riders: list[dict],
  cache_path: str = DEFAULT_CACHE_PATH,
) -> tuple[Optional[str], float]:
  """
  Resolve a Pinnacle display name to a PCS rider URL.

  Returns:
    (pcs_url, confidence) where pcs_url is None if confidence < LOW_CONFIDENCE_THRESHOLD.
  """
  cache = _load_cache(cache_path)
  if pinnacle_name in cache:
    return cache[pinnacle_name], 1.0

  if not riders:
    return None, 0.0

  norm_query = normalize_name(pinnacle_name)
  choices = {normalize_name(r["name"]): r["url"] for r in riders}

  result = process.extractOne(norm_query, choices.keys(), scorer=fuzz.token_sort_ratio)
  if result is None:
    return None, 0.0

  matched_norm, score, _ = result
  confidence = score / 100.0
  matched_url = choices[matched_norm]

  if confidence >= AUTO_ACCEPT_THRESHOLD:
    cache[pinnacle_name] = matched_url
    _save_cache(cache, cache_path)
    log.info("Auto-resolved '%s' → %s (%.2f)", pinnacle_name, matched_url, confidence)
    return matched_url, confidence

  if confidence >= LOW_CONFIDENCE_THRESHOLD:
    _log_unresolved(pinnacle_name, matched_url, confidence)
    log.warning("Low-confidence match '%s' → %s (%.2f) — check unresolved_names.json", pinnacle_name, matched_url, confidence)
    return matched_url, confidence

  log.warning("Could not resolve '%s' (best confidence %.2f)", pinnacle_name, confidence)
  return None, confidence


def resolve_all(
  markets: list[OddsMarket],
  db_path: str = DB_PATH,
  cache_path: str = DEFAULT_CACHE_PATH,
) -> list[ResolvedMarket]:
  """Resolve all markets, loading riders from DB once."""
  riders = _load_riders_from_db(db_path)
  resolved = []
  for market in markets:
    url_a, conf_a = resolve_name(market.rider_a_name, riders, cache_path)
    url_b, conf_b = resolve_name(market.rider_b_name, riders, cache_path)
    resolved.append(ResolvedMarket(
      market=market,
      rider_a_url=url_a,
      rider_b_url=url_b,
      rider_a_confidence=conf_a,
      rider_b_confidence=conf_b,
      resolved=url_a is not None and url_b is not None,
    ))
  return resolved


def _load_riders_from_db(db_path: str) -> list[dict]:
  conn = get_db(db_path)
  rows = conn.execute("SELECT url, name FROM riders WHERE name IS NOT NULL").fetchall()
  conn.close()
  return [{"url": r["url"], "name": r["name"]} for r in rows]


def _load_cache(path: str) -> dict:
  try:
    with open(path, encoding="utf-8") as f:
      return json.load(f)
  except (FileNotFoundError, json.JSONDecodeError):
    return {}


def _save_cache(cache: dict, path: str) -> None:
  with open(path, "w", encoding="utf-8") as f:
    json.dump(cache, f, indent=2, ensure_ascii=False)


def _log_unresolved(name: str, best_guess: str, confidence: float) -> None:
  try:
    with open(UNRESOLVED_PATH, encoding="utf-8") as f:
      data = json.load(f)
  except (FileNotFoundError, json.JSONDecodeError):
    data = {}
  data[name] = {"best_guess": best_guess, "confidence": round(confidence, 3)}
  with open(UNRESOLVED_PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_name_resolver.py -v
```
Expected: All 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add data/name_resolver.py tests/test_name_resolver.py
git commit -m "feat: add name resolver with fuzzy matching and persistent cache"
```

---

## Task 4: Stage Context Fetcher

**Files:**
- Create: `intelligence/stage_context.py`

The pipeline needs `race_params` for `predict_manual()`. This component looks up stage details from `cache.db` by matching race name and date. Falls back to neutral defaults so the pipeline never hard-fails.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stage_context.py
import pytest
from unittest.mock import patch, MagicMock
from intelligence.stage_context import fetch_stage_context, _neutral_defaults
from intelligence.models import StageContext


def test_neutral_defaults_returns_valid_stage_context():
  ctx = _neutral_defaults("Tour de Romandie", "Stage 4", "2026-04-30")
  assert isinstance(ctx, StageContext)
  assert ctx.source == "neutral_defaults"
  assert ctx.stage_type == "RR"
  assert ctx.profile_icon in ("p0", "p1", "p2", "p3", "p4", "p5")


def test_to_race_params_has_required_keys():
  ctx = _neutral_defaults("Race", "Stage 1", "2026-04-30")
  params = ctx.to_race_params()
  for key in ("distance", "vertical_meters", "profile_icon", "is_one_day_race", "stage_type", "race_date"):
    assert key in params


def test_fetch_returns_db_result_when_found():
  mock_row = {
    "distance": 178.0, "vertical_meters": 4200.0, "profile_icon": "p5",
    "profile_score": 180.0, "is_one_day_race": 0, "stage_type": "RR",
    "date": "2026-04-30", "num_climbs": 5, "race_url": "race/tour-de-romandie",
  }
  with patch("intelligence.stage_context._lookup_in_db", return_value=mock_row):
    ctx = fetch_stage_context("Tour de Romandie", "Stage 4", "2026-04-30")
  assert ctx.source == "db"
  assert ctx.distance == 178.0
  assert ctx.vertical_meters == 4200.0


def test_fetch_falls_back_to_neutral_when_db_miss():
  with patch("intelligence.stage_context._lookup_in_db", return_value=None):
    ctx = fetch_stage_context("Unknown Race", "Stage 1", "2026-04-30")
  assert ctx.source == "neutral_defaults"
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
Fetches stage context for upcoming race predictions.

Lookup order:
  1. cache.db — match race name + date range
  2. Neutral defaults — never hard-fail the pipeline
"""

import logging
import os
from typing import Optional

from data.scraper import get_db, DB_PATH
from intelligence.models import StageContext

log = logging.getLogger(__name__)


def fetch_stage_context(
  race_name: str,
  stage_name: str,
  race_date: str,
  db_path: str = DB_PATH,
) -> StageContext:
  """
  Fetch stage context. Returns DB data if found, else neutral defaults.
  Never raises — the pipeline must continue even if context is unavailable.
  """
  try:
    row = _lookup_in_db(race_name, race_date, db_path)
    if row:
      log.info("Stage context found in DB for '%s'", race_name)
      return _from_db_row(row, race_name, stage_name, race_date)
  except Exception as exc:
    log.warning("DB stage lookup failed for '%s': %s", race_name, exc)

  log.warning("Using neutral defaults for '%s' — verify stage details manually", race_name)
  return _neutral_defaults(race_name, stage_name, race_date)


def _lookup_in_db(race_name: str, race_date: str, db_path: str) -> Optional[dict]:
  """Look up stage in cache.db by fuzzy race name + date proximity (±3 days)."""
  conn = get_db(db_path)
  try:
    # Normalise race name to match PCS URL slug style
    name_fragment = race_name.lower().replace(" ", "-").replace("'", "")
    row = conn.execute(
      """
      SELECT s.distance, s.vertical_meters, s.profile_icon, s.profile_score,
             s.is_one_day_race, s.stage_type, s.date, s.num_climbs,
             r.url AS race_url, r.uci_tour
        FROM stages s
        JOIN races r ON r.url = s.race_url
       WHERE s.date BETWEEN date(?, '-3 days') AND date(?, '+3 days')
         AND lower(r.url) LIKE ?
       ORDER BY abs(julianday(s.date) - julianday(?))
       LIMIT 1
      """,
      (race_date, race_date, f"%{name_fragment}%", race_date),
    ).fetchone()
    return dict(row) if row else None
  finally:
    conn.close()


def _from_db_row(row: dict, race_name: str, stage_name: str, race_date: str) -> StageContext:
  return StageContext(
    race_name=race_name,
    stage_name=stage_name,
    race_date=race_date,
    distance=float(row.get("distance") or 150.0),
    vertical_meters=float(row.get("vertical_meters") or 0.0),
    profile_icon=row.get("profile_icon") or "p2",
    profile_score=float(row.get("profile_score") or 25.0),
    is_one_day_race=bool(row.get("is_one_day_race", 0)),
    stage_type=row.get("stage_type") or "RR",
    num_climbs=int(row.get("num_climbs") or 0),
    uci_tour=row.get("uci_tour") or "1.UWT",
    race_base_url=row.get("race_url") or "",
    source="db",
  )


def _neutral_defaults(race_name: str, stage_name: str, race_date: str) -> StageContext:
  """Neutral mid-range defaults. Predictions will be less accurate but won't crash."""
  return StageContext(
    race_name=race_name,
    stage_name=stage_name,
    race_date=race_date,
    distance=150.0,
    vertical_meters=1500.0,
    profile_icon="p2",
    profile_score=25.0,
    is_one_day_race=False,
    stage_type="RR",
    num_climbs=2,
    uci_tour="1.UWT",
    race_base_url="",
    source="neutral_defaults",
  )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_stage_context.py -v
```
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add intelligence/stage_context.py tests/test_stage_context.py
git commit -m "feat: add stage context fetcher with DB lookup and neutral fallback"
```

---

## Task 5: Qualitative Intelligence

**Files:**
- Create: `intelligence/qualitative.py`
- Create: `tests/test_qualitative.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_qualitative.py
import pytest
from unittest.mock import patch, MagicMock
from intelligence.qualitative import research_matchup, _build_search_queries, _parse_claude_response
from intelligence.models import MatchupIntel, RiderFlag


def test_build_search_queries_contains_rider_names():
  queries = _build_search_queries("Tadej Pogačar", "Jonas Vingegaard", "Tour de Romandie", "Stage 4")
  combined = " ".join(queries)
  assert "Pogačar" in combined or "Pogacar" in combined
  assert "Vingegaard" in combined
  assert len(queries) >= 3


def test_parse_claude_response_domestique():
  raw = """{
    "rider_a": {
      "flag_type": "domestique",
      "flag_detail": "Confirmed lead-out man for sprint today",
      "confidence": "high",
      "sources": ["VeloNews preview"],
      "qual_recommendation": "skip"
    },
    "rider_b": {
      "flag_type": "none",
      "flag_detail": "No significant news",
      "confidence": "high",
      "sources": [],
      "qual_recommendation": "no signal"
    }
  }"""
  a_flag, b_flag = _parse_claude_response(raw, "rider/a", "rider/b")
  assert a_flag.flag_type == "domestique"
  assert a_flag.qual_recommendation == "skip"
  assert b_flag.flag_type == "none"


def test_parse_claude_response_handles_malformed_json():
  a_flag, b_flag = _parse_claude_response("not valid json", "rider/a", "rider/b")
  assert a_flag.flag_type == "none"
  assert a_flag.flag_detail == "parse error"
  assert b_flag.flag_type == "none"


def test_research_matchup_returns_matchup_intel():
  mock_search = [{"title": "Pogacar preview", "body": "Expected to win", "href": "https://velosnews.com"}]
  mock_claude = MagicMock()
  mock_claude.messages.create.return_value = MagicMock(
    content=[MagicMock(text='''{
      "rider_a": {"flag_type":"none","flag_detail":"No news","confidence":"high","sources":[],"qual_recommendation":"no signal"},
      "rider_b": {"flag_type":"none","flag_detail":"No news","confidence":"high","sources":[],"qual_recommendation":"no signal"}
    }''')]
  )
  with patch("intelligence.qualitative.DDGS") as mock_ddgs_cls, \
       patch("intelligence.qualitative._get_anthropic_client", return_value=mock_claude):
    mock_ddgs_cls.return_value.__enter__ = lambda s: s
    mock_ddgs_cls.return_value.__exit__ = MagicMock(return_value=False)
    mock_ddgs_cls.return_value.text = MagicMock(return_value=mock_search)
    intel = research_matchup(
      rider_a_url="rider/tadej-pogacar",
      rider_b_url="rider/jonas-vingegaard",
      rider_a_name="Tadej Pogačar",
      rider_b_name="Jonas Vingegaard",
      race_name="Tour de Romandie",
      stage_name="Stage 4",
      race_date="2026-04-30",
    )
  assert isinstance(intel, MatchupIntel)
  assert intel.rider_a_flag.flag_type == "none"
  assert intel.error is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_qualitative.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'intelligence.qualitative'`

- [ ] **Step 3: Implement `intelligence/qualitative.py`**

```python
# intelligence/qualitative.py
"""
Per-matchup qualitative intelligence via web search + Claude Haiku.

Searches CyclingNews, VeloNews, PCS news, Reddit, and Twitter for
tactical signals (domestique roles, fatigue, injury, team strategy).
"""

import json
import logging
import os
from typing import Optional

import anthropic
from duckduckgo_search import DDGS

from intelligence.models import MatchupIntel, RiderFlag

log = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
MAX_SEARCH_RESULTS = 8


def research_matchup(
  rider_a_url: str,
  rider_b_url: str,
  rider_a_name: str,
  rider_b_name: str,
  race_name: str,
  stage_name: str,
  race_date: str,
) -> MatchupIntel:
  """
  Research a H2H matchup for tactical signals.
  Never raises — returns MatchupIntel with error field set on failure.
  """
  try:
    queries = _build_search_queries(rider_a_name, rider_b_name, race_name, stage_name)
    search_results = _run_searches(queries)
    raw_response = _call_claude(rider_a_name, rider_b_name, race_name, stage_name, race_date, search_results)
    a_flag, b_flag = _parse_claude_response(raw_response, rider_a_url, rider_b_url)
    return MatchupIntel(
      rider_a_url=rider_a_url,
      rider_b_url=rider_b_url,
      rider_a_flag=a_flag,
      rider_b_flag=b_flag,
      search_queries_used=queries,
    )
  except Exception as exc:
    log.error("Qual research failed for %s vs %s: %s", rider_a_name, rider_b_name, exc)
    return MatchupIntel(
      rider_a_url=rider_a_url,
      rider_b_url=rider_b_url,
      rider_a_flag=_no_signal_flag(rider_a_url),
      rider_b_flag=_no_signal_flag(rider_b_url),
      error=str(exc),
    )


def _build_search_queries(rider_a: str, rider_b: str, race: str, stage: str) -> list[str]:
  return [
    f"{rider_a} {race} {stage} 2026",
    f"{rider_b} {race} {stage} 2026",
    f"{race} {stage} team strategy domestique 2026",
    f"{rider_a} {rider_b} injury form news",
    f"site:reddit.com/r/peloton {race} {stage}",
  ]


def _run_searches(queries: list[str]) -> str:
  """Run all queries and combine results into a single text block."""
  results = []
  with DDGS() as ddgs:
    for q in queries:
      try:
        hits = list(ddgs.text(q, max_results=MAX_SEARCH_RESULTS))
        for h in hits:
          results.append(f"Source: {h.get('href','')}\n{h.get('title','')}: {h.get('body','')}")
      except Exception as exc:
        log.debug("Search query failed '%s': %s", q, exc)
  return "\n\n".join(results[:40])  # cap total context


def _call_claude(
  rider_a: str, rider_b: str, race: str, stage: str, race_date: str, search_text: str
) -> str:
  client = _get_anthropic_client()
  prompt = f"""You are a cycling intelligence analyst. Analyse the search results below for the H2H matchup:

MATCHUP: {rider_a} vs {rider_b}
RACE: {race} — {stage} ({race_date})

SEARCH RESULTS:
{search_text}

Return ONLY a JSON object with this exact structure (no markdown, no extra text):
{{
  "rider_a": {{
    "flag_type": "domestique|fatigue|injury|protected|none",
    "flag_detail": "one sentence explanation",
    "confidence": "high|medium|low",
    "sources": ["source name or URL"],
    "qual_recommendation": "skip|reduce|proceed|boost|no signal"
  }},
  "rider_b": {{
    "flag_type": "domestique|fatigue|injury|protected|none",
    "flag_detail": "one sentence explanation",
    "confidence": "high|medium|low",
    "sources": ["source name or URL"],
    "qual_recommendation": "skip|reduce|proceed|boost|no signal"
  }}
}}

Rules:
- flag_type "none" and qual_recommendation "no signal" when no relevant news found
- Only flag "high" confidence when a credible source explicitly states the role/condition
- "domestique" = rider confirmed as support for another rider today
- "fatigue" = rider attacked hard yesterday or recent back-to-back hard efforts reported
- "protected" = rider is the protected team leader for GC or sprint
- "injury" = any reported physical issue
"""
  response = client.messages.create(
    model=CLAUDE_MODEL,
    max_tokens=512,
    messages=[{"role": "user", "content": prompt}],
  )
  return response.content[0].text


def _parse_claude_response(raw: str, rider_a_url: str, rider_b_url: str) -> tuple[RiderFlag, RiderFlag]:
  try:
    data = json.loads(raw.strip())
    return (
      _dict_to_flag(data["rider_a"], rider_a_url),
      _dict_to_flag(data["rider_b"], rider_b_url),
    )
  except Exception:
    return _error_flag(rider_a_url), _error_flag(rider_b_url)


def _dict_to_flag(d: dict, rider_url: str) -> RiderFlag:
  return RiderFlag(
    rider_url=rider_url,
    flag_type=d.get("flag_type", "none"),
    flag_detail=d.get("flag_detail", ""),
    confidence=d.get("confidence", "low"),
    sources=d.get("sources", []),
    qual_recommendation=d.get("qual_recommendation", "no signal"),
  )


def _no_signal_flag(rider_url: str) -> RiderFlag:
  return RiderFlag(rider_url=rider_url, flag_type="none", flag_detail="No significant news found",
                   confidence="high", sources=[], qual_recommendation="no signal")


def _error_flag(rider_url: str) -> RiderFlag:
  return RiderFlag(rider_url=rider_url, flag_type="none", flag_detail="parse error",
                   confidence="low", sources=[], qual_recommendation="no signal")


def _get_anthropic_client() -> anthropic.Anthropic:
  return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_qualitative.py -v
```
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add intelligence/qualitative.py tests/test_qualitative.py
git commit -m "feat: add per-matchup qualitative intelligence via Claude Haiku + DuckDuckGo"
```

---

## Task 6: Report Generator + Email

**Files:**
- Create: `intelligence/report.py`
- Create: `tests/test_report.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_report.py
import os
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from intelligence.report import build_report, save_report, _edge_badge_color


def _make_matchup_result(edge: float = 0.09, tier: str = "ACT"):
  from intelligence.models import (
    MatchupResult, ResolvedMarket, OddsMarket, StageContext, RiderFlag, MatchupIntel
  )
  from models.predict import PredictionResult, KellyResult
  market = OddsMarket("1", "Tour de Romandie", "Stage 4", "Pogacar", "Vingegaard", 1.65, 2.30, datetime.utcnow())
  resolved = ResolvedMarket(market, "rider/a", "rider/b", 0.95, 0.95, True)
  stage = StageContext("TdR", "S4", "2026-04-30", 178.0, 4200.0, "p5", 180.0, False, "RR", 5, "1.UWT", "race/tdr", "db")
  kelly = KellyResult(edge=edge, kelly_fraction=0.04, half_kelly=0.02, quarter_kelly=0.01, expected_value=0.05, should_bet=True)
  pred = PredictionResult("Pogacar", "Vingegaard", 0.61, 0.39, kelly, None, "CalibratedXGBoost")
  flag = RiderFlag("rider/a", "none", "No news", "high", [], "no signal")
  intel = MatchupIntel("rider/a", "rider/b", flag, flag)
  return MatchupResult(resolved, stage, pred, intel, edge, tier, 42.0)


def test_build_report_contains_rider_names():
  result = _make_matchup_result()
  html = build_report([result], bankroll=2000.0, run_time=datetime(2026, 4, 30, 21, 30))
  assert "Pogacar" in html
  assert "Vingegaard" in html


def test_build_report_contains_edge_tier_badge():
  result = _make_matchup_result(edge=0.09, tier="ACT")
  html = build_report([result], bankroll=2000.0, run_time=datetime(2026, 4, 30, 21, 30))
  assert "ACT" in html


def test_build_report_shows_kelly_dollars():
  result = _make_matchup_result()
  html = build_report([result], bankroll=2000.0, run_time=datetime(2026, 4, 30, 21, 30))
  assert "$42" in html


def test_save_report_writes_file(tmp_path):
  with patch("intelligence.report.REPORTS_DIR", str(tmp_path)):
    path = save_report("<html>test</html>", run_time=datetime(2026, 4, 30, 21, 30))
  assert os.path.exists(path)
  assert open(path).read() == "<html>test</html>"


def test_edge_badge_color():
  assert _edge_badge_color("ACT") == "#1a7a3a"
  assert _edge_badge_color("FLAG") == "#b8860b"
  assert _edge_badge_color("MONITOR") == "#4a6fa5"
  assert _edge_badge_color("NO EDGE") == "#888888"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_report.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'intelligence.report'`

- [ ] **Step 3: Implement `intelligence/report.py`**

```python
# intelligence/report.py
"""
Assembles HTML email report and sends via SMTP.
"""

import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from intelligence.models import MatchupResult

log = logging.getLogger(__name__)

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "reports")

_BADGE_COLORS = {
  "ACT": "#1a7a3a",
  "FLAG": "#b8860b",
  "MONITOR": "#4a6fa5",
  "NO EDGE": "#888888",
}


def _edge_badge_color(tier: str) -> str:
  return _BADGE_COLORS.get(tier, "#888888")


def build_report(
  results: list[MatchupResult],
  bankroll: float,
  run_time: datetime,
  unresolved_names: Optional[list[str]] = None,
) -> str:
  """Build full HTML report string."""
  # Group by race
  races: dict[str, list[MatchupResult]] = {}
  for r in results:
    key = f"{r.resolved_market.market.race_name} — {r.resolved_market.market.stage_name}"
    races.setdefault(key, []).append(r)

  body_parts = []
  for race_key, race_results in races.items():
    sorted_results = sorted(race_results, key=lambda x: x.edge, reverse=True)
    stage = sorted_results[0].stage_context
    body_parts.append(_render_race_section(race_key, stage, sorted_results, bankroll))

  if unresolved_names:
    body_parts.append(_render_unresolved(unresolved_names))

  return _wrap_html(
    content="\n".join(body_parts),
    run_time=run_time,
    bankroll=bankroll,
  )


def _render_race_section(race_key: str, stage, results: list[MatchupResult], bankroll: float) -> str:
  matchup_rows = "".join(_render_matchup(r, bankroll) for r in results)
  source_note = "" if stage.source == "db" else f'<p style="color:#888;font-size:12px;">⚠ Stage context: {stage.source} — verify manually</p>'
  return f"""
<div style="margin-bottom:32px;border:1px solid #ddd;border-radius:8px;overflow:hidden;">
  <div style="background:#1e2a3a;color:white;padding:12px 16px;">
    <strong>{race_key}</strong>
    &nbsp;&nbsp;|&nbsp;&nbsp;
    {stage.distance:.0f}km &nbsp;·&nbsp; {stage.vertical_meters:.0f}m gain &nbsp;·&nbsp;
    {stage.stage_type} &nbsp;·&nbsp; {stage.profile_icon.upper()}
  </div>
  {source_note}
  {matchup_rows}
</div>"""


def _render_matchup(r: MatchupResult, bankroll: float) -> str:
  market = r.resolved_market.market
  pred = r.prediction
  intel = r.intel
  color = _edge_badge_color(r.edge_tier)

  prob_a = f"{pred.prob_a_wins:.0%}" if pred else "—"
  implied = f"{r.implied_prob_a:.0%}"
  edge_str = f"{r.edge:+.1%}"
  kelly_str = f"${r.kelly_dollars:.0f}" if r.kelly_dollars else "—"

  a_flag = intel.rider_a_flag if intel else None
  b_flag = intel.rider_b_flag if intel else None

  def flag_html(flag, name: str) -> str:
    if not flag or flag.flag_type == "none":
      return ""
    icon = {"domestique": "🚴", "fatigue": "😓", "injury": "🩹", "protected": "🛡"}.get(flag.flag_type, "⚠")
    return f'<div style="font-size:12px;color:#555;margin-top:4px;">{icon} <strong>{name}</strong>: {flag.flag_detail} <em>({flag.confidence} confidence)</em> → <strong>{flag.qual_recommendation}</strong></div>'

  flags_html = flag_html(a_flag, market.rider_a_name) + flag_html(b_flag, market.rider_b_name)
  qual_error = f'<div style="font-size:11px;color:#999;">Qual research failed: {intel.error}</div>' if intel and intel.error else ""

  return f"""
<div style="padding:12px 16px;border-bottom:1px solid #eee;">
  <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
    <span style="background:{color};color:white;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;">{r.edge_tier}</span>
    <strong>{market.rider_a_name} vs {market.rider_b_name}</strong>
  </div>
  <div style="margin-top:6px;font-size:13px;color:#333;">
    Model: <strong>{prob_a}</strong> &nbsp;|&nbsp;
    Pinnacle: {implied} &nbsp;|&nbsp;
    Edge: <strong>{edge_str}</strong> &nbsp;|&nbsp;
    Half Kelly: <strong>{kelly_str}</strong>
    &nbsp;(odds {market.odds_a:.2f} / {market.odds_b:.2f})
  </div>
  {flags_html}
  {qual_error}
</div>"""


def _render_unresolved(names: list[str]) -> str:
  items = "".join(f"<li>{n}</li>" for n in names)
  return f"""
<div style="margin-top:24px;padding:12px;background:#fff8e1;border:1px solid #ffe082;border-radius:6px;">
  <strong>⚠ Unresolved matchups</strong> — rider names not matched to PCS:
  <ul>{items}</ul>
  Add confirmed mappings to <code>data/name_mappings.json</code>.
</div>"""


def _wrap_html(content: str, run_time: datetime, bankroll: float) -> str:
  return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>body{{font-family:Arial,sans-serif;max-width:700px;margin:0 auto;color:#222;}}</style>
</head><body>
<h2 style="color:#1e2a3a;">🚴 PaceIQ Intelligence Report</h2>
<p style="color:#666;font-size:13px;">Generated: {run_time.strftime('%Y-%m-%d %H:%M UTC')} &nbsp;|&nbsp; Bankroll: ${bankroll:,.0f}</p>
{content}
<hr style="margin-top:32px;">
<p style="font-size:11px;color:#999;">Bet manually on Pinnacle. This is not financial advice.</p>
</body></html>"""


def save_report(html: str, run_time: Optional[datetime] = None) -> str:
  """Save report to data/reports/ and return the file path."""
  if run_time is None:
    run_time = datetime.utcnow()
  os.makedirs(REPORTS_DIR, exist_ok=True)
  filename = run_time.strftime("%Y-%m-%d-%H%M.html")
  path = os.path.join(REPORTS_DIR, filename)
  with open(path, "w", encoding="utf-8") as f:
    f.write(html)
  log.info("Report saved to %s", path)
  return path


def send_report(html: str, subject: str) -> None:
  """Send HTML report via SMTP. Reads config from environment variables."""
  smtp_host = os.environ["SMTP_HOST"]          # e.g. smtp.gmail.com
  smtp_port = int(os.environ.get("SMTP_PORT", "587"))
  smtp_user = os.environ["SMTP_USER"]          # e.g. you@gmail.com
  smtp_pass = os.environ["SMTP_PASS"]          # Gmail app password
  report_email = os.environ["REPORT_EMAIL"]    # destination address

  msg = MIMEMultipart("alternative")
  msg["Subject"] = subject
  msg["From"] = smtp_user
  msg["To"] = report_email
  msg.attach(MIMEText(html, "html"))

  with smtplib.SMTP(smtp_host, smtp_port) as server:
    server.starttls()
    server.login(smtp_user, smtp_pass)
    server.sendmail(smtp_user, [report_email], msg.as_string())

  log.info("Report emailed to %s", report_email)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_report.py -v
```
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add intelligence/report.py tests/test_report.py
git commit -m "feat: add HTML report generator and SMTP email sender"
```

---

## Task 7: Pipeline Orchestrator

**Files:**
- Create: `scripts/intelligence_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_intelligence_pipeline.py
import pytest
from unittest.mock import patch, MagicMock
from intelligence.models import OddsMarket, ResolvedMarket, StageContext, MatchupIntel, MatchupResult, RiderFlag
from datetime import datetime


def _mock_market():
  m = OddsMarket("1", "TdR", "S4", "Pogacar", "Vingegaard", 1.65, 2.30, datetime.utcnow())
  return m


def test_pipeline_run_returns_html_string():
  """run_pipeline returns an HTML string and does not raise on normal flow."""
  from scripts.intelligence_pipeline import run_pipeline

  with patch("scripts.intelligence_pipeline.fetch_cycling_markets", return_value=[_mock_market()]), \
       patch("scripts.intelligence_pipeline.resolve_all") as mock_resolve, \
       patch("scripts.intelligence_pipeline.fetch_stage_context") as mock_stage, \
       patch("scripts.intelligence_pipeline.Predictor") as mock_pred_cls, \
       patch("scripts.intelligence_pipeline.research_matchup") as mock_qual, \
       patch("scripts.intelligence_pipeline.get_current_bankroll", return_value=2000.0), \
       patch("scripts.intelligence_pipeline.send_report"), \
       patch("scripts.intelligence_pipeline.save_report", return_value="/tmp/r.html"):

    from intelligence.models import ResolvedMarket
    resolved = ResolvedMarket(_mock_market(), "rider/a", "rider/b", 0.95, 0.95, True)
    mock_resolve.return_value = [resolved]

    from intelligence.models import StageContext
    mock_stage.return_value = StageContext("TdR", "S4", "2026-04-30", 150.0, 2000.0, "p3", 60.0, False, "RR", 3, "1.UWT", "race/tdr", "db")

    from models.predict import PredictionResult, KellyResult
    from intelligence.models import RiderFlag, MatchupIntel
    kelly = KellyResult(0.09, 0.04, 0.02, 0.01, 0.05, True)
    mock_pred_cls.return_value.predict_manual.return_value = PredictionResult("A", "B", 0.61, 0.39, kelly, None, "CalibratedXGBoost")

    flag = RiderFlag("rider/a", "none", "No news", "high", [], "no signal")
    mock_qual.return_value = MatchupIntel("rider/a", "rider/b", flag, flag)

    html = run_pipeline(session_cookie="fake")

  assert "<html>" in html.lower()
  assert "Pogacar" in html or "TdR" in html


def test_pipeline_run_still_sends_alert_on_pinnacle_auth_failure():
  from scripts.intelligence_pipeline import run_pipeline

  with patch("scripts.intelligence_pipeline.fetch_cycling_markets", side_effect=PermissionError("session expired")), \
       patch("scripts.intelligence_pipeline.send_alert_email") as mock_alert:
    with pytest.raises(PermissionError):
      run_pipeline(session_cookie="bad")
    mock_alert.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_intelligence_pipeline.py -v
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `scripts/intelligence_pipeline.py`**

```python
#!/usr/bin/env python3
# scripts/intelligence_pipeline.py
"""
PaceIQ nightly intelligence pipeline.

Fetches Pinnacle H2H cycling odds, runs model predictions on every matchup,
performs per-matchup qualitative research, generates HTML report, sends email.

Usage:
  python scripts/intelligence_pipeline.py          # uses PINNACLE_SESSION_COOKIE env var
  python scripts/intelligence_pipeline.py --dry-run  # skip email, print report path
"""

import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import argparse

from data.odds import fetch_cycling_markets, append_to_odds_log
from data.name_resolver import resolve_all
from data.pnl import get_current_bankroll
from intelligence.models import MatchupResult
from intelligence.qualitative import research_matchup
from intelligence.report import build_report, save_report, send_report
from intelligence.stage_context import fetch_stage_context
from models.predict import Predictor

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def run_pipeline(session_cookie: str, dry_run: bool = False) -> str:
  """
  Run the full intelligence pipeline.

  Returns:
    HTML report string.

  Raises:
    PermissionError: If Pinnacle session cookie is invalid — caller handles alert.
  """
  run_time = datetime.now(timezone.utc)
  log.info("Pipeline started at %s", run_time.isoformat())

  # 1. Fetch odds — raises PermissionError on auth failure
  markets = fetch_cycling_markets(session_cookie)
  append_to_odds_log(markets)
  log.info("Fetched %d markets", len(markets))

  if not markets:
    log.warning("No markets returned — nothing to report")
    html = "<html><body><p>No H2H cycling markets found on Pinnacle today.</p></body></html>"
    _finalize(html, run_time, dry_run, subject="PaceIQ — No markets today")
    return html

  # 2. Resolve names
  resolved_markets = resolve_all(markets)
  unresolved_names = [
    f"{r.market.rider_a_name} vs {r.market.rider_b_name}"
    for r in resolved_markets if not r.resolved
  ]
  bettable = [r for r in resolved_markets if r.resolved]
  log.info("%d markets resolved, %d unresolved", len(bettable), len(unresolved_names))

  # 3. Load predictor once
  predictor = Predictor()
  bankroll = get_current_bankroll()

  # 4. Process each resolved matchup
  results: list[MatchupResult] = []
  for rm in bettable:
    market = rm.market
    stage_ctx = fetch_stage_context(market.race_name, market.stage_name, run_time.strftime("%Y-%m-%d"))

    try:
      pred = predictor.predict_manual(
        rm.rider_a_url,
        rm.rider_b_url,
        stage_ctx.to_race_params(),
        odds_a=market.odds_a,
        odds_b=market.odds_b,
      )
    except Exception as exc:
      log.warning("Prediction failed for %s vs %s: %s", market.rider_a_name, market.rider_b_name, exc)
      pred = None

    intel = research_matchup(
      rider_a_url=rm.rider_a_url,
      rider_b_url=rm.rider_b_url,
      rider_a_name=market.rider_a_name,
      rider_b_name=market.rider_b_name,
      race_name=market.race_name,
      stage_name=market.stage_name,
      race_date=run_time.strftime("%Y-%m-%d"),
    )

    if pred and pred.kelly_a and pred.kelly_a.should_bet:
      edge = pred.kelly_a.edge
      kelly_dollars = pred.kelly_a.half_kelly * bankroll
    else:
      edge = 0.0
      kelly_dollars = None

    results.append(MatchupResult(
      resolved_market=rm,
      stage_context=stage_ctx,
      prediction=pred,
      intel=intel,
      edge=edge,
      edge_tier=MatchupResult.tier_for_edge(edge),
      kelly_dollars=kelly_dollars,
    ))

  # 5. Build and deliver report
  html = build_report(results, bankroll=bankroll, run_time=run_time, unresolved_names=unresolved_names)
  _finalize(html, run_time, dry_run, subject=f"PaceIQ Report — {run_time.strftime('%Y-%m-%d')}")
  return html


def _finalize(html: str, run_time: datetime, dry_run: bool, subject: str) -> None:
  save_report(html, run_time=run_time)
  if not dry_run:
    send_report(html, subject=subject)
    log.info("Report sent")
  else:
    log.info("Dry run — email not sent")


def send_alert_email(message: str) -> None:
  """Send a plain-text alert when the pipeline fails catastrophically."""
  try:
    alert_html = f"<html><body><pre>{message}</pre></body></html>"
    send_report(alert_html, subject="PaceIQ ⚠ Pipeline Alert")
  except Exception as exc:
    log.error("Failed to send alert email: %s", exc)


if __name__ == "__main__":
  parser = argparse.ArgumentParser()
  parser.add_argument("--dry-run", action="store_true", help="Skip email send")
  args = parser.parse_args()

  cookie = os.environ.get("PINNACLE_SESSION_COOKIE", "")
  if not cookie:
    log.error("PINNACLE_SESSION_COOKIE environment variable not set")
    sys.exit(1)

  try:
    run_pipeline(session_cookie=cookie, dry_run=args.dry_run)
  except PermissionError as exc:
    send_alert_email(f"Pinnacle session expired — update PINNACLE_SESSION_COOKIE\n\n{exc}")
    sys.exit(1)
  except Exception as exc:
    send_alert_email(f"Pipeline failed unexpectedly:\n\n{exc}")
    log.exception("Pipeline failed")
    sys.exit(1)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_intelligence_pipeline.py -v
```
Expected: Both tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v
```
Expected: All existing tests plus new tests PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/intelligence_pipeline.py tests/test_intelligence_pipeline.py
git commit -m "feat: add intelligence pipeline orchestrator"
```

---

## Task 8: Flask Trigger Endpoint + Bet Prefill

**Files:**
- Modify: `webapp/app.py`
- Create: `tests/test_pipeline_endpoint.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pipeline_endpoint.py
import pytest
import os
from unittest.mock import patch


@pytest.fixture
def client():
  os.environ["PIPELINE_SECRET"] = "test-secret-abc"
  from webapp.app import app
  app.config["TESTING"] = True
  with app.test_client() as c:
    yield c


def test_pipeline_run_requires_secret(client):
  resp = client.post("/api/pipeline/run")
  assert resp.status_code == 401


def test_pipeline_run_rejects_wrong_secret(client):
  resp = client.post("/api/pipeline/run", headers={"X-Pipeline-Secret": "wrong"})
  assert resp.status_code == 401


def test_pipeline_run_triggers_pipeline_with_correct_secret(client):
  with patch("webapp.app.run_pipeline", return_value="<html>report</html>") as mock_run, \
       patch.dict(os.environ, {"PINNACLE_SESSION_COOKIE": "fake-cookie"}):
    resp = client.post("/api/pipeline/run", headers={"X-Pipeline-Secret": "test-secret-abc"})
  assert resp.status_code == 200
  data = resp.get_json()
  assert data["status"] == "ok"
  assert "<html>" in data["report_html"]
  mock_run.assert_called_once()


def test_bets_prefill_returns_form_data(client):
  from data.odds import OddsMarket
  from datetime import datetime
  mock_market = OddsMarket("mkt-1", "TdR", "S4", "Pogacar", "Vingegaard", 1.65, 2.30, datetime.utcnow())
  with patch("webapp.app.load_odds_log", return_value=[mock_market]):
    resp = client.get("/bets/prefill?market_id=mkt-1")
  assert resp.status_code == 200
  data = resp.get_json()
  assert data["rider_a_name"] == "Pogacar"
  assert data["odds_a"] == 1.65


def test_bets_prefill_returns_404_for_unknown_market(client):
  with patch("webapp.app.load_odds_log", return_value=[]):
    resp = client.get("/bets/prefill?market_id=unknown")
  assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pipeline_endpoint.py -v
```
Expected: FAIL

- [ ] **Step 3: Add the two new routes to `webapp/app.py`**

Find the end of the existing routes section (before `if __name__ == "__main__"`) and add:

```python
# --- Intelligence pipeline trigger (add near end of webapp/app.py) ---

from scripts.intelligence_pipeline import run_pipeline, send_alert_email
from data.odds import load_odds_log


def _require_pipeline_secret(f):
  """Authenticate pipeline trigger requests via X-Pipeline-Secret header."""
  from functools import wraps
  @wraps(f)
  def decorated(*args, **kwargs):
    secret = os.environ.get("PIPELINE_SECRET", "")
    provided = request.headers.get("X-Pipeline-Secret", "")
    if not secret or provided != secret:
      return jsonify({"error": "unauthorized"}), 401
    return f(*args, **kwargs)
  return decorated


@app.route("/api/pipeline/run", methods=["POST"])
@_require_pipeline_secret
def api_pipeline_run():
  """Trigger the intelligence pipeline. Called by GitHub Actions after nightly data fetch."""
  cookie = os.environ.get("PINNACLE_SESSION_COOKIE", "")
  if not cookie:
    return jsonify({"error": "PINNACLE_SESSION_COOKIE not configured"}), 500
  try:
    html = run_pipeline(session_cookie=cookie)
    return jsonify({"status": "ok", "report_html": html})
  except PermissionError as exc:
    send_alert_email(str(exc))
    return jsonify({"error": "pinnacle_auth_failure", "detail": str(exc)}), 502
  except Exception as exc:
    send_alert_email(f"Pipeline error: {exc}")
    return jsonify({"error": "pipeline_failed", "detail": str(exc)}), 500


@app.route("/bets/prefill", methods=["GET"])
def bets_prefill():
  """Return pre-filled form data for a market from the odds log."""
  market_id = request.args.get("market_id", "")
  markets = load_odds_log()
  market = next((m for m in markets if m.market_id == market_id), None)
  if not market:
    return jsonify({"error": "market not found"}), 404
  return jsonify({
    "market_id": market.market_id,
    "race_name": market.race_name,
    "stage_name": market.stage_name,
    "rider_a_name": market.rider_a_name,
    "rider_b_name": market.rider_b_name,
    "odds_a": market.odds_a,
    "odds_b": market.odds_b,
  })
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_pipeline_endpoint.py -v
```
Expected: All 5 tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v
```
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/app.py tests/test_pipeline_endpoint.py
git commit -m "feat: add pipeline trigger endpoint and bet prefill route to Flask app"
```

---

## Task 9: GitHub Actions + Environment Config

**Files:**
- Modify: `.github/workflows/nightly-pipeline.yml`
- Modify: `.env.example` (create if missing)

- [ ] **Step 1: Add trigger step to nightly pipeline**

Open `.github/workflows/nightly-pipeline.yml`. After the "Commit updated snapshot" step, add:

```yaml
      - name: Trigger intelligence pipeline
        if: success()
        run: |
          curl -s -f -X POST "http://148.230.81.207:5001/api/pipeline/run" \
            -H "X-Pipeline-Secret: ${{ secrets.PIPELINE_SECRET }}" \
            --max-time 600 \
            -o /dev/null \
            && echo "Pipeline triggered successfully" \
            || echo "Pipeline trigger failed — check VPS logs"
```

`--max-time 600` gives the pipeline up to 10 minutes to complete before curl times out. The `|| echo` means a trigger failure does not fail the entire Actions job.

- [ ] **Step 2: Add PIPELINE_SECRET to GitHub Actions**

In the GitHub repo → Settings → Secrets and variables → Actions → New repository secret:
- Name: `PIPELINE_SECRET`
- Value: generate with `python -c "import secrets; print(secrets.token_hex(32))"`

Save the same value to the VPS in `/etc/environment`:
```bash
PIPELINE_SECRET=<the same value>
```

- [ ] **Step 3: Document environment variables**

Create or update `.env.example`:

```bash
# Pinnacle session cookie — extract from browser DevTools after logging in
PINNACLE_SESSION_COOKIE=

# Pinnacle internal API URL — discovered during Task 2 Step 1
PINNACLE_API_URL=

# Anthropic API key for Claude Haiku qualitative research
ANTHROPIC_API_KEY=

# Pipeline trigger shared secret (generate with: python -c "import secrets; print(secrets.token_hex(32))")
PIPELINE_SECRET=

# Email delivery (Gmail: use an App Password, not your main password)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=
REPORT_EMAIL=you@gmail.com
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/nightly-pipeline.yml .env.example
git commit -m "feat: add pipeline trigger step to nightly GH Actions workflow"
```

---

## Task 10: VPS Deployment

**Files:**
- Create: `systemd/paceiq.service`

- [ ] **Step 1: Create the systemd service file**

```ini
# systemd/paceiq.service
[Unit]
Description=PaceIQ Flask App
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/ml-cycling-predictor
Environment=PATH=/root/ml-cycling-predictor/.venv/bin
EnvironmentFile=/etc/environment
ExecStart=/root/ml-cycling-predictor/.venv/bin/python webapp/app.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: SSH into the VPS and set up Python environment**

Run these commands on the VPS (use the Hostinger Terminal or SSH):

```bash
# SSH in
ssh root@148.230.81.207

# Verify Python
python3 --version  # should be 3.11+; if not: apt install python3.11 python3.11-venv

# Clone repo
cd /root
git clone https://github.com/BryanHaakman/ml-cycling-predictor.git
cd ml-cycling-predictor

# Create virtualenv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Install playwright chromium (for future Pinnacle scraping)
playwright install chromium
```

- [ ] **Step 3: Set environment variables**

```bash
# On VPS — append to /etc/environment (one per line, no export keyword)
cat >> /etc/environment << 'EOF'
ANTHROPIC_API_KEY=<your key>
PINNACLE_SESSION_COOKIE=<your session cookie>
PINNACLE_API_URL=<discovered URL from Task 2>
PIPELINE_SECRET=<same value as GitHub Actions secret>
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=<your gmail>
SMTP_PASS=<gmail app password>
REPORT_EMAIL=<destination email>
EOF

# Reload environment
source /etc/environment
```

- [ ] **Step 4: Copy trained model artifacts from local machine**

Run this on your **local machine** (not the VPS):

```bash
scp -r models/trained/ root@148.230.81.207:/root/ml-cycling-predictor/models/
```

- [ ] **Step 5: Install and start the systemd service**

On the VPS:

```bash
cp systemd/paceiq.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable paceiq
systemctl start paceiq
systemctl status paceiq  # should show: Active: active (running)
```

- [ ] **Step 6: Test the pipeline manually**

```bash
# On VPS — dry run first
source /etc/environment
source .venv/bin/activate
python scripts/intelligence_pipeline.py --dry-run

# If dry run succeeds, test full pipeline (sends email)
python scripts/intelligence_pipeline.py
```

- [ ] **Step 7: Test the GitHub Actions trigger locally**

From your local machine:
```bash
curl -v -X POST "http://148.230.81.207:5001/api/pipeline/run" \
  -H "X-Pipeline-Secret: <PIPELINE_SECRET value>"
```
Expected: `{"status": "ok", "report_html": "..."}` within ~5 minutes.

- [ ] **Step 8: Set up cron fallback**

On VPS (in case GitHub Actions webhook is flaky):

```bash
crontab -e
# Add this line:
0 22 * * * source /etc/environment && /root/ml-cycling-predictor/.venv/bin/python /root/ml-cycling-predictor/scripts/intelligence_pipeline.py >> /var/log/paceiq.log 2>&1
```

- [ ] **Step 9: Commit systemd file**

```bash
# On local machine
git add systemd/paceiq.service
git commit -m "feat: add systemd service unit for VPS deployment"
git push
```

Then on VPS: `git pull` to get the latest.

---

## Self-Review Checklist

**Spec coverage:**
- [x] Odds ingestion from Pinnacle — Task 2
- [x] Name resolver with fuzzy matching and cache — Task 3
- [x] Stage context fetch from DB with neutral fallback — Task 4
- [x] Predictions via existing `predict_manual()` — Task 7 orchestrator
- [x] Qualitative research per matchup via Claude Haiku — Task 5
- [x] HTML report with all matchups sorted by edge — Task 6
- [x] Email delivery via SMTP — Task 6
- [x] Report archived to `data/reports/` — Task 6
- [x] `POST /api/pipeline/run` endpoint with secret auth — Task 8
- [x] `GET /bets/prefill` endpoint — Task 8
- [x] GitHub Actions trigger step — Task 9
- [x] VPS deployment with systemd — Task 10
- [x] Cron fallback — Task 10
- [x] `data/odds_log.jsonl` append-only audit log — Task 2
- [x] `data/unresolved_names.json` for low-confidence matches — Task 3
- [x] Partial report on component failure (never hard-crash) — Task 7

**Gap found:** The spec mentions bankroll pulled from P&L tracker at report time — confirmed: Task 7 calls `get_current_bankroll()`. ✓

**Type consistency:**
- `OddsMarket`, `StageContext`, `RiderFlag`, `MatchupIntel`, `ResolvedMarket`, `MatchupResult` defined in Task 1, used consistently in Tasks 2–8. ✓
- `StageContext.to_race_params()` method used in Task 7 `run_pipeline()`. ✓
- `MatchupResult.tier_for_edge()` static method defined in Task 1, called in Task 7. ✓
- `Predictor.predict_manual()` signature matches existing `models/predict.py`. ✓
- `load_odds_log()` defined in Task 2, imported in Task 8. ✓
