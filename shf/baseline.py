"""Conventional fault location: fault passage indicators (FPI) on each device.

A device "flags" when its current exceeds a fixed pickup. In a radial feeder
the fault is in the zone fed by the deepest flagged device. This is how many
FLISR schemes work today, so it is the baseline the ML model has to beat.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config
from .faults import DEVICES
from .topology import Zones


def pickups(peak: dict[str, dict]) -> dict[str, tuple[float, float]]:
    """(phase pickup A, ground pickup A) per device from peak-load currents."""
    out = {}
    for d, p in peak.items():
        phase = config.FPI_PHASE_FACTOR * p["imax"]
        ground = max(config.FPI_GROUND_FACTOR * p["imax"], config.FPI_GROUND_MARGIN * p["i_res"])
        out[d] = (phase, ground)
    return out


def _depth(zones: Zones, zone: str) -> int:
    d = 0
    while zones.parent[zone] is not None:
        zone = zones.parent[zone]
        d += 1
    return d


def predict(df: pd.DataFrame, zones: Zones, pick: dict[str, tuple[float, float]]) -> np.ndarray:
    """Predicted zone per row, or 'none' when no device flagged.

    Phase element: any phase current above the phase pickup.
    Ground element: residual current |3*I0| above the ground pickup.
    """
    depth = {d: _depth(zones, d) for d in DEVICES}
    flags = {}
    for d in DEVICES:
        phase_pu, ground_pu = pick[d]
        imax = df[[f"{d}_Ia", f"{d}_Ib", f"{d}_Ic"]].max(axis=1)
        flags[d] = (imax > phase_pu) | (3 * df[f"{d}_I0"] > ground_pu)
    flag_df = pd.DataFrame(flags)
    order = sorted(DEVICES, key=lambda d: depth[d], reverse=True)
    pred = np.full(len(df), "none", dtype=object)
    for d in reversed(order):          # shallow first, deeper devices overwrite
        pred[flag_df[d].to_numpy()] = d
    return pred
