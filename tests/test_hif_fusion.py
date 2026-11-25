"""Unit and integration tests for Tier-1 Edge HIF-Sensor & OpenDSS fusion (research/hif-fusion/PLAN.md)."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import warnings

import numpy as np
import pytest
from scipy import signal

from shf import active_grid as ag, faults, feeder, hif_edge as he, hif_fusion as hf, transfer


def _make_dummy_edge_model(tmp_path: Path, seed: int = 123, threshold: float = 0.5) -> he.EdgeModel:
    """Create a deterministic 16->16->8->1 int8 EdgeModel (417 params / 504 bytes) saved as model_int8.npz."""
    rng = np.random.default_rng(seed)
    dims = [(16, 16), (16, 8), (8, 1)]
    layers = []
    for n_in, n_out in dims:
        w = rng.normal(0.0, 0.3, size=(n_in, n_out))
        s = float(np.abs(w).max() / 127.0)
        layers.append({
            "Wq": np.round(w / s).astype(np.int8),
            "scale": s,
            "b": rng.normal(0.0, 0.1, size=(n_out,)).astype(np.float32),
        })
    p = tmp_path / "model_int8.npz"
    he.save_model_npz(p, layers, threshold, pickups={"residual_overcurrent_51N": 48.3, "third_harmonic_level": 13.8})
    return he.load_model_npz(p, source="unit_test_dummy")


# ---------------------------------------------------------------------------
# 1. 4th-order Butterworth front-end cutoff (-3 dB) & 12-bit 15.36 kHz ADC
# ---------------------------------------------------------------------------
def test_butterworth_frontend_cutoff_and_adc_behavior():
    fc = he.cutoff_hz()
    # Exact Python front-end -3 dB cutoff is ~2047.9 Hz; LTspice UniversalOpAmp2 is 2045.1 Hz.
    assert abs(fc - 2047.9) < 0.5, f"unexpected Python -3 dB cutoff: {fc}"
    assert abs(fc - he.LTSPICE_CUTOFF_HZ) < 5.0
    assert he.FS_ADC == 15360.0 and he.N_CYCLE == 256 and he.ADC_BITS == 12

    # Check passband gain at 60 Hz and stopband attenuation at Nyquist (7,680 Hz) & FS_ADC (15,360 Hz).
    freqs_hz = np.array([60.0, 7680.0, 15360.0])
    _, h = signal.freqs([1.0], he.analog_den(), worN=2.0 * np.pi * freqs_hz)
    att_db = -20.0 * np.log10(np.abs(h))
    assert abs(att_db[0]) < 0.05                    # flat passband at 60 Hz
    assert 44.0 < att_db[1] < 49.0                  # ~46.4 dB at Nyquist
    assert 68.0 < att_db[2] < 74.0                  # ~70.6 dB at 15.36 kHz

    # 1-D vs batched 2-D sensing produces valid 12-bit codes and clips huge fault currents cleanly.
    t = he.standard_time_grid()
    wave_normal = 10.0 * np.sqrt(2.0) * np.sin(he.W * t)
    wave_bolted = 500.0 * np.sqrt(2.0) * np.sin(he.W * t)       # exceeds +/-100 A clamp
    codes_1d = he.sense(wave_normal, np.random.default_rng(7))
    assert codes_1d.dtype == np.int16 and codes_1d.shape == (he.N_SIM_SAMPLES // he.OVERSAMPLE,)
    assert int(codes_1d.min()) >= 0 and int(codes_1d.max()) <= 4095

    codes_2d = he.sense(np.stack([wave_normal, wave_bolted]), np.random.default_rng(7))
    assert codes_2d.shape == (2, he.N_SIM_SAMPLES // he.OVERSAMPLE)
    assert int(codes_2d.min()) >= 0 and int(codes_2d.max()) <= 4095
    assert int(codes_2d[1].max()) == 4095 and int(codes_2d[1].min()) == 0
    amps = he.codes_to_amps(codes_2d)
    assert np.isfinite(amps).all()


# ---------------------------------------------------------------------------
# 2. Exact numerical equivalence of 16 features & front end with hif-sensor repo
# ---------------------------------------------------------------------------
def _load_external_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_numerical_parity_with_hif_sensor_repo(tmp_path):
    hif_root = Path(os.environ.get("HIF_SENSOR_ROOT", Path(__file__).resolve().parent.parent.parent / "hif-sensor"))
    if not (hif_root / "hif" / "features.py").is_file():
        pytest.skip("Sibling hif-sensor repository not present in this environment")

    import sys

    sys.path.insert(0, str(hif_root))
    try:
        ext_frontend = importlib.import_module("hif.frontend")
        ext_features = importlib.import_module("hif.features")
        ext_waveforms = importlib.import_module("hif.waveforms")
        ext_train = importlib.import_module("train_kaggle")
    finally:
        sys.path.remove(str(hif_root))

    assert he.FEATURES == ext_features.FEATURES
    assert he.SURFACES == ext_waveforms.SURFACES
    assert he.DISTURBANCES == ext_waveforms.DISTURBANCES
    assert he.K == ext_features.K == 8
    assert abs(he.cutoff_hz() - ext_frontend.cutoff_hz()) < 1e-9

    # Bit-for-bit identical waveforms and 16 window features on both HIF and normal records.
    for is_hif, seed in ((True, 11), (False, 22)):
        amps_local, meta_local = he.make_event(np.random.default_rng(seed), is_hif=is_hif)
        amps_ext, meta_ext = ext_waveforms.make_event(np.random.default_rng(seed), is_hif=is_hif)
        assert meta_local == meta_ext
        assert np.allclose(amps_local, amps_ext, atol=1e-12, rtol=1e-12)

        X_local, ends_local = he.window_features(amps_local)
        X_ext, ends_ext = ext_features.window_features(amps_ext)
        assert X_local.shape == X_ext.shape == (53, 16)
        assert np.array_equal(ends_local, ends_ext)
        assert np.allclose(X_local, X_ext, atol=1e-6, rtol=1e-6)
        assert np.array_equal(he.window_labels(ends_local, meta_local), ext_features.window_labels(ends_ext, meta_ext))

    # Quantized int8 forward pass and persistence alarms match train_kaggle.py.
    model = _make_dummy_edge_model(tmp_path, seed=99)
    p_local = he.predict_q(model.layers, X_local)
    p_ext = ext_train.predict_q(model.layers, X_local)
    assert np.allclose(p_local, p_ext, atol=1e-6, rtol=1e-6)
    assert he.alarms(p_local, model.threshold) == ext_train.alarms(p_ext, model.threshold)


# ---------------------------------------------------------------------------
# 3. int8 model loading (417 params / 504 bytes), [0, 1] bounds & PERSIST=3
# ---------------------------------------------------------------------------
def test_int8_model_stats_inference_bounds_and_persist_logic(tmp_path):
    model = _make_dummy_edge_model(tmp_path, seed=7, threshold=0.65)
    assert model.n_params == he.EXPECTED_PARAMS == 417
    assert model.n_bytes == he.EXPECTED_BYTES == 504
    assert model.sha256 is not None and len(model.sha256) == 64
    assert all(L["Wq"].dtype == np.int8 for L in model.layers)
    assert model.pickups["residual_overcurrent_51N"] == pytest.approx(48.3)

    # Normal, random, and extreme-magnitude inputs stay finite in [0, 1] with zero overflow warnings.
    rng = np.random.default_rng(5)
    X_test = np.vstack([
        rng.normal(0.0, 2.0, size=(50, 16)),
        np.full((4, 16), 1e6),
        np.full((4, 16), -1e6),
        np.zeros((2, 16)),
    ]).astype(np.float32)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        probs = he.predict_q(model.layers, X_test)
    assert not caught, f"unexpected warnings during predict_q: {[str(w.message) for w in caught]}"
    assert probs.shape == (len(X_test),)
    assert np.isfinite(probs).all()
    assert float(probs.min()) >= 0.0 and float(probs.max()) <= 1.0

    # PERSIST = 3 equivalence: p_hif > thr iff >= 3 consecutive post-event windows exceed thr.
    ends = np.arange(7, 60, dtype=np.int16)
    start_cycle = 20
    # Case A: only 2 consecutive post-event windows above 0.65 -> must NOT trigger alarm.
    p_two = np.full(len(ends), 0.1, dtype=np.float32)
    p_two[20:22] = 0.95
    assert he.persisted_score(p_two, ends=ends, start_cycle=start_cycle) <= 0.65

    # Case B: 3 consecutive pre-event windows above 0.65 (ends < 20) -> post-event p_hif stays low.
    p_pre = np.full(len(ends), 0.1, dtype=np.float32)
    p_pre[0:4] = 0.95
    assert he.persisted_score(p_pre, ends=ends, start_cycle=start_cycle) <= 0.65

    # Case C: 3 consecutive post-event windows above 0.65 -> p_hif equals their min (> 0.65).
    p_three = np.full(len(ends), 0.1, dtype=np.float32)
    p_three[25:28] = [0.70, 0.92, 0.80]
    score = he.persisted_score(p_three, ends=ends, start_cycle=start_cycle)
    assert score == pytest.approx(0.70, abs=1e-6) and score > 0.65

    # Randomized equivalence check across 50 sequences.
    for _ in range(50):
        p_rand = rng.uniform(0.0, 1.0, size=len(ends))
        sc = he.persisted_score(p_rand, ends=ends, start_cycle=start_cycle, persist=he.PERSIST)
        # Check exact condition: exists k with ends[k] >= start_cycle and p[k-2], p[k-1], p[k] > thr.
        thr = model.threshold
        post_alarm = any(
            ends[k] >= start_cycle and (p_rand[k - 2] > thr and p_rand[k - 1] > thr and p_rand[k] > thr)
            for k in range(he.PERSIST - 1, len(ends))
        )
        assert (sc > thr) == post_alarm


# ---------------------------------------------------------------------------
# 4. All 5 Emanuel arc surfaces + 7 background disturbances
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("surface", list(he.SURFACES))
def test_all_5_emanuel_surfaces_generate_finite_features(surface, tmp_path):
    model = _make_dummy_edge_model(tmp_path)
    amps, meta = he.make_event(np.random.default_rng(101), is_hif=True, surface=surface, disturbance="none")
    assert meta["is_hif"] is True and meta["surface"] == surface and meta["arc_rms"] > 0.0
    assert amps.shape == (he.N_CYCLES * he.N_CYCLE,) and np.isfinite(amps).all()
    X, ends = he.window_features(amps)
    assert X.shape == (53, 16) and np.isfinite(X).all()
    p_hif, alarm = he.score_waveform(amps, model, start_cycle=meta["start_cycle"])
    assert 0.0 <= p_hif <= 1.0 and alarm in (0.0, 1.0)


@pytest.mark.parametrize("disturbance", list(he.DISTURBANCES))
def test_all_7_background_disturbances_generate_finite_features(disturbance, tmp_path):
    model = _make_dummy_edge_model(tmp_path)
    amps, meta = he.make_event(np.random.default_rng(202), is_hif=False, disturbance=disturbance)
    assert meta["is_hif"] is False and meta["disturbance"] == disturbance and meta["arc_rms"] == 0.0
    assert amps.shape == (he.N_CYCLES * he.N_CYCLE,) and np.isfinite(amps).all()
    X, _ = he.window_features(amps)
    assert X.shape == (53, 16) and np.isfinite(X).all()
    p_hif, alarm = he.score_waveform(amps, model, start_cycle=meta["start_cycle"])
    assert 0.0 <= p_hif <= 1.0 and alarm in (0.0, 1.0)


# ---------------------------------------------------------------------------
# 5. OpenDSS + Edge HIF-Sensor fusion on IEEE 123-bus & IEEE 34-bus (passive + active)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("feeder_name,hif_bus,hif_r", [
    ("ieee123", "60", 400.0),
    ("ieee34", "844", 2500.0),
])
def test_opendss_passive_fusion_no_nan_and_isolated_npz(feeder_name, hif_bus, hif_r, tmp_path):
    model = _make_dummy_edge_model(tmp_path, seed=13)
    transfer.load_feeder(feeder_name)
    grid = transfer.study_grid() if feeder_name == "ieee123" else transfer.placement_rule(feeder_name)
    if feeder_name == "ieee123":
        feeder.set_normal_configuration()
    struct = transfer.structure(grid)
    rng = np.random.default_rng(42)

    p0 = feeder.bus_phases(hif_bus)[0]
    feeder.cmd(f"New Fault.F phases=1 bus1={hif_bus}.{p0} bus2={hif_bus}.0 r={hif_r} enabled=no")
    assert feeder.solve(controls=True)
    pre_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
    pre = faults._perturb(pre_clean, rng)

    # Case 1: High-impedance SLG -> arcing HIF.
    feeder.cmd(f"Edit Fault.F phases=1 bus1={hif_bus}.{p0} bus2={hif_bus}.0 r={hif_r} enabled=yes")
    assert feeder.solve(controls=False)
    post_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
    post = faults._perturb(post_clean, rng)
    i_flt = hf.fault_current_rms("Fault.F")
    assert hf.is_arcing_hif("SLG", hif_r, i_flt) is True

    x_fused, info = hf.fuse_passive_event(
        grid, pre, post, struct, model, rng,
        ftype="SLG", r_ohm=hif_r, i_fault_a=i_flt, pre_clean=pre_clean, post_clean=post_clean,
    )
    assert x_fused.shape == (len(grid.devices), len(hf.PASSIVE_FUSED_FEATURES))
    assert x_fused.shape[1] == 23 and np.isfinite(x_fused).all()
    assert info["is_arcing"] is True and info["surface"] in he.SURFACES

    p_col = hf.PASSIVE_FUSED_FEATURES.index("p_hif")
    a_col = hf.PASSIVE_FUSED_FEATURES.index("hif_alarm")
    assert (x_fused[:, p_col] >= 0.0).all() and (x_fused[:, p_col] <= 1.0).all()
    assert set(np.unique(x_fused[:, a_col])).issubset({0.0, 1.0})

    # Physical current-division sanity: feeder head sees dI_res > 0.05 A on arcing SLG;
    # on IEEE 123-bus fault at bus 60, healthy sibling branch Sw3 (18-135) sees near-zero dI_res.
    assert info["di_res"][0] > hf.ARC_MIN_DEVICE_DI_RES_A
    if feeder_name == "ieee123":
        sw3_idx = grid.devices.index("Sw3")
        assert info["di_res"][sw3_idx] < 0.25

    # Stripping edge features recovers the exact 21-feature 60Hz-only tensor.
    x_60 = transfer.node_features(grid, pre, post, struct)
    assert np.allclose(hf.strip_edge_features(x_fused, "passive"), x_60, atol=1e-7)

    # Case 2: Bolted 3PH fault -> non-arcing, still finite.
    feeder.cmd(f"Edit Fault.F phases=3 bus1={hif_bus}.1.2.3 bus2={hif_bus}.0.0.0 r=0.01 enabled=yes")
    assert feeder.solve(controls=False)
    post_3ph_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
    post_3ph = faults._perturb(post_3ph_clean, rng)
    i_3ph = hf.fault_current_rms("Fault.F")
    assert hf.is_arcing_hif("3PH", 0.01, i_3ph) is False
    x_3ph, info_3ph = hf.fuse_passive_event(
        grid, pre, post_3ph, struct, model, rng,
        ftype="3PH", r_ohm=0.01, i_fault_a=i_3ph, pre_clean=pre_clean, post_clean=post_3ph_clean,
    )
    assert np.isfinite(x_3ph).all() and info_3ph["is_arcing"] is False and info_3ph["surface"] == "none"
    feeder.cmd("Edit Fault.F enabled=no")

    # End-to-end isolated export to tmp_path and reload.
    npz_out = tmp_path / f"hif_fusion_passive_{feeder_name}.npz"
    summary = hf.sweep_passive_fusion(
        feeder_name, model, seed=0, scenarios=1, max_cases=3, out_path=npz_out, verbose=False,
    )
    assert npz_out.is_file() and summary["events_total"] == 3 and summary["converged"] == 3
    ds = hf.load_passive_fusion_dataset(feeder_name, path=npz_out)
    assert ds.X.shape == (3, len(grid.devices), 23) and np.isfinite(ds.X).all()
    assert ds.X_60hz.shape == (3, len(grid.devices), 21) and np.isfinite(ds.X_60hz).all()
    assert ds.features == hf.PASSIVE_FUSED_FEATURES


@pytest.mark.parametrize("feeder_name", ["ieee123", "ieee34"])
def test_opendss_active_fusion_topologies_7_disturbances_and_isolated_npz(feeder_name, tmp_path):
    model = _make_dummy_edge_model(tmp_path, seed=19)
    npz_out = tmp_path / f"hif_fusion_active_{feeder_name}.npz"
    summary = hf.sweep_active_fusion(
        feeder_name,
        model,
        seed=1,
        scenarios_per_topo=1,
        max_cases=2,
        max_nofault_per_topo=15,
        out_path=npz_out,
        verbose=False,
    )
    assert npz_out.is_file() and summary["converged"] == summary["events_total"]
    ds = hf.load_active_fusion_dataset(feeder_name, path=npz_out)
    n_topos = len(ag.TOPOLOGIES[feeder_name])
    assert ds.X.shape == (n_topos * (2 + 15), len(ds.devices), 28)
    assert np.isfinite(ds.X).all()
    assert ds.features == hf.ACTIVE_FUSED_FEATURES
    assert ds.X_60hz.shape == (ds.X.shape[0], ds.X.shape[1], 26)

    p_col = hf.ACTIVE_FUSED_FEATURES.index("p_hif")
    a_col = hf.ACTIVE_FUSED_FEATURES.index("hif_alarm")
    assert (ds.X[:, :, p_col] >= 0.0).all() and (ds.X[:, :, p_col] <= 1.0).all()
    assert set(np.unique(ds.X[:, :, a_col])).issubset({0.0, 1.0})

    # Verify all 7 background disturbances appear in NO_FAULT events!
    nf_mask = ds.y == ds.nofault_class
    assert int(nf_mask.sum()) == n_topos * 15
    seen_dists = set(ds.edge_disturbance[nf_mask].tolist())
    assert seen_dists == set(he.DISTURBANCES), f"missing NO_FAULT disturbances: {set(he.DISTURBANCES) - seen_dists}"


# ---------------------------------------------------------------------------
# 6. Offline sensor blanking (blanks BOTH 60 Hz phasors AND edge p_hif/hif_alarm)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("branch,n_feat,n_live", [
    ("passive", 23, hf.N_PASSIVE_FUSED_ELEC),
    ("active", 28, hf.N_ACTIVE_FUSED_ELEC),
])
def test_offline_sensor_blanking_blanks_60hz_and_edge_jointly(branch, n_feat, n_live):
    rng = np.random.default_rng(77)
    X = rng.uniform(0.0, 1.0, size=(20, 6, n_feat)).astype(np.float32)
    feats = hf.PASSIVE_FUSED_FEATURES if branch == "passive" else hf.ACTIVE_FUSED_FEATURES
    p_idx = feats.index("p_hif")
    a_idx = feats.index("hif_alarm")
    assert p_idx < n_live and a_idx < n_live

    # Single-sensor blanking on node 2.
    Xb = hf.blank_fused_sensor(X, node=2, branch=branch)
    assert np.isnan(Xb[:, 2, :n_live]).all()
    assert np.isnan(Xb[:, 2, p_idx]).all() and np.isnan(Xb[:, 2, a_idx]).all()
    assert np.isfinite(Xb[:, 2, n_live:]).all()
    assert np.array_equal(Xb[:, 2, n_live:], X[:, 2, n_live:])
    for other in (0, 1, 3, 4, 5):
        assert np.array_equal(Xb[:, other, :], X[:, other, :])

    # Training sensor dropout blanks at most one node per event (both 60 Hz + edge).
    Xd = hf.apply_fused_sensor_dropout(X, np.random.default_rng(88), branch=branch, rate=0.5)
    assert np.isfinite(Xd[:, :, n_live:]).all()
    dropped_nodes_per_event = np.isnan(Xd[:, :, p_idx]).sum(axis=1)
    assert ((dropped_nodes_per_event == 0) | (dropped_nodes_per_event == 1)).all()
    assert dropped_nodes_per_event.sum() > 0


# ---------------------------------------------------------------------------
# 7. Parallel edge synthesis matches serial execution bit-for-bit
# ---------------------------------------------------------------------------
def test_parallel_edge_synthesis_matches_serial(tmp_path):
    model = _make_dummy_edge_model(tmp_path, seed=31)
    rng = np.random.default_rng(55)
    n_ev, n_dev = 36, 4
    i_res_pre = rng.uniform(1.0, 15.0, size=(n_ev, n_dev)).astype(np.float32)
    di_res = rng.uniform(0.0, 10.0, size=(n_ev, n_dev)).astype(np.float32)
    is_closed = np.ones((n_ev, n_dev), dtype=bool)
    is_closed[0, 1] = False
    is_arcing = np.arange(n_ev) % 2 == 0
    is_nofault = np.arange(n_ev) % 6 == 5
    is_arcing[is_nofault] = False
    nf_dist = [he.DISTURBANCES[i % len(he.DISTURBANCES)] if is_nofault[i] else None for i in range(n_ev)]
    nf_kind = ["load_step" if is_nofault[i] else None for i in range(n_ev)]

    e1, s1, d1 = hf._run_edge_synthesis_batch(
        i_res_pre, di_res, is_closed, is_arcing, is_nofault, nf_dist, nf_kind,
        model=model, seed=9, n_workers=1, verbose=False,
    )
    e2, s2, d2 = hf._run_edge_synthesis_batch(
        i_res_pre, di_res, is_closed, is_arcing, is_nofault, nf_dist, nf_kind,
        model=model, seed=9, n_workers=2, verbose=False,
    )
    assert np.array_equal(e1, e2)
    assert np.array_equal(s1, s2)
    assert np.array_equal(d1, d2)
