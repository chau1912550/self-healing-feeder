"""Residual-current waveforms: normal feeder operation, disturbances, and Emanuel-model HIF arcs.

All parameter ranges are assumptions chosen to cover typical published behaviour; they are not field
measurements. Results trained on these waveforms must be described as simulation results.
"""
import numpy as np

from .frontend import F_LINE, FS_SIM, N_CYCLE, OVERSAMPLE, codes_to_amps, sense, sim_rate_hz

W = 2 * np.pi * F_LINE
TWO_PI = 2 * np.pi
V_PHASE_PK = 7200.0 * np.sqrt(2)    # 12.47 kV feeder, phase-to-ground peak
WARMUP = 4                          # cycles dropped while the filter settles
N_CYCLES = 60                       # cycles kept per event (1 s at 60 Hz, 1.2 s at 50 Hz)

# Emanuel arc model: conducts above +Vp through Rp and below -Vn through Rn.
SURFACES = {
    "wet_grass": {"Vp": (0.5e3, 2.0e3), "R": (300.0, 700.0)},
    "wet_sand": {"Vp": (1.0e3, 3.0e3), "R": (600.0, 1500.0)},
    "concrete": {"Vp": (1.5e3, 4.5e3), "R": (800.0, 2000.0)},
    "dry_grass": {"Vp": (2.0e3, 5.0e3), "R": (900.0, 2500.0)},
    "dry_asphalt": {"Vp": (3.0e3, 7.0e3), "R": (2000.0, 6000.0)},
}
DISTURBANCES = ("none", "load_step", "cap_switch", "inrush", "motor_start", "arc_welder",
                "nonlinear_fluct")


def _base(t, rng, w=W):
    a1 = np.exp(rng.uniform(np.log(1.0), np.log(20.0))) * np.sqrt(2)   # 1-20 A rms unbalance
    ph = rng.uniform(0, TWO_PI)
    env = 1 + rng.uniform(0, 0.04) * np.sin(TWO_PI * rng.uniform(0.1, 2.0) * t + rng.uniform(0, TWO_PI))
    i = a1 * env * np.sin(w * t + ph)
    for h, hi in ((3, 0.6), (5, 0.2), (7, 0.1), (9, 0.08)):          # triplen-heavy neutral current
        i += a1 * rng.uniform(0, hi) * np.sin(h * w * t + rng.uniform(0, TWO_PI))
    i += rng.normal(0, rng.uniform(0.02, 0.2), t.shape)
    if rng.random() < 0.3:                                              # inverter switching noise
        i += rng.uniform(0.2, 2.0) * np.sin(TWO_PI * rng.uniform(8e3, 20e3) * t + rng.uniform(0, TWO_PI))
    return i, a1, ph


def _arc(t, t0, rng, s, w=W, v_phase_pk=V_PHASE_PK):
    vp, rp = rng.uniform(*s["Vp"]), rng.uniform(*s["R"])
    vn, rn = vp * rng.uniform(1.05, 1.4), rp * rng.uniform(0.85, 1.15)
    if rng.random() < 0.5:
        vp, vn, rp, rn = vn, vp, rn, rp
    sig, p_off = rng.uniform(0.03, 0.12), rng.uniform(0.0, 0.3)
    phv = rng.uniform(0, TWO_PI)
    v = v_phase_pk * np.sin(w * t + phv)
    half = np.floor((w * t + phv) / np.pi).astype(np.int64)
    half -= half.min()
    jit = 1 + sig * rng.standard_normal((4, half.max() + 1))            # new arc each half cycle
    VP, VN, RP, RN = vp * jit[0][half], vn * jit[1][half], rp * jit[2][half], rn * jit[3][half]
    i = np.where(v > VP, (v - VP) / RP, 0.0) + np.where(v < -VN, (v + VN) / RN, 0.0)
    cyc = half // 2
    i *= (rng.random(cyc.max() + 1) >= p_off)[cyc]                      # arc fails to restrike
    dt = t - t0
    a0, tb = rng.uniform(0.1, 0.5), rng.uniform(0.02, 0.3)
    env = np.where(dt >= 0, 1 - (1 - a0) * np.exp(-np.clip(dt, 0, None) / tb), 0.0)
    return i * env


def _bursts(rng, n):
    on, state, k = np.zeros(n, bool), rng.random() < 0.5, 0
    while k < n:
        L = int(rng.integers(6, 31))
        on[k:k + L] = state
        state, k = not state, k + L
    return on


def _disturb(t, t1, rng, kind, a1, ph, w=W):
    if kind == "none":
        return 0.0
    dt = t - t1
    on = dt >= 0
    dtp = np.clip(dt, 0, None)
    cyc = np.floor(w * t / TWO_PI).astype(np.int64)
    nc = cyc.max() + 1
    if kind == "load_step":
        return on * rng.uniform(-0.5, 1.0) * a1 * np.sin(w * t + ph + rng.uniform(-0.3, 0.3))
    if kind == "cap_switch":
        A, f, tau = rng.uniform(5, 40), rng.uniform(300, 1200), rng.uniform(2e-3, 10e-3)
        return on * A * np.exp(-dtp / tau) * np.sin(TWO_PI * f * dtp + rng.uniform(0, TWO_PI))
    if kind == "inrush":
        ipk, tau, th = rng.uniform(10, 40), rng.uniform(0.1, 1.0), np.deg2rad(rng.uniform(60, 150))
        pulse = np.clip(np.sin(w * t + rng.uniform(0, TWO_PI)) - np.cos(th), 0, None) / (1 - np.cos(th))
        return on * rng.choice([-1.0, 1.0]) * ipk * np.exp(-dtp / tau) * pulse
    if kind == "motor_start":
        k, tau, lag = rng.uniform(2, 6), rng.uniform(0.1, 0.5), np.deg2rad(rng.uniform(40, 80))
        return on * (k - 1) * a1 * np.exp(-dtp / tau) * np.sin(w * t + ph - lag)
    if kind == "arc_welder":                                            # hard negative: random but symmetric
        aw = rng.uniform(3, 20) * np.sqrt(2)
        amp = np.clip(1 + 0.25 * rng.standard_normal(nc), 0.2, None)
        x = np.tanh(4 * np.sin(w * t + rng.uniform(0, TWO_PI)))
        return on * aw * amp[cyc] * _bursts(rng, nc)[cyc] * x
    if kind == "nonlinear_fluct":                                       # many electronic loads switching
        out = 0.0
        for h, hi in ((3, 0.5), (5, 0.2), (7, 0.1)):
            fac = 1 + rng.uniform(0.1, 0.3) * rng.standard_normal(nc)
            out = out + a1 * rng.uniform(0.1, hi) * fac[cyc] * np.sin(h * w * t + rng.uniform(0, TWO_PI))
        return on * out
    raise ValueError(kind)


def make_event(rng, is_hif, surface=None, disturbance=None, f_line=F_LINE):
    """One 60-cycle record. Returns (amps at the ADC, meta). meta['start_cycle'] is the event cycle."""
    fs_sim = FS_SIM if f_line == F_LINE else sim_rate_hz(f_line)
    w = W if f_line == F_LINE else 2 * np.pi * float(f_line)
    n = (WARMUP + N_CYCLES) * N_CYCLE * OVERSAMPLE
    t = np.arange(n) / fs_sim
    start = int(rng.integers(12, 41))
    t0 = (WARMUP + start) / float(f_line)
    i, a1, ph = _base(t, rng, w=w)
    meta = {"is_hif": bool(is_hif), "start_cycle": start, "base_rms": float(a1 / np.sqrt(2))}
    if f_line != F_LINE:
        meta["f_line"] = float(f_line)
    if is_hif:
        surface = surface or str(rng.choice(list(SURFACES)))
        arc = _arc(t, t0, rng, SURFACES[surface], w=w)
        i = i + arc
        if disturbance is None:
            disturbance = str(rng.choice(DISTURBANCES)) if rng.random() < 0.25 else "none"
        t1 = (WARMUP + rng.integers(0, N_CYCLES)) / float(f_line)
        tail = arc[-20 * N_CYCLE * OVERSAMPLE:]
        meta["arc_rms"] = float(np.sqrt(np.mean(tail ** 2)))
    else:
        disturbance = disturbance or str(rng.choice(DISTURBANCES))
        t1 = t0
        meta["arc_rms"] = 0.0
    i = i + _disturb(t, t1, rng, disturbance, a1, ph, w=w)
    meta["surface"] = surface or "none"
    meta["disturbance"] = disturbance
    amps = codes_to_amps(sense(i, rng, f_line=f_line))[WARMUP * N_CYCLE:]
    return amps, meta
