# Coding Conventions
> Python ML project with consistent style across all modules — no formatter enforced but patterns are uniform.

## Overview

This is a pure Python project with no linting or formatting configuration files (no `.flake8`, `.pylintrc`, `pyproject.toml`, or `setup.cfg`). Despite this, the codebase applies consistent informal conventions throughout all modules. The project is research-oriented, with code quality driven by the `decision_log.md` requirement rather than automated tooling.

---

## Formatting & Style

**No formatter is configured.** There is no `black`, `ruff`, `isort`, or `prettier` config. Style is maintained by convention.

**Line length:** Long lines are common and not constrained. `features/pipeline.py` has lines exceeding 100 characters.

**Indentation:** 4 spaces throughout, consistent across all files.

**Blank lines:** Two blank lines between top-level functions/classes; one blank line inside functions between logical blocks. Section separators use `# ---` comment dividers:
```python
# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
```

**Trailing whitespace:** Not consistently controlled (no formatter enforced).

---

## Naming Conventions

**Functions:** `snake_case` throughout. Private functions (not meant for external use) are prefixed with a single underscore:
- `_rate_limit()` — `data/scraper.py`
- `_pcs_fetch()` — `data/scraper.py`
- `_create_tables()` — `data/scraper.py`
- `_safe_float()` — nested inside `scrape_stage()` in `data/scraper.py`
- `_rider_age_at_date()` — `features/rider_features.py`
- `_elapsed()` — `scripts/train.py`

**Variables:** `snake_case`. Loop variables follow domain naming (`race_url`, `stage_url`, `rider_url`). Temporary/inner variables use short names (`rq`, `rf_val`, `pct_q`).

**Constants:** `UPPER_SNAKE_CASE`:
- `DB_PATH`, `REQUEST_DELAY`, `MAX_RETRIES`, `FETCH_TIMEOUT` — `data/scraper.py`
- `RACE_FEATURE_NAMES`, `RIDER_FEATURE_NAMES` — `features/` modules
- `MODELS_DIR` — `models/benchmark.py`, `models/predict.py`
- `TABLES` — `scripts/export_data.py`

**Classes:** `PascalCase`. There are few classes — `_FetchTimeout` (exception), `KellyResult` (dataclass), `Predictor`.

**Feature naming:** Features use systematic prefixes that the pipeline relies on programmatically:
- `race_*` — race-level features
- `diff_*` — differenced rider features (A minus B)
- `a_*` / `b_*` — absolute features for rider A and rider B
- `h2h_*` — head-to-head history features
- `interact_*` — interaction/cross features

**Database keys:** URL strings serve as primary keys (`races.url`, `stages.url`, `riders.url`). These are PCS path segments like `race/tour-de-france/2025`.

---

## Module-Level Structure

Every Python module begins with a module docstring. The pattern is:
```python
"""
Short description of what this module does.

Additional context if needed.
"""
```

Example from `data/scraper.py`:
```python
"""
SQLite-backed cache and data scraper for ProCyclingStats.

Scrapes race results, rider profiles, and race characteristics.
All data is cached in SQLite to avoid redundant requests.
Rate-limited to ~1 request/second.
"""
```

Modules that are CLI entry points begin with `#!/usr/bin/env python3` before the docstring.

---

## Import Organization

Scripts that are CLI entry points follow a strict import order enforced by architecture requirements:

```python
#!/usr/bin/env python3
"""Module docstring."""

import os
os.environ["OMP_NUM_THREADS"] = "1"   # thread config before imports
os.environ["MKL_NUM_THREADS"] = "1"

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# stdlib
import logging
import argparse

# third-party
import pandas as pd
import numpy as np

# project
from data.scraper import get_db, DB_PATH
from features.pipeline import build_feature_matrix
```

The `sys.path.insert(0, repo_root)` pattern appears in every script in `scripts/` and in `tests/test_export.py`. Project modules use absolute imports (e.g., `from data.scraper import get_db`), never relative imports.

Late/deferred imports are used deliberately where needed to avoid OpenMP conflicts:
```python
# Lazy import: neural_net imports torch which conflicts with XGBoost's OpenMP on macOS
# Import inside functions that need it instead
```

---

## Function Design

**Docstrings:** Key public functions have Google-style docstrings with `Args:` and `Returns:` sections. Private helpers often have single-line docstrings:
```python
def discover_races(year: int, tiers: list[str] = None) -> list[str]:
    """Discover race base URLs from PCS calendar pages for a given year.

    Args:
        year: Calendar year to discover races for.
        tiers: List of calendar tier keys from RACE_CALENDAR_URLS.
               Defaults to ["worldtour", "proseries"] ...

    Returns:
        Sorted list of unique race base URLs (e.g., "race/tour-de-france").
    """
```

**Type hints:** Used on public function signatures but not universally. `Optional[str]`, `list[int]`, `tuple[pd.DataFrame, ...]` appear throughout. Inner variables are generally untyped.

**Return types:** Functions that can fail return `None` or `False` rather than raising. Pattern:
- DB lookup functions return `Optional[str]` — `scrape_race_overview()` returns URL or `None`
- Scrape functions return `bool` — `scrape_stage()`, `scrape_rider()` return `True/False`
- Feature functions return `dict` — `compute_rider_features()`, `build_feature_vector()`

**Default arguments:** Mutable defaults (like `list[str] = None`) use the `None` sentinel pattern with inline defaulting, not mutable default arguments.

---

## Error Handling

**Strategy:** Catch-and-log with graceful degradation rather than propagation. The scraper never crashes on individual failures:
```python
except Exception as e:
    log.warning(f"Failed to scrape stage {stage_url}: {e}")
    return False
```

**Stub insertion on failure:** When a rider scrape fails, a minimal stub record is inserted to prevent infinite retries on future runs:
```python
except Exception as e:
    log.debug(f"Rider parse failed for {rider_url}: {e} — inserting stub")
    try:
        conn.execute("INSERT OR IGNORE INTO riders (url, name, ...) VALUES ...")
    except Exception:
        pass
    return False
```

**Specific exception types for parse errors:** `(ValueError, TypeError)` are caught separately from network errors, with different log levels (`debug` vs `warning`):
```python
try:
    data = stage.parse()
except (ValueError, TypeError) as parse_err:
    log.debug(f"Skipping {stage_url}: incomplete data on PCS ({parse_err})")
    return False
```

**Safe numeric conversion:** The `_safe_float()` helper is used extensively to handle PCS's non-numeric placeholders like `"-"`.

**Flask error handlers:** The web app registers explicit `@app.errorhandler` decorators for 400, 404, 500 that return JSON for API routes:
```python
@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(500)
def handle_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": str(e)}), e.code if hasattr(e, 'code') else 500
```

---

## Logging

**Framework:** Python stdlib `logging`. Every module that does any I/O or computation gets its own logger:
```python
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
```

**Log levels used:**
- `log.info()` — normal progress: "Scraped stage: ...", "=== Step 1: Building H2H pairs ==="
- `log.warning()` — recoverable problems: server errors, failed scrapes, fallbacks
- `log.debug()` — noisy details suppressed in production: parse failures, skips
- No `log.error()` observed — errors are either warnings (handled) or raised

**Progress bars:** `tqdm` wraps long loops in scrape and feature-building code:
```python
for race_base in tqdm(races, desc=f"Year {year}"):
    scrape_full_race(conn, race_base, year, force=force)
```

**Milestone logging:** Training scripts log elapsed time between pipeline steps using a `_elapsed()` helper.

---

## Comments

**Section headers:** Long files use ASCII divider comments to separate major sections:
```python
# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------
```

**Inline comments:** Used generously to explain non-obvious logic — SQL query intent, magic numbers, algorithm decisions:
```python
# Prevent ordering bias: randomly swap A/B
# Top-50 finishers only, up to 200 pairs per stage
# Only uses pre-race data (no leakage)
```

**Decision rationale in comments:** Important constraints are documented inline alongside the code:
```python
# Lazy import: neural_net imports torch which conflicts with XGBoost's OpenMP on macOS
# Import inside functions that need it instead
```

---

## Database Access

**Always use `get_db()`** from `data.scraper`. This sets WAL mode, enables foreign keys, and attaches the `sqlite3.Row` factory. Raw `sqlite3.connect()` is not used.

**Parameterised queries:** All queries use `?` placeholders:
```python
conn.execute("SELECT url FROM races WHERE url = ?", (race_url,))
```

**No ORM.** Raw SQL throughout. Multi-row inserts use `executemany()` in some scripts; others use a for-loop with `execute()`.

---

## Thread Safety Convention

Scripts that use both PyTorch and scikit-learn set single-thread environment variables **before any imports**:
```python
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
```
And after torch import:
```python
torch.set_num_threads(1)
```
Random Forest models use `n_jobs=1`. This pattern must be maintained to avoid macOS deadlocks.

---

## Script Entry Point Pattern

All CLI scripts in `scripts/` follow this structure:
```python
#!/usr/bin/env python3
"""Docstring."""
# env vars before imports
import os, sys
sys.path.insert(0, ...)
# imports
import argparse
# ...

def main():
    parser = argparse.ArgumentParser(...)
    # ...

if __name__ == "__main__":
    main()
```

---

## Key Observations

- No automated formatting or linting tools are configured — conventions are maintained manually
- Private functions consistently use the `_prefix` convention; this is the only access-control mechanism used
- The f-string format for log messages is universal (no `%s` formatting)
- `Optional[T]` return types signal graceful failure rather than exception raising — callers must check for `None`/`False`
- Feature name prefixes (`race_`, `diff_`, `a_`, `b_`, `interact_`) are load-bearing — the pipeline builds and checks these programmatically in `features/pipeline.py`
- The decision log (`decision_log.md`) is the required record for all ML experiments, not code comments
- Module docstrings are present on all source files; function docstrings are present on public API functions but not consistently on private helpers
- No `dataclass` or `TypedDict` usage except for `KellyResult` in `models/predict.py`
