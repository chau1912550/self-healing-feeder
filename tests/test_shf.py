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
