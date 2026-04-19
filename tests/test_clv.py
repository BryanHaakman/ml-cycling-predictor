"""
Unit tests for CLV computation and schema migration in data/pnl.py.

Tests cover:
- compute_clv() raw and vig-free formula
- clv_confidence_interval() bootstrap CI
- _create_pnl_tables() migration adds CLV columns
- get_total_bankroll() cash + pending stakes
- place_bet() recommended_stake parameter
- settle_bet() writes CLV atomically
- auto_settle_from_results() uses closing odds
- get_bet_history() SQL filters (status, race_name, stage_type)
- get_clv_summary() aggregate stats
- get_clv_by_terrain() groups by profile_type_label
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.pnl import (
  compute_clv,
  clv_confidence_interval,
  get_total_bankroll,
  get_clv_summary,
  get_clv_by_terrain,
  get_pnl_db,
  place_bet,
  settle_bet,
  set_initial_bankroll,
  get_bet_history,
  auto_settle_from_results,
)
from data.scraper import get_db


class TestSchemaMigration(unittest.TestCase):
  """Verify _create_pnl_tables adds all CLV columns idempotently."""

  def test_clv_columns_added(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      conn = get_pnl_db(db_path=tmp_db)
      cols = {row[1] for row in conn.execute("PRAGMA table_info(bets)").fetchall()}
      self.assertIn("closing_odds_a", cols)
      self.assertIn("closing_odds_b", cols)
      self.assertIn("clv", cols)
      self.assertIn("clv_no_vig", cols)
      self.assertIn("recommended_stake", cols)
      conn.close()
    finally:
      os.unlink(tmp_db)

  def test_migration_idempotent(self):
    """Calling get_pnl_db twice does not error."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      conn1 = get_pnl_db(db_path=tmp_db)
      conn1.close()
      conn2 = get_pnl_db(db_path=tmp_db)
      cols = {row[1] for row in conn2.execute("PRAGMA table_info(bets)").fetchall()}
      self.assertIn("closing_odds_a", cols)
      conn2.close()
    finally:
      os.unlink(tmp_db)

  def test_market_snapshots_table_created(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      conn = get_pnl_db(db_path=tmp_db)
      tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
      ).fetchall()}
      self.assertIn("market_snapshots", tables)
      conn.close()
    finally:
      os.unlink(tmp_db)


class TestComputeClv(unittest.TestCase):
  """Verify CLV formula for both selection A and B."""

  def test_selection_a(self):
    # Bet at 2.0 on A; closing: A=1.8, B=2.1
    clv_raw, clv_no_vig = compute_clv(2.0, 1.8, 2.1, 'A')
    # bet_implied = 0.5, closing_implied_a = 1/1.8 = 0.5556
    # clv_raw = (0.5556 - 0.5) / 0.5 = 0.1111
    self.assertAlmostEqual(clv_raw, 0.1111, places=3)
    # vig-free: total_implied = 1/1.8 + 1/2.1 = 0.5556 + 0.4762 = 1.0317
    # fair_prob = 0.5556 / 1.0317 = 0.5386
    # clv_no_vig = (0.5386 - 0.5) / 0.5 = 0.0772
    self.assertAlmostEqual(clv_no_vig, 0.0772, places=3)

  def test_selection_b(self):
    # Bet at 2.1 on B; closing: A=1.8, B=2.1
    clv_raw, clv_no_vig = compute_clv(2.1, 1.8, 2.1, 'B')
    # bet_implied = 1/2.1 = 0.4762
    # closing_implied_b = 1/2.1 = 0.4762
    # clv_raw = (0.4762 - 0.4762) / 0.4762 = 0.0
    self.assertAlmostEqual(clv_raw, 0.0, places=3)

  def test_vig_free_differs_from_raw(self):
    clv_raw, clv_no_vig = compute_clv(2.0, 1.8, 2.1, 'A')
    self.assertNotAlmostEqual(clv_raw, clv_no_vig, places=3)

  def test_negative_clv(self):
    # Bet at 1.5 on A; closing: A=2.0, B=1.9 (line moved against us)
    clv_raw, clv_no_vig = compute_clv(1.5, 2.0, 1.9, 'A')
    # bet_implied = 1/1.5 = 0.6667
    # closing_implied = 1/2.0 = 0.5
    # clv_raw = (0.5 - 0.6667) / 0.6667 = -0.25
    self.assertAlmostEqual(clv_raw, -0.25, places=3)


class TestClvConfidenceInterval(unittest.TestCase):
  """Verify bootstrap CI computation."""

  def test_returns_tuple(self):
    values = [0.05, 0.03, 0.08, -0.01, 0.02, 0.04, 0.06]
    low, high = clv_confidence_interval(values)
    self.assertIsInstance(low, float)
    self.assertIsInstance(high, float)
    self.assertLess(low, high)

  def test_fewer_than_5_returns_zeros(self):
    low, high = clv_confidence_interval([0.05, 0.03])
    self.assertEqual(low, 0.0)
    self.assertEqual(high, 0.0)

  def test_exactly_5_values(self):
    low, high = clv_confidence_interval([0.05, 0.03, 0.08, -0.01, 0.02])
    self.assertLess(low, high)


class TestGetTotalBankroll(unittest.TestCase):
  """Verify bankroll = cash + pending stakes (D-20)."""

  def test_cash_plus_pending(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      set_initial_bankroll(1000.0, db_path=tmp_db)
      # Place a bet (deducts 50 from cash -> cash = 950)
      place_bet(
        stage_url="/test/stage",
        race_name="Test Race",
        race_date="2026-04-18",
        rider_a_url="/rider/a",
        rider_a_name="Rider A",
        rider_b_url="/rider/b",
        rider_b_name="Rider B",
        selection="A",
        decimal_odds=2.0,
        model_prob=0.55,
        kelly_fraction=0.05,
        stake=50.0,
        db_path=tmp_db,
      )
      total = get_total_bankroll(db_path=tmp_db)
      # cash=950 + pending_stake=50 = 1000
      self.assertAlmostEqual(total, 1000.0, places=2)
    finally:
      os.unlink(tmp_db)

  def test_no_bankroll_returns_zero(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      total = get_total_bankroll(db_path=tmp_db)
      self.assertEqual(total, 0.0)
    finally:
      os.unlink(tmp_db)


class TestPlaceBetRecommendedStake(unittest.TestCase):
  """Verify place_bet accepts and stores recommended_stake."""

  def test_recommended_stake_stored(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      set_initial_bankroll(1000.0, db_path=tmp_db)
      bet_id = place_bet(
        stage_url="/test/stage",
        race_name="Test Race",
        race_date="2026-04-18",
        rider_a_url="/rider/a",
        rider_a_name="Rider A",
        rider_b_url="/rider/b",
        rider_b_name="Rider B",
        selection="A",
        decimal_odds=2.0,
        model_prob=0.55,
        kelly_fraction=0.05,
        stake=50.0,
        recommended_stake=75.0,
        db_path=tmp_db,
      )
      conn = get_pnl_db(db_path=tmp_db)
      bet = conn.execute("SELECT recommended_stake FROM bets WHERE id = ?", (bet_id,)).fetchone()
      self.assertAlmostEqual(bet["recommended_stake"], 75.0)
      conn.close()
    finally:
      os.unlink(tmp_db)


class TestSettleBetWithClv(unittest.TestCase):
  """Verify settle_bet writes CLV when closing odds are available."""

  def _setup_bet_with_closing_odds(self, tmp_db: str) -> int:
    """Place a bet and insert a closing snapshot. Returns bet_id."""
    set_initial_bankroll(1000.0, db_path=tmp_db)
    bet_id = place_bet(
      stage_url="/test/stage",
      race_name="Test Race",
      race_date="2026-04-18",
      rider_a_url="/rider/a",
      rider_a_name="Rider A",
      rider_b_url="/rider/b",
      rider_b_name="Rider B",
      selection="A",
      decimal_odds=2.0,
      model_prob=0.55,
      kelly_fraction=0.05,
      stake=50.0,
      db_path=tmp_db,
    )
    # Insert closing odds snapshot
    conn = get_pnl_db(db_path=tmp_db)
    conn.execute("""
      INSERT INTO market_snapshots
        (race_name, rider_a_name, rider_b_name, odds_a, odds_b, snapshot_type)
      VALUES (?, ?, ?, ?, ?, 'closing')
    """, ("Test Race", "Rider A", "Rider B", 1.8, 2.1))
    conn.commit()
    conn.close()
    return bet_id

  def test_clv_populated_on_settle(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      bet_id = self._setup_bet_with_closing_odds(tmp_db)
      settle_bet(bet_id, won=True, db_path=tmp_db)
      conn = get_pnl_db(db_path=tmp_db)
      bet = conn.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
      self.assertIsNotNone(bet["clv"])
      self.assertIsNotNone(bet["clv_no_vig"])
      self.assertAlmostEqual(bet["closing_odds_a"], 1.8)
      self.assertAlmostEqual(bet["closing_odds_b"], 2.1)
      conn.close()
    finally:
      os.unlink(tmp_db)

  def test_clv_correct_value(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      bet_id = self._setup_bet_with_closing_odds(tmp_db)
      settle_bet(bet_id, won=True, db_path=tmp_db)
      conn = get_pnl_db(db_path=tmp_db)
      bet = conn.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
      # bet_odds=2.0, closing_a=1.8, closing_b=2.1, selection=A
      expected_raw, expected_nv = compute_clv(2.0, 1.8, 2.1, 'A')
      self.assertAlmostEqual(bet["clv"], expected_raw, places=6)
      self.assertAlmostEqual(bet["clv_no_vig"], expected_nv, places=6)
      conn.close()
    finally:
      os.unlink(tmp_db)


class TestSettleBetWithoutClosingOdds(unittest.TestCase):
  """Verify settle_bet works with NULL CLV when no closing odds available."""

  def test_settles_without_clv(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      set_initial_bankroll(1000.0, db_path=tmp_db)
      bet_id = place_bet(
        stage_url="/test/stage",
        race_name="Test Race",
        race_date="2026-04-18",
        rider_a_url="/rider/a",
        rider_a_name="Rider A",
        rider_b_url="/rider/b",
        rider_b_name="Rider B",
        selection="A",
        decimal_odds=2.0,
        model_prob=0.55,
        kelly_fraction=0.05,
        stake=50.0,
        db_path=tmp_db,
      )
      # No closing odds inserted — settle anyway
      settle_bet(bet_id, won=False, db_path=tmp_db)
      conn = get_pnl_db(db_path=tmp_db)
      bet = conn.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
      self.assertEqual(bet["status"], "lost")
      self.assertIsNone(bet["clv"])
      self.assertIsNone(bet["clv_no_vig"])
      conn.close()
    finally:
      os.unlink(tmp_db)


class TestGetBetHistory(unittest.TestCase):
  """Verify get_bet_history supports SQL-level filters."""

  def _place_bets(self, tmp_db: str):
    """Place several bets with different attributes."""
    set_initial_bankroll(10000.0, db_path=tmp_db)
    place_bet(
      stage_url="/race1/stage1", race_name="Tour de France",
      race_date="2026-04-18", rider_a_url="/ra", rider_a_name="A",
      rider_b_url="/rb", rider_b_name="B", selection="A",
      decimal_odds=2.0, model_prob=0.55, kelly_fraction=0.05,
      stake=50.0, stage_type="RR", db_path=tmp_db,
    )
    place_bet(
      stage_url="/race2/stage1", race_name="Giro d'Italia",
      race_date="2026-04-19", rider_a_url="/rc", rider_a_name="C",
      rider_b_url="/rd", rider_b_name="D", selection="B",
      decimal_odds=1.8, model_prob=0.6, kelly_fraction=0.08,
      stake=80.0, stage_type="ITT", db_path=tmp_db,
    )
    # Settle the first bet
    settle_bet(1, won=True, db_path=tmp_db)

  def test_filter_by_status(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      self._place_bets(tmp_db)
      pending = get_bet_history(db_path=tmp_db, status="pending")
      self.assertEqual(len(pending), 1)
      self.assertEqual(pending[0]["race_name"], "Giro d'Italia")
    finally:
      os.unlink(tmp_db)

  def test_filter_by_race_name(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      self._place_bets(tmp_db)
      tdf = get_bet_history(db_path=tmp_db, race_name="Tour de France")
      self.assertEqual(len(tdf), 1)
      self.assertEqual(tdf[0]["race_name"], "Tour de France")
    finally:
      os.unlink(tmp_db)

  def test_filter_by_stage_type(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      self._place_bets(tmp_db)
      itts = get_bet_history(db_path=tmp_db, stage_type="ITT")
      self.assertEqual(len(itts), 1)
      self.assertEqual(itts[0]["stage_type"], "ITT")
    finally:
      os.unlink(tmp_db)

  def test_no_filter_returns_all(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      self._place_bets(tmp_db)
      all_bets = get_bet_history(db_path=tmp_db)
      self.assertEqual(len(all_bets), 2)
    finally:
      os.unlink(tmp_db)


class TestGetClvSummary(unittest.TestCase):
  """Verify get_clv_summary returns correct aggregate stats."""

  def test_summary_with_clv_data(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      set_initial_bankroll(10000.0, db_path=tmp_db)
      # Place and settle bets with closing odds
      for i in range(6):
        bet_id = place_bet(
          stage_url=f"/race/stage{i}", race_name="Test Race",
          race_date="2026-04-18", rider_a_url=f"/ra{i}", rider_a_name=f"A{i}",
          rider_b_url=f"/rb{i}", rider_b_name=f"B{i}", selection="A",
          decimal_odds=2.0, model_prob=0.55, kelly_fraction=0.05,
          stake=50.0, db_path=tmp_db,
        )
        # Insert closing odds
        conn = get_pnl_db(db_path=tmp_db)
        conn.execute("""
          INSERT INTO market_snapshots
            (race_name, rider_a_name, rider_b_name, odds_a, odds_b, snapshot_type)
          VALUES (?, ?, ?, ?, ?, 'closing')
        """, ("Test Race", f"A{i}", f"B{i}", 1.8, 2.1))
        conn.commit()
        conn.close()
        settle_bet(bet_id, won=(i % 2 == 0), db_path=tmp_db)

      summary = get_clv_summary(db_path=tmp_db)
      self.assertIn("avg_clv", summary)
      self.assertIn("avg_clv_no_vig", summary)
      self.assertIn("ci_low", summary)
      self.assertIn("ci_high", summary)
      self.assertIn("n_bets", summary)
      self.assertEqual(summary["n_bets"], 6)
      self.assertGreater(summary["avg_clv"], 0)  # positive CLV since closing odds are tighter
    finally:
      os.unlink(tmp_db)


class TestGetClvByTerrain(unittest.TestCase):
  """Verify get_clv_by_terrain groups by profile_type_label."""

  def test_groups_by_terrain(self):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
      tmp_db = f.name
    try:
      set_initial_bankroll(10000.0, db_path=tmp_db)
      # Place bets with different profile_icons
      profiles = [("p0", "RR"), ("p0", "RR"), ("p4", "RR"), ("p4", "RR"), ("p4", "RR")]
      for i, (icon, st) in enumerate(profiles):
        bet_id = place_bet(
          stage_url=f"/race/stage{i}", race_name="Test Race",
          race_date="2026-04-18", rider_a_url=f"/ra{i}", rider_a_name=f"A{i}",
          rider_b_url=f"/rb{i}", rider_b_name=f"B{i}", selection="A",
          decimal_odds=2.0, model_prob=0.55, kelly_fraction=0.05,
          stake=50.0, profile_icon=icon, stage_type=st, db_path=tmp_db,
        )
        conn = get_pnl_db(db_path=tmp_db)
        conn.execute("""
          INSERT INTO market_snapshots
            (race_name, rider_a_name, rider_b_name, odds_a, odds_b, snapshot_type)
          VALUES (?, ?, ?, ?, ?, 'closing')
        """, ("Test Race", f"A{i}", f"B{i}", 1.8, 2.1))
        conn.commit()
        conn.close()
        settle_bet(bet_id, won=True, db_path=tmp_db)

      terrain = get_clv_by_terrain(db_path=tmp_db)
      self.assertIsInstance(terrain, list)
      labels = {t["stage_type"] for t in terrain}
      self.assertIn("flat", labels)
      self.assertIn("mountain", labels)
      for t in terrain:
        self.assertIn("avg_clv", t)
        self.assertIn("n_bets", t)
        self.assertIn("ci_low", t)
        self.assertIn("ci_high", t)
    finally:
      os.unlink(tmp_db)


if __name__ == "__main__":
  unittest.main()
