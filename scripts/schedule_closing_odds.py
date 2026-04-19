#!/usr/bin/env python3
"""Schedule closing-odds captures at race start times.

Reads start times from the latest market snapshots, then triggers
closing-odds scrapes at each race start time. Designed for VPS cron:

    # Daily at midnight EST: schedule today's closing-odds captures
    0 0 * * * cd /path/to/ml-cycling-predictor && python scripts/schedule_closing_odds.py

Can also be run manually for testing:
    python scripts/schedule_closing_odds.py --dry-run
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import subprocess
import time
import logging
from datetime import datetime, timedelta

from data.pinnacle_scraper import get_upcoming_start_times

log = logging.getLogger("schedule_closing_odds")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def schedule_closing_scrapes(dry_run: bool = False) -> int:
  """Read start times from snapshots and trigger closing-odds scrapes.

  Iterates through upcoming race start times, sleeps until each one,
  then triggers a closing-odds scrape via subprocess. Races already
  past (> 5 min ago) are skipped.

  Args:
    dry_run: If True, show schedule without triggering scrapes.

  Returns:
    The number of scrapes triggered.
  """
  start_times = get_upcoming_start_times()
  if not start_times:
    log.info("No upcoming races found in snapshots. Nothing to schedule.")
    return 0

  # Deduplicate by (start_date, start_time) — multiple matchups share the same start
  unique_times: dict[tuple[str, str], str] = {}
  for st in start_times:
    key = (st["start_date"], st["start_time"])
    if key not in unique_times:
      unique_times[key] = st["race_name"]

  log.info("Found %d unique start times to schedule", len(unique_times))
  triggered = 0
  script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scrape_odds.py")

  for (start_date, start_time_str), race_name in sorted(unique_times.items()):
    if not start_date or not start_time_str:
      log.warning("Skipping %s: missing date or time", race_name)
      continue

    try:
      # Parse "HH:MM" start time on the given date (EST)
      target = datetime.strptime(f"{start_date} {start_time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
      log.warning("Skipping %s: unparseable time '%s %s'", race_name, start_date, start_time_str)
      continue

    now = datetime.now()
    wait_seconds = (target - now).total_seconds()

    if wait_seconds < -300:
      log.info("Skipping %s at %s %s — already past", race_name, start_date, start_time_str)
      continue

    # If within 5 min of start or slightly past, trigger immediately
    if wait_seconds <= 0:
      wait_seconds = 0

    log.info("Scheduled: %s at %s %s (in %.0fs)", race_name, start_date, start_time_str, wait_seconds)

    if dry_run:
      log.info("  [DRY RUN] Would sleep %.0fs then scrape closing odds", wait_seconds)
      triggered += 1
      continue

    if wait_seconds > 0:
      log.info("  Sleeping %.0fs until %s...", wait_seconds, start_time_str)
      time.sleep(wait_seconds)

    log.info("  Triggering closing-odds scrape for %s...", race_name)
    try:
      result = subprocess.run(
        [sys.executable, script_path, "--closing"],
        capture_output=True, text=True, timeout=300
      )
      if result.returncode == 0:
        log.info("  Closing-odds scrape complete: %s", result.stdout.strip())
        triggered += 1
      else:
        log.error("  Scrape failed (rc=%d): %s", result.returncode, result.stderr.strip())
    except subprocess.TimeoutExpired:
      log.error("  Scrape timed out for %s", race_name)
    except Exception as e:
      log.error("  Scrape error for %s: %s", race_name, e)

  log.info("Done. Triggered %d closing-odds scrapes.", triggered)
  return triggered


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="Schedule closing-odds captures at race start times")
  parser.add_argument("--dry-run", action="store_true",
                      help="Show schedule without triggering scrapes")
  args = parser.parse_args()
  schedule_closing_scrapes(dry_run=args.dry_run)
