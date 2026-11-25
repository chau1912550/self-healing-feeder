"""Analog front end + ESP32-S3 ADC model. Component values match circuit/front_end_ac.cir.

Supports both 60 Hz (US 12.47 kV, FS_ADC = 15,360 Hz) and 50 Hz (Vietnam / Australia 22 kV,
FS_ADC = 12,800 Hz) grid operation on the exact same physical 4th-order Butterworth Sallen-Key
anti-aliasing hardware (fc ≈ 2,045 Hz), as well as an optional resistor-retuned 50 Hz variant.
"""
import numpy as np
from scipy import signal

F_LINE = 60.0
F_LINE_VN = 50.0                    # Vietnam / Australia / IEC 50 Hz grid frequency
N_CYCLE = 256                       # ADC samples per power cycle (same for 50 Hz and 60 Hz)
FS_ADC = F_LINE * N_CYCLE           # 15,360 Hz at 60 Hz (12,800 Hz at 50 Hz)
OVERSAMPLE = 8
FS_SIM = FS_ADC * OVERSAMPLE        # 122,880 Hz at 60 Hz (102,400 Hz at 50 Hz)
CT_RATIO = 2000.0                   # SCT-013-000 clamp CT (100 A : 50 mA)
R_BURDEN = 33.0
GAIN_V_PER_A = R_BURDEN / CT_RATIO  # 16.5 mV per primary amp
VREF, VDD = 1.65, 3.3
ADC_BITS = 12
ADC_FS_V = 3.3
ADC_NOISE_LSB = 1.5                 # assumed ADC noise; ESP32 nonlinearity is not modeled
# (R, C_feedback, C_ground) of each unity-gain Sallen-Key stage (matches circuit/front_end_ac.cir)
STAGES = ((8.66e3, 10e-9, 8.2e-9), (4.42e3, 47e-9, 6.8e-9))
# Optional 50 Hz resistor-retuned BOM (E96 values scaling R by 60/50 = 1.2x; same PCB & capacitors)
STAGES_50HZ_RETUNED = ((10.5e3, 10e-9, 8.2e-9), (5.36e3, 47e-9, 6.8e-9))


def adc_rate_hz(f_line=F_LINE):
    """ADC sampling rate (Hz) to keep exactly N_CYCLE=256 samples per power cycle."""
    return float(f_line) * N_CYCLE


def sim_rate_hz(f_line=F_LINE):
    """Oversampled analog simulation rate (Hz) for a given line frequency."""
    return adc_rate_hz(f_line) * OVERSAMPLE


def analog_den(stages=STAGES):
    """Denominator of H(s) = 1 / prod(s^2 R^2 C1 C2 + 2 s R C2 + 1)."""
    a = np.array([1.0])
    for r, c_fb, c_gnd in stages:
        a = np.polymul(a, [r * r * c_fb * c_gnd, 2 * r * c_gnd, 1.0])
    return a


def cutoff_hz(stages=STAGES):
    w = 2 * np.pi * np.logspace(2, 4.5, 20000)
    _, h = signal.freqs([1.0], analog_den(stages), worN=w)
    return float(w[np.argmax(np.abs(h) < 1 / np.sqrt(2))] / (2 * np.pi))


def frequency_response_summary(f_line=F_LINE, stages=STAGES):
    """Exact analytical response of the analog anti-alias front end at a given grid frequency."""
    f_line = float(f_line)
    fs_adc = adc_rate_hz(f_line)
    f_nyq = fs_adc / 2.0
    den = analog_den(stages)

    def eval_f(freq_hz):
        _, h = signal.freqs([1.0], den, worN=[2 * np.pi * float(freq_hz)])
        return complex(h[0])

    h_f1 = eval_f(f_line)
    h_f3 = eval_f(3.0 * f_line)
    h_1k = eval_f(1000.0)
    h_nyq = eval_f(f_nyq)
    h_fs = eval_f(fs_adc)
    fc = cutoff_hz(stages)
    return {
        "f_line_Hz": f_line,
        "samples_per_cycle": N_CYCLE,
        "adc_sample_rate_Hz": fs_adc,
        "nyquist_Hz": f_nyq,
        "window_8cycles_ms": round(8.0 / f_line * 1000.0, 2),
        "f_minus3dB_Hz": round(fc, 2),
        "harmonics_within_3dB": int(np.floor(fc / f_line)),
        "gain_V_per_A_at_f1": round(abs(h_f1) * GAIN_V_PER_A, 7),
        "gain_dB_at_3rd_vs_f1": round(float(20 * np.log10(abs(h_f3) / abs(h_f1))), 4),
        "gain_dB_at_1kHz_vs_f1": round(float(20 * np.log10(abs(h_1k) / abs(h_f1))), 4),
        "phase_lag_at_f1_deg": round(float(-np.degrees(np.angle(h_f1))), 3),
        "attenuation_at_nyquist_dB": round(float(-20 * np.log10(abs(h_nyq))), 2),
        "attenuation_at_fs_dB": round(float(-20 * np.log10(abs(h_fs))), 2),
    }


_SOS_CACHE = {}


def _sos_for_rate(fs_sim, stages=STAGES):
    key = (float(fs_sim), stages)
    if key not in _SOS_CACHE:
        a = analog_den(stages)
        z, p, k = signal.bilinear_zpk([], np.roots(a), 1.0 / a[0], float(fs_sim))
        _SOS_CACHE[key] = signal.zpk2sos(z, p, k)
    return _SOS_CACHE[key]


def _sos():
    return _sos_for_rate(FS_SIM, STAGES)


def sense(i_primary, rng, f_line=F_LINE, stages=STAGES):
    """Primary current (A) at sim_rate_hz(f_line) -> 12-bit ADC codes at adc_rate_hz(f_line)."""
    sos = _sos_for_rate(sim_rate_hz(f_line), stages)
    v = signal.sosfilt(sos, i_primary * GAIN_V_PER_A)[::OVERSAMPLE] + VREF
    v = np.clip(v, -0.3, VDD + 0.3)                      # Schottky clamps
    lsb = ADC_FS_V / (2 ** ADC_BITS - 1)
    code = np.round(v / lsb + rng.normal(0.0, ADC_NOISE_LSB, v.shape))
    return np.clip(code, 0, 2 ** ADC_BITS - 1).astype(np.int16)


def codes_to_amps(code):
    lsb = ADC_FS_V / (2 ** ADC_BITS - 1)
    return (code.astype(np.float64) * lsb - VREF) / GAIN_V_PER_A
