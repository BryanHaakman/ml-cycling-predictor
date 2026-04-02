#!/usr/bin/env python3
"""Dump the full SQLite database to a compressed file.

Usage:
    python scripts/dump_db.py                       # → data/db_snapshot.sql.gz
    python scripts/dump_db.py -o backup.sql.gz      # custom output path
"""

import sys
import os
import gzip
import sqlite3
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.scraper import get_db

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUT = os.path.join(PROJECT_ROOT, "data", "db_snapshot.sql.gz")


def dump_db(output_path: str) -> None:
    conn = get_db()

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [t["name"] for t in tables]

    row_counts = {}
    for name in table_names:
        count = conn.execute(f"SELECT COUNT(*) as c FROM [{name}]").fetchone()["c"]
        row_counts[name] = count

    # Checkpoint WAL so all data is in the main DB file
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    db_path = conn.execute("PRAGMA database_list").fetchone()["file"]
    conn.close()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(db_path, "rb") as f_in, gzip.open(output_path, "wb", compresslevel=6) as f_out:
        while chunk := f_in.read(1024 * 1024):
            f_out.write(chunk)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    total_rows = sum(row_counts.values())

    print(f"Dumped {total_rows:,} rows across {len(table_names)} tables:")
    for name in table_names:
        print(f"  {name:25s}  {row_counts[name]:>8,} rows")
    print(f"\nOutput: {output_path} ({size_mb:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description="Dump database to compressed file")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT,
                        help=f"Output path (default: {DEFAULT_OUTPUT})")
    args = parser.parse_args()
    dump_db(args.output)


if __name__ == "__main__":
    main()
