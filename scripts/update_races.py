#!/usr/bin/env python3
"""Update races since last scrape. Run periodically (e.g. weekly cron).

Examples:
    python scripts/update_races.py                 # WT + ProSeries
    python scripts/update_races.py --all-tiers     # All tiers
"""

import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.scraper import scrape_since_last, get_stats

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Incremental race data update")
    parser.add_argument("--all-tiers", action="store_true",
                        help="Discover from all tiers (WT + Pro + Class1 + Class2)")
    args = parser.parse_args()

    tiers = ["worldtour", "proseries", "class1", "class2"] if args.all_tiers else None

    print("Updating races since last scrape...")
    scrape_since_last(tiers=tiers)
    stats = get_stats()
    print(f"\nDone! Stats: {stats}")
