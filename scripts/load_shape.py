"""Build the hourly load shape for the hourly restoration study.

Reads the PJM AEP hourly load (Kaggle "Hourly Energy Consumption", AEP_hourly.csv,
downloaded by hand into data/external/pjm/), fixes clock-change hours, keeps the
latest full calendar year (or --year) and divides by that year's peak MW, so the
result is a feeder-wide LoadMult with a maximum of 1.0. Writes
results/hourly/load_shape.csv and results/hourly/load_shape_info.json.

    .venv\\Scripts\\python scripts\\load_shape.py [--year 2017]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shf import config, hourly  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, help="calendar year to use (default: latest full year)")
    args = ap.parse_args()
    src = config.LOAD_SHAPE_CSV
    if not src.exists():
        sys.exit(f"{src} not found. Locally: download AEP_hourly.csv (Kaggle 'Hourly Energy "
                 "Consumption', PJM) into data/external/pjm/. On Kaggle: Add Input -> that dataset.")
    s, info = hourly.read_hourly(src, config.LOAD_SHAPE_COLUMN)
    year = args.year or hourly.latest_full_year(s)
    shape = hourly.normalize(s, year)
    if len(shape) < 8760 or shape["mult"].isna().any():
        sys.exit(f"year {year} is incomplete ({len(shape)} hours); pick another with --year")
    config.HOURLY.mkdir(parents=True, exist_ok=True)
    shape.to_csv(config.HOURLY / "load_shape.csv", index=False, float_format="%.5f", lineterminator="\n")
    info.update(year=year, hours=len(shape), peak_mw=float(shape["mw"].max()),
                mult_min=float(shape["mult"].min()), mult_mean=float(shape["mult"].mean()),
                source=f"{src.name}, column {config.LOAD_SHAPE_COLUMN}")
    (config.HOURLY / "load_shape_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
