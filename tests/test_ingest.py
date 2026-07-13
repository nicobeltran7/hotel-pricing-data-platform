"""Unit tests for the ingestion layer: validation, upsert semantics, quarantine."""

import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from ingest import DDL, upsert, validate  # noqa: E402


def frame(rows):
    return pd.DataFrame(rows, columns=["vendor_code", "property_code", "rate_date", "duration_band", "rate_usd"])


@pytest.fixture()
def con():
    c = duckdb.connect(":memory:")
    c.execute(DDL)
    yield c
    c.close()


class TestValidate:
    def test_clean_rows_pass(self):
        good, bad = validate(frame([("V", "AUS001", "2026-01-01", "1N", "120.00")]))
        assert len(good) == 1 and bad.empty

    def test_missing_property_quarantined(self):
        good, bad = validate(frame([("V", None, "2026-01-01", "1N", "120.00")]))
        assert good.empty and bad.iloc[0]["reason_code"] == "MISSING_PROPERTY"

    def test_bad_date_quarantined(self):
        good, bad = validate(frame([("V", "AUS001", "01/15/2026", "1N", "120.00")]))
        assert good.empty and bad.iloc[0]["reason_code"] == "BAD_DATE"

    def test_non_positive_rate_quarantined(self):
        _, bad = validate(frame([("V", "AUS001", "2026-01-01", "1N", "-5"),
                                 ("V", "AUS001", "2026-01-02", "1N", "0")]))
        assert list(bad["reason_code"]) == ["NON_POSITIVE_RATE"] * 2

    def test_unknown_band_quarantined(self):
        _, bad = validate(frame([("V", "AUS001", "2026-01-01", "14N", "99")]))
        assert bad.iloc[0]["reason_code"] == "BAD_BAND"

    def test_in_batch_duplicates_keep_last(self):
        good, _ = validate(frame([("V", "AUS001", "2026-01-01", "1N", "100"),
                                  ("V", "AUS001", "2026-01-01", "1N", "110")]))
        assert len(good) == 1 and float(good.iloc[0]["rate_usd"]) == 110.0


class TestUpsert:
    def test_insert_then_correct(self, con):
        upsert(con, frame([("V", "AUS001", "2026-01-01", "1N", "100")]))
        upsert(con, frame([("V", "AUS001", "2026-01-01", "1N", "125")]))  # late correction
        rows = con.execute("SELECT rate_usd FROM raw.rate_observations").fetchall()
        assert rows == [(125.00,)]

    def test_idempotent_rerun(self, con):
        batch = frame([("V", "AUS001", "2026-01-01", "1N", "100"),
                       ("V", "AUS002", "2026-01-01", "2-3N", "90")])
        upsert(con, batch)
        upsert(con, batch)
        n = con.execute("SELECT COUNT(*) FROM raw.rate_observations").fetchone()[0]
        assert n == 2

    def test_different_vendors_do_not_collide(self, con):
        upsert(con, frame([("V1", "AUS001", "2026-01-01", "1N", "100")]))
        upsert(con, frame([("V2", "AUS001", "2026-01-01", "1N", "105")]))
        n = con.execute("SELECT COUNT(*) FROM raw.rate_observations").fetchone()[0]
        assert n == 2


class TestQuarantine:
    def test_quarantine_handles_missing_values(self, con):
        """Regression: NaN in quarantined rows must not break raw_record join (pandas>=3 astype behavior)."""
        from ingest import quarantine
        df = frame([("V", None, "2026-01-01", "1N", None)])
        df["reason_code"] = "MISSING_PROPERTY"
        n = quarantine(con, df, "test_file.csv")
        assert n == 1
        rec = con.execute("SELECT raw_record, reason_code FROM raw.quarantine").fetchone()
        assert rec[1] == "MISSING_PROPERTY" and "V|" in rec[0]
