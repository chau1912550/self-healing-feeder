"""Self-contained Tier-1 Edge HIF-Sensor model (research/hif-fusion/PLAN.md).

Exact mathematical and parameter parity with the companion project `hif-sensor`
(`hif/frontend.py`, `hif/features.py`, `hif/waveforms.py`, `train_kaggle.py`),
packaged self-contained inside `shf/` so both local runs and Kaggle zips work
with zero external path dependencies:

  1. Analog front end + 12-bit ADC @ 15.36 kHz:
     - Clamp CT SCT-013-000 (2000:1), 33 ohm burden -> 16.5 mV/A, 1.65 V mid-rail bias.
     - 4th-order Butterworth low-pass filter (two unity-gain Sallen-Key stages):
       -3 dB at 2,047.9 Hz (Python bilinear IIR) vs 2,045.1 Hz (LTspice UniversalOpAmp2).
     - Schottky clamps [-0.3 V, 3.6 V], 12-bit ADC with assumed 1.5 LSB Gaussian noise.
  2. 16 window features over K = 8 cycles (133.3 ms @ 60 Hz, 256 samples/cycle).
  3. Emanuel two-diode ground-arc generator (5 surfaces) + 7 background disturbances.
  4. Frozen int8 Tiny MLP inference (`16 -> 16 -> 8 -> 1`, 417 params, 504 bytes)
     loaded from `model_int8.npz`, plus PERSIST = 3 relay persistence logic.

Simulation only. All waveforms and ADC noise parameters are modeled assumptions,
not field measurements.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy import signal

from . import config

# ---------------------------------------------------------------------------
# 1. Analog front end + ESP32-S3 ADC constants (exact parity with hif/frontend.py)
# ---------------------------------------------------------------------------
F_LINE = 60.0
N_CYCLE = 256                       # ADC samples per 60 Hz cycle
FS_ADC = F_LINE * N_CYCLE           # 15,360 Hz
OVERSAMPLE = 8
FS_SIM = FS_ADC * OVERSAMPLE        # 122,880 Hz time step for the "analog" signal
CT_RATIO = 2000.0                   # ASSUMPTION: SCT-013-000 clamp CT (100 A : 50 mA), ideal
R_BURDEN = 33.0                     # ohms
GAIN_V_PER_A = R_BURDEN / CT_RATIO  # 16.5 mV per primary amp
VREF = 1.65                         # mid-rail bias (V)
VDD = 3.3                           # supply rail (V)
ADC_BITS = 12                       # ASSUMPTION: 12-bit ESP32-S3 ADC
ADC_FS_V = 3.3
ADC_NOISE_LSB = 1.5                 # ASSUMPTION: additive Gaussian ADC noise; nonlinearity not modeled
# (R, C_feedback, C_ground) of each unity-gain Sallen-Key Butterworth stage
STAGES = ((8.66e3, 10e-9, 8.2e-9), (4.42e3, 47e-9, 6.8e-9))
LTSPICE_CUTOFF_HZ = 2045.1          # LTspice AC verification (hif-sensor/circuit/ltspice_results.json)

# ---------------------------------------------------------------------------
# 2. Window feature constants (exact parity with hif/features.py)
# ---------------------------------------------------------------------------
K = 8                               # window length in 60 Hz cycles (133.3 ms)
FEATURES = [
    "log_I1", "log_I3", "h2_ratio", "h3_ratio", "h5_ratio", "even_ratio", "dc_ratio",
    "peak_asym", "I3_cv", "I1_cv", "ph3_jitter", "cycle_diff", "even_std", "h3_trend",
    "I1_trend", "interharm",
]
EPS = 1e-6

# ---------------------------------------------------------------------------
# 3. Waveform generator constants (exact parity with hif/waveforms.py)
# ---------------------------------------------------------------------------
W = 2.0 * np.pi * F_LINE
TWO_PI = 2.0 * np.pi
V_PHASE_PK = 7200.0 * np.sqrt(2.0)  # ASSUMPTION: 12.47 kV nominal phase-to-ground peak for Emanuel arc model
WARMUP = 4                          # cycles dropped while the anti-alias filter settles
N_CYCLES = 60                       # cycles kept per 1-second record
N_SIM_SAMPLES = (WARMUP + N_CYCLES) * N_CYCLE * OVERSAMPLE  # 131,072 samples at FS_SIM

# ASSUMPTION: Emanuel arc model surface ranges (conducts above +Vp through Rp and below -Vn through Rn).
SURFACES: dict[str, dict[str, tuple[float, float]]] = {
    "wet_grass":   {"Vp": (0.5e3, 2.0e3), "R": (300.0, 700.0)},
    "wet_sand":    {"Vp": (1.0e3, 3.0e3), "R": (600.0, 1500.0)},
    "concrete":    {"Vp": (1.5e3, 4.5e3), "R": (800.0, 2000.0)},
    "dry_grass":   {"Vp": (2.0e3, 5.0e3), "R": (900.0, 2500.0)},
    "dry_asphalt": {"Vp": (3.0e3, 7.0e3), "R": (2000.0, 6000.0)},
}
DISTURBANCES: tuple[str, ...] = (
    "none", "load_step", "cap_switch", "inrush", "motor_start", "arc_welder", "nonlinear_fluct",
)

# ---------------------------------------------------------------------------
# 4. Tiny MLP int8 constants (exact parity with hif-sensor/train_kaggle.py)
# ---------------------------------------------------------------------------
SEED = 42
N_EVENTS = 4000                     # half HIF, half normal (fallback training spec)
MAX_FALSE_ALARM = 0.01              # validation false-alarm budget
PERSIST = 3                         # consecutive windows above threshold before relay alarm
HIDDEN = (16, 8)
EXPECTED_PARAMS = 417               # (16*16+16) + (16*8+8) + (8*1+1)
EXPECTED_BYTES = 504                # int8 weights (392 B) + float32 biases (100 B) + float32 scales (12 B)
FROZEN_MODEL_SHA256 = "3ba5bd23685d7964a6cea0c94064c1e65a8bf3129d83ac129215d110218397c1"

_SOS: np.ndarray | None = None
_STD_T: np.ndarray | None = None
_STD_HARMONICS: dict[int, tuple[np.ndarray, np.ndarray]] | None = None
_STD_CYC: np.ndarray | None = None


# ---------------------------------------------------------------------------
# Front-end functions
# ---------------------------------------------------------------------------
def analog_den() -> np.ndarray:
    """Denominator of H(s) = 1 / prod(s^2 R^2 C1 C2 + 2 s R C2 + 1)."""
    a = np.array([1.0])
    for r, c_fb, c_gnd in STAGES:
        a = np.polymul(a, [r * r * c_fb * c_gnd, 2.0 * r * c_gnd, 1.0])
    return a


def cutoff_hz() -> float:
    """Analog -3 dB cutoff frequency of the 4th-order Butterworth Sallen-Key front end (Hz)."""
    w = 2.0 * np.pi * np.logspace(2, 4.5, 20000)
    _, h = signal.freqs([1.0], analog_den(), worN=w)
    return float(w[np.argmax(np.abs(h) < 1.0 / np.sqrt(2.0))] / (2.0 * np.pi))


def _sos() -> np.ndarray:
    global _SOS
    if _SOS is None:
        a = analog_den()
        z, p, k = signal.bilinear_zpk([], np.roots(a), 1.0 / a[0], FS_SIM)
        _SOS = signal.zpk2sos(z, p, k)
    return _SOS


def sense(i_primary: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Primary current (A) at FS_SIM -> 12-bit ADC codes at FS_ADC.

    Supports both 1-D `(T,)` and batched 2-D `(N, T)` arrays along the last axis.
    """
    arr = np.asarray(i_primary, dtype=np.float64)
    v = signal.sosfilt(_sos(), arr * GAIN_V_PER_A, axis=-1)[..., ::OVERSAMPLE] + VREF
    v = np.clip(v, -0.3, VDD + 0.3)                         # Schottky input clamps
    lsb = ADC_FS_V / (2 ** ADC_BITS - 1)
    code = np.round(v / lsb + rng.normal(0.0, ADC_NOISE_LSB, v.shape))
    return np.clip(code, 0, 2 ** ADC_BITS - 1).astype(np.int16)


def codes_to_amps(code: np.ndarray) -> np.ndarray:
    """Convert 12-bit ADC codes back to estimated primary amperes."""
    lsb = ADC_FS_V / (2 ** ADC_BITS - 1)
    return (np.asarray(code, dtype=np.float64) * lsb - VREF) / GAIN_V_PER_A


# ---------------------------------------------------------------------------
# 16 window features (exact parity with hif/features.py)
# ---------------------------------------------------------------------------
def window_features(amps: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """amps: 1-D samples, whole cycles. Returns (X [n_windows, 16] float32, end_cycle [n_windows] int16)."""
    c = np.asarray(amps, dtype=np.float64).reshape(-1, N_CYCLE)
    n_c = len(c)
    if n_c < K:
        return np.empty((0, len(FEATURES)), dtype=np.float32), np.empty((0,), dtype=np.int16)

    X = np.fft.rfft(c, axis=1) / (N_CYCLE / 2)
    X[:, 0] /= 2
    mag = np.abs(X)
    I1 = mag[:, 1] + EPS
    I3 = mag[:, 3] + EPS
    even = mag[:, 2] + mag[:, 4] + mag[:, 6]
    c_max = c.max(1)
    c_min = c.min(1)
    asym = (c_max + c_min) / (c_max - c_min + EPS)
    ph31 = np.exp(1j * (np.angle(X[:, 3]) - 3 * np.angle(X[:, 1])))
    energy = (c ** 2).sum(1) + EPS
    cdiff = np.zeros(n_c)
    cdiff[1:] = ((c[1:] - c[:-1]) ** 2).sum(1) / energy[1:]

    h = K // 2
    swv = np.lib.stride_tricks.sliding_window_view
    i1_w = swv(I1, K)
    i3_w = swv(I3, K)
    r2_w = swv(mag[:, 2] / I1, K)
    r3_w = swv(I3 / I1, K)
    r5_w = swv(mag[:, 5] / I1, K)
    re_w = swv(even / I1, K)
    dc_w = swv(mag[:, 0] / I1, K)
    as_w = swv(asym, K)
    ph_w = swv(ph31, K)
    cd_w = swv(cdiff, K)

    i1_mean = i1_w.mean(axis=1)
    i3_mean = i3_w.mean(axis=1)
    R = np.clip(np.abs(ph_w.mean(axis=1)), EPS, 1.0)

    # 4-cycle interharmonic FFT for windows ending at j = K-1 .. n_c-1: c[j-3:j+1].ravel()
    c4 = swv(c, 4, axis=0)[K - 4:]
    c4 = np.transpose(c4, (0, 2, 1)).reshape(-1, 4 * N_CYCLE)
    P = np.abs(np.fft.rfft(c4, axis=1)) ** 2
    interharm = 1.0 - P[:, ::4].sum(axis=1) / (P.sum(axis=1) + EPS)

    rows = np.column_stack([
        np.log10(i1_mean),
        np.log10(i3_mean),
        r2_w.mean(axis=1),
        r3_w.mean(axis=1),
        r5_w.mean(axis=1),
        re_w.mean(axis=1),
        dc_w.mean(axis=1),
        as_w.mean(axis=1),
        i3_w.std(axis=1) / i3_mean,
        i1_w.std(axis=1) / i1_mean,
        np.sqrt(-2.0 * np.log(R)),
        cd_w.mean(axis=1),
        re_w.std(axis=1),
        r3_w[:, h:].mean(axis=1) - r3_w[:, :h].mean(axis=1),
        np.log10(i1_w[:, h:].mean(axis=1) / i1_w[:, :h].mean(axis=1)),
        interharm,
    ]).astype(np.float32)
    ends = np.arange(K - 1, n_c, dtype=np.int16)
    return rows, ends


def window_labels(ends: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
    """1 = at least K/2 arcing cycles in window, 0 = no arc yet / normal, -1 = ambiguous."""
    if not meta["is_hif"]:
        return np.zeros(len(ends), np.int8)
    s = meta["start_cycle"]
    y = np.full(len(ends), -1, np.int8)
    y[ends < s] = 0
    y[ends - s + 1 >= K // 2] = 1
    return y


# ---------------------------------------------------------------------------
# Waveforms: 5 Emanuel surfaces + 7 disturbances (exact parity with hif/waveforms.py)
# ---------------------------------------------------------------------------
def standard_time_grid() -> np.ndarray:
    """Standard 1-second + warmup time grid (131,072 samples at FS_SIM = 122,880 Hz)."""
    global _STD_T
    if _STD_T is None:
        _STD_T = np.arange(N_SIM_SAMPLES, dtype=np.float64) / FS_SIM
    return _STD_T


def _standard_tables() -> tuple[np.ndarray, dict[int, tuple[np.ndarray, np.ndarray]], np.ndarray]:
    """Cached harmonic sin/cos tables on the standard time grid for fast fusion synthesis."""
    global _STD_HARMONICS, _STD_CYC
    t = standard_time_grid()
    if _STD_HARMONICS is None or _STD_CYC is None:
        _STD_HARMONICS = {
            h: (np.sin(h * W * t), np.cos(h * W * t))
            for h in (1, 3, 5, 7, 9)
        }
        _STD_CYC = np.floor(W * t / TWO_PI).astype(np.int64)
    return t, _STD_HARMONICS, _STD_CYC


def _sin_harmonic(h: int, ph: float, t: np.ndarray) -> np.ndarray:
    """Compute sin(h * W * t + ph) using cached tables when on the standard time grid."""
    if t is _STD_T and _STD_HARMONICS is not None and h in _STD_HARMONICS:
        s_h, c_h = _STD_HARMONICS[h]
        return s_h * np.cos(ph) + c_h * np.sin(ph)
    return np.sin(h * W * t + ph)


def _base(t: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, float, float]:
    """Exact parity with hif-sensor/hif/waveforms.py:_base()."""
    a1 = np.exp(rng.uniform(np.log(1.0), np.log(20.0))) * np.sqrt(2.0)  # 1-20 A rms unbalance
    ph = rng.uniform(0.0, TWO_PI)
    env = 1.0 + rng.uniform(0.0, 0.04) * np.sin(TWO_PI * rng.uniform(0.1, 2.0) * t + rng.uniform(0.0, TWO_PI))
    i = a1 * env * np.sin(W * t + ph)
    for h, hi in ((3, 0.6), (5, 0.2), (7, 0.1), (9, 0.08)):             # triplen-heavy neutral current
        i += a1 * rng.uniform(0.0, hi) * np.sin(h * W * t + rng.uniform(0.0, TWO_PI))
    i += rng.normal(0.0, rng.uniform(0.02, 0.2), t.shape)
    if rng.random() < 0.3:                                              # inverter switching noise
        i += rng.uniform(0.2, 2.0) * np.sin(TWO_PI * rng.uniform(8e3, 20e3) * t + rng.uniform(0.0, TWO_PI))
    return i, float(a1), float(ph)


def make_base_residual(
    t: np.ndarray,
    rng: np.random.Generator,
    base_rms: float,
    *,
    force_inverter_noise: bool = False,
) -> tuple[np.ndarray, float, float]:
    """Local pre-fault residual background anchored to `base_rms` (A RMS), matching `_base()` harmonics.

    ASSUMPTION (research/hif-fusion/PLAN.md §3.1): uses the exact triplen-heavy harmonic structure,
    wideband noise (0.02-0.2 A), and 8-20 kHz inverter switching noise of `hif-sensor/hif/waveforms.py:_base()`,
    anchored to the switch's OpenDSS pre-fault residual current (clipped to [1, 20] A RMS by the caller).
    """
    _standard_tables()
    a1 = float(base_rms) * np.sqrt(2.0)
    ph = float(rng.uniform(0.0, TWO_PI))
    env = 1.0 + rng.uniform(0.0, 0.04) * np.sin(TWO_PI * rng.uniform(0.1, 2.0) * t + rng.uniform(0.0, TWO_PI))
    i = a1 * env * _sin_harmonic(1, ph, t)
    for h, hi in ((3, 0.6), (5, 0.2), (7, 0.1), (9, 0.08)):
        i += a1 * rng.uniform(0.0, hi) * _sin_harmonic(h, float(rng.uniform(0.0, TWO_PI)), t)
    i += rng.normal(0.0, rng.uniform(0.02, 0.2), t.shape)
    if force_inverter_noise or rng.random() < 0.3:
        i += rng.uniform(0.2, 2.0) * np.sin(TWO_PI * rng.uniform(8e3, 20e3) * t + rng.uniform(0.0, TWO_PI))
    return i, a1, ph


def _arc(
    t: np.ndarray,
    t0: float,
    rng: np.random.Generator,
    s: dict[str, tuple[float, float]],
    arc_duty: float | None = None,
) -> np.ndarray:
    """Emanuel two-diode ground-arc generator (exact parity with hif-sensor/hif/waveforms.py:_arc() when arc_duty=None).

    When `arc_duty` is provided (realistic fusion mode, research/hif-fusion-realistic/PLAN.md §3.2),
    the cycle restrike dropout probability is synchronized with OpenDSS intermittent conduction duty
    `d_cond` via `p_off = clip(1.0 - arc_duty, 0.0, 0.65)` (ASSUMPTION).
    """
    vp, rp = rng.uniform(*s["Vp"]), rng.uniform(*s["R"])
    vn, rn = vp * rng.uniform(1.05, 1.4), rp * rng.uniform(0.85, 1.15)
    if rng.random() < 0.5:
        vp, vn, rp, rn = vn, vp, rn, rp
    sig = rng.uniform(0.03, 0.12)
    if arc_duty is None:
        p_off = rng.uniform(0.0, 0.3)
    else:
        # ASSUMPTION (research/hif-fusion-realistic/PLAN.md §3.2): synchronize cycle restrike
        # dropout probability with OpenDSS intermittent conduction duty cycle d_cond.
        p_off = float(np.clip(1.0 - float(arc_duty), 0.0, 0.65))
    phv = rng.uniform(0.0, TWO_PI)
    v = V_PHASE_PK * np.sin(W * t + phv)
    half = np.floor((W * t + phv) / np.pi).astype(np.int64)
    half -= half.min()
    jit = 1.0 + sig * rng.standard_normal((4, half.max() + 1))          # new arc each half cycle
    VP, VN, RP, RN = vp * jit[0][half], vn * jit[1][half], rp * jit[2][half], rn * jit[3][half]
    i = np.where(v > VP, (v - VP) / RP, 0.0) + np.where(v < -VN, (v + VN) / RN, 0.0)
    cyc = half // 2
    i *= (rng.random(cyc.max() + 1) >= p_off)[cyc]                      # arc fails to restrike
    dt = t - t0
    a0, tb = rng.uniform(0.1, 0.5), rng.uniform(0.02, 0.3)
    env = np.where(dt >= 0, 1.0 - (1.0 - a0) * np.exp(-np.clip(dt, 0.0, None) / tb), 0.0)
    return i * env


def _bursts(rng: np.random.Generator, n: int) -> np.ndarray:
    on, state, k = np.zeros(n, bool), rng.random() < 0.5, 0
    while k < n:
        L = int(rng.integers(6, 31))
        on[k:k + L] = state
        state, k = not state, k + L
    return on


def _disturb(
    t: np.ndarray,
    t1: float,
    rng: np.random.Generator,
    kind: str,
    a1: float,
    ph: float,
) -> np.ndarray | float:
    """Exact parity with hif-sensor/hif/waveforms.py:_disturb()."""
    if kind == "none":
        return 0.0
    dt = t - t1
    on = dt >= 0
    dtp = np.clip(dt, 0.0, None)
    cyc = _STD_CYC if (t is _STD_T and _STD_CYC is not None) else np.floor(W * t / TWO_PI).astype(np.int64)
    nc = int(cyc.max()) + 1
    if kind == "load_step":
        return on * rng.uniform(-0.5, 1.0) * a1 * _sin_harmonic(1, ph + float(rng.uniform(-0.3, 0.3)), t)
    if kind == "cap_switch":
        A, f, tau = rng.uniform(5.0, 40.0), rng.uniform(300.0, 1200.0), rng.uniform(2e-3, 10e-3)
        return on * A * np.exp(-dtp / tau) * np.sin(TWO_PI * f * dtp + rng.uniform(0.0, TWO_PI))
    if kind == "inrush":
        ipk, tau, th = rng.uniform(10.0, 40.0), rng.uniform(0.1, 1.0), np.deg2rad(rng.uniform(60.0, 150.0))
        pulse = np.clip(_sin_harmonic(1, float(rng.uniform(0.0, TWO_PI)), t) - np.cos(th), 0.0, None) / (1.0 - np.cos(th))
        return on * rng.choice([-1.0, 1.0]) * ipk * np.exp(-dtp / tau) * pulse
    if kind == "motor_start":
        k, tau, lag = rng.uniform(2.0, 6.0), rng.uniform(0.1, 0.5), np.deg2rad(rng.uniform(40.0, 80.0))
        return on * (k - 1.0) * a1 * np.exp(-dtp / tau) * _sin_harmonic(1, ph - float(lag), t)
    if kind == "arc_welder":                                            # hard negative: random but symmetric
        aw = rng.uniform(3.0, 20.0) * np.sqrt(2.0)
        amp = np.clip(1.0 + 0.25 * rng.standard_normal(nc), 0.2, None)
        x = np.tanh(4.0 * _sin_harmonic(1, float(rng.uniform(0.0, TWO_PI)), t))
        return on * aw * amp[cyc] * _bursts(rng, nc)[cyc] * x
    if kind == "nonlinear_fluct":                                       # many electronic loads switching
        out: np.ndarray | float = 0.0
        for h, hi in ((3, 0.5), (5, 0.2), (7, 0.1)):
            fac = 1.0 + rng.uniform(0.1, 0.3) * rng.standard_normal(nc)
            out = out + a1 * rng.uniform(0.1, hi) * fac[cyc] * _sin_harmonic(h, float(rng.uniform(0.0, TWO_PI)), t)
        return on * out
    raise ValueError(f"unknown disturbance kind: {kind!r}")


def make_event(
    rng: np.random.Generator,
    is_hif: bool,
    surface: str | None = None,
    disturbance: str | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """One 1-second standalone record (exact parity with hif-sensor/hif/waveforms.py:make_event())."""
    n = N_SIM_SAMPLES
    t = np.arange(n) / FS_SIM
    start = int(rng.integers(12, 41))
    t0 = (WARMUP + start) / F_LINE
    i, a1, ph = _base(t, rng)
    meta: dict[str, Any] = {"is_hif": bool(is_hif), "start_cycle": start, "base_rms": float(a1 / np.sqrt(2.0))}
    if is_hif:
        surface = surface or str(rng.choice(list(SURFACES)))
        arc = _arc(t, t0, rng, SURFACES[surface])
        i = i + arc
        if disturbance is None:
            disturbance = str(rng.choice(DISTURBANCES)) if rng.random() < 0.25 else "none"
        t1 = (WARMUP + int(rng.integers(0, N_CYCLES))) / F_LINE
        tail = arc[-20 * N_CYCLE * OVERSAMPLE:]
        meta["arc_rms"] = float(np.sqrt(np.mean(tail ** 2)))
    else:
        disturbance = disturbance or str(rng.choice(DISTURBANCES))
        t1 = t0
        meta["arc_rms"] = 0.0
    i = i + _disturb(t, t1, rng, disturbance, a1, ph)
    meta["surface"] = surface or "none"
    meta["disturbance"] = disturbance
    amps = codes_to_amps(sense(i, rng))[WARMUP * N_CYCLE:]
    return amps, meta


# ---------------------------------------------------------------------------
# Quantized int8 Tiny MLP: load, save, infer, persistence, fallback training
# ---------------------------------------------------------------------------
@dataclass
class EdgeModel:
    """Frozen Tier-1 int8 Tiny MLP (`16 -> 16 -> 8 -> 1`, 417 params / 504 bytes)."""

    layers: list[dict[str, Any]]
    threshold: float
    pickups: dict[str, float] = field(default_factory=dict)
    n_params: int = 0
    n_bytes: int = 0
    source: str = "unknown"
    sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.n_params or not self.n_bytes:
            self.n_params, self.n_bytes = model_stats(self.layers)


def model_stats(layers: list[dict[str, Any]]) -> tuple[int, int]:
    """Return (param_count, serialized_byte_size) matching hif-sensor/train_kaggle.py."""
    n_params = int(sum(L["Wq"].size + L["b"].size for L in layers))
    n_bytes = int(sum(L["Wq"].size + 4 * L["b"].size + 4 for L in layers))
    return n_params, n_bytes


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def fold_and_quantize(sc: Any, clf: Any) -> list[dict[str, Any]]:
    """Fold StandardScaler into layer 1, then symmetric per-layer int8 weights + float32 biases."""
    Ws = [w.copy() for w in clf.coefs_]
    bs = [b.copy() for b in clf.intercepts_]
    bs[0] = bs[0] - (sc.mean_ / sc.scale_) @ Ws[0]
    Ws[0] = Ws[0] / sc.scale_[:, None]
    layers = []
    for W_mat, b_vec in zip(Ws, bs):
        s = float(np.abs(W_mat).max() / 127.0)
        if s == 0.0:
            s = 1.0
        layers.append({
            "Wq": np.round(W_mat / s).astype(np.int8),
            "scale": s,
            "b": b_vec.astype(np.float32),
        })
    return layers


def predict_q(layers: list[dict[str, Any]], X: np.ndarray) -> np.ndarray:
    """Exact dequantized int8 MLP forward pass (`ReLU` hidden, `sigmoid` output), returning probs in [0, 1]."""
    h = np.asarray(X, dtype=np.float32)
    if h.ndim == 1:
        h = h[None, :]
    for n, L in enumerate(layers):
        w = L["Wq"].astype(np.float32) * np.float32(L["scale"])
        h = h @ w + L["b"].astype(np.float32)
        if n < len(layers) - 1:
            h = np.maximum(h, 0.0)
        else:
            # Clip logits to [-60, 60] to prevent float32 exp overflow warnings while keeping identical outputs.
            z = np.clip(h, -60.0, 60.0)
            h = 1.0 / (1.0 + np.exp(-z))
    return np.clip(h.ravel(), 0.0, 1.0).astype(np.float32)


def alarms(p: np.ndarray, thr: float, persist: int = PERSIST) -> list[int]:
    """Window indices where `p > thr` completes `persist` consecutive windows (parity with train_kaggle.py)."""
    run, out = 0, []
    for k, a in enumerate(np.asarray(p) > thr):
        run = run + 1 if a else 0
        if run == persist:
            out.append(k)
    return out


def persisted_score(
    p: np.ndarray,
    ends: np.ndarray | None = None,
    start_cycle: int | None = None,
    persist: int = PERSIST,
) -> float:
    """Persisted HIF probability over post-event windows (research/hif-fusion/PLAN.md §2.1).

        p_hif = max_{k: ends[k] >= start_cycle} min(p[k - persist + 1], ..., p[k])

    Satisfies `p_hif > thr` if and only if at least `persist` consecutive windows exceed `thr`
    at some post-event window `k` (`ends[k] >= start_cycle`).
    """
    arr = np.asarray(p, dtype=np.float64).ravel()
    n = len(arr)
    if n < persist:
        return 0.0
    # Sliding minimum of length `persist` ending at index k (for k = persist - 1 .. n - 1).
    win_min = np.minimum.reduce([arr[i:n - persist + 1 + i] for i in range(persist)])
    if ends is not None and start_cycle is not None:
        end_arr = np.asarray(ends).ravel()[persist - 1:]
        mask = end_arr >= start_cycle
        if not np.any(mask):
            return 0.0
        val = float(np.max(win_min[mask]))
    else:
        val = float(np.max(win_min))
    return float(np.clip(val, 0.0, 1.0))


def score_waveform(
    amps: np.ndarray,
    model: EdgeModel,
    *,
    start_cycle: int | None = None,
    persist: int = PERSIST,
) -> tuple[float, float]:
    """Run 16-feature extraction + frozen int8 MLP + PERSIST=3 logic on one switch waveform.

    Returns `(p_hif, hif_alarm)` with `p_hif in [0.0, 1.0]` and `hif_alarm in {0.0, 1.0}`.
    """
    X_win, ends = window_features(amps)
    p = predict_q(model.layers, X_win)
    p_hif = persisted_score(p, ends=ends, start_cycle=start_cycle, persist=persist)
    hif_alarm = 1.0 if p_hif > model.threshold else 0.0
    return p_hif, hif_alarm


def save_model_npz(
    path: Path | str,
    layers: list[dict[str, Any]],
    threshold: float,
    pickups: dict[str, float] | None = None,
) -> Path:
    """Save int8 Tiny MLP in the exact `model_int8.npz` format used by `hif-sensor`."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"thr": np.float64(threshold)}
    for n, L in enumerate(layers):
        payload[f"W{n}"] = np.asarray(L["Wq"], dtype=np.int8)
        payload[f"s{n}"] = np.float64(L["scale"])
        payload[f"b{n}"] = np.asarray(L["b"], dtype=np.float32)
    for name, val in (pickups or {}).items():
        payload["pickup_" + name] = np.float64(val)
    np.savez(out, **payload)
    return out


def load_model_npz(path: Path | str, *, source: str | None = None) -> EdgeModel:
    """Load a frozen `model_int8.npz` file and validate int8 layer structure."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Edge HIF model not found: {p}")
    with np.load(p, allow_pickle=False) as z:
        if "thr" not in z.files:
            raise ValueError(f"{p}: missing 'thr' key")
        layers: list[dict[str, Any]] = []
        n = 0
        while f"W{n}" in z.files:
            wq = np.asarray(z[f"W{n}"])
            if wq.dtype != np.int8:
                raise ValueError(f"{p}: layer W{n} has dtype {wq.dtype}, expected int8")
            layers.append({
                "Wq": wq.copy(),
                "scale": float(z[f"s{n}"]),
                "b": np.asarray(z[f"b{n}"], dtype=np.float32).copy(),
            })
            n += 1
        if not layers:
            raise ValueError(f"{p}: no W0/s0/b0 layers found")
        if layers[0]["Wq"].shape[0] != len(FEATURES):
            raise ValueError(f"{p}: expected {len(FEATURES)} input features, got {layers[0]['Wq'].shape[0]}")
        thr = float(z["thr"])
        pickups = {k[len("pickup_"):]: float(z[k]) for k in z.files if k.startswith("pickup_")}
    n_params, n_bytes = model_stats(layers)
    return EdgeModel(
        layers=layers,
        threshold=thr,
        pickups=pickups,
        n_params=n_params,
        n_bytes=n_bytes,
        source=source or str(p),
        sha256=file_sha256(p),
    )


def find_model_npz(explicit_path: Path | str | None = None) -> Path | None:
    """Locate a frozen `model_int8.npz` locally or in `/kaggle/input`."""
    if explicit_path is not None:
        p = Path(explicit_path)
        if not p.is_file():
            raise FileNotFoundError(f"--model-npz not found: {p}")
        return p
    env_p = os.environ.get("SHF_HIF_MODEL_NPZ")
    if env_p and Path(env_p).is_file():
        return Path(env_p)
    local_candidates = [
        config.ROOT / "hif_sensor" / "results" / "model_int8.npz",
        config.MODELS / "hif_edge" / "model_int8.npz",
        config.GENERATED / "model_int8.npz",
        config.GENERATED / "hif_model_int8_seed42.npz",
    ]
    for cand in local_candidates:
        if cand.is_file():
            return cand
    kaggle = Path("/kaggle/input")
    if kaggle.is_dir():
        for hit in sorted(kaggle.rglob("model_int8.npz")):
            if hit.is_file():
                return hit
    return None


def _event_result(e: dict[str, Any], score: np.ndarray, thr: float) -> dict[str, Any]:
    al = [int(e["ends"][k]) for k in alarms(score, thr)]
    s = e["start_cycle"]
    if e["is_hif"]:
        pre = any(a < s for a in al)
        post = [a for a in al if a >= s]
        return {"false_alarm": pre, "detected": bool(post), "delay": (post[0] - s) if post else None}
    return {"false_alarm": bool(al), "detected": False, "delay": None}


def _pick_threshold(evs: list[dict[str, Any]], scores: list[np.ndarray], grid: np.ndarray) -> float:
    def fa(thr: float) -> float:
        return float(np.mean([_event_result(e, s, thr)["false_alarm"] for e, s in zip(evs, scores)]))

    lo, hi = 0, len(grid) - 1
    if fa(float(grid[hi])) > MAX_FALSE_ALARM:
        return float(grid[hi])
    while lo < hi:
        mid = (lo + hi) // 2
        if fa(float(grid[mid])) <= MAX_FALSE_ALARM:
            hi = mid
        else:
            lo = mid + 1
    return float(grid[lo])


def train_fallback_model(
    *,
    seed: int = SEED,
    n_events: int = N_EVENTS,
    save_path: Path | str | None = None,
    verbose: bool = True,
) -> tuple[EdgeModel, dict[str, Any]]:
    """Deterministic fallback training matching `hif-sensor/train_kaggle.py` (standalone waveforms only).

    Used ONLY when the pre-trained Kaggle `model_int8.npz` is unavailable (PLAN.md §3.3).
    Zero OpenDSS data is ever seen during Tier-1 training.
    """
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler

    t0 = time.time()
    rng_sim = np.random.default_rng(seed)
    events = []
    for k in range(n_events):
        amps, meta = make_event(rng_sim, is_hif=(k % 2 == 0))
        X, ends = window_features(amps)
        events.append({"X": X, "ends": ends, "y": window_labels(ends, meta), **meta})
        if verbose and (k + 1) % 500 == 0:
            print(f"  [hif_edge fallback] simulated {k + 1}/{n_events} events ({time.time() - t0:.1f} s)")

    rng_split = np.random.default_rng(seed)
    idx = rng_split.permutation(len(events))
    n1, n2 = int(0.6 * len(events)), int(0.8 * len(events))
    tr = [events[i] for i in idx[:n1]]
    va = [events[i] for i in idx[n1:n2]]
    te = [events[i] for i in idx[n2:]]

    def _stack(evs: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
        X_all = np.concatenate([e["X"] for e in evs])
        y_all = np.concatenate([e["y"] for e in evs])
        keep = y_all >= 0
        return X_all[keep], y_all[keep]

    X_tr, y_tr = _stack(tr)
    sc = StandardScaler().fit(X_tr)
    clf = MLPClassifier(
        hidden_layer_sizes=HIDDEN,
        alpha=1e-3,
        max_iter=400,
        early_stopping=True,
        n_iter_no_change=15,
        random_state=seed,
    ).fit(sc.transform(X_tr), y_tr)
    layers = fold_and_quantize(sc, clf)
    grid = np.linspace(0.30, 0.999, 300)
    thr = _pick_threshold(va, [predict_q(layers, e["X"]) for e in va], grid)

    te_scores = [predict_q(layers, e["X"]) for e in te]
    res = [_event_result(e, s, thr) for e, s in zip(te, te_scores)]
    hif_res = [r for e, r in zip(te, res) if e["is_hif"]]
    nor_res = [r for e, r in zip(te, res) if not e["is_hif"]]

    out_path = Path(save_path) if save_path is not None else (config.GENERATED / f"hif_model_int8_seed{seed}.npz")
    save_model_npz(out_path, layers, thr)
    model = load_model_npz(out_path, source="retrained_seed42_fallback" if seed == SEED else f"retrained_seed{seed}_fallback")
    summary = {
        "model_source": model.source,
        "path": str(out_path),
        "sha256": model.sha256,
        "seed": seed,
        "n_events": n_events,
        "params": model.n_params,
        "bytes": model.n_bytes,
        "threshold": model.threshold,
        "standalone_test_detection_rate": float(np.mean([r["detected"] for r in hif_res])) if hif_res else None,
        "standalone_test_false_alarm_rate_normal": float(np.mean([r["false_alarm"] for r in nor_res])) if nor_res else None,
        "runtime_s": round(time.time() - t0, 1),
    }
    return model, summary


def load_or_train_model(
    model_npz: Path | str | None = None,
    *,
    fallback_path: Path | str | None = None,
    allow_retrain: bool = True,
    n_events: int = N_EVENTS,
    verbose: bool = True,
) -> tuple[EdgeModel, dict[str, Any]]:
    """Load frozen `model_int8.npz`, or fall back to deterministic `seed=42` standalone training."""
    found = find_model_npz(model_npz)
    if found is not None:
        m = load_model_npz(found, source=str(found))
        return m, {
            "model_source": m.source,
            "path": str(found),
            "sha256": m.sha256,
            "params": m.n_params,
            "bytes": m.n_bytes,
            "threshold": m.threshold,
        }
    if not allow_retrain:
        raise FileNotFoundError("model_int8.npz not found and allow_retrain=False")
    return train_fallback_model(seed=SEED, n_events=n_events, save_path=fallback_path, verbose=verbose)
