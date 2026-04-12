"""Flask Blueprint for Pinnacle market endpoints.

Provides:
  POST /api/pinnacle/load        — fetch, resolve, and return ResolvedMarket JSON
  POST /api/pinnacle/refresh-odds — re-fetch odds for known matchup_ids (stateless)
"""
import dataclasses
import logging
from collections import defaultdict
from typing import Any

import requests
from flask import Blueprint, jsonify, request

from data.name_resolver import NameResolver
from data.odds import PinnacleAuthError, fetch_cycling_h2h_markets
from intelligence.stage_context import fetch_stage_context
from webapp.auth import _require_localhost

log = logging.getLogger(__name__)

pinnacle_bp = Blueprint("pinnacle", __name__)


@pinnacle_bp.route("/api/pinnacle/load", methods=["POST"])
@_require_localhost
def pinnacle_load():
  """Fetch today's Pinnacle cycling H2H markets, resolve rider names, fetch stage context.

  Returns a ResolvedMarket JSON response grouped by race.
  Never raises — all exceptions are caught and returned as structured JSON.
  """
  try:
    markets = fetch_cycling_h2h_markets()
  except PinnacleAuthError as e:
    return jsonify({"error": str(e), "env_var": "PINNACLE_SESSION_COOKIE", "type": "auth_error"}), 401
  except requests.RequestException as e:
    return jsonify({"error": "Pinnacle API unavailable", "detail": str(e), "type": "network_error"}), 503
  except Exception as e:
    log.exception("Unexpected error in pinnacle_load")
    return jsonify({"error": str(e), "type": "internal_error"}), 500

  # Group markets by race name (D-04: exact string equality, one stage_context per group)
  by_race: dict[str, list] = defaultdict(list)
  for market in markets:
    by_race[market.race_name].append(market)

  # Instantiate NameResolver once per request (loads ~5K riders from DB)
  resolver = NameResolver()

  races = []
  for race_name, race_markets in by_race.items():
    # Fetch stage context once per race (D-04)
    stage_ctx = fetch_stage_context(race_name)

    pairs = []
    for market in race_markets:
      result_a = resolver.resolve(market.rider_a_name)
      result_b = resolver.resolve(market.rider_b_name)

      pair: dict[str, Any] = {
        "pinnacle_name_a": market.rider_a_name,
        "pinnacle_name_b": market.rider_b_name,
        "rider_a_url": result_a.url,
        "rider_b_url": result_b.url,
        "rider_a_resolved": result_a.url is not None,
        "rider_b_resolved": result_b.url is not None,
        "best_candidate_a_name": result_a.best_candidate_name,
        "best_candidate_a_url": result_a.best_candidate_url,
        "best_candidate_b_name": result_b.best_candidate_name,
        "best_candidate_b_url": result_b.best_candidate_url,
        "odds_a": market.odds_a,
        "odds_b": market.odds_b,
        "matchup_id": market.matchup_id,
      }
      pairs.append(pair)

    race_entry = {
      "race_name": race_name,
      "stage_resolved": stage_ctx.is_resolved,
      "stage_context": dataclasses.asdict(stage_ctx),
      "pairs": pairs,
    }
    races.append(race_entry)

  return jsonify({"races": races}), 200


@pinnacle_bp.route("/api/pinnacle/refresh-odds", methods=["POST"])
@_require_localhost
def pinnacle_refresh_odds():
  """Re-fetch Pinnacle odds for known matchup_ids. Stateless — no name resolution or stage fetch.

  Request body: {"matchup_ids": ["12345", "67890"]}
  Response: {"pairs": [{"matchup_id": "...", "odds_a": X.XX, "odds_b": Y.YY}]}
  """
  data = request.get_json(silent=True)
  if data is None or "matchup_ids" not in data:
    return jsonify({"error": "matchup_ids required", "type": "bad_request"}), 400

  ids = data.get("matchup_ids", [])
  if not ids:
    return jsonify({"error": "matchup_ids must be non-empty", "type": "bad_request"}), 400

  try:
    markets = fetch_cycling_h2h_markets()
  except PinnacleAuthError as e:
    return jsonify({"error": str(e), "env_var": "PINNACLE_SESSION_COOKIE", "type": "auth_error"}), 401
  except requests.RequestException as e:
    return jsonify({"error": "Pinnacle API unavailable", "detail": str(e), "type": "network_error"}), 503
  except Exception as e:
    log.exception("Unexpected error in pinnacle_refresh_odds")
    return jsonify({"error": str(e), "type": "internal_error"}), 500

  id_to_market = {m.matchup_id: m for m in markets}

  pairs = []
  for mid in ids:
    m = id_to_market.get(mid)
    if m is not None:
      pairs.append({"matchup_id": mid, "odds_a": m.odds_a, "odds_b": m.odds_b})
    # Silently omit IDs not found (market may have closed)

  return jsonify({"pairs": pairs}), 200
