"""
Name resolver for mapping Pinnacle display names to PCS rider URLs.

Implements a four-stage resolution pipeline:
  1. Persistent cache lookup (data/name_mappings.json)
  2. Exact match against cache.db riders table
  3. Unicode-normalized + word-order-reversed match
  4. Fuzzy match via rapidfuzz token_sort_ratio (auto-accept >= 90, hint 60-89)

Accepted mappings persist in data/name_mappings.json and are reused on
future NameResolver instantiations without re-querying cache.db.
"""

import json
import logging
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz, process

from data.scraper import get_db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CACHE_PATH = os.path.join(os.path.dirname(__file__), "name_mappings.json")
AUTO_ACCEPT_THRESHOLD = 90
HINT_THRESHOLD = 60
CACHE_URL_PATTERN = re.compile(r"^rider/[a-z0-9-]+$")

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ResolveResult:
  """Result of a name resolution attempt.

  url is populated only when resolution succeeded (method != 'unresolved').
  best_candidate_* fields are populated only when score is in range 60-89.
  """
  url: Optional[str]
  best_candidate_url: Optional[str]
  best_candidate_name: Optional[str]
  best_score: Optional[int]
  method: str  # "exact" | "normalized" | "fuzzy" | "cache" | "unresolved"


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
  """Normalize a Pinnacle display name for corpus comparison.

  Applies NFKD decomposition, ASCII stripping, lowercasing, and
  last-word-first reversal to convert Pinnacle SURNAME-FIRST ALL-CAPS
  format to given-name-first lowercase for corpus matching.

  Examples:
    "ROGLIC PRIMOZ"   -> "primoz roglic"
    "VAN AERT WOUT"   -> "wout van aert"
    "Primož Roglič"   -> "roglic primoz"  (accent stripped, then reversed)

  Args:
    name: Input name string (Pinnacle format or raw).

  Returns:
    Normalized string with last token moved to front.
  """
  nfkd = unicodedata.normalize("NFKD", name)
  ascii_str = nfkd.encode("ascii", "ignore").decode("ascii").lower().strip()
  tokens = ascii_str.split()
  if len(tokens) >= 2:
    return f"{tokens[-1]} {' '.join(tokens[:-1])}"
  return ascii_str


def _normalize_pcs_name(name: str) -> str:
  """Normalize a PCS corpus name for index lookup.

  Applies NFKD decomposition, ASCII stripping, and lowercasing WITHOUT
  word-order reversal. PCS names are already in given-name-first order.

  Examples:
    "Primož Roglič"  -> "primoz roglic"
    "Wout van Aert"  -> "wout van aert"
    "Romain Bardet"  -> "romain bardet"

  Args:
    name: PCS rider name (given-name first, may have accents).

  Returns:
    Normalized string preserving original word order.
  """
  nfkd = unicodedata.normalize("NFKD", name)
  return nfkd.encode("ascii", "ignore").decode("ascii").lower().strip()


# ---------------------------------------------------------------------------
# NameResolver class
# ---------------------------------------------------------------------------

class NameResolver:
  """Maps Pinnacle display names to PCS rider URLs via a multi-stage pipeline.

  Stage 1: Persistent cache lookup (data/name_mappings.json) — O(1)
  Stage 2: Exact match against riders corpus — O(1) via dict
  Stage 3: Unicode-normalized + word-order-reversed match — O(1) via index
  Stage 4: Fuzzy match via rapidfuzz token_sort_ratio — O(n) corpus scan

  The full riders corpus (~5K rows) is loaded once at construction time.
  All subsequent resolve() calls operate on in-memory data structures.
  """

  def __init__(self) -> None:
    """Load riders from cache.db and persistent cache from name_mappings.json."""
    conn = get_db()
    rows = conn.execute("SELECT url, name FROM riders").fetchall()
    conn.close()

    self._corpus: list[tuple[str, str]] = [(r["url"], r["name"]) for r in rows]
    self._name_to_url: dict[str, str] = {name: url for url, name in self._corpus}
    self._normalized_index: dict[str, str] = {
      _normalize_pcs_name(name): url for url, name in self._corpus
    }
    self._corpus_normalized: list[str] = [
      _normalize_pcs_name(name) for _, name in self._corpus
    ]
    self._cache: dict[str, str] = self._load_cache()

    log.info("NameResolver: loaded %d riders from cache.db", len(self._corpus))

  def resolve(self, pinnacle_name: str) -> ResolveResult:
    """Resolve a Pinnacle display name to a PCS rider URL.

    Runs stages 1-4 in order; returns on first hit.

    Args:
      pinnacle_name: Rider display name from Pinnacle API (typically
        SURNAME-FIRST ALL-CAPS, e.g. "ROGLIC PRIMOZ").

    Returns:
      ResolveResult with url populated on success, None on failure.
    """
    # Stage 1: persistent cache
    if pinnacle_name in self._cache:
      return ResolveResult(
        url=self._cache[pinnacle_name],
        best_candidate_url=None,
        best_candidate_name=None,
        best_score=None,
        method="cache",
      )

    # Stage 2: exact match (handles names already in PCS format)
    if pinnacle_name in self._name_to_url:
      return ResolveResult(
        url=self._name_to_url[pinnacle_name],
        best_candidate_url=None,
        best_candidate_name=None,
        best_score=None,
        method="exact",
      )

    # Stage 3: unicode-normalized + word-order-reversed match
    normalized = _normalize_name(pinnacle_name)
    if normalized in self._normalized_index:
      url = self._normalized_index[normalized]
      self.accept(pinnacle_name, url)
      return ResolveResult(
        url=url,
        best_candidate_url=None,
        best_candidate_name=None,
        best_score=None,
        method="normalized",
      )

    # Stage 4: fuzzy match via rapidfuzz token_sort_ratio
    fuzzy_result = process.extractOne(
      query=normalized,
      choices=self._corpus_normalized,
      scorer=fuzz.token_sort_ratio,
      score_cutoff=float(HINT_THRESHOLD),
    )
    if fuzzy_result is not None:
      _matched_str, score, idx = fuzzy_result
      matched_url, matched_name = self._corpus[idx]
      score_int = int(score)
      if score_int >= AUTO_ACCEPT_THRESHOLD:
        self.accept(pinnacle_name, matched_url)
        return ResolveResult(
          url=matched_url,
          best_candidate_url=None,
          best_candidate_name=None,
          best_score=None,
          method="fuzzy",
        )
      else:
        # Hint range: 60-89
        return ResolveResult(
          url=None,
          best_candidate_url=matched_url,
          best_candidate_name=matched_name,
          best_score=score_int,
          method="unresolved",
        )

    # No match at all (below HINT_THRESHOLD)
    return ResolveResult(
      url=None,
      best_candidate_url=None,
      best_candidate_name=None,
      best_score=None,
      method="unresolved",
    )

  def accept(self, pinnacle_name: str, pcs_url: str) -> None:
    """Record a confirmed name-to-URL mapping and persist it to disk.

    Updates the in-memory cache immediately so resolve() finds it in the
    same session. Called by Phase 4 endpoint on manual match confirmation,
    and internally by resolve() when a normalized match is found.

    Args:
      pinnacle_name: Pinnacle display name (dict key).
      pcs_url: Confirmed PCS rider URL (e.g. "rider/primoz-roglic").
    """
    self._cache[pinnacle_name] = pcs_url
    self._save_cache()

  def _load_cache(self) -> dict[str, str]:
    """Load persistent name mappings from CACHE_PATH.

    Handles missing file and corrupt JSON gracefully. Validates each
    entry's URL against CACHE_URL_PATTERN (per D-07); invalid entries
    are logged and skipped.

    Returns:
      Dict mapping Pinnacle names to PCS URLs (validated entries only).
    """
    try:
      with open(CACHE_PATH, encoding="utf-8") as f:
        raw: dict = json.load(f)
    except FileNotFoundError:
      return {}
    except json.JSONDecodeError as e:
      log.warning("_load_cache: corrupt JSON in %s: %s", CACHE_PATH, e)
      return {}

    validated: dict[str, str] = {}
    for key, val in raw.items():
      if isinstance(val, str) and CACHE_URL_PATTERN.match(val):
        validated[key] = val
      else:
        log.warning("_load_cache: skipping invalid entry %r -> %r", key, val)
    return validated

  def _save_cache(self) -> None:
    """Atomically write the current in-memory cache to CACHE_PATH.

    Uses tempfile + os.replace() to prevent partial writes on crash or
    disk-full conditions (per D-08, Pattern 4 in RESEARCH).
    """
    dir_name = os.path.dirname(CACHE_PATH) or "."
    try:
      with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=dir_name,
        suffix=".tmp",
        delete=False,
      ) as f:
        json.dump(self._cache, f, indent=2, ensure_ascii=False)
        tmp_path = f.name
      os.replace(tmp_path, CACHE_PATH)
    except OSError as e:
      log.warning("_save_cache: could not write %s: %s", CACHE_PATH, e)
