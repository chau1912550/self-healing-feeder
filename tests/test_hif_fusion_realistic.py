"""Unit, integration, artifact, and dashboard tests for Branch-10 realistic HIF-Fusion.

Covers:
  1. Backward compatibility (`realistic=False`, `arc_duty=None`) vs realistic mode
     (`realistic=True`: intermittent arcing `r_eff` & `arc_duty`, hierarchical zone
     loading + pre/post drift, CT/PT systematic bias + additive noise floors), with
     zero NaN/Inf and zero label leakage.
  2. Simultaneous single-sensor blanking across 60 Hz electrical channels AND Tier-1
     edge channels `(p_hif, hif_alarm)` for passive graphs, active graphs, and `ml_full`.
  3. Real experiment artifacts in `results/hif_fusion_realistic/*.json` (`quick_mode=False`,
     exact frozen Tier-1 `model_int8.npz` SHA-256 lock, provenance manifest, published
     `docs/data/` copies) and complete preservation of legacy `results/hif_fusion/*.json`.
  4. Static verification of `docs/index.html` section 2d (Before/After Branch-10 table,
     pre-registered R1-R4 verdict chips, and bilingual EN/VI honest simulation disclaimer).

Simulation only. All result numbers checked dynamically against `results/`.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import numpy as np
import pytest

from shf import config, faults, hif_edge as he, hif_fusion as hf, model as shf_model, provenance

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_TIER1_SHA256 = "3ba5bd23685d7964a6cea0c94064c1e65a8bf3129d83ac129215d110218397c1"

REALISTIC_RESULT_FILES = (
    "dataset_summary.json",
    "passive_ieee123.json",
    "passive_ieee34.json",
    "active_ieee123.json",
    "active_ieee34.json",
    "conformal_hif.json",
    "summary.json",
)

LEGACY_RESULT_FILES = (
    "dataset_summary.json",
    "passive_ieee123.json",
    "passive_ieee34.json",
    "active_ieee123.json",
    "active_ieee34.json",
    "conformal_hif.json",
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _same_text(a: Path, b: Path) -> bool:
    return a.read_bytes().replace(b"\r\n", b"\n") == b.read_bytes().replace(b"\r\n", b"\n")


def _load_frozen_tier1_model() -> he.EdgeModel:
    model_path = ROOT / "hif_sensor" / "results" / "model_int8.npz"
    assert model_path.is_file(), f"Frozen Tier-1 model missing: {model_path}"
    return he.load_model_npz(model_path, source="hif_sensor/results/model_int8.npz")


def _load_realistic_runner_module():
    script_path = ROOT / "scripts" / "hif_fusion_realistic_run.py"
    spec = importlib.util.spec_from_file_location("hif_fusion_realistic_run_testmod", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. Backward compatibility (realistic=False) vs Realistic physics (realistic=True)
# ---------------------------------------------------------------------------
def test_arc_waveform_backward_compat_and_arc_duty_sync():
    t = he.standard_time_grid()
    t0 = (he.WARMUP + 20) / he.F_LINE
    surf = he.SURFACES["dry_grass"]

    # Default call and explicit arc_duty=None must be bit-for-bit identical.
    w_default = he._arc(t, t0, np.random.default_rng(123), surf)
    w_none = he._arc(t, t0, np.random.default_rng(123), surf, arc_duty=None)
    assert np.array_equal(w_default, w_none)
    assert np.isfinite(w_default).all()

    # Synchronized arc_duty=1.0 (p_off=0.0) keeps post-event cycles conducting,
    # whereas arc_duty=0.35 (p_off=0.65) drops many post-event cycles to zero.
    spc = he.N_CYCLE * he.OVERSAMPLE
    post_start = (he.WARMUP + 22) * spc

    def _dropout_stats(arc_duty: float) -> tuple[float, float]:
        zero_cyc_shares = []
        zero_samp_shares = []
        for s in range(25):
            w = he._arc(t, t0, np.random.default_rng(1000 + s), surf, arc_duty=arc_duty)
            assert np.isfinite(w).all()
            post = w[post_start:]
            cyc_blocks = post.reshape(-1, spc)
            cyc_rms = np.sqrt(np.mean(cyc_blocks ** 2, axis=1))
            zero_cyc_shares.append(float(np.mean(cyc_rms < 1e-12)))
            zero_samp_shares.append(float(np.mean(np.abs(post) < 1e-12)))
        return float(np.mean(zero_cyc_shares)), float(np.mean(zero_samp_shares))

    zero_cont, samp_cont = _dropout_stats(1.0)
    zero_interm, samp_interm = _dropout_stats(0.35)
    # Fixed spc-aligned bins straddle random phase phv, so an aligned bin is fully zero
    # with probability ~p_off^2 (~0.4225 for p_off=0.65 vs 0.0 for p_off=0.0).
    assert zero_cont < 0.05, f"continuous arc_duty=1.0 should rarely drop cycles, got {zero_cont}"
    assert zero_interm > 0.35, f"intermittent arc_duty=0.35 (p_off=0.65) expected >35% zero bins, got {zero_interm}"
    assert samp_interm > samp_cont + 0.25, f"expected markedly more zero samples at arc_duty=0.35 ({samp_interm} vs {samp_cont})"

    # synthesize_event_edge with arc_duty + linear di_res_drift keeps all outputs finite
    # and injects only a linear 60 Hz step (no Emanuel arc) onto a healthy branch (di_res=0).
    model = _load_frozen_tier1_model()
    i_res_pre = np.array([6.0, 4.0, 5.0], dtype=np.float64)
    di_res = np.array([3.5, 0.0, 0.0], dtype=np.float64)
    di_res_drift = np.array([0.8, 2.0, 0.0], dtype=np.float64)
    is_closed = np.array([True, True, False], dtype=bool)
    ef, info = hf.synthesize_event_edge(
        i_res_pre, di_res, is_closed, model, np.random.default_rng(42),
        is_arcing=True, is_nofault=False, surface="wet_grass",
        arc_duty=0.35, di_res_drift=di_res_drift,
    )
    assert ef.shape == (3, 2) and np.isfinite(ef).all()
    assert (ef[:, 0] >= 0.0).all() and (ef[:, 0] <= 1.0).all()
    assert set(np.unique(ef[:, 1])).issubset({0.0, 1.0})
    assert info["is_arcing"] is True and info["surface"] == "wet_grass"
    assert info["device_disturbances"][2] == "open"
    # Healthy closed switch with di_res=0 and linear 60 Hz drift only (when disturbance=='none')
    # does not receive an Emanuel arc waveform and stays free of spurious HIF alarm.
    if info["device_disturbances"][1] == "none":
        assert ef[1, 1] == 0.0


def test_realistic_arc_resistance_voltage_scaling_and_load_ct_pt_noise():
    rng = np.random.default_rng(2026)

    # Non-SLG and low-R SLG keep r_eff == r_nom cleanly.
    for ftype, r_nom in (("3PH", 10.0), ("LL", 10.0), ("LLG", 10.0), ("SLG", 0.01), ("SLG", 50.0)):
        arc = hf._sample_realistic_arc(r_nom, ftype, rng)
        assert arc["is_arcing"] is False
        assert arc["r_eff"] == pytest.approx(r_nom)
        assert arc["arc_kappa"] == pytest.approx(1.0)
        assert arc["arc_duty"] == pytest.approx(1.0)

    # 4.16 kV SLG 400 ohm: intermittent & continuous regimes, capped at config.HIF_R_EFF_MAX (2500 ohm).
    draws_400 = [hf._sample_realistic_arc(400.0, "SLG", rng) for _ in range(200)]
    assert all(d["is_arcing"] for d in draws_400)
    assert all(200.0 <= d["r_eff"] <= config.HIF_R_EFF_MAX for d in draws_400)
    assert all(0.0 < d["arc_kappa"] < 1.0 for d in draws_400)
    assert any(0.35 <= d["arc_duty"] <= 0.85 for d in draws_400), "expected intermittent arc draws"
    assert any(d["arc_duty"] == 1.0 for d in draws_400), "expected continuous arc draws"

    # 24.9 kV HV SLG 5,000 & 10,000 ohm: cap scales as 6.25 * r_nom (never clipped down to 2500 ohm).
    for r_hv in (5000.0, 10000.0):
        draws_hv = [hf._sample_realistic_arc(r_hv, "SLG", rng) for _ in range(80)]
        assert all(d["is_arcing"] for d in draws_hv)
        assert all(0.5 * r_hv <= d["r_eff"] <= 6.25 * r_hv for d in draws_hv)
        assert any(d["r_eff"] > config.HIF_R_EFF_MAX for d in draws_hv)

    # Hierarchical zone loading & pre/post drift: realistic=False has zero drift; realistic=True has drift.
    load_zones = np.array([i % 5 for i in range(60)], dtype=int)
    f_pre_clean, f_post_clean = faults.sample_load_factors(load_zones, 5, np.random.default_rng(11), realistic=False)
    assert np.array_equal(f_pre_clean, f_post_clean)
    assert np.isfinite(f_pre_clean).all() and (f_pre_clean > 0.0).all()

    f_pre_real, f_post_real = faults.sample_load_factors(load_zones, 5, np.random.default_rng(11), realistic=True)
    assert np.isfinite(f_pre_real).all() and np.isfinite(f_post_real).all()
    assert (f_pre_real > 0.0).all() and (f_post_real > 0.0).all()
    assert not np.allclose(f_pre_real, f_post_real), "realistic=True must apply pre-to-post load drift"
    ratio = f_post_real / f_pre_real
    lo_d, hi_d = config.LOAD_DRIFT_CLIP
    assert float(ratio.min()) >= lo_d - 1e-9 and float(ratio.max()) <= hi_d + 1e-9

    # Systematic CT/PT bias + additive noise floors perturb energized phases only, with zero NaN/Inf.
    devices = ["Sw1", "Sw2"]
    bias = faults.sample_ct_pt_bias(devices, np.random.default_rng(22))
    assert set(bias.keys()) == set(devices)
    clean_meas = {
        "Sw1": {
            "i": np.array([100.0 + 0j, -50.0 + 86.6j, 0.0 + 0j]),
            "v": np.array([1.0 + 0j, -0.5 + 0.866j, 0.0 + 0j]),
            "i0": (50.0 + 86.6j) / 3.0,
            "i2": 10.0 + 0j,
        },
        "Sw2": {
            "i": np.array([50.0 + 0j, 50.0 + 0j, 50.0 + 0j]),
            "v": np.array([1.0 + 0j, 1.0 + 0j, 1.0 + 0j]),
            "i0": 50.0 + 0j,
            "i2": 0.0 + 0j,
        },
    }
    pert = faults._perturb(
        clean_meas, np.random.default_rng(33), bias=bias,
        floor_i=config.NOISE_I_FLOOR_A, floor_v=config.NOISE_V_FLOOR_PU,
    )
    for d in devices:
        assert np.isfinite(pert[d]["i"]).all() and np.isfinite(pert[d]["v"]).all()
        assert np.isfinite(pert[d]["i0"]) and np.isfinite(pert[d]["i2"])
    # Unenergized phase C on Sw1 stays exactly 0.
    assert pert["Sw1"]["i"][2] == 0.0 and pert["Sw1"]["v"][2] == 0.0
    # Energized phases are perturbed relative to clean.
    assert not np.allclose(pert["Sw1"]["i"][:2], clean_meas["Sw1"]["i"][:2])


def test_passive_sweep_backward_compat_vs_realistic_ieee123(tmp_path):
    model = _load_frozen_tier1_model()
    npz_clean = tmp_path / "clean_passive_123.npz"
    npz_real = tmp_path / "realistic_passive_123.npz"

    sum_clean = hf.sweep_passive_fusion(
        "ieee123", model, seed=7, scenarios=1, max_cases=24,
        out_path=npz_clean, verbose=False, realistic=False,
    )
    sum_real = hf.sweep_passive_fusion(
        "ieee123", model, seed=7, scenarios=1, max_cases=24,
        out_path=npz_real, verbose=False, realistic=True,
    )

    assert sum_clean["realistic_mode"] is False and sum_clean["converged"] == 24
    assert sum_real["realistic_mode"] is True and sum_real["converged"] == 24
    assert sum_real["arcing_events"] > 0

    ds_clean = hf.load_passive_fusion_dataset("ieee123", path=npz_clean)
    ds_real = hf.load_passive_fusion_dataset("ieee123", path=npz_real)

    # Backward-compatible realistic=False dataset defaults cleanly.
    assert ds_clean.realistic_mode is False
    assert ds_clean.X_ml_full is None
    assert ds_clean.X.shape == (24, 10, 23) and np.isfinite(ds_clean.X).all()
    assert ds_clean.X_60hz.shape == (24, 10, 21) and np.isfinite(ds_clean.X_60hz).all()
    assert np.allclose(ds_clean.r_eff, ds_clean.r)
    assert np.all(ds_clean.arc_kappa == 1.0)
    assert np.all(ds_clean.arc_duty == 1.0)

    # Realistic=True dataset activates r_eff, arc_kappa, arc_duty, load drift, CT/PT noise & X_ml_full.
    assert ds_real.realistic_mode is True
    assert ds_real.X.shape == (24, 10, 23) and np.isfinite(ds_real.X).all()
    assert ds_real.X_60hz.shape == (24, 10, 21) and np.isfinite(ds_real.X_60hz).all()
    assert ds_real.X_ml_full is not None and ds_real.X_ml_full.shape == (24, 150)
    assert np.isfinite(ds_real.X_ml_full).all()
    assert ds_real.ml_full_features is not None and len(ds_real.ml_full_features) == 150

    # Verify exact column order match with shf.model.feature_columns(..., kind="full").
    import pandas as pd

    dummy_df = pd.DataFrame(columns=ds_real.ml_full_features)
    assert shf_model.feature_columns(dummy_df, kind="full") == ds_real.ml_full_features

    # Check raw npz carries di_res_drift (non-zero pre->post load drift on arcing events).
    with np.load(npz_real, allow_pickle=False) as raw:
        assert "di_res_drift" in raw.files
        drift = raw["di_res_drift"]
        assert drift.shape == (24, 10) and np.isfinite(drift).all()
        arc_mask = ds_real.is_arcing
        assert float(np.abs(drift[arc_mask]).max()) > 0.0, "expected non-zero load drift on arcing events"

    # Arcing SLG >= 100 ohm events actually activate r_eff != r and arc_kappa < 1.0.
    arc_mask = ds_real.is_arcing
    assert int(arc_mask.sum()) > 0
    assert not np.allclose(ds_real.r_eff[arc_mask], ds_real.r[arc_mask])
    assert (ds_real.arc_kappa[arc_mask] < 1.0).all()
    assert ((ds_real.arc_duty[arc_mask] >= 0.35) & (ds_real.arc_duty[arc_mask] <= 1.0)).all()

    # Non-arcing events keep r_eff == r, arc_kappa == 1.0, arc_duty == 1.0.
    non_arc = ~arc_mask
    assert int(non_arc.sum()) > 0
    assert np.allclose(ds_real.r_eff[non_arc], ds_real.r[non_arc])
    assert np.all(ds_real.arc_kappa[non_arc] == 1.0)
    assert np.all(ds_real.arc_duty[non_arc] == 1.0)

    # Realistic 60 Hz measurements differ from clean 60 Hz due to zone loading, drift, and CT/PT noise.
    assert not np.allclose(ds_real.X_60hz, ds_clean.X_60hz)

    # No label leakage in feature names; valid bounds for y, p_hif, hif_alarm.
    forbidden_leak_names = {"y", "label", "zone", "bus", "r", "r_eff", "arc_duty", "arc_kappa", "ftype", "is_arcing"}
    assert forbidden_leak_names.isdisjoint(set(ds_real.features))
    assert forbidden_leak_names.isdisjoint(set(ds_real.ml_full_features))
    assert ds_real.y.min() >= 0 and ds_real.y.max() < len(ds_real.devices)
    p_col = hf.PASSIVE_FUSED_FEATURES.index("p_hif")
    a_col = hf.PASSIVE_FUSED_FEATURES.index("hif_alarm")
    assert (ds_real.X[:, :, p_col] >= 0.0).all() and (ds_real.X[:, :, p_col] <= 1.0).all()
    assert set(np.unique(ds_real.X[:, :, a_col])).issubset({0.0, 1.0})


def test_active_sweep_realistic_ieee34_hv_and_all_7_disturbances(tmp_path):
    model = _load_frozen_tier1_model()
    npz_real = tmp_path / "realistic_active_34.npz"

    summary = hf.sweep_active_fusion(
        "ieee34", model, seed=3, scenarios_per_topo=1, max_cases=18,
        max_nofault_per_topo=15, out_path=npz_real, verbose=False, realistic=True,
    )
    assert summary["realistic_mode"] is True
    assert summary["converged"] > 0 and summary["arcing_events"] > 0

    ds = hf.load_active_fusion_dataset("ieee34", path=npz_real)
    assert ds.realistic_mode is True
    assert ds.X.shape[1:] == (len(ds.devices), 28) and np.isfinite(ds.X).all()
    assert ds.X_60hz.shape[1:] == (len(ds.devices), 26) and np.isfinite(ds.X_60hz).all()
    assert ds.features == hf.ACTIVE_FUSED_FEATURES

    p_col = hf.ACTIVE_FUSED_FEATURES.index("p_hif")
    a_col = hf.ACTIVE_FUSED_FEATURES.index("hif_alarm")
    assert (ds.X[:, :, p_col] >= 0.0).all() and (ds.X[:, :, p_col] <= 1.0).all()
    assert set(np.unique(ds.X[:, :, a_col])).issubset({0.0, 1.0})

    # All 7 background disturbances must appear in NO_FAULT events, with no arcing leakage.
    nf = ds.y == ds.nofault_class
    assert int(nf.sum()) > 0
    assert not ds.is_arcing[nf].any()
    assert np.all(ds.r_eff[nf] == -1.0)
    assert np.all(ds.arc_duty[nf] == 1.0)
    assert set(ds.edge_disturbance[nf].tolist()) == set(he.DISTURBANCES)

    # HV SLG >= 5000 ohm must use voltage-scaled r_eff cap (never clipped down to 2500 ohm).
    hv_mask = (ds.ftype == "SLG") & (ds.r >= 5000.0)
    assert int(hv_mask.sum()) > 0
    assert (ds.r_eff[hv_mask] >= 0.5 * ds.r[hv_mask]).all()
    assert (ds.r_eff[hv_mask] > config.HIF_R_EFF_MAX).any()


# ---------------------------------------------------------------------------
# 2. Simultaneous 1-sensor blanking: 60 Hz AND (p_hif, hif_alarm)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("branch,n_nodes,n_feat,n_live", [
    ("passive", 10, 23, hf.N_PASSIVE_FUSED_ELEC),
    ("active", 7, 28, hf.N_ACTIVE_FUSED_ELEC),
])
def test_single_sensor_blanking_blanks_60hz_and_edge_simultaneously_graph(branch, n_nodes, n_feat, n_live):
    rng = np.random.default_rng(91)
    X = rng.uniform(0.1, 1.0, size=(30, n_nodes, n_feat)).astype(np.float32)
    feats = hf.PASSIVE_FUSED_FEATURES if branch == "passive" else hf.ACTIVE_FUSED_FEATURES
    p_idx = feats.index("p_hif")
    a_idx = feats.index("hif_alarm")
    n_60 = n_live - 2
    assert p_idx == n_60 and a_idx == n_60 + 1

    # Single-sensor blanking on every node wipes BOTH 60 Hz channels AND (p_hif, hif_alarm) together.
    for node in range(n_nodes):
        Xb = hf.blank_fused_sensor(X, node=node, branch=branch)
        assert np.isnan(Xb[:, node, :n_60]).all(), "60 Hz live electrical channels must be NaN"
        assert np.isnan(Xb[:, node, p_idx]).all() and np.isnan(Xb[:, node, a_idx]).all(), "edge channels must be NaN"
        assert np.isfinite(Xb[:, node, n_live:]).all(), "structural/grid-state channels must stay finite"
        assert np.array_equal(Xb[:, node, n_live:], X[:, node, n_live:])
        for other in range(n_nodes):
            if other != node:
                assert np.array_equal(Xb[:, other, :], X[:, other, :])

    # Sensor dropout blanks 60 Hz and edge on the exact same node (never mismatched).
    Xd = hf.apply_fused_sensor_dropout(X, np.random.default_rng(92), branch=branch, rate=0.5)
    nan_60 = np.isnan(Xd[:, :, 0])
    nan_p = np.isnan(Xd[:, :, p_idx])
    nan_a = np.isnan(Xd[:, :, a_idx])
    assert np.array_equal(nan_60, nan_p) and np.array_equal(nan_p, nan_a)
    assert np.isfinite(Xd[:, :, n_live:]).all()
    dropped_per_event = nan_p.sum(axis=1)
    assert ((dropped_per_event == 0) | (dropped_per_event == 1)).all()
    assert int(dropped_per_event.sum()) > 0


def test_single_sensor_blanking_blanks_60hz_and_edge_simultaneously_ml_full():
    runner = _load_realistic_runner_module()
    n_dev = 10
    n_per_dev = len(hf.ML_FULL_DEVICE_KEYS)  # 15
    assert n_per_dev == 15

    rng = np.random.default_rng(404)
    X_170 = rng.uniform(0.1, 2.0, size=(40, n_dev * n_per_dev + 2 * n_dev)).astype(np.float32)

    for dev_idx in range(n_dev):
        Xb = runner._blank_ml_full_sensor(X_170, dev_idx, n_dev, use_edge=True)
        cols_60 = list(range(dev_idx * n_per_dev, (dev_idx + 1) * n_per_dev))
        cols_edge = [n_dev * n_per_dev + 2 * dev_idx, n_dev * n_per_dev + 2 * dev_idx + 1]
        assert np.isnan(Xb[:, cols_60]).all(), f"ml_full 60 Hz cols not blanked for dev {dev_idx}"
        assert np.isnan(Xb[:, cols_edge]).all(), f"ml_full edge cols not blanked for dev {dev_idx}"

        other_cols = [c for c in range(X_170.shape[1]) if c not in set(cols_60 + cols_edge)]
        assert np.isfinite(Xb[:, other_cols]).all()
        assert np.array_equal(Xb[:, other_cols], X_170[:, other_cols])

    # Training sensor dropout for ml_full +Edge blanks 0 or 1 device per event, jointly across 60 Hz + edge.
    Xd = runner._ml_full_dropout(X_170, n_dev, use_edge=True, rng=np.random.default_rng(405), rate=0.5)
    any_dropped = False
    for r in range(len(Xd)):
        blanked_60 = [d for d in range(n_dev) if np.isnan(Xd[r, d * n_per_dev])]
        blanked_edge = [d for d in range(n_dev) if np.isnan(Xd[r, n_dev * n_per_dev + 2 * d])]
        assert blanked_60 == blanked_edge
        assert len(blanked_60) in (0, 1)
        if blanked_60:
            any_dropped = True
            d0 = blanked_60[0]
            assert np.isnan(Xd[r, runner._ml_full_device_cols(d0, n_dev, True)]).all()
    assert any_dropped


# ---------------------------------------------------------------------------
# 3. Realistic results existence, quick_mode=False, Tier-1 SHA-256 & legacy integrity
# ---------------------------------------------------------------------------
def test_realistic_results_exist_full_run_and_tier1_sha256_matches():
    res_dir = ROOT / "results" / "hif_fusion_realistic"
    assert res_dir.is_dir(), f"Missing directory: {res_dir}"

    # Verify frozen Tier-1 model file SHA-256 matches lock exact hash.
    model = _load_frozen_tier1_model()
    assert model.n_params == he.EXPECTED_PARAMS == 417
    assert model.n_bytes == he.EXPECTED_BYTES == 504
    assert model.sha256 == EXPECTED_TIER1_SHA256 == he.FROZEN_MODEL_SHA256

    # Verify all 7 realistic result JSON files exist, are full runs (quick_mode=False), and simulation_only=True.
    loaded: dict[str, dict] = {}
    for fname in REALISTIC_RESULT_FILES:
        p = res_dir / fname
        assert p.is_file(), f"Missing realistic result file: {p}"
        data = json.loads(p.read_text(encoding="utf-8"))
        loaded[fname] = data
        assert data.get("simulation_only") is True, f"{fname}: expected simulation_only=True"
        assert data.get("realistic_mode") is True, f"{fname}: expected realistic_mode=True"
        assert data.get("quick_mode") is False, f"{fname}: expected quick_mode=False"

        # Published copy in docs/data/ must exist and match results/hif_fusion_realistic/.
        pub = ROOT / "docs" / "data" / f"hif_fusion_realistic_{fname}"
        assert pub.is_file(), f"Missing published copy: {pub}"
        assert _same_text(p, pub), f"Published copy {pub} differs from {p}"

    # Verify Tier-1 SHA-256 recorded across dataset_summary.json and summary.json.
    ds_sum = loaded["dataset_summary.json"]
    assert ds_sum["tier1_model_sha256"] == EXPECTED_TIER1_SHA256
    assert ds_sum["tier1_edge_model"]["sha256"] == EXPECTED_TIER1_SHA256
    for branch_key in ("passive_ieee123", "passive_ieee34", "active_ieee123", "active_ieee34"):
        assert ds_sum[branch_key]["model_sha256"] == EXPECTED_TIER1_SHA256
        assert ds_sum[branch_key]["realistic_mode"] is True

    summary = loaded["summary.json"]
    assert summary["tier1_model_sha256"] == EXPECTED_TIER1_SHA256
    assert summary["tier1_edge_model"]["sha256"] == EXPECTED_TIER1_SHA256
    for branch_key in ("passive_ieee123", "passive_ieee34", "active_ieee123", "active_ieee34", "conformal_hif"):
        assert summary["branch_status"][branch_key] == "COMPLETED"
    valid_verdicts = {"PASS", "PARTIAL", "FAIL", "NOT_RUN_YET"}
    for crit in ("R1", "R2", "R3", "R3a", "R3b", "R4"):
        assert summary["verdicts"][crit] in valid_verdicts

    # Provenance manifest for hif_fusion_realistic must exist and match every file's SHA-256.
    manifest_path = ROOT / "results" / "provenance" / "hif_fusion_realistic.json"
    assert manifest_path.is_file(), f"Missing provenance manifest: {manifest_path}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["producer"] == "hif_fusion_realistic"
    recorded_files = manifest["files"]
    assert len(recorded_files) == len(REALISTIC_RESULT_FILES)
    for fname in REALISTIC_RESULT_FILES:
        rel = f"results/hif_fusion_realistic/{fname}"
        assert rel in recorded_files
        assert _sha256_file(ROOT / rel) == recorded_files[rel]


def test_legacy_hif_fusion_results_completely_intact():
    legacy_dir = ROOT / "results" / "hif_fusion"
    legacy_manifest_path = ROOT / "results" / "provenance" / "hif_fusion.json"
    assert legacy_dir.is_dir() and legacy_manifest_path.is_file()

    manifest = json.loads(legacy_manifest_path.read_text(encoding="utf-8"))
    assert manifest["producer"] == "hif_fusion"
    recorded_files = manifest["files"]
    assert len(recorded_files) == len(LEGACY_RESULT_FILES)

    for fname in LEGACY_RESULT_FILES:
        rel = f"results/hif_fusion/{fname}"
        p = ROOT / rel
        assert p.is_file(), f"Legacy result file missing: {p}"
        assert rel in recorded_files
        assert _sha256_file(p) == recorded_files[rel], f"Legacy file modified: {rel}"

    # Global provenance verifier must pass with 0 changed, 0 missing, 0 unrecorded.
    v = provenance.verify()
    assert v["changed"] == [], f"Changed result files: {v['changed']}"
    assert v["missing"] == [], f"Missing result files: {v['missing']}"
    assert v["unrecorded"] == [], f"Unrecorded result files: {v['unrecorded']}"
    manifest_files = list((ROOT / "results" / "provenance").glob("*.json"))
    assert len(manifest_files) >= 24


# ---------------------------------------------------------------------------
# 4. Static verification of docs/index.html section 2d (Before/After + EN/VI honesty)
# ---------------------------------------------------------------------------
def test_dashboard_html_section_2d_before_after_and_bilingual_disclaimer():
    html_path = ROOT / "docs" / "index.html"
    assert html_path.is_file(), "docs/index.html missing"
    html = html_path.read_text(encoding="utf-8")

    # Section 2d (#hif-fusion) must contain the Branch-10 Before/After subsection (#hif-fusion-realistic).
    idx_2d = html.find('id="hif-fusion"')
    idx_real = html.find('id="hif-fusion-realistic"')
    assert idx_2d != -1, "Missing section 2d (id='hif-fusion') in docs/index.html"
    assert idx_real > idx_2d, "Missing Branch-10 subsection (id='hif-fusion-realistic') inside section 2d"

    # Extract the Branch-10 realistic block through the closing of its honest disclaimer box.
    idx_honest = html.find('class="hif-honest"', idx_real)
    assert idx_honest > idx_real, "Missing honest simulation disclaimer box (class='hif-honest') in section 2d"
    idx_section_end = html.find("</section>", idx_honest)
    assert idx_section_end > idx_honest
    real_block = html[idx_real:idx_section_end]

    # Must not show pending/placeholder text since full run completed.
    assert "Pending Branch-10 Run" not in real_block
    assert "Chờ chạy Nhánh 10" not in real_block
    assert "Not run yet (awaiting T-66)" not in real_block

    # Bilingual EN & VI Before/After heading and 3-stage column headers.
    assert "Before / After on Branch-10 Realistic Arcing" in real_block
    assert "Đối chứng Trước / Sau trên mô phỏng hồ quang chập chờn" in real_block
    assert "Clean 60 Hz" in real_block and "60 Hz sạch cũ" in real_block
    assert "Realistic 60 Hz" in real_block and "60 Hz thực tế" in real_block
    assert "Realistic + Edge" in real_block and "Thực tế + Edge" in real_block
    assert real_block.count("<table") >= 4, "Expected Before/After, arcing/surfaces, 1-sensor-offline, and 7-disturbance tables"

    # Verify numbers dynamically from results/metrics.json & results/hif_fusion_realistic/*.json.
    metrics = json.loads((ROOT / "results" / "metrics.json").read_text(encoding="utf-8"))
    p123 = json.loads((ROOT / "results" / "hif_fusion_realistic" / "passive_ieee123.json").read_text(encoding="utf-8"))
    summary = json.loads((ROOT / "results" / "hif_fusion_realistic" / "summary.json").read_text(encoding="utf-8"))

    pct1 = lambda x: f"{100.0 * float(x):.1f}%"
    base_metrics_400 = pct1(metrics["fault_location"]["ml_full"]["slg_by_resistance"]["400.0"])
    assert base_metrics_400 in real_block

    for mkey in ("ml_full", "per_node_gbdt", "zone_tree_gnn"):
        b400 = pct1(p123["ablations"]["60Hz_only"][mkey]["slg_by_resistance"]["400.0"])
        f400 = pct1(p123["ablations"]["60Hz_plus_edge"][mkey]["slg_by_resistance"]["400.0"])
        assert b400 in real_block, f"Missing realistic 60Hz SLG 400 value {b400} for {mkey} in section 2d"
        assert f400 in real_block, f"Missing realistic +Edge SLG 400 value {f400} for {mkey} in section 2d"

    # Pre-registered R1-R4 verdict chips must match summary.json verbatim.
    chips = re.findall(r'<span class="chip [^"]+">([^<]+)</span>', real_block)
    for crit, verdict in summary["verdicts"].items():
        assert f"{crit}: {verdict}" in chips, f"Missing verdict chip '{crit}: {verdict}' in section 2d (found {chips})"

    # Bilingual EN/VI honest simulation disclaimer must be present inside class="hif-honest".
    honest_slice = html[idx_honest:idx_section_end]
    assert 'data-l="en"' in honest_slice and 'data-l="vi"' in honest_slice
    assert "Honest simulation note (Branch 10 realistic HIF-Fusion)" in honest_slice
    assert "100% simulation" in honest_slice
    assert "Ghi chú trung thực (HIF-Fusion thực tế Nhánh 10)" in honest_slice
    assert "mô phỏng 100%" in honest_slice
    assert "Emanuel" in honest_slice and "VeHIF" in honest_slice


def test_open_switch_52a_interlock_prevents_noise_false_alarm():
    """IEEE C37.2 52a interlock: open switches (0 A + 1.5 LSB ADC noise) report (0.0, 0.0)."""
    model = _load_frozen_tier1_model()
    i_res_pre = np.array([8.0, 6.0, 0.0, 0.0], dtype=np.float64)
    di_res = np.array([4.0, 0.1, 0.0, 0.0], dtype=np.float64)
    is_closed = np.array([True, True, False, False], dtype=bool)
    for is_nf in (False, True):
        ef, info = hf.synthesize_event_edge(
            i_res_pre, di_res, is_closed, model, np.random.default_rng(77),
            is_arcing=not is_nf, is_nofault=is_nf,
            nofault_disturbance="none" if is_nf else None,
            surface="wet_grass" if not is_nf else None,
            arc_duty=0.8 if not is_nf else None,
            arc_path_mask=np.array([True, False, False, False], dtype=bool) if not is_nf else None,
        )
        assert ef[2, 0] == 0.0 and ef[2, 1] == 0.0
        assert ef[3, 0] == 0.0 and ef[3, 1] == 0.0
        assert info["device_disturbances"][2] == "open"
        assert info["device_disturbances"][3] == "open"


def test_kirchhoff_arc_path_masks_radial_and_looped():
    """Verify exact source-to-fault harmonic return path masks on radial trees and closed loops."""
    # IEEE 34-bus tree: parent = [-1, 0, 0, 2, 2, 3, 3] (D1..D7)
    parent = np.array([-1, 0, 0, 2, 2, 3, 3], dtype=np.int64)
    assert hf.passive_arc_path_mask(parent, 0).tolist() == [True, False, False, False, False, False, False]
    assert hf.passive_arc_path_mask(parent, 6).tolist() == [True, False, True, True, False, False, True]
    assert hf.passive_arc_path_mask(parent, 4).tolist() == [True, False, True, False, True, False, False]

    # Active graph with a closed loop 0-1-2-3-0 plus radial stub 3-4 and open switch 5:
    adj = np.zeros((6, 6), dtype=np.float32)
    for u, v in ((0, 1), (1, 2), (2, 3), (3, 0), (3, 4), (2, 5)):
        adj[u, v] = adj[v, u] = 1.0
    closed = np.array([True, True, True, True, True, False], dtype=bool)
    # Fault at node 2: both loop branches (0-1-2 and 0-3-2) carry arc return, stub 4 and open 5 do NOT.
    assert hf.active_arc_path_mask(adj, closed, 2).tolist() == [True, True, True, True, False, False]
    # Fault at stub 4: loop 0-1-2-3 + stub 4 all lie on simple paths 0->4, open 5 does NOT.
    assert hf.active_arc_path_mask(adj, closed, 4).tolist() == [True, True, True, True, True, False]

    # Healthy downstream switch (1.0 A pre-fault + 0.6 A linear voltage-sag shift, outside arc path)
    # must NOT receive fake nonlinear Emanuel arc injection (dramatically fewer false alarms than
    # unmasked arc injection on identical seeds).
    model = _load_frozen_tier1_model()
    i_res_pre = np.array([3.5, 1.0], dtype=np.float64)
    di_res = np.array([20.0, 0.6], dtype=np.float64)
    is_closed = np.array([True, True], dtype=bool)
    path_mask = np.array([True, False], dtype=bool)
    fa_masked, fa_unmasked = 0, 0
    for s in range(20):
        ef_m, info_m = hf.synthesize_event_edge(
            i_res_pre, di_res, is_closed, model, np.random.default_rng(500 + s),
            is_arcing=True, is_nofault=False, surface="concrete", arc_duty=1.0,
            arc_path_mask=path_mask,
        )
        ef_u, info_u = hf.synthesize_event_edge(
            i_res_pre, di_res, is_closed, model, np.random.default_rng(500 + s),
            is_arcing=True, is_nofault=False, surface="concrete", arc_duty=1.0,
            arc_path_mask=None,
        )
        if info_m["device_disturbances"][1] == "none" and ef_m[1, 1] > 0.5:
            fa_masked += 1
        if info_u["device_disturbances"][1] == "none" and ef_u[1, 1] > 0.5:
            fa_unmasked += 1
    assert fa_unmasked >= 10, f"Expected unmasked bug to false-alarm heavily, got {fa_unmasked}/20"
    assert fa_masked <= 3 and fa_masked < fa_unmasked, (
        f"Kirchhoff arc-path mask should cut healthy-switch false alarms ({fa_unmasked} -> {fa_masked})"
    )
