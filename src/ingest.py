"""Ingest multi-vendor rate files into DuckDB.

Pattern: per-vendor adapter -> common normalized shape -> validate ->
  valid rows   UPSERT into raw.rate_observations (natural key)
  invalid rows INSERT into raw.quarantine with a reason code

Natural key: (vendor_code, property_code, rate_date, duration_band).
Re-running is idempotent; corrected rows overwrite via upsert.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

NORMALIZED_COLS = ["vendor_code", "property_code", "rate_date", "duration_band", "rate_usd"]
VALID_BANDS = {"1N", "2-3N", "4-6N", "7+N"}

DDL = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE TABLE IF NOT EXISTS raw.rate_observations (
    vendor_code   VARCHAR NOT NULL,
    property_code VARCHAR NOT NULL,
    rate_date     DATE    NOT NULL,
    duration_band VARCHAR NOT NULL,
    rate_usd      DECIMAL(9, 2) NOT NULL,
    loaded_at     TIMESTAMP NOT NULL,
    PRIMARY KEY (vendor_code, property_code, rate_date, duration_band)
);
CREATE TABLE IF NOT EXISTS raw.quarantine (
    vendor_code VARCHAR,
    source_file VARCHAR,
    raw_record  VARCHAR,
    reason_code VARCHAR,
    loaded_at   TIMESTAMP
);
"""


# ---------------------------------------------------------------- adapters
def adapt_ratehawk(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    df = df.rename(columns={"rate_usd": "rate_usd"})
    df["vendor_code"] = "RATEHAWK"
    return df[NORMALIZED_COLS]


def adapt_stayscan(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    band_map = {"1": "1N", "2-3": "2-3N", "4-6": "4-6N", "7plus": "7+N"}
    df = df.rename(columns={"hotel_id": "property_code", "price": "rate_usd"})
    df["duration_band"] = df["los_bucket"].map(band_map)
    # US-format dates -> ISO
    df["rate_date"] = pd.to_datetime(df["shop_date"], format="%m/%d/%Y", errors="coerce").dt.strftime("%Y-%m-%d")
    df["vendor_code"] = "STAYSCAN"
    return df[NORMALIZED_COLS]


def adapt_lodgiq(path: Path) -> pd.DataFrame:
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    df = pd.DataFrame.from_records(records)
    df = df.rename(columns={"prop": "property_code", "date": "rate_date", "band": "duration_band"})
    df["rate_usd"] = pd.to_numeric(df["rate_cents"], errors="coerce") / 100  # cents -> dollars
    df["vendor_code"] = "LODGIQ"
    return df[NORMALIZED_COLS]


def adapt_travelmetrics(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    df["vendor_code"] = "TRAVELMETRICS"
    return df[NORMALIZED_COLS]


ADAPTERS = {
    "ratehawk_rates.csv": adapt_ratehawk,
    "stayscan_export.csv": adapt_stayscan,
    "lodgiq_feed.jsonl": adapt_lodgiq,
    "travelmetrics_2025H2_2026H1.csv": adapt_travelmetrics,
    "travelmetrics_corrections.csv": adapt_travelmetrics,
}


# ---------------------------------------------------------------- validation
def validate(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split normalized frame into (valid, quarantined-with-reason)."""
    df = df.copy()
    df["rate_usd"] = pd.to_numeric(df["rate_usd"], errors="coerce")
    df["rate_date_parsed"] = pd.to_datetime(df["rate_date"], format="%Y-%m-%d", errors="coerce")

    reasons = pd.Series("", index=df.index)
    reasons[df["property_code"].isna() | (df["property_code"].astype(str).str.strip() == "")] = "MISSING_PROPERTY"
    reasons[(reasons == "") & df["rate_date_parsed"].isna()] = "BAD_DATE"
    reasons[(reasons == "") & ~df["duration_band"].isin(VALID_BANDS)] = "BAD_BAND"
    reasons[(reasons == "") & (df["rate_usd"].isna() | (df["rate_usd"] <= 0))] = "NON_POSITIVE_RATE"

    bad = df[reasons != ""].assign(reason_code=reasons[reasons != ""])
    good = df[reasons == ""].drop(columns=["rate_date_parsed"])
    # dedupe on natural key inside the batch (keep last: corrections win)
    good = good.drop_duplicates(subset=["vendor_code", "property_code", "rate_date", "duration_band"], keep="last")
    return good, bad


# ---------------------------------------------------------------- load
def upsert(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    df = df.assign(loaded_at=datetime.now(timezone.utc).replace(tzinfo=None))
    con.register("batch", df)
    con.execute(
        """
        INSERT INTO raw.rate_observations
        SELECT vendor_code, property_code, CAST(rate_date AS DATE), duration_band,
               CAST(rate_usd AS DECIMAL(9,2)), loaded_at
        FROM batch
        ON CONFLICT (vendor_code, property_code, rate_date, duration_band)
        DO UPDATE SET rate_usd = excluded.rate_usd, loaded_at = excluded.loaded_at
        """
    )
    con.unregister("batch")
    return len(df)


def quarantine(con: duckdb.DuckDBPyConnection, df: pd.DataFrame, source_file: str) -> int:
    if df.empty:
        return 0
    payload = pd.DataFrame(
        {
            "vendor_code": df["vendor_code"],
            "source_file": source_file,
            "raw_record": df[NORMALIZED_COLS].astype(str).agg("|".join, axis=1),
            "reason_code": df["reason_code"],
            "loaded_at": datetime.now(timezone.utc).replace(tzinfo=None),
        }
    )
    con.register("q", payload)
    con.execute("INSERT INTO raw.quarantine SELECT * FROM q")
    con.unregister("q")
    return len(payload)


def run(raw_dir: Path, db_path: Path) -> dict:
    con = duckdb.connect(str(db_path))
    con.execute(DDL)
    stats: dict[str, dict] = {}
    for fname, adapter in ADAPTERS.items():
        fpath = raw_dir / fname
        if not fpath.exists():
            continue
        good, bad = validate(adapter(fpath))
        stats[fname] = {"upserted": upsert(con, good), "quarantined": quarantine(con, bad, fname)}
    con.close()
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default="data/raw", type=Path)
    ap.add_argument("--db", default="data/warehouse.duckdb", type=Path)
    args = ap.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    for f, s in run(args.raw_dir, args.db).items():
        print(f"{f:45s} upserted={s['upserted']:>7,d}  quarantined={s['quarantined']:>5,d}")
