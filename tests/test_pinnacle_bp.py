"""
Unit tests for webapp/pinnacle_bp.py -- Pinnacle blueprint endpoints.

Tests cover:
- /api/pinnacle/load endpoint with mocked scraper
- /api/pinnacle/snapshot endpoint with mocked scraper + save_snapshot
- /api/pinnacle/snapshot/closing endpoint
- Error handling for PinnacleScrapeError
- _require_localhost enforcement
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.pinnacle_scraper import MatchupSnapshot, PinnacleScrapeError
from intelligence.stage_context import StageContext


def _make_test_app():
  """Create a Flask test app with the pinnacle blueprint registered."""
  from webapp.app import app
  app.config["TESTING"] = True
  return app


def _sample_snapshots():
  """Return a list of sample MatchupSnapshot objects for testing."""
  return [
    MatchupSnapshot(
      rider_a_name="Tadej Pogacar",
      rider_b_name="Jonas Vingegaard",
      odds_a=1.75,
      odds_b=2.10,
      race_name="Tour de France",
      race_slug="tour-de-france",
      start_time="14:00",
      start_date="2026-07-01",
      snapshot_type="manual",
      source_url="https://www.pinnacle.ca/en/cycling/tour-de-france/matchups/",
    ),
  ]


@dataclass
class _MockResolveResult:
  url: str
  best_candidate_name: str
  best_candidate_url: str


class TestPinnacleLoad(unittest.TestCase):
  """Tests for POST /api/pinnacle/load."""

  @patch("webapp.pinnacle_bp.fetch_stage_context")
  @patch("webapp.pinnacle_bp.NameResolver")
  @patch("webapp.pinnacle_bp.scrape_cycling_markets")
  def test_load_returns_races(self, mock_scrape, mock_resolver_cls, mock_stage_ctx):
    """Successful scrape returns grouped races with pairs."""
    mock_scrape.return_value = _sample_snapshots()

    resolver_instance = MagicMock()
    resolver_instance.resolve.return_value = _MockResolveResult(
      url=None, best_candidate_name="", best_candidate_url="",
    )
    mock_resolver_cls.return_value = resolver_instance

    ctx = StageContext(is_resolved=False)
    mock_stage_ctx.return_value = ctx

    app = _make_test_app()
    with app.test_client() as client:
      resp = client.post("/api/pinnacle/load",
                         environ_base={"REMOTE_ADDR": "127.0.0.1"})
      self.assertEqual(resp.status_code, 200)
      data = resp.get_json()
      self.assertIn("races", data)
      self.assertEqual(len(data["races"]), 1)
      self.assertEqual(data["races"][0]["race_name"], "Tour de France")
      self.assertEqual(len(data["races"][0]["pairs"]), 1)
      pair = data["races"][0]["pairs"][0]
      self.assertEqual(pair["pinnacle_name_a"], "Tadej Pogacar")
      self.assertEqual(pair["odds_a"], 1.75)
      self.assertIn("model_prob", pair)
      self.assertIn("should_bet", pair)

  @patch("webapp.pinnacle_bp.scrape_cycling_markets")
  def test_load_scrape_error(self, mock_scrape):
    """PinnacleScrapeError returns 503."""
    mock_scrape.side_effect = PinnacleScrapeError("blocked")

    app = _make_test_app()
    with app.test_client() as client:
      resp = client.post("/api/pinnacle/load",
                         environ_base={"REMOTE_ADDR": "127.0.0.1"})
      self.assertEqual(resp.status_code, 503)
      data = resp.get_json()
      self.assertEqual(data["type"], "scrape_error")

  @patch("webapp.pinnacle_bp.scrape_cycling_markets")
  def test_load_generic_error(self, mock_scrape):
    """Generic exception returns 500."""
    mock_scrape.side_effect = RuntimeError("unexpected")

    app = _make_test_app()
    with app.test_client() as client:
      resp = client.post("/api/pinnacle/load",
                         environ_base={"REMOTE_ADDR": "127.0.0.1"})
      self.assertEqual(resp.status_code, 500)

  def test_load_requires_localhost(self):
    """Non-localhost requests get 403."""
    app = _make_test_app()
    with app.test_client() as client:
      resp = client.post("/api/pinnacle/load",
                         environ_base={"REMOTE_ADDR": "8.8.8.8"})
      self.assertEqual(resp.status_code, 403)


class TestPinnacleSnapshot(unittest.TestCase):
  """Tests for POST /api/pinnacle/snapshot."""

  @patch("webapp.pinnacle_bp._enrich_snapshots_with_predictions")
  @patch("webapp.pinnacle_bp.save_snapshot")
  @patch("webapp.pinnacle_bp.scrape_cycling_markets")
  def test_snapshot_saves_and_returns_count(self, mock_scrape, mock_save, mock_enrich):
    """Snapshot endpoint scrapes, saves, and returns count."""
    snaps = _sample_snapshots()
    mock_scrape.return_value = snaps

    app = _make_test_app()
    with app.test_client() as client:
      resp = client.post("/api/pinnacle/snapshot",
                         environ_base={"REMOTE_ADDR": "127.0.0.1"})
      self.assertEqual(resp.status_code, 200)
      data = resp.get_json()
      self.assertEqual(data["saved"], 1)
      mock_save.assert_called_once_with(snaps)
      mock_enrich.assert_called_once()

  @patch("webapp.pinnacle_bp.scrape_cycling_markets")
  def test_snapshot_scrape_error(self, mock_scrape):
    """PinnacleScrapeError returns 503."""
    mock_scrape.side_effect = PinnacleScrapeError("blocked")

    app = _make_test_app()
    with app.test_client() as client:
      resp = client.post("/api/pinnacle/snapshot",
                         environ_base={"REMOTE_ADDR": "127.0.0.1"})
      self.assertEqual(resp.status_code, 503)

  def test_snapshot_requires_localhost(self):
    """Non-localhost requests get 403."""
    app = _make_test_app()
    with app.test_client() as client:
      resp = client.post("/api/pinnacle/snapshot",
                         environ_base={"REMOTE_ADDR": "8.8.8.8"})
      self.assertEqual(resp.status_code, 403)


class TestPinnacleSnapshotClosing(unittest.TestCase):
  """Tests for POST /api/pinnacle/snapshot/closing."""

  @patch("webapp.pinnacle_bp._enrich_snapshots_with_predictions")
  @patch("webapp.pinnacle_bp.save_snapshot")
  @patch("webapp.pinnacle_bp.scrape_cycling_markets")
  def test_closing_snapshot_passes_type(self, mock_scrape, mock_save, mock_enrich):
    """Closing snapshot endpoint passes snapshot_type='closing'."""
    mock_scrape.return_value = _sample_snapshots()

    app = _make_test_app()
    with app.test_client() as client:
      resp = client.post("/api/pinnacle/snapshot/closing",
                         environ_base={"REMOTE_ADDR": "127.0.0.1"})
      self.assertEqual(resp.status_code, 200)
      mock_scrape.assert_called_once_with(snapshot_type="closing")

  def test_closing_requires_localhost(self):
    """Non-localhost requests get 403."""
    app = _make_test_app()
    with app.test_client() as client:
      resp = client.post("/api/pinnacle/snapshot/closing",
                         environ_base={"REMOTE_ADDR": "8.8.8.8"})
      self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
  unittest.main()
