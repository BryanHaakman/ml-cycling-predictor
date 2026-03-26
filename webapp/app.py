"""
Flask web application for cycling head-to-head predictions.
"""

import os
import sys
import json
import logging
import subprocess
import threading
import time
import queue

from flask import Flask, render_template, request, jsonify, Response

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.scraper import get_db, DB_PATH
from data.pnl import (
    get_pnl_db, place_bet, settle_bet, void_bet,
    get_pnl_summary, get_bet_history, get_current_bankroll,
    set_initial_bankroll, auto_settle_from_results,
)
from models.predict import Predictor, kelly_criterion, decimal_odds_to_implied_prob
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)

_predictor = None


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(500)
def handle_error(e):
    """Return JSON for API errors instead of HTML."""
    if request.path.startswith("/api/"):
        return jsonify({"error": str(e)}), e.code if hasattr(e, 'code') else 500
    return e


def get_predictor():
    global _predictor
    if _predictor is None:
        try:
            _predictor = Predictor()
        except FileNotFoundError:
            log.warning("No trained model found — train first with: python -m models.benchmark")
            return None
    return _predictor


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/riders")
def api_riders():
    """Autocomplete endpoint for rider search."""
    q = request.args.get("q", "").strip().lower()
    if len(q) < 2:
        return jsonify([])

    conn = get_db()
    riders = conn.execute("""
        SELECT url, name, nationality FROM riders
        WHERE LOWER(name) LIKE ?
        ORDER BY name LIMIT 20
    """, (f"%{q}%",)).fetchall()
    conn.close()

    return jsonify([
        {"url": r["url"], "name": r["name"], "nationality": r["nationality"]}
        for r in riders
    ])


@app.route("/api/races")
def api_races():
    """Search upcoming or recent races/stages."""
    q = request.args.get("q", "").strip().lower()
    year = request.args.get("year", "")

    conn = get_db()
    if q:
        stages = conn.execute("""
            SELECT s.url, s.stage_name, s.date, s.distance, s.profile_icon,
                   s.vertical_meters, r.name as race_name, r.year
            FROM stages s
            JOIN races r ON s.race_url = r.url
            WHERE LOWER(r.name) LIKE ? OR LOWER(s.stage_name) LIKE ?
            ORDER BY s.date DESC LIMIT 30
        """, (f"%{q}%", f"%{q}%")).fetchall()
    elif year:
        stages = conn.execute("""
            SELECT s.url, s.stage_name, s.date, s.distance, s.profile_icon,
                   s.vertical_meters, r.name as race_name, r.year
            FROM stages s
            JOIN races r ON s.race_url = r.url
            WHERE r.year = ?
            ORDER BY s.date DESC LIMIT 50
        """, (int(year),)).fetchall()
    else:
        stages = conn.execute("""
            SELECT s.url, s.stage_name, s.date, s.distance, s.profile_icon,
                   s.vertical_meters, r.name as race_name, r.year
            FROM stages s
            JOIN races r ON s.race_url = r.url
            ORDER BY s.date DESC LIMIT 30
        """).fetchall()
    conn.close()

    return jsonify([
        {
            "url": s["url"],
            "label": f"{s['race_name']} — {s['stage_name']} ({s['date']})",
            "distance": s["distance"],
            "profile": s["profile_icon"],
            "vertical_meters": s["vertical_meters"],
        }
        for s in stages
    ])


@app.route("/api/predict", methods=["POST"])
def api_predict():
    """Make a head-to-head prediction. Supports both DB stage_url and manual race params."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid or missing JSON body"}), 400
    rider_a_url = data.get("rider_a_url")
    rider_b_url = data.get("rider_b_url")
    stage_url = data.get("stage_url")
    race_params = data.get("race_params")  # manual race dict
    odds_a = data.get("odds_a")  # decimal odds
    odds_b = data.get("odds_b")  # decimal odds

    if not all([rider_a_url, rider_b_url]):
        return jsonify({"error": "Missing rider_a_url or rider_b_url"}), 400

    if not stage_url and not race_params:
        return jsonify({"error": "Provide either stage_url or race_params"}), 400

    predictor = get_predictor()
    if predictor is None:
        return jsonify({"error": "No trained model available. Run training first."}), 503

    try:
        odds_a = float(odds_a) if odds_a else None
        odds_b = float(odds_b) if odds_b else None

        if race_params:
            result = predictor.predict_manual(rider_a_url, rider_b_url, race_params, odds_a, odds_b)
        else:
            result = predictor.predict(rider_a_url, rider_b_url, stage_url, odds_a, odds_b)

        response = {
            "rider_a": {
                "name": result.rider_a_name,
                "url": rider_a_url,
                "win_probability": round(result.prob_a_wins, 4),
                "win_pct": f"{result.prob_a_wins:.1%}",
            },
            "rider_b": {
                "name": result.rider_b_name,
                "url": rider_b_url,
                "win_probability": round(result.prob_b_wins, 4),
                "win_pct": f"{result.prob_b_wins:.1%}",
            },
            "model": result.model_used,
        }

        # Kelly analysis for rider A
        if result.kelly_a:
            k = result.kelly_a
            response["rider_a"]["kelly"] = {
                "edge": round(k.edge, 4),
                "edge_pct": f"{k.edge:.1%}",
                "full_kelly": round(k.kelly_fraction, 4),
                "half_kelly": round(k.half_kelly, 4),
                "quarter_kelly": round(k.quarter_kelly, 4),
                "expected_value": round(k.expected_value, 4),
                "should_bet": k.should_bet,
                "bookmaker_odds": odds_a,
                "implied_prob": round(decimal_odds_to_implied_prob(odds_a), 4),
                "summary": k.describe(),
            }

        # Kelly analysis for rider B
        if result.kelly_b:
            k = result.kelly_b
            response["rider_b"]["kelly"] = {
                "edge": round(k.edge, 4),
                "edge_pct": f"{k.edge:.1%}",
                "full_kelly": round(k.kelly_fraction, 4),
                "half_kelly": round(k.half_kelly, 4),
                "quarter_kelly": round(k.quarter_kelly, 4),
                "expected_value": round(k.expected_value, 4),
                "should_bet": k.should_bet,
                "bookmaker_odds": odds_b,
                "implied_prob": round(decimal_odds_to_implied_prob(odds_b), 4),
                "summary": k.describe(),
            }

        return jsonify(response)

    except Exception as e:
        log.exception("Prediction error")
        return jsonify({"error": str(e)}), 500


@app.route("/api/predict/batch", methods=["POST"])
def api_predict_batch():
    """Batch head-to-head predictions. Accepts multiple pairs against a shared race config."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    pairs = data.get("pairs", [])
    stage_url = data.get("stage_url")
    race_params = data.get("race_params")

    if not pairs:
        return jsonify({"error": "No pairs provided"}), 400
    if not stage_url and not race_params:
        return jsonify({"error": "Provide either stage_url or race_params"}), 400

    predictor = get_predictor()
    if predictor is None:
        return jsonify({"error": "No trained model available. Run training first."}), 503

    results = []
    for i, pair in enumerate(pairs):
        rider_a_url = pair.get("rider_a_url")
        rider_b_url = pair.get("rider_b_url")
        odds_a = pair.get("odds_a")
        odds_b = pair.get("odds_b")

        if not rider_a_url or not rider_b_url:
            results.append({"error": f"Pair {i+1}: missing rider URLs", "index": i})
            continue

        try:
            odds_a = float(odds_a) if odds_a else None
            odds_b = float(odds_b) if odds_b else None

            if race_params:
                result = predictor.predict_manual(rider_a_url, rider_b_url, race_params, odds_a, odds_b)
            else:
                result = predictor.predict(rider_a_url, rider_b_url, stage_url, odds_a, odds_b)

            entry = {
                "index": i,
                "rider_a": {
                    "name": result.rider_a_name,
                    "url": rider_a_url,
                    "win_probability": round(result.prob_a_wins, 4),
                    "win_pct": f"{result.prob_a_wins:.1%}",
                },
                "rider_b": {
                    "name": result.rider_b_name,
                    "url": rider_b_url,
                    "win_probability": round(result.prob_b_wins, 4),
                    "win_pct": f"{result.prob_b_wins:.1%}",
                },
                "model": result.model_used,
            }

            if result.kelly_a:
                k = result.kelly_a
                entry["rider_a"]["kelly"] = {
                    "edge": round(k.edge, 4),
                    "edge_pct": f"{k.edge:.1%}",
                    "full_kelly": round(k.kelly_fraction, 4),
                    "half_kelly": round(k.half_kelly, 4),
                    "quarter_kelly": round(k.quarter_kelly, 4),
                    "expected_value": round(k.expected_value, 4),
                    "should_bet": k.should_bet,
                    "bookmaker_odds": odds_a,
                    "implied_prob": round(decimal_odds_to_implied_prob(odds_a), 4),
                }
            if result.kelly_b:
                k = result.kelly_b
                entry["rider_b"]["kelly"] = {
                    "edge": round(k.edge, 4),
                    "edge_pct": f"{k.edge:.1%}",
                    "full_kelly": round(k.kelly_fraction, 4),
                    "half_kelly": round(k.half_kelly, 4),
                    "quarter_kelly": round(k.quarter_kelly, 4),
                    "expected_value": round(k.expected_value, 4),
                    "should_bet": k.should_bet,
                    "bookmaker_odds": odds_b,
                    "implied_prob": round(decimal_odds_to_implied_prob(odds_b), 4),
                }

            results.append(entry)
        except Exception as e:
            log.warning("Batch prediction error for pair %d: %s", i, e)
            results.append({"error": str(e), "index": i})

    return jsonify({"results": results, "count": len(results)})


@app.route("/api/stats")
def api_stats():
    """Database stats."""
    conn = get_db()
    stats = {}
    for table in ["races", "stages", "results", "riders"]:
        row = conn.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()
        stats[table] = row["c"]
    year_range = conn.execute("SELECT MIN(year) as mn, MAX(year) as mx FROM races").fetchone()
    stats["year_range"] = f"{year_range['mn']}-{year_range['mx']}" if year_range["mn"] else "N/A"
    conn.close()
    # Load best model AUC from benchmark results
    bench_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                              "models", "trained", "benchmark_results.csv")
    try:
        import csv
        with open(bench_path) as f:
            reader = csv.DictReader(f)
            best_auc = max(float(row["roc_auc"]) for row in reader)
            stats["best_auc"] = best_auc
    except Exception:
        stats["best_auc"] = None
    return jsonify(stats)


# ── Saved Races ────────────────────────────────────────────────────────────

@app.route("/api/saved-races")
def api_saved_races():
    """List saved race configurations."""
    conn = get_pnl_db()
    rows = conn.execute("SELECT * FROM saved_races ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/saved-races", methods=["POST"])
def api_save_race():
    """Save a race configuration for re-use."""
    data = request.get_json(silent=True)
    if not data or not data.get("name"):
        return jsonify({"error": "Race name is required"}), 400

    conn = get_pnl_db()
    cur = conn.execute("""
        INSERT INTO saved_races (name, distance_km, vertical_meters, profile_icon,
                                  stage_type, is_one_day_race, num_climbs, race_base_url, race_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["name"],
        data.get("distance_km"),
        data.get("vertical_meters"),
        data.get("profile_icon", "p3"),
        data.get("stage_type", "RR"),
        1 if data.get("is_one_day_race") else 0,
        data.get("num_climbs", 0),
        data.get("race_base_url"),
        data.get("race_date"),
    ))
    conn.commit()
    race_id = cur.lastrowid
    conn.close()
    return jsonify({"id": race_id, "message": "Race saved"})


@app.route("/api/saved-races/<int:race_id>", methods=["DELETE"])
def api_delete_saved_race(race_id):
    """Delete a saved race configuration."""
    conn = get_pnl_db()
    conn.execute("DELETE FROM saved_races WHERE id = ?", (race_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Deleted"})


# ── P&L Routes ──────────────────────────────────────────────────────────────

@app.route("/pnl")
def pnl_page():
    return render_template("pnl.html")


@app.route("/api/pnl/summary")
def api_pnl_summary():
    return jsonify(get_pnl_summary())


@app.route("/api/pnl/history")
def api_pnl_history():
    limit = request.args.get("limit", 50, type=int)
    return jsonify(get_bet_history(limit=limit))


@app.route("/api/pnl/bankroll", methods=["POST"])
def api_set_bankroll():
    data = request.json
    amount = data.get("bankroll")
    if not amount or float(amount) <= 0:
        return jsonify({"error": "Bankroll must be positive"}), 400
    set_initial_bankroll(float(amount))
    return jsonify({"bankroll": float(amount)})


@app.route("/api/pnl/bet", methods=["POST"])
def api_place_bet():
    data = request.json
    required = ["stage_url", "race_name", "rider_a_url", "rider_a_name",
                 "rider_b_url", "rider_b_name", "selection", "decimal_odds",
                 "model_prob", "kelly_fraction", "stake"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {missing}"}), 400

    try:
        bet_id = place_bet(
            stage_url=data["stage_url"],
            race_name=data["race_name"],
            race_date=data.get("race_date", ""),
            rider_a_url=data["rider_a_url"],
            rider_a_name=data["rider_a_name"],
            rider_b_url=data["rider_b_url"],
            rider_b_name=data["rider_b_name"],
            selection=data["selection"],
            decimal_odds=float(data["decimal_odds"]),
            model_prob=float(data["model_prob"]),
            kelly_fraction=float(data["kelly_fraction"]),
            stake=float(data["stake"]),
            model_used=data.get("model_used", ""),
            notes=data.get("notes", ""),
        )
        return jsonify({"bet_id": bet_id, "bankroll": get_current_bankroll()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/pnl/settle", methods=["POST"])
def api_settle_bet():
    data = request.json
    bet_id = data.get("bet_id")
    won = data.get("won")
    if bet_id is None or won is None:
        return jsonify({"error": "Need bet_id and won (true/false)"}), 400
    try:
        settle_bet(int(bet_id), bool(won))
        return jsonify({"ok": True, "bankroll": get_current_bankroll()})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pnl/void", methods=["POST"])
def api_void_bet():
    data = request.json
    bet_id = data.get("bet_id")
    if bet_id is None:
        return jsonify({"error": "Need bet_id"}), 400
    try:
        void_bet(int(bet_id))
        return jsonify({"ok": True, "bankroll": get_current_bankroll()})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pnl/auto-settle", methods=["POST"])
def api_auto_settle():
    count = auto_settle_from_results()
    return jsonify({"settled": count, "bankroll": get_current_bankroll()})



# ── Results Browser Routes ──────────────────────────────────────────────────

@app.route("/results")
@app.route("/results/<path:subpath>")
def results_page(subpath=None):
    return render_template("results.html")


@app.route("/api/results/races")
def api_results_races():
    """List races, optionally filtered by year or search query."""
    conn = get_db()
    year = request.args.get("year", type=int)
    q = (request.args.get("q") or "").strip().lower()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    offset = (page - 1) * per_page

    conditions, params = [], []
    if year:
        conditions.append("r.year = ?")
        params.append(year)
    if q:
        conditions.append("LOWER(r.name) LIKE ?")
        params.append(f"%{q}%")
    # Only show races that have at least one result
    conditions.append(
        "EXISTS (SELECT 1 FROM results res JOIN stages s2 ON res.stage_url = s2.url WHERE s2.race_url = r.url)"
    )

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    total = conn.execute(f"SELECT COUNT(*) as c FROM races r {where}", params).fetchone()["c"]
    rows = conn.execute(f"""
        SELECT r.url, r.name, r.year, r.nationality, r.is_one_day_race, r.category,
               r.uci_tour, r.startdate, r.enddate,
               (SELECT COUNT(*) FROM stages s WHERE s.race_url = r.url) as stage_count,
               (SELECT COUNT(*) FROM results res JOIN stages s2 ON res.stage_url = s2.url WHERE s2.race_url = r.url) as result_count
        FROM races r {where}
        ORDER BY r.startdate DESC
        LIMIT ? OFFSET ?
    """, params + [per_page, offset]).fetchall()

    years = [r["year"] for r in conn.execute("""
        SELECT DISTINCT r.year FROM races r
        WHERE EXISTS (SELECT 1 FROM results res JOIN stages s ON res.stage_url = s.url WHERE s.race_url = r.url)
        ORDER BY year DESC
    """).fetchall()]
    conn.close()

    return jsonify({
        "races": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "years": years,
    })


@app.route("/api/results/stages")
def api_results_stages():
    """List stages for a race."""
    race_url = request.args.get("race_url")
    if not race_url:
        return jsonify({"error": "race_url required"}), 400

    conn = get_db()
    stages = conn.execute("""
        SELECT s.url, s.stage_name, s.date, s.distance, s.vertical_meters,
               s.profile_score, s.profile_icon, s.avg_speed_winner,
               s.avg_temperature, s.departure, s.arrival, s.stage_type,
               s.num_climbs,
               (SELECT COUNT(*) FROM results r WHERE r.stage_url = s.url) as finishers
        FROM stages s
        WHERE s.race_url = ?
          AND EXISTS (SELECT 1 FROM results r WHERE r.stage_url = s.url)
        ORDER BY s.date, s.url
    """, (race_url,)).fetchall()

    race = conn.execute("SELECT * FROM races WHERE url = ?", (race_url,)).fetchone()
    conn.close()

    return jsonify({
        "race": dict(race) if race else None,
        "stages": [dict(s) for s in stages],
    })


@app.route("/api/results/stage")
def api_results_stage():
    """Full results for a single stage."""
    stage_url = request.args.get("stage_url")
    if not stage_url:
        return jsonify({"error": "stage_url required"}), 400

    conn = get_db()
    stage = conn.execute("SELECT * FROM stages WHERE url = ?", (stage_url,)).fetchone()
    results = conn.execute("""
        SELECT r.rank, r.rider_url, r.rider_name, r.team_name, r.age,
               r.nationality, r.time_str, r.bonus, r.pcs_points, r.uci_points,
               r.breakaway_kms, r.status
        FROM results r
        WHERE r.stage_url = ?
        ORDER BY CASE WHEN r.rank IS NULL THEN 999999 ELSE r.rank END
    """, (stage_url,)).fetchall()
    conn.close()

    return jsonify({
        "stage": dict(stage) if stage else None,
        "results": [dict(r) for r in results],
    })


@app.route("/api/results/rider")
def api_results_rider():
    """All results for a specific rider."""
    rider_url = request.args.get("rider_url")
    if not rider_url:
        return jsonify({"error": "rider_url required"}), 400

    q = (request.args.get("q") or "").strip().lower()
    year = request.args.get("year", type=int)
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 100, type=int)
    offset = (page - 1) * per_page

    conn = get_db()
    rider = conn.execute("SELECT * FROM riders WHERE url = ?", (rider_url,)).fetchone()

    conditions = ["r.rider_url = ?"]
    params = [rider_url]
    if year:
        conditions.append("rac.year = ?")
        params.append(year)
    if q:
        conditions.append("LOWER(rac.name) LIKE ?")
        params.append(f"%{q}%")

    where = " AND ".join(conditions)

    total = conn.execute(f"""
        SELECT COUNT(*) as c FROM results r
        JOIN stages s ON r.stage_url = s.url
        JOIN races rac ON s.race_url = rac.url
        WHERE {where}
    """, params).fetchone()["c"]

    results = conn.execute(f"""
        SELECT r.rank, r.rider_name, r.team_name, r.time_str, r.pcs_points,
               r.uci_points, r.breakaway_kms, r.status, r.age,
               s.url as stage_url, s.stage_name, s.date, s.distance,
               s.vertical_meters, s.profile_icon, s.stage_type,
               rac.name as race_name, rac.year, rac.url as race_url
        FROM results r
        JOIN stages s ON r.stage_url = s.url
        JOIN races rac ON s.race_url = rac.url
        WHERE {where}
        ORDER BY s.date DESC
        LIMIT ? OFFSET ?
    """, params + [per_page, offset]).fetchall()

    conn.close()

    return jsonify({
        "rider": dict(rider) if rider else None,
        "results": [dict(r) for r in results],
        "total": total,
        "page": page,
        "per_page": per_page,
    })


@app.route("/api/results/search")
def api_results_search():
    """Global search across races, riders, stages."""
    q = (request.args.get("q") or "").strip().lower()
    if len(q) < 2:
        return jsonify({"races": [], "riders": []})

    conn = get_db()
    races = conn.execute("""
        SELECT url, name, year, is_one_day_race, category
        FROM races WHERE LOWER(name) LIKE ? ORDER BY year DESC LIMIT 15
    """, (f"%{q}%",)).fetchall()

    riders = conn.execute("""
        SELECT ri.url, ri.name, ri.nationality,
               (SELECT COUNT(*) FROM results r WHERE r.rider_url = ri.url) as race_count
        FROM riders ri WHERE LOWER(ri.name) LIKE ? ORDER BY ri.name LIMIT 15
    """, (f"%{q}%",)).fetchall()

    conn.close()
    return jsonify({
        "races": [dict(r) for r in races],
        "riders": [dict(r) for r in riders],
    })


# ─── Admin: Script Runner ─────────────────────────────────────────────

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VENV_PYTHON = os.path.join(_REPO_ROOT, ".venv", "bin", "python")

# Track running processes: script_name → {process, output_queue, start_time, status}
_running_scripts = {}
_script_lock = threading.Lock()

SCRIPTS = {
    "update_data": {
        "label": "Update Data",
        "description": "Fetch new race results since last scrape",
        "cmd": [_VENV_PYTHON, "-u", os.path.join(_REPO_ROOT, "scripts", "update_races.py")],
    },
    "precompute": {
        "label": "Precompute Features",
        "description": "Rebuild feature caches (rider + race parquet files)",
        "cmd": [_VENV_PYTHON, "-u", os.path.join(_REPO_ROOT, "scripts", "precompute_features.py")],
    },
    "train": {
        "label": "Train Models",
        "description": "Full training pipeline (WT-only, ~15 min)",
        "cmd": ["caffeinate", "-s", _VENV_PYTHON, "-u",
                os.path.join(_REPO_ROOT, "scripts", "train.py"), "--wt-only"],
    },
}


def _stream_output(proc, q, script_name):
    """Read process stdout/stderr line by line into a queue."""
    try:
        for line in iter(proc.stdout.readline, ""):
            if line:
                q.put(line.rstrip("\n"))
        proc.wait()
    finally:
        exit_code = proc.returncode
        status = "done" if exit_code == 0 else "error"
        q.put(f"__EXIT__{exit_code}")
        with _script_lock:
            if script_name in _running_scripts:
                _running_scripts[script_name]["status"] = status
                _running_scripts[script_name]["exit_code"] = exit_code


@app.route("/admin")
def admin():
    return render_template("admin.html")


@app.route("/api/admin/scripts")
def admin_scripts():
    """List available scripts and their current status."""
    result = []
    with _script_lock:
        for key, info in SCRIPTS.items():
            state = _running_scripts.get(key, {})
            result.append({
                "id": key,
                "label": info["label"],
                "description": info["description"],
                "status": state.get("status", "idle"),
                "start_time": state.get("start_time"),
                "exit_code": state.get("exit_code"),
            })
    return jsonify(result)


@app.route("/api/admin/run/<script_id>", methods=["POST"])
def admin_run_script(script_id):
    """Start a script. Returns error if already running."""
    if script_id not in SCRIPTS:
        return jsonify({"error": f"Unknown script: {script_id}"}), 404

    with _script_lock:
        existing = _running_scripts.get(script_id, {})
        if existing.get("status") == "running":
            return jsonify({"error": "Script is already running"}), 409

    script = SCRIPTS[script_id]
    q = queue.Queue()

    proc = subprocess.Popen(
        script["cmd"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=_REPO_ROOT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    with _script_lock:
        _running_scripts[script_id] = {
            "process": proc,
            "queue": q,
            "start_time": time.time(),
            "status": "running",
            "exit_code": None,
        }

    t = threading.Thread(target=_stream_output, args=(proc, q, script_id), daemon=True)
    t.start()

    return jsonify({"status": "started", "pid": proc.pid})


@app.route("/api/admin/stream/<script_id>")
def admin_stream(script_id):
    """SSE endpoint — streams script output line by line."""
    def generate():
        with _script_lock:
            state = _running_scripts.get(script_id)
        if not state:
            yield f"data: Script not running\n\n"
            return

        q = state["queue"]
        while True:
            try:
                line = q.get(timeout=1.0)
                if line.startswith("__EXIT__"):
                    code = line.replace("__EXIT__", "")
                    yield f"event: done\ndata: {code}\n\n"
                    return
                yield f"data: {line}\n\n"
            except queue.Empty:
                # Check if process is still alive
                with _script_lock:
                    s = _running_scripts.get(script_id, {})
                if s.get("status") != "running":
                    yield f"event: done\ndata: {s.get('exit_code', -1)}\n\n"
                    return
                yield f": keepalive\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/admin/stop/<script_id>", methods=["POST"])
def admin_stop_script(script_id):
    """Stop a running script."""
    with _script_lock:
        state = _running_scripts.get(script_id)
        if not state or state["status"] != "running":
            return jsonify({"error": "Script not running"}), 404
        proc = state["process"]

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

    with _script_lock:
        if script_id in _running_scripts:
            _running_scripts[script_id]["status"] = "stopped"

    return jsonify({"status": "stopped"})


if __name__ == "__main__":
    app.run(debug=True, port=5001)
