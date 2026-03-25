#!/usr/bin/env python3
"""Export all database tables to CSV files for backup/portability.

Usage:
    python scripts/export_data.py                  # export to data/exports/
    python scripts/export_data.py -o ~/backups     # custom output directory
    python scripts/export_data.py --tables races stages  # specific tables only
"""

import sys
import os
import csv
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.scraper import get_db

TABLES = ["races", "stages", "results", "riders", "scrape_log"]


def export_table(conn, table_name: str, output_dir: str) -> int:
    """Export a single table to CSV. Returns row count."""
    cursor = conn.execute(f"SELECT * FROM {table_name}")
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()

    path = os.path.join(output_dir, f"{table_name}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row[c] for c in columns])

    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="Export database tables to CSV")
    parser.add_argument("-o", "--output", default=None,
                        help="Output directory (default: data/exports/YYYYMMDD_HHMMSS)")
    parser.add_argument("--tables", nargs="+", default=TABLES,
                        help=f"Tables to export (default: {' '.join(TABLES)})")
    args = parser.parse_args()

    if args.output:
        output_dir = args.output
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "exports", timestamp
        )

    os.makedirs(output_dir, exist_ok=True)

    conn = get_db()
    total = 0
    print(f"Exporting to: {output_dir}\n")

    for table in args.tables:
        try:
            count = export_table(conn, table, output_dir)
            total += count
            size = os.path.getsize(os.path.join(output_dir, f"{table}.csv"))
            print(f"  {table:15s}  {count:>8,} rows  ({size / 1024:.1f} KB)")
        except Exception as e:
            print(f"  {table:15s}  ERROR: {e}")

    conn.close()
    print(f"\nDone! {total:,} total rows exported to {output_dir}")

    # Always update data/exports/latest/ for git tracking
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    latest_dir = os.path.join(project_root, "data", "exports", "latest")
    if os.path.abspath(output_dir) != os.path.abspath(latest_dir):
        import shutil
        if os.path.exists(latest_dir):
            shutil.rmtree(latest_dir)
        shutil.copytree(output_dir, latest_dir)
        print(f"Updated data/exports/latest/")


if __name__ == "__main__":
    main()
