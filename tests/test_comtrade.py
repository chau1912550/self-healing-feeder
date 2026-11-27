"""Unit and integration tests for IEEE C37.111 COMTRADE I/O and feature conversion.

Covers:
  - IEEE C37.111-1999 & 2013 reading/writing (ASCII, BINARY, BINARY32, FLOAT32, .cff)
  - Scaling `a * x + b`, primary/secondary CT/PT ratios (`P`/`S`), and SI unit scaling
  - 50/60 Hz pre- and post-fault fundamental phasor extraction (including skew, multi-rate,
    non-integer samples/cycle, and onset detection)
  - Exact feature parity with Tier-2 (`shf.model` / `shf.faults`, 15 features/device),
    Transfer (`shf.transfer`, 21 features/node), Active-Grid (`shf.active_grid`, 26 features/node),
    and Tier-1 HIF bridge (`shf.hif_edge`, 16 window features)
  - Missing-device and missing-channel `NaN` handling across all three feature schemas
  - Bundled public open-source & simulation round-trip samples in `data/comtrade_samples/`
  - Schema, provenance, and published-copy checks for `results/comtrade/summary.json`

Run: .venv/Scripts/python -m pytest -v tests/test_comtrade.py
"""
from __future__ import annotations

import cmath
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from shf import active_grid, comtrade, config, faults, feeder, hif_edge, model, transfer

ROOT = config.ROOT
SAMPLES_DIR = ROOT / "data" / "comtrade_samples"
PUBLIC_DIR = SAMPLES_DIR / "public"
SYNTH_DIR = SAMPLES_DIR / "synthetic_roundtrip"
SUMMARY_PATH = config.RESULTS / "comtrade" / "summary.json"
PUB_SUMMARY_PATH = ROOT / "docs" / "data" / "comtrade_summary.json"
PROV_PATH = config.RESULTS / "provenance" / "comtrade_verify.json"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_synth_phasor_pair(
    *,
    i_pre: tuple[complex, complex, complex],
    i_post: tuple[complex, complex, complex],
    v_pre: tuple[complex, complex, complex],
    v_post: tuple[complex, complex, complex],
) -> tuple[dict, dict]:
    def _pack(iv, vv):
        i_arr = np.array(iv, dtype=np.complex128)
        v_arr = np.array(vv, dtype=np.complex128)
        ia, ib, ic = i_arr
        return {
            "i": i_arr,
            "v": v_arr,
            "i0": (ia + ib + ic) / 3.0,
            "i2": (ia + comtrade.A_OP * comtrade.A_OP * ib + comtrade.A_OP * ic) / 3.0,
        }

    return _pack(i_pre, v_pre), _pack(i_post, v_post)


def _build_demo_grid_and_snapshots() -> tuple[transfer.Grid, dict[str, dict], dict[str, dict]]:
    """Deterministic 4-node radial Grid and synthetic pre/post phasors (no OpenDSS needed)."""
    devs = ["D1", "D2", "D3", "D4"]
    parent = {"D1": None, "D2": "D1", "D3": "D1", "D4": "D2"}
    members = {d: [f"b_{d}"] for d in devs}
    kw = {"D1": 400.0, "D2": 300.0, "D3": 200.0, "D4": 100.0}
    grid = transfer.Grid("demo", devs, {d: d for d in devs}, parent, members, kw)

    ang_b = -2.0 * math.pi / 3.0
    ang_c = 2.0 * math.pi / 3.0
    pre: dict[str, dict] = {}
    post: dict[str, dict] = {}
    specs = {
        # (I_pre_mag, I_post_a_mag, V_post_a_mag, reverse_post_power)
        "D1": (300.0, 1200.0, 0.72, False),
        "D2": (180.0, 950.0, 0.55, False),
        "D3": (110.0, 115.0, 0.91, True),   # DER reverse current flow on healthy branch
        "D4": (60.0, 40.0, 0.45, True),
    }
    for d, (i0_mag, ia_post_mag, va_post_mag, rev) in specs.items():
        i_pre = (
            cmath.rect(i0_mag, -0.3),
            cmath.rect(i0_mag * 0.95, ang_b - 0.3),
            cmath.rect(i0_mag * 1.05, ang_c - 0.3),
        )
        v_pre = (
            cmath.rect(1.02, 0.0),
            cmath.rect(1.01, ang_b),
            cmath.rect(1.00, ang_c),
        )
        phase_shift = math.pi - 0.2 if rev else -1.1
        i_post = (
            cmath.rect(ia_post_mag, phase_shift),
            cmath.rect(i0_mag * 0.98, ang_b + (math.pi - 0.2 if rev else -0.35)),
            cmath.rect(i0_mag * 1.02, ang_c + (math.pi - 0.2 if rev else -0.35)),
        )
        v_post = (
            cmath.rect(va_post_mag, -0.15),
            cmath.rect(0.99, ang_b - 0.05),
            cmath.rect(0.98, ang_c - 0.05),
        )
        pre[d], post[d] = _make_synth_phasor_pair(
            i_pre=i_pre, i_post=i_post, v_pre=v_pre, v_post=v_post
        )
    return grid, pre, post


# ---------------------------------------------------------------------------
# 1. IEEE C37.111-1999 & 2013 read/write: ASCII, BINARY, BINARY32, FLOAT32, .cff
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "fmt,rev_year,atol",
    [
        ("ASCII", 1999, 1e-2),
        ("ASCII", 2013, 1e-2),
        ("BINARY", 1999, 0.25),
        ("BINARY", 2013, 0.25),
        ("BINARY32", 2013, 1e-4),
        ("FLOAT32", 2013, 1e-3),
    ],
)
def test_comtrade_roundtrip_formats_and_revisions(tmp_path: Path, fmt: str, rev_year: int, atol: float):
    fs = 3840.0
    freq = 60.0
    n = 320
    t = np.arange(n, dtype=np.float64) / fs
    analog = {
        "Ia": 400.0 * np.sqrt(2.0) * np.cos(2.0 * math.pi * freq * t - 0.4),
        "Ib": 380.0 * np.sqrt(2.0) * np.cos(2.0 * math.pi * freq * t - 2.0 * math.pi / 3.0),
        "Va": 2401.777 * np.sqrt(2.0) * np.cos(2.0 * math.pi * freq * t),
    }
    # 18 digital channels to test multi-word (2 x 16-bit) packing in BINARY/BINARY32/FLOAT32
    digital = np.zeros((18, n), dtype=np.uint8)
    digital[0, 120:] = 1
    digital[15, 160:220] = 1
    digital[17, 200:] = 1

    cfg_p, dat_p = comtrade.write_comtrade(
        tmp_path / f"rt_{fmt}_{rev_year}.cfg",
        analog=analog,
        digital=digital,
        fs=fs,
        freq=freq,
        fmt=fmt,
        rev_year=rev_year,
        station="TEST_STN",
        rec_dev_id="REL_01",
        trigger_offset_s=120.0 / fs,
    )
    assert cfg_p.is_file() and dat_p.is_file()

    rec = comtrade.read_comtrade(cfg_p, side="primary")
    assert rec.rev_year == rev_year
    assert rec.data_format == fmt
    assert rec.station == "TEST_STN"
    assert rec.rec_dev_id == "REL_01"
    assert rec.frequency == pytest.approx(freq)
    assert rec.n_samples == n
    assert rec.n_analog == 3
    assert rec.n_digital == 18
    assert rec.trigger_offset_s == pytest.approx(120.0 / fs, abs=1e-6)
    np.testing.assert_allclose(rec.time, t, atol=1e-9)
    np.testing.assert_allclose(rec.get_analog("Ia"), analog["Ia"], atol=atol)
    np.testing.assert_allclose(rec.get_analog("Ib"), analog["Ib"], atol=atol)
    np.testing.assert_allclose(rec.get_analog("Va"), analog["Va"], atol=atol)
    np.testing.assert_array_equal(rec.digital, digital)


def test_comtrade_cff_single_file_reader(tmp_path: Path):
    """Single-file IEEE C37.111-2013 .cff combines CFG and DAT sections."""
    fs = 1200.0
    t = np.arange(80, dtype=np.float64) / fs
    ia = 100.0 * np.sqrt(2.0) * np.sin(2.0 * math.pi * 60.0 * t)
    cfg_p, dat_p = comtrade.write_comtrade(
        tmp_path / "base.cfg",
        analog={"IA": ia},
        fs=fs,
        freq=60.0,
        fmt="BINARY",
        rev_year=2013,
    )
    cff_p = tmp_path / "combined.cff"
    payload = (
        b"--- file type: CFG ---\r\n"
        + cfg_p.read_bytes()
        + b"--- file type: DAT BINARY ---\r\n"
        + dat_p.read_bytes()
    )
    cff_p.write_bytes(payload)

    rec = comtrade.read_comtrade(cff_p)
    assert rec.rev_year == 2013
    assert rec.data_format == "BINARY"
    assert rec.n_samples == 80
    np.testing.assert_allclose(rec.get_analog("IA"), ia, atol=0.05)


def test_comtrade_nrates_zero_and_multirate_time_axis(tmp_path: Path):
    """Variable timestamps (`nrates=0`) and multi-rate segments reconstruct exact time axes."""
    # 1) Multi-rate: 10 samples at 4000 Hz, then 10 samples at 1000 Hz
    cfg_multi = "\r\n".join([
        "MULTI_STN,DEV_M,1999",
        "1,1A,0D",
        "1,IA,A,,A,1,0,0,-32767,32767,1,1,P",
        "50",
        "2",
        "4000,10",
        "1000,20",
        "01/01/2026,00:00:00.000000",
        "01/01/2026,00:00:00.002000",
        "ASCII",
        "1",
    ]) + "\r\n"
    dat_multi = "\r\n".join(f"{i + 1},0,{i * 10}" for i in range(20)) + "\r\n"
    (tmp_path / "multi.cfg").write_text(cfg_multi, encoding="utf-8")
    (tmp_path / "multi.dat").write_text(dat_multi, encoding="utf-8")

    rec_m = comtrade.read_comtrade(tmp_path / "multi.cfg")
    dt1 = np.diff(rec_m.time[:10])
    dt2 = np.diff(rec_m.time[9:])
    np.testing.assert_allclose(dt1, 1.0 / 4000.0, rtol=1e-9)
    np.testing.assert_allclose(dt2, 1.0 / 1000.0, rtol=1e-9)

    # 2) nrates=0 with timemult=10 (each raw timestamp tick = 10 us)
    cfg_var = "\r\n".join([
        "VAR_STN,DEV_V,2013",
        "1,1A,0D",
        "1,IA,A,,A,0.5,2.0,0,-32767,32767,1,1,P",
        "60",
        "0",
        "0,4",
        "01/01/2026,00:00:00.000000",
        "01/01/2026,00:00:00.001000",
        "ASCII",
        "10",
        "0,0",
        "0,0",
    ]) + "\r\n"
    dat_var = "\r\n".join([
        "1,100,10",
        "2,200,20",
        "3,350,30",
        "4,600,",   # empty ASCII value -> NaN
    ]) + "\r\n"
    (tmp_path / "var.cfg").write_text(cfg_var, encoding="utf-8")
    (tmp_path / "var.dat").write_text(dat_var, encoding="utf-8")

    rec_v = comtrade.read_comtrade(tmp_path / "var.cfg")
    expected_t = np.array([0.0, 1000e-6, 2500e-6, 5000e-6])
    np.testing.assert_allclose(rec_v.time, expected_t, atol=1e-12)
    np.testing.assert_allclose(rec_v.analog[0, :3], [7.0, 12.0, 17.0], atol=1e-12)
    assert np.isnan(rec_v.analog[0, 3])


# ---------------------------------------------------------------------------
# 2. Scaling: a * x + b, P/S CT/PT ratios, and SI unit multipliers
# ---------------------------------------------------------------------------
def test_scaling_ax_plus_b_ps_and_units(tmp_path: Path):
    """Verify exact `(a * x + b) * ratio_factor(side)` for P/S and kA/kV SI scaling."""
    cfg_text = "\r\n".join([
        "SCALE_STN,REL_S,2013",
        "4,4A,0D",
        # ch1: secondary current, CT 1000:5 -> factor 200 when reading primary
        "1,IA,A,,A,0.01,-0.5,0,-32767,32767,1000,5,S",
        # ch2: primary current in kA -> side='primary' gives kA, si=True gives A (*1000)
        "2,IB,B,,kA,0.002,0.1,0,-32767,32767,1000,5,P",
        # ch3: secondary voltage, PT 13800:115 -> factor 120 when reading primary
        "3,VA,A,,V,0.1,1.0,0,-32767,32767,13800,115,S",
        # ch4: primary voltage in kV
        "4,VB,B,,kV,0.05,0.0,0,-32767,32767,13800,115,P",
        "60",
        "1",
        "1200,3",
        "01/01/2026,00:00:00.000000",
        "01/01/2026,00:00:00.000000",
        "ASCII",
        "1",
        "0,0",
        "0,0",
    ]) + "\r\n"
    dat_text = "\r\n".join([
        "1,0,100,500,100,20",
        "2,833,250,1000,200,40",
        "3,1667,-50,0,-100,-20",
    ]) + "\r\n"
    cfg_p = tmp_path / "scale.cfg"
    cfg_p.write_text(cfg_text, encoding="utf-8")
    (tmp_path / "scale.dat").write_text(dat_text, encoding="utf-8")

    rec_p = comtrade.read_comtrade(cfg_p, side="primary")
    rec_s = comtrade.read_comtrade(cfg_p, side="secondary")
    rec_r = comtrade.read_comtrade(cfg_p, side="raw")

    # ch1 (PS='S', a=0.01, b=-0.5, CT=1000/5=200): raw = [0.5, 2.0, -1.0] A_sec
    raw1 = np.array([0.5, 2.0, -1.0])
    np.testing.assert_allclose(rec_r.get_analog("IA"), raw1, rtol=1e-12)
    np.testing.assert_allclose(rec_s.get_analog("IA"), raw1, rtol=1e-12)
    np.testing.assert_allclose(rec_p.get_analog("IA"), raw1 * 200.0, rtol=1e-12)

    # ch2 (PS='P', a=0.002, b=0.1, unit='kA'): primary = [1.1, 2.1, 0.1] kA
    prim2_ka = np.array([1.1, 2.1, 0.1])
    np.testing.assert_allclose(rec_p.get_analog("IB"), prim2_ka, rtol=1e-12)
    np.testing.assert_allclose(rec_p.get_analog("IB", si=True), prim2_ka * 1000.0, rtol=1e-12)
    np.testing.assert_allclose(rec_s.get_analog("IB"), prim2_ka * (5.0 / 1000.0), rtol=1e-12)

    # ch3 (PS='S', a=0.1, b=1.0, PT=13800/115=120): raw = [11.0, 21.0, -9.0] V_sec
    raw3 = np.array([11.0, 21.0, -9.0])
    np.testing.assert_allclose(rec_p.get_analog("VA"), raw3 * 120.0, rtol=1e-12)
    np.testing.assert_allclose(rec_s.get_analog("VA"), raw3, rtol=1e-12)

    # ch4 (PS='P', unit='kV'): primary = [1.0, 2.0, -1.0] kV
    prim4_kv = np.array([1.0, 2.0, -1.0])
    np.testing.assert_allclose(rec_p.get_analog("VB", si=True), prim4_kv * 1000.0, rtol=1e-12)


def test_write_comtrade_ps_secondary_roundtrip_ct_pt(tmp_path: Path):
    """Writing primary waveforms with `ps='S'` and CT/PT ratios recovers exact primary & secondary."""
    fs = 3840.0
    t = np.arange(256, dtype=np.float64) / fs
    ia_prim = 800.0 * np.sqrt(2.0) * np.cos(2.0 * math.pi * 60.0 * t)
    va_prim = 2401.777 * np.sqrt(2.0) * np.cos(2.0 * math.pi * 60.0 * t)
    ct = (1000.0, 1.0)
    pt = (2401.777, 120.0)

    cfg_p, _ = comtrade.write_comtrade(
        tmp_path / "sec_rt.cfg",
        analog={"Ia": ia_prim, "Va": va_prim},
        fs=fs,
        freq=60.0,
        fmt="BINARY",
        rev_year=2013,
        ct_ratio=ct,
        pt_ratio=pt,
        ps="S",
    )
    rec_p = comtrade.read_comtrade(cfg_p, side="primary")
    rec_s = comtrade.read_comtrade(cfg_p, side="secondary")

    assert rec_p.analog_channels[0].ps == "S"
    assert rec_p.analog_channels[0].primary == pytest.approx(1000.0)
    assert rec_p.analog_channels[0].secondary == pytest.approx(1.0)
    np.testing.assert_allclose(rec_p.get_analog("Ia"), ia_prim, atol=0.1)
    np.testing.assert_allclose(rec_s.get_analog("Ia"), ia_prim / 1000.0, atol=1e-4)
    np.testing.assert_allclose(rec_p.get_analog("Va"), va_prim, atol=0.25)
    np.testing.assert_allclose(rec_s.get_analog("Va"), va_prim * (120.0 / 2401.777), atol=0.02)


# ---------------------------------------------------------------------------
# 3. 50 Hz & 60 Hz pre- and post-fault phasor extraction + channel mapping
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("freq,fs", [(50.0, 3200.0), (60.0, 3840.0), (50.0, 2345.0), (60.0, 2500.0)])
def test_phasor_extraction_50hz_and_60hz_pre_post(tmp_path: Path, freq: float, fs: float):
    """Full-cycle DFT recovers pre- and post-fault RMS phasors at 50/60 Hz (integer & non-integer fs/f0)."""
    pre_ref, post_ref = _make_synth_phasor_pair(
        i_pre=(cmath.rect(120.0, -0.25), cmath.rect(115.0, -2.35), cmath.rect(125.0, 1.85)),
        i_post=(cmath.rect(950.0, -1.05), cmath.rect(118.0, -2.30), cmath.rect(122.0, 1.80)),
        v_pre=(cmath.rect(1.02, 0.0), cmath.rect(1.01, -2.0 * math.pi / 3.0), cmath.rect(1.00, 2.0 * math.pi / 3.0)),
        v_post=(cmath.rect(0.58, -0.18), cmath.rect(0.99, -2.0 * math.pi / 3.0 - 0.04), cmath.rect(0.98, 2.0 * math.pi / 3.0 - 0.03)),
    )
    v_base_ln = 2401.777
    waves, trig_s = comtrade.synthesize_phasor_waveforms(
        pre_ref, post_ref, fs=fs, freq=freq, v_base_ln=v_base_ln, pre_cycles=4, post_cycles=5
    )
    cfg_p, _ = comtrade.write_comtrade(
        tmp_path / f"ph_{int(freq)}_{int(fs)}.cfg",
        analog=waves,
        fs=fs,
        freq=freq,
        fmt="ASCII",
        rev_year=2013,
        trigger_offset_s=trig_s,
    )
    rec = comtrade.read_comtrade(cfg_p)
    info = comtrade.extract_device_phasors(rec, v_base_ln=v_base_ln)

    assert info["onset_source"] == "trigger"
    assert info["v_base_source"] == "explicit_v_base_ln"
    # Tight tolerance for exact integer fs/f0, slightly relaxed for non-integer cubic-spline path
    tol_i = 0.05 if abs((fs / freq) - round(fs / freq)) < 1e-6 else 1.5
    tol_v = 1e-4 if abs((fs / freq) - round(fs / freq)) < 1e-6 else 2e-3
    np.testing.assert_allclose(info["pre"]["i"], pre_ref["i"], atol=tol_i)
    np.testing.assert_allclose(info["post"]["i"], post_ref["i"], atol=tol_i)
    np.testing.assert_allclose(info["pre"]["v"], pre_ref["v"], atol=tol_v)
    np.testing.assert_allclose(info["post"]["v"], post_ref["v"], atol=tol_v)
    assert abs(info["post"]["i0"] - post_ref["i0"]) < tol_i
    assert abs(info["post"]["i2"] - post_ref["i2"]) < tol_i


def test_phasor_skew_and_auto_onset_detection(tmp_path: Path):
    """Channel skew compensation and automatic step onset detection when trigger is at t=0."""
    freq = 60.0
    fs = 3840.0
    skew_us = 250.0  # 250 us delay -> phase shift 2*pi*60*250e-6 rad
    n = 384          # 6 cycles
    t = np.arange(n, dtype=np.float64) / fs
    x_true = cmath.rect(200.0, 0.35)
    # Sampled waveform at t_eff = t + skew_us*1e-6
    y_skew = np.real(math.sqrt(2.0) * x_true * np.exp(1j * 2.0 * math.pi * freq * (t + skew_us * 1e-6)))
    ph = comtrade.extract_cycle_phasor(y_skew, t, freq, t_start=1.0 / freq, skew_us=skew_us)
    assert abs(ph - x_true) < 1e-9

    # Auto step detection when trigger_offset_s = 0 (edge of record)
    pre_ref, post_ref = _make_synth_phasor_pair(
        i_pre=(100 + 0j, cmath.rect(100, -2.0944), cmath.rect(100, 2.0944)),
        i_post=(900 - 300j, cmath.rect(100, -2.0944), cmath.rect(100, 2.0944)),
        v_pre=(1.0 + 0j, cmath.rect(1.0, -2.0944), cmath.rect(1.0, 2.0944)),
        v_post=(0.5 + 0j, cmath.rect(1.0, -2.0944), cmath.rect(1.0, 2.0944)),
    )
    waves, true_trig = comtrade.synthesize_phasor_waveforms(pre_ref, post_ref, fs=fs, freq=freq, pre_cycles=4, post_cycles=5)
    cfg_p, _ = comtrade.write_comtrade(
        tmp_path / "auto_step.cfg",
        analog=waves,
        fs=fs,
        freq=freq,
        fmt="ASCII",
        trigger_offset_s=0.0,  # forces auto_step
    )
    rec = comtrade.read_comtrade(cfg_p)
    info = comtrade.extract_device_phasors(rec, v_base_kv=4.16)
    assert info["onset_source"] == "auto_step"
    assert abs(info["event_time_s"] - true_trig) <= 1.0 / freq
    assert info["v_base_source"] == "explicit_v_base_kv"
    np.testing.assert_allclose(np.abs(info["post"]["i"]), np.abs(post_ref["i"]), rtol=1e-3)


def test_channel_mapping_auto_and_custom_json(tmp_path: Path):
    """Auto-mapper ignores line-to-line voltages (VAB) and accepts custom JSON overrides."""
    n = 64
    t = np.arange(n, dtype=np.float64) / 3840.0
    sig = np.sin(2.0 * math.pi * 60.0 * t)
    chs = [
        comtrade.AnalogChannel(1, "VAB", "AB", "", "V"),
        comtrade.AnalogChannel(2, "F1-IA", "A", "", "A"),
        comtrade.AnalogChannel(3, "F2-IB", "B", "", "A"),
        comtrade.AnalogChannel(4, "F3-IC", "C", "", "A"),
        comtrade.AnalogChannel(5, "F4-IG", "N", "", "A"),
        comtrade.AnalogChannel(6, "AUX_CH", "", "", "V"),
    ]
    cfg_p, _ = comtrade.write_comtrade(
        tmp_path / "map.cfg",
        analog=np.vstack([sig] * len(chs)),
        channels=chs,
        fs=3840.0,
        freq=60.0,
        fmt="ASCII",
    )
    rec = comtrade.read_comtrade(cfg_p)
    auto = comtrade.map_channels(rec)
    assert auto == {"Ia": 1, "Ib": 2, "Ic": 3, "In": 4}
    assert "Va" not in auto  # VAB must not map to Va

    # Custom JSON map with name, '#An' 1-based ref, and None removal
    cmap_path = tmp_path / "channel_map.json"
    cmap_path.write_text(json.dumps({"Va": "#6", "In": None, "Ia": "F1-IA"}), encoding="utf-8")
    loaded = comtrade.load_channel_map(cmap_path)
    custom = comtrade.map_channels(rec, loaded)
    assert custom["Va"] == 5
    assert "In" not in custom
    assert custom["Ia"] == 1


# ---------------------------------------------------------------------------
# 4. Exact feature parity: Tier-2 (15/dev), Transfer (21/node), Active-Grid (26/node)
# ---------------------------------------------------------------------------
def test_tier2_15_features_exact_parity_with_model_and_faults(tmp_path: Path):
    """COMTRADE -> Tier-2 features match `shf.model.feature_columns` & `shf.faults.features`."""
    dummy_df = pd.DataFrame()
    expected_full_cols = model.feature_columns(dummy_df, kind="full")
    expected_mag_cols = model.feature_columns(dummy_df, kind="magnitude")
    assert len(expected_full_cols) == 150
    assert len(expected_mag_cols) == 70
    assert len(comtrade.TIER2_DEVICE_KEYS_FULL) == 15
    assert len(comtrade.TIER2_DEVICE_KEYS_MAG) == 7

    # Synthetic 10-device event matching all config.SECTIONALIZERS
    rng = np.random.default_rng(7)
    pre_all: dict[str, dict] = {}
    post_all: dict[str, dict] = {}
    for d in config.SECTIONALIZERS:
        i_pre = tuple(cmath.rect(rng.uniform(40, 250), rng.uniform(-math.pi, math.pi)) for _ in range(3))
        i_post = tuple(cmath.rect(rng.uniform(50, 900), rng.uniform(-math.pi, math.pi)) for _ in range(3))
        v_pre = tuple(cmath.rect(rng.uniform(0.97, 1.03), -2.0 * math.pi * k / 3.0) for k in range(3))
        v_post = tuple(cmath.rect(rng.uniform(0.45, 1.01), -2.0 * math.pi * k / 3.0 - 0.1) for k in range(3))
        pre_all[d], post_all[d] = _make_synth_phasor_pair(i_pre=i_pre, i_post=i_post, v_pre=v_pre, v_post=v_post)

    # 1) Direct phasor parity against shf.faults.features
    ref_row = faults.features(post_all, pre_all)
    got_row, got_vec, got_cols = comtrade.to_tier2_features(pre_all, post_all, kind="full")
    assert got_cols == expected_full_cols
    ref_vec = np.array([ref_row[c] for c in expected_full_cols], dtype=np.float64)
    np.testing.assert_allclose(got_vec, ref_vec, rtol=1e-12, atol=1e-12)
    assert all(math.isclose(got_row[c], ref_row[c], rel_tol=1e-12, abs_tol=1e-12) for c in expected_full_cols)

    _, mag_vec, mag_cols = comtrade.to_tier2_features(pre_all, post_all, kind="magnitude")
    assert mag_cols == expected_mag_cols
    np.testing.assert_allclose(mag_vec, [ref_row[c] for c in expected_mag_cols], rtol=1e-12, atol=1e-12)

    # 2) Full waveform -> COMTRADE (BINARY, secondary CT/PT) -> comtrade_to_model_inputs parity
    v_base_ln = 4160.0 / math.sqrt(3.0)
    recs: dict[str, Path] = {}
    for d in config.SECTIONALIZERS:
        waves, trig_s = comtrade.synthesize_phasor_waveforms(
            pre_all[d], post_all[d], fs=3840.0, freq=60.0, v_base_ln=v_base_ln, pre_cycles=3, post_cycles=4
        )
        cfg_p, _ = comtrade.write_comtrade(
            tmp_path / f"{d}.cfg",
            analog=waves,
            fs=3840.0,
            freq=60.0,
            fmt="BINARY",
            rev_year=2013,
            trigger_offset_s=trig_s,
            ct_ratio=(1000.0, 1.0),
            pt_ratio=(v_base_ln, 120.0),
            ps="S",
        )
        recs[d] = cfg_p

    bundle = comtrade.comtrade_to_model_inputs(recs, v_base_ln=v_base_ln, include_hif=False)
    assert bundle["tier2"]["columns"] == expected_full_cols
    assert bundle["tier2_devices_missing"] == []
    assert len(bundle["tier2_devices_present"]) == 10
    np.testing.assert_allclose(bundle["tier2"]["vector"], ref_vec, rtol=1e-3, atol=0.15)


def test_graph_21_and_26_features_exact_parity_with_transfer_and_active_grid():
    """Exact parity against `shf.transfer.node_features` (21) and `shf.active_grid.active_node_features` (26)."""
    assert comtrade.TRANSFER_FEATURES == tuple(transfer.FEATURES)
    assert len(comtrade.TRANSFER_FEATURES) == 21
    assert comtrade.ACTIVE_FEATURES == tuple(active_grid.ACTIVE_FEATURES)
    assert len(comtrade.ACTIVE_FEATURES) == 26

    grid, pre, post = _build_demo_grid_and_snapshots()
    struct = transfer.structure(grid)

    # 1) Transfer 21 features
    X_tr_ref = transfer.node_features(grid, pre, post, struct)
    X_tr_got, devs_tr, parent_tr = comtrade.to_transfer_features(pre, post, grid=grid)
    assert devs_tr == grid.devices
    assert X_tr_got.shape == (4, 21)
    assert X_tr_got.dtype == np.float32
    np.testing.assert_array_equal(parent_tr, np.array([-1, 0, 0, 1], dtype=np.int64))
    np.testing.assert_allclose(X_tr_got, X_tr_ref, rtol=1e-6, atol=1e-6)

    # 2) Active-Grid 26 features across reconfigured + closed-loop topologies with DER
    topos = [
        active_grid.TopoSpec("normal", (), (), (), (), False),
        active_grid.TopoSpec("reconfig", ("D2",), ("Tie1",), (("D3", "D4"),), ("D4",), False),
        active_grid.TopoSpec("looped", (), ("Tie1",), (("D3", "D4"),), (), True),
    ]
    adj_all, _ = active_grid.build_topology_matrices(grid, topos)
    der_kw = {"D2": 120.0, "D3": 250.0, "D4": 400.0}

    for ti, topo in enumerate(topos):
        X_ag_ref = active_grid.active_node_features(grid, topo, adj_all[ti], pre, post, der_kw)
        X_ag_got, devs_ag, adj_got = comtrade.to_active_grid_features(
            pre, post, grid=grid, topo=topo, der_kw_by_zone=der_kw
        )
        assert devs_ag == grid.devices
        assert X_ag_got.shape == (4, 26)
        assert X_ag_got.dtype == np.float32
        np.testing.assert_array_equal(adj_got, adj_all[ti])
        np.testing.assert_allclose(X_ag_got, X_ag_ref, rtol=1e-6, atol=1e-6)
        # Verify power reversal flag is active on D3 and D4 (indices 2, 3)
        rev_idx = active_grid.ACTIVE_FEATURES.index("power_rev")
        assert X_ag_got[0, rev_idx] == 0.0
        assert X_ag_got[2, rev_idx] == 1.0
        assert X_ag_got[3, rev_idx] == 1.0


# ---------------------------------------------------------------------------
# 5. Missing devices & missing channels -> NaN handling across all schemas
# ---------------------------------------------------------------------------
def test_missing_devices_and_channels_filled_with_nan(tmp_path: Path):
    """Missing devices populate NaN in Tier-2 (15/dev), Transfer (0..16), and Active-Grid (0..20)."""
    grid, pre, post = _build_demo_grid_and_snapshots()
    # Keep only D1 and D3; omit D2 and D4
    pre_partial = {k: pre[k] for k in ("D1", "D3")}
    post_partial = {k: post[k] for k in ("D1", "D3")}

    # Tier-2 with custom 4-device list: 2 present (30 finite), 2 missing (30 NaN)
    row, vec, cols = comtrade.to_tier2_features(pre_partial, post_partial, devices=grid.devices)
    assert len(cols) == 60
    assert int(np.isfinite(vec).sum()) == 30
    for missing_dev in ("D2", "D4"):
        assert all(math.isnan(row[f"{missing_dev}_{k}"]) for k in comtrade.TIER2_DEVICE_KEYS_FULL)
    for present_dev in ("D1", "D3"):
        assert all(math.isfinite(row[f"{present_dev}_{k}"]) for k in comtrade.TIER2_DEVICE_KEYS_FULL)

    # Transfer: missing devices have NaN in electrical cols 0..16, finite tree structure in 17..20
    X_tr, _, _ = comtrade.to_transfer_features(pre_partial, post_partial, grid=grid)
    assert np.all(np.isfinite(X_tr[0])) and np.all(np.isfinite(X_tr[2]))
    for idx in (1, 3):
        assert np.all(np.isnan(X_tr[idx, :comtrade.N_TRANSFER_ELEC]))
        assert np.all(np.isfinite(X_tr[idx, comtrade.N_TRANSFER_ELEC:]))

    # Active-Grid: missing devices have NaN in electrical cols 0..20, finite grid state in 21..25
    topo = active_grid.TopoSpec("normal", (), (), (), (), False)
    X_ag, _, _ = comtrade.to_active_grid_features(pre_partial, post_partial, grid=grid, topo=topo)
    assert np.all(np.isfinite(X_ag[0])) and np.all(np.isfinite(X_ag[2]))
    for idx in (1, 3):
        assert np.all(np.isnan(X_ag[idx, :comtrade.N_ACTIVE_ELEC]))
        assert np.all(np.isfinite(X_ag[idx, comtrade.N_ACTIVE_ELEC:]))

    # Current-only single device on IEEE 123-bus default 10 devices -> 9 finite, 141 NaN
    fs = 1200.0
    t = np.arange(80, dtype=np.float64) / fs
    ia = 150.0 * np.sqrt(2.0) * np.cos(2.0 * math.pi * 60.0 * t)
    ib = 150.0 * np.sqrt(2.0) * np.cos(2.0 * math.pi * 60.0 * t - 2.0 * math.pi / 3.0)
    ic = 150.0 * np.sqrt(2.0) * np.cos(2.0 * math.pi * 60.0 * t + 2.0 * math.pi / 3.0)
    cfg_p, _ = comtrade.write_comtrade(
        tmp_path / "curr_only.cfg",
        analog={"IA": ia, "IB": ib, "IC": ic},
        fs=fs,
        freq=60.0,
        fmt="ASCII",
    )
    bundle = comtrade.comtrade_to_model_inputs(cfg_p, device_name="Sw1", include_hif=False)
    assert bundle["tier2_devices_present"] == ["Sw1"]
    assert len(bundle["tier2_devices_missing"]) == 9
    assert int(np.isfinite(bundle["tier2"]["vector"]).sum()) == 9  # 9 current features finite, 6 voltage + 135 missing = 141 NaN
    for vk in ("Va", "Vb", "Vc", "dVa", "dVb", "dVc"):
        assert math.isnan(bundle["tier2"]["features"][f"Sw1_{vk}"])


# ---------------------------------------------------------------------------
# 6. Optional Tier-1 HIF bridge guards and parity
# ---------------------------------------------------------------------------
def test_hif_edge_guards_and_synthetic_parity(tmp_path: Path):
    """Low sampling rate, short duration, or missing currents cleanly return ok=False; 15.36 kHz matches."""
    # Guard 1: fs too low (480 Hz < 16 * 60 = 960 Hz)
    t_low = np.arange(160, dtype=np.float64) / 480.0
    cfg_low, _ = comtrade.write_comtrade(
        tmp_path / "low_fs.cfg",
        analog={"IN": np.sin(2.0 * math.pi * 60.0 * t_low)},
        fs=480.0,
        freq=60.0,
        fmt="ASCII",
    )
    res_low = comtrade.to_hif_edge_features(comtrade.read_comtrade(cfg_low))
    assert res_low["ok"] is False
    assert "Sampling rate too low" in res_low["reason"]

    # Guard 2: duration < K=8 cycles (4 cycles at 3840 Hz)
    t_short = np.arange(256, dtype=np.float64) / 3840.0
    cfg_short, _ = comtrade.write_comtrade(
        tmp_path / "short.cfg",
        analog={"IN": np.sin(2.0 * math.pi * 60.0 * t_short)},
        fs=3840.0,
        freq=60.0,
        fmt="ASCII",
    )
    res_short = comtrade.to_hif_edge_features(comtrade.read_comtrade(cfg_short))
    assert res_short["ok"] is False
    assert "too short" in res_short["reason"]

    # Guard 3: voltage-only -> no residual channel
    cfg_vonly, _ = comtrade.write_comtrade(
        tmp_path / "vonly.cfg",
        analog={"VA": np.sin(2.0 * math.pi * 60.0 * t_short)},
        fs=3840.0,
        freq=60.0,
        fmt="ASCII",
    )
    res_vonly = comtrade.to_hif_edge_features(comtrade.read_comtrade(cfg_vonly))
    assert res_vonly["ok"] is False
    assert "No residual channel" in res_vonly["reason"]

    # Happy path: 15.36 kHz simulated Emanuel HIF matches shf.hif_edge.window_features
    rng = np.random.default_rng(123)
    amps, meta = hif_edge.make_event(rng, is_hif=True)
    X_gt, ends_gt = hif_edge.window_features(amps)
    cfg_ok, _ = comtrade.write_comtrade(
        tmp_path / "hif_ok.cfg",
        analog={"IN": amps},
        fs=hif_edge.FS_ADC,
        freq=hif_edge.F_LINE,
        fmt="BINARY",
        rev_year=2013,
    )
    hif_mod_path = hif_edge.find_model_npz()
    hif_mod = hif_edge.load_model_npz(hif_mod_path) if hif_mod_path is not None else None
    res_ok = comtrade.to_hif_edge_features(
        comtrade.read_comtrade(cfg_ok),
        model=hif_mod,
        start_cycle=int(meta["start_cycle"]),
    )
    assert res_ok["ok"] is True
    assert res_ok["features"].shape == X_gt.shape
    assert res_ok["feature_names"] == list(hif_edge.FEATURES)
    np.testing.assert_allclose(res_ok["features"], X_gt, atol=1e-3, rtol=1e-3)
    if hif_mod is not None:
        assert res_ok["p_hif"] is not None
        assert 0.0 <= res_ok["p_hif"] <= 1.0


# ---------------------------------------------------------------------------
# 7. Bundled public & synthetic samples in data/comtrade_samples/
# ---------------------------------------------------------------------------
def test_public_comtrade_samples_read_and_convert():
    """All 5 bundled open-source IEEE C37.111 samples parse cleanly and match summary hashes."""
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    pub_entries = summary["public_samples"]
    assert len(pub_entries) == 5

    for item in pub_entries:
        cfg_p = ROOT / item["cfg"]
        dat_p = ROOT / item["dat"]
        assert cfg_p.is_file(), f"Missing public sample cfg: {cfg_p}"
        assert dat_p.is_file(), f"Missing public sample dat: {dat_p}"
        assert _file_sha256(cfg_p) == item["cfg_sha256"]
        assert _file_sha256(dat_p) == item["dat_sha256"]

        rec = comtrade.read_comtrade(cfg_p, side="primary")
        assert rec.rev_year == item["rev_year"]
        assert rec.data_format == item["data_format"]
        assert rec.frequency == pytest.approx(item["frequency_hz"])
        assert rec.n_samples == item["n_samples"]
        assert rec.n_analog == item["n_analog"]
        assert rec.n_digital == item["n_digital"]

        bundle = comtrade.comtrade_to_model_inputs(rec, device_name="Sw1", include_hif=True)
        assert bundle["tier2"]["vector"].shape == (150,)
        assert int(np.isfinite(bundle["tier2"]["vector"]).sum()) == item["tier2_finite_features"]
        assert list(bundle["transfer"]["X"].shape) == item["transfer_shape"]
        assert list(bundle["active_grid"]["X"].shape) == item["active_grid_shape"]
        mapped = {
            k: rec.analog_channels[idx].name
            for k, idx in bundle["phasors"]["Sw1"]["channel_map"].items()
        }
        assert mapped == item["mapped_channels"]


def test_synthetic_roundtrip_samples_and_ingest_cli(tmp_path: Path):
    """Bundled synthetic OpenDSS/LTspice/Tier-1 COMTRADE files match manifest ground truth & CLI."""
    manifest_p = SYNTH_DIR / "manifest.json"
    assert manifest_p.is_file()
    manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert manifest["simulation_only"] is True
    assert len(manifest["opendss_events"]) == 3
    assert len(manifest["ltspice_records"]) == 2

    # Check OpenDSS multi-device folder parity on event 0 (bus 60 ASCII with channel_map.json)
    ev0 = manifest["opendss_events"][0]
    ev0_dir = ROOT / ev0["dir"]
    assert (ev0_dir / "channel_map.json").is_file()
    for dev, fmeta in ev0["devices"].items():
        assert _file_sha256(ROOT / fmeta["cfg"]) == fmeta["cfg_sha256"]
        assert _file_sha256(ROOT / fmeta["dat"]) == fmeta["dat_sha256"]

    feeder.load_feeder()
    grid_123 = transfer.study_grid()
    topo_normal = active_grid.TOPOLOGIES["ieee123"][0]
    adj_all, _ = active_grid.build_topology_matrices(grid_123, [topo_normal])

    recs = {d: comtrade.read_comtrade(ROOT / fmeta["cfg"], side="primary") for d, fmeta in ev0["devices"].items()}
    bundle = comtrade.comtrade_to_model_inputs(
        recs,
        v_base_ln=ev0["v_base_ln_v"],
        grid=grid_123,
        topo=topo_normal,
        adj=adj_all[0],
        include_hif=False,
    )
    gt_t2 = np.array([ev0["gt_tier2"][c] for c in bundle["tier2"]["columns"]], dtype=np.float64)
    np.testing.assert_allclose(bundle["tier2"]["vector"], gt_t2, rtol=1e-4, atol=1e-2)
    np.testing.assert_allclose(bundle["transfer"]["X"], np.asarray(ev0["gt_transfer"], dtype=np.float32), atol=1e-4)
    np.testing.assert_allclose(bundle["active_grid"]["X"], np.asarray(ev0["gt_active_grid"], dtype=np.float32), atol=1e-4)

    # Check LTspice & Tier-1 HIF synthetic files exist and match manifest hashes
    for lt in manifest["ltspice_records"]:
        assert _file_sha256(ROOT / lt["cfg"]) == lt["cfg_sha256"]
        assert _file_sha256(ROOT / lt["dat"]) == lt["dat_sha256"]
        rec_lt = comtrade.read_comtrade(ROOT / lt["cfg"], side="primary")
        assert rec_lt.n_samples > 1000

    t1 = manifest["tier1_hif_record"]
    assert _file_sha256(ROOT / t1["cfg"]) == t1["cfg_sha256"]
    assert _file_sha256(ROOT / t1["dat"]) == t1["dat_sha256"]
    hif_res = comtrade.to_hif_edge_features(
        comtrade.read_comtrade(ROOT / t1["cfg"], side="primary"),
        channel_map={"In": "IN"},
        start_cycle=int(t1["start_cycle"]),
    )
    assert hif_res["ok"] is True
    gt_hif = np.asarray(t1["gt_features"], dtype=np.float32)
    np.testing.assert_allclose(hif_res["features"][: len(gt_hif)], gt_hif, atol=1e-3)

    # Exercise scripts/comtrade_ingest.py CLI (single public file + multi-device folder, writing only to tmp_path)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts import comtrade_ingest

    out_single = tmp_path / "single_out.json"
    rc1 = comtrade_ingest.main([
        str(PUBLIC_DIR / "fdr2214_ag_fault.cfg"),
        "--no-infer",
        "--out-features",
        str(out_single),
    ])
    assert rc1 == 0 and out_single.is_file()
    p1 = json.loads(out_single.read_text(encoding="utf-8"))
    assert p1["feature_summary"]["tier2_finite"] == 15
    assert p1["feature_summary"]["tier2_total"] == 150
    assert p1["feature_summary"]["transfer_shape"] == [1, 21]
    assert p1["feature_summary"]["active_grid_shape"] == [1, 26]

    out_multi = tmp_path / "multi_out.json"
    rc2 = comtrade_ingest.main([
        str(ev0_dir),
        "--channel-map",
        str(ev0_dir / "channel_map.json"),
        "--no-infer",
        "--out-features",
        str(out_multi),
    ])
    assert rc2 == 0 and out_multi.is_file()
    p2 = json.loads(out_multi.read_text(encoding="utf-8"))
    assert p2["feature_summary"]["tier2_finite"] == 150
    assert p2["feature_summary"]["transfer_shape"] == [10, 21]
    assert p2["feature_summary"]["active_grid_shape"] == [10, 26]


# ---------------------------------------------------------------------------
# 8. Schema, provenance, and published-copy validation for results/comtrade/summary.json
# ---------------------------------------------------------------------------
def test_comtrade_summary_schema_provenance_and_published_copy():
    """Validate results/comtrade/summary.json schema, counts, honesty notices, provenance & docs/data sync."""
    assert SUMMARY_PATH.is_file(), "results/comtrade/summary.json missing"
    assert PUB_SUMMARY_PATH.is_file(), "docs/data/comtrade_summary.json missing"
    assert PROV_PATH.is_file(), "results/provenance/comtrade_verify.json missing"

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    required_top = {
        "status",
        "simulation_notice",
        "models_available",
        "counts",
        "parity",
        "public_samples",
        "synthetic_opendss",
        "synthetic_ltspice",
        "synthetic_hif_edge",
        "single_device_demo",
        "cli_examples",
        "runtime_s",
    }
    assert required_top.issubset(summary.keys())
    assert summary["status"] == "ok"
    assert "simulation" in summary["simulation_notice"].lower()

    counts = summary["counts"]
    assert counts["public_samples"] == len(summary["public_samples"]) == 5
    assert counts["public_passed"] == counts["public_samples"]
    assert counts["synthetic_opendss_events"] == len(summary["synthetic_opendss"]) == 3
    assert counts["synthetic_opendss_passed"] == counts["synthetic_opendss_events"]
    assert counts["synthetic_ltspice_records"] == len(summary["synthetic_ltspice"]) == 2
    assert counts["synthetic_ltspice_passed"] == counts["synthetic_ltspice_records"]
    assert counts["synthetic_hif_records"] == 1
    assert counts["synthetic_hif_passed"] == 1
    expected_total = (
        counts["public_samples"]
        + counts["synthetic_opendss_events"]
        + counts["synthetic_ltspice_records"]
        + counts["synthetic_hif_records"]
    )
    assert counts["total_verified"] == expected_total == 11
    assert counts["total_passed"] == expected_total

    # Every synthetic entry must explicitly declare simulation=True
    for ev in summary["synthetic_opendss"]:
        assert ev["simulation"] is True
        assert ev["ok"] is True
        assert ev["n_devices"] == 10
    for lt in summary["synthetic_ltspice"]:
        assert lt["simulation"] is True
        assert lt["ok"] is True
    assert summary["synthetic_hif_edge"]["simulation"] is True
    assert summary["synthetic_hif_edge"]["ok"] is True

    # Parity bounds & single-device limitation demo
    parity = summary["parity"]
    assert parity["opendss_max_tier2_rel_err"] < 1e-3
    assert parity["opendss_max_transfer_abs_err"] < 1e-3
    assert parity["opendss_max_active_abs_err"] < 1e-3
    assert parity["opendss_tier2_model_matches"] == parity["opendss_total_events"] == 3
    assert parity["opendss_transfer_gbdt_matches"] == 3
    assert parity["opendss_transfer_gnn_matches"] == 3

    sdemo = summary["single_device_demo"]
    assert sdemo["simulation"] is True
    assert sdemo["single_device_finite_tier2"] == 15
    assert sdemo["all_10_devices_finite_tier2"] == 150

    # Published copy matches results/ ignoring CRLF/LF
    assert (
        SUMMARY_PATH.read_bytes().replace(b"\r\n", b"\n")
        == PUB_SUMMARY_PATH.read_bytes().replace(b"\r\n", b"\n")
    )

    # Provenance manifest records exact SHA-256 of results/comtrade/summary.json
    prov = json.loads(PROV_PATH.read_text(encoding="utf-8"))
    assert prov["producer"] == "comtrade_verify"
    assert "results/comtrade/summary.json" in prov["files"]
    assert prov["files"]["results/comtrade/summary.json"] == hashlib.sha256(
        SUMMARY_PATH.read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest() or prov["files"]["results/comtrade/summary.json"] == _file_sha256(SUMMARY_PATH)
