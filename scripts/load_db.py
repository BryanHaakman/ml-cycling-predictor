#!/usr/bin/env python3
"""Restore the SQLite database from a compressed snapshot.

Usage:
    python scripts/load_db.py                       # ← data/db_snapshot.sql.gz
    python scripts/load_db.py -i backup.sql.gz      # custom input path
    python scripts/load_db.py --force                # overwrite existing DB without prompt
"""

import sys
import os
import gzip
import sqlite3
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_INPUT = os.path.join(PROJECT_ROOT, "data", "db_snapshot.sql.gz")
DB_PATH = os.path.join(PROJECT_ROOT, "data", "cache.db")


def load_db(input_path: str, force: bool = False) -> None:
    if not os.path.exists(input_path):
        print(f"Error: snapshot not found: {input_path}")
        sys.exit(1)

    if os.path.exists(DB_PATH) and not force:
        response = input(f"Overwrite existing {DB_PATH}? [y/N] ").strip().lower()
        if response != "y":
            print("Aborted.")
            sys.exit(0)

    # Remove existing DB and WAL files
    for suffix in ("", "-shm", "-wal"):
        path = DB_PATH + suffix
        if os.path.exists(path):
            os.remove(path)

    size_mb = os.path.getsize(input_path) / (1024 * 1024)
    print(f"Restoring from: {input_path} ({size_mb:.1f} MB)")

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    with gzip.open(input_path, "rb") as f_in, open(DB_PATH, "wb") as f_out:
        while chunk := f_in.read(1024 * 1024):
            f_out.write(chunk)

    # Verify
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()

    total_rows = 0
    print(f"\nRestored {len(tables)} tables:")
    for t in tables:
        name = t["name"]
        count = conn.execute(f"SELECT COUNT(*) as c FROM [{name}]").fetchone()["c"]
        total_rows += count
        print(f"  {name:25s}  {count:>8,} rows")

    conn.close()
    db_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
    print(f"\nDone! {total_rows:,} total rows → {DB_PATH} ({db_mb:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description="Restore database from compressed snapshot")
    parser.add_argument("-i", "--input", default=DEFAULT_INPUT,
                        help=f"Input snapshot path (default: {DEFAULT_INPUT})")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing DB without prompting")
    args = parser.parse_args()
    load_db(args.input, args.force)


if __name__ == "__main__":
    main()
