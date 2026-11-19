"""Hourly restoration study: how much healthy load the ties can pick up depends on
the hour of the fault, because the feeder's load (and so its voltage drop and line
currents) changes through the day and the year.

Every spot load follows one shared hourly shape (config ASSUMPTION), so the plan
depends only on the feeder-wide LoadMult. We therefore run restoration once per
level on a grid (sweep) and map every hour of the year onto that grid (by_hour),
instead of 8,760 separate runs.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import config, feeder, restoration, topology


# ---------------------------------------------------------------------------
# Load shape
# ---------------------------------------------------------------------------
def read_hourly(path: Path, column: str) -> tuple[pd.Series, dict]:
    """Hourly MW indexed by timestamp, with clock-change gaps and duplicates fixed.

    Timestamps are hour-ending in the source and hour-beginning in the result.
    The fall-back hour appears twice (we average the two); the spring-forward hour
    is missing (we interpolate across at most 3 missing hours)."""
    raw = pd.read_csv(path, usecols=["Datetime", column])
    # PJM/Kaggle stamps each value at the END of its hour (a day runs 01:00 ... 00:00 of
    # the next day), so shift back one hour to label each hour by its start.
    raw["Datetime"] = pd.to_datetime(raw["Datetime"]) - pd.Timedelta(hours=1)
    dup = int(raw["Datetime"].duplicated().sum())
    s = raw.groupby("Datetime")[column].mean().sort_index()
    full = pd.date_range(s.index.min(), s.index.max(), freq="h")
    s = s.reindex(full)
    gaps = int(s.isna().sum())
    s = s.interpolate(limit=3, limit_area="inside")
    return s, {"rows": len(raw), "duplicates_averaged": dup, "missing_filled": gaps - int(s.isna().sum()),
               "missing_left": int(s.isna().sum()), "first": str(s.index.min()), "last": str(s.index.max())}


def latest_full_year(s: pd.Series) -> int:
    """Latest calendar year with a value for every hour."""
    for year in sorted(set(s.index.year), reverse=True):
        y = s[s.index.year == year]
        hours = 24 * (366 if pd.Timestamp(year=year, month=12, day=31).dayofyear == 366 else 365)
        if len(y) == hours and not y.isna().any():
            return year
    raise ValueError("no calendar year with every hour present")


def normalize(s: pd.Series, year: int) -> pd.DataFrame:
    """One year of hourly MW and its LoadMult (MW / that year's peak MW)."""
    y = s[s.index.year == year]
    return pd.DataFrame({"datetime": y.index, "mw": y.to_numpy(), "mult": (y / y.max()).to_numpy()})


def season(months: pd.Series) -> pd.Series:
    return np.where(months.isin(config.SUMMER_MONTHS), "summer",
                    np.where(months.isin(config.WINTER_MONTHS), "winter", "other"))


# ---------------------------------------------------------------------------
# Restoration on a LoadMult grid
# ---------------------------------------------------------------------------
def levels() -> np.ndarray:
    lo, hi = config.HOURLY_LEVEL_RANGE
    step = config.HOURLY_LEVEL_STEP
    return np.round(np.arange(lo, hi + step / 2, step), 2)


def to_level(mult) -> np.ndarray:
    lo, hi = config.HOURLY_LEVEL_RANGE
    step = config.HOURLY_LEVEL_STEP
    return np.round(np.clip(np.round(np.asarray(mult) / step) * step, lo, hi), 2)


def plan_at(zones: topology.Zones, level: float) -> list[dict]:
    """Restoration for every fault zone at one load level, from a fresh circuit
    (so regulator taps do not carry over from the previous level)."""
    feeder.load_feeder()
    feeder.set_load_level(level)
    feeder.set_normal_configuration()
    base = restoration.check_power_flow(zones, set(zones.names))
    rows = []
    for zf in zones.names:
        plan = restoration.plan_restoration(zones, zf)
        km = restoration.kw_minutes(zones, plan)
        final = plan.checks[-1]
        healthy = sum(zones.kw[z] for z in zones.downstream(zf))
        by_tie = sum(zones.kw[z] for z in plan.restored_by_tie)
        reasons = {r: 0 for r in restoration.REASONS}
        for c in plan.checks[:-1]:
            for r in restoration.classify(c):
                reasons[r] += 1
        rows.append({
            "level": level, "fault_zone": zf,
            "ties_closed": " ".join(plan.closed_ties) or "-",
            "restored_by_tie": " ".join(sorted(plan.restored_by_tie)) or "-",
            "unserved_healthy": " ".join(sorted(plan.unserved)) or "-",
            "kW_downstream_healthy": healthy, "kW_restored_by_tie": by_tie,
            "power_flow_checks": len(plan.checks) - 1,
            "power_flow_rejected": sum(not c["ok"] for c in plan.checks[:-1]),
            **{f"rejected_{r}": n for r, n in reasons.items()},
            "final_vmin_pu": round(final["vmin"], 4), "final_vmax_pu": round(final["vmax"], 4),
            "final_ok": bool(final["ok"] and final["radial"]),
            "kWmin_reduction_pct": round(100 * (1 - km["automated"] / km["conventional"]), 1),
            "base_vmin_pu": round(base["vmin"], 4), "base_vmax_pu": round(base["vmax"], 4),
            "base_ok": bool(base["ok"]),
        })
    return rows


def sweep(grid=None, verbose: bool = True) -> pd.DataFrame:
    feeder.load_feeder()
    zones = topology.find_zones()
    rows = []
    for level in (levels() if grid is None else grid):
        rows += plan_at(zones, float(level))
        if verbose:
            print(f"  LoadMult {level:.2f} done", end="\r")
    restoration.reset(zones)
    feeder.set_load_level(1.0)
    return pd.DataFrame(rows)


def totals(by_level: pd.DataFrame) -> pd.DataFrame:
    """Per level, summed over the 10 fault zones (each zone's fault counted once)."""
    g = by_level.groupby("level")
    out = g[["kW_downstream_healthy", "kW_restored_by_tie", "power_flow_rejected",
             *[f"rejected_{r}" for r in restoration.REASONS]]].sum()
    out["pct_restored"] = out["kW_restored_by_tie"] / out["kW_downstream_healthy"]
    out["base_ok"] = g["base_ok"].all()
    out["final_ok"] = g["final_ok"].all()
    return out.reset_index()


def non_monotone(by_level: pd.DataFrame) -> dict[str, int]:
    """Per fault zone, how many grid steps restore MORE kW at a HIGHER load level."""
    p = by_level.pivot(index="level", columns="fault_zone", values="kW_restored_by_tie").sort_index()
    return {z: int((p[z].diff() > 0).sum()) for z in p.columns}


# ---------------------------------------------------------------------------
# Hours of the year
# ---------------------------------------------------------------------------
def held_mult(mult: pd.Series, hours: int = config.HOLD_HOURS) -> pd.Series:
    """Highest LoadMult from this hour through the next hours-1 hours (the outage window)."""
    return mult[::-1].rolling(hours, min_periods=1).max()[::-1]


def by_hour(shape: pd.DataFrame, by_level: pd.DataFrame) -> pd.DataFrame:
    tot = totals(by_level).set_index("level")
    df = shape[["datetime", "mult"]].copy()
    df["level"] = to_level(df["mult"])
    df["level_held"] = to_level(held_mult(df["mult"]))
    df["pct_restored"] = tot.loc[df["level"], "pct_restored"].to_numpy()
    df["pct_restored_held"] = tot.loc[df["level_held"], "pct_restored"].to_numpy()
    for r in restoration.REASONS:
        df[f"rejected_{r}"] = tot.loc[df["level"], f"rejected_{r}"].to_numpy()
    dt = pd.to_datetime(df["datetime"])
    df["hour"] = dt.dt.hour
    df["season"] = season(dt.dt.month)
    return df
