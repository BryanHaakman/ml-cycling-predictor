"""
Unit tests for config.py — centralized configuration constants.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConfigConstants(unittest.TestCase):
  """Verify all migrated constants exist and have correct types."""

  def test_pinnacle_api_base_is_string(self):
    from config import PINNACLE_API_BASE
    self.assertIsInstance(PINNACLE_API_BASE, str)
    self.assertTrue(PINNACLE_API_BASE.startswith("https://"))

  def test_pinnacle_home_url_is_string(self):
    from config import PINNACLE_HOME_URL
    self.assertIsInstance(PINNACLE_HOME_URL, str)
    self.assertIn("pinnacle.ca", PINNACLE_HOME_URL)

  def test_pinnacle_cycling_sport_id_is_int(self):
    from config import PINNACLE_CYCLING_SPORT_ID
    self.assertIsInstance(PINNACLE_CYCLING_SPORT_ID, int)
    self.assertEqual(PINNACLE_CYCLING_SPORT_ID, 45)

  def test_request_timeout_is_int(self):
    from config import REQUEST_TIMEOUT
    self.assertIsInstance(REQUEST_TIMEOUT, int)
    self.assertGreater(REQUEST_TIMEOUT, 0)

  def test_key_cache_path_is_absolute(self):
    from config import KEY_CACHE_PATH
    self.assertIsInstance(KEY_CACHE_PATH, str)
    self.assertTrue(os.path.isabs(KEY_CACHE_PATH))

  def test_odds_log_path_is_absolute(self):
    from config import ODDS_LOG_PATH
    self.assertIsInstance(ODDS_LOG_PATH, str)
    self.assertTrue(os.path.isabs(ODDS_LOG_PATH))

  def test_session_state_path_is_absolute(self):
    from config import SESSION_STATE_PATH
    self.assertIsInstance(SESSION_STATE_PATH, str)
    self.assertTrue(os.path.isabs(SESSION_STATE_PATH))
    self.assertIn(".pinnacle_session_state.json", SESSION_STATE_PATH)

  def test_session_state_path_in_data_dir(self):
    from config import SESSION_STATE_PATH
    self.assertIn("data", SESSION_STATE_PATH)


class TestDotenvNoOverride(unittest.TestCase):
  """Verify python-dotenv does not overwrite existing env vars."""

  def test_existing_env_var_not_overwritten(self):
    """load_dotenv(override=False) preserves existing env vars."""
    from dotenv import load_dotenv
    os.environ["_TEST_DOTENV_VAR"] = "original"
    # Even if .env had _TEST_DOTENV_VAR=different, load_dotenv should not overwrite
    load_dotenv(override=False)
    self.assertEqual(os.environ.get("_TEST_DOTENV_VAR"), "original")
    del os.environ["_TEST_DOTENV_VAR"]


if __name__ == "__main__":
  unittest.main()
