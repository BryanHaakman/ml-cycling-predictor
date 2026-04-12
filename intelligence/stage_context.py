"""Stage context fetcher for Pinnacle race name -> PCS stage details."""

import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

TIMEOUT_SECONDS: int = 5
PINNACLE_STAGE_SEPARATOR: str = " - "
RACE_MATCH_THRESHOLD: int = 75


@dataclass
class StageContext:
  """Structured stage metadata for build_feature_vector_manual race_params.

  All field names map 1:1 to race_params keys expected by
  build_feature_vector_manual in features/pipeline.py.
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

  Args:
    pinnacle_race_name: Full Pinnacle race name (e.g. "Tour de Romandie - Stage 3").

  Returns:
    Race name without stage qualifier.
  """
  raise NotImplementedError("Stub -- implementation in Task 2")


def _resolve_race_url(race_name: str, year: Optional[int] = None) -> Optional[str]:
  """Resolve a race name to a PCS race URL via fuzzy match against cache.db.

  Args:
    race_name: Clean race name (without stage suffix).
    year: Race year; defaults to current year if None.

  Returns:
    PCS race URL (e.g. "race/tour-de-romandie/2026") or None if no match.
  """
  raise NotImplementedError("Stub -- implementation in Task 2")


def _extract_base_url(race_url: str) -> str:
  """Extract base race URL by stripping the year suffix.

  Args:
    race_url: Full race URL with year (e.g. "race/tour-de-romandie/2026").

  Returns:
    Base URL without year (e.g. "race/tour-de-romandie").
  """
  raise NotImplementedError("Stub -- implementation in Task 2")


def _unresolved_context() -> StageContext:
  """Return an unresolved StageContext with all defaults.

  Returns:
    StageContext with is_resolved=False.
  """
  return StageContext()


def _do_fetch(race_url: str) -> StageContext:
  """Fetch stage details from PCS. Runs inside ThreadPoolExecutor.

  Args:
    race_url: PCS race URL (e.g. "race/tour-de-romandie/2026").

  Returns:
    Populated StageContext or unresolved context on failure.
  """
  raise NotImplementedError("Stub -- implementation in Task 3")


def _fetch_with_timeout(race_url: str) -> StageContext:
  """Wrap _do_fetch in a 5-second timeout via ThreadPoolExecutor.

  Args:
    race_url: PCS race URL.

  Returns:
    StageContext from _do_fetch, or unresolved on timeout/error.
  """
  raise NotImplementedError("Stub -- implementation in Task 3")


def fetch_stage_context(pinnacle_race_name: str) -> StageContext:
  """Map a Pinnacle race name to PCS stage details.

  Args:
    pinnacle_race_name: Race name from Pinnacle (e.g. "Tour de Romandie - Stage 3").

  Returns:
    StageContext with is_resolved=True if successful, is_resolved=False on any failure.
  """
  raise NotImplementedError("Stub -- implementation in Task 2")
