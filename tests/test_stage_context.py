"""Tests for intelligence/stage_context.py — StageContext dataclass and fetch_stage_context."""

import os
import sys
import time
import dataclasses
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from intelligence.stage_context import (
  StageContext,
  fetch_stage_context,
  _parse_race_name,
  _resolve_race_url,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_race_row(url: str, name: str) -> MagicMock:
  """Return a sqlite3.Row-like mock with url and name keys."""
  row = MagicMock()
  row.__getitem__ = lambda self, key: {"url": url, "name": name}[key]
  return row


def _make_mock_db(rows):
  """Return a context-managed mock connection that returns given rows."""
  mock_conn = MagicMock()
  mock_cursor = MagicMock()
  mock_cursor.fetchall.return_value = rows
  mock_conn.execute.return_value = mock_cursor
  return mock_conn


# ---------------------------------------------------------------------------
# TestStageContextDataclass
# ---------------------------------------------------------------------------

class TestStageContextDataclass:
  """Tests for StageContext dataclass structure and defaults (D-07)."""

  def test_default_values(self):
    """StageContext() has expected defaults."""
    ctx = StageContext()
    assert ctx.is_resolved is False
    assert ctx.distance == 0.0
    assert ctx.profile_icon == "p1"
    assert ctx.stage_type == "RR"
    assert ctx.num_climbs == 0
    assert ctx.is_one_day_race is False
    assert ctx.race_date == ""
    assert ctx.race_base_url == ""
    assert ctx.uci_tour == ""
    assert ctx.vertical_meters is None
    assert ctx.profile_score is None
    assert ctx.avg_temperature is None

  def test_fields_match_race_params_keys(self):
    """StageContext field names match build_feature_vector_manual race_params keys."""
    # Keys expected by build_feature_vector_manual (from features/pipeline.py line 225)
    required_race_params_keys = {
      "distance",
      "vertical_meters",
      "profile_icon",
      "profile_score",
      "is_one_day_race",
      "stage_type",
      "race_date",
      "race_base_url",
      "num_climbs",
      "avg_temperature",
    }
    # Extra StageContext-specific fields
    extra_fields = {"uci_tour", "is_resolved"}
    expected_fields = required_race_params_keys | extra_fields

    actual_fields = {f.name for f in dataclasses.fields(StageContext)}
    assert actual_fields == expected_fields, (
      f"StageContext fields mismatch.\n"
      f"  Missing: {expected_fields - actual_fields}\n"
      f"  Extra: {actual_fields - expected_fields}"
    )


# ---------------------------------------------------------------------------
# TestParseRaceName
# ---------------------------------------------------------------------------

class TestParseRaceName:
  """Tests for _parse_race_name (D-02)."""

  def test_strips_stage_suffix(self):
    """'Tour de Romandie - Stage 3' -> 'Tour de Romandie'."""
    assert _parse_race_name("Tour de Romandie - Stage 3") == "Tour de Romandie"

  def test_no_separator_returns_full_name(self):
    """'Paris-Roubaix' (no ' - ' separator) returns unchanged."""
    assert _parse_race_name("Paris-Roubaix") == "Paris-Roubaix"

  def test_multiple_separators_splits_on_first(self):
    """Multiple ' - ' separators: only first split is taken."""
    result = _parse_race_name("Giro d'Italia - Stage 5 - Mountain Finish")
    assert result == "Giro d'Italia"

  def test_logs_parsed_assumption(self, caplog):
    """_parse_race_name logs the parsing assumption."""
    import logging
    with caplog.at_level(logging.INFO, logger="intelligence.stage_context"):
      _parse_race_name("Tour de France - Stage 10")
    assert len(caplog.records) >= 1


# ---------------------------------------------------------------------------
# TestResolveRaceUrl
# ---------------------------------------------------------------------------

class TestResolveRaceUrl:
  """Tests for _resolve_race_url fuzzy matching against cache.db (D-01)."""

  def test_fuzzy_match_returns_url(self):
    """Exact-ish match against a DB row returns the URL."""
    row = MagicMock()
    row.__getitem__ = lambda self, k: {"url": "race/tour-de-romandie/2026", "name": "Tour de Romandie"}[k]

    mock_conn = _make_mock_db([row])

    with patch("intelligence.stage_context.get_db", return_value=mock_conn):
      result = _resolve_race_url("Tour de Romandie", 2026)
    assert result == "race/tour-de-romandie/2026"

  def test_below_threshold_returns_none(self):
    """Input that scores below RACE_MATCH_THRESHOLD (75) returns None."""
    row = MagicMock()
    row.__getitem__ = lambda self, k: {"url": "race/tour-de-romandie/2026", "name": "Tour de Romandie"}[k]

    mock_conn = _make_mock_db([row])

    with patch("intelligence.stage_context.get_db", return_value=mock_conn):
      result = _resolve_race_url("Completely Different Race XYZ", 2026)
    assert result is None

  def test_no_races_in_db_returns_none(self):
    """Empty DB returns None with a warning logged."""
    mock_conn = _make_mock_db([])

    with patch("intelligence.stage_context.get_db", return_value=mock_conn):
      result = _resolve_race_url("Tour de Romandie", 2026)
    assert result is None

  def test_logs_match_score(self, caplog):
    """_resolve_race_url logs the fuzzy match score on success."""
    import logging
    row = MagicMock()
    row.__getitem__ = lambda self, k: {"url": "race/tour-de-romandie/2026", "name": "Tour de Romandie"}[k]

    mock_conn = _make_mock_db([row])

    with patch("intelligence.stage_context.get_db", return_value=mock_conn):
      with caplog.at_level(logging.INFO, logger="intelligence.stage_context"):
        _resolve_race_url("Tour de Romandie", 2026)
    # Should log the score somewhere
    log_text = " ".join(r.message for r in caplog.records)
    assert "score" in log_text.lower() or any("score" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_stage():
  """Mock procyclingstats.Stage with typical stage data."""
  stage = MagicMock()
  stage.distance.return_value = 150.0
  stage.vertical_meters.return_value = 2500
  stage.profile_icon.return_value = "p3"
  stage.profile_score.return_value = 45
  stage.stage_type.return_value = "RR"
  stage.date.return_value = "2026-04-12"
  stage.avg_temperature.return_value = 18.0
  stage.climbs.return_value = [1, 2, 3]
  return stage


@pytest.fixture
def mock_race_multi_stage():
  """Mock procyclingstats.Race for a multi-stage race."""
  race = MagicMock()
  race.is_one_day_race.return_value = False
  race.uci_tour.return_value = "2.UWT"
  race.stages.return_value = [
    {"stage_url": "race/tour-de-romandie/2026/stage-3", "date": "04-12"},
  ]
  return race


@pytest.fixture
def mock_race_one_day():
  """Mock procyclingstats.Race for a one-day race."""
  race = MagicMock()
  race.is_one_day_race.return_value = True
  race.uci_tour.return_value = "1.UWT"
  race.stages.return_value = []
  return race


@pytest.fixture
def mock_db_romandie():
  """Mock DB returning Tour de Romandie race row."""
  row = MagicMock()
  row.__getitem__ = lambda self, k: {
    "url": "race/tour-de-romandie/2026",
    "name": "Tour de Romandie",
  }[k]
  mock_conn = _make_mock_db([row])
  return mock_conn


@pytest.fixture
def mock_db_roubaix():
  """Mock DB returning Paris-Roubaix race row."""
  row = MagicMock()
  row.__getitem__ = lambda self, k: {
    "url": "race/paris-roubaix/2026",
    "name": "Paris-Roubaix",
  }[k]
  mock_conn = _make_mock_db([row])
  return mock_conn


# ---------------------------------------------------------------------------
# TestFetchStageContext (resolved path)
# ---------------------------------------------------------------------------

class TestFetchStageContext:
  """Tests for fetch_stage_context successful resolution (STGE-01)."""

  def test_resolved_stage_race(self, mock_db_romandie, mock_race_multi_stage, mock_stage):
    """Multi-stage race resolves to fully-populated StageContext with is_resolved=True."""
    with patch("intelligence.stage_context.get_db", return_value=mock_db_romandie), \
         patch("intelligence.stage_context._date") as mock_date_cls, \
         patch("procyclingstats.Race", return_value=mock_race_multi_stage), \
         patch("procyclingstats.Stage", return_value=mock_stage):

      mock_date_cls.today.return_value.strftime.return_value = "04-12"
      mock_date_cls.today.return_value.year = 2026

      result = fetch_stage_context("Tour de Romandie - Stage 3")

    assert result.is_resolved is True
    assert result.distance == 150.0
    assert result.vertical_meters == 2500
    assert result.profile_icon == "p3"
    assert result.profile_score == 45
    assert result.stage_type == "RR"
    assert result.race_date == "2026-04-12"
    assert result.num_climbs == 3
    assert result.avg_temperature == 18.0
    assert result.is_one_day_race is False
    assert result.uci_tour == "2.UWT"

  def test_resolved_one_day_race(self, mock_db_roubaix, mock_race_one_day, mock_stage):
    """One-day race resolves with is_one_day_race=True and /result URL suffix."""
    with patch("intelligence.stage_context.get_db", return_value=mock_db_roubaix), \
         patch("intelligence.stage_context._date") as mock_date_cls, \
         patch("procyclingstats.Race", return_value=mock_race_one_day), \
         patch("procyclingstats.Stage", return_value=mock_stage) as mock_stage_cls:

      mock_date_cls.today.return_value.strftime.return_value = "04-12"
      mock_date_cls.today.return_value.year = 2026

      result = fetch_stage_context("Paris-Roubaix")

    # Stage should have been called with /result suffix
    call_args = mock_stage_cls.call_args[0][0]
    assert call_args.endswith("/result"), f"Expected /result suffix, got: {call_args}"
    assert result.is_one_day_race is True

  def test_is_one_day_uses_race_not_stage(self, mock_db_romandie, mock_race_multi_stage, mock_stage):
    """is_one_day_race is sourced from Race.is_one_day_race(), not Stage.is_one_day_race()."""
    # Race says False (multi-stage)
    mock_race_multi_stage.is_one_day_race.return_value = False
    # Stage would say True if asked — but we should never ask Stage
    mock_stage.is_one_day_race = MagicMock(return_value=True)

    with patch("intelligence.stage_context.get_db", return_value=mock_db_romandie), \
         patch("intelligence.stage_context._date") as mock_date_cls, \
         patch("procyclingstats.Race", return_value=mock_race_multi_stage), \
         patch("procyclingstats.Stage", return_value=mock_stage):

      mock_date_cls.today.return_value.strftime.return_value = "04-12"
      mock_date_cls.today.return_value.year = 2026

      result = fetch_stage_context("Tour de Romandie - Stage 3")

    # Should be False (from Race), not True (from Stage)
    assert result.is_one_day_race is False
    # Stage.is_one_day_race should NOT have been called
    mock_stage.is_one_day_race.assert_not_called()


# ---------------------------------------------------------------------------
# TestFallbacks (STGE-02)
# ---------------------------------------------------------------------------

class TestFallbacks:
  """Tests for fetch_stage_context graceful degradation (STGE-02)."""

  def test_unresolved_race_name(self, mock_db_romandie):
    """Input name that fails fuzzy match returns is_resolved=False without raising."""
    with patch("intelligence.stage_context.get_db", return_value=mock_db_romandie), \
         patch("intelligence.stage_context._date") as mock_date_cls:
      mock_date_cls.today.return_value.year = 2026

      result = fetch_stage_context("ZZZZ Nonexistent Race")

    assert result.is_resolved is False

  def test_pcs_race_exception(self, mock_db_romandie):
    """Exception from Race() returns is_resolved=False without raising."""
    with patch("intelligence.stage_context.get_db", return_value=mock_db_romandie), \
         patch("intelligence.stage_context._date") as mock_date_cls, \
         patch("procyclingstats.Race", side_effect=Exception("PCS down")):

      mock_date_cls.today.return_value.year = 2026
      mock_date_cls.today.return_value.strftime.return_value = "04-12"

      result = fetch_stage_context("Tour de Romandie - Stage 3")

    assert result.is_resolved is False

  def test_pcs_stage_exception(self, mock_db_romandie, mock_race_multi_stage):
    """Exception from Stage() returns is_resolved=False without raising."""
    with patch("intelligence.stage_context.get_db", return_value=mock_db_romandie), \
         patch("intelligence.stage_context._date") as mock_date_cls, \
         patch("procyclingstats.Race", return_value=mock_race_multi_stage), \
         patch("procyclingstats.Stage", side_effect=AttributeError("NoneType")):

      mock_date_cls.today.return_value.year = 2026
      mock_date_cls.today.return_value.strftime.return_value = "04-12"

      result = fetch_stage_context("Tour de Romandie - Stage 3")

    assert result.is_resolved is False

  def test_timeout_returns_unresolved(self, mock_db_romandie):
    """PCS fetch that exceeds 5s timeout returns is_resolved=False within 6 seconds."""
    def slow_fetch(*args, **kwargs):
      time.sleep(10)
      return StageContext(is_resolved=True)

    with patch("intelligence.stage_context.get_db", return_value=mock_db_romandie), \
         patch("intelligence.stage_context._date") as mock_date_cls, \
         patch("intelligence.stage_context._do_fetch", side_effect=slow_fetch):

      mock_date_cls.today.return_value.year = 2026

      start = time.time()
      result = fetch_stage_context("Tour de Romandie - Stage 3")
      elapsed = time.time() - start

    assert result.is_resolved is False
    assert elapsed < 6.0, f"Expected return within 6s, took {elapsed:.1f}s"

  def test_no_stage_today(self, mock_db_romandie):
    """When no stage matches today's date, returns is_resolved=False."""
    race = MagicMock()
    race.is_one_day_race.return_value = False
    race.uci_tour.return_value = "2.UWT"
    # Stages have dates that don't match today
    race.stages.return_value = [
      {"stage_url": "race/tour-de-romandie/2026/stage-1", "date": "01-01"},
      {"stage_url": "race/tour-de-romandie/2026/stage-2", "date": "01-02"},
    ]

    with patch("intelligence.stage_context.get_db", return_value=mock_db_romandie), \
         patch("intelligence.stage_context._date") as mock_date_cls, \
         patch("procyclingstats.Race", return_value=race), \
         patch("procyclingstats.Stage") as mock_stage_cls:

      # Today is 04-12, stages are in January
      mock_date_cls.today.return_value.strftime.return_value = "04-12"
      mock_date_cls.today.return_value.year = 2026

      result = fetch_stage_context("Tour de Romandie - Stage 3")

    assert result.is_resolved is False
    # Stage should not have been constructed since no date matched
    mock_stage_cls.assert_not_called()


# ---------------------------------------------------------------------------
# TestLiveIntegration (real PCS network calls — no mocks)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestLiveIntegration:
  """Live integration tests against real PCS network — no mocks.

  These tests exercise the full fetch_stage_context pipeline with real
  network calls to procyclingstats.com. They are marked `integration`
  and can be excluded via `pytest -m "not integration"`.

  Note: cache.db races table may be empty in development environments.
  When the races table is empty, _resolve_race_url returns None immediately
  and fetch_stage_context returns is_resolved=False without making any
  network call. Tests are written to accommodate both scenarios.
  """

  def test_known_race_resolves(self):
    """_do_fetch returns a populated StageContext for a known upcoming WT stage URL.

    Tests PCS network connectivity and data parsing directly via _do_fetch,
    bypassing the cache.db fuzzy-match step. Uses Giro d'Italia 2026 Stage 1
    (upcoming as of 2026-04-12, starts 2026-05-09).

    SC-1: fetch_stage_context returns a populated StageContext with
    non-default values for distance, profile_icon, stage_type, race_date, uci_tour.
    """
    from intelligence.stage_context import _do_fetch, StageContext

    # Giro d'Italia 2026 Stage 1 — upcoming, verified live during research
    known_stage_url = "race/giro-d-italia/2026/stage-1"
    result = _do_fetch(known_stage_url)

    assert isinstance(result, StageContext), f"Expected StageContext, got {type(result)}"
    assert result.is_resolved is True, (
      f"Expected is_resolved=True for {known_stage_url}, got is_resolved=False. "
      "Check that the PCS page is still accessible and the stage URL is valid."
    )
    assert result.distance > 0.0, f"distance should be > 0, got {result.distance}"
    assert result.profile_icon in ("p1", "p2", "p3", "p4", "p5"), (
      f"profile_icon should be p1-p5, got {result.profile_icon!r}"
    )
    assert result.stage_type in ("RR", "ITT", "TTT"), (
      f"stage_type should be RR/ITT/TTT, got {result.stage_type!r}"
    )
    assert result.race_date != "", f"race_date should not be empty, got {result.race_date!r}"
    assert result.uci_tour != "", f"uci_tour should not be empty, got {result.uci_tour!r}"
    # num_climbs is 0 for upcoming stages (KOM tables absent pre-race) — acceptable per D-09
    assert isinstance(result.num_climbs, int), f"num_climbs should be int, got {type(result.num_climbs)}"
    print(f"\n[live] _do_fetch result for {known_stage_url}: {result}")

  def test_unresolvable_race_degrades(self):
    """fetch_stage_context with a bogus race name returns is_resolved=False quickly.

    When cache.db races table is empty, the function returns immediately
    (no network call attempted). When the DB has races, it returns after
    fuzzy matching fails. Either way, it must complete in < 6 seconds.
    """
    import time
    start = time.time()
    result = fetch_stage_context("ZZZZZ Completely Fake Race 9999")
    elapsed = time.time() - start

    assert result.is_resolved is False
    assert elapsed < 6.0, f"Degradation took {elapsed:.1f}s, expected < 6s"
    print(f"\n[live] Bogus race degraded in {elapsed:.3f}s (expected < 6s)")

  def test_one_day_race_resolves(self):
    """fetch_stage_context with 'Paris-Roubaix' returns a StageContext without raising.

    When cache.db races table has 2026 data, Paris-Roubaix should fuzzy-match
    and return is_resolved=True with is_one_day_race=True.
    When cache.db is empty (development), is_resolved=False is acceptable.
    In both cases, the function must not raise an exception.
    """
    result = fetch_stage_context("Paris-Roubaix")

    assert isinstance(result, StageContext), f"Expected StageContext, got {type(result)}"
    # If resolved, validate one-day race fields
    if result.is_resolved:
      assert result.is_one_day_race is True, (
        f"Paris-Roubaix should have is_one_day_race=True, got {result.is_one_day_race}"
      )
      assert result.distance > 0.0, f"Paris-Roubaix distance should be > 0, got {result.distance}"
    else:
      # cache.db empty or no 2026 races scraped yet — acceptable in dev environment
      print(
        "\n[live] Paris-Roubaix: is_resolved=False (cache.db may be empty — "
        "run scripts/scrape_all.py to populate races table)"
      )
    print(f"\n[live] fetch_stage_context('Paris-Roubaix'): {result}")
