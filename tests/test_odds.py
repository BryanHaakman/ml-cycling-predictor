"""
Unit tests for data/odds.py — Pinnacle cycling H2H market client.

Tests cover:
- _american_to_decimal() conversion formula
- _get_api_key() lookup chain (cache -> JS bundle, no PINNACLE_SESSION_COOKIE)
- _check_auth() raises on 401/403
- _append_audit_log() JSONL output
- fetch_cycling_h2h_markets() 2-call sport-level flow, auth retry, and empty-market behavior
- OddsMarket dataclass fields and types
- Guest API constant, The Field filter, no X-Session header, race name from league
"""

import dataclasses
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from unittest.mock import MagicMock, patch, mock_open, call

# Ensure repo root is on path for absolute imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.odds as odds_module
from data.odds import (
  OddsMarket,
  PinnacleAuthError,
  _american_to_decimal,
  _get_api_key,
  _check_auth,
  _append_audit_log,
  _invalidate_key_cache,
  fetch_cycling_h2h_markets,
)


class TestAmericanToDecimal(unittest.TestCase):
  """Tests for _american_to_decimal()."""

  def test_positive_odds_107(self):
    self.assertAlmostEqual(_american_to_decimal(107), 2.07, places=4)

  def test_negative_odds_154(self):
    expected = round(100 / 154 + 1, 4)
    self.assertAlmostEqual(_american_to_decimal(-154), expected, places=4)

  def test_negative_100_is_evens(self):
    self.assertAlmostEqual(_american_to_decimal(-100), 2.0, places=4)

  def test_positive_100(self):
    self.assertAlmostEqual(_american_to_decimal(100), 2.0, places=4)

  def test_positive_200(self):
    self.assertAlmostEqual(_american_to_decimal(200), 3.0, places=4)

  def test_negative_200(self):
    self.assertAlmostEqual(_american_to_decimal(-200), 1.5, places=4)


class TestOddsMarketDataclass(unittest.TestCase):
  """Tests for OddsMarket dataclass structure."""

  def test_fields_exist(self):
    fields = {f.name for f in dataclasses.fields(OddsMarket)}
    expected = {"rider_a_name", "rider_b_name", "odds_a", "odds_b", "race_name", "matchup_id"}
    self.assertEqual(fields, expected)

  def test_field_order(self):
    field_names = [f.name for f in dataclasses.fields(OddsMarket)]
    self.assertEqual(
      field_names,
      ["rider_a_name", "rider_b_name", "odds_a", "odds_b", "race_name", "matchup_id"],
    )

  def test_matchup_id_typed_as_str(self):
    hints = {f.name: f.type for f in dataclasses.fields(OddsMarket)}
    # type may be the actual type or a string annotation
    matchup_id_type = hints.get("matchup_id")
    self.assertIn(matchup_id_type, (str, "str"))

  def test_instantiation(self):
    m = OddsMarket(
      rider_a_name="Rider A",
      rider_b_name="Rider B",
      odds_a=1.85,
      odds_b=2.10,
      race_name="Paris-Roubaix",
      matchup_id="12345",
    )
    self.assertIsInstance(m.matchup_id, str)
    self.assertEqual(m.race_name, "Paris-Roubaix")


class TestGetApiKey(unittest.TestCase):
  """Tests for _get_api_key() lookup chain (cache -> JS bundle, no env var)."""

  def test_returns_cache_when_available(self):
    """Returns key from disk cache when file exists and is non-empty."""
    env = {k: v for k, v in os.environ.items() if k not in ("PINNACLE_SESSION_COOKIE", "PINNACLE_SESSION")}
    with patch.dict(os.environ, env, clear=True):
      with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data="cachedkey456\n")):
          with patch("data.odds.KEY_CACHE_PATH", "/fake/cache"):
            key = _get_api_key()
      self.assertEqual(key, "cachedkey456")

  def test_calls_bundle_extraction_when_no_cache(self):
    """When no cache file, _extract_key_from_bundle() is called."""
    env = {k: v for k, v in os.environ.items() if k not in ("PINNACLE_SESSION_COOKIE", "PINNACLE_SESSION")}
    with patch.dict(os.environ, env, clear=True):
      with patch("data.odds.KEY_CACHE_PATH", "/nonexistent/path/cache"):
        with patch("data.odds._extract_key_from_bundle", return_value="bundlekey789") as mock_extract:
          with patch("builtins.open", mock_open()):
            key = _get_api_key()
          mock_extract.assert_called_once()
          self.assertEqual(key, "bundlekey789")

  def test_raises_pinnacle_auth_error_when_all_paths_fail(self):
    """When no cache and bundle extraction returns None -> raises PinnacleAuthError."""
    env = {k: v for k, v in os.environ.items() if k not in ("PINNACLE_SESSION_COOKIE", "PINNACLE_SESSION")}
    with patch.dict(os.environ, env, clear=True):
      with patch("data.odds.KEY_CACHE_PATH", "/nonexistent/path/cache"):
        with patch("data.odds._extract_key_from_bundle", return_value=None):
          with self.assertRaises(PinnacleAuthError):
            _get_api_key()


class TestCheckAuth(unittest.TestCase):
  """Tests for _check_auth()."""

  def _make_response(self, status_code: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    return resp

  def test_raises_on_401(self):
    resp = self._make_response(401)
    with self.assertRaises(PinnacleAuthError) as ctx:
      _check_auth(resp)
    self.assertIn("401", str(ctx.exception))

  def test_raises_on_403(self):
    resp = self._make_response(403)
    with self.assertRaises(PinnacleAuthError) as ctx:
      _check_auth(resp)
    self.assertIn("403", str(ctx.exception))

  def test_does_not_raise_on_200(self):
    resp = self._make_response(200)
    # Should not raise
    _check_auth(resp)


class TestAppendAuditLog(unittest.TestCase):
  """Tests for _append_audit_log()."""

  def test_writes_valid_json_line(self):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      original = odds_module.ODDS_LOG_PATH
      odds_module.ODDS_LOG_PATH = tmp_path
      _append_audit_log([], "empty")
      odds_module.ODDS_LOG_PATH = original

      with open(tmp_path) as fh:
        line = fh.readline().strip()
      record = json.loads(line)
      self.assertIn("fetched_at", record)
      self.assertIn("status", record)
      self.assertIn("market_count", record)
      self.assertIn("markets", record)
    finally:
      os.unlink(tmp_path)

  def test_empty_markets_writes_empty_list(self):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      original = odds_module.ODDS_LOG_PATH
      odds_module.ODDS_LOG_PATH = tmp_path
      _append_audit_log([], "empty")
      odds_module.ODDS_LOG_PATH = original

      with open(tmp_path) as fh:
        record = json.loads(fh.readline())
      self.assertEqual(record["markets"], [])
      self.assertEqual(record["status"], "empty")
      self.assertEqual(record["market_count"], 0)
    finally:
      os.unlink(tmp_path)

  def test_markets_serialized_as_dicts(self):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      market = OddsMarket(
        rider_a_name="A",
        rider_b_name="B",
        odds_a=1.85,
        odds_b=2.10,
        race_name="Test Race",
        matchup_id="999",
      )
      original = odds_module.ODDS_LOG_PATH
      odds_module.ODDS_LOG_PATH = tmp_path
      _append_audit_log([market], "ok")
      odds_module.ODDS_LOG_PATH = original

      with open(tmp_path) as fh:
        record = json.loads(fh.readline())
      self.assertEqual(record["market_count"], 1)
      self.assertEqual(len(record["markets"]), 1)
      self.assertEqual(record["markets"][0]["rider_a_name"], "A")
    finally:
      os.unlink(tmp_path)


class TestFetchCyclingH2hMarkets(unittest.TestCase):
  """Tests for fetch_cycling_h2h_markets() with sport-level 2-call pattern."""

  def _make_response(self, data, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    return resp

  def _sample_matchups(self):
    return [
      {
        "id": 1628017725,
        "participants": [
          {"alignment": "home", "name": "Tomas Kopecky", "order": 0},
          {"alignment": "away", "name": "Brent van Moer", "order": 1},
        ],
        "league": {"id": 8227, "name": "Paris-Roubaix"},
        "status": "pending",
        "type": "matchup",
      }
    ]

  def _sample_markets(self):
    return [
      {
        "matchupId": 1628017725,
        "status": "open",
        "type": "moneyline",
        "prices": [
          {"designation": "home", "price": -154},
          {"designation": "away", "price": 107},
        ],
      }
    ]

  def test_returns_empty_list_when_no_open_markets(self):
    """Returns [] without raising when API has no open markets."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch("data.odds._get_api_key", return_value="validkey"):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("requests.get") as mock_get:
            matchups_resp = self._make_response([])
            markets_resp = self._make_response([])
            mock_get.side_effect = [matchups_resp, markets_resp]

            result = fetch_cycling_h2h_markets()
            self.assertEqual(result, [])
    finally:
      os.unlink(tmp_path)

  def test_returns_odds_market_objects(self):
    """Returns list of OddsMarket with decimal odds."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch("data.odds._get_api_key", return_value="validkey"):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("requests.get") as mock_get:
            matchups_resp = self._make_response(self._sample_matchups())
            markets_resp = self._make_response(self._sample_markets())
            mock_get.side_effect = [matchups_resp, markets_resp]

            result = fetch_cycling_h2h_markets()
            self.assertEqual(len(result), 1)
            self.assertIsInstance(result[0], OddsMarket)
            self.assertEqual(result[0].rider_a_name, "Tomas Kopecky")
            self.assertEqual(result[0].rider_b_name, "Brent van Moer")
            self.assertEqual(result[0].matchup_id, "1628017725")
            # Verify decimal conversion
            self.assertAlmostEqual(result[0].odds_a, round(100 / 154 + 1, 4), places=4)
            self.assertAlmostEqual(result[0].odds_b, 2.07, places=4)
    finally:
      os.unlink(tmp_path)

  def test_auth_401_invalidates_cache_and_retries(self):
    """First 401 -> cache invalidated -> retry once -> succeeds."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch("data.odds.ODDS_LOG_PATH", tmp_path):
        with patch("data.odds._invalidate_key_cache") as mock_invalidate:
          call_count = {"n": 0}

          def mock_get_api_key():
            call_count["n"] += 1
            return "key" + str(call_count["n"])

          with patch("data.odds._get_api_key", side_effect=mock_get_api_key):
            with patch("requests.get") as mock_get:
              auth_fail_resp = MagicMock()
              auth_fail_resp.status_code = 401
              auth_fail_resp.json.return_value = {"status": 401}

              matchups_resp = self._make_response([])
              markets_resp = self._make_response([])
              mock_get.side_effect = [auth_fail_resp, matchups_resp, markets_resp]

              result = fetch_cycling_h2h_markets()
              mock_invalidate.assert_called_once()
              self.assertEqual(result, [])
    finally:
      os.unlink(tmp_path)

  def test_auth_401_raises_after_one_retry(self):
    """First 401 -> retry -> second 401 -> raises PinnacleAuthError."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch("data.odds.ODDS_LOG_PATH", tmp_path):
        with patch("data.odds._get_api_key", return_value="somekey"):
          with patch("data.odds._invalidate_key_cache"):
            with patch("requests.get") as mock_get:
              auth_fail_resp_1 = MagicMock()
              auth_fail_resp_1.status_code = 401

              auth_fail_resp_2 = MagicMock()
              auth_fail_resp_2.status_code = 401

              mock_get.side_effect = [auth_fail_resp_1, auth_fail_resp_2]

              with self.assertRaises(PinnacleAuthError):
                fetch_cycling_h2h_markets()

              # Verify no third attempt was made (only 2 calls)
              self.assertEqual(mock_get.call_count, 2)
    finally:
      os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# New guest API tests
# ---------------------------------------------------------------------------

class TestGuestApiConstant(unittest.TestCase):
  """Test that PINNACLE_API_BASE points to the guest API subdomain."""

  def test_base_url_is_guest_subdomain(self):
    from data.odds import PINNACLE_API_BASE
    self.assertIn("guest.api.arcadia.pinnacle.com", PINNACLE_API_BASE)

  def test_base_url_uses_https(self):
    from data.odds import PINNACLE_API_BASE
    self.assertTrue(PINNACLE_API_BASE.startswith("https://"))

  def test_base_url_not_authed_subdomain(self):
    """Ensure we're not accidentally using the auth-required subdomain."""
    from data.odds import PINNACLE_API_BASE
    # The auth-required subdomain is api.arcadia.pinnacle.com (not guest.api.*)
    self.assertNotIn("https://api.arcadia.pinnacle.com", PINNACLE_API_BASE)


class TestTheFieldFilter(unittest.TestCase):
  """Test that matchups with 'The Field' participant are excluded from results."""

  def _make_response(self, data, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    return resp

  def test_field_as_rider_b_is_excluded(self):
    """Matchup where rider_b is 'The Field' should not appear in results."""
    matchups = [
      {
        "id": 1111,
        "participants": [
          {"alignment": "home", "name": "Ivan Romeo", "order": 0},
          {"alignment": "away", "name": "The Field", "order": 1},
        ],
        "league": {"id": 999, "name": "O Gran Camino"},
        "status": "pending",
        "type": "matchup",
      }
    ]
    markets = [
      {
        "matchupId": 1111,
        "status": "open",
        "type": "moneyline",
        "prices": [
          {"designation": "home", "price": -200},
          {"designation": "away", "price": 150},
        ],
      }
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch("data.odds._get_api_key", return_value="key"):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("requests.get") as mock_get:
            mock_get.side_effect = [
              self._make_response(matchups),
              self._make_response(markets),
            ]
            result = fetch_cycling_h2h_markets()
            self.assertEqual(result, [])
    finally:
      os.unlink(tmp_path)

  def test_field_as_rider_a_is_excluded(self):
    """Matchup where rider_a is 'The Field' should not appear in results."""
    matchups = [
      {
        "id": 2222,
        "participants": [
          {"alignment": "home", "name": "The Field", "order": 0},
          {"alignment": "away", "name": "Txomin Juaristi", "order": 1},
        ],
        "league": {"id": 999, "name": "O Gran Camino"},
        "status": "pending",
        "type": "matchup",
      }
    ]
    markets = [
      {
        "matchupId": 2222,
        "status": "open",
        "type": "moneyline",
        "prices": [
          {"designation": "home", "price": -300},
          {"designation": "away", "price": 200},
        ],
      }
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch("data.odds._get_api_key", return_value="key"):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("requests.get") as mock_get:
            mock_get.side_effect = [
              self._make_response(matchups),
              self._make_response(markets),
            ]
            result = fetch_cycling_h2h_markets()
            self.assertEqual(result, [])
    finally:
      os.unlink(tmp_path)

  def test_mixed_matchups_field_excluded_h2h_kept(self):
    """When some matchups have The Field and some are H2H, only H2H are returned."""
    matchups = [
      {
        "id": 1111,
        "participants": [
          {"alignment": "home", "name": "Ivan Romeo", "order": 0},
          {"alignment": "away", "name": "The Field", "order": 1},
        ],
        "league": {"id": 999, "name": "O Gran Camino"},
        "status": "pending",
        "type": "matchup",
      },
      {
        "id": 2222,
        "participants": [
          {"alignment": "home", "name": "Ivan Romeo", "order": 0},
          {"alignment": "away", "name": "Txomin Juaristi", "order": 1},
        ],
        "league": {"id": 999, "name": "O Gran Camino"},
        "status": "pending",
        "type": "matchup",
      },
    ]
    markets = [
      {
        "matchupId": 1111,
        "status": "open",
        "type": "moneyline",
        "prices": [
          {"designation": "home", "price": -200},
          {"designation": "away", "price": 150},
        ],
      },
      {
        "matchupId": 2222,
        "status": "open",
        "type": "moneyline",
        "prices": [
          {"designation": "home", "price": -154},
          {"designation": "away", "price": 107},
        ],
      },
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch("data.odds._get_api_key", return_value="key"):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("requests.get") as mock_get:
            mock_get.side_effect = [
              self._make_response(matchups),
              self._make_response(markets),
            ]
            result = fetch_cycling_h2h_markets()
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].rider_a_name, "Ivan Romeo")
            self.assertEqual(result[0].rider_b_name, "Txomin Juaristi")
    finally:
      os.unlink(tmp_path)


class TestSportLevelFetch(unittest.TestCase):
  """Test that fetch_cycling_h2h_markets makes exactly 2 sport-level calls."""

  def _make_response(self, data, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    return resp

  def test_exactly_two_http_calls(self):
    """fetch_cycling_h2h_markets makes exactly 2 GET calls total."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch("data.odds._get_api_key", return_value="key"):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("requests.get") as mock_get:
            mock_get.side_effect = [
              self._make_response([]),
              self._make_response([]),
            ]
            fetch_cycling_h2h_markets()
            self.assertEqual(mock_get.call_count, 2)
    finally:
      os.unlink(tmp_path)

  def test_first_call_is_sport_matchups_endpoint(self):
    """First HTTP call goes to /sports/45/matchups."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch("data.odds._get_api_key", return_value="key"):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("requests.get") as mock_get:
            mock_get.side_effect = [
              self._make_response([]),
              self._make_response([]),
            ]
            fetch_cycling_h2h_markets()
            first_call_url = mock_get.call_args_list[0][0][0]
            self.assertIn("/sports/45/matchups", first_call_url)
    finally:
      os.unlink(tmp_path)

  def test_second_call_is_sport_markets_endpoint(self):
    """Second HTTP call goes to /sports/45/markets/straight."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch("data.odds._get_api_key", return_value="key"):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("requests.get") as mock_get:
            mock_get.side_effect = [
              self._make_response([]),
              self._make_response([]),
            ]
            fetch_cycling_h2h_markets()
            second_call_url = mock_get.call_args_list[1][0][0]
            self.assertIn("/sports/45/markets/straight", second_call_url)
    finally:
      os.unlink(tmp_path)


class TestNoSessionHeader(unittest.TestCase):
  """Test that no X-Session header is sent in any request."""

  def _make_response(self, data, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    return resp

  def test_no_x_session_header_in_matchups_call(self):
    """X-Session header is NOT present in the matchups request."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch("data.odds._get_api_key", return_value="key"):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("requests.get") as mock_get:
            mock_get.side_effect = [
              self._make_response([]),
              self._make_response([]),
            ]
            fetch_cycling_h2h_markets()
            # Check headers of both calls
            for call_args in mock_get.call_args_list:
              headers = call_args[1].get("headers", {})
              self.assertNotIn("X-Session", headers)
    finally:
      os.unlink(tmp_path)

  def test_x_api_key_header_present(self):
    """X-Api-Key courtesy header IS present in requests."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch("data.odds._get_api_key", return_value="testkey123"):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("requests.get") as mock_get:
            mock_get.side_effect = [
              self._make_response([]),
              self._make_response([]),
            ]
            fetch_cycling_h2h_markets()
            for call_args in mock_get.call_args_list:
              headers = call_args[1].get("headers", {})
              self.assertIn("X-Api-Key", headers)
              self.assertEqual(headers["X-Api-Key"], "testkey123")
    finally:
      os.unlink(tmp_path)


class TestRaceNameFromLeague(unittest.TestCase):
  """Test that race_name is extracted from matchup['league']['name']."""

  def _make_response(self, data, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    return resp

  def test_race_name_from_matchup_league_name(self):
    """OddsMarket.race_name equals matchup['league']['name']."""
    matchups = [
      {
        "id": 5555,
        "participants": [
          {"alignment": "home", "name": "Rider A", "order": 0},
          {"alignment": "away", "name": "Rider B", "order": 1},
        ],
        "league": {"id": 285810, "name": "O Gran Camino"},
        "status": "pending",
        "type": "matchup",
      }
    ]
    markets = [
      {
        "matchupId": 5555,
        "status": "open",
        "type": "moneyline",
        "prices": [
          {"designation": "home", "price": -150},
          {"designation": "away", "price": 120},
        ],
      }
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch("data.odds._get_api_key", return_value="key"):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("requests.get") as mock_get:
            mock_get.side_effect = [
              self._make_response(matchups),
              self._make_response(markets),
            ]
            result = fetch_cycling_h2h_markets()
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].race_name, "O Gran Camino")
    finally:
      os.unlink(tmp_path)

  def test_empty_matchups_returns_empty_list(self):
    """When matchups endpoint returns [], result is [] with no error."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch("data.odds._get_api_key", return_value="key"):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("requests.get") as mock_get:
            mock_get.side_effect = [
              self._make_response([]),
              self._make_response([]),
            ]
            result = fetch_cycling_h2h_markets()
            self.assertEqual(result, [])
    finally:
      os.unlink(tmp_path)

  def test_non_open_market_skipped(self):
    """Matchup whose market status is not 'open' is skipped."""
    matchups = [
      {
        "id": 6666,
        "participants": [
          {"alignment": "home", "name": "Rider A", "order": 0},
          {"alignment": "away", "name": "Rider B", "order": 1},
        ],
        "league": {"id": 999, "name": "Test Race"},
        "status": "pending",
        "type": "matchup",
      }
    ]
    markets = [
      {
        "matchupId": 6666,
        "status": "suspended",  # not "open"
        "type": "moneyline",
        "prices": [
          {"designation": "home", "price": -154},
          {"designation": "away", "price": 107},
        ],
      }
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch("data.odds._get_api_key", return_value="key"):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("requests.get") as mock_get:
            mock_get.side_effect = [
              self._make_response(matchups),
              self._make_response(markets),
            ]
            result = fetch_cycling_h2h_markets()
            self.assertEqual(result, [])
    finally:
      os.unlink(tmp_path)

  def test_matchup_with_fewer_than_two_participants_skipped(self):
    """Matchup with fewer than 2 participants is skipped gracefully."""
    matchups = [
      {
        "id": 7777,
        "participants": [
          {"alignment": "home", "name": "Solo Rider", "order": 0},
        ],
        "league": {"id": 999, "name": "Test Race"},
        "status": "pending",
        "type": "matchup",
      }
    ]
    markets = [
      {
        "matchupId": 7777,
        "status": "open",
        "type": "moneyline",
        "prices": [
          {"designation": "home", "price": -154},
          {"designation": "away", "price": 107},
        ],
      }
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch("data.odds._get_api_key", return_value="key"):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("requests.get") as mock_get:
            mock_get.side_effect = [
              self._make_response(matchups),
              self._make_response(markets),
            ]
            result = fetch_cycling_h2h_markets()
            self.assertEqual(result, [])
    finally:
      os.unlink(tmp_path)


if __name__ == "__main__":
  unittest.main()
