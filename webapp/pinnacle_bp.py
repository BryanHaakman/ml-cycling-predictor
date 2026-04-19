"""Flask Blueprint for Pinnacle market endpoints.

Provides:
  POST /api/pinnacle/load           -- scrape, resolve, predict, return JSON
  POST /api/pinnacle/snapshot       -- scrape and save snapshot to SQLite
  POST /api/pinnacle/snapshot/closing -- scrape closing odds snapshot
"""
import dataclasses
import logging
from collections import defaultdict
from typing import Any, Optional

from flask import Blueprint, jsonify, request

from data.name_resolver import NameResolver
from data.pinnacle_scraper import (
  PinnacleScrapeError, scrape_cycling_markets, save_snapshot, MatchupSnapshot,
)
from data.pnl import get_total_bankroll
from data.scraper import get_db, DB_PATH
from intelligence.stage_context import fetch_stage_context
from models.predict import Predictor, kelly_criterion, decimal_odds_to_implied_prob
from webapp.auth import _require_localhost

log = logging.getLogger(__name__)

pinnacle_bp = Blueprint("pinnacle", __name__)

# ---------------------------------------------------------------------------
# Lazy-loaded Predictor (same pattern as webapp/app.py)
# ---------------------------------------------------------------------------

_predictor: Optional[Predictor] = None


def _get_predictor() -> Optional[Predictor]:
  """Return a lazily-loaded Predictor instance, or None if no model trained."""
  global _predictor
  if _predictor is None:
    try:
      _predictor = Predictor()
    except FileNotFoundError:
      log.warning("No trained model found -- predictions unavailable")
      return None
  return _predictor


def _compute_prediction_for_pair(
    rider_a_url: Optional[str],
    rider_b_url: Optional[str],
    odds_a: float,
    odds_b: float,
) -> dict[str, Any]:
  """Run model prediction and Kelly analysis for a resolved rider pair.

  Returns dict with model_prob, edge, recommended_stake, should_bet.
  Returns empty-ish defaults if prediction is unavailable.
  """
  defaults = {
    "model_prob": None,
    "edge": None,
    "recommended_stake": 0.0,
    "should_bet": False,
  }
  if not rider_a_url or not rider_b_url:
    return defaults

  predictor = _get_predictor()
  if predictor is None:
    return defaults

  try:
    # Use predict_manual with minimal race_params -- the /load caller
    # doesn't necessarily have a stage_url, so we use manual path.
    # We need odds for Kelly calculation.
    result = predictor.predict_manual(
      rider_a_url, rider_b_url,
      race_params={},  # minimal -- features degrade gracefully
      odds_a=odds_a, odds_b=odds_b,
    )
    # Determine which side has the edge
    prob_a = result.prob_a_wins
    implied_a = decimal_odds_to_implied_prob(odds_a) if odds_a else 0.5
    implied_b = decimal_odds_to_implied_prob(odds_b) if odds_b else 0.5

    # Kelly for rider A
    kelly_a = kelly_criterion(prob_a, odds_a) if odds_a else None
    kelly_b = kelly_criterion(1.0 - prob_a, odds_b) if odds_b else None

    bankroll = get_total_bankroll()

    # Pick the side with the better edge
    best_kelly = None
    best_prob = None
    best_edge = None
    if kelly_a and kelly_a.should_bet:
      best_kelly = kelly_a
      best_prob = prob_a
      best_edge = kelly_a.edge
    if kelly_b and kelly_b.should_bet:
      if best_kelly is None or kelly_b.edge > best_kelly.edge:
        best_kelly = kelly_b
        best_prob = 1.0 - prob_a
        best_edge = kelly_b.edge

    if best_kelly:
      rec_stake = round(best_kelly.quarter_kelly * bankroll, 2)
      return {
        "model_prob": round(best_prob, 4),
        "edge": round(best_edge, 4),
        "recommended_stake": rec_stake,
        "should_bet": best_edge > 0.05,
      }
    else:
      # No edge on either side
      return {
        "model_prob": round(prob_a, 4),
        "edge": round(prob_a - implied_a, 4),
        "recommended_stake": 0.0,
        "should_bet": False,
      }
  except Exception as e:
    log.warning("_compute_prediction_for_pair: %s vs %s failed: %s",
                rider_a_url, rider_b_url, e)
    return defaults


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@pinnacle_bp.route("/api/pinnacle/load", methods=["POST"])
@_require_localhost
def pinnacle_load():
  """Scrape Pinnacle cycling H2H markets, resolve names, run predictions.

  Returns a ResolvedMarket JSON response grouped by race.
  Never raises -- all exceptions are caught and returned as structured JSON.
  """
  try:
    snapshots = scrape_cycling_markets()
  except PinnacleScrapeError as e:
    return jsonify({"error": str(e), "type": "scrape_error"}), 503
  except Exception as e:
    log.exception("Unexpected error in pinnacle_load")
    return jsonify({"error": str(e), "type": "internal_error"}), 500

  # Group markets by race name
  by_race: dict[str, list[MatchupSnapshot]] = defaultdict(list)
  for snap in snapshots:
    by_race[snap.race_name].append(snap)

  # Instantiate NameResolver once per request (loads ~5K riders from DB)
  resolver = NameResolver()

  races = []
  for race_name, race_snaps in by_race.items():
    # Fetch stage context once per race
    stage_ctx = fetch_stage_context(race_name)

    pairs = []
    for snap in race_snaps:
      result_a = resolver.resolve(snap.rider_a_name)
      result_b = resolver.resolve(snap.rider_b_name)

      # Model prediction per D-12/ODDS-04
      pred = _compute_prediction_for_pair(
        result_a.url, result_b.url,
        snap.odds_a, snap.odds_b,
      )

      pair: dict[str, Any] = {
        "pinnacle_name_a": snap.rider_a_name,
        "pinnacle_name_b": snap.rider_b_name,
        "rider_a_url": result_a.url,
        "rider_b_url": result_b.url,
        "rider_a_resolved": result_a.url is not None,
        "rider_b_resolved": result_b.url is not None,
        "best_candidate_a_name": result_a.best_candidate_name,
        "best_candidate_a_url": result_a.best_candidate_url,
        "best_candidate_b_name": result_b.best_candidate_name,
        "best_candidate_b_url": result_b.best_candidate_url,
        "odds_a": snap.odds_a,
        "odds_b": snap.odds_b,
        "start_time": snap.start_time,
        "model_prob": pred["model_prob"],
        "edge": pred["edge"],
        "recommended_stake": pred["recommended_stake"],
        "should_bet": pred["should_bet"],
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


@pinnacle_bp.route("/api/pinnacle/snapshot", methods=["POST"])
@_require_localhost
def pinnacle_snapshot():
  """Scrape and persist a market snapshot to market_snapshots table.

  Also computes and stores model predictions per D-12/ODDS-04.
  """
  try:
    snapshots = scrape_cycling_markets()
    save_snapshot(snapshots)
    _enrich_snapshots_with_predictions(snapshots)
    return jsonify({"saved": len(snapshots)}), 200
  except PinnacleScrapeError as e:
    return jsonify({"error": str(e), "type": "scrape_error"}), 503
  except Exception as e:
    log.exception("Unexpected error in pinnacle_snapshot")
    return jsonify({"error": str(e), "type": "internal_error"}), 500


@pinnacle_bp.route("/api/pinnacle/snapshot/closing", methods=["POST"])
@_require_localhost
def pinnacle_snapshot_closing():
  """Scrape closing odds and persist snapshot with snapshot_type='closing'.

  Used for CLV-01 closing line capture before race start.
  """
  try:
    snapshots = scrape_cycling_markets(snapshot_type="closing")
    save_snapshot(snapshots)
    _enrich_snapshots_with_predictions(snapshots)
    return jsonify({"saved": len(snapshots)}), 200
  except PinnacleScrapeError as e:
    return jsonify({"error": str(e), "type": "scrape_error"}), 503
  except Exception as e:
    log.exception("Unexpected error in pinnacle_snapshot_closing")
    return jsonify({"error": str(e), "type": "internal_error"}), 500


def _enrich_snapshots_with_predictions(snapshots: list[MatchupSnapshot]) -> None:
  """Update saved snapshot rows with model predictions.

  For each snapshot, resolve rider names to PCS URLs, run predictions,
  and UPDATE the market_snapshots row with model_prob, edge, and
  recommended_stake for both sides.
  """
  predictor = _get_predictor()
  if predictor is None:
    return

  resolver = NameResolver()
  conn = get_db()

  for snap in snapshots:
    result_a = resolver.resolve(snap.rider_a_name)
    result_b = resolver.resolve(snap.rider_b_name)
    if not result_a.url or not result_b.url:
      continue

    try:
      pred_result = predictor.predict_manual(
        result_a.url, result_b.url,
        race_params={},
        odds_a=snap.odds_a, odds_b=snap.odds_b,
      )
      prob_a = pred_result.prob_a_wins
      prob_b = 1.0 - prob_a
      bankroll = get_total_bankroll()

      kelly_a = kelly_criterion(prob_a, snap.odds_a)
      kelly_b = kelly_criterion(prob_b, snap.odds_b)

      rec_stake_a = round(kelly_a.quarter_kelly * bankroll, 2) if kelly_a.should_bet else 0.0
      rec_stake_b = round(kelly_b.quarter_kelly * bankroll, 2) if kelly_b.should_bet else 0.0

      conn.execute("""
        UPDATE market_snapshots
        SET rider_a_pcs_url = ?, rider_b_pcs_url = ?,
            model_prob_a = ?, edge_a = ?, recommended_stake_a = ?,
            model_prob_b = ?, edge_b = ?, recommended_stake_b = ?
        WHERE id = (
          SELECT id FROM market_snapshots
          WHERE rider_a_name = ? AND rider_b_name = ?
            AND race_name = ? AND snapshot_type = ?
          ORDER BY id DESC LIMIT 1
        )
      """, (
        result_a.url, result_b.url,
        round(prob_a, 4), round(kelly_a.edge, 4), rec_stake_a,
        round(prob_b, 4), round(kelly_b.edge, 4), rec_stake_b,
        snap.rider_a_name, snap.rider_b_name,
        snap.race_name, snap.snapshot_type,
      ))
    except Exception as e:
      log.warning("_enrich_snapshots_with_predictions: %s vs %s failed: %s",
                  snap.rider_a_name, snap.rider_b_name, e)

  conn.commit()
  conn.close()
