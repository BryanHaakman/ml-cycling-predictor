# PaceIQ Daily Intelligence Pipeline — Design Spec

**Date:** 2026-04-10
**Status:** Approved
**Milestone:** v1.0

---

## What We're Building

An autonomous twice-daily pipeline that replaces the current fully manual betting workflow. Every morning and evening, the system pulls Pinnacle H2H cycling odds, resolves rider names to PCS identities, fetches stage context, runs model predictions on every available matchup, performs qualitative intelligence research per race, and delivers a structured email report. The user opens one email, reviews ranked matchups with both model sizing and qualitative flags, then places bets manually on Pinnacle.

**Goal:** Reduce the workflow from ~30 minutes of manual work per session to opening one email and making decisions.

---

## What This Is Not (Explicit Out of Scope)

- Automated bet placement — manual Pinnacle placement is permanent for this milestone
- Quantitative Kelly adjustment from qual signals — informational only for now (future milestone)
- CLV tracking automation — manual for now
- Multi-user support — personal tool only
- Real-time odds monitoring — twice daily is sufficient (not chasing live line movement)

---

## Architecture

Everything runs on the existing Hostinger VPS alongside n8n.

```
Hostinger VPS
├── n8n (existing)
│   ├── Cron: 17:00 local + 22:00 local
│   ├── HTTP node → POST /api/pipeline/run on Flask app (trigger only)
│   └── Email node → deliver report_html from Flask response to inbox
│
└── PaceIQ Flask app (deployed here)
    ├── All existing routes unchanged
    ├── POST /api/pipeline/run — pipeline trigger endpoint
    │   ├── Fetches odds from Pinnacle internal API (session cookie)
    │   ├── Resolves names → PCS URLs
    │   ├── Fetches stage context via MCP server
    │   ├── Runs model predictions on all matchups
    │   ├── Runs qualitative research per race
    │   └── Returns {"status": "ok", "report_html": "..."}
    └── Bet logging UI (existing, enhanced)
```

n8n's only job is to trigger the pipeline on schedule and deliver the email. All data fetching and intelligence logic lives in Python.

n8n orchestrates scheduling and delivery. Flask app does all ML and intelligence work. Clean separation of concerns.

---

## Component Design

### 1. Odds Ingestion (`data/odds.py`)

Hits Pinnacle's internal API (the same endpoint their web frontend calls) using a stored session cookie. Runs twice daily at 17:00 and 22:00 local time, triggered by n8n cron.

**Output:** List of `OddsMarket` objects:
```python
@dataclass
class OddsMarket:
    market_id: str
    race_name: str
    stage_name: str
    rider_a_name: str      # Pinnacle display name
    rider_b_name: str
    odds_a: float          # decimal odds
    odds_b: float
    fetched_at: datetime
```

**Design decisions:**
- Session cookie stored as environment variable on VPS — never committed to git
- If cookie expires, pipeline fails gracefully and emails an alert instead of a report
- All raw odds saved to `data/odds_log.jsonl` for audit trail (append-only)
- No retry on Pinnacle auth failure — flag it and move on

---

### 2. Name Resolver (`data/name_resolver.py`)

Maps Pinnacle display names to PCS rider URLs. The hard part: accents, abbreviations, ordering differences ("Van der Poel, Mathieu" vs "Mathieu van der Poel").

**Strategy:**
1. Check `data/name_mappings.json` (confirmed matches cache) — O(1) lookup
2. If miss: fuzzy match against all riders in `cache.db` using normalized names (strip accents, lowercase, sort tokens)
3. If fuzzy match confidence > 0.85: auto-accept, add to cache
4. If confidence 0.70–0.85: log to `data/unresolved_names.json` for manual confirmation; use best guess for this run
5. If confidence < 0.70: skip matchup, note in report as "name unresolved"

**Cache file format** (`data/name_mappings.json`):
```json
{
  "Mathieu van der Poel": "https://www.procyclingstats.com/rider/mathieu-van-der-poel",
  "Pogacar Tadej": "https://www.procyclingstats.com/rider/tadej-pogacar"
}
```

Cache grows over time. After one season, nearly all top riders are resolved automatically.

---

### 3. Stage Context (`intelligence/stage_context.py`)

Uses the existing PCS MCP server to fetch stage details. Takes the race name from the Pinnacle market, resolves it to a PCS race URL, then pulls:
- Stage type (RR / ITT / TTT)
- Distance, elevation gain, climb count and categories
- Profile icon (flat / hilly / mountain)
- Race tier (UCI WT, 2.UWT, etc.)

This replaces manually filling in stage details in the prediction UI. The resolved stage context is passed directly into the existing prediction pipeline as a `stage_row`.

**Fallback:** If MCP resolution fails, use neutral defaults and flag the report section as "Stage context unavailable — verify manually."

---

### 4. Prediction Engine (existing `models/predict.py`)

No changes to the core predictor. The pipeline calls the existing `Predictor.predict()` for each resolved matchup, passing the stage context from component 3 and the rider URLs from component 2.

**Output per matchup:**
- `model_prob`: model's win probability for rider A
- `implied_prob_a`: 1 / odds_a (Pinnacle implied)
- `edge`: model_prob - implied_prob_a
- `kelly_fraction`: half Kelly, capped at 10% bankroll
- `kelly_dollars`: fraction × current bankroll (read from P&L tracker)

Edge tiers:
- **ACT**: edge > 8%
- **FLAG**: edge 5–8%
- **MONITOR**: edge 1–5%
- **NO EDGE**: edge ≤ 0% (still shown, qual may be interesting)

---

### 5. Qualitative Intelligence (`intelligence/qualitative.py`)

One research job per race (not per matchup). Searches for tactical signals affecting that day's stage.

**Sources queried (via web search):**
- CyclingNews and VeloNews (previews, injury reports, team statements)
- ProCyclingStats race news tab
- Twitter/X: rider accounts, team accounts, known cycling journalists
- Reddit r/peloton (community intelligence, race thread)

**Claude API call:** Single call per race with all search results as context. Prompt extracts:
- Domestique / protected rider designations
- Injury or illness flags (any rider in the startlist)
- Previous day fatigue signals (hard attack, long breakaway)
- Team strategy signals (sprint lead-out assignments, GC protection)
- General social sentiment or notable discussion

**Output per race** (`QualIntel` object):
```python
@dataclass
class QualIntel:
    race_name: str
    stage_name: str
    race_summary: str          # 2-3 sentence tactical overview
    rider_flags: dict[str, RiderFlag]  # keyed by PCS URL

@dataclass
class RiderFlag:
    rider_url: str
    flag_type: str             # "domestique" | "fatigue" | "injury" | "protected" | "none"
    flag_detail: str           # human-readable explanation
    confidence: str            # "high" | "medium" | "low"
    sources: list[str]         # URLs or source names
    qual_recommendation: str   # "skip" | "reduce" | "proceed" | "boost" | "no signal"
```

**Cost estimate:** ~5-10 races/day × 1 Claude Sonnet call = ~$0.05–0.15/day. Negligible.

---

### 6. Report Generator (`intelligence/report.py`)

Assembles all components into a structured HTML email. One report per pipeline run.

**Structure:**
```
PaceIQ Intelligence Report
[Race Name] — [Date] — [Run time]

For each race:
  RACE CONTEXT
    Stage details (auto-fetched)
    Tactical summary (from qual intel)

  MATCHUPS (all of them, sorted by edge descending)
    [ACT / FLAG / MONITOR / NO EDGE] badge
    Rider A vs Rider B
    Model prob | Pinnacle implied | Edge
    Model Kelly: X% ($Y on $Z bankroll)
    Qual flag (if any): [flag detail + source]
    Qual recommendation: proceed / reduce / skip / no signal

  UNRESOLVED MATCHUPS (name match failures)
    Listed with Pinnacle names for manual lookup
```

**Design decisions:**
- HTML email with inline CSS (no external dependencies)
- Plain text fallback included for email clients that strip HTML
- Report also saved to `data/reports/YYYY-MM-DD-HH.html` for archive
- Bankroll dollar amount pulled from P&L tracker at report generation time

---

### 7. Bet Logging (enhanced existing UI)

The existing Flask bet logging UI gets one enhancement: a pre-fill endpoint.

`GET /bets/prefill?market_id=XYZ` returns a form pre-populated with:
- Race, stage, matchup, odds (from the odds log)
- Recommended stake (from report)

User adjusts stake based on qual recommendation, clicks submit. Bet is logged to `data/bets.csv` with all fields.

No structural changes to `data/bets.csv` schema.

---

### 8. Pipeline Trigger Endpoint (`webapp/app.py`)

New route: `POST /api/pipeline/run`

- Protected by `_require_localhost` decorator (n8n calls via `http://localhost:5001` from same VPS) OR a shared secret header
- On trigger: fetches Pinnacle odds itself via `data/odds.py`, then runs components 2–6 synchronously
- Returns `{"status": "ok", "report_html": "..."}` to n8n
- n8n sends the HTML as email body

**Error handling:**
- Any component failure → partial report with error section, still emailed
- Pinnacle auth failure → "Pinnacle session expired" alert email instead of report
- MCP failure → report continues with "stage context unavailable" note
- Qual failure → report continues without qual section, noted

---

### 9. n8n Workflow Design

Two workflows (or one with two cron triggers):

**Trigger:** Cron at 17:00 and 22:00 local time

**Steps:**
1. HTTP POST → `http://localhost:5001/api/pipeline/run` (no payload — Flask fetches odds itself)
2. If response OK → Email node → send `report_html` to configured address
3. If response error → Email node → send error alert

Pinnacle session cookie stored as environment variable on VPS, accessed by Flask app directly. n8n has no credentials for Pinnacle.

---

## Deployment

**Target:** Hostinger VPS alongside existing n8n.

**Steps (implementation phase):**
1. Install Python 3.11 + pip on VPS (if not present)
2. Clone repo, install requirements
3. Set environment variables: `ANTHROPIC_API_KEY`, `PINNACLE_SESSION_COOKIE`, `BANKROLL`
4. Run Flask app as a systemd service on port 5001
5. Configure n8n workflows (cron + HTTP + email)
6. Test with a single manual trigger before enabling schedule

**No Docker required** — keep it simple for a personal tool.

---

## Data + Files Added

| File | Purpose |
|------|---------|
| `data/odds.py` | Pinnacle API client |
| `data/name_resolver.py` | Fuzzy name matching |
| `data/name_mappings.json` | Confirmed name → PCS URL cache |
| `data/unresolved_names.json` | Names needing manual confirmation |
| `data/odds_log.jsonl` | Append-only raw odds audit log |
| `data/reports/` | Archived HTML reports |
| `intelligence/stage_context.py` | MCP-based stage detail fetcher |
| `intelligence/qualitative.py` | Claude-powered qual research |
| `intelligence/report.py` | Report assembler |

**Files modified:**
- `webapp/app.py` — add `/api/pipeline/run` endpoint + `/bets/prefill` endpoint
- `.env.example` — document new env vars

---

## What Success Looks Like

- Report arrives in inbox at 17:00 and 22:00 without touching a computer
- All Pinnacle matchups for that day's races are present in the report
- Name resolution works for >95% of top-tier riders without manual intervention
- Stage context is auto-populated (no manual distance/climb entry)
- Qual flags correctly identify domestique roles and fatigue signals when news is available
- Bet can be logged from the report in under 60 seconds

---

## Future Milestone Hooks (not in scope now)

- Quantitative Kelly adjustment: `qual_adjustment_factor` field added to `RiderFlag` (currently always 1.0)
- CLV tracking: `closing_odds` field in odds log enables future automation
- Startlist-aware predictions: stage context fetch already pulls startlist, pipeline can pass it to `build_feature_vector_manual`

---

*Spec written: 2026-04-10*
