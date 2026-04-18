# Technology Stack — v2.0 Edge Validation & System Maturity

**Project:** PaceIQ
**Milestone:** v2.0 — CLV tracking, edge-bucket ROI analysis, model upgrades, automation
**Researched:** 2026-04-18
**Confidence:** HIGH (verified via PyPI, official docs, local pip inspection)

---

## Existing Stack (Validated in v1.0 — Do Not Re-research)

| Technology | Pinned | Confirmed Installed | Notes |
|------------|--------|---------------------|-------|
| Python | 3.11 | 3.11 | Runtime |
| Flask | >=3.0.0 | yes | Port 5001 |
| SQLite WAL | built-in | yes | `data/cache.db` — do not migrate |
| XGBoost | >=2.0.0 | 3.2.0 | See upgrade note below |
| scikit-learn | >=1.3.0 | 1.8.0 | |
| PyTorch | >=2.1.0 | yes | Neural net kept but not primary |
| pandas | >=2.0.0 | 3.0.2 | |
| numpy | >=1.24.0 | yes | |
| pyarrow | >=14.0.0 | yes | Parquet feature cache |
| scipy | >=1.7.0 | **1.17.1** | Already installed — covers all stats needs |
| rapidfuzz | >=3.0.0 | yes | Name resolution |
| requests | >=2.31.0 | yes | HTTP client |
| joblib | >=1.3.0 | yes | Model serialization |
| Jinja2 | Flask dep | yes | Already available — no separate install |

---

## New Additions Required for v2.0

Only two new packages need to be added to `requirements.txt`. Everything else in scope is already
available via the existing stack.

### 1. APScheduler 3.x — Background Job Scheduling

**Add:** `APScheduler>=3.10.0,<4.0`

**Current stable:** 3.11.2 (released December 22, 2025). Source: PyPI.

**Why APScheduler 3.x (not 4.x):** APScheduler 4.x is a near-complete API rewrite with
async-first design. The 4.x API is not backward-compatible with 3.x — `BackgroundScheduler`,
`CronTrigger`, and the job store interfaces all changed. 3.x (pinned `<4.0`) uses the well-known
pattern that integrates cleanly with a Flask single-worker setup and is battle-tested. The
`<4.0` upper bound prevents an accidental breaking upgrade.

**Why APScheduler over system cron:** The six automation jobs (closing-odds capture,
post-race settlement, pre-race briefing, edge alerts, drift monitor, data freshness) all need
access to `data/cache.db` and the same Python functions already used by Flask routes. System
cron forks a new process per invocation and cannot share the SQLite WAL connection pool safely
or reuse in-memory state (name resolver cache, loaded model). APScheduler runs in-process
inside the Flask worker — jobs call the same Python functions as routes, no code duplication.

**Why APScheduler over Celery/Dramatiq/RQ:** All task queue alternatives require a broker
(Redis or RabbitMQ). Adding message queue infrastructure violates the project's explicit
"no new infrastructure" constraint and is architecturally inappropriate for a personal
single-worker tool. APScheduler is a direct fit.

**Thread safety note:** `BackgroundScheduler` runs jobs in a thread pool. All SQLite access
in job functions must call `get_db()` to open a fresh connection — never pass a connection
object between threads. This matches the existing pattern in `data/pnl.py` where
`auto_settle_from_results` opens a new connection per iteration.

**Integration:** Initialize `BackgroundScheduler` in `webapp/app.py` after `app` is created.
Use `atexit.register(scheduler.shutdown)` for clean shutdown on process exit.

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit

scheduler = BackgroundScheduler()
scheduler.add_job(capture_closing_odds, CronTrigger(hour=11, minute=0))
scheduler.add_job(auto_settle_and_compute_clv, CronTrigger(hour=18, minute=0))
scheduler.add_job(generate_daily_report, CronTrigger(hour=8, minute=0))
scheduler.add_job(drift_check, CronTrigger(day_of_week="mon", hour=6))
scheduler.start()
atexit.register(scheduler.shutdown)
```

---

### 2. discord-webhook 1.x — Edge Alerts and Notifications

**Add:** `discord-webhook>=1.3.0`

**Current stable:** 1.4.1 (released March 5, 2025). Source: PyPI.

**Why discord-webhook over raw requests:** The library adds embed formatting (color-coded
alerts with structured fields), rate limit handling, and retry logic on top of `requests`.
For edge alerts and drift notifications, Discord embeds (color by severity: green for
confirmed edge, red for drift alert) are meaningfully more readable than plain text posts.
The library wraps `requests` internally — no new HTTP dependency is introduced.

**Why Discord over email:** Discord webhooks require zero SMTP configuration. The user
already uses Discord. Email via stdlib `smtplib` remains available as a fallback if needed
(no new dependency — stdlib only).

**Integration:** Create `intelligence/notifier.py`. Reads `DISCORD_WEBHOOK_URL` from
environment. All calls are fire-and-forget — on failure, log a warning and return without
raising (automation jobs must never crash because a notification failed).

```python
from discord_webhook import DiscordWebhook, DiscordEmbed
import os, logging

log = logging.getLogger(__name__)

def send_edge_alert(matchup: str, edge: float, model_prob: float, odds: float) -> bool:
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        log.warning("DISCORD_WEBHOOK_URL not set — skipping notification")
        return False
    try:
        webhook = DiscordWebhook(url=url)
        embed = DiscordEmbed(title="Edge Alert", color="03b2f8")
        embed.add_embed_field(name="Matchup", value=matchup, inline=False)
        embed.add_embed_field(name="Edge", value=f"{edge:.1%}", inline=True)
        embed.add_embed_field(name="Model prob", value=f"{model_prob:.1%}", inline=True)
        embed.add_embed_field(name="Odds", value=f"{odds:.2f}", inline=True)
        webhook.add_embed(embed)
        webhook.execute()
        return True
    except Exception as e:
        log.warning("send_edge_alert failed: %s", e)
        return False
```

---

## No New Install Required — Already Available

### Statistical Analysis — scipy 1.17.1 (confirmed installed)

All CLV significance testing and edge-bucket ROI analysis is covered by scipy already in
the environment. Do not add statsmodels.

**Functions to use:**

| Analysis | scipy function | Notes |
|----------|---------------|-------|
| Is average CLV > 0? | `scipy.stats.binomtest(wins, n, p=0.5)` | One-sided test on win rate vs implied prob |
| Wilson CI on win rate per edge bucket | Manual calculation using `scipy.stats.norm.ppf` | See pattern below |
| Pearson correlation: edge vs realized CLV | `scipy.stats.pearsonr(edges, clvs)` | Over settled bets |
| Calibration check: expected vs actual win rate | `scipy.stats.chi2_contingency` | Per confidence bin |

Wilson CI pattern (pure scipy, no statsmodels needed):
```python
from scipy.stats import norm

def wilson_ci(wins: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z = norm.ppf(1 - (1 - confidence) / 2)
    p = wins / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = (z * (p * (1 - p) / n + z**2 / (4 * n**2)) ** 0.5) / denom
    return (centre - half, centre + half)
```

**Why not statsmodels:** statsmodels provides `proportion_confint(method="wilson")` which
wraps the same calculation. It is a large dependency (~8 MB) that is not currently installed.
scipy's `norm.ppf` is all that's needed. Adding statsmodels would be dependency bloat.

---

### XGBRanker — Already in xgboost >=2.0.0

`XGBRanker` (pairwise LambdaRank for stage ranking) is part of the xgboost package.
Confirmed available in the installed 3.2.0. No additional install needed.

**XGBoost version note:** xgboost 3.2.0 (Feb 2026, currently installed) requires Python >=3.10.
The project runs Python 3.11 — compatible. The Python sklearn API is backward-compatible
from 2.x to 3.x: `XGBClassifier`, `CalibratedClassifierCV`, and `XGBRanker` all work
identically. The 3.x breaking changes were confined to the R and JVM packages.

**Current `requirements.txt` pin `>=2.0.0` is fine** — it already allows 3.x. No change needed.

**XGBRanker usage for MODEL-07 (phase 2):**
```python
from xgboost import XGBRanker

ranker = XGBRanker(
    objective="rank:pairwise",   # LambdaRank: pairwise loss, good for H2H
    n_estimators=300,
    learning_rate=0.05,
    max_depth=6,
    tree_method="hist",
)
# qid groups riders in the same stage together for pairwise comparison
ranker.fit(X_train, y_train, qid=stage_ids_train)
scores = ranker.predict(X_test)  # higher = predicted better finisher
```

The existing pair builder already groups by stage — `stage_ids_train` maps directly to
the existing stage-level stratification in `models/benchmark.py`.

---

### Markdown Report Generation — Jinja2 (Flask dependency, already installed)

Pre-race briefing reports (Phase 3 AUT-03) use Jinja2 templates rendered from a standalone
script. Flask depends on Jinja2, so it is already in the environment. No separate install.

**Pattern:** `scripts/generate_report.py` instantiates `jinja2.Environment` with
`FileSystemLoader` pointing at `reports/templates/`. Template `daily_brief.md.j2` is a
plain Jinja2 template that produces Markdown output. The script does not require Flask
app context — Jinja2 runs standalone.

```python
from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader("reports/templates"))
template = env.get_template("daily_brief.md.j2")
report = template.render(matchups=matchups, date=today)
with open(f"reports/{today}_brief.md", "w") as f:
    f.write(report)
```

---

### CLV Storage — SQLite migration (existing pattern)

CLV columns are added to the existing `bets` table in `data/cache.db` using the same
idempotent `ALTER TABLE` migration pattern already in `data/pnl.py`. No new library needed.

```python
# In _create_pnl_tables() — same pattern as race metadata columns in v1.0
migrations = [
    ("closing_odds", "REAL"),
    ("clv", "REAL"),                    # (closing_odds / bet_odds) - 1
    ("clv_captured_at", "TEXT"),
]
for col_name, col_type in migrations:
    if col_name not in existing:
        conn.execute(f"ALTER TABLE bets ADD COLUMN {col_name} {col_type}")
```

---

## What NOT to Add

| Rejected Dependency | Reason |
|---------------------|--------|
| `statsmodels` | scipy 1.17.1 already covers all needed tests (Wilson CI, binomtest, pearsonr). statsmodels is 8+ MB of additional dependencies for zero capability gain here. |
| `celery` | Requires Redis/RabbitMQ broker. Violates "no new infrastructure" constraint. Six lightweight in-process jobs do not need a distributed task queue. |
| `flask-apscheduler` | Adds a Flask extension wrapper over APScheduler, including a REST API for managing jobs. The REST API is unnecessary — jobs are configured at startup, not dynamically. Plain `BackgroundScheduler` is simpler. |
| `redis` | No message queue or distributed cache needed. SQLite WAL handles all persistence. |
| `sendgrid` / `mailgun` | External email API with API key management. Overkill for a personal tool. Discord webhook is the primary channel; stdlib `smtplib` covers email fallback. |
| `httpx` | `requests` already handles all HTTP needs. httpx adds async/HTTP2 support irrelevant to synchronous scheduled jobs. |
| `polars` | pandas 2.0 + pyarrow is integrated throughout the feature pipeline. Polars would require a new API and parallel data paths. No throughput issue at 292K pairs. |
| `mlflow` | Overkill for a personal tool. `decision_log.md` is the agreed experiment tracking mechanism. |
| `optuna` | No hyperparameter search planned in v2.0. Phase 2 model upgrades use manual configuration. |
| `playwright` | Used in v1.0 dev/discovery only. Not needed in v2.0 — Pinnacle guest API is confirmed zero-auth. |
| `python-crontab` | Manages OS crontab files. APScheduler in-process is the chosen approach; OS crontab manipulation is not needed. |
| `APScheduler>=4.0` | Breaking API rewrite, async-first, not backward-compatible. Provides no benefit for this use case. |

---

## Updated requirements.txt

Add exactly two lines:

```
APScheduler>=3.10.0,<4.0
discord-webhook>=1.3.0
```

All other v2.0 capabilities use libraries already in requirements.txt or Python stdlib.

---

## Integration Map

```
webapp/app.py
  └── BackgroundScheduler (APScheduler 3.x)
        ├── capture_closing_odds()    → data/odds.py (existing Pinnacle client, reused)
        ├── auto_settle_and_clv()     → data/pnl.py (existing settle_bet(), new CLV columns)
        ├── generate_daily_report()   → scripts/generate_report.py (new, Jinja2 standalone)
        ├── send_edge_alerts()        → intelligence/notifier.py (new, discord-webhook)
        ├── drift_check()             → models/predict.py + scipy.stats.binomtest
        └── data_freshness_check()   → data/scraper.py (existing scrape_log table)

intelligence/notifier.py              (new module)
  └── discord-webhook → DISCORD_WEBHOOK_URL env var (fire-and-forget, never raises)

data/pnl.py (extended)
  └── CLV columns via idempotent ALTER TABLE migration
      closing_odds REAL, clv REAL, clv_captured_at TEXT

features/pipeline.py (extended for MODEL-06)
  └── market_implied_prob added as feature — read from bets table at prediction time
      (uses opening odds at bet placement; closing odds captured separately for CLV)

models/benchmark.py (extended for MODEL-07)
  └── XGBRanker added alongside existing XGBClassifier + CalibratedXGBoost
      Uses existing stage-level grouping as qid array

scripts/generate_report.py            (new script)
  └── Jinja2 Environment (standalone, no Flask app context needed)
      reports/templates/daily_brief.md.j2 → reports/YYYY-MM-DD_brief.md
```

---

## Confidence Assessment

| Area | Confidence | Source |
|------|------------|--------|
| APScheduler 3.11.2 stable, `<4.0` pin prevents API break | HIGH | PyPI + official docs + version history |
| discord-webhook 1.4.1 current, embed support confirmed | HIGH | PyPI (Mar 2025) |
| scipy 1.17.1 installed, covers all stats needs | HIGH | Local `python -c "import scipy; print(scipy.__version__)"` |
| XGBRanker in xgboost >=2.0.0, Python API stable in 3.x | HIGH | Official XGBoost 2.x + 3.x docs |
| xgboost 3.x Python sklearn API backward-compatible | MEDIUM | Official 3.0 changelog (R/JVM breaking, Python not) |
| Jinja2 available via Flask dependency | HIGH | Flask dependency tree, confirmed installed |
| SQLite ALTER TABLE migration pattern works | HIGH | Existing pattern in data/pnl.py validated in v1.0 |

---

## Sources

- [APScheduler PyPI — 3.11.2](https://pypi.org/project/APScheduler/)
- [APScheduler 3.x User Guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html)
- [discord-webhook PyPI — 1.4.1](https://pypi.org/project/discord-webhook/)
- [python-discord-webhook GitHub](https://github.com/lovvskillz/python-discord-webhook)
- [XGBoost Learning to Rank — 2.x docs](https://xgboost.readthedocs.io/en/release_2.0.0/tutorials/learning_to_rank.html)
- [XGBoost Learning to Rank — 3.2.0 stable](https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html)
- [XGBoost 3.0.0 changelog](https://xgboost.readthedocs.io/en/latest/changes/v3.0.0.html)
- [xgboost PyPI — 3.2.0](https://pypi.org/project/xgboost/)
- [scipy stats docs — binomtest](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html)
- [Flask Jinja2 templating](https://flask.palletsprojects.com/en/stable/templating/)
- [Miguel Grinberg — Flask scheduled jobs](https://blog.miguelgrinberg.com/post/run-your-flask-regularly-scheduled-jobs-with-cron)

---

## Historical — v1.0 Pinnacle Preload Stack (2026-04-11)

The following was the v1.0 stack research. Kept for reference; do not re-research.

New libraries added in v1.0:
- `rapidfuzz>=3.14.3` — fuzzy name resolution
- `procyclingstats>=0.2.8` — stage context (pin upgrade from >=0.2.0)
- `playwright>=1.58.0` — dev/discovery only (not in production requirements.txt)

All other v1.0 capabilities used existing libraries (requests, json stdlib, unicodedata stdlib).
