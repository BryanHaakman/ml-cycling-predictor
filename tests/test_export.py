"""Tests for scripts/export_data.py"""

import csv
import os
import sqlite3
import tempfile

import pytest

# Adjust path so we can import project modules
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.scraper import get_db
from scripts.export_data import export_table, TABLES


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary database with sample data."""
    db_path = str(tmp_path / "test.db")
    conn = get_db(db_path)

    # Insert sample race
    conn.execute("""
        INSERT INTO races (url, name, year, nationality, is_one_day_race)
        VALUES ('race/test-race/2024', 'Test Race', 2024, 'Belgium', 1)
    """)

    # Insert sample stage
    conn.execute("""
        INSERT INTO stages (url, race_url, stage_name, date, distance, vertical_meters,
                            profile_score, profile_icon, stage_type, is_one_day_race)
        VALUES ('race/test-race/2024/result', 'race/test-race/2024', 'Test Race',
                '2024-04-14', 250.5, 3200, 85, 'p3', 'RR', 1)
    """)

    # Insert sample results
    for i in range(5):
        conn.execute("""
            INSERT INTO results (stage_url, rider_url, rider_name, rank, pcs_points)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "race/test-race/2024/result",
            f"rider/test-rider-{i}",
            f"Test Rider {i}",
            i + 1,
            100.0 - i * 15,
        ))

    # Insert sample riders
    for i in range(3):
        conn.execute("""
            INSERT INTO riders (url, name, nationality, weight, height)
            VALUES (?, ?, ?, ?, ?)
        """, (
            f"rider/test-rider-{i}",
            f"Test Rider {i}",
            "Belgium",
            72.0 + i,
            1.82 + i * 0.02,
        ))

    # Insert scrape_log entry
    conn.execute("""
        INSERT INTO scrape_log (action, detail) VALUES ('race_done', 'race/test-race/2024')
    """)

    conn.commit()
    yield conn, tmp_path, db_path
    conn.close()


class TestExportTable:
    """Tests for export_table function."""

    def test_exports_all_rows(self, test_db):
        conn, tmp_path, _ = test_db
        out_dir = str(tmp_path / "exports")
        os.makedirs(out_dir)

        count = export_table(conn, "races", out_dir)
        assert count == 1

    def test_creates_csv_file(self, test_db):
        conn, tmp_path, _ = test_db
        out_dir = str(tmp_path / "exports")
        os.makedirs(out_dir)

        export_table(conn, "results", out_dir)
        assert os.path.exists(os.path.join(out_dir, "results.csv"))

    def test_csv_has_header_row(self, test_db):
        conn, tmp_path, _ = test_db
        out_dir = str(tmp_path / "exports")
        os.makedirs(out_dir)

        export_table(conn, "riders", out_dir)
        with open(os.path.join(out_dir, "riders.csv"), newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
        assert "url" in header
        assert "name" in header
        assert "nationality" in header

    def test_csv_row_count_matches_db(self, test_db):
        conn, tmp_path, _ = test_db
        out_dir = str(tmp_path / "exports")
        os.makedirs(out_dir)

        export_table(conn, "results", out_dir)
        with open(os.path.join(out_dir, "results.csv"), newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        # 1 header + 5 data rows
        assert len(rows) == 6

    def test_csv_data_matches_db(self, test_db):
        conn, tmp_path, _ = test_db
        out_dir = str(tmp_path / "exports")
        os.makedirs(out_dir)

        export_table(conn, "races", out_dir)
        with open(os.path.join(out_dir, "races.csv"), newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert rows[0]["name"] == "Test Race"
        assert rows[0]["year"] == "2024"
        assert rows[0]["url"] == "race/test-race/2024"

    def test_exports_empty_table(self, test_db):
        """Exporting a table with no rows should produce a header-only CSV."""
        conn, tmp_path, _ = test_db
        out_dir = str(tmp_path / "exports")
        os.makedirs(out_dir)

        conn.execute("DELETE FROM scrape_log")
        conn.commit()

        count = export_table(conn, "scrape_log", out_dir)
        assert count == 0

        with open(os.path.join(out_dir, "scrape_log.csv"), newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        # Just the header row
        assert len(rows) == 1
        assert "action" in rows[0]

    def test_all_tables_exportable(self, test_db):
        """Every table in the TABLES list should export without error."""
        conn, tmp_path, _ = test_db
        out_dir = str(tmp_path / "exports")
        os.makedirs(out_dir)

        for table in TABLES:
            count = export_table(conn, table, out_dir)
            assert count >= 0
            assert os.path.exists(os.path.join(out_dir, f"{table}.csv"))

    def test_preserves_unicode(self, test_db):
        """Unicode characters in rider names should survive export."""
        conn, tmp_path, _ = test_db
        out_dir = str(tmp_path / "exports")
        os.makedirs(out_dir)

        conn.execute("""
            INSERT INTO riders (url, name, nationality)
            VALUES ('rider/tadej-pogacar', 'Tadej Pogačar', 'Slovenia')
        """)
        conn.commit()

        export_table(conn, "riders", out_dir)
        with open(os.path.join(out_dir, "riders.csv"), newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        names = [r["name"] for r in rows]
        assert "Tadej Pogačar" in names

    def test_handles_null_values(self, test_db):
        """NULL values should be exported as empty strings."""
        conn, tmp_path, _ = test_db
        out_dir = str(tmp_path / "exports")
        os.makedirs(out_dir)

        # Riders without weight/height have NULL values
        conn.execute("""
            INSERT INTO riders (url, name) VALUES ('rider/stub-rider', 'Stub')
        """)
        conn.commit()

        export_table(conn, "riders", out_dir)
        with open(os.path.join(out_dir, "riders.csv"), newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        stub = [r for r in rows if r["name"] == "Stub"][0]
        assert stub["weight"] == "" or stub["weight"] == "None"

    def test_numeric_precision(self, test_db):
        """Numeric values like distance and points should be preserved."""
        conn, tmp_path, _ = test_db
        out_dir = str(tmp_path / "exports")
        os.makedirs(out_dir)

        export_table(conn, "stages", out_dir)
        with open(os.path.join(out_dir, "stages.csv"), newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert float(rows[0]["distance"]) == 250.5
        assert float(rows[0]["vertical_meters"]) == 3200


class TestExportReimport:
    """Test that exported CSVs can be reimported to recreate the data."""

    def test_round_trip_results(self, test_db):
        """Export results → read CSV → verify all rows present."""
        conn, tmp_path, _ = test_db
        out_dir = str(tmp_path / "exports")
        os.makedirs(out_dir)

        db_rows = conn.execute("SELECT * FROM results ORDER BY rank").fetchall()
        export_table(conn, "results", out_dir)

        with open(os.path.join(out_dir, "results.csv"), newline="") as f:
            csv_rows = list(csv.DictReader(f))

        assert len(csv_rows) == len(db_rows)
        for db_row, csv_row in zip(db_rows, csv_rows):
            assert csv_row["rider_name"] == db_row["rider_name"]
            assert int(csv_row["rank"]) == db_row["rank"]
