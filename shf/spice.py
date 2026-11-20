"""LTspice circuits for what the phasor power flow cannot show.

OpenDSS solves 60 Hz phasors: a fault current is one steady RMS number. A real recloser
sees a waveform that starts with a decaying DC offset, through a CT and an analog front
end into an ADC, and it estimates the phasor from samples. Two circuits cover that:

1. fault_dc_offset.asc  per-phase equivalent of the feeder seen from the fault bus
   (Thevenin R and L from OpenDSS, the pre-fault load at the feeder head). A bolted fault
   closes at two instants: the one with no DC offset and the one with the largest.
2. ct_adc_frontend.asc  the worst-case fault current through a CT (ideal ratio), a burden
   resistor on a mid-rail bias, an RC anti-alias filter and clamp diodes, i.e. what a
   3.3 V microcontroller ADC pin would see.

Every value is written from the study (OpenDSS) or from config.py (marked ASSUMPTION).
The schematics are generated, like the AutoCAD DXF, so they always match the model:

    python scripts/spice_run.py --register
"""
from __future__ import annotations

import json
import math
import os
import struct
import subprocess
from pathlib import Path

import numpy as np

from . import config

F = 60.0
W = 2 * math.pi * F
FAULT_ASC = config.SPICE_DIR / "fault_dc_offset.asc"
CT_ASC = config.SPICE_DIR / "ct_adc_frontend.asc"
PWL = config.SPICE_DIR / "ct_secondary.pwl"
HIF_ASC = config.SPICE_DIR / "hif_arc.asc"
HIF_T_FROM, HIF_T_END = 0.050, 0.100   # arc circuit: 3 settled cycles are analysed
EXPORTS = config.ROOT / "exports"
SUMMARY = config.RESULTS / "spice" / "summary.json"
T0 = 0.050          # fault after 3 cycles of pre-fault load
T_END = 0.150
GRID_S = 20e-6      # CSV exports are resampled on a 20 us grid


# ---------------------------------------------------------------- values from the study
def fault_params(bus: str = config.SPICE_FAULT_BUS) -> dict:
    """Thevenin impedance at `bus`, pre-fault feeder-head current and the OpenDSS
    3-phase bolted-fault current, all from the IEEE 123-bus model."""
    import opendssdirect as dss
    from . import feeder
    feeder.load_feeder()
    feeder.set_normal_configuration()
    feeder.solve(controls=True)
    i_pre = float(np.abs(feeder.device_measurement("Sw1")["i"]).mean())
    p, q = (-x for x in dss.Circuit.TotalPower()[:2])
    pf = p / math.hypot(p, q)
    feeder.cmd(f"New Fault.SpiceF phases=3 bus1={bus}.1.2.3 r={config.SPICE_FAULT_R}")
    feeder.solve(controls=False)                       # regulator taps frozen, as in the fault sweep
    i_dss = float(np.abs(feeder.device_measurement("Sw1")["i"]).mean())
    feeder.cmd("Solve mode=faultstudy")
    dss.Circuit.SetActiveBus(bus)
    r, x = dss.Bus.Zsc1()
    r0, x0 = dss.Bus.Zsc0()
    vph = dss.Bus.kVBase() * 1000
    feeder.load_feeder()                               # leave a clean circuit behind
    zl = vph / i_pre
    return {
        "bus": bus, "vph": vph, "vpk": vph * math.sqrt(2), "rth": r, "xth": x, "lth": x / W, "r0": r0, "x0": x0,
        "x_over_r": x / r, "tau_ms": 1000 * x / W / r,
        "i_pre": i_pre, "pf": pf, "rload": zl * pf, "lload": zl * math.sqrt(1 - pf * pf) / W,
        "rf": config.SPICE_FAULT_R, "i_fault_opendss": i_dss,
        "i_fault_thevenin": vph / math.hypot(r + config.SPICE_FAULT_R, x),
        # source phase at the fault instant: theta -> no DC offset, theta + 90 -> the largest
        "alpha_no_offset": math.degrees(math.atan2(x, r)), "alpha_max_offset": math.degrees(math.atan2(x, r)) + 90,
    }


def frontend_params(p: dict) -> dict:
    """Burden sized so the steady fault peak uses FRONTEND_HEADROOM_V of the ADC half-range."""
    i_sec_pk = p["i_fault_thevenin"] * math.sqrt(2) / config.CT_RATIO
    rb = float(f"{config.FRONTEND_HEADROOM_V / i_sec_pk:.2g}")
    rf, cf = config.FRONTEND_RC
    return {"ct_ratio": config.CT_RATIO, "rb": rb, "rf": rf, "cf": cf, "bias": config.ADC_BIAS,
            "vref": config.ADC_VREF, "bits": config.ADC_BITS, "fc_hz": 1 / (2 * math.pi * rf * cf)}


# ---------------------------------------------------------------- schematics
def _g(x: float) -> str:
    return f"{x:.6g}"


def _asc(lines: list[str]) -> bytes:
    """LTspice reads .asc as Windows-1252; everything written here is plain ASCII."""
    return ("\r\n".join(lines) + "\r\n").encode("ascii")


def fault_asc(p: dict) -> bytes:
    """Source -> Rth -> Lth -> node f; behavioural fault resistor and the pre-fault load hang
    from f to ground. Layout follows LTspice's own drafting rules (16 px grid, 48 px stubs)."""
    return _asc([
        "Version 4.1",
        "SHEET 1 1120 880",
        "WIRE 64 112 64 176", "WIRE 176 112 64 112",                       # V1 + up to the rail, on to Rth
        "WIRE 320 112 256 112",                                            # Rth -> Lth
        "WIRE 544 112 400 112", "WIRE 896 112 544 112",                    # Lth -> node f -> load
        "WIRE 544 160 544 112", "WIRE 896 160 896 112",                    # stubs down to the fault and load
        "WIRE 896 288 896 240",                                            # Rload -> Lload
        "WIRE 64 432 64 256", "WIRE 544 432 544 240", "WIRE 896 432 896 368",   # to ground
        "FLAG 64 112 src", "FLAG 480 112 f",
        "FLAG 64 432 0", "FLAG 544 432 0", "FLAG 896 432 0",
        "SYMBOL voltage 64 160 R0", "SYMATTR InstName V1", "SYMATTR Value SINE(0 {Vpk} 60)",
        "SYMBOL res 272 96 R90", "WINDOW 0 0 56 VBottom 2", "WINDOW 3 32 56 VTop 2",
        "SYMATTR InstName Rth", "SYMATTR Value {Rth}",
        "SYMBOL ind 416 96 R90", "WINDOW 0 5 56 VBottom 2", "WINDOW 3 32 56 VTop 2",
        "SYMATTR InstName Lth", "SYMATTR Value {Lth}", "SYMATTR SpiceLine Rser=0",
        "SYMBOL bv 544 144 R0", "SYMATTR InstName Bfault", "SYMATTR Value R=if(time<tf,1e9,Rf)",
        "SYMBOL res 880 144 R0", "SYMATTR InstName Rload", "SYMATTR Value {Rload}",
        "SYMBOL ind 880 272 R0", "SYMATTR InstName Lload", "SYMATTR Value {Lload}", "SYMATTR SpiceLine Rser=0",
        f"TEXT 64 488 Left 2 ;Per-phase equivalent of the IEEE 123-bus feeder seen from bus {p['bus']} (Thevenin R, L from OpenDSS)",
        "TEXT 64 520 Left 2 ;Generated by scripts/spice_run.py - edit shf/spice.py, not this file",
        f"TEXT 64 568 Left 2 !.param Vpk={_g(p['vpk'])} Rth={_g(p['rth'])} Lth={_g(p['lth'])} "
        f"Rload={_g(p['rload'])} Lload={_g(p['lload'])} Rf={_g(p['rf'])} t0={_g(T0)}",
        "TEXT 64 600 Left 2 !.param tf=t0+alpha/360/60",
        f"TEXT 64 632 Left 2 !.step param alpha list {_g(p['alpha_no_offset'])} {_g(p['alpha_max_offset'])}",
        f"TEXT 64 664 Left 2 !.tran 0 {_g(T_END)} 0 2u",
        "TEXT 64 696 Left 2 !.options plotwinsize=0",
        "TEXT 64 728 Left 2 !.meas TRAN Imax MAX I(Lth) FROM 50m TO 150m",
        "TEXT 64 760 Left 2 !.meas TRAN Imin MIN I(Lth) FROM 50m TO 150m",
        "TEXT 64 792 Left 2 !.meas TRAN Irms_fault RMS I(Lth) FROM 116.6667m TO 133.3333m",
    ])


def ct_asc(fe: dict) -> bytes:
    """Secondary current (PWL) || burden on a 1.65 V bias -> RC -> ADC node, clamped to 0..3.3 V."""
    return _asc([
        "Version 4.1",
        "SHEET 1 1120 960",
        "WIRE 64 112 64 176", "WIRE 192 112 64 112", "WIRE 192 176 192 112", "WIRE 288 112 192 112",  # cs rail
        "WIRE 64 320 64 256", "WIRE 64 384 64 320", "WIRE 192 320 192 256", "WIRE 192 320 64 320",   # mid rail
        "WIRE 464 112 368 112", "WIRE 592 112 464 112", "WIRE 720 112 592 112", "WIRE 816 112 720 112",  # adc rail
        "WIRE 464 160 464 112", "WIRE 592 160 592 112", "WIRE 720 112 720 64",
        "WIRE 720 0 720 -48", "WIRE 896 -48 720 -48", "WIRE 896 0 896 -48",                         # vdd rail
        "WIRE 64 528 64 464", "WIRE 464 528 464 224", "WIRE 592 528 592 224", "WIRE 896 528 896 80",  # to ground
        "FLAG 240 112 cs", "FLAG 128 320 mid", "FLAG 816 112 adc", "FLAG 808 -48 vdd",
        "FLAG 64 528 0", "FLAG 464 528 0", "FLAG 592 528 0", "FLAG 896 528 0",
        "SYMBOL res 48 160 R0", "SYMATTR InstName Rb", "SYMATTR Value {Rb}",
        "SYMBOL current 192 256 R180", "WINDOW 0 -24 80 Left 2", "WINDOW 3 -24 56 Left 2",
        "SYMATTR InstName Isec", "SYMATTR Value PWL file=ct_secondary.pwl",
        "SYMBOL voltage 64 368 R0", "SYMATTR InstName Vbias", f"SYMATTR Value {_g(fe['bias'])}",
        "SYMBOL res 384 96 R90", "WINDOW 0 0 56 VBottom 2", "WINDOW 3 32 56 VTop 2",
        "SYMATTR InstName Rflt", f"SYMATTR Value {_g(fe['rf'])}",
        "SYMBOL cap 448 160 R0", "SYMATTR InstName Cflt", f"SYMATTR Value {_g(fe['cf'])}",
        "SYMBOL diode 608 224 R180", "WINDOW 0 24 64 Left 2", "WINDOW 3 24 0 Left 2",
        "SYMATTR InstName Dlo", "SYMATTR Value DCL",
        "SYMBOL diode 736 64 R180", "WINDOW 0 24 64 Left 2", "WINDOW 3 24 0 Left 2",
        "SYMATTR InstName Dhi", "SYMATTR Value DCL",
        "SYMBOL voltage 896 -16 R0", "SYMATTR InstName Vdd", f"SYMATTR Value {_g(fe['vref'])}",
        f"TEXT 64 584 Left 2 ;Secondary current = worst-case fault current from fault_dc_offset.asc / CT ratio {fe['ct_ratio']}",
        "TEXT 64 616 Left 2 ;Generated by scripts/spice_run.py - edit shf/spice.py, not this file",
        f"TEXT 64 664 Left 2 !.param Rb={_g(fe['rb'])}",
        "TEXT 64 696 Left 2 !.model DCL D(Ron=1 Vfwd=0.3)",
        f"TEXT 64 728 Left 2 !.tran 0 {_g(T_END)} 0 2u",
        "TEXT 64 760 Left 2 !.options plotwinsize=0",
        "TEXT 64 792 Left 2 !.meas TRAN Vadc_max MAX V(adc)",
        "TEXT 64 824 Left 2 !.meas TRAN Vadc_min MIN V(adc)",
    ])


# ---------------------------------------------------------------- running LTspice
def ltspice_exe() -> Path:
    if os.environ.get("SHF_LTSPICE"):
        return Path(os.environ["SHF_LTSPICE"])
    for cand in (Path(r"C:\Program Files\ADI\LTspice\LTspice.exe"),
                 Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "ADI" / "LTspice" / "LTspice.exe"):
        if cand.exists():
            return cand
    raise FileNotFoundError("LTspice.exe not found: install LTspice or set SHF_LTSPICE")


def run(asc: Path) -> Path:
    """Batch-simulate a schematic (no window); returns the .raw path."""
    raw = asc.with_suffix(".raw")
    if raw.exists():
        raw.unlink()
    subprocess.run([str(ltspice_exe()), "-b", asc.name], cwd=asc.parent, check=True, timeout=600)
    if not raw.exists():
        log = asc.with_suffix(".log")
        raise RuntimeError(f"LTspice wrote no {raw.name}:\n" + (log.read_text(errors="ignore") if log.exists() else ""))
    return raw


def read_raw(path: Path) -> tuple[dict, list[dict[str, np.ndarray]]]:
    """Binary LTspice transient .raw -> (header, one {signal: array} per step)."""
    blob = path.read_bytes()
    marker = "Binary:\n".encode("utf-16-le")
    cut = blob.index(marker)
    head = blob[:cut].decode("utf-16-le")
    hdr, names, in_vars = {}, [], False
    for line in head.splitlines():
        if in_vars:
            parts = line.split("\t")
            if len(parts) >= 3:
                names.append(parts[2])
            continue
        if line.startswith("Variables:"):
            in_vars = True
        elif ":" in line:
            k, v = line.split(":", 1)
            hdr[k.strip()] = v.strip()
    nvar, npts = int(hdr["No. Variables"]), int(hdr["No. Points"])
    data = blob[cut + len(marker):]
    double = "double" in hdr.get("Flags", "")
    rec = np.dtype([("t", "<f8")] + [(f"v{i}", "<f8" if double else "<f4") for i in range(1, nvar)])
    arr = np.frombuffer(data[: npts * rec.itemsize], dtype=rec)
    t = np.abs(arr["t"])                                  # LTspice flags some points with a negative time
    starts = [0] + [i for i in range(1, len(t)) if t[i] < t[i - 1]] + [len(t)]
    steps = []
    for a, b in zip(starts, starts[1:]):
        d = {"time": t[a:b]}
        for i, n in enumerate(names[1:], 1):
            d[n] = arr[f"v{i}"][a:b].astype(float)
        steps.append(d)
    return hdr, steps


def resample(step: dict, grid: np.ndarray, names: list[str]) -> dict:
    return {n: np.interp(grid, step["time"], step[n]) for n in names}


# ---------------------------------------------------------------- analysis
def adc_samples(t: np.ndarray, v: np.ndarray, fe: dict) -> tuple[np.ndarray, np.ndarray]:
    """Sample V(adc) at ADC_SAMPLES_PER_CYCLE and quantize to ADC_BITS; returns (times, counts)."""
    ts = np.arange(0, t[-1], 1 / (F * config.ADC_SAMPLES_PER_CYCLE))
    full = 2 ** fe["bits"] - 1
    counts = np.clip(np.round(np.interp(ts, t, v) / fe["vref"] * full), 0, full)
    return ts, counts


def dft_rms(counts: np.ndarray, fe: dict) -> np.ndarray:
    """One-cycle full-cycle DFT magnitude of the samples, converted back to primary RMS amps.
    Element k uses samples k-N+1 .. k (NaN until a full cycle exists)."""
    n = config.ADC_SAMPLES_PER_CYCLE
    volts = counts / (2 ** fe["bits"] - 1) * fe["vref"] - fe["bias"]
    amps = volts / fe["rb"] * fe["ct_ratio"]
    out = np.full(len(amps), np.nan)
    k = np.arange(n)
    c, s = np.cos(2 * np.pi * k / n), np.sin(2 * np.pi * k / n)
    for i in range(n - 1, len(amps)):
        win = amps[i - n + 1: i + 1]
        re, im = (2 / n) * (win @ c), (2 / n) * (win @ s)
        out[i] = math.hypot(re, im) / math.sqrt(2)
    return out


def summarize(p: dict, fe: dict, meas_fault: dict, steps: list[dict], ct: dict) -> dict:
    """Numbers for the report, all from the LTspice runs and the study."""
    cases = {}
    for name, st in zip(("no_offset", "max_offset"), steps):
        after = st["time"] >= T0 + p["alpha_no_offset" if name == "no_offset" else "alpha_max_offset"] / 360 / F
        i = st["I(Lth)"]
        cases[name] = {"peak_a": float(np.max(np.abs(i[after]))), "time_of_peak_ms": float(st["time"][after][np.argmax(np.abs(i[after]))] * 1000)}
    i_ss = meas_fault["Irms_fault"]
    for c in cases.values():
        c["asymmetry"] = c["peak_a"] / (math.sqrt(2) * i_ss)
    t, vadc = ct["time"], ct["V(adc)"]
    ts, counts = adc_samples(t, vadc, fe)
    est = dft_rms(counts, fe)
    tf = T0 + p["alpha_max_offset"] / 360 / F
    after = ts >= tf
    within = np.abs(est - i_ss) <= 0.05 * i_ss
    settle = None
    for j in np.where(after)[0]:
        if within[j:].all():
            settle = float((ts[j] - tf) * 1000)
            break
    clip = (counts <= 0) | (counts >= 2 ** fe["bits"] - 1)
    counts_per_amp = fe["rb"] / fe["ct_ratio"] / fe["vref"] * (2 ** fe["bits"] - 1)
    return {
        "bus": p["bus"],
        "model": {k: p[k] for k in ("vph", "rth", "xth", "x_over_r", "tau_ms", "i_pre", "pf", "rf",
                                    "alpha_no_offset", "alpha_max_offset")},
        "fault_rms_a": {"ltspice_steady": i_ss, "thevenin": p["i_fault_thevenin"], "opendss_3ph_sw1": p["i_fault_opendss"]},
        "first_peak": cases,
        "asymmetry_ansi_estimate": 1.02 + 0.98 * math.exp(-3 / p["x_over_r"]),
        "dc_left_after_one_cycle": math.exp(-1000 / F / p["tau_ms"]),
        "frontend": {**fe, "vadc_max": float(vadc.max()), "vadc_min": float(vadc.min()),
                     "clipped_samples": int(clip.sum()), "counts_per_primary_amp": counts_per_amp,
                     "primary_amps_per_count": 1 / counts_per_amp,
                     "prefault_peak_counts": p["i_pre"] * math.sqrt(2) * counts_per_amp,
                     "dft_settle_ms_within_5pct": settle,
                     "dft_max_over_steady": float(np.nanmax(est[after]) / i_ss)},
    }


# ---------------------------------------------------------------- arcing high-impedance fault
def arc_resistance(vpk: float, vp: float, vn: float, irms: float) -> float:
    """Rp = Rn of the two-diode arc model that gives `irms` RMS from a sine of peak `vpk`:
    i = (v - Vp)/R while v > Vp, (v + Vn)/R while v < -Vn, zero in between."""
    v = vpk * np.sin(np.linspace(0, 2 * np.pi, 200_000, endpoint=False))
    drive = np.where(v > vp, v - vp, 0.0) + np.where(v < -vn, v + vn, 0.0)
    return float(np.sqrt(np.mean(drive ** 2)) / irms)


def hif_params(p: dict) -> dict:
    """Ground-fault source impedance (2 Z1 + Z0) / 3 at the fault bus, the arc voltages and,
    for each fault resistance in HIF_R_CASES, the arc resistance with the same RMS current."""
    rs = (2 * p["rth"] + p["r0"]) / 3
    xs = (2 * p["xth"] + p["x0"]) / 3
    vp, vn = config.HIF_VP_FRAC * p["vpk"], config.HIF_VN_FRAC * p["vpk"]
    cases = []
    for r in config.HIF_R_CASES:
        target = p["vph"] / math.hypot(rs + r, xs)
        cases.append({"r_fault": float(r), "irms_target": target,
                      "r_arc": arc_resistance(p["vpk"], vp, vn, target) - rs})
    return {"bus": p["bus"], "vpk": p["vpk"], "rs": rs, "xs": xs, "ls": xs / W, "vp": vp, "vn": vn,
            "vp_frac": config.HIF_VP_FRAC, "vn_frac": config.HIF_VN_FRAC, "cases": cases}


def hif_asc(h: dict) -> bytes:
    """Two copies of the ground-fault source side by side: on the left the two-diode arc
    (Dp-Rp-Vp conducts above +Vp, Dn-Rn-Vn below -Vn), on the right the fixed-resistance
    fault the fault sweep uses. .step runs each fault resistance in HIF_R_CASES."""
    table = ", ".join(f"{_g(c['r_fault'])}, {_g(c['r_arc'])}" for c in h["cases"])
    steps = " ".join(_g(c["r_fault"]) for c in h["cases"])
    return _asc([
        "Version 4.1",
        "SHEET 1 1600 1100",
        # arc circuit
        "WIRE 64 112 64 176", "WIRE 176 112 64 112", "WIRE 320 112 256 112",
        "WIRE 544 112 400 112", "WIRE 704 112 544 112",
        "WIRE 544 160 544 112", "WIRE 704 160 704 112",
        "WIRE 544 288 544 224", "WIRE 544 448 544 368", "WIRE 704 288 704 224", "WIRE 704 448 704 368",
        "WIRE 64 592 64 256", "WIRE 544 592 544 528", "WIRE 704 592 704 528",
        # fixed-resistance circuit
        "WIRE 1024 112 1024 176", "WIRE 1136 112 1024 112", "WIRE 1280 112 1216 112",
        "WIRE 1504 112 1360 112", "WIRE 1504 176 1504 112",
        "WIRE 1024 592 1024 256", "WIRE 1504 592 1504 256",
        "FLAG 480 112 farc", "FLAG 1440 112 flin",
        "FLAG 64 592 0", "FLAG 544 592 0", "FLAG 704 592 0", "FLAG 1024 592 0", "FLAG 1504 592 0",
        "SYMBOL voltage 64 160 R0", "SYMATTR InstName Va", "SYMATTR Value SINE(0 {Vpk} 60)",
        "SYMBOL res 272 96 R90", "WINDOW 0 0 56 VBottom 2", "WINDOW 3 32 56 VTop 2",
        "SYMATTR InstName Rsa", "SYMATTR Value {Rsrc}",
        "SYMBOL ind 416 96 R90", "WINDOW 0 5 56 VBottom 2", "WINDOW 3 32 56 VTop 2",
        "SYMATTR InstName Larc", "SYMATTR Value {Lsrc}", "SYMATTR SpiceLine Rser=0",
        "SYMBOL diode 528 160 R0", "SYMATTR InstName Dp", "SYMATTR Value DARC",
        "SYMBOL res 528 272 R0", "SYMATTR InstName Rp", "SYMATTR Value {Ra}",
        "SYMBOL voltage 544 432 R0", "SYMATTR InstName Vp", "SYMATTR Value {Vpos}",
        "SYMBOL diode 720 224 R180", "WINDOW 0 24 64 Left 2", "WINDOW 3 24 0 Left 2",
        "SYMATTR InstName Dn", "SYMATTR Value DARC",
        "SYMBOL res 688 272 R0", "SYMATTR InstName Rn", "SYMATTR Value {Ra}",
        "SYMBOL voltage 704 432 R0", "SYMATTR InstName Vn", "SYMATTR Value {-Vneg}",
        "SYMBOL voltage 1024 160 R0", "SYMATTR InstName Vl", "SYMATTR Value SINE(0 {Vpk} 60)",
        "SYMBOL res 1232 96 R90", "WINDOW 0 0 56 VBottom 2", "WINDOW 3 32 56 VTop 2",
        "SYMATTR InstName Rsl", "SYMATTR Value {Rsrc}",
        "SYMBOL ind 1376 96 R90", "WINDOW 0 5 56 VBottom 2", "WINDOW 3 32 56 VTop 2",
        "SYMATTR InstName Llin", "SYMATTR Value {Lsrc}", "SYMATTR SpiceLine Rser=0",
        "SYMBOL res 1488 160 R0", "SYMATTR InstName Rfl", "SYMATTR Value {Rlin}",
        f"TEXT 64 656 Left 2 ;Ground fault at bus {h['bus']}: source (2 Z1 + Z0)/3 from OpenDSS. "
        "Left: two-diode arc (Emanuel et al. 1990). Right: fixed resistance, as in the fault sweep",
        "TEXT 64 688 Left 2 ;Generated by scripts/spice_run.py - edit shf/spice.py, not this file",
        f"TEXT 64 736 Left 2 !.param Vpk={_g(h['vpk'])} Rsrc={_g(h['rs'])} Lsrc={_g(h['ls'])} "
        f"Vpos={_g(h['vp'])} Vneg={_g(h['vn'])}",
        f"TEXT 64 768 Left 2 !.param Ra=table(Rlin, {table})",
        f"TEXT 64 800 Left 2 !.step param Rlin list {steps}",
        "TEXT 64 832 Left 2 !.model DARC D(Ron=1m Roff=1G Vfwd=0)",
        f"TEXT 64 864 Left 2 !.tran 0 {_g(HIF_T_END)} 0 2u",
        "TEXT 64 896 Left 2 !.options plotwinsize=0",
        f"TEXT 64 928 Left 2 !.meas TRAN Irms_arc RMS I(Larc) FROM {_g(HIF_T_FROM)} TO {_g(HIF_T_END)}",
        f"TEXT 64 960 Left 2 !.meas TRAN Irms_lin RMS I(Llin) FROM {_g(HIF_T_FROM)} TO {_g(HIF_T_END)}",
    ])


def spectrum(t: np.ndarray, i: np.ndarray, n: int = 1536) -> dict:
    """RMS, DC, 60 Hz component and harmonics of a current over the settled window
    (a whole number of cycles, so every harmonic falls on an FFT bin)."""
    cycles = round((HIF_T_END - HIF_T_FROM) * F)
    grid = HIF_T_FROM + np.arange(n) * (HIF_T_END - HIF_T_FROM) / n
    x = np.interp(grid, t, i)
    X = np.fft.rfft(x) / n
    fund = abs(X[cycles])
    h = {k: float(abs(X[k * cycles]) / fund) for k in range(2, 26)}
    return {"rms": float(np.sqrt(np.mean(x ** 2))), "dc": float(X[0].real), "i1_rms": float(2 * fund / math.sqrt(2)),
            "h2_pct": 100 * h[2], "h3_pct": 100 * h[3], "h5_pct": 100 * h[5],
            "thd_pct": 100 * math.sqrt(sum(v * v for v in h.values()))}


def adc_view(t: np.ndarray, i: np.ndarray, fe: dict) -> dict:
    """The fault current alone through the CT, burden and bias of the front end (linear range,
    RC filter left out), sampled and quantized by the ADC, then the one-cycle DFT estimate."""
    sel = (t >= HIF_T_FROM) & (t <= HIF_T_END)
    v = fe["bias"] + i[sel] / fe["ct_ratio"] * fe["rb"]
    ts, counts = adc_samples(t[sel] - HIF_T_FROM, v, fe)
    est = dft_rms(counts, fe)
    # samples are locked to 60 Hz, so every full-cycle window holds the same samples and the
    # estimate is one number; its error is the quantization error at this sampling phase
    return {"counts_span": int(counts.max() - counts.min()), "dft_estimate_a": float(np.nanmean(est))}


def summarize_hif(h: dict, p: dict, fe: dict, steps: list[dict], meas_hif: dict) -> dict:
    """Arc vs fixed resistance with the same RMS current, per fault resistance."""
    cases = {}
    for k, (c, st) in enumerate(zip(h["cases"], steps)):
        t = st["time"]
        arc, lin = spectrum(t, -st["I(Larc)"]), spectrum(t, -st["I(Llin)"])
        view_arc, view_lin = adc_view(t, -st["I(Larc)"], fe), adc_view(t, -st["I(Llin)"], fe)
        cases[f"{c['r_fault']:g}"] = {
            "r_fault": c["r_fault"], "r_arc": c["r_arc"],
            "irms_linear": meas_hif["irms_lin"][k], "irms_arc": meas_hif["irms_arc"][k],
            "i1_linear": lin["i1_rms"], "i1_arc": arc["i1_rms"],
            "i1_arc_vs_linear": arc["i1_rms"] / lin["i1_rms"],
            "dc_arc_a": arc["dc"], "h2_arc_pct": arc["h2_pct"], "h3_arc_pct": arc["h3_pct"],
            "h5_arc_pct": arc["h5_pct"], "thd_arc_pct": arc["thd_pct"], "thd_linear_pct": lin["thd_pct"],
            "share_of_prefault_load_pct": 100 * meas_hif["irms_arc"][k] / p["i_pre"],
            "adc_counts_span_arc": view_arc["counts_span"], "adc_counts_span_linear": view_lin["counts_span"],
            "dft_estimate_arc_a": view_arc["dft_estimate_a"],
            "dft_error_arc_pct": 100 * (view_arc["dft_estimate_a"] / arc["i1_rms"] - 1),
        }
    return {"bus": h["bus"], "model": {k: h[k] for k in ("rs", "xs", "vp", "vn", "vp_frac", "vn_frac")},
            "source": "two-diode arc model, Emanuel et al., IEEE Trans. Power Delivery 5(2), 1990",
            "cases": cases}
