#!/usr/bin/env python3
"""Scrape races from 2018-2026.

By default scrapes WorldTour + ProSeries races (dynamically discovered from
PCS calendar pages).  Use --all-tiers to also include Class 1 and Class 2
races for maximum coverage, or --major-only to use the hardcoded 35-race list.

Examples:
    python scripts/scrape_all.py                    # WT + ProSeries (~80 races/year)
    python scripts/scrape_all.py --all-tiers        # WT + Pro + Class1 + Class2 (~200+ races/year)
    python scripts/scrape_all.py --major-only       # Only the 35 hardcoded major races
    python scripts/scrape_all.py --years 2024 2025  # Only specific years
"""

import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.scraper import scrape_years, get_stats

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape cycling race data from ProCyclingStats")
    parser.add_argument("--years", nargs="+", type=int, default=list(range(2026, 2017, -1)),
                        help="Years to scrape (default: 2026-2018, newest first)")
    parser.add_argument("--all-tiers", action="store_true",
                        help="Scrape all tiers: WorldTour + ProSeries + Class 1 + Class 2")
    parser.add_argument("--major-only", action="store_true",
                        help="Only scrape the 35 hardcoded major races (no dynamic discovery)")
    parser.add_argument("--force", action="store_true",
                        help="Re-scrape races even if already completed (ignore resume log)")
    args = parser.parse_args()

    if args.major_only:
        tiers = []  # empty = skip discovery, fallback to MAJOR_RACES
    elif args.all_tiers:
        tiers = ["worldtour", "proseries", "class1", "class2"]
    else:
        tiers = ["worldtour", "proseries"]

    # When major-only, pass None to use old MAJOR_RACES list behavior
    tier_arg = tiers if tiers else None

    print(f"Scraping years: {args.years}")
    if args.major_only:
        print("Mode: major-only (35 hardcoded races)")
    elif args.all_tiers:
        print("Mode: all-tiers (WorldTour + ProSeries + Class 1 + Class 2 — ~200+ races/year)")
    else:
        print("Mode: default (WorldTour + ProSeries — ~80 races/year)")
    if args.force:
        print("Force mode: re-scraping all races (ignoring resume log)")
    else:
        print("Resume mode: skipping already-scraped races (use --force to re-scrape)")
    print("This will take a while (rate-limited to ~1.2 req/sec)...")

    scrape_years(args.years, tiers=tier_arg, force=args.force)
    stats = get_stats()
    print(f"\nDone! Stats: {stats}")
