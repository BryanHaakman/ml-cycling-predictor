"""
P&L (Profit & Loss) tracker for cycling bets.

Stores bets in SQLite alongside the scraped data cache.
Tracks bankroll, ROI, win rate, and provides data for charts.

Public interface (new in Phase 6):
  - compute_clv()              — raw + vig-free CLV from closing odds
  - clv_confidence_interval()  — bootstrap 95% CI for mean CLV
  - get_total_bankroll()       — cash + pending stakes (D-20)
  - get_clv_summary()          — aggregate CLV stats with CI
  - get_clv_by_terrain()       — CLV grouped by profile_type_label
"""

import logging
import sqlite3
import json
from datetime import datetime
from typing import Optional

from data.scraper import get_db, DB_PATH

log = logging.getLogger(__name__)


def _create_pnl_tables(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS bets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT DEFAULT (datetime('now')),
        race_date TEXT,
        race_name TEXT,
        stage_url TEXT,
        rider_a_url TEXT,
        rider_a_name TEXT,
        rider_b_url TEXT,
        rider_b_name TEXT,
        selection TEXT,          -- 'A' or 'B'
        selection_name TEXT,
        decimal_odds REAL,
        implied_prob REAL,
        model_prob REAL,
        edge REAL,
        kelly_fraction REAL,
        stake REAL,
        bankroll_at_bet REAL,
        status TEXT DEFAULT 'pending',  -- pending, won, lost, void
        payout REAL DEFAULT 0,
        profit REAL DEFAULT 0,
        settled_at TEXT,
        model_used TEXT,
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS bankroll_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT DEFAULT (datetime('now')),
        bankroll REAL,
        event TEXT  -- 'initial', 'bet_placed', 'bet_settled', 'deposit', 'withdrawal'
    );

    CREATE INDEX IF NOT EXISTS idx_bets_status ON bets(status);
    CREATE INDEX IF NOT EXISTS idx_bets_date ON bets(race_date);

    CREATE TABLE IF NOT EXISTS saved_races (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        distance_km REAL,
        vertical_meters REAL,
        profile_icon TEXT,
        stage_type TEXT DEFAULT 'RR',
        is_one_day_race INTEGER DEFAULT 0,
        num_climbs INTEGER DEFAULT 0,
        race_base_url TEXT,
        race_date TEXT
    );
    """)

    # Migrate: add race metadata snapshot columns to bets (idempotent)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(bets)").fetchall()}
    migrations = [
        ("is_one_day_race", "INTEGER"),
        ("stage_type", "TEXT"),
        ("profile_icon", "TEXT"),
        ("distance_km", "REAL"),
        ("vertical_meters", "REAL"),
        ("num_climbs", "INTEGER"),
    ]
    for col_name, col_type in migrations:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE bets ADD COLUMN {col_name} {col_type}")

    # Migrate: CLV and bet enrichment columns (D-13, D-14)
    clv_migrations = [
        ("closing_odds_a", "REAL"),
        ("closing_odds_b", "REAL"),
        ("clv", "REAL"),
        ("clv_no_vig", "REAL"),
        ("recommended_stake", "REAL"),
    ]
    for col_name, col_type in clv_migrations:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE bets ADD COLUMN {col_name} {col_type}")

    # Market snapshots table (shared with pinnacle_scraper — CREATE IF NOT EXISTS)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT DEFAULT (datetime('now')),
            race_name TEXT NOT NULL,
            race_slug TEXT,
            rider_a_name TEXT NOT NULL,
            rider_b_name TEXT NOT NULL,
            rider_a_pcs_url TEXT,
            rider_b_pcs_url TEXT,
            odds_a REAL NOT NULL,
            odds_b REAL NOT NULL,
            implied_prob_a REAL,
            implied_prob_b REAL,
            start_time TEXT,
            start_date TEXT,
            model_prob_a REAL,
            edge_a REAL,
            recommended_stake_a REAL,
            model_prob_b REAL,
            edge_b REAL,
            recommended_stake_b REAL,
            snapshot_type TEXT DEFAULT 'manual',
            source_url TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_date ON market_snapshots(captured_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_race ON market_snapshots(race_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_riders ON market_snapshots(rider_a_name, rider_b_name)")

    conn.commit()


def get_pnl_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = get_db(db_path)
    _create_pnl_tables(conn)
    return conn


def compute_clv(
    bet_odds: float,
    closing_odds_a: float,
    closing_odds_b: float,
    selection: str,
) -> tuple[float, float]:
  """Compute raw CLV and vig-free CLV using multiplicative vig removal (D-16).

  Args:
    bet_odds: Decimal odds at time of bet placement.
    closing_odds_a: Closing decimal odds for rider A.
    closing_odds_b: Closing decimal odds for rider B.
    selection: 'A' or 'B' — which rider was backed.

  Returns:
    Tuple of (clv_raw, clv_no_vig) as fractions (not percentages).
  """
  bet_implied = 1.0 / bet_odds
  closing_odds = closing_odds_a if selection == 'A' else closing_odds_b
  closing_implied = 1.0 / closing_odds
  clv_raw = (closing_implied - bet_implied) / bet_implied

  # Multiplicative vig removal (equal-margin method for H2H)
  total_implied = (1.0 / closing_odds_a) + (1.0 / closing_odds_b)
  fair_prob = closing_implied / total_implied
  clv_no_vig = (fair_prob - bet_implied) / bet_implied

  return clv_raw, clv_no_vig


def clv_confidence_interval(
    clv_values: list[float],
    confidence: float = 0.95,
) -> tuple[float, float]:
  """Compute bootstrap 95% CI for mean CLV using scipy.stats.bootstrap (D-29).

  Uses BCa method with 10000 resamples and random_state=42 for reproducibility.
  Returns (0.0, 0.0) if fewer than 5 values (insufficient sample).

  Args:
    clv_values: List of CLV values from settled bets.
    confidence: Confidence level (default 0.95).

  Returns:
    Tuple of (ci_low, ci_high).
  """
  if len(clv_values) < 5:
    return (0.0, 0.0)

  from scipy.stats import bootstrap
  import numpy as np

  data = (np.array(clv_values),)
  result = bootstrap(
    data, np.mean, confidence_level=confidence,
    n_resamples=10000, random_state=42, method='BCa',
  )
  return (
    float(result.confidence_interval.low),
    float(result.confidence_interval.high),
  )


def set_initial_bankroll(bankroll: float, db_path: str = DB_PATH):
    conn = get_pnl_db(db_path)
    conn.execute(
        "INSERT INTO bankroll_history (bankroll, event) VALUES (?, 'initial')",
        (bankroll,)
    )
    conn.commit()
    conn.close()


def get_current_bankroll(db_path: str = DB_PATH) -> float:
    conn = get_pnl_db(db_path)
    row = conn.execute(
        "SELECT bankroll FROM bankroll_history ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["bankroll"] if row else 0.0


def get_total_bankroll(db_path: str = DB_PATH) -> float:
  """Return total bankroll = cash balance + sum of all pending stakes (D-20).

  Kelly sizing uses this value so pending bets don't shrink recommendations.
  Cash balance is the latest bankroll_history entry; pending stakes are
  the sum of stakes on all unsettled bets.
  """
  conn = get_pnl_db(db_path)
  cash_row = conn.execute(
    "SELECT bankroll FROM bankroll_history ORDER BY id DESC LIMIT 1"
  ).fetchone()
  pending_row = conn.execute(
    "SELECT COALESCE(SUM(stake), 0) as pending FROM bets WHERE status = 'pending'"
  ).fetchone()
  conn.close()
  cash = cash_row["bankroll"] if cash_row else 0.0
  pending = pending_row["pending"] if pending_row else 0.0
  return cash + pending


def place_bet(
    stage_url: str,
    race_name: str,
    race_date: str,
    rider_a_url: str,
    rider_a_name: str,
    rider_b_url: str,
    rider_b_name: str,
    selection: str,  # 'A' or 'B'
    decimal_odds: float,
    model_prob: float,
    kelly_fraction: float,
    stake: float,
    model_used: str = "",
    notes: str = "",
    is_one_day_race: Optional[int] = None,
    stage_type: Optional[str] = None,
    profile_icon: Optional[str] = None,
    distance_km: Optional[float] = None,
    vertical_meters: Optional[float] = None,
    num_climbs: Optional[int] = None,
    recommended_stake: float = 0.0,
    capture_timestamp: str = "",
    db_path: str = DB_PATH,
) -> int:
  """Log a new bet. Returns the bet ID.

  Args:
    recommended_stake: Quarter-Kelly recommended amount (D-14/BET-01).
    capture_timestamp: Timestamp of odds capture (ODDS-03).
    All other args: see existing place_bet signature.
  """
  conn = get_pnl_db(db_path)

  implied_prob = 1.0 / decimal_odds if decimal_odds > 1 else 1.0
  edge = model_prob - implied_prob
  selection_name = rider_a_name if selection == "A" else rider_b_name
  bankroll = get_current_bankroll(db_path)

  cursor = conn.execute("""
      INSERT INTO bets (race_date, race_name, stage_url, rider_a_url, rider_a_name,
          rider_b_url, rider_b_name, selection, selection_name, decimal_odds,
          implied_prob, model_prob, edge, kelly_fraction, stake,
          bankroll_at_bet, model_used, notes,
          is_one_day_race, stage_type, profile_icon, distance_km, vertical_meters, num_climbs,
          recommended_stake)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
              ?, ?, ?, ?, ?, ?, ?)
  """, (
      race_date, race_name, stage_url, rider_a_url, rider_a_name,
      rider_b_url, rider_b_name, selection, selection_name, decimal_odds,
      implied_prob, model_prob, edge, kelly_fraction, stake,
      bankroll, model_used, notes,
      is_one_day_race, stage_type, profile_icon, distance_km, vertical_meters, num_climbs,
      recommended_stake,
  ))

  bet_id = cursor.lastrowid
  new_bankroll = bankroll - stake
  conn.execute(
      "INSERT INTO bankroll_history (bankroll, event) VALUES (?, 'bet_placed')",
      (new_bankroll,)
  )
  conn.commit()
  conn.close()
  return bet_id


def settle_bet(
    bet_id: int,
    won: bool,
    db_path: str = DB_PATH,
):
  """Settle a pending bet as won or lost, atomically computing CLV (D-15).

  After updating win/loss status, looks up closing odds from
  market_snapshots and computes CLV in the same transaction.
  If no closing odds are found, settlement proceeds with NULL CLV.
  """
  conn = get_pnl_db(db_path)
  bet = conn.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
  if not bet:
    conn.close()
    raise ValueError(f"Bet {bet_id} not found")

  if bet["status"] != "pending":
    conn.close()
    raise ValueError(f"Bet {bet_id} already settled as {bet['status']}")

  if won:
    payout = bet["stake"] * bet["decimal_odds"]
    profit = payout - bet["stake"]
    status = "won"
  else:
    payout = 0.0
    profit = -bet["stake"]
    status = "lost"

  conn.execute("""
      UPDATE bets SET status = ?, payout = ?, profit = ?, settled_at = datetime('now')
      WHERE id = ?
  """, (status, payout, profit, bet_id))

  # Atomic CLV computation (D-15): lookup closing odds and write CLV
  closing = conn.execute("""
      SELECT odds_a, odds_b FROM market_snapshots
      WHERE rider_a_name = ? AND rider_b_name = ?
        AND snapshot_type = 'closing'
      ORDER BY captured_at DESC LIMIT 1
  """, (bet["rider_a_name"], bet["rider_b_name"])).fetchone()

  if closing and closing["odds_a"] and closing["odds_b"]:
    clv_raw, clv_nv = compute_clv(
      bet["decimal_odds"], closing["odds_a"], closing["odds_b"],
      bet["selection"],
    )
    conn.execute("""
        UPDATE bets
        SET closing_odds_a = ?, closing_odds_b = ?, clv = ?, clv_no_vig = ?
        WHERE id = ?
    """, (closing["odds_a"], closing["odds_b"], clv_raw, clv_nv, bet_id))
  else:
    log.warning("settle_bet: no closing odds for bet %d — CLV left as NULL", bet_id)

  bankroll = get_current_bankroll(db_path) + payout
  conn.execute(
      "INSERT INTO bankroll_history (bankroll, event) VALUES (?, 'bet_settled')",
      (bankroll,)
  )
  conn.commit()
  conn.close()


def void_bet(bet_id: int, db_path: str = DB_PATH):
    """Void a pending bet (refund stake)."""
    conn = get_pnl_db(db_path)
    bet = conn.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
    if not bet:
        conn.close()
        raise ValueError(f"Bet {bet_id} not found")

    conn.execute(
        "UPDATE bets SET status = 'void', settled_at = datetime('now') WHERE id = ?",
        (bet_id,)
    )
    bankroll = get_current_bankroll(db_path) + bet["stake"]
    conn.execute(
        "INSERT INTO bankroll_history (bankroll, event) VALUES (?, 'bet_voided')",
        (bankroll,)
    )
    conn.commit()
    conn.close()


def update_bet_odds(bet_id: int, new_odds: float, db_path: str = DB_PATH):
    """Update the decimal odds on a pending bet."""
    conn = get_pnl_db(db_path)
    bet = conn.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
    if not bet:
        conn.close()
        raise ValueError(f"Bet {bet_id} not found")
    if bet["status"] != "pending":
        conn.close()
        raise ValueError(f"Bet {bet_id} is already {bet['status']} — can only edit pending bets")
    conn.execute(
        "UPDATE bets SET decimal_odds = ? WHERE id = ?",
        (new_odds, bet_id),
    )
    conn.commit()
    conn.close()


def get_pnl_summary(db_path: str = DB_PATH) -> dict:
    """Get P&L summary statistics."""
    conn = get_pnl_db(db_path)

    settled = conn.execute(
        "SELECT * FROM bets WHERE status IN ('won', 'lost')"
    ).fetchall()

    pending = conn.execute(
        "SELECT * FROM bets WHERE status = 'pending'"
    ).fetchall()

    total_staked = sum(b["stake"] for b in settled)
    total_returned = sum(b["payout"] for b in settled)
    total_profit = sum(b["profit"] for b in settled)
    wins = sum(1 for b in settled if b["status"] == "won")
    losses = sum(1 for b in settled if b["status"] == "lost")
    total_bets = wins + losses
    pending_stake = sum(b["stake"] for b in pending)

    avg_edge = (
        sum(b["edge"] for b in settled) / total_bets if total_bets > 0 else 0
    )
    avg_odds = (
        sum(b["decimal_odds"] for b in settled) / total_bets if total_bets > 0 else 0
    )

    bankroll = get_current_bankroll(db_path)

    # Bankroll history for chart
    history = conn.execute(
        "SELECT timestamp, bankroll, event FROM bankroll_history ORDER BY id"
    ).fetchall()

    conn.close()

    return {
        "bankroll": bankroll,
        "total_bets": total_bets,
        "pending_bets": len(pending),
        "pending_stake": pending_stake,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / total_bets if total_bets > 0 else 0,
        "total_staked": total_staked,
        "total_returned": total_returned,
        "total_profit": total_profit,
        "roi": total_profit / total_staked if total_staked > 0 else 0,
        "avg_edge": avg_edge,
        "avg_odds": avg_odds,
        "bankroll_history": [
            {"timestamp": h["timestamp"], "bankroll": h["bankroll"], "event": h["event"]}
            for h in history
        ],
    }


def get_bet_history(
    db_path: str = DB_PATH,
    limit: int = 50,
    status: Optional[str] = None,
    race_name: Optional[str] = None,
    stage_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
  """Get bet history with optional SQL-level filters (D-19/BET-03).

  All filters use parameterized queries — never string interpolation (T-06-04).

  Args:
    limit: Maximum number of rows to return.
    status: Filter by bet status ('pending', 'won', 'lost', 'void').
    race_name: Filter by exact race name.
    stage_type: Filter by stage type ('RR', 'ITT', 'TTT').
    date_from: Filter bets on or after this date (YYYY-MM-DD).
    date_to: Filter bets on or before this date (YYYY-MM-DD).

  Returns:
    List of bet dicts, most recent first.
  """
  conn = get_pnl_db(db_path)
  clauses: list[str] = []
  params: list = []

  if status is not None:
    clauses.append("status = ?")
    params.append(status)
  if race_name is not None:
    clauses.append("race_name = ?")
    params.append(race_name)
  if stage_type is not None:
    clauses.append("stage_type = ?")
    params.append(stage_type)
  if date_from is not None:
    clauses.append("race_date >= ?")
    params.append(date_from)
  if date_to is not None:
    clauses.append("race_date <= ?")
    params.append(date_to)

  where = ""
  if clauses:
    where = "WHERE " + " AND ".join(clauses)

  query = f"SELECT * FROM bets {where} ORDER BY id DESC LIMIT ?"
  params.append(limit)

  bets = conn.execute(query, params).fetchall()
  conn.close()
  return [dict(b) for b in bets]


def auto_settle_from_results(db_path: str = DB_PATH) -> int:
    """
    Auto-settle pending bets using scraped race results.
    Returns number of bets settled.
    """
    conn = get_pnl_db(db_path)
    pending = conn.execute(
        "SELECT * FROM bets WHERE status = 'pending'"
    ).fetchall()
    conn.close()

    settled_count = 0
    for bet in pending:
        # Open a fresh connection per iteration so an exception in settle_bet
        # doesn't leave a closed connection for the next iteration.
        conn = get_pnl_db(db_path)
        result_a = conn.execute(
            "SELECT rank FROM results WHERE stage_url = ? AND rider_url = ?",
            (bet["stage_url"], bet["rider_a_url"])
        ).fetchone()
        result_b = conn.execute(
            "SELECT rank FROM results WHERE stage_url = ? AND rider_url = ?",
            (bet["stage_url"], bet["rider_b_url"])
        ).fetchone()
        conn.close()

        rank_a = result_a["rank"] if result_a else None
        rank_b = result_b["rank"] if result_b else None

        # Neither rider has a result at all — can't settle
        if result_a is None and result_b is None:
            continue

        # Both have results but both DNF (rank is None) — can't settle
        if rank_a is None and rank_b is None:
            continue

        # One missing/DNF — the rider with a finishing rank wins
        if rank_a is None:
            a_ahead = False
        elif rank_b is None:
            a_ahead = True
        else:
            a_ahead = rank_a < rank_b
        selection_won = (bet["selection"] == "A" and a_ahead) or \
                       (bet["selection"] == "B" and not a_ahead)

        settle_bet(bet["id"], won=selection_won, db_path=db_path)
        settled_count += 1

    return settled_count


def profile_type_label(profile_icon: Optional[str] = None,
                       stage_type: Optional[str] = None,
                       race_name: Optional[str] = None) -> str:
    """Derive a human-readable profile label from raw metadata."""
    if stage_type and stage_type in ("ITT", "TTT"):
        return "tt"
    if race_name and any(k in (race_name or "").lower() for k in ("roubaix", "cobble")):
        return "cobbles"
    mapping = {"p0": "flat", "p1": "flat", "p2": "hilly", "p3": "hilly",
               "p4": "mountain", "p5": "mountain"}
    return mapping.get(profile_icon, "unknown")


def get_pnl_by_race_type(db_path: str = DB_PATH) -> list[dict]:
    """
    Analyse settled bet P&L grouped by profile type.

    Returns list of dicts with keys: profile_type, bets, wins, losses,
    win_rate, total_staked, total_profit, roi.
    """
    conn = get_pnl_db(db_path)
    settled = conn.execute(
        "SELECT * FROM bets WHERE status IN ('won', 'lost')"
    ).fetchall()
    conn.close()

    groups: dict[str, list] = {}
    for b in settled:
        label = profile_type_label(b["profile_icon"], b["stage_type"], b["race_name"])
        groups.setdefault(label, []).append(b)

    results = []
    for label, bets in sorted(groups.items()):
        wins = sum(1 for b in bets if b["status"] == "won")
        losses = len(bets) - wins
        staked = sum(b["stake"] for b in bets)
        profit = sum(b["profit"] for b in bets)
        results.append({
            "profile_type": label,
            "bets": len(bets),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / len(bets) if bets else 0,
            "total_staked": staked,
            "total_profit": profit,
            "roi": profit / staked if staked > 0 else 0,
        })
    return results


def get_pnl_by_race_category(db_path: str = DB_PATH) -> list[dict]:
    """
    Analyse settled bet P&L grouped by race category (stage_race vs one_day).
    """
    conn = get_pnl_db(db_path)
    settled = conn.execute(
        "SELECT * FROM bets WHERE status IN ('won', 'lost')"
    ).fetchall()
    conn.close()

    groups: dict[str, list] = {}
    for b in settled:
        label = "one_day" if b["is_one_day_race"] == 1 else "stage_race" if b["is_one_day_race"] == 0 else "unknown"
        groups.setdefault(label, []).append(b)

    results = []
    for label, bets in sorted(groups.items()):
        wins = sum(1 for b in bets if b["status"] == "won")
        losses = len(bets) - wins
        staked = sum(b["stake"] for b in bets)
        profit = sum(b["profit"] for b in bets)
        results.append({
            "race_category": label,
            "bets": len(bets),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / len(bets) if bets else 0,
            "total_staked": staked,
            "total_profit": profit,
            "roi": profit / staked if staked > 0 else 0,
        })
    return results


def get_clv_summary(db_path: str = DB_PATH) -> dict:
  """Return aggregate CLV statistics with bootstrap confidence interval.

  Queries all settled bets with non-NULL clv. Computes average raw CLV,
  average vig-free CLV, 95% bootstrap CI, and total count.

  Returns:
    Dict with keys: avg_clv, avg_clv_no_vig, ci_low, ci_high, n_bets.
  """
  conn = get_pnl_db(db_path)
  rows = conn.execute(
    "SELECT clv, clv_no_vig FROM bets WHERE status IN ('won', 'lost') AND clv IS NOT NULL"
  ).fetchall()
  conn.close()

  if not rows:
    return {
      "avg_clv": 0.0,
      "avg_clv_no_vig": 0.0,
      "ci_low": 0.0,
      "ci_high": 0.0,
      "n_bets": 0,
    }

  clv_vals = [r["clv"] for r in rows]
  clv_nv_vals = [r["clv_no_vig"] for r in rows]
  ci_low, ci_high = clv_confidence_interval(clv_vals)

  return {
    "avg_clv": sum(clv_vals) / len(clv_vals),
    "avg_clv_no_vig": sum(clv_nv_vals) / len(clv_nv_vals),
    "ci_low": ci_low,
    "ci_high": ci_high,
    "n_bets": len(rows),
  }


def get_clv_by_terrain(db_path: str = DB_PATH) -> list[dict]:
  """Return CLV breakdown grouped by terrain type (CLV-07).

  Groups settled bets with non-NULL clv by profile_type_label().
  For each group, computes average CLV, average vig-free CLV, count,
  and bootstrap CI (suppressed if n < 5).

  Returns:
    List of dicts with keys: stage_type, n_bets, avg_clv, avg_clv_no_vig,
    ci_low, ci_high.
  """
  conn = get_pnl_db(db_path)
  rows = conn.execute(
    "SELECT clv, clv_no_vig, profile_icon, stage_type, race_name "
    "FROM bets WHERE status IN ('won', 'lost') AND clv IS NOT NULL"
  ).fetchall()
  conn.close()

  groups: dict[str, list[dict]] = {}
  for r in rows:
    label = profile_type_label(r["profile_icon"], r["stage_type"], r["race_name"])
    groups.setdefault(label, []).append(dict(r))

  results = []
  for label, bets in sorted(groups.items()):
    clv_vals = [b["clv"] for b in bets]
    clv_nv_vals = [b["clv_no_vig"] for b in bets]
    ci_low, ci_high = clv_confidence_interval(clv_vals)
    results.append({
      "stage_type": label,
      "n_bets": len(bets),
      "avg_clv": sum(clv_vals) / len(clv_vals),
      "avg_clv_no_vig": sum(clv_nv_vals) / len(clv_nv_vals),
      "ci_low": ci_low,
      "ci_high": ci_high,
    })
  return results
