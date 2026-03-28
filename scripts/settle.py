#!/usr/bin/env python3
"""
Settle pending bets by scraping results for stages with open bets.

This is useful after manually adding a stage — it will:
1. Find all pending bets
2. Scrape results for any stages missing results
3. Auto-settle bets where both riders have results

Usage:
    python scripts/settle.py              # scrape missing results + settle
    python scripts/settle.py --no-scrape  # settle only (results already in DB)
    python scripts/settle.py --status     # show pending bets without settling
"""

import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.scraper import get_db, scrape_stage
from data.pnl import auto_settle_from_results, get_pnl_db

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "cache.db")


def get_pending_bets():
    """Get all pending bets grouped by stage."""
    conn = get_pnl_db()
    bets = conn.execute(
        "SELECT * FROM bets WHERE status = 'pending' ORDER BY race_date, id"
    ).fetchall()
    conn.close()
    return bets


def scrape_missing_stages(bets):
    """Scrape results for stages that have pending bets but no results."""
    db = get_db()
    stage_urls = set(b["stage_url"] for b in bets)
    scraped = 0

    for stage_url in sorted(stage_urls):
        # Check if results already exist
        count = db.execute(
            "SELECT COUNT(*) as c FROM results WHERE stage_url = ?",
            (stage_url,)
        ).fetchone()["c"]

        if count > 0:
            continue

        # Get the race_url from the stage
        stage_row = db.execute(
            "SELECT race_url FROM stages WHERE url = ?", (stage_url,)
        ).fetchone()
        if not stage_row:
            # Derive race_url from stage_url (e.g. race/foo/2026/stage-1 -> race/foo/2026)
            parts = stage_url.rsplit("/", 1)
            race_url = parts[0] if len(parts) > 1 else stage_url
        else:
            race_url = stage_row["race_url"]

        print(f"  Scraping results for {stage_url}...")
        try:
            scrape_stage(db, stage_url, race_url)
            new_count = db.execute(
                "SELECT COUNT(*) as c FROM results WHERE stage_url = ?",
                (stage_url,)
            ).fetchone()["c"]
            print(f"    → {new_count} results")
            scraped += 1
        except Exception as e:
            print(f"    → Failed: {e}")

    return scraped


def print_status(bets):
    """Print summary of pending bets."""
    db = get_db()
    by_race = {}
    for b in bets:
        key = b["race_name"]
        if key not in by_race:
            by_race[key] = []
        by_race[key].append(b)

    for race, race_bets in by_race.items():
        stage_url = race_bets[0]["stage_url"]
        result_count = db.execute(
            "SELECT COUNT(*) as c FROM results WHERE stage_url = ?",
            (stage_url,)
        ).fetchone()["c"]

        status = f"✅ {result_count} results" if result_count > 0 else "⏳ no results"
        print(f"\n  {race} ({status})")
        for b in race_bets:
            print(f"    #{b['id']:>3}: {b['selection_name']:<25} "
                  f"@ {b['decimal_odds']:.2f}  £{b['stake']:.2f}")

    db.close()


def main():
    parser = argparse.ArgumentParser(description="Settle pending bets")
    parser.add_argument("--no-scrape", action="store_true",
                        help="Don't scrape — only settle from existing results")
    parser.add_argument("--status", action="store_true",
                        help="Show pending bets without settling")
    args = parser.parse_args()

    bets = get_pending_bets()
    if not bets:
        print("No pending bets.")
        return

    print(f"Found {len(bets)} pending bet(s)")
    print_status(bets)

    if args.status:
        return

    if not args.no_scrape:
        print(f"\nScraping missing results...")
        scraped = scrape_missing_stages(bets)
        if scraped:
            print(f"  Scraped {scraped} stage(s)")
        else:
            print("  All stages already have results")

    print(f"\nAuto-settling...")
    settled = auto_settle_from_results()
    if settled:
        print(f"✅ Settled {settled} bet(s)")
    else:
        print("No bets could be settled (results may be missing)")

    # Show remaining pending
    remaining = get_pending_bets()
    if remaining:
        print(f"\n{len(remaining)} bet(s) still pending:")
        print_status(remaining)


if __name__ == "__main__":
    main()
