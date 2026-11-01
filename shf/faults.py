"""Fault sweep: simulate thousands of faults and record what each device would see.

For every bus, fault type, fault resistance and load level we:
  1. solve the pre-fault power flow (regulators free to move),
  2. freeze regulator taps (protection acts in cycles, regulators in seconds),
  3. apply the fault and solve again,
  4. store each device's phase currents/voltages and their change from pre-fault.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from . import config, feeder
from .topology import Zones

DEVICES = list(config.SECTIONALIZERS)
PAIRS = [(1, 2), (2, 3), (3, 1)]


def fault_cases(zones: Zones) -> list[dict]:
    cases = []
    for zone, buses in zones.members.items():
        for bus in buses:
            ph = feeder.bus_phases(bus)
            for p in ph:
                for r in config.SLG_RESISTANCES:
                    cases.append(dict(bus=bus, zone=zone, ftype="SLG", phases=f"{p}", r=r,
                                      spec=f"phases=1 bus1={bus}.{p} bus2={bus}.0 r={r}"))
            for p, q in PAIRS:
                if p in ph and q in ph:
                    for r in config.PHASE_RESISTANCES:
                        cases.append(dict(bus=bus, zone=zone, ftype="LL", phases=f"{p}{q}", r=r,
                                          spec=f"phases=1 bus1={bus}.{p} bus2={bus}.{q} r={r}"))
                        cases.append(dict(bus=bus, zone=zone, ftype="LLG", phases=f"{p}{q}", r=r,
                                          spec=f"phases=2 bus1={bus}.{p}.{q} bus2={bus}.0.0 r={r}"))
            if ph == [1, 2, 3]:
                for r in config.PHASE_RESISTANCES:
                    cases.append(dict(bus=bus, zone=zone, ftype="3PH", phases="123", r=r,
                                      spec=f"phases=3 bus1={bus}.1.2.3 bus2={bus}.0.0.0 r={r}"))
    return cases


def snapshot(rng: np.random.Generator | None = None) -> dict[str, dict]:
    """Read every device. With `rng`, add instrument-transformer error:
    1% magnitude and 0.5 degree angle (1 sigma), independent per sample."""
    clean = {d: feeder.device_measurement(d) for d in DEVICES}
    return _perturb(clean, rng) if rng is not None else clean


def features(meas: dict, pre: dict) -> dict[str, float]:
    """Per device: phase current magnitudes, incremental (superimposed) currents,
    sequence-current changes, phase voltages and voltage changes."""
    row = {}
    for d in DEVICES:
        m, p = meas[d], pre[d]
        for k, ph in enumerate("abc"):
            row[f"{d}_I{ph}"] = abs(m["i"][k])
            row[f"{d}_dI{ph}"] = abs(m["i"][k] - p["i"][k])
            row[f"{d}_V{ph}"] = abs(m["v"][k])
            row[f"{d}_dV{ph}"] = abs(m["v"][k]) - abs(p["v"][k])
        row[f"{d}_I0"] = abs(m["i0"])
        row[f"{d}_dI0"] = abs(m["i0"] - p["i0"])
        row[f"{d}_dI2"] = abs(m["i2"] - p["i2"])
    return row


def _perturb(meas: dict, rng: np.random.Generator) -> dict:
    out = {}
    for d, m in meas.items():
        m = dict(m)
        for key in ("i", "v"):
            n = len(m[key])
            m[key] = m[key] * (1 + rng.normal(0, config.NOISE_MAG, n)) * np.exp(
                1j * np.deg2rad(rng.normal(0, config.NOISE_ANG_DEG, n)))
        ia, ib, ic = m["i"]
        m["i0"] = (ia + ib + ic) / 3
        m["i2"] = (ia + feeder.A * feeder.A * ib + feeder.A * ic) / 3
        out[d] = m
    return out


def peak_load_currents() -> dict[str, dict]:
    """Device currents at peak load, used to set conventional pickups."""
    feeder.set_normal_configuration()
    feeder.set_load_level(1.0)
    feeder.solve(controls=True)
    out = {}
    for d in DEVICES:
        m = feeder.device_measurement(d)
        out[d] = {"imax": float(np.abs(m["i"]).max()), "i_res": float(abs(3 * m["i0"]))}
    return out


def generate(zones: Zones, noise: bool = True, seed: int = 0,
             verbose: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    noise_rng = rng if noise else None
    cases = fault_cases(zones)
    base = feeder.base_loads()
    feeder.set_normal_configuration()
    feeder.cmd("New Fault.F phases=1 bus1=149.1 bus2=149.0 r=1 enabled=no")
    rows, t0 = [], time.time()
    for s in range(config.SCENARIOS_PER_CASE):
        for c in cases:
            mult = rng.uniform(*config.LOAD_MULT_RANGE)
            spread = np.clip(rng.normal(1.0, config.LOAD_SPREAD, len(base)), 0.3, 1.7)
            feeder.scale_loads(base, spread)
            feeder.set_load_level(mult)
            feeder.cmd("Edit Fault.F enabled=no")
            ok_pre = feeder.solve(controls=True)
            pre = snapshot(noise_rng)
            feeder.cmd(f"Edit Fault.F {c['spec']} enabled=yes")
            ok = feeder.solve(controls=False)
            row = {k: c[k] for k in ("bus", "zone", "ftype", "phases", "r")}
            row.update(scenario=s, load_mult=mult, converged=ok and ok_pre)
            row.update(features(snapshot(noise_rng), pre))
            rows.append(row)
        if verbose:
            print(f"  scenario {s + 1}/{config.SCENARIOS_PER_CASE}: {len(cases)} faults, "
                  f"{time.time() - t0:.1f}s elapsed")
    feeder.cmd("Edit Fault.F enabled=no")
    feeder.scale_loads(base, np.ones(len(base)))
    feeder.set_load_level(1.0)
    feeder.solve(controls=True)
    return pd.DataFrame(rows)
