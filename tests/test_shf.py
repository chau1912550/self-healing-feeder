"""Sanity tests for the feeder model, zones, fault physics and restoration.

Run: python -m pytest -q
"""
import numpy as np
import pytest

from shf import baseline, config, faults, feeder, restoration, topology


@pytest.fixture(scope="module")
def zones():
    feeder.load_feeder()
    return topology.find_zones()


def test_base_case_matches_reference(zones):
    feeder.set_normal_configuration()
    assert feeder.solve(controls=True)
    # OpenDSS reference result for the IEEE 123-bus case is ~3.6 MW at the source
    assert 3550 < -feeder.dss.Circuit.TotalPower()[0] < 3680
    res = restoration.check_power_flow(zones, set(zones.names))
    assert res["ok"], res


def test_every_bus_in_exactly_one_zone(zones):
    seen = [b for z in zones.names for b in zones.members[z]]
    assert len(seen) == len(set(seen))
    assert abs(sum(zones.kw.values()) - 3490.0) < 1e-6   # every spot load counted once
    assert len(zones.names) == len(config.SECTIONALIZERS)


def test_normal_configuration_is_radial(zones):
    feeder.set_normal_configuration()
    assert not topology.closed_graph_has_loop()
    feeder.close_device("Sw7")
    assert topology.closed_graph_has_loop()   # closing a tie in normal state makes a loop
    feeder.set_normal_configuration()


def test_bolted_fault_current_flows_only_through_upstream_devices(zones):
    """A fault in zone L68 is fed through Sw1 -> Sw2 -> Sw4 -> L68. Those
    devices must see a large current rise; devices on other branches must not."""
    feeder.set_normal_configuration()
    feeder.solve(controls=True)
    pre = faults.snapshot()
    feeder.cmd("New Fault.T phases=3 bus1=99.1.2.3 bus2=99.0.0.0 r=0.01")
    feeder.solve(controls=False)
    post = faults.snapshot()
    feeder.cmd("Edit Fault.T enabled=no")
    feeder.solve(controls=True)
    rise = {d: np.abs(post[d]["i"]).max() - np.abs(pre[d]["i"]).max() for d in faults.DEVICES}
    for d in ("Sw1", "Sw2", "Sw4", "L68"):
        assert rise[d] > 2000, (d, rise[d])
    for d in ("Sw3", "L13", "L45", "L61", "L77", "Sw5"):
        assert rise[d] < 100, (d, rise[d])


def test_fpi_baseline_finds_bolted_three_phase_fault(zones, monkeypatch):
    monkeypatch.setattr(config, "SCENARIOS_PER_CASE", 1)
    df = faults.generate(zones, noise=False, verbose=False).query("ftype == '3PH' and r < 0.1")
    pred = baseline.predict(df, zones, baseline.pickups(faults.peak_load_currents()))
    assert (pred == df["zone"].to_numpy()).mean() > 0.95


@pytest.mark.parametrize("zf", list(config.SECTIONALIZERS))
def test_restoration_respects_limits_and_stays_radial(zones, zf):
    plan = restoration.plan_restoration(zones, zf)
    final = plan.checks[-1]
    assert final["converged"]
    assert final["radial"]
    assert final["vmin"] >= config.V_MIN_PU - config.V_TOL
    assert final["vmax"] <= config.V_MAX_PU + config.V_TOL
    assert not final["overloads"]
    assert zf not in plan.energized                  # faulted zone stays isolated
    assert len(plan.closed_ties) == len(set(plan.closed_ties))
    restoration.reset(zones)


# ---------------------------------------------------------------------------
# Hourly restoration study
# ---------------------------------------------------------------------------
def test_hourly_at_peak_matches_run_results(zones):
    """At LoadMult 1.0 the hourly study must reproduce run.py's restoration.csv."""
    import pandas as pd
    from shf import hourly
    ref = pd.read_csv(config.RESULTS / "restoration.csv")
    got = pd.DataFrame(hourly.plan_at(zones, 1.0))
    restoration.reset(zones)
    cols = ["fault_zone", "ties_closed", "restored_by_tie", "unserved_healthy", "kW_restored_by_tie",
            "power_flow_checks", "power_flow_rejected", "final_vmin_pu", "final_vmax_pu"]
    pd.testing.assert_frame_equal(got[cols], ref[cols], check_dtype=False)
    assert (got.power_flow_rejected <= got[[f"rejected_{r}" for r in restoration.REASONS]].sum(axis=1)).all()


def test_classify_labels_hand_built_checks():
    ok = {"converged": True, "vmin": 1.0, "vmax": 1.0, "overloads": []}
    assert restoration.classify(ok) == []
    assert restoration.classify({**ok, "vmin": 0.94}) == ["undervoltage"]
    assert restoration.classify({**ok, "vmax": 1.051}) == ["overvoltage"]
    assert restoration.classify({**ok, "vmax": 1.0504}) == []          # inside V_TOL
    assert restoration.classify({**ok, "vmin": 0.9, "overloads": [("L1", 700, 662)]}) == ["undervoltage", "overload"]
    assert restoration.classify({**ok, "converged": False, "vmin": 0.5}) == ["nonconverged"]


def test_load_shape_fixes_clock_changes_and_peaks_at_one(tmp_path):
    import pandas as pd
    from shf import hourly
    t = pd.date_range("2017-01-01 01:00", "2018-01-01 00:00", freq="h")   # hour-ending, like PJM
    mw = 10000 + 3000 * np.sin(np.arange(len(t)) / 24 * 2 * np.pi)
    df = pd.DataFrame({"Datetime": t, "AEP_MW": mw})
    df = df.drop(index=1600)                                   # spring-forward gap
    df = pd.concat([df, df.iloc[[7000]]])                      # fall-back duplicate
    df = df.sample(frac=1, random_state=0)                     # rows out of order
    p = tmp_path / "AEP_hourly.csv"
    df.to_csv(p, index=False)
    s, info = hourly.read_hourly(p, "AEP_MW")
    assert info["duplicates_averaged"] == 1 and info["missing_filled"] == 1 and info["missing_left"] == 0
    assert hourly.latest_full_year(s) == 2017
    shape = hourly.normalize(s, 2017)
    assert len(shape) == 8760 and shape["mult"].max() == pytest.approx(1.0)
    assert str(shape["datetime"].iloc[0]) == "2017-01-01 00:00:00"


def test_hours_map_to_grid_and_hold_window():
    import pandas as pd
    from shf import hourly
    assert list(hourly.to_level([0.123, 0.5, 0.996, 2.0])) == [0.3, 0.5, 1.0, 1.1]
    m = pd.Series([0.4, 0.5, 0.9, 0.6, 0.5, 0.4, 0.4, 0.4])
    held = hourly.held_mult(m, hours=3)
    assert list(held) == [0.9, 0.9, 0.9, 0.6, 0.5, 0.4, 0.4, 0.4]


# ---------------------------------------------------------------------------
# Realistic HIF arcing, per-zone loading + drift, and CT/PT noise model
# ---------------------------------------------------------------------------
def test_emanuel_fundamental_factor_matches_analytic_and_ltspice():
    import json
    assert faults.emanuel_fundamental_factor(0.0) == pytest.approx(1.0)
    assert faults.emanuel_fundamental_factor(1.0) == pytest.approx(0.0)
    k_p = faults.emanuel_fundamental_factor(0.30)
    k_n = faults.emanuel_fundamental_factor(0.33)
    assert k_p == pytest.approx(0.623838, abs=1e-5)
    assert k_n == pytest.approx(0.587586, abs=1e-5)
    kappa = 0.5 * (k_p + k_n)
    assert kappa == pytest.approx(0.605712, abs=1e-5)
    # Monotone decreasing on [0, 1]
    vals = [faults.emanuel_fundamental_factor(g) for g in np.linspace(0.0, 1.0, 11)]
    assert all(a > b for a, b in zip(vals, vals[1:]))
    with pytest.raises(ValueError):
        faults.emanuel_fundamental_factor(-0.01)
    with pytest.raises(ValueError):
        faults.emanuel_fundamental_factor(1.01)
    # Cross-check against the project's LTspice 2-diode simulation at bus 60 (400 ohm)
    spice_path = config.RESULTS / "spice" / "summary.json"
    if spice_path.exists():
        sp = json.loads(spice_path.read_text(encoding="utf-8"))
        c400 = sp["hif"]["cases"]["400"]
        ltspice_kappa = (c400["r_arc"] / c400["r_fault"]) * c400["i1_arc_vs_linear"]
        assert kappa == pytest.approx(ltspice_kappa, rel=2e-3)


def test_sample_arc_resistance_gating_and_distribution():
    rng = np.random.default_rng(123)
    # Non-arcing types and low-R SLG stay strictly linear
    for ftype, r in [("3PH", 0.01), ("LL", 2.0), ("LLG", 0.5), ("SLG", 0.01), ("SLG", 50.0)]:
        arc = faults.sample_arc_resistance(r, ftype, rng)
        assert arc["is_arcing"] is False
        assert arc["r_eff"] == pytest.approx(r)
        assert arc["arc_kappa"] == 1.0
        assert arc["arc_duty"] == 1.0
    # Arcing SLG >= 100 ohm: bounds, higher median R_eff, intermittent & continuous draws
    for r_nom in (100.0, 200.0, 400.0):
        draws = [faults.sample_arc_resistance(r_nom, "SLG", rng) for _ in range(400)]
        r_effs = np.array([d["r_eff"] for d in draws])
        duties = np.array([d["arc_duty"] for d in draws])
        kappas = np.array([d["arc_kappa"] for d in draws])
        assert all(d["is_arcing"] for d in draws)
        assert (r_effs >= 0.5 * r_nom).all()
        assert (r_effs <= config.HIF_R_EFF_MAX).all()
        assert np.median(r_effs) > 1.5 * r_nom
        assert (kappas > 0.25).all() and (kappas < 0.90).all()
        intermittent = duties < 1.0
        assert 0.30 < intermittent.mean() < 0.60
        assert (duties[intermittent] >= config.HIF_DUTY_RANGE[0]).all()
        assert (duties[intermittent] <= config.HIF_DUTY_RANGE[1]).all()


def test_zone_loading_independent_and_pre_post_drift(zones):
    base = feeder.base_loads()
    buses = feeder.load_buses(base)
    assert len(buses) == len(base)
    assert all(b in zones.bus_zone for b in buses)
    znames = list(zones.names)
    zidx = {z: i for i, z in enumerate(znames)}
    load_zone_idx = np.array([zidx[zones.bus_zone[b]] for b in buses], dtype=int)

    rng = np.random.default_rng(7)
    # Clean mode: zero drift
    pre_c, post_c = faults.sample_load_factors(load_zone_idx, len(znames), rng, realistic=False)
    np.testing.assert_array_equal(pre_c, post_c)

    # Realistic mode: independent zone spread + small pre-to-post drift
    zone_means = []
    drifts = []
    for _ in range(200):
        f_pre, f_post = faults.sample_load_factors(load_zone_idx, len(znames), rng, realistic=True)
        assert (f_pre >= config.SPOT_FACTOR_CLIP[0]).all() and (f_pre <= config.SPOT_FACTOR_CLIP[1]).all()
        ratio = f_post / f_pre
        assert (ratio >= config.LOAD_DRIFT_CLIP[0] - 1e-12).all()
        assert (ratio <= config.LOAD_DRIFT_CLIP[1] + 1e-12).all()
        assert not np.allclose(f_post, f_pre)
        drifts.append(ratio - 1.0)
        zone_means.append([f_pre[load_zone_idx == z].mean() for z in range(len(znames))])
    zm = np.array(zone_means)
    # Zones vary substantially and nearly independently across draws
    assert zm.std(axis=0).mean() > 0.22
    corr = np.corrcoef(zm.T)
    off_diag = corr[~np.eye(len(znames), dtype=bool)]
    assert np.abs(off_diag).mean() < 0.15
    d_all = np.concatenate(drifts)
    assert 0.012 < d_all.std() < 0.024


def test_ct_pt_bias_and_additive_noise_floor(monkeypatch):
    rng = np.random.default_rng(2026)
    bias = faults.sample_ct_pt_bias(["Sw1", "Sw2"], rng)
    for d in ("Sw1", "Sw2"):
        assert np.all(np.abs(np.abs(bias[d]["i"]) - 1.0) <= config.CT_BIAS_MAG_CLIP + 1e-12)
        assert np.all(np.abs(np.rad2deg(np.angle(bias[d]["i"]))) <= config.CT_BIAS_ANG_CLIP_DEG + 1e-12)
        assert np.all(np.abs(np.abs(bias[d]["v"]) - 1.0) <= config.PT_BIAS_MAG_CLIP + 1e-12)
        assert np.all(np.abs(np.rad2deg(np.angle(bias[d]["v"]))) <= config.PT_BIAS_ANG_CLIP_DEG + 1e-12)

    # Balanced 3-phase measurement: phase-independent CT bias creates non-zero spurious 3*I0
    # and stays identical between pre and post when random noise is disabled.
    bal_i = np.array([100.0 + 0j, 100.0 * feeder.A * feeder.A, 100.0 * feeder.A])
    bal_v = np.array([1.0 + 0j, 1.0 * feeder.A * feeder.A, 1.0 * feeder.A])
    clean = {"Sw1": {"i": bal_i.copy(), "v": bal_v.copy(), "i0": 0j, "i2": 0j, "bus": "150r"}}
    with monkeypatch.context() as mp:
        mp.setattr(config, "NOISE_MAG", 0.0)
        mp.setattr(config, "NOISE_ANG_DEG", 0.0)
        pre = faults._perturb(clean, rng, bias=bias, floor_i=0.0, floor_v=0.0)
        post = faults._perturb(clean, rng, bias=bias, floor_i=0.0, floor_v=0.0)
        np.testing.assert_allclose(pre["Sw1"]["i"], post["Sw1"]["i"])
        np.testing.assert_allclose(pre["Sw1"]["v"], post["Sw1"]["v"])
        assert abs(3 * pre["Sw1"]["i0"]) > 0.1

    # Additive noise floor: acts on energized phases (even at 0 A), never injects onto absent phase
    partial = {
        "Sw1": {
            "i": np.array([0.0 + 0j, 10.0 + 0j, 0.0 + 0j]),  # ph a energized unloaded, ph b loaded, ph c absent
            "v": np.array([1.0 + 0j, 1.0 + 0j, 0.0 + 0j]),
            "i0": 0j, "i2": 0j, "bus": "150r",
        }
    }
    # Legacy 2-arg call keeps zero-current phase at exact 0 (backward compatibility)
    legacy = faults._perturb(partial, np.random.default_rng(1))
    assert legacy["Sw1"]["i"][0] == 0j and legacy["Sw1"]["i"][2] == 0j and legacy["Sw1"]["v"][2] == 0j

    with monkeypatch.context() as mp:
        mp.setattr(config, "NOISE_MAG", 0.0)
        mp.setattr(config, "NOISE_ANG_DEG", 0.0)
        samples_ia, samples_va = [], []
        for _ in range(500):
            p = faults._perturb(partial, rng, floor_i=config.NOISE_I_FLOOR_A, floor_v=config.NOISE_V_FLOOR_PU)
            assert p["Sw1"]["i"][2] == 0j and p["Sw1"]["v"][2] == 0j   # absent phase untouched
            samples_ia.append(p["Sw1"]["i"][0])
            samples_va.append(p["Sw1"]["v"][0] - 1.0)
        rms_i = float(np.sqrt(np.mean(np.abs(samples_ia) ** 2)))
        rms_v = float(np.sqrt(np.mean(np.abs(samples_va) ** 2)))
        assert rms_i == pytest.approx(config.NOISE_I_FLOOR_A, rel=0.15)
        assert rms_v == pytest.approx(config.NOISE_V_FLOOR_PU, rel=0.15)


def test_realistic_generate_deterministic_and_clean_mode(zones, monkeypatch):
    import pandas as pd
    all_cases = faults.fault_cases(zones)
    # Representative subset covering multiple zones, all fault types, and low + arcing SLG resistances
    picked = []
    for target in [
        ("SLG", 0.01), ("SLG", 50), ("SLG", 100), ("SLG", 200), ("SLG", 400),
        ("LL", 0.01), ("LLG", 0.5), ("3PH", 0.01),
    ]:
        matches = [c for c in all_cases if (c["ftype"], c["r"]) == target]
        picked.extend(matches[:3])
    monkeypatch.setattr(config, "SCENARIOS_PER_CASE", 2)
    monkeypatch.setattr(faults, "fault_cases", lambda _z: picked)

    df1 = faults.generate(zones, noise=True, seed=42, verbose=False)
    df2 = faults.generate(zones, noise=True, seed=42, verbose=False)
    df3 = faults.generate(zones, noise=True, seed=99, verbose=False)
    pd.testing.assert_frame_equal(df1, df2)
    assert not np.allclose(df1["r_eff"].to_numpy(), df3["r_eff"].to_numpy())

    for col in ("r_eff", "is_arcing", "arc_kappa", "arc_duty"):
        assert col in df1.columns
    assert df1["converged"].all()
    expected_arc = (df1["ftype"] == "SLG") & (df1["r"] >= config.HIF_ARC_MIN_R)
    assert (df1["is_arcing"] == expected_arc).all()
    assert (df1.loc[~expected_arc, "r_eff"] == df1.loc[~expected_arc, "r"]).all()
    assert (df1.loc[expected_arc, "r_eff"] != df1.loc[expected_arc, "r"]).any()

    # noise=False keeps clean linear physics (no arc, no drift, no noise) and is deterministic
    dfc1 = faults.generate(zones, noise=False, seed=42, verbose=False)
    dfc2 = faults.generate(zones, noise=False, seed=42, verbose=False)
    pd.testing.assert_frame_equal(dfc1, dfc2)
    assert (~dfc1["is_arcing"]).all()
    assert (dfc1["r_eff"] == dfc1["r"]).all()
    assert (dfc1["arc_kappa"] == 1.0).all() and (dfc1["arc_duty"] == 1.0).all()

    # Circuit is cleanly restored after generate()
    assert feeder.solve(controls=True)
    assert 3550 < -feeder.dss.Circuit.TotalPower()[0] < 3680


def test_realistic_full_sweep_convergence(zones, monkeypatch):
    """One full realistic scenario across every bus/type/resistance must converge >= 99.5%."""
    monkeypatch.setattr(config, "SCENARIOS_PER_CASE", 1)
    df = faults.generate(zones, noise=True, seed=0, verbose=False)
    assert len(df) == 3816
    assert float(df["converged"].mean()) >= 0.995
    arc_rows = df[(df["ftype"] == "SLG") & (df["r"] >= config.HIF_ARC_MIN_R)]
    assert arc_rows["is_arcing"].all()
    assert float(arc_rows["r_eff"].median()) > float(arc_rows["r"].median())
    assert 3550 < -feeder.dss.Circuit.TotalPower()[0] < 3680
