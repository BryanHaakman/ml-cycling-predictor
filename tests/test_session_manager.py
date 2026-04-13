"""
Unit tests for data/session_manager.py — Playwright session acquisition and adaptive TTL.

Tests cover:
- _load_session_state() / _save_session_state() persistence
- _is_session_fresh() TTL logic
- acquire_session_token() Playwright flow (mocked)
- acquire_session_token_with_fallback() CAPTCHA detection
- get_session_token() full integration (env override, cache, Playwright)
"""

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.session_manager as sm_module
from data.session_manager import (
  _load_session_state,
  _save_session_state,
  _is_session_fresh,
  get_session_token,
  invalidate_session,
  acquire_session_token_with_fallback,
  CaptchaOrMfaDetected,
  _TTL_INFINITY_SENTINEL,
)


class TestLoadSessionState(unittest.TestCase):
  """Tests for _load_session_state() disk persistence."""

  def test_returns_defaults_when_file_missing(self):
    """No state file -> returns {token: None, last_acquired: 0.0, learned_ttl_seconds: sentinel}."""
    with tempfile.TemporaryDirectory() as tmpdir:
      fake_path = os.path.join(tmpdir, "nonexistent.json")
      with patch("data.session_manager.SESSION_STATE_PATH", fake_path):
        state = _load_session_state()
    self.assertIsNone(state["token"])
    self.assertEqual(state["last_acquired"], 0.0)
    self.assertEqual(state["learned_ttl_seconds"], _TTL_INFINITY_SENTINEL)

  def test_loads_valid_json_state(self):
    """Valid JSON file -> returns parsed state dict."""
    expected = {"token": "abc123", "last_acquired": 1000.0, "learned_ttl_seconds": 3600}
    with tempfile.NamedTemporaryFile(
      mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
      json.dump(expected, f)
      tmp_path = f.name

    try:
      with patch("data.session_manager.SESSION_STATE_PATH", tmp_path):
        state = _load_session_state()
      self.assertEqual(state["token"], "abc123")
      self.assertEqual(state["last_acquired"], 1000.0)
      self.assertEqual(state["learned_ttl_seconds"], 3600)
    finally:
      os.unlink(tmp_path)

  def test_returns_defaults_on_corrupt_json(self):
    """Corrupt JSON -> returns defaults, does not crash."""
    with tempfile.NamedTemporaryFile(
      mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
      f.write("{this is not valid json}")
      tmp_path = f.name

    try:
      with patch("data.session_manager.SESSION_STATE_PATH", tmp_path):
        state = _load_session_state()
      self.assertIsNone(state["token"])
      self.assertEqual(state["last_acquired"], 0.0)
      self.assertEqual(state["learned_ttl_seconds"], _TTL_INFINITY_SENTINEL)
    finally:
      os.unlink(tmp_path)


class TestSaveSessionState(unittest.TestCase):
  """Tests for _save_session_state() disk persistence."""

  def test_writes_valid_json(self):
    """State dict -> written as valid JSON to disk."""
    state = {"token": "abc", "last_acquired": 1000.0, "learned_ttl_seconds": 3600}
    with tempfile.NamedTemporaryFile(
      mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
      tmp_path = f.name

    try:
      with patch("data.session_manager.SESSION_STATE_PATH", tmp_path):
        _save_session_state(state)
      with open(tmp_path, "r", encoding="utf-8") as fh:
        loaded = json.load(fh)
      self.assertEqual(loaded["token"], "abc")
      self.assertEqual(loaded["last_acquired"], 1000.0)
      self.assertEqual(loaded["learned_ttl_seconds"], 3600)
    finally:
      os.unlink(tmp_path)

  def test_infinity_sentinel_serialized_correctly(self):
    """TTL infinity sentinel (9999999) is written as integer, not float('inf')."""
    state = {"token": "tok", "last_acquired": 500.0, "learned_ttl_seconds": _TTL_INFINITY_SENTINEL}
    with tempfile.NamedTemporaryFile(
      mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
      tmp_path = f.name

    try:
      with patch("data.session_manager.SESSION_STATE_PATH", tmp_path):
        _save_session_state(state)
      with open(tmp_path, "r", encoding="utf-8") as fh:
        raw = fh.read()
      # Verify no float("inf") was written (which would cause ValueError in json)
      loaded = json.loads(raw)
      self.assertEqual(loaded["learned_ttl_seconds"], _TTL_INFINITY_SENTINEL)
      self.assertIsInstance(loaded["learned_ttl_seconds"], int)
    finally:
      os.unlink(tmp_path)


class TestIsSessionFresh(unittest.TestCase):
  """Tests for _is_session_fresh() TTL logic."""

  def test_fresh_when_within_ttl(self):
    """Token acquired 10s ago with TTL 3600s -> fresh."""
    state = {
      "token": "some_token",
      "last_acquired": time.time() - 10,
      "learned_ttl_seconds": 3600,
    }
    self.assertTrue(_is_session_fresh(state))

  def test_stale_when_beyond_ttl(self):
    """Token acquired 7200s ago with TTL 3600s -> stale."""
    state = {
      "token": "some_token",
      "last_acquired": time.time() - 7200,
      "learned_ttl_seconds": 3600,
    }
    self.assertFalse(_is_session_fresh(state))

  def test_fresh_when_ttl_is_infinity_and_token_exists(self):
    """TTL is infinity sentinel + token exists -> fresh (first-time use)."""
    state = {
      "token": "some_token",
      "last_acquired": time.time() - 10,
      "learned_ttl_seconds": _TTL_INFINITY_SENTINEL,
    }
    self.assertTrue(_is_session_fresh(state))

  def test_stale_when_no_token(self):
    """No token regardless of TTL -> stale."""
    state = {
      "token": None,
      "last_acquired": time.time() - 10,
      "learned_ttl_seconds": 3600,
    }
    self.assertFalse(_is_session_fresh(state))

  def test_stale_when_no_token_with_infinity_ttl(self):
    """No token with infinity TTL -> stale."""
    state = {
      "token": None,
      "last_acquired": time.time() - 10,
      "learned_ttl_seconds": _TTL_INFINITY_SENTINEL,
    }
    self.assertFalse(_is_session_fresh(state))


class TestAdaptiveTtl(unittest.TestCase):
  """Tests for adaptive TTL update on 401/403 via invalidate_session()."""

  def test_ttl_updated_to_session_age_on_failure(self):
    """401 after 1800s -> learned_ttl_seconds becomes 1800."""
    now = time.time()
    initial_state = {
      "token": "old_token",
      "last_acquired": now - 1800,
      "learned_ttl_seconds": _TTL_INFINITY_SENTINEL,
    }
    saved_states = []

    def fake_load():
      return dict(initial_state)

    def fake_save(state):
      saved_states.append(dict(state))

    with tempfile.TemporaryDirectory() as tmpdir:
      fake_path = os.path.join(tmpdir, "state.json")
      with patch("data.session_manager.SESSION_STATE_PATH", fake_path):
        with patch("data.session_manager._load_session_state", side_effect=fake_load):
          with patch("data.session_manager._save_session_state", side_effect=fake_save):
            invalidate_session()

    self.assertTrue(len(saved_states) > 0)
    saved = saved_states[-1]
    self.assertIsNone(saved["token"])
    # TTL should be approximately 1800 (the age at failure)
    self.assertAlmostEqual(saved["learned_ttl_seconds"], 1800, delta=5)

  def test_ttl_only_shrinks_never_grows(self):
    """New failure at 1200s when TTL was 1800s -> TTL becomes 1200."""
    now = time.time()
    initial_state = {
      "token": "old_token",
      "last_acquired": now - 1200,
      "learned_ttl_seconds": 1800,  # Already learned 1800s TTL
    }
    saved_states = []

    def fake_load():
      return dict(initial_state)

    def fake_save(state):
      saved_states.append(dict(state))

    with tempfile.TemporaryDirectory() as tmpdir:
      fake_path = os.path.join(tmpdir, "state.json")
      with patch("data.session_manager.SESSION_STATE_PATH", fake_path):
        with patch("data.session_manager._load_session_state", side_effect=fake_load):
          with patch("data.session_manager._save_session_state", side_effect=fake_save):
            invalidate_session()

    saved = saved_states[-1]
    self.assertIsNone(saved["token"])
    # TTL should shrink from 1800 to ~1200
    self.assertAlmostEqual(saved["learned_ttl_seconds"], 1200, delta=5)

  def test_ttl_does_not_grow(self):
    """If new failure at 2400s but TTL was 1800s -> TTL stays 1800 (only shrinks)."""
    now = time.time()
    initial_state = {
      "token": "old_token",
      "last_acquired": now - 2400,
      "learned_ttl_seconds": 1800,  # TTL is 1800, but session lived 2400s
    }
    saved_states = []

    def fake_load():
      return dict(initial_state)

    def fake_save(state):
      saved_states.append(dict(state))

    with tempfile.TemporaryDirectory() as tmpdir:
      fake_path = os.path.join(tmpdir, "state.json")
      with patch("data.session_manager.SESSION_STATE_PATH", fake_path):
        with patch("data.session_manager._load_session_state", side_effect=fake_load):
          with patch("data.session_manager._save_session_state", side_effect=fake_save):
            invalidate_session()

    saved = saved_states[-1]
    # TTL should NOT grow — stays at 1800
    self.assertEqual(saved["learned_ttl_seconds"], 1800)


class TestGetSessionToken(unittest.TestCase):
  """Tests for the full get_session_token() integration."""

  def test_returns_cached_token_when_fresh(self):
    """Cached token within TTL -> returns it, no Playwright."""
    fresh_state = {
      "token": "cached_token_xyz",
      "last_acquired": time.time() - 10,
      "learned_ttl_seconds": 3600,
    }
    with tempfile.TemporaryDirectory() as tmpdir:
      fake_path = os.path.join(tmpdir, "state.json")
      with patch("data.session_manager.SESSION_STATE_PATH", fake_path):
        with patch("data.session_manager._load_session_state", return_value=fresh_state):
          with patch(
            "data.session_manager.acquire_session_token_with_fallback"
          ) as mock_playwright:
            token = get_session_token()

    self.assertEqual(token, "cached_token_xyz")
    mock_playwright.assert_not_called()

  def test_calls_playwright_when_cache_stale(self):
    """Cache beyond TTL -> calls acquire_session_token_with_fallback()."""
    stale_state = {
      "token": "old_token",
      "last_acquired": time.time() - 7200,
      "learned_ttl_seconds": 3600,
    }
    with tempfile.NamedTemporaryFile(
      mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
      tmp_path = f.name

    try:
      with patch("data.session_manager.SESSION_STATE_PATH", tmp_path):
        with patch("data.session_manager._load_session_state", return_value=stale_state):
          with patch(
            "data.session_manager.acquire_session_token_with_fallback",
            return_value="new_playwright_token",
          ) as mock_playwright:
            token = get_session_token()

      mock_playwright.assert_called_once()
      self.assertEqual(token, "new_playwright_token")
    finally:
      os.unlink(tmp_path)

  def test_updates_state_after_playwright_acquisition(self):
    """After Playwright returns token -> state file updated with new timestamp."""
    stale_state = {
      "token": None,
      "last_acquired": 0.0,
      "learned_ttl_seconds": _TTL_INFINITY_SENTINEL,
    }
    saved_states = []

    def fake_save(state):
      saved_states.append(dict(state))

    with tempfile.TemporaryDirectory() as tmpdir:
      fake_path = os.path.join(tmpdir, "state.json")
      with patch("data.session_manager.SESSION_STATE_PATH", fake_path):
        with patch("data.session_manager._load_session_state", return_value=stale_state):
          with patch("data.session_manager._save_session_state", side_effect=fake_save):
            with patch(
              "data.session_manager.acquire_session_token_with_fallback",
              return_value="playwright_token",
            ):
              token = get_session_token()

    self.assertEqual(token, "playwright_token")
    self.assertTrue(len(saved_states) > 0)
    saved = saved_states[-1]
    self.assertEqual(saved["token"], "playwright_token")
    # last_acquired should be recent (within last 5 seconds)
    self.assertAlmostEqual(saved["last_acquired"], time.time(), delta=5)

  def test_returns_none_when_playwright_fails(self):
    """If acquire_session_token_with_fallback() raises -> returns None, does not raise."""
    stale_state = {
      "token": None,
      "last_acquired": 0.0,
      "learned_ttl_seconds": _TTL_INFINITY_SENTINEL,
    }
    with tempfile.TemporaryDirectory() as tmpdir:
      fake_path = os.path.join(tmpdir, "state.json")
      with patch("data.session_manager.SESSION_STATE_PATH", fake_path):
        with patch("data.session_manager._load_session_state", return_value=stale_state):
          with patch(
            "data.session_manager.acquire_session_token_with_fallback",
            side_effect=Exception("browser failed"),
          ):
            token = get_session_token()

    self.assertIsNone(token)


class TestAcquireSessionTokenWithFallback(unittest.TestCase):
  """Tests for acquire_session_token_with_fallback() CAPTCHA-headed fallback."""

  def test_returns_token_on_headless_success(self):
    """Headless succeeds -> returns token without headed fallback."""
    with patch(
      "data.session_manager.acquire_session_token",
      return_value="headless_token",
    ) as mock_acquire:
      token = acquire_session_token_with_fallback()

    self.assertEqual(token, "headless_token")
    mock_acquire.assert_called_once_with(headless=True)

  def test_retries_headed_on_captcha_detected(self):
    """CaptchaOrMfaDetected on headless -> retries with headless=False."""

    def side_effect(headless=True):
      if headless:
        raise CaptchaOrMfaDetected("CAPTCHA detected")
      return "headed_token"

    with patch("data.session_manager.acquire_session_token", side_effect=side_effect):
      token = acquire_session_token_with_fallback()

    self.assertEqual(token, "headed_token")


if __name__ == "__main__":
  unittest.main()
