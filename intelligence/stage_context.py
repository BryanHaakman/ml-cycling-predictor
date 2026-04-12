"""Stage context fetcher for Pinnacle race name -> PCS stage details."""

import os
import sys
import logging
import concurrent.futures
from dataclasses import dataclass
from datetime import date as _date
from typing import Optional

from rapidfuzz import fuzz, process

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.scraper import get_db

log = logging.getLogger(__name__)

TIMEOUT_SECONDS: int = 5
PINNACLE_STAGE_SEPARATOR: str = " - "
RACE_MATCH_THRESHOLD: int = 75


@dataclass
class StageContext:
  """Structured stage metadata for build_feature_vector_manual race_params.

  All field names map 1:1 to race_params keys expected by
  build_feature_vector_manual in features/pipeline.py. The extra fields
  uci_tour and is_resolved are stage_context-specific.
  """

  distance: float = 0.0
  vertical_meters: Optional[int] = None
  profile_icon: str = "p1"
  profile_score: Optional[int] = None
  is_one_day_race: bool = False
  stage_type: str = "RR"
  race_date: str = ""
  race_base_url: str = ""
  num_climbs: int = 0
  avg_temperature: Optional[float] = None
  uci_tour: str = ""
  is_resolved: bool = False


def _parse_race_name(pinnacle_race_name: str) -> str:
  """Parse Pinnacle race name, stripping stage suffix.

  Splits on PINNACLE_STAGE_SEPARATOR (' - ') and returns the first part.
  If no separator is present the full name is returned unchanged.
  Logs the parsing assumption made (D-02).

  Args:
    pinnacle_race_name: Full Pinnacle race name (e.g. "Tour de Romandie - Stage 3").

  Returns:
    Race name without stage qualifier (e.g. "Tour de Romandie").
  """
  if PINNACLE_STAGE_SEPARATOR in pinnacle_race_name:
    result = pinnacle_race_name.split(PINNACLE_STAGE_SEPARATOR)[0].strip()
  else:
    result = pinnacle_race_name.strip()
  log.info(
    "_parse_race_name: parsed %r -> %r (separator=%r)",
    pinnacle_race_name,
    result,
    PINNACLE_STAGE_SEPARATOR,
  )
  return result


def _resolve_race_url(race_name: str, year: Optional[int] = None) -> Optional[str]:
  """Resolve a race name to a PCS race URL via fuzzy match against cache.db.

  Uses rapidfuzz token_sort_ratio with RACE_MATCH_THRESHOLD (75) to match
  the race name against all races in cache.db for the given year.
  Parameterized SQL query prevents injection (T-3-01).

  Args:
    race_name: Clean race name (without stage suffix).
    year: Race year; defaults to current year if None.

  Returns:
    PCS race URL (e.g. "race/tour-de-romandie/2026") or None if no match.
  """
  if year is None:
    year = _date.today().year

  conn = get_db()
  rows = conn.execute("SELECT url, name FROM races WHERE year = ?", (year,)).fetchall()
  conn.close()

  if not rows:
    log.warning(
      "_resolve_race_url: no races in cache.db for year %d — cannot resolve %r",
      year,
      race_name,
    )
    return None

  names = [r["name"] for r in rows]
  match = process.extractOne(
    race_name,
    names,
    scorer=fuzz.token_sort_ratio,
    score_cutoff=RACE_MATCH_THRESHOLD,
  )

  if match is None:
    log.warning(
      "_resolve_race_url: no match for %r in year %d (threshold=%d)",
      race_name,
      year,
      RACE_MATCH_THRESHOLD,
    )
    return None

  matched_name, score, idx = match
  log.info(
    "_resolve_race_url: matched %r -> %r (score=%.1f)",
    race_name,
    rows[idx]["url"],
    score,
  )
  return rows[idx]["url"]


def _extract_base_url(race_url: str) -> str:
  """Extract base race URL by stripping the year suffix.

  Args:
    race_url: Full race URL with year (e.g. "race/tour-de-romandie/2026").

  Returns:
    Base URL without year (e.g. "race/tour-de-romandie").
  """
  return race_url.rsplit("/", 1)[0]


def _unresolved_context() -> StageContext:
  """Return an unresolved StageContext with all defaults.

  Returns:
    StageContext with is_resolved=False.
  """
  return StageContext()


def _do_fetch(race_url: str) -> StageContext:
  """Fetch stage details from PCS. Runs inside ThreadPoolExecutor.

  Determines is_one_day_race via Race.is_one_day_race() — never Stage.
  For multi-stage races, finds today's stage by matching MM-DD date format.
  For one-day races, constructs the URL with /result suffix.

  Args:
    race_url: PCS race URL including year (e.g. "race/tour-de-romandie/2026").

  Returns:
    Populated StageContext with is_resolved=True, or _unresolved_context() if
    today's stage cannot be located.
  """
  from procyclingstats import Race, Stage

  race = Race(race_url)
  is_one_day = race.is_one_day_race()  # Critical Finding #1: Race, not Stage

  uci_tour = ""
  try:
    uci_tour = race.uci_tour()
  except Exception:
    log.warning("_do_fetch: uci_tour() failed for %s", race_url)

  if is_one_day:
    stage_url = f"{race_url}/result"
  else:
    today_mmdd = _date.today().strftime("%m-%d")
    stages = race.stages()
    todays = next((s for s in stages if s["date"] == today_mmdd), None)
    if todays is None:
      log.warning(
        "_do_fetch: no stage matching today %s in %s",
        today_mmdd,
        race_url,
      )
      return _unresolved_context()
    stage_url = todays["stage_url"]

  stage = Stage(stage_url)
  return StageContext(
    distance=stage.distance(),
    vertical_meters=stage.vertical_meters(),
    profile_icon=stage.profile_icon(),
    profile_score=stage.profile_score(),
    is_one_day_race=is_one_day,          # From Race, NOT Stage (Critical Finding #1)
    stage_type=stage.stage_type(),
    race_date=stage.date(),
    race_base_url=_extract_base_url(race_url),
    num_climbs=len(stage.climbs()),      # Per D-09
    avg_temperature=stage.avg_temperature(),
    uci_tour=uci_tour,
    is_resolved=True,
  )


def _fetch_with_timeout(race_url: str) -> StageContext:
  """Wrap _do_fetch in a 5-second timeout via ThreadPoolExecutor.

  Uses a new ThreadPoolExecutor per call (Critical Finding #7) — no thread reuse.
  Catches concurrent.futures.TimeoutError specifically (Critical Finding #6).
  signal.alarm is NOT used — Windows-safe (Critical Finding #2).

  The executor is shut down with wait=False so that a timed-out background
  thread does not block the caller — the thread is abandoned (daemon behaviour).

  Args:
    race_url: PCS race URL.

  Returns:
    StageContext from _do_fetch, or _unresolved_context() on timeout/error.
  """
  executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
  try:
    future = executor.submit(_do_fetch, race_url)
    try:
      return future.result(timeout=TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
      log.warning(
        "fetch_stage_context: PCS timed out after %ss for %s",
        TIMEOUT_SECONDS,
        race_url,
      )
      return _unresolved_context()
    except Exception as exc:
      log.warning(
        "fetch_stage_context: PCS fetch failed for %s: %s",
        race_url,
        exc,
      )
      return _unresolved_context()
  finally:
    # Shut down without waiting — abandoned thread will finish in background.
    # This prevents a timed-out PCS request from blocking the caller.
    executor.shutdown(wait=False)


def fetch_stage_context(pinnacle_race_name: str) -> StageContext:
  """Map a Pinnacle race name to PCS stage details.

  Pipeline:
    1. _parse_race_name: strip stage suffix (e.g. "Tour de Romandie - Stage 3" -> "Tour de Romandie")
    2. _resolve_race_url: fuzzy match against cache.db races table
    3. _fetch_with_timeout: fetch Race + Stage from PCS within 5s timeout
    4. Return populated StageContext or StageContext(is_resolved=False) on any failure

  Args:
    pinnacle_race_name: Race name from Pinnacle (e.g. "Tour de Romandie - Stage 3").

  Returns:
    StageContext with is_resolved=True if successful, is_resolved=False on any failure.
    Never raises an exception.
  """
  race_name = _parse_race_name(pinnacle_race_name)
  race_url = _resolve_race_url(race_name)
  if not race_url:
    return _unresolved_context()

  return _fetch_with_timeout(race_url)
