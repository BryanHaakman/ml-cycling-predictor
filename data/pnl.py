"""
P&L (Profit & Loss) tracker for cycling bets.

Stores bets in SQLite alongside the scraped data cache.
Tracks bankroll, ROI, win rate, and provides data for charts.
"""

import sqlite3
import json
from datetime import datetime
from typing import Optional

from data.scraper import get_db, DB_PATH


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

    conn.commit()


def get_pnl_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = get_db(db_path)
    _create_pnl_tables(conn)
    return conn


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
    db_path: str = DB_PATH,
) -> int:
    """Log a new bet. Returns the bet ID."""
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
            is_one_day_race, stage_type, profile_icon, distance_km, vertical_meters, num_climbs)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?)
    """, (
        race_date, race_name, stage_url, rider_a_url, rider_a_name,
        rider_b_url, rider_b_name, selection, selection_name, decimal_odds,
        implied_prob, model_prob, edge, kelly_fraction, stake,
        bankroll, model_used, notes,
        is_one_day_race, stage_type, profile_icon, distance_km, vertical_meters, num_climbs,
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
    """Settle a pending bet as won or lost."""
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


def get_bet_history(db_path: str = DB_PATH, limit: int = 50) -> list[dict]:
    """Get recent bet history."""
    conn = get_pnl_db(db_path)
    bets = conn.execute(
        "SELECT * FROM bets ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
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

    settled_count = 0
    for bet in pending:
        # Check if results exist for this stage
        result_a = conn.execute(
            "SELECT rank FROM results WHERE stage_url = ? AND rider_url = ?",
            (bet["stage_url"], bet["rider_a_url"])
        ).fetchone()
        result_b = conn.execute(
            "SELECT rank FROM results WHERE stage_url = ? AND rider_url = ?",
            (bet["stage_url"], bet["rider_b_url"])
        ).fetchone()

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

        conn.close()
        settle_bet(bet["id"], won=selection_won, db_path=db_path)
        conn = get_pnl_db(db_path)
        settled_count += 1

    conn.close()
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
