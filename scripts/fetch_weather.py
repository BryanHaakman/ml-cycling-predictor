#!/usr/bin/env python3
"""
Fetch historical weather data for all stages using Open-Meteo API.

Pipeline:
1. Geocode departure cities using Nominatim (OpenStreetMap)
2. Fetch historical weather from Open-Meteo archive API
3. Store results in cache.db weather tables

Both APIs are free and require no API key.
"""

import os
import sys
import json
import time
import logging
import sqlite3
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from data.scraper import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ISO country code mapping for nationality field from PCS
NATIONALITY_TO_COUNTRY = {
    "FR": "France", "IT": "Italy", "ES": "Spain", "BE": "Belgium",
    "NL": "Netherlands", "DE": "Germany", "GB": "United Kingdom",
    "CH": "Switzerland", "AT": "Austria", "PT": "Portugal",
    "AU": "Australia", "US": "United States", "CO": "Colombia",
    "SL": "Slovenia", "DK": "Denmark", "NO": "Norway", "PL": "Poland",
    "CZ": "Czech Republic", "IE": "Ireland", "LU": "Luxembourg",
    "HR": "Croatia", "SK": "Slovakia", "HU": "Hungary", "CN": "China",
    "JP": "Japan", "KZ": "Kazakhstan", "SA": "Saudi Arabia",
    "AE": "United Arab Emirates", "OM": "Oman", "RW": "Rwanda",
    "MA": "Morocco", "ET": "Ethiopia", "ER": "Eritrea",
    "SE": "Sweden", "FI": "Finland", "CA": "Canada", "AR": "Argentina",
    "UY": "Uruguay", "EC": "Ecuador", "MN": "Mongolia",
}


def _init_tables(conn):
    """Create weather-related tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS geocoded_cities (
            city TEXT NOT NULL,
            country TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            display_name TEXT,
            geocoded_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (city, country)
        );

        CREATE TABLE IF NOT EXISTS stage_weather (
            stage_url TEXT PRIMARY KEY,
            temperature_max REAL,
            temperature_min REAL,
            precipitation_mm REAL,
            wind_speed_max_kmh REAL,
            humidity_mean_pct REAL,
            fetched_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (stage_url) REFERENCES stages(url)
        );
    """)
    conn.commit()


def geocode_cities(conn):
    """Geocode all unique departure cities."""
    _init_tables(conn)

    # Get cities we still need to geocode
    rows = conn.execute("""
        SELECT DISTINCT s.departure, r.nationality
        FROM stages s
        JOIN races r ON s.race_url = r.url
        WHERE s.departure IS NOT NULL AND s.departure != ''
        AND NOT EXISTS (
            SELECT 1 FROM geocoded_cities g
            WHERE g.city = s.departure AND g.country = r.nationality
        )
    """).fetchall()

    if not rows:
        log.info("All cities already geocoded")
        return

    log.info(f"Geocoding {len(rows)} cities...")
    geolocator = Nominatim(user_agent="cycling-predictor-weather", timeout=10)

    for i, row in enumerate(rows):
        city = row["departure"]
        nationality = row["nationality"]
        country = NATIONALITY_TO_COUNTRY.get(nationality, "")

        query = f"{city}, {country}" if country else city

        try:
            location = geolocator.geocode(query)
            if location:
                conn.execute(
                    "INSERT OR REPLACE INTO geocoded_cities (city, country, latitude, longitude, display_name) VALUES (?, ?, ?, ?, ?)",
                    (city, nationality, location.latitude, location.longitude, location.address),
                )
            else:
                # Try without country
                location = geolocator.geocode(city)
                if location:
                    conn.execute(
                        "INSERT OR REPLACE INTO geocoded_cities (city, country, latitude, longitude, display_name) VALUES (?, ?, ?, ?, ?)",
                        (city, nationality, location.latitude, location.longitude, location.address),
                    )
                else:
                    log.warning(f"  Could not geocode: {query}")
                    conn.execute(
                        "INSERT OR REPLACE INTO geocoded_cities (city, country, latitude, longitude) VALUES (?, ?, NULL, NULL)",
                        (city, nationality),
                    )
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            log.warning(f"  Geocoder error for {query}: {e}")
            conn.execute(
                "INSERT OR REPLACE INTO geocoded_cities (city, country, latitude, longitude) VALUES (?, ?, NULL, NULL)",
                (city, nationality),
            )

        if (i + 1) % 50 == 0:
            conn.commit()
            log.info(f"  Geocoded {i + 1}/{len(rows)}")

        time.sleep(1.1)  # Nominatim rate limit: 1 req/sec

    conn.commit()

    success = conn.execute("SELECT COUNT(*) FROM geocoded_cities WHERE latitude IS NOT NULL").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM geocoded_cities").fetchone()[0]
    log.info(f"Geocoding complete: {success}/{total} cities resolved")


def fetch_weather(conn):
    """Fetch historical weather for all stages with geocoded departure cities."""
    _init_tables(conn)

    # Get stages that need weather data
    rows = conn.execute("""
        SELECT s.url, s.date, g.latitude, g.longitude
        FROM stages s
        JOIN races r ON s.race_url = r.url
        JOIN geocoded_cities g ON g.city = s.departure AND g.country = r.nationality
        WHERE g.latitude IS NOT NULL
        AND s.date IS NOT NULL AND s.date != ''
        AND NOT EXISTS (
            SELECT 1 FROM stage_weather w WHERE w.stage_url = s.url
        )
    """).fetchall()

    if not rows:
        log.info("All stage weather already fetched")
        return

    log.info(f"Fetching weather for {len(rows)} stages...")

    # Batch by unique lat/lon + date ranges to minimize API calls
    # Open-Meteo allows date ranges, so group by location
    from collections import defaultdict
    location_stages = defaultdict(list)
    for row in rows:
        key = (round(row["latitude"], 4), round(row["longitude"], 4))
        location_stages[key].append((row["url"], row["date"]))

    log.info(f"  {len(location_stages)} unique locations")

    fetched = 0
    errors = 0
    backoff = 2.0  # Base delay between requests

    for loc_idx, ((lat, lon), stages) in enumerate(location_stages.items()):
        stages.sort(key=lambda x: x[1])
        dates = [s[1] for s in stages]
        min_date = min(dates)
        max_date = max(dates)

        url = (
            f"https://archive-api.open-meteo.com/v1/archive?"
            f"latitude={lat}&longitude={lon}"
            f"&start_date={min_date}&end_date={max_date}"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,"
            f"windspeed_10m_max,relative_humidity_2m_mean"
            f"&timezone=auto"
        )

        success = False
        for attempt in range(3):
            try:
                resp = urllib.request.urlopen(url, timeout=30)
                data = json.loads(resp.read())
                daily = data.get("daily", {})

                date_weather = {}
                for i, d in enumerate(daily.get("time", [])):
                    date_weather[d] = {
                        "temperature_max": daily.get("temperature_2m_max", [None])[i],
                        "temperature_min": daily.get("temperature_2m_min", [None])[i],
                        "precipitation_mm": daily.get("precipitation_sum", [None])[i],
                        "wind_speed_max_kmh": daily.get("windspeed_10m_max", [None])[i],
                        "humidity_mean_pct": daily.get("relative_humidity_2m_mean", [None])[i],
                    }

                for stage_url, stage_date in stages:
                    w = date_weather.get(stage_date)
                    if w:
                        conn.execute(
                            """INSERT OR REPLACE INTO stage_weather
                               (stage_url, temperature_max, temperature_min, precipitation_mm,
                                wind_speed_max_kmh, humidity_mean_pct)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (stage_url, w["temperature_max"], w["temperature_min"],
                             w["precipitation_mm"], w["wind_speed_max_kmh"], w["humidity_mean_pct"]),
                        )
                        fetched += 1

                success = True
                backoff = 2.0  # Reset backoff on success
                break

            except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
                if "429" in str(e):
                    wait = 30 * (attempt + 1)
                    log.warning(f"  Rate limited (attempt {attempt+1}/3), waiting {wait}s...")
                    time.sleep(wait)
                    backoff = min(backoff + 1.0, 5.0)  # Slow down permanently
                else:
                    log.warning(f"  Weather API error for ({lat},{lon}): {e}")
                    break

        if not success:
            errors += 1

        if (loc_idx + 1) % 50 == 0:
            conn.commit()
            log.info(f"  Progress: {loc_idx+1}/{len(location_stages)} locations, "
                     f"{fetched} stages fetched, {errors} errors")

        time.sleep(backoff)

    conn.commit()
    log.info(f"Weather fetch complete: {fetched} stages, {errors} errors")


def main():
    conn = get_db()

    log.info("=== Step 1: Geocoding departure cities ===")
    t0 = time.time()
    geocode_cities(conn)
    log.info(f"Geocoding took {time.time() - t0:.0f}s")

    log.info("\n=== Step 2: Fetching historical weather ===")
    t1 = time.time()
    fetch_weather(conn)
    log.info(f"Weather fetch took {time.time() - t1:.0f}s")

    # Summary
    total_stages = conn.execute("SELECT COUNT(*) FROM stages").fetchone()[0]
    with_weather = conn.execute("SELECT COUNT(*) FROM stage_weather").fetchone()[0]
    log.info(f"\nWeather coverage: {with_weather}/{total_stages} stages ({100*with_weather/total_stages:.0f}%)")

    conn.close()


if __name__ == "__main__":
    main()
