"""
Unit tests for data/pinnacle_scraper.py — Playwright-based Pinnacle scraper.

Tests cover:
- _american_to_decimal() conversion formula
- parse_american_odds() string parsing
- MatchupSnapshot dataclass fields and defaults
- save_snapshot() SQLite persistence and table creation
- _create_snapshot_table() idempotency
- _discover_races() with mocked Playwright Page
- _scrape_race_matchups() with mocked Page returning decimal odds
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.pinnacle_scraper import (
  MatchupSnapshot,
  PinnacleScrapeError,
  _american_to_decimal,
  _create_snapshot_table,
  parse_american_odds,
  save_snapshot,
  scrape_cycling_markets,
  get_upcoming_start_times,
  _discover_races,
  _scrape_race_matchups,
)
from data.scraper import get_db


class TestAmericanToDecimal(unittest.TestCase):
  """Tests for _american_to_decimal()."""

  def test_positive_odds(self):
    self.assertAlmostEqual(_american_to_decimal(160), 2.6, places=4)

  def test_negative_odds(self):
    expected = round(100 / 231 + 1, 4)
    self.assertAlmostEqual(_american_to_decimal(-231), expected, places=4)

  def test_zero_raises(self):
    with self.assertRaises(ValueError):
      _american_to_decimal(0)

  def test_even_money(self):
    self.assertAlmostEqual(_american_to_decimal(-100), 2.0, places=4)
    self.assertAlmostEqual(_american_to_decimal(100), 2.0, places=4)


class TestParseAmericanOdds(unittest.TestCase):
  """Tests for parse_american_odds() string parsing."""

  def test_positive_string(self):
    self.assertAlmostEqual(parse_american_odds("+160"), 2.6, places=4)

  def test_negative_string(self):
    expected = round(100 / 231 + 1, 4)
    self.assertAlmostEqual(parse_american_odds("-231"), expected, places=4)

  def test_ev_string(self):
    self.assertAlmostEqual(parse_american_odds("EV"), 2.0, places=4)

  def test_empty_string(self):
    self.assertIsNone(parse_american_odds(""))

  def test_whitespace(self):
    self.assertAlmostEqual(parse_american_odds("  +160  "), 2.6, places=4)

  def test_unparseable(self):
    self.assertIsNone(parse_american_odds("N/A"))


class TestMatchupSnapshot(unittest.TestCase):
  """Tests for MatchupSnapshot dataclass."""

  def test_required_fields(self):
    snap = MatchupSnapshot(
      rider_a_name="Alex Aranburu",
      rider_b_name="Christian Scaroni",
      odds_a=1.4329,
      odds_b=2.6,
      race_name="Amstel Gold",
      race_slug="amstel-gold-race",
      start_time="05:10",
      start_date="2026-04-20",
    )
    self.assertEqual(snap.rider_a_name, "Alex Aranburu")
    self.assertEqual(snap.rider_b_name, "Christian Scaroni")
    self.assertAlmostEqual(snap.odds_a, 1.4329)
    self.assertAlmostEqual(snap.odds_b, 2.6)
    self.assertEqual(snap.race_name, "Amstel Gold")
    self.assertEqual(snap.race_slug, "amstel-gold-race")
    self.assertEqual(snap.start_time, "05:10")
    self.assertEqual(snap.start_date, "2026-04-20")

  def test_defaults(self):
    snap = MatchupSnapshot(
      rider_a_name="A", rider_b_name="B",
      odds_a=1.5, odds_b=2.5,
      race_name="Test", race_slug="test",
      start_time=None, start_date=None,
    )
    self.assertEqual(snap.snapshot_type, "manual")
    self.assertEqual(snap.source_url, "")


class TestSaveSnapshot(unittest.TestCase):
  """Tests for save_snapshot() SQLite persistence."""

  def test_persists_to_db(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      snap = MatchupSnapshot(
        rider_a_name="Alex Aranburu",
        rider_b_name="Christian Scaroni",
        odds_a=1.4329,
        odds_b=2.6,
        race_name="Amstel Gold",
        race_slug="amstel-gold-race",
        start_time="05:10",
        start_date="2026-04-20",
      )
      save_snapshot([snap], db_path=tmp_db)
      conn = get_db(tmp_db)
      rows = conn.execute("SELECT * FROM market_snapshots").fetchall()
      self.assertEqual(len(rows), 1)
      self.assertEqual(rows[0]["rider_a_name"], "Alex Aranburu")
      self.assertAlmostEqual(rows[0]["odds_a"], 1.4329, places=4)
      conn.close()
    finally:
      os.unlink(tmp_db)

  def test_creates_table_with_indexes(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      save_snapshot([], db_path=tmp_db)
      conn = get_db(tmp_db)
      indexes = [
        row[1] for row in conn.execute(
          "SELECT * FROM sqlite_master WHERE type='index'"
        ).fetchall()
      ]
      self.assertIn("idx_snapshots_date", indexes)
      self.assertIn("idx_snapshots_race", indexes)
      self.assertIn("idx_snapshots_riders", indexes)
      conn.close()
    finally:
      os.unlink(tmp_db)

  def test_idempotent_table_creation(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      conn = get_db(tmp_db)
      _create_snapshot_table(conn)
      _create_snapshot_table(conn)  # second call should not error
      conn.close()
    finally:
      os.unlink(tmp_db)

  def test_implied_probs_computed(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      snap = MatchupSnapshot(
        rider_a_name="A", rider_b_name="B",
        odds_a=2.0, odds_b=2.0,
        race_name="Test", race_slug="test",
        start_time=None, start_date=None,
      )
      save_snapshot([snap], db_path=tmp_db)
      conn = get_db(tmp_db)
      row = conn.execute("SELECT * FROM market_snapshots").fetchone()
      self.assertAlmostEqual(row["implied_prob_a"], 0.5, places=4)
      self.assertAlmostEqual(row["implied_prob_b"], 0.5, places=4)
      conn.close()
    finally:
      os.unlink(tmp_db)


class TestDiscoverRaces(unittest.TestCase):
  """Tests for _discover_races() with mocked Playwright Page."""

  def _make_mock_page(self):
    """Build a mock Page that returns race links."""
    page = MagicMock()
    page.goto = MagicMock()
    page.wait_for_selector = MagicMock()

    link1 = MagicMock()
    link1.get_attribute.return_value = "/en/cycling/amstel-gold-race/matchups/"
    link1.inner_text.return_value = "Amstel Gold 19"

    link2 = MagicMock()
    link2.get_attribute.return_value = "/en/cycling/tour-of-alps-stage-1/matchups/"
    link2.inner_text.return_value = "Tour Of the Alps - Stage 1 14"

    page.query_selector_all = MagicMock(return_value=[link1, link2])
    return page

  @patch("data.pinnacle_scraper.time")
  @patch("data.pinnacle_scraper._navigate_with_retry", return_value=True)
  def test_returns_race_tuples(self, mock_nav, mock_time):
    page = self._make_mock_page()
    result = _discover_races(page)
    self.assertEqual(len(result), 2)
    self.assertEqual(result[0][0], "amstel-gold-race")
    self.assertEqual(result[1][0], "tour-of-alps-stage-1")

  @patch("data.pinnacle_scraper.time")
  @patch("data.pinnacle_scraper._navigate_with_retry", return_value=False)
  def test_returns_empty_on_nav_failure(self, mock_nav, mock_time):
    page = MagicMock()
    result = _discover_races(page)
    self.assertEqual(result, [])


class TestScrapeRaceMatchups(unittest.TestCase):
  """Tests for _scrape_race_matchups() with mocked Page."""

  def _make_mock_page(self, rider_a="Alex Aranburu", rider_b="Christian Scaroni",
                      odds_a="-231", odds_b="+160", start_time="05:10",
                      date_bar="TOMORROW"):
    """Build a mock Page that returns matchup elements."""
    page = MagicMock()

    # Rider name elements
    name_a_el = MagicMock()
    name_a_el.inner_text.return_value = rider_a
    name_b_el = MagicMock()
    name_b_el.inner_text.return_value = rider_b

    # Time element
    time_el = MagicMock()
    time_el.inner_text.return_value = start_time

    # Matchup metadata element
    metadata_el = MagicMock()
    metadata_el.query_selector_all.return_value = [name_a_el, name_b_el]
    metadata_el.query_selector.return_value = time_el

    # Date bar element
    date_bar_el = MagicMock()
    date_bar_el.inner_text.return_value = date_bar

    # Odds button elements
    odds_a_btn = MagicMock()
    odds_a_btn.inner_text.return_value = odds_a
    odds_b_btn = MagicMock()
    odds_b_btn.inner_text.return_value = odds_b

    moneyline_el = MagicMock()
    moneyline_el.query_selector_all.return_value = [odds_a_btn, odds_b_btn]
    moneyline_el.inner_text.return_value = odds_a + "\n" + odds_b

    def query_selector_all_side_effect(selector):
      if "matchupMetadata" in selector:
        return [metadata_el]
      if "moneyline" in selector:
        return [moneyline_el]
      if "DateBar" in selector:
        return [date_bar_el]
      return []

    page.query_selector_all = MagicMock(side_effect=query_selector_all_side_effect)
    page.wait_for_selector = MagicMock()
    return page

  @patch("data.pinnacle_scraper.time")
  @patch("data.pinnacle_scraper._navigate_with_retry", return_value=True)
  def test_returns_matchup_snapshots(self, mock_nav, mock_time):
    page = self._make_mock_page()
    result = _scrape_race_matchups(page, "amstel-gold-race", "Amstel Gold")
    self.assertEqual(len(result), 1)
    self.assertIsInstance(result[0], MatchupSnapshot)
    self.assertEqual(result[0].rider_a_name, "Alex Aranburu")
    self.assertEqual(result[0].rider_b_name, "Christian Scaroni")

  @patch("data.pinnacle_scraper.time")
  @patch("data.pinnacle_scraper._navigate_with_retry", return_value=True)
  def test_odds_are_decimal(self, mock_nav, mock_time):
    page = self._make_mock_page(odds_a="-231", odds_b="+160")
    result = _scrape_race_matchups(page, "test-race", "Test")
    self.assertAlmostEqual(result[0].odds_a, round(100 / 231 + 1, 4), places=4)
    self.assertAlmostEqual(result[0].odds_b, 2.6, places=2)

  @patch("data.pinnacle_scraper.time")
  @patch("data.pinnacle_scraper._navigate_with_retry", return_value=False)
  def test_returns_empty_on_nav_failure(self, mock_nav, mock_time):
    page = MagicMock()
    result = _scrape_race_matchups(page, "test-race", "Test")
    self.assertEqual(result, [])


if __name__ == "__main__":
  unittest.main()
