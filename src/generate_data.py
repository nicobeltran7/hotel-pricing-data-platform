"""Synthetic multi-vendor hotel-rate data generator.

Deliberately produces messy, inconsistent files that mimic real
rate-shopping vendor feeds. Every defect is intentional and documented
in the README's data-defect catalog. Fully seeded => reproducible.

Vendors
-------
ratehawk       clean CSV, ISO dates              (the well-behaved one)
stayscan       CSV, US dates, renamed columns, duplicate rows
lodgiq         JSON-lines, rates in cents, missing property codes
travelmetrics  CSV, re-sends corrected rows for prior dates (late-arriving)
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 42
START = date(2025, 7, 1)
DAYS = 365
DURATION_BANDS = ["1N", "2-3N", "4-6N", "7+N"]
BAND_MULTIPLIER = {"1N": 1.00, "2-3N": 0.94, "4-6N": 0.87, "7+N": 0.78}

MARKETS = [
    ("AUS", "Austin", 1.25),
    ("DAL", "Dallas", 1.10),
    ("HOU", "Houston", 1.05),
    ("SAT", "San Antonio", 0.95),
    ("ELP", "El Paso", 0.80),
    ("FTW", "Fort Worth", 1.00),
    ("CCT", "Corpus Christi", 0.85),
    ("LBB", "Lubbock", 0.75),
]

BRANDS = ["Amber", "Cobalt", "Juniper", "Meridian", "Pallas"]


def build_properties(rng: random.Random) -> list[dict]:
    props = []
    n = 1
    districts = ["Downtown", "Airport", "Uptown", "Riverside", "Medical Center"]
    for mkt_code, mkt_name, mkt_mult in MARKETS:
        for _ in range(rng.randint(4, 6)):
            props.append(
                {
                    "property_code": f"{mkt_code}{n:03d}",
                    "property_name": f"{rng.choice(BRANDS)} {mkt_name} {rng.choice(districts)}",
                    "market_code": mkt_code,
                    "market_name": mkt_name,
                    "rooms": rng.randint(80, 420),
                    "base_rate": round(95 * mkt_mult * rng.uniform(0.85, 1.45), 2),
                }
            )
            n += 1
    return props


def daily_rate(prop: dict, d: date, band: str, rng: random.Random) -> float:
    """Base rate + weekly seasonality + annual drift + noise."""
    dow = 1.12 if d.weekday() in (4, 5) else (0.93 if d.weekday() == 6 else 1.0)
    annual = 1 + 0.10 * ((d - START).days / DAYS)  # gentle inflation
    event = 1.35 if (d.month == 3 and 12 <= d.day <= 19 and prop["market_code"] == "AUS") else 1.0
    noise = rng.uniform(0.96, 1.04)
    return round(prop["base_rate"] * BAND_MULTIPLIER[band] * dow * annual * event * noise, 2)


def generate(out_dir: Path, seed: int = SEED) -> None:
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    props = build_properties(rng)

    # reference file (clean, used as dbt seed)
    with open(out_dir / "properties.csv", "w") as f:
        f.write("property_code,property_name,market_code,market_name,rooms\n")
        for p in props:
            f.write(f"{p['property_code']},{p['property_name']},{p['market_code']},{p['market_name']},{p['rooms']}\n")

    dates = [START + timedelta(days=i) for i in range(DAYS)]

    # --- vendor 1: ratehawk (clean, but only covers ~70% of days: gaps to fill) ---
    with open(out_dir / "ratehawk_rates.csv", "w") as f:
        f.write("property_code,rate_date,duration_band,rate_usd,shop_ts\n")
        for p in props:
            for d in dates:
                if rng.random() < 0.30:  # DEFECT G1: coverage gaps
                    continue
                for band in DURATION_BANDS:
                    r = daily_rate(p, d, band, rng)
                    f.write(f"{p['property_code']},{d.isoformat()},{band},{r},{d.isoformat()}T06:00:00\n")

    # --- vendor 2: stayscan (US dates, renamed cols, ~2% duplicated rows) ---
    with open(out_dir / "stayscan_export.csv", "w") as f:
        f.write("hotel_id,shop_date,los_bucket,price,currency\n")
        for p in props:
            for d in dates:
                if rng.random() < 0.45:
                    continue
                for band in DURATION_BANDS:
                    r = daily_rate(p, d, band, rng) * rng.uniform(0.99, 1.01)
                    los = {"1N": "1", "2-3N": "2-3", "4-6N": "4-6", "7+N": "7plus"}[band]
                    row = f"{p['property_code']},{d.strftime('%m/%d/%Y')},{los},{round(r, 2)},USD\n"
                    f.write(row)
                    if rng.random() < 0.02:  # DEFECT D1: exact duplicate rows
                        f.write(row)

    # --- vendor 3: lodgiq (JSONL, cents, 3% missing property code -> quarantine) ---
    with open(out_dir / "lodgiq_feed.jsonl", "w") as f:
        for p in props:
            for d in dates:
                if rng.random() < 0.55:
                    continue
                for band in DURATION_BANDS:
                    r = daily_rate(p, d, band, rng) * rng.uniform(0.98, 1.02)
                    rec = {
                        "prop": None if rng.random() < 0.03 else p["property_code"],  # DEFECT Q1
                        "date": d.isoformat(),
                        "band": band,
                        "rate_cents": int(round(r * 100)),  # DEFECT U1: unit mismatch
                    }
                    f.write(json.dumps(rec) + "\n")

    # --- vendor 4: travelmetrics (initial file + correction file re-sending keys) ---
    tm_rows = []
    for p in props:
        for d in dates:
            if rng.random() < 0.50:
                continue
            for band in DURATION_BANDS:
                tm_rows.append((p["property_code"], d, band, daily_rate(p, d, band, rng)))
    with open(out_dir / "travelmetrics_2025H2_2026H1.csv", "w") as f:
        f.write("property_code,rate_date,duration_band,rate_usd\n")
        for pc, d, band, r in tm_rows:
            f.write(f"{pc},{d.isoformat()},{band},{r}\n")
    corrections = rng.sample(tm_rows, k=int(len(tm_rows) * 0.05))  # DEFECT L1: late corrections
    with open(out_dir / "travelmetrics_corrections.csv", "w") as f:
        f.write("property_code,rate_date,duration_band,rate_usd\n")
        for pc, d, band, r in corrections:
            f.write(f"{pc},{d.isoformat()},{band},{round(r * 1.10, 2)}\n")

    # DEFECT V1: a few impossible values in stayscan (negative / zero rates)
    with open(out_dir / "stayscan_export.csv", "a") as f:
        for _ in range(25):
            p = rng.choice(props)
            d = rng.choice(dates)
            f.write(f"{p['property_code']},{d.strftime('%m/%d/%Y')},1,{rng.choice([-1, 0])},USD\n")

    print(f"generated {len(list(out_dir.iterdir()))} files in {out_dir}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/raw", type=Path)
    ap.add_argument("--seed", default=SEED, type=int)
    args = ap.parse_args()
    generate(args.out, args.seed)
