# Testing Patterns
> Minimal pytest suite covering only the CSV export script — the ML pipeline, scraper, feature engineering, and models have no tests.

## Overview

The project has a single test file (`tests/test_export.py`) with 11 tests covering `scripts/export_data.py`. All tests use `pytest` with the `tmp_path` fixture to create isolated temporary SQLite databases. The rest of the codebase — scraping, feature engineering, model training, prediction, and the web app — has no automated test coverage.

---

## Test Framework

**Runner:** pytest (no version pinned in `requirements.txt`, not listed as a dev dependency)

**Config:** No `pytest.ini`, `pyproject.toml`, or `conftest.py` exists. Tests are discovered by pytest's default file/class/function naming conventions.

**Run commands:**
```bash
pytest tests/ -v                  # full suite (11 tests)
pytest tests/test_export.py -v    # single module
pytest tests/test_export.py::TestExportTable::test_csv_created -v  # single test
```

---

## Test File Organization

**Location:** `tests/` directory at project root. A single file exists: `tests/test_export.py`.

**`__init__.py`:** `tests/__init__.py` exists (empty), making `tests/` a Python package.

**Naming:** Test file matches `test_*.py` pattern. Test methods match `test_*` pattern. Test classes match `Test*` pattern.

**Structure:**
```
tests/
├── __init__.py
└── test_export.py       # 231 lines, 11 tests for scripts/export_data.py
```

---

## Test Structure

**Path injection:** Tests use the same `sys.path.insert` pattern as scripts:
```python
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data.scraper import get_db
from scripts.export_data import export_table, TABLES
```

**Test classes:** Tests are grouped into two classes by concern:
```python
class TestExportTable:
    """Tests for export_table function."""
    # 9 tests covering core export behaviour

class TestExportReimport:
    """Test that exported CSVs can be reimported to recreate the data."""
    # 1 test covering round-trip fidelity
```

**Setup via fixture:** A shared `test_db` fixture creates a fully-populated temporary SQLite database for all tests:
```python
@pytest.fixture
def test_db(tmp_path):
    """Create a temporary database with sample data."""
    db_path = str(tmp_path / "test.db")
    conn = get_db(db_path)
    # Insert sample race, stages, results (5), riders (3), scrape_log
    conn.commit()
    yield conn, tmp_path, db_path
    conn.close()
```

The fixture yields a 3-tuple `(conn, tmp_path, db_path)`. Tests destructure it:
```python
def test_exports_all_rows(self, test_db):
    conn, tmp_path, _ = test_db
```

---

## What Is Tested

**`tests/test_export.py` — `TestExportTable` (9 tests):**
- `test_exports_all_rows` — return value (row count) is correct
- `test_creates_csv_file` (`test_csv_created` per CLI docs) — output file is created
- `test_csv_has_header_row` — header contains expected column names
- `test_csv_row_count_matches_db` — 1 header + N data rows
- `test_csv_data_matches_db` — first row values match inserted data
- `test_exports_empty_table` — header-only CSV when table is empty, count returns 0
- `test_all_tables_exportable` — every table in `TABLES` list exports without error and creates a file
- `test_preserves_unicode` — Unicode characters (e.g., `Tadej Pogačar`) survive the CSV round-trip
- `test_handles_null_values` — NULL DB values appear as empty string or `"None"` in CSV

**`TestExportReimport` (1 test):**
- `test_round_trip_results` — export to CSV then re-read, verify all rows and key column values match

---

## What Is NOT Tested

The following core systems have zero test coverage:

- **`data/scraper.py`** — scraping logic, `_pcs_fetch()`, retry/backoff, `get_db()`, `_create_tables()`, all scrape functions
- **`data/builder.py`** — H2H pair generation, sampling, A/B swap logic
- **`features/pipeline.py`** — `build_feature_vector()`, `build_feature_matrix()`, H2H computation, startlist percentile calculations, all interaction features
- **`features/rider_features.py`** — all 78 rider feature computations, temporal filtering, terrain affinity
- **`features/race_features.py`** — race feature extraction, climb scoring
- **`features/feature_store.py`** — parquet cache load/save
- **`models/benchmark.py`** — training pipeline, time-based split, stratified split, all model training
- **`models/predict.py`** — `Predictor` class, `kelly_criterion()`, odds conversion functions
- **`models/neural_net.py`** — neural network architecture, training loop
- **`webapp/app.py`** — all Flask routes and API endpoints
- **`data/pnl.py`** — P&L tracking, bet placement, settlement
- **`scripts/`** — all CLI scripts (train, experiment, feature_selection, etc.)

---

## Assertions Style

Tests use plain `assert` statements throughout — no assertion library beyond pytest's built-in assertion rewriting:
```python
assert count == 1
assert os.path.exists(os.path.join(out_dir, "results.csv"))
assert "url" in header
assert len(rows) == 6
assert float(rows[0]["distance"]) == 250.5
assert "Tadej Pogačar" in names
assert stub["weight"] == "" or stub["weight"] == "None"
```

Multi-condition assertions use `or` for flexible tolerance (e.g., NULL export format).

---

## Fixtures and Test Data

**No fixtures directory or factory files.** All test data is inline in the `test_db` fixture. Sample data:
- 1 race (`race/test-race/2024`, Belgium, 2024)
- 1 stage with known distance (250.5 km), vertical meters (3200)
- 5 results with ranks 1–5 and descending PCS points
- 3 riders with Belgian nationality, varying weight/height
- 1 scrape_log entry

Tests that need additional data insert it directly inside the test method:
```python
conn.execute("""
    INSERT INTO riders (url, name, nationality)
    VALUES ('rider/tadej-pogacar', 'Tadej Pogačar', 'Slovenia')
""")
conn.commit()
```

---

## CI/CD

**No test step in CI.** The GitHub Actions workflow at `.github/workflows/nightly-pipeline.yml` runs only the data pipeline:
1. Restore database snapshot
2. `python scripts/update_races.py`
3. `python scripts/dump_db.py`
4. Commit snapshot

Tests are not run in CI. There is no separate test workflow.

---

## Coverage

**No coverage tooling configured.** No `pytest-cov`, no `.coveragerc`, no coverage badge or report.

Estimated code coverage by module:
| Module | Coverage |
|---|---|
| `scripts/export_data.py` | High — all key paths tested |
| Everything else | 0% |

---

## Key Observations

- Only 1 of ~15 source files has any test coverage; the tested file (`scripts/export_data.py`) is a utility script, not core ML logic
- The `test_db` fixture correctly uses `get_db()` from `data.scraper`, so tests exercise the real schema creation code
- The `test_all_tables_exportable` test acts as a smoke test that catches schema changes breaking the `TABLES` list
- No mocking is used anywhere — tests hit a real (in-memory/tmpdir) SQLite database
- Tests do not test for exception handling behaviour (e.g., what happens if a table name is invalid)
- The `test_handles_null_values` assertion `stub["weight"] == "" or stub["weight"] == "None"` reveals uncertainty about the actual NULL export format — this is a loose assertion
- No integration tests, no end-to-end tests, no model accuracy tests
- Adding a `conftest.py` with the shared `test_db` fixture would allow it to be reused across future test files without import overhead
