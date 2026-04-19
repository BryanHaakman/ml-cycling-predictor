#!/usr/bin/env python3
"""Scrape Pinnacle cycling H2H odds and store market snapshots.

Examples:
    python scripts/scrape_odds.py            # headless (VPS cron default)
    python scripts/scrape_odds.py --headed   # show browser (local debug)
    python scripts/scrape_odds.py --closing  # closing-odds capture for CLV
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from data.pinnacle_scraper import scrape_cycling_markets, save_snapshot

if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="Scrape Pinnacle cycling H2H odds")
  parser.add_argument("--headed", action="store_true",
                      help="Show browser window (local debug mode)")
  parser.add_argument("--closing", action="store_true",
                      help="Tag snapshot as closing odds (for CLV computation)")
  args = parser.parse_args()

  snapshot_type = "closing" if args.closing else "manual"
  snapshots = scrape_cycling_markets(headed=args.headed, snapshot_type=snapshot_type)
  save_snapshot(snapshots)
  print(f"Saved {len(snapshots)} snapshots (type={snapshot_type})")
