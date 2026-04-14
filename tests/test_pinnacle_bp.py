"""Unit tests for webapp/pinnacle_bp.py — both endpoints, all error paths.

Tests are written in RED state first (TDD). They will fail with ImportError
until webapp/pinnacle_bp.py is created in Task 2.
"""
import pytest
import requests
from unittest.mock import patch, MagicMock

from data.odds import OddsMarket, PinnacleAuthError
from data.name_resolver import ResolveResult
from intelligence.stage_context import StageContext


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
  from webapp.app import app
  app.config["TESTING"] = True
  with app.test_client() as c:
    yield c


def _make_stage_context(is_resolved: bool = True) -> StageContext:
  """Helper: build a StageContext for mocking."""
  return StageContext(
    distance=156.0,
    vertical_meters=887,
    profile_icon="p1",
    profile_score=9,
    is_one_day_race=False,
    stage_type="RR",
    race_date="2026-04-28",
    race_base_url="race/tour-de-romandie/2026",
    num_climbs=0,
    avg_temperature=None,
    uci_tour="2.UWT",
    is_resolved=is_resolved,
  )


def _make_market(
  race_name: str = "Tour de Romandie",
  rider_a: str = "ROGLIC Primoz",
  rider_b: str = "VINGEGAARD Jonas",
  odds_a: float = 1.85,
  odds_b: float = 2.10,
  matchup_id: str = "12345",
) -> OddsMarket:
  """Helper: build an OddsMarket for mocking."""
  return OddsMarket(
    race_name=race_name,
    rider_a_name=rider_a,
    rider_b_name=rider_b,
    odds_a=odds_a,
    odds_b=odds_b,
    matchup_id=matchup_id,
  )


def _resolved(url: str = "rider/some-rider") -> ResolveResult:
  return ResolveResult(
    url=url,
    best_candidate_url=None,
    best_candidate_name=None,
    best_score=None,
    method="exact",
  )


def _unresolved(hint_name: str = None, hint_url: str = None) -> ResolveResult:
  return ResolveResult(
    url=None,
    best_candidate_url=hint_url,
    best_candidate_name=hint_name,
    best_score=75,
    method="fuzzy",
  )


# ---------------------------------------------------------------------------
# /api/pinnacle/load tests
# ---------------------------------------------------------------------------

class TestPinnacleLoad:

  def test_load_returns_401_on_auth_error(self, client):
    """Auth error from Pinnacle → 401 with structured error body."""
    with patch("webapp.pinnacle_bp.fetch_cycling_h2h_markets") as mock_fetch:
      mock_fetch.side_effect = PinnacleAuthError("expired")
      resp = client.post(
        "/api/pinnacle/load",
        json={},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
      )
    assert resp.status_code == 401
    body = resp.get_json()
    assert body["type"] == "auth_error"

  def test_load_returns_503_on_network_error(self, client):
    """Network error from Pinnacle → 503 with network_error type."""
    with patch("webapp.pinnacle_bp.fetch_cycling_h2h_markets") as mock_fetch:
      mock_fetch.side_effect = requests.RequestException("timeout")
      resp = client.post(
        "/api/pinnacle/load",
        json={},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
      )
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["type"] == "network_error"

  def test_load_returns_200_with_valid_markets(self, client):
    """Happy path: two markets for same race → proper ResolvedMarket JSON."""
    markets = [
      _make_market(matchup_id="111", rider_a="ROGLIC Primoz", rider_b="VINGEGAARD Jonas"),
      _make_market(matchup_id="222", rider_a="POGACAR Tadej", rider_b="EVENEPOEL Remco"),
    ]
    resolve_result = _resolved("rider/some-rider")
    stage_ctx = _make_stage_context(is_resolved=True)

    with patch("webapp.pinnacle_bp.fetch_cycling_h2h_markets", return_value=markets), \
         patch("webapp.pinnacle_bp.NameResolver") as MockResolver, \
         patch("webapp.pinnacle_bp.fetch_stage_context", return_value=stage_ctx):
      instance = MockResolver.return_value
      instance.resolve.return_value = resolve_result
      resp = client.post(
        "/api/pinnacle/load",
        json={},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
      )

    assert resp.status_code == 200
    body = resp.get_json()
    assert "races" in body
    assert len(body["races"]) == 1
    race = body["races"][0]
    assert race["race_name"] == "Tour de Romandie"
    assert race["stage_resolved"] is True
    assert "stage_context" in race
    assert len(race["pairs"]) == 2
    pair = race["pairs"][0]
    for field in ("pinnacle_name_a", "pinnacle_name_b", "rider_a_url", "rider_b_url",
                  "rider_a_resolved", "rider_b_resolved", "best_candidate_a_name",
                  "best_candidate_a_url", "best_candidate_b_name", "best_candidate_b_url",
                  "odds_a", "odds_b", "matchup_id"):
      assert field in pair, f"Missing field: {field}"

  def test_load_unresolved_pair_includes_hint(self, client):
    """Unresolved rider → url=null, resolved=false, best_candidate fields populated."""
    market = _make_market(rider_a="ROGLIC Primoz", rider_b="VINGEGAARD Jonas")
    hint_result = _unresolved(hint_name="ROGLIC Primoz", hint_url="rider/primoz-roglic")
    resolved_result = _resolved("rider/jonas-vingegaard")
    stage_ctx = _make_stage_context()

    with patch("webapp.pinnacle_bp.fetch_cycling_h2h_markets", return_value=[market]), \
         patch("webapp.pinnacle_bp.NameResolver") as MockResolver, \
         patch("webapp.pinnacle_bp.fetch_stage_context", return_value=stage_ctx):
      instance = MockResolver.return_value
      # First call (rider_a) → unresolved with hint; second call (rider_b) → resolved
      instance.resolve.side_effect = [hint_result, resolved_result]
      resp = client.post(
        "/api/pinnacle/load",
        json={},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
      )

    assert resp.status_code == 200
    pair = resp.get_json()["races"][0]["pairs"][0]
    assert pair["rider_a_url"] is None
    assert pair["rider_a_resolved"] is False
    assert pair["best_candidate_a_name"] == "ROGLIC Primoz"
    assert pair["best_candidate_a_url"] == "rider/primoz-roglic"

  def test_load_requires_localhost(self, client):
    """Non-localhost request → 403 (before any Pinnacle fetch)."""
    resp = client.post(
      "/api/pinnacle/load",
      json={},
      environ_base={"REMOTE_ADDR": "10.0.0.1"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# /api/pinnacle/refresh-odds tests
# ---------------------------------------------------------------------------

class TestPinnacleRefreshOdds:

  def test_refresh_returns_401_on_auth_error(self, client):
    """Auth error → 401 with auth_error type."""
    with patch("webapp.pinnacle_bp.fetch_cycling_h2h_markets") as mock_fetch:
      mock_fetch.side_effect = PinnacleAuthError("expired")
      resp = client.post(
        "/api/pinnacle/refresh-odds",
        json={"matchup_ids": ["123"]},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
      )
    assert resp.status_code == 401
    body = resp.get_json()
    assert body["type"] == "auth_error"

  def test_refresh_returns_400_on_empty_matchup_ids(self, client):
    """Empty matchup_ids list → 400 before calling fetch_cycling_h2h_markets."""
    with patch("webapp.pinnacle_bp.fetch_cycling_h2h_markets") as mock_fetch:
      resp = client.post(
        "/api/pinnacle/refresh-odds",
        json={"matchup_ids": []},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
      )
      mock_fetch.assert_not_called()
    assert resp.status_code == 400

  def test_refresh_returns_updated_odds(self, client):
    """Happy path: returns only {pairs:[{matchup_id, odds_a, odds_b}]}."""
    market = _make_market(matchup_id="123", odds_a=1.90, odds_b=2.05)
    with patch("webapp.pinnacle_bp.fetch_cycling_h2h_markets", return_value=[market]):
      resp = client.post(
        "/api/pinnacle/refresh-odds",
        json={"matchup_ids": ["123"]},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
      )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"pairs": [{"matchup_id": "123", "odds_a": 1.90, "odds_b": 2.05}]}

  def test_refresh_omits_closed_matchups(self, client):
    """matchup_id not in current Pinnacle response → silently omitted."""
    market = _make_market(matchup_id="123", odds_a=1.90, odds_b=2.05)
    with patch("webapp.pinnacle_bp.fetch_cycling_h2h_markets", return_value=[market]):
      resp = client.post(
        "/api/pinnacle/refresh-odds",
        json={"matchup_ids": ["123", "999"]},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
      )
    assert resp.status_code == 200
    body = resp.get_json()
    ids = [p["matchup_id"] for p in body["pairs"]]
    assert "123" in ids
    assert "999" not in ids

  def test_refresh_requires_localhost(self, client):
    """Non-localhost request → 403."""
    resp = client.post(
      "/api/pinnacle/refresh-odds",
      json={"matchup_ids": ["123"]},
      environ_base={"REMOTE_ADDR": "10.0.0.1"},
    )
    assert resp.status_code == 403
