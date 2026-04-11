# External Integrations
> One external data source (ProCyclingStats) — keyless, HTTP-scraped via procyclingstats library.

## Overview

The project integrates with one external data source: ProCyclingStats for cycling race data (scraped via the `procyclingstats` library and `cloudscraper`). No paid APIs, authentication providers, or cloud platforms are used. All data is persisted locally in SQLite.

## APIs & External Services

**Cycling Data:**
- ProCyclingStats (`https://www.procyclingstats.com`) — primary data source for all race, stage, and rider data
  - SDK/Client: `procyclingstats>=0.2.0` (`data/scraper.py`) — wraps `Race`, `Stage`, `Rider` page objects
  - Cloudflare bypass: `cloudscraper>=1.2.71` (`data/scraper.py`) — used specifically for calendar discovery pages (`/races.php?year=...`)
  - Auth: None — public website, no API key
  - Rate limit: self-imposed 0.5 s delay between requests (`REQUEST_DELAY = 0.5` in `data/scraper.py`)
  - Retry logic: up to 3 retries with exponential backoff on HTTP 429/500/502/503 and Cloudflare errors
  - Timeout: 60 s per request via `ThreadPoolExecutor.future.result(timeout=60)` in `_pcs_fetch` (`data/scraper.py`) — cross-platform


## Data Storage

**Databases:**
- SQLite (Python stdlib `sqlite3`) — single file `data/cache.db` (gitignored)
  - Schema defined in `data/scraper.py` (`_create_tables`) and `data/pnl.py` (`_create_pnl_tables`)
  - Tables: `races`, `stages`, `results`, `riders`, `scrape_log`, `bets`, `bankroll_history`, `saved_races`
  - WAL mode enabled; foreign keys enforced
  - Connection: hardcoded path `data/cache.db` via `DB_PATH` constant in `data/scraper.py`
  - Snapshot: none committed to git (regenerate via `scripts/dump_db.py`)

**File Storage:**
- Local filesystem only
  - Feature cache: `data/rider_features_cache.parquet`, `data/race_features_cache.parquet`
  - Trained models: `models/trained/*.pkl`, `models/trained/benchmark_results.csv`
  - Data exports: `data/exports/` (gitignored CSV dumps)

**Caching:**
- SQLite serves as the cache layer — all PCS scrape results are persisted before use; scrape resumption is tracked via `scrape_log` table

## Authentication & Identity

**Auth Provider:** None — no user authentication, no session management, no login system

The Flask app (`webapp/app.py`) is unauthenticated. The admin panel at `/admin` exposes script execution (update data, train models) with no access control. This is intentional for a local-use tool.

## Monitoring & Observability

**Error Tracking:** None — no Sentry or equivalent

**Logs:**
- Python stdlib `logging` module throughout all modules
- Format: `"%(asctime)s %(levelname)s %(message)s"` at `INFO` level
- Output: stdout/stderr only — no log files, no structured logging
- Admin panel streams script stdout in real time via Server-Sent Events (`/api/admin/stream/<script_id>`)

## CI/CD & Deployment

**Hosting:** No production hosting detected

**CI Pipeline:**
- GitHub Actions — `.github/workflows/nightly-pipeline.yml`
- Schedule: `cron: '0 0 * * *'` (midnight UTC daily) + manual trigger via `workflow_dispatch`
- Runner: `ubuntu-latest`, timeout 60 minutes
- Python version: `3.11` with `pip` cache
- Actions used: `actions/checkout@v4`, `actions/setup-python@v5`
- Pipeline steps:
  1. Restore SQLite from `data/db_snapshot.sql.gz` (`scripts/load_db.py --force`)
  2. Fetch latest race data (`scripts/update_races.py --all-tiers --no-settle`)
  3. Dump updated snapshot (`scripts/dump_db.py`)
  4. Commit and push updated `data/db_snapshot.sql.gz` with message `"data: nightly snapshot YYYY-MM-DD"`
- Permissions: `contents: write`, `actions: write`

## Environment Configuration

**Required env vars:** None — no environment variables are read by any module

**Secrets:** None required — all integrations are keyless public APIs

**Notable absence:** No `.env` file, no `os.getenv()` calls for secrets, no config file beyond `requirements.txt`

## Webhooks & Callbacks

**Incoming:** None

**Outgoing:** None — the app only makes outbound HTTP requests to PCS during data collection scripts; the Flask app itself makes no outbound calls at request time

---

*Integration audit: 2026-04-10*
