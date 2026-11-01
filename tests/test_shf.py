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
