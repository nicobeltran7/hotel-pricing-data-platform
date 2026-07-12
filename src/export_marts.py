"""Export mart tables to parquet so downstream projects (the Power BI
semantic model, the P&L analysis) can consume them without cloning this
repo's toolchain."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

MARTS = ["dim_date", "dim_property", "dim_duration_band", "fct_daily_rates"]


def export(db_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path), read_only=True)
    schema = con.execute(
        "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE '%marts'"
    ).fetchone()[0]
    for table in MARTS:
        target = out_dir / f"{table}.parquet"
        con.execute(f"COPY (SELECT * FROM {schema}.{table}) TO '{target}' (FORMAT PARQUET)")
        n = con.execute(f"SELECT COUNT(*) FROM {schema}.{table}").fetchone()[0]
        print(f"{table:20s} -> {target}  ({n:,} rows)")
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/warehouse.duckdb", type=Path)
    ap.add_argument("--out", default="exports", type=Path)
    args = ap.parse_args()
    export(args.db, args.out)
