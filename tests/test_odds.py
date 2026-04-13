"""
Unit tests for data/odds.py — Pinnacle cycling H2H market client.

Tests cover:
- _american_to_decimal() conversion formula
- _get_api_key() lookup chain (env var -> cache -> JS bundle)
- _check_auth() raises on 401/403
- _append_audit_log() JSONL output
- fetch_cycling_h2h_markets() flow, auth retry, and empty-market behavior
- OddsMarket dataclass fields and types
"""

import dataclasses
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from unittest.mock import MagicMock, patch, mock_open

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
  """Tests for _get_api_key() lookup chain."""

  def test_returns_cached_key(self):
    """Disk cache exists -> returns cached static API key."""
    with patch("os.path.exists", return_value=True):
      with patch("builtins.open", mock_open(read_data="CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R\n")):
        with patch("data.odds.KEY_CACHE_PATH", "/fake/cache"):
          key = _get_api_key()
    self.assertEqual(key, "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R")

  def test_returns_cache_when_env_absent(self):
    with patch.dict(os.environ, {}, clear=True):
      # Remove the env var if present
      env = {k: v for k, v in os.environ.items() if k != "PINNACLE_SESSION_COOKIE"}
      with patch.dict(os.environ, env, clear=True):
        with patch("os.path.exists", return_value=True):
          with patch("builtins.open", mock_open(read_data="cachedkey456\n")):
            # Also patch KEY_CACHE_PATH check
            with patch("data.odds.KEY_CACHE_PATH", "/fake/cache"):
              key = _get_api_key()
        self.assertEqual(key, "cachedkey456")

  def test_calls_bundle_extraction_when_no_env_no_cache(self):
    """When env var absent and no cache file, _extract_key_from_bundle() is called."""
    env = {k: v for k, v in os.environ.items() if k != "PINNACLE_SESSION_COOKIE"}
    with patch.dict(os.environ, env, clear=True):
      with patch("data.odds.KEY_CACHE_PATH", "/nonexistent/path/cache"):
        with patch("data.odds._extract_key_from_bundle", return_value="bundlekey789") as mock_extract:
          with patch("builtins.open", mock_open()):
            key = _get_api_key()
          mock_extract.assert_called_once()
          self.assertEqual(key, "bundlekey789")

  def test_raises_pinnacle_auth_error_when_all_paths_fail(self):
    """When no cache and bundle extraction returns None -> raises PinnacleAuthError."""
    with patch("data.odds.KEY_CACHE_PATH", "/nonexistent/path/cache"):
      with patch("data.odds._extract_key_from_bundle", return_value=None):
        with self.assertRaises(PinnacleAuthError) as ctx:
          _get_api_key()
        self.assertIn("API key", str(ctx.exception))


class TestSessionTokenInFetch(unittest.TestCase):
  """Tests for X-Session header integration in fetch_cycling_h2h_markets (D-10)."""

  def test_env_var_sets_x_session_header(self):
    """PINNACLE_SESSION_COOKIE env var -> sent as X-Session header (D-05)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name
    try:
      with patch.dict(os.environ, {"PINNACLE_SESSION_COOKIE": "manual_session"}):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("data.odds._get_api_key", return_value="static_key"):
            with patch("requests.get") as mock_get:
              resp = MagicMock()
              resp.status_code = 200
              resp.json.return_value = []
              mock_get.return_value = resp
              fetch_cycling_h2h_markets()
              # Check the headers sent in the request
              call_headers = mock_get.call_args[1]["headers"]
              self.assertEqual(call_headers["X-Api-Key"], "static_key")
              self.assertEqual(call_headers["X-Session"], "manual_session")
    finally:
      os.unlink(tmp_path)

  def test_session_manager_called_when_no_env_var(self):
    """No PINNACLE_SESSION_COOKIE -> get_session_token() called for X-Session."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name
    try:
      env = {k: v for k, v in os.environ.items() if k != "PINNACLE_SESSION_COOKIE"}
      with patch.dict(os.environ, env, clear=True):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("data.odds._get_api_key", return_value="static_key"):
            with patch("data.session_manager.get_session_token", return_value="playwright_session") as mock_st:
              with patch("requests.get") as mock_get:
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = []
                mock_get.return_value = resp
                fetch_cycling_h2h_markets()
                mock_st.assert_called_once()
                call_headers = mock_get.call_args[1]["headers"]
                self.assertEqual(call_headers["X-Session"], "playwright_session")
    finally:
      os.unlink(tmp_path)

  def test_no_x_session_when_session_manager_returns_none(self):
    """get_session_token() returns None -> X-Session header not sent."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name
    try:
      env = {k: v for k, v in os.environ.items() if k != "PINNACLE_SESSION_COOKIE"}
      with patch.dict(os.environ, env, clear=True):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("data.odds._get_api_key", return_value="static_key"):
            with patch("data.session_manager.get_session_token", return_value=None):
              with patch("requests.get") as mock_get:
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = []
                mock_get.return_value = resp
                fetch_cycling_h2h_markets()
                call_headers = mock_get.call_args[1]["headers"]
                self.assertNotIn("X-Session", call_headers)
    finally:
      os.unlink(tmp_path)


class TestInvalidateSessionOn401(unittest.TestCase):
  """Tests that invalidate_session() is called on 401/403 retry (D-12)."""

  def test_401_calls_invalidate_session(self):
    """On 401 during fetch, invalidate_session() called alongside _invalidate_key_cache()."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch.dict(os.environ, {"PINNACLE_SESSION_COOKIE": "initialkey"}):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("data.odds._extract_key_from_bundle", return_value="newkey"):
            with patch("requests.get") as mock_get:
              auth_fail_resp = MagicMock()
              auth_fail_resp.status_code = 401
              auth_fail_resp.json.return_value = {"status": 401}

              leagues_resp = MagicMock()
              leagues_resp.status_code = 200
              leagues_resp.json.return_value = []

              mock_get.side_effect = [auth_fail_resp, leagues_resp]

              with patch("data.odds._invalidate_key_cache") as mock_inv_cache:
                with patch("data.session_manager.invalidate_session") as mock_inv_session:
                  result = fetch_cycling_h2h_markets()
                  mock_inv_cache.assert_called_once()
                  mock_inv_session.assert_called_once()
                  self.assertEqual(result, [])
    finally:
      os.unlink(tmp_path)


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
    self.assertIn("PINNACLE_SESSION_COOKIE", str(ctx.exception))
    self.assertIn("401", str(ctx.exception))

  def test_raises_on_403(self):
    resp = self._make_response(403)
    with self.assertRaises(PinnacleAuthError) as ctx:
      _check_auth(resp)
    self.assertIn("PINNACLE_SESSION_COOKIE", str(ctx.exception))
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
  """Tests for fetch_cycling_h2h_markets()."""

  def _make_league_response(self, leagues: list) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = leagues
    return resp

  def _make_matchups_response(self, matchups: list) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = matchups
    return resp

  def _make_markets_response(self, markets: list) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = markets
    return resp

  def _sample_league(self):
    return [{"id": 8227, "name": "Paris-Roubaix"}]

  def _sample_matchups(self):
    return [
      {
        "id": 1628017725,
        "participants": [
          {"alignment": "home", "name": "Tomas Kopecky", "order": 0},
          {"alignment": "away", "name": "Brent van Moer", "order": 1},
        ],
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
      with patch.dict(os.environ, {"PINNACLE_SESSION_COOKIE": "validkey"}):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("requests.get") as mock_get:
            # Leagues response with one league, no matchups
            leagues_resp = self._make_league_response(self._sample_league())
            matchups_resp = self._make_matchups_response([])
            markets_resp = self._make_markets_response([])
            mock_get.side_effect = [leagues_resp, matchups_resp, markets_resp]

            result = fetch_cycling_h2h_markets()
            self.assertEqual(result, [])
    finally:
      os.unlink(tmp_path)

  def test_returns_odds_market_objects(self):
    """Returns list of OddsMarket with decimal odds."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch.dict(os.environ, {"PINNACLE_SESSION_COOKIE": "validkey"}):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("requests.get") as mock_get:
            leagues_resp = self._make_league_response(self._sample_league())
            matchups_resp = self._make_matchups_response(self._sample_matchups())
            markets_resp = self._make_markets_response(self._sample_markets())
            mock_get.side_effect = [leagues_resp, matchups_resp, markets_resp]

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
    """First 401 -> cache invalidated -> _extract_key_from_bundle called once -> retry succeeds."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      env = {k: v for k, v in os.environ.items() if k != "PINNACLE_SESSION_COOKIE"}
      with patch.dict(os.environ, env, clear=True):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("data.odds.KEY_CACHE_PATH", "/fake/cache"):
            with patch("data.odds._extract_key_from_bundle", return_value="newkey") as mock_extract:
              with patch("requests.get") as mock_get:
                # First request (leagues) -> 401
                auth_fail_resp = MagicMock()
                auth_fail_resp.status_code = 401
                auth_fail_resp.json.return_value = {"status": 401, "detail": "No auth"}

                # Second request (leagues after retry) -> 200
                leagues_resp = self._make_league_response(self._sample_league())
                matchups_resp = self._make_matchups_response([])
                markets_resp = self._make_markets_response([])
                mock_get.side_effect = [
                  auth_fail_resp,
                  leagues_resp,
                  matchups_resp,
                  markets_resp,
                ]

                # Simulate: first _get_api_key() call returns "oldkey" via env var
                # After 401, _invalidate_key_cache is called (real), then _get_api_key()
                # finds no env var and no cache -> calls _extract_key_from_bundle
                # We patch _get_api_key to return "oldkey" on first call, then
                # use real logic (which calls _extract_key_from_bundle) on retry
                call_count = {"n": 0}
                original_get_api_key = odds_module._get_api_key

                def mock_get_api_key_side_effect():
                  call_count["n"] += 1
                  if call_count["n"] == 1:
                    return "oldkey"
                  # Second call: no env var, no cache -> extract from bundle
                  return original_get_api_key()

                with patch("data.odds._get_api_key", side_effect=mock_get_api_key_side_effect):
                  with patch("data.odds._invalidate_key_cache") as mock_invalidate:
                    # os.path.exists returns False so _extract_key_from_bundle is called
                    with patch("os.path.exists", return_value=False):
                      result = fetch_cycling_h2h_markets()
                      mock_invalidate.assert_called_once()
                      mock_extract.assert_called_once()
                      self.assertEqual(result, [])
    finally:
      os.unlink(tmp_path)

  def test_auth_401_raises_after_one_retry(self):
    """First 401 -> re-extract -> second 401 -> raises PinnacleAuthError (no third attempt)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      env = {k: v for k, v in os.environ.items() if k != "PINNACLE_SESSION_COOKIE"}
      with patch.dict(os.environ, env, clear=True):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("data.odds.KEY_CACHE_PATH", "/fake/cache"):
            with patch("data.odds._extract_key_from_bundle", return_value="newkey"):
              with patch("os.path.exists", return_value=True):
                with patch("builtins.open", mock_open(read_data="oldkey\n")):
                  with patch("requests.get") as mock_get:
                    auth_fail_resp_1 = MagicMock()
                    auth_fail_resp_1.status_code = 401
                    auth_fail_resp_1.json.return_value = {"status": 401}

                    auth_fail_resp_2 = MagicMock()
                    auth_fail_resp_2.status_code = 401
                    auth_fail_resp_2.json.return_value = {"status": 401}

                    mock_get.side_effect = [auth_fail_resp_1, auth_fail_resp_2]

                    with patch("data.odds._invalidate_key_cache"):
                      with self.assertRaises(PinnacleAuthError):
                        fetch_cycling_h2h_markets()

                    # Verify no third attempt was made (only 2 calls)
                    self.assertEqual(mock_get.call_count, 2)
    finally:
      os.unlink(tmp_path)

  def test_auth_401_then_200_succeeds(self):
    """First 401 -> re-extract -> second call 200 -> returns markets list, no raise."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
      tmp_path = f.name

    try:
      with patch.dict(os.environ, {"PINNACLE_SESSION_COOKIE": "initialkey"}):
        with patch("data.odds.ODDS_LOG_PATH", tmp_path):
          with patch("data.odds._extract_key_from_bundle", return_value="newkey"):
            with patch("requests.get") as mock_get:
              auth_fail_resp = MagicMock()
              auth_fail_resp.status_code = 401
              auth_fail_resp.json.return_value = {"status": 401}

              leagues_resp = self._make_league_response(self._sample_league())
              matchups_resp = self._make_matchups_response(self._sample_matchups())
              markets_resp = self._make_markets_response(self._sample_markets())
              mock_get.side_effect = [auth_fail_resp, leagues_resp, matchups_resp, markets_resp]

              with patch("data.odds._invalidate_key_cache"):
                result = fetch_cycling_h2h_markets()
                self.assertIsInstance(result, list)
                self.assertEqual(len(result), 1)
    finally:
      os.unlink(tmp_path)


if __name__ == "__main__":
  unittest.main()
