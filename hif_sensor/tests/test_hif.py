"""Automated verification suite for hif-sensor (physics, features, int8 C parity, results, provenance)."""
import json
import re
from pathlib import Path

import numpy as np
import pytest

from hif.features import FEATURES, K, window_features, window_labels
from hif.frontend import (
    ADC_BITS, F_LINE, F_LINE_VN, GAIN_V_PER_A, N_CYCLE, STAGES, STAGES_50HZ_RETUNED,
    adc_rate_hz, codes_to_amps, cutoff_hz, frequency_response_summary, sense, sim_rate_hz,
)
from hif.provenance import verify_manifest
from hif.waveforms import DISTURBANCES, N_CYCLES, SURFACES, make_event

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- 1. Front-end physics (50 Hz & 60 Hz)
def test_frontend_60hz_matches_ltspice():
    lt = json.loads((ROOT / "circuit" / "ltspice_results.json").read_text(encoding="utf-8"))
    s60 = frequency_response_summary(F_LINE, STAGES)
    assert s60["adc_sample_rate_Hz"] == 15360.0
    assert s60["nyquist_Hz"] == 7680.0
    assert abs(s60["f_minus3dB_Hz"] - lt["ac"]["f_minus3dB_Hz"]) < 5.0
    assert abs(s60["attenuation_at_nyquist_dB"] - lt["ac"]["attenuation_at_7680Hz_dB"]) < 1.5
    assert abs(s60["phase_lag_at_f1_deg"] - lt["ac"]["phase_lag_at_60Hz_deg"]) < 0.2
    assert abs(s60["gain_V_per_A_at_f1"] - GAIN_V_PER_A) < 1e-4


def test_frontend_50hz_vietnam_physics():
    s50 = frequency_response_summary(F_LINE_VN, STAGES)
    s50r = frequency_response_summary(F_LINE_VN, STAGES_50HZ_RETUNED)
    assert adc_rate_hz(50.0) == 12800.0
    assert sim_rate_hz(50.0) == 102400.0
    assert s50["nyquist_Hz"] == 6400.0
    assert s50["window_8cycles_ms"] == 160.0
    assert s50["attenuation_at_nyquist_dB"] > 38.0
    assert s50["harmonics_within_3dB"] >= 40
    # Retuned 50 Hz BOM restores >= 45 dB Nyquist anti-alias margin at 6.4 kHz
    assert s50r["attenuation_at_nyquist_dB"] > 45.0
    assert s50r["f_minus3dB_Hz"] < s50["f_minus3dB_Hz"]


@pytest.mark.parametrize("f_line", [60.0, 50.0])
def test_adc_roundtrip_and_clamping(f_line):
    rng = np.random.default_rng(123)
    fs = sim_rate_hz(f_line)
    t = np.arange(10 * N_CYCLE * 8) / fs
    i_in = 15.0 * np.sqrt(2) * np.sin(2 * np.pi * f_line * t)
    codes = sense(i_in, rng, f_line=f_line)
    assert codes.dtype == np.int16
    assert codes.min() >= 0 and codes.max() <= (2 ** ADC_BITS - 1)
    amps = codes_to_amps(codes)[4 * N_CYCLE:]
    rms_out = float(np.sqrt(np.mean(amps ** 2)))
    assert abs(rms_out - 15.0) < 0.5


# ---------------------------------------------------------------- 2. Waveforms & 16 features
@pytest.mark.parametrize("f_line", [60.0, 50.0])
def test_waveforms_and_features_all_types(f_line):
    rng = np.random.default_rng(7)
    for surf in SURFACES:
        amps, meta = make_event(rng, is_hif=True, surface=surf, disturbance="none", f_line=f_line)
        assert len(amps) == N_CYCLES * N_CYCLE
        assert np.isfinite(amps).all()
        X, ends = window_features(amps)
        y = window_labels(ends, meta)
        assert X.shape == (N_CYCLES - K + 1, len(FEATURES))
        assert np.isfinite(X).all()
        assert set(np.unique(y)).issubset({-1, 0, 1})
        assert (y == 1).sum() > 0

    for dist in DISTURBANCES:
        amps, meta = make_event(rng, is_hif=False, disturbance=dist, f_line=f_line)
        X, ends = window_features(amps)
        y = window_labels(ends, meta)
        assert np.isfinite(X).all()
        assert (y == 0).all()


# ---------------------------------------------------------------- 3. C header <-> NPZ <-> test_vectors bit parity
def _parse_c_header(path: Path):
    txt = path.read_text(encoding="utf-8")
    thr = float(re.search(r"HIF_THRESHOLD\s*=\s*([0-9eE.+\-]+)f", txt).group(1))
    layers = []
    for n in (1, 2, 3):
        out_n = int(re.search(rf"#define\s+HIF_L{n}_OUT\s+(\d+)", txt).group(1))
        in_n = int(re.search(rf"#define\s+HIF_L{n}_IN\s+(\d+)", txt).group(1))
        w_str = re.search(rf"HIF_W{n}\[\d+\]\[\d+\]\s*=\s*\{{(.*?)\}};", txt, re.S).group(1)
        s_val = float(re.search(rf"HIF_S{n}\s*=\s*([0-9eE.+\-]+)f", txt).group(1))
        b_str = re.search(rf"HIF_B{n}\[\d+\]\s*=\s*\{{([^}}]+)\}}", txt).group(1)
        W = np.array([int(v.strip(" \t\r\n{}")) for v in w_str.split(",")], dtype=np.int8).reshape(out_n, in_n)
        b = np.array([float(v.strip().rstrip("f")) for v in b_str.split(",")], dtype=np.float32)
        layers.append((W, np.float32(s_val), b))
    return thr, layers


def _c_fp32_predict(layers, x_list):
    """Exact float32 scalar math mirroring dense() in firmware/hif_infer.c."""
    h = np.asarray(x_list, dtype=np.float32)
    for idx, (W, scale, b) in enumerate(layers):
        y = np.zeros(W.shape[0], dtype=np.float32)
        for o in range(W.shape[0]):
            acc = np.float32(0.0)
            for i in range(W.shape[1]):
                acc = np.float32(acc + np.float32(W[o, i]) * h[i])
            acc = np.float32(acc * scale + b[o])
            y[o] = np.float32(acc if (idx == len(layers) - 1 or acc > 0.0) else 0.0)
        h = y
    return float(1.0 / (1.0 + np.exp(-float(h[0]))))


def test_c_header_matches_npz_and_test_vectors():
    hdr = ROOT / "firmware" / "hif_model.h"
    npz = ROOT / "results" / "model_int8.npz"
    vecs = json.loads((ROOT / "results" / "test_vectors.json").read_text(encoding="utf-8"))
    thr, c_layers = _parse_c_header(hdr)
    z = np.load(npz)
    assert abs(thr - float(z["thr"])) < 1e-6

    total_params = 0
    total_bytes = 0
    for idx, (W_c, s_c, b_c) in enumerate(c_layers):
        W_py = z[f"W{idx}"].T
        assert np.array_equal(W_c, W_py), f"Layer {idx+1} int8 weight mismatch"
        assert abs(float(s_c) - float(z[f"s{idx}"])) < 1e-7
        assert np.allclose(b_c, z[f"b{idx}"], atol=1e-6)
        total_params += W_c.size + b_c.size
        total_bytes += W_c.size + 4 * b_c.size + 4
    assert total_params == 417
    assert total_bytes == 504

    max_err = 0.0
    for v in vecs:
        p_c = _c_fp32_predict(c_layers, v["features"])
        err = abs(p_c - v["prob"])
        max_err = max(max_err, err)
        assert (p_c > thr) == (v["prob"] > thr)
    assert max_err < 1e-5


# ---------------------------------------------------------------- 4. Real results & provenance
def test_phase0_and_phase1_results_integrity():
    m = json.loads((ROOT / "results" / "metrics.json").read_text(encoding="utf-8"))
    v = json.loads((ROOT / "results" / "real_vehif.json").read_text(encoding="utf-8"))
    assert m["model"]["params"] == 417
    assert m["model"]["bytes_int8_weights_float_bias"] == 504
    assert 0.90 <= m["test_ml_int8"]["detection_rate"] <= 1.0
    assert m["test_ml_int8"]["false_alarm_rate_normal"] <= 0.03
    assert v["real_faults"]["recordings"] == 250
    assert v["background_recordings"]["recordings"] == 53
    assert v["background_recordings"]["alarm_rate"] == 0.0


def test_phase15_results_when_present():
    p15_path = ROOT / "results" / "phase15_vehif.json"
    c_path = ROOT / "results" / "c_firmware_verify.json"
    if not p15_path.exists():
        pytest.skip("Phase 1.5 not pulled from Kaggle yet")
    p15 = json.loads(p15_path.read_text(encoding="utf-8"))
    assert "freq_50hz_vs_60hz" in p15
    assert "feature_ablation" in p15
    assert "few_shot_adaptation" in p15
    if c_path.exists():
        cv = json.loads(c_path.read_text(encoding="utf-8"))
        assert cv["phase0_official_6_vectors"]["parity_pass"] is True
        assert cv["phase0_official_6_vectors"]["max_abs_prob_error"] < 1e-5


def test_sha256_provenance_manifest():
    manifest_path = ROOT / "results" / "provenance" / "manifest.json"
    if not manifest_path.exists():
        pytest.skip("Provenance manifest not recorded yet")
    res = verify_manifest(ROOT, manifest_path)
    assert res["ok"], f"Provenance mismatch: {res}"
    assert res["checked"] >= 7


def test_c99_dsp_firmware_constants_match_python():
    dsp_h = (ROOT / "firmware" / "hif_dsp.h").read_text(encoding="utf-8")
    dsp_c = (ROOT / "firmware" / "hif_dsp.c").read_text(encoding="utf-8")
    assert f"#define HIF_N_CYCLE {N_CYCLE}" in dsp_h
    assert f"#define HIF_K_WINDOW {K}" in dsp_h
    assert f"#define HIF_N_FEATURES {len(FEATURES)}" in dsp_h
    for fn in ("hif_adc_to_amps", "hif_fft_radix2", "hif_extract_features"):
        assert fn in dsp_h and fn in dsp_c
