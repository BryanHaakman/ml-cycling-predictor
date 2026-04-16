"""
SQLite-backed cache and data scraper for ProCyclingStats.

Scrapes race results, rider profiles, and race characteristics.
All data is cached in SQLite to avoid redundant requests.
Rate-limited to ~1 request/second.
"""

import sqlite3
import time
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeoutError
from datetime import datetime, date
from typing import Optional

from tqdm import tqdm
from procyclingstats import Race, Stage, Rider

_DATA_DIR = os.path.dirname(__file__)
_DEFAULT_DB = os.path.join(_DATA_DIR, "cache.db")
_SNAPSHOT = os.path.join(_DATA_DIR, "db_snapshot.sql.gz")


def _resolve_db_path() -> str:
  """Return the path to cache.db, restoring from snapshot on Vercel if needed."""
  if os.path.exists(_DEFAULT_DB):
    return _DEFAULT_DB

  # Serverless (Vercel): filesystem is read-only except /tmp.
  # Restore the gzipped snapshot there on cold start.
  if os.path.exists(_SNAPSHOT):
    import gzip
    tmp_db = "/tmp/cache.db"
    if not os.path.exists(tmp_db):
      with gzip.open(_SNAPSHOT, "rb") as src, open(tmp_db, "wb") as dst:
        while chunk := src.read(1024 * 1024):
          dst.write(chunk)
    return tmp_db

  return _DEFAULT_DB  # fallback — get_db will create an empty DB


DB_PATH = _resolve_db_path()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
_last_request_time = 0.0
REQUEST_DELAY = 0.5  # seconds between PCS requests
MAX_RETRIES = 3      # retry on server errors


def _rate_limit():
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)
    _last_request_time = time.time()


FETCH_TIMEOUT = 60  # seconds before we consider a request hung


class _FetchTimeout(Exception):
    pass


def _pcs_fetch(pcs_class, url, retries=MAX_RETRIES):
    """Fetch and parse a PCS page with automatic retry on server errors."""
    for attempt in range(retries):
        _rate_limit()
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(pcs_class, url)
                try:
                    return future.result(timeout=FETCH_TIMEOUT)
                except _FuturesTimeoutError:
                    backoff = REQUEST_DELAY * (attempt + 2)
                    log.warning(f"Request timed out on {url}, retrying in {backoff:.1f}s (attempt {attempt+1}/{retries})")
                    time.sleep(backoff)
                    continue
        except _FetchTimeout:
            continue
        except Exception as e:
            err_str = str(e)
            # Retry on server errors (500, 503, etc.) or Cloudflare blocks
            if any(code in err_str for code in ["500", "502", "503", "429", "Cloudflare"]):
                backoff = REQUEST_DELAY * (attempt + 2)
                log.warning(f"Server error ({err_str[:60]}) on {url}, retrying in {backoff:.1f}s (attempt {attempt+1}/{retries})")
                time.sleep(backoff)
                continue
            raise  # re-raise non-retryable errors
    # Final attempt — let it raise
    _rate_limit()
    return pcs_class(url)


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

def get_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _create_tables(conn)
    return conn


def _create_tables(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS races (
        url TEXT PRIMARY KEY,
        name TEXT,
        year INTEGER,
        nationality TEXT,
        is_one_day_race INTEGER,
        category TEXT,
        uci_tour TEXT,
        startdate TEXT,
        enddate TEXT,
        scraped_at TEXT
    );

    CREATE TABLE IF NOT EXISTS stages (
        url TEXT PRIMARY KEY,
        race_url TEXT,
        stage_name TEXT,
        date TEXT,
        distance REAL,
        vertical_meters REAL,
        profile_score REAL,
        profile_icon TEXT,
        avg_speed_winner REAL,
        avg_temperature REAL,
        departure TEXT,
        arrival TEXT,
        stage_type TEXT,
        is_one_day_race INTEGER,
        race_category TEXT,
        startlist_quality_score TEXT,
        pcs_points_scale TEXT,
        uci_points_scale TEXT,
        num_climbs INTEGER,
        climbs_json TEXT,
        scraped_at TEXT
    );

    CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stage_url TEXT NOT NULL,
        rider_url TEXT NOT NULL,
        rider_name TEXT,
        team_name TEXT,
        team_url TEXT,
        rank INTEGER,
        status TEXT,
        age INTEGER,
        nationality TEXT,
        time_str TEXT,
        bonus TEXT,
        pcs_points REAL,
        uci_points REAL,
        breakaway_kms REAL,
        UNIQUE(stage_url, rider_url)
    );

    CREATE TABLE IF NOT EXISTS riders (
        url TEXT PRIMARY KEY,
        name TEXT,
        nationality TEXT,
        birthdate TEXT,
        weight REAL,
        height REAL,
        specialty_one_day REAL,
        specialty_gc REAL,
        specialty_tt REAL,
        specialty_sprint REAL,
        specialty_climber REAL,
        specialty_hills REAL,
        points_history_json TEXT,
        scraped_at TEXT
    );

    CREATE TABLE IF NOT EXISTS scrape_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT,
        detail TEXT,
        timestamp TEXT DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_results_stage ON results(stage_url);
    CREATE INDEX IF NOT EXISTS idx_results_rider ON results(rider_url);
    CREATE INDEX IF NOT EXISTS idx_stages_race ON stages(race_url);
    CREATE INDEX IF NOT EXISTS idx_stages_date ON stages(date);
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Race calendar scraping
# ---------------------------------------------------------------------------

# Major race URLs to scrape calendars from. PCS uses this URL pattern for
# calendar pages listing all races in a year.
RACE_CALENDAR_URLS = {
    "worldtour": "races.php?year={year}&circuit=1&class=&filter=Filter",
    "proseries": "races.php?year={year}&circuit=2&class=&filter=Filter",
    "class1": "races.php?year={year}&circuit=&class=1.1&filter=Filter",
    "class2": "races.php?year={year}&circuit=&class=1.2&filter=Filter",
}

# Known major stage races and monuments (fallback if dynamic discovery fails)
MAJOR_RACES = [
    "race/tour-de-france",
    "race/giro-d-italia",
    "race/vuelta-a-espana",
    "race/paris-nice",
    "race/tirreno-adriatico",
    "race/volta-a-catalunya",
    "race/itzulia-basque-country",
    "race/tour-de-romandie",
    "race/criterium-du-dauphine",
    "race/tour-de-suisse",
    "race/tour-de-pologne",
    "race/milano-sanremo",
    "race/strade-bianche",
    "race/e3-harelbeke",
    "race/gent-wevelgem",
    "race/dwars-door-vlaanderen",
    "race/ronde-van-vlaanderen",
    "race/paris-roubaix",
    "race/amstel-gold-race",
    "race/la-fleche-wallonne",
    "race/liege-bastogne-liege",
    "race/clasica-ciclista-san-sebastian",
    "race/bretagne-classic",
    "race/cyclassics-hamburg",
    "race/gp-quebec",
    "race/gp-montreal",
    "race/il-lombardia",
    "race/tour-down-under",
    "race/uae-tour",
    "race/omloop-het-nieuwsblad",
    "race/paris-tours",
    "race/renewi-tour",
    "race/tour-de-wallonie",
    "race/deutschland-tour",
    "race/binckbank-tour",
]

# Substrings that indicate women's, junior, or U23 races — skip these
_EXCLUDE_PATTERNS = [
    "-we", "-wj", "-wu-", "women", "woman", "ladies", "lady",
    "feminin", "femina", "feminas", "féminin",
    "dames", "dame", "-mj", "junior", "juniores", "junioren", "u23", "u19",
    "ceratizit-festival",  # women's race series
]


def discover_races(year: int, tiers: list[str] = None) -> list[str]:
    """Discover race base URLs from PCS calendar pages for a given year.

    Args:
        year: Calendar year to discover races for.
        tiers: List of calendar tier keys from RACE_CALENDAR_URLS.
               Defaults to ["worldtour", "proseries"] for the top two tiers.
               Use ["worldtour", "proseries", "class1", "class2"] for all tiers.

    Returns:
        Sorted list of unique race base URLs (e.g., "race/tour-de-france").
    """
    import re
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper()
    except ImportError:
        log.warning("cloudscraper not installed — cannot discover races dynamically")
        return list(MAJOR_RACES)

    if tiers is None:
        tiers = ["worldtour", "proseries"]

    all_races = set()

    for tier in tiers:
        url_template = RACE_CALENDAR_URLS.get(tier)
        if not url_template:
            log.warning(f"Unknown tier: {tier}")
            continue

        url = f"https://www.procyclingstats.com/{url_template.format(year=year)}"
        _rate_limit()
        try:
            resp = scraper.get(url, timeout=30)
            if resp.status_code != 200:
                log.warning(f"Failed to fetch {tier} calendar for {year}: HTTP {resp.status_code}")
                continue

            # Extract all race hrefs
            links = re.findall(r'href="(race/[^"]+)"', resp.text)
            for link in links:
                # Get base URL like "race/tour-de-france" from "race/tour-de-france/2024/gc"
                parts = link.split("/")
                if len(parts) >= 2:
                    base = "/".join(parts[:2])
                    all_races.add(base)

            log.info(f"  {tier} {year}: found {len(links)} links → {len([r for r in all_races])} cumulative races")

        except Exception as e:
            log.warning(f"Error fetching {tier} calendar for {year}: {e}")
            continue

    # Filter out women's, junior, U23 races
    filtered = set()
    for race in all_races:
        race_lower = race.lower()
        if any(pat in race_lower for pat in _EXCLUDE_PATTERNS):
            continue
        filtered.add(race)

    # Always include the known major races as a safety net
    filtered.update(MAJOR_RACES)

    result = sorted(filtered)
    log.info(f"Discovered {len(result)} men's elite races for {year} (from {len(all_races)} total)")
    return result


def scrape_race_overview(conn: sqlite3.Connection, race_base_url: str, year: int) -> Optional[str]:
    """Scrape a race overview page and store in DB. Returns the race URL or None on failure."""
    race_url = f"{race_base_url}/{year}"

    existing = conn.execute("SELECT url FROM races WHERE url = ?", (race_url,)).fetchone()
    if existing:
        return race_url

    _rate_limit()
    try:
        race = _pcs_fetch(Race, race_url)
        try:
            data = race.parse()
        except (ValueError, TypeError) as parse_err:
            log.debug(f"Skipping {race_url}: incomplete data on PCS ({parse_err})")
            return None
        conn.execute("""
            INSERT OR REPLACE INTO races (url, name, year, nationality, is_one_day_race,
                category, uci_tour, startdate, enddate, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            race_url,
            data.get("name"),
            year,
            data.get("nationality"),
            1 if data.get("is_one_day_race") else 0,
            data.get("category"),
            data.get("uci_tour"),
            data.get("startdate"),
            data.get("enddate"),
            datetime.now().isoformat(),
        ))
        conn.commit()
        log.info(f"Scraped race overview: {race_url}")
        return race_url
    except Exception as e:
        log.warning(f"Failed to scrape race overview {race_url}: {e}")
        return None


def scrape_stage(conn: sqlite3.Connection, stage_url: str, race_url: str) -> bool:
    """Scrape a stage/one-day race result page. Returns True on success."""
    existing = conn.execute("SELECT url FROM stages WHERE url = ?", (stage_url,)).fetchone()
    if existing:
        return True

    _rate_limit()
    try:
        stage = _pcs_fetch(Stage, stage_url)
        try:
            data = stage.parse()
        except (ValueError, TypeError) as parse_err:
            # procyclingstats crashes on incomplete pages (e.g. float('-') for missing distance)
            log.debug(f"Skipping {stage_url}: incomplete data on PCS ({parse_err})")
            return False

        def _safe_float(val):
            """Convert to float, returning None for non-numeric values like '-'."""
            if val is None:
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        climbs = data.get("climbs", [])
        num_climbs = len(climbs) if climbs else 0
        climbs_json = json.dumps(climbs, default=str) if climbs else "[]"

        sq = data.get("race_startlist_quality_score")
        sq_str = json.dumps(sq, default=str) if sq else None

        conn.execute("""
            INSERT OR REPLACE INTO stages (url, race_url, stage_name, date, distance,
                vertical_meters, profile_score, profile_icon, avg_speed_winner,
                avg_temperature, departure, arrival, stage_type, is_one_day_race,
                race_category, startlist_quality_score, pcs_points_scale, uci_points_scale,
                num_climbs, climbs_json, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            stage_url, race_url,
            f"{data.get('departure', '')} → {data.get('arrival', '')}",
            data.get("date"),
            _safe_float(data.get("distance")),
            _safe_float(data.get("vertical_meters")),
            _safe_float(data.get("profile_score")),
            data.get("profile_icon"),
            _safe_float(data.get("avg_speed_winner")),
            _safe_float(data.get("avg_temperature")),
            data.get("departure"),
            data.get("arrival"),
            data.get("stage_type"),
            1 if data.get("is_one_day_race") else 0,
            data.get("race_category"),
            sq_str,
            data.get("pcs_points_scale"),
            data.get("uci_points_scale"),
            num_climbs, climbs_json,
            datetime.now().isoformat(),
        ))

        # Store results
        results = data.get("results", [])
        for r in results:
            rank = r.get("rank")
            if rank is None:
                continue
            conn.execute("""
                INSERT OR IGNORE INTO results (stage_url, rider_url, rider_name, team_name,
                    team_url, rank, status, age, nationality, time_str, bonus,
                    pcs_points, uci_points, breakaway_kms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                stage_url,
                r.get("rider_url"),
                r.get("rider_name"),
                r.get("team_name"),
                r.get("team_url"),
                rank,
                r.get("status"),
                r.get("age"),
                r.get("nationality"),
                r.get("time"),
                r.get("bonus"),
                _safe_float(r.get("pcs_points")),
                _safe_float(r.get("uci_points")),
                _safe_float(r.get("breakaway_kms")),
            ))

        conn.commit()
        log.info(f"Scraped stage: {stage_url} ({len(results)} results)")
        return True
    except Exception as e:
        log.warning(f"Failed to scrape stage {stage_url}: {e}")
        return False


def scrape_rider(conn: sqlite3.Connection, rider_url: str) -> bool:
    """Scrape a rider profile. Returns True on success."""
    existing = conn.execute("SELECT url FROM riders WHERE url = ?", (rider_url,)).fetchone()
    if existing:
        return True

    _rate_limit()
    try:
        rider = _pcs_fetch(Rider, rider_url)
        data = rider.parse()
        spec = data.get("points_per_speciality", {}) or {}
        pts_history = data.get("points_per_season_history", [])

        conn.execute("""
            INSERT OR REPLACE INTO riders (url, name, nationality, birthdate, weight, height,
                specialty_one_day, specialty_gc, specialty_tt, specialty_sprint,
                specialty_climber, specialty_hills, points_history_json, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rider_url,
            data.get("name"),
            data.get("nationality"),
            data.get("birthdate"),
            data.get("weight"),
            data.get("height"),
            spec.get("one_day_races"),
            spec.get("gc"),
            spec.get("time_trial"),
            spec.get("sprint"),
            spec.get("climber"),
            spec.get("hills"),
            json.dumps(pts_history, default=str),
            datetime.now().isoformat(),
        ))
        conn.commit()
        log.info(f"Scraped rider: {rider_url} ({data.get('name')})")
        return True
    except Exception as e:
        # Insert a stub record so we don't retry this rider every run
        log.debug(f"Rider parse failed for {rider_url}: {e} — inserting stub")
        try:
            conn.execute("""
                INSERT OR IGNORE INTO riders (url, name, scraped_at)
                VALUES (?, ?, ?)
            """, (rider_url, rider_url.split("/")[-1].replace("-", " ").title(),
                  datetime.now().isoformat()))
            conn.commit()
        except Exception:
            pass
        return False


def scrape_full_race(conn: sqlite3.Connection, race_base_url: str, year: int, force: bool = False):
    """Scrape a complete race: overview → stages → results → rider profiles.

    Skips races already fully scraped (logged in scrape_log) unless force=True.
    """
    # Resume support: skip if already completed
    if not force:
        done = conn.execute(
            "SELECT 1 FROM scrape_log WHERE action = 'race_done' AND detail = ?",
            (f"{race_base_url}/{year}",)
        ).fetchone()
        if done:
            log.debug(f"Skipping {race_base_url}/{year} (already scraped)")
            return

    race_url = scrape_race_overview(conn, race_base_url, year)
    if not race_url:
        return

    race_row = conn.execute("SELECT * FROM races WHERE url = ?", (race_url,)).fetchone()
    is_one_day = race_row["is_one_day_race"]

    if is_one_day:
        stage_url = f"{race_url}/result"
        scrape_stage(conn, stage_url, race_url)
    else:
        # Get stages from race overview
        _rate_limit()
        try:
            race = _pcs_fetch(Race, race_url)
            stages = race.stages()
            for s in stages:
                stage_url = s.get("stage_url")
                if stage_url:
                    scrape_stage(conn, stage_url, race_url)
        except Exception as e:
            log.warning(f"Failed to get stages for {race_url}: {e}")

    # Scrape rider profiles for all riders in results
    rider_urls = conn.execute("""
        SELECT DISTINCT r.rider_url FROM results r
        JOIN stages s ON r.stage_url = s.url
        WHERE s.race_url = ? AND r.rider_url NOT IN (SELECT url FROM riders)
    """, (race_url,)).fetchall()

    for row in rider_urls:
        scrape_rider(conn, row["rider_url"])

    # Mark race as fully scraped for resume support
    conn.execute(
        "INSERT INTO scrape_log (action, detail) VALUES (?, ?)",
        ("race_done", f"{race_base_url}/{year}")
    )
    conn.commit()


def scrape_years(years: list[int], db_path: str = DB_PATH, tiers: list[str] = None, force: bool = False):
    """Scrape races for given years. Uses dynamic discovery from PCS calendars.

    Args:
        years: List of years to scrape.
        db_path: Path to SQLite database.
        tiers: Calendar tiers to discover from. Defaults to ["worldtour", "proseries"].
               Use ["worldtour", "proseries", "class1", "class2"] for maximum coverage.
        force: If True, re-scrape races even if already completed.
    """
    conn = get_db(db_path)

    for year in years:
        log.info(f"=== Scraping year {year} ===")
        races = discover_races(year, tiers=tiers)
        log.info(f"Will scrape {len(races)} races for {year}")
        for race_base in tqdm(races, desc=f"Year {year}"):
            scrape_full_race(conn, race_base, year, force=force)
        conn.execute(
            "INSERT INTO scrape_log (action, detail) VALUES (?, ?)",
            ("scrape_year", f"year={year}")
        )
        conn.commit()

    conn.close()


def scrape_since_last(db_path: str = DB_PATH, tiers: list[str] = None):
    """Scrape new races since last scrape session. Designed to run periodically."""
    conn = get_db(db_path)

    last_log = conn.execute(
        "SELECT detail FROM scrape_log WHERE action='scrape_update' ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()

    if last_log:
        last_date = last_log["detail"]
    else:
        # Fall back to max date in stages
        row = conn.execute("SELECT MAX(date) as d FROM stages").fetchone()
        last_date = row["d"] if row and row["d"] else "2025-01-01"

    current_year = date.today().year
    log.info(f"Updating races since {last_date} for {current_year}")

    races = discover_races(current_year, tiers=tiers)
    for race_base in tqdm(races, desc="Updating"):
        race_url = f"{race_base}/{current_year}"
        existing_stages = conn.execute(
            "SELECT COUNT(*) as c FROM stages WHERE race_url = ?", (race_url,)
        ).fetchone()["c"]

        # Re-scrape if race exists but might have new stages
        race_row = conn.execute("SELECT * FROM races WHERE url = ?", (race_url,)).fetchone()
        if race_row:
            enddate = race_row["enddate"]
            if enddate and enddate >= last_date:
                # Race may have new results — delete cached stages and re-scrape
                log.info(f"Re-checking {race_url} (enddate {enddate} >= {last_date})")
                stage_urls = [r["url"] for r in conn.execute(
                    "SELECT url FROM stages WHERE race_url = ?", (race_url,)
                ).fetchall()]
                for surl in stage_urls:
                    conn.execute("DELETE FROM results WHERE stage_url = ?", (surl,))
                conn.execute("DELETE FROM stages WHERE race_url = ?", (race_url,))
                conn.execute("DELETE FROM races WHERE url = ?", (race_url,))
                conn.execute(
                    "DELETE FROM scrape_log WHERE action = 'race_done' AND detail = ?",
                    (race_url,)
                )
                conn.commit()
        else:
            # No race row but may have stale scrape_log entry — clear it
            conn.execute(
                "DELETE FROM scrape_log WHERE action = 'race_done' AND detail = ?",
                (race_url,)
            )
            conn.commit()

        scrape_full_race(conn, race_base, current_year)

    # Also check previous year if we're early in the season
    if date.today().month <= 3:
        prev_year = current_year - 1
        prev_races = discover_races(prev_year, tiers=tiers)
        for race_base in prev_races:
            scrape_full_race(conn, race_base, prev_year)

    conn.execute(
        "INSERT INTO scrape_log (action, detail) VALUES (?, ?)",
        ("scrape_update", date.today().isoformat())
    )
    conn.commit()
    conn.close()
    log.info("Update complete.")


def get_stats(db_path: str = DB_PATH) -> dict:
    """Get scraping statistics."""
    conn = get_db(db_path)
    stats = {}
    for table in ["races", "stages", "results", "riders"]:
        row = conn.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()
        stats[table] = row["c"]
    year_range = conn.execute("SELECT MIN(year) as mn, MAX(year) as mx FROM races").fetchone()
    stats["year_range"] = f"{year_range['mn']}-{year_range['mx']}" if year_range["mn"] else "N/A"
    conn.close()
    return stats
