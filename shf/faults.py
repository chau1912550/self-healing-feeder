"""Fault sweep: simulate thousands of faults and record what each device would see.

For every bus, fault type, fault resistance and load level we:
  1. solve the pre-fault power flow (regulators free to move, independent zone + spot loading),
  2. freeze regulator taps (protection acts in cycles, regulators in seconds),
  3. apply pre-to-post load drift and the fault (with intermittent arcing equivalent 60 Hz
     resistance for SLG faults >= HIF_ARC_MIN_R in realistic mode) and solve again,
  4. store each device's phase currents/voltages (with CT/PT systematic bias, random error,
     and additive noise floor in realistic mode) and their change from pre-fault.
"""
from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd

from . import config, feeder
from .topology import Zones

DEVICES = list(config.SECTIONALIZERS)
PAIRS = [(1, 2), (2, 3), (3, 1)]


def emanuel_fundamental_factor(gamma: float) -> float:
    """Fundamental (60 Hz) describing-function factor k1(gamma) for the Emanuel 2-diode arc.

    For phase voltage Vpk*sin(theta) conducting when sin(theta) > gamma = V_arc / Vpk:
        k1(gamma) = 1 - (2/pi) * (arcsin(gamma) + gamma * sqrt(1 - gamma^2))
    """
    if gamma < 0.0 or gamma > 1.0:
        raise ValueError(f"gamma must be in [0, 1], got {gamma}")
    if gamma == 0.0:
        return 1.0
    if gamma == 1.0:
        return 0.0
    return 1.0 - (2.0 / math.pi) * (math.asin(gamma) + gamma * math.sqrt(1.0 - gamma * gamma))


def sample_arc_resistance(r_nom: float, ftype: str, rng: np.random.Generator) -> dict:
    """Map nominal fault resistance to an equivalent 60 Hz resistance for arcing HIFs.

    Applies only to SLG faults with r_nom >= config.HIF_ARC_MIN_R; all other fault types
    and lower resistances keep r_eff = r_nom cleanly.
    """
    r_nom_f = float(r_nom)
    if ftype != "SLG" or r_nom_f < config.HIF_ARC_MIN_R:
        return {
            "r_eff": r_nom_f,
            "is_arcing": False,
            "arc_kappa": 1.0,
            "arc_duty": 1.0,
            "r_jitter": 1.0,
        }
    gamma_p = float(rng.uniform(*config.HIF_VP_FRAC_RANGE))
    u_asym = float(rng.uniform(*config.HIF_ASYM_RANGE))
    gamma_n = float(np.clip(gamma_p * u_asym, config.HIF_VP_FRAC_RANGE[0], config.HIF_VN_FRAC_MAX))
    kappa = 0.5 * (emanuel_fundamental_factor(gamma_p) + emanuel_fundamental_factor(gamma_n))
    duty = (
        float(rng.uniform(*config.HIF_DUTY_RANGE))
        if rng.random() < config.HIF_INTERMITTENT_PROB
        else 1.0
    )
    m_r = float(np.clip(
        math.exp(float(rng.normal(0.0, config.HIF_R_JITTER_LOGSTD))),
        *config.HIF_R_JITTER_CLIP,
    ))
    r_eff = float(np.clip((r_nom_f * m_r) / (kappa * duty), 0.5 * r_nom_f, config.HIF_R_EFF_MAX))
    return {
        "r_eff": r_eff,
        "is_arcing": True,
        "arc_kappa": float(kappa),
        "arc_duty": float(duty),
        "r_jitter": m_r,
    }


def sample_ct_pt_bias(devices: list[str] | tuple[str, ...],
                      rng: np.random.Generator) -> dict[str, dict[str, np.ndarray]]:
    """Sample per-device, per-phase systematic CT/PT ratio and phase-angle bias.

    Held fixed between pre-fault and post-fault snapshots of one event, and re-sampled
    across events so models cannot memorize static per-channel calibration offsets.
    """
    out: dict[str, dict[str, np.ndarray]] = {}
    for d in devices:
        b_i = np.clip(rng.normal(0.0, config.CT_BIAS_MAG, 3),
                      -config.CT_BIAS_MAG_CLIP, config.CT_BIAS_MAG_CLIP)
        th_i = np.clip(rng.normal(0.0, config.CT_BIAS_ANG_DEG, 3),
                       -config.CT_BIAS_ANG_CLIP_DEG, config.CT_BIAS_ANG_CLIP_DEG)
        b_v = np.clip(rng.normal(0.0, config.PT_BIAS_MAG, 3),
                      -config.PT_BIAS_MAG_CLIP, config.PT_BIAS_MAG_CLIP)
        th_v = np.clip(rng.normal(0.0, config.PT_BIAS_ANG_DEG, 3),
                       -config.PT_BIAS_ANG_CLIP_DEG, config.PT_BIAS_ANG_CLIP_DEG)
        out[d] = {
            "i": (1.0 + b_i) * np.exp(1j * np.deg2rad(th_i)),
            "v": (1.0 + b_v) * np.exp(1j * np.deg2rad(th_v)),
        }
    return out


def sample_load_factors(load_zone_idx: np.ndarray, n_zones: int,
                        rng: np.random.Generator,
                        realistic: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Sample pre-fault and post-fault per-load scaling factors.

    When realistic=True: combines independent per-zone loading, spot-load spread, and
    small correlated + independent pre-to-post load drift.
    When realistic=False: spot-load spread only, with zero pre-to-post drift.
    """
    n_loads = len(load_zone_idx)
    spot = np.clip(rng.normal(1.0, config.LOAD_SPREAD, n_loads), 0.3, 1.7)
    if not realistic:
        return spot, spot
    zone_mult = np.clip(rng.normal(1.0, config.ZONE_LOAD_SPREAD, n_zones), *config.ZONE_LOAD_CLIP)
    safe_idx = np.maximum(load_zone_idx, 0)
    z_for_load = np.where(load_zone_idx >= 0, zone_mult[safe_idx], 1.0)
    f_pre = np.clip(z_for_load * spot, *config.SPOT_FACTOR_CLIP)
    d_zone = rng.normal(0.0, config.LOAD_DRIFT_ZONE, n_zones)
    dz_for_load = np.where(load_zone_idx >= 0, d_zone[safe_idx], 0.0)
    d_spot = rng.normal(0.0, config.LOAD_DRIFT_SPOT, n_loads)
    drift = np.clip(1.0 + dz_for_load + d_spot, *config.LOAD_DRIFT_CLIP)
    f_post = f_pre * drift
    return f_pre, f_post


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


def snapshot(rng: np.random.Generator | None = None, *,
             bias: dict[str, dict[str, np.ndarray]] | None = None,
             floor_i: float = 0.0,
             floor_v: float = 0.0) -> dict[str, dict]:
    """Read every device. With `rng`, add instrument-transformer error (plus optional
    systematic CT/PT bias and additive low-signal noise floors)."""
    clean = {d: feeder.device_measurement(d) for d in DEVICES}
    return _perturb(clean, rng, bias=bias, floor_i=floor_i, floor_v=floor_v) if rng is not None else clean


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


def _perturb(meas: dict, rng: np.random.Generator, *,
             bias: dict[str, dict[str, np.ndarray]] | None = None,
             floor_i: float = 0.0,
             floor_v: float = 0.0) -> dict:
    """Perturb device phasor measurements with multiplicative noise, optional systematic
    CT/PT bias, and optional circular complex additive floor on energized phases only.

    Calling `_perturb(clean, rng)` with default keyword arguments preserves the legacy
    two-argument behavior and RNG sequence for downstream studies.
    """
    out = {}
    floors = {"i": float(floor_i), "v": float(floor_v)}
    inv_sqrt2 = 1.0 / math.sqrt(2.0)
    for d, m in meas.items():
        m = dict(m)
        i_clean = np.asarray(m["i"])
        v_clean = np.asarray(m["v"])
        active = (np.abs(v_clean) > 0.05) | (np.abs(i_clean) > 1e-6)
        b_dev = bias.get(d) if bias is not None else None
        for key in ("i", "v"):
            arr = np.asarray(m[key])
            n = len(arr)
            if b_dev is not None and key in b_dev:
                arr = arr * b_dev[key][:n]
            arr = arr * (1 + rng.normal(0, config.NOISE_MAG, n)) * np.exp(
                1j * np.deg2rad(rng.normal(0, config.NOISE_ANG_DEG, n)))
            sigma = floors[key]
            if sigma > 0.0:
                s = sigma * inv_sqrt2
                add = rng.normal(0.0, s, n) + 1j * rng.normal(0.0, s, n)
                arr = arr + np.where(active[:n], add, 0.0)
            m[key] = arr
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
             verbose: bool = True, realistic: bool | None = None) -> pd.DataFrame:
    if realistic is None:
        realistic = noise
    rng = np.random.default_rng(seed)
    noise_rng = rng if noise else None
    cases = fault_cases(zones)
    base = feeder.base_loads()
    zone_names = list(zones.names)
    zone_idx = {z: idx for idx, z in enumerate(zone_names)}
    load_zone_idx = np.array(
        [zone_idx.get(zones.bus_zone.get(b, ""), -1) for b in feeder.load_buses(base)],
        dtype=int,
    )
    use_realistic_noise = bool(noise and realistic)
    floor_i = config.NOISE_I_FLOOR_A if use_realistic_noise else 0.0
    floor_v = config.NOISE_V_FLOOR_PU if use_realistic_noise else 0.0

    feeder.set_normal_configuration()
    exists = "fault.f" in (n.lower() for n in feeder.dss.Circuit.AllElementNames())
    feeder.cmd(f"{'Edit' if exists else 'New'} Fault.F phases=1 bus1=149.1 bus2=149.0 r=1 enabled=no")
    feeder.scale_loads(base, np.ones(len(base)))
    feeder.set_load_level(1.0)
    feeder.reset_regulators()
    feeder.solve(controls=True)
    rows, t0 = [], time.time()
    for s in range(config.SCENARIOS_PER_CASE):
        for c in cases:
            mult = rng.uniform(*config.LOAD_MULT_RANGE)
            f_pre, f_post = sample_load_factors(load_zone_idx, len(zone_names), rng, realistic=realistic)
            feeder.scale_loads(base, f_pre)
            feeder.set_load_level(mult)
            feeder.cmd("Edit Fault.F enabled=no")
            ok_pre = feeder.solve(controls=True)
            bias = sample_ct_pt_bias(DEVICES, rng) if use_realistic_noise else None
            pre = snapshot(noise_rng, bias=bias, floor_i=floor_i, floor_v=floor_v)

            if realistic:
                feeder.scale_loads(base, f_post)
                arc = sample_arc_resistance(c["r"], c["ftype"], rng)
            else:
                arc = {"r_eff": float(c["r"]), "is_arcing": False, "arc_kappa": 1.0, "arc_duty": 1.0, "r_jitter": 1.0}
            spec = f"{c['spec'].rsplit(' r=', 1)[0]} r={arc['r_eff']:.6f}" if arc["is_arcing"] else c["spec"]
            feeder.cmd(f"Edit Fault.F {spec} enabled=yes")
            ok = feeder.solve(controls=False)
            post = snapshot(noise_rng, bias=bias, floor_i=floor_i, floor_v=floor_v)

            row = {k: c[k] for k in ("bus", "zone", "ftype", "phases", "r")}
            row.update(
                r_eff=arc["r_eff"],
                is_arcing=arc["is_arcing"],
                arc_kappa=arc["arc_kappa"],
                arc_duty=arc["arc_duty"],
                scenario=s,
                load_mult=mult,
                converged=ok and ok_pre,
            )
            row.update(features(post, pre))
            rows.append(row)
        if verbose:
            print(f"  scenario {s + 1}/{config.SCENARIOS_PER_CASE}: {len(cases)} faults, "
                  f"{time.time() - t0:.1f}s elapsed")
    feeder.cmd("Edit Fault.F enabled=no")
    feeder.scale_loads(base, np.ones(len(base)))
    feeder.set_load_level(1.0)
    feeder.reset_regulators()
    feeder.solve(controls=True)
    return pd.DataFrame(rows)
