"""
Pinnacle cycling H2H market scraper (Playwright).

Replaces the broken guest API client (data/odds.py) with a headless browser
scraper that navigates Pinnacle.ca's React SPA, extracts H2H cycling matchups
with American odds, converts to decimal, and stores snapshots in SQLite.

Two-level scrape:
  1. Leagues index -> discover active cycling races
  2. Each race matchups page -> extract rider names, odds, start times

Public interface:
  - MatchupSnapshot        — dataclass with decimal odds per H2H matchup
  - PinnacleScrapeError    — raised when scraping fails unrecoverably
  - scrape_cycling_markets() — main entry point; returns list[MatchupSnapshot]
  - save_snapshot()        — persist snapshots to market_snapshots table
  - parse_american_odds()  — parse American odds string to decimal
  - _american_to_decimal() — convert numeric American odds to decimal
  - get_upcoming_start_times() — query upcoming race start times from snapshots
"""

import dataclasses
import json
import logging
import os
import re
import time
import random
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from playwright.sync_api import sync_playwright, Page

from data.scraper import get_db, DB_PATH

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PINNACLE_BASE_URL: str = "https://www.pinnacle.ca"
PINNACLE_LEAGUES_URL: str = "https://www.pinnacle.ca/en/cycling/leagues/"
REQUEST_TIMEOUT: int = 30000  # ms for Playwright
SCRAPE_DELAY_MIN: float = 1.0
SCRAPE_DELAY_MAX: float = 2.0
MAX_RETRIES: int = 3
SCRAPE_LOG_PATH: str = os.path.join(os.path.dirname(__file__), "scrape_log.jsonl")

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PinnacleScrapeError(Exception):
  """Raised when scraping fails unrecoverably."""
  pass


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class MatchupSnapshot:
  """A single H2H cycling matchup snapshot with normalized decimal odds.

  Odds are always decimal (never American) — conversion happens inside
  the scraper before any MatchupSnapshot is created.
  """
  rider_a_name: str
  rider_b_name: str
  odds_a: float          # decimal odds
  odds_b: float          # decimal odds
  race_name: str
  race_slug: str
  start_time: Optional[str]   # HH:MM EST from Pinnacle
  start_date: Optional[str]   # YYYY-MM-DD resolved from date bar
  snapshot_type: str = "manual"   # "manual" or "closing"
  source_url: str = ""


# ---------------------------------------------------------------------------
# Odds conversion
# ---------------------------------------------------------------------------

def _american_to_decimal(american: int | float) -> float:
  """Convert American odds to decimal format.

  Args:
    american: American odds value (e.g., +160, -231, or -154.5).

  Returns:
    Decimal odds rounded to 4 decimal places.

  Raises:
    ValueError: If american is 0.
  """
  if american == 0:
    raise ValueError("American odds of 0 are invalid")
  if american > 0:
    return round(american / 100.0 + 1.0, 4)
  return round(100.0 / abs(american) + 1.0, 4)


def parse_american_odds(text: str) -> float | None:
  """Parse American odds string from Pinnacle DOM to decimal odds.

  Handles formats: '-231', '+160', '-102', 'EV', empty string.
  Returns None if unparseable.

  Args:
    text: Raw odds string from the DOM element.

  Returns:
    Decimal odds as float, or None if the string cannot be parsed.
  """
  text = text.strip()
  if not text:
    return None
  if text == "EV":
    return 2.0
  match = re.match(r'^([+-]?\d+\.?\d*)$', text)
  if not match:
    return None
  american = float(match.group(1))
  if american == 0:
    return None
  if american > 0:
    return round(american / 100.0 + 1.0, 4)
  return round(100.0 / abs(american) + 1.0, 4)


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------

def _navigate_with_retry(page: Page, url: str, max_retries: int = MAX_RETRIES) -> bool:
  """Navigate to a URL with exponential backoff on failure.

  Returns True on success, False after all retries exhausted.

  Args:
    page: Playwright Page object.
    url: URL to navigate to.
    max_retries: Maximum number of attempts.

  Returns:
    True if navigation succeeded, False otherwise.
  """
  delay = 2.0
  for attempt in range(max_retries):
    try:
      page.goto(url, wait_until="networkidle", timeout=REQUEST_TIMEOUT)
      return True
    except Exception as e:
      log.warning("_navigate_with_retry: attempt %d failed for %s: %s", attempt + 1, url, e)
      if attempt < max_retries - 1:
        time.sleep(delay)
        delay *= 2.0  # exponential backoff
  log.error("_navigate_with_retry: all %d retries exhausted for %s", max_retries, url)
  return False


def _resolve_date_from_bar(bar_text: str) -> str:
  """Convert date bar text to YYYY-MM-DD format.

  Handles 'TODAY', 'TOMORROW', and date strings. Defaults to today
  if the text is unparseable.

  Args:
    bar_text: Text from the date bar element (e.g., 'TODAY', 'TOMORROW').

  Returns:
    Date string in YYYY-MM-DD format.
  """
  bar_text = bar_text.strip().upper()
  today = datetime.now()
  if bar_text == "TODAY":
    return today.strftime("%Y-%m-%d")
  if bar_text == "TOMORROW":
    return (today + timedelta(days=1)).strftime("%Y-%m-%d")
  # Try to parse common date formats
  for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
    try:
      return datetime.strptime(bar_text, fmt).strftime("%Y-%m-%d")
    except ValueError:
      continue
  # Default to today if unparseable
  log.warning("_resolve_date_from_bar: could not parse '%s', defaulting to today", bar_text)
  return today.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Scraping functions
# ---------------------------------------------------------------------------

def _discover_races(page: Page) -> list[tuple[str, str]]:
  """Discover active cycling races from the Pinnacle leagues page.

  Navigates to PINNACLE_LEAGUES_URL, waits for the leagues container,
  and extracts all race links with their slugs.

  Args:
    page: Playwright Page object.

  Returns:
    List of (race_slug, race_name) tuples.
  """
  if not _navigate_with_retry(page, PINNACLE_LEAGUES_URL):
    return []

  try:
    page.wait_for_selector(
      '[data-test-id="Browse-Leagues"], [data-test-id="Leagues-Container-AllLeagues"]',
      timeout=15000,
    )
  except Exception as e:
    log.warning("_discover_races: leagues container not found: %s", e)
    return []

  links = page.query_selector_all('a[href*="/cycling/"][href*="/matchups/"]')
  races: list[tuple[str, str]] = []
  for link in links:
    href = link.get_attribute("href")
    if not href:
      continue
    # Extract slug from href pattern: /en/cycling/{slug}/matchups/
    slug_match = re.search(r'/cycling/([^/]+)/matchups/', href)
    if not slug_match:
      continue
    slug = slug_match.group(1)
    # Race name from link text — strip trailing number (matchup count)
    raw_name = link.inner_text().strip()
    race_name = re.sub(r'\s+\d+\s*$', '', raw_name).strip()
    races.append((slug, race_name))

  # Anti-bot delay
  time.sleep(random.uniform(SCRAPE_DELAY_MIN, SCRAPE_DELAY_MAX))
  return races


def _scrape_race_matchups(page: Page, race_slug: str, race_name: str) -> list[MatchupSnapshot]:
  """Scrape H2H matchups from a race matchups page.

  Navigates to the race matchups URL, waits for content to render,
  then extracts rider names, start times, and odds from the DOM.
  American odds are converted to decimal before creating MatchupSnapshot.

  Args:
    page: Playwright Page object.
    race_slug: URL slug for the race (e.g., 'amstel-gold-race').
    race_name: Display name for the race.

  Returns:
    List of MatchupSnapshot objects with decimal odds.
  """
  url = f"{PINNACLE_BASE_URL}/en/cycling/{race_slug}/matchups/"
  if not _navigate_with_retry(page, url):
    return []

  try:
    page.wait_for_selector('[class*=matchupMetadata]', timeout=15000)
  except Exception as e:
    log.warning("_scrape_race_matchups: no matchup metadata found for %s: %s", race_name, e)
    return []

  # Resolve date from date bar
  date_bars = page.query_selector_all('[data-test-id="Events.DateBar"]')
  current_date = _resolve_date_from_bar(
    date_bars[0].inner_text().strip() if date_bars else "TODAY"
  )

  # Extract matchup metadata (rider names + start times)
  metadata_els = page.query_selector_all('[class*=matchupMetadata]')
  matchup_data: list[dict] = []
  for el in metadata_els:
    names = el.query_selector_all('[class*=gameInfoLabel] span')
    time_el = el.query_selector('[class*=matchupDate]')
    if len(names) >= 2:
      matchup_data.append({
        'rider_a': names[0].inner_text().strip(),
        'rider_b': names[1].inner_text().strip(),
        'start_time': time_el.inner_text().strip() if time_el else None,
      })

  # Extract odds from moneyline buttons
  moneyline_els = page.query_selector_all('[data-test-id="moneyline"]')
  # Filter out header rows
  odds_rows = [
    el for el in moneyline_els
    if el.inner_text().strip() not in ('MONEY LINE', '')
  ]
  for i, odds_el in enumerate(odds_rows):
    btns = odds_el.query_selector_all('.market-btn')
    if len(btns) >= 2 and i < len(matchup_data):
      matchup_data[i]['odds_a_text'] = btns[0].inner_text().strip()
      matchup_data[i]['odds_b_text'] = btns[1].inner_text().strip()

  # Build MatchupSnapshot list
  snapshots: list[MatchupSnapshot] = []
  for m in matchup_data:
    odds_a = parse_american_odds(m.get('odds_a_text', ''))
    odds_b = parse_american_odds(m.get('odds_b_text', ''))
    if odds_a is None or odds_b is None:
      log.warning(
        "_scrape_race_matchups: skipping %s vs %s — unparseable odds",
        m.get('rider_a', '?'), m.get('rider_b', '?'),
      )
      continue
    snapshots.append(MatchupSnapshot(
      rider_a_name=m['rider_a'],
      rider_b_name=m['rider_b'],
      odds_a=odds_a,
      odds_b=odds_b,
      race_name=race_name,
      race_slug=race_slug,
      start_time=m.get('start_time'),
      start_date=current_date,
      source_url=url,
    ))

  # Anti-bot delay
  time.sleep(random.uniform(SCRAPE_DELAY_MIN, SCRAPE_DELAY_MAX))
  return snapshots


def scrape_cycling_markets(headed: bool = False, snapshot_type: str = "manual") -> list[MatchupSnapshot]:
  """Scrape all cycling H2H markets from Pinnacle.ca.

  Main entry point. Launches a Playwright Chromium browser, discovers
  all active cycling races, then scrapes matchups from each race page.
  Each race failure is logged and skipped — never crashes the pipeline.

  Args:
    headed: If True, show the browser window (local debug mode).
    snapshot_type: Tag for snapshots — 'manual' or 'closing'.

  Returns:
    List of MatchupSnapshot objects. Empty list if no markets found
    or on persistent failure.
  """
  snapshots: list[MatchupSnapshot] = []
  with sync_playwright() as p:
    browser = p.chromium.launch(headless=not headed)
    try:
      page = browser.new_page()
      # Level 1: discover race slugs
      race_slugs = _discover_races(page)
      log.info("scrape_cycling_markets: discovered %d races", len(race_slugs))
      # Level 2: scrape each race
      for slug, race_name in race_slugs:
        try:
          new_snaps = _scrape_race_matchups(page, slug, race_name)
          snapshots.extend(new_snaps)
        except Exception as e:
          log.warning("scrape_cycling_markets: failed for %s: %s", race_name, e)
          # Degrade gracefully — continue with next race
    finally:
      browser.close()

  # Set snapshot_type on all snapshots
  for s in snapshots:
    s.snapshot_type = snapshot_type

  _append_audit_log(snapshots, "ok" if snapshots else "empty")
  return snapshots


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def _append_audit_log(
  snapshots: list,
  fetch_status: str,
  error: Optional[str] = None,
) -> None:
  """Append one JSONL record to SCRAPE_LOG_PATH after every scrape.

  Record is always written — including empty scrapes.

  Args:
    snapshots: List of MatchupSnapshot objects (may be empty).
    fetch_status: One of 'ok', 'empty', or 'error'.
    error: Optional error message string.
  """
  record: dict = {
    "scraped_at": datetime.now(timezone.utc).isoformat(),
    "status": fetch_status,
    "snapshot_count": len(snapshots),
  }
  if error is not None:
    record["error"] = error
  try:
    with open(SCRAPE_LOG_PATH, "a", encoding="utf-8") as f:
      f.write(json.dumps(record) + "\n")
  except OSError as e:
    log.warning("_append_audit_log: could not write to %s: %s", SCRAPE_LOG_PATH, e)


# ---------------------------------------------------------------------------
# SQLite snapshot storage
# ---------------------------------------------------------------------------

def _create_snapshot_table(conn) -> None:
  """Create market_snapshots table if it doesn't exist.

  Idempotent — safe to call multiple times. Creates indexes for
  common query patterns (by date, race, rider pair).

  Args:
    conn: SQLite connection from get_db().
  """
  conn.executescript("""
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
    );

    CREATE INDEX IF NOT EXISTS idx_snapshots_date ON market_snapshots(captured_at);
    CREATE INDEX IF NOT EXISTS idx_snapshots_race ON market_snapshots(race_name);
    CREATE INDEX IF NOT EXISTS idx_snapshots_riders ON market_snapshots(rider_a_name, rider_b_name);
  """)


def save_snapshot(snapshots: list[MatchupSnapshot], db_path: str = DB_PATH) -> None:
  """Persist a list of MatchupSnapshot records to market_snapshots table.

  Computes implied probabilities from odds before inserting. Uses
  parameterized queries to prevent SQL injection from scraped strings.

  Args:
    snapshots: List of MatchupSnapshot objects to persist.
    db_path: Path to the SQLite database (default: cache.db).
  """
  conn = get_db(db_path)
  _create_snapshot_table(conn)
  for s in snapshots:
    implied_prob_a = 1.0 / s.odds_a if s.odds_a > 0 else None
    implied_prob_b = 1.0 / s.odds_b if s.odds_b > 0 else None
    conn.execute("""
      INSERT INTO market_snapshots
        (race_name, race_slug, rider_a_name, rider_b_name, odds_a, odds_b,
         implied_prob_a, implied_prob_b, start_time, start_date,
         snapshot_type, source_url)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
      s.race_name, s.race_slug, s.rider_a_name, s.rider_b_name,
      s.odds_a, s.odds_b, implied_prob_a, implied_prob_b,
      s.start_time, s.start_date, s.snapshot_type, s.source_url,
    ))
  conn.commit()
  conn.close()


def get_upcoming_start_times(db_path: str = DB_PATH) -> list[dict]:
  """Query upcoming race start times from the latest manual snapshot.

  Returns distinct (start_date, start_time) pairs where start_date
  is today or later. Used by schedule_closing_odds.py to schedule
  closing-odds captures.

  Args:
    db_path: Path to the SQLite database (default: cache.db).

  Returns:
    List of dicts with keys: start_date, start_time, race_name.
  """
  conn = get_db(db_path)
  _create_snapshot_table(conn)
  today = datetime.now().strftime("%Y-%m-%d")
  rows = conn.execute("""
    SELECT DISTINCT start_date, start_time, race_name
    FROM market_snapshots
    WHERE snapshot_type = 'manual'
      AND start_date >= ?
      AND start_time IS NOT NULL
      AND start_date IS NOT NULL
    ORDER BY start_date, start_time
  """, (today,)).fetchall()
  conn.close()
  return [
    {"start_date": row["start_date"], "start_time": row["start_time"], "race_name": row["race_name"]}
    for row in rows
  ]
