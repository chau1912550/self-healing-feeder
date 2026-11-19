"""Hourly restoration study: re-run isolation and restoration for every fault zone
at every feeder load level, then map the hours of a real year onto those levels.

Stage 1 (always): results/hourly/by_level.csv, one row per (LoadMult, fault zone).
Stage 2 (only after scripts/load_shape.py): results/hourly/by_hour.csv, one row per
hour of the year. Both stages are summarized in results/hourly/hourly.json.
Existing results (run.py outputs) are not touched.

    .venv\\Scripts\\python scripts\\hourly_restoration.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shf import config, hourly, restoration  # noqa: E402


def r4(x) -> list[float]:
    return [round(float(v), 4) for v in x]


def summarize_hours(bh: pd.DataFrame, by_level: pd.DataFrame) -> dict:
    out: dict = {"typical_day": {}, "zone_hour": {}, "rejected_by_hour": {}}
    zl = by_level[by_level.kW_downstream_healthy > 0].copy()
    zl["pct"] = zl.kW_restored_by_tie / zl.kW_downstream_healthy
    zpct = zl.pivot(index="level", columns="fault_zone", values="pct")
    for name in ("summer", "winter"):
        d = bh[bh.season == name]
        g = d.groupby("hour")
        out["typical_day"][name] = {"mult": r4(g.mult.mean()), "pct_restored": r4(g.pct_restored.mean()),
                                    "pct_restored_held": r4(g.pct_restored_held.mean()), "days": len(d) // 24}
        z = zpct.loc[d.level].reset_index(drop=True)
        z["hour"] = d.hour.to_numpy()
        out["zone_hour"][name] = {c: r4(v) for c, v in z.groupby("hour").mean().items()}
        out["rejected_by_hour"][name] = {r: r4(g[f"rejected_{r}"].mean()) for r in restoration.REASONS}
    out["year"] = {
        "pct_restored_mean": float(bh.pct_restored.mean()),
        "pct_restored_held_mean": float(bh.pct_restored_held.mean()),
        "share_hours_held_lower": float((bh.pct_restored_held < bh.pct_restored - 1e-12).mean()),
        "share_hours_at_peak_plan": float((bh.pct_restored <= bh.pct_restored.min() + 1e-12).mean()),
        "mult_min": float(bh.mult.min()), "mult_max": float(bh.mult.max()), "mult_mean": float(bh.mult.mean()),
        "level_min": float(bh.level.min()),
    }
    return out


def main() -> None:
    out = config.HOURLY
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print("1) Restoration at every load level")
    by_level = hourly.sweep()
    by_level.to_csv(out / "by_level.csv", index=False)
    tot = hourly.totals(by_level)
    lo, hi = config.HOURLY_LEVEL_RANGE
    summary: dict = {
        "levels": {"min": lo, "max": hi, "step": config.HOURLY_LEVEL_STEP, "count": int(tot.shape[0])},
        "hold_hours": config.HOLD_HOURS,
        "base_ok_all_levels": bool(tot.base_ok.all()),
        "final_ok_all_levels": bool(tot.final_ok.all()),
        "by_level": {"level": r4(tot.level), "pct_restored": r4(tot.pct_restored),
                     "kW_restored_by_tie": r4(tot.kW_restored_by_tie),
                     **{f"rejected_{r}": [int(v) for v in tot[f"rejected_{r}"]] for r in restoration.REASONS}},
        "kW_downstream_healthy_total": float(tot.kW_downstream_healthy.iloc[0]),
        "base_vmax_by_level": r4(by_level.groupby("level").base_vmax_pu.first()),
        "base_vmin_by_level": r4(by_level.groupby("level").base_vmin_pu.first()),
        "load_shape": None,
        # Physically, more load should never let a tie pick up MORE. Where it does,
        # the decision sits within one regulator tap of the 1.05 pu limit.
        "level_steps_with_more_restored": hourly.non_monotone(by_level),
    }
    shape_csv = out / "load_shape.csv"
    if shape_csv.exists():
        print("2) Hours of the year")
        shape = pd.read_csv(shape_csv)
        bh = hourly.by_hour(shape, by_level)
        bh.to_csv(out / "by_hour.csv", index=False, float_format="%.5f")
        summary["load_shape"] = json.loads((out / "load_shape_info.json").read_text(encoding="utf-8"))
        summary.update(summarize_hours(bh, by_level))
    else:
        print("2) skipped: no results/hourly/load_shape.csv (run scripts/load_shape.py first)")
    summary["runtime_s"] = round(time.time() - t0, 1)
    (out / "hourly.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"done in {summary['runtime_s']} s")


if __name__ == "__main__":
    main()
