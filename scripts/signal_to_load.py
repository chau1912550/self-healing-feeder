"""How big is a line-to-ground fault current next to the load the feeder head already carries?

Replaces hand estimates in the transfer write-up with OpenDSS numbers. For each feeder, at nominal load
(load level 1.0, regulators free to move, then frozen for the fault), it reads the pre-fault current of the
feeder-head device (largest phase) and, for every SLG fault in the study zones at each resistance, the fault
current. It reports the median, min and max fault current and its share of the head current.

    .venv\\Scripts\\python scripts\\signal_to_load.py          # ~10 s

Writes results/transfer/signal_to_load.json with a run record. Simulation only.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import opendssdirect as dss

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shf import feeder, provenance, transfer  # noqa: E402

RESISTANCES = {"ieee123": [100.0, 400.0],
               "ieee34": [100.0, 400.0, 1000.0, 2500.0, 10000.0, 20000.0, 25000.0, 30000.0, 40000.0]}


def _fault_current() -> float:
    dss.Circuit.SetActiveElement("Fault.F")
    c = dss.CktElement.Currents()
    return float(abs(complex(c[0], c[1])))


def measure(name: str) -> dict:
    transfer.load_feeder(name)
    grid = transfer.study_grid() if name == "ieee123" else transfer.placement_rule(name)
    if name == "ieee123":
        feeder.set_normal_configuration()
    feeder.set_load_level(1.0)
    head = grid.devices[0]
    first = grid.members[head][0]
    feeder.cmd(f"New Fault.F phases=1 bus1={first}.1 bus2={first}.0 r=1 enabled=no")
    assert feeder.solve(controls=True), f"{name}: pre-fault power flow did not converge"
    m = feeder.device_measurement(grid.line[head])
    i_head = float(np.abs(m["i"]).max())
    dss.Circuit.SetActiveBus(m["bus"])
    kv_ln = float(dss.Bus.kVBase())

    out = {"head_device": head, "head_line": grid.line[head], "head_current_a": round(i_head, 1),
           "nominal_kv_ln": round(kv_ln, 3), "by_resistance": {}}
    buses = sorted({b for d in grid.devices for b in grid.members[d]})
    for r in RESISTANCES[name]:
        cur, n_fail = [], 0
        for b in buses:
            for p in feeder.bus_phases(b):
                feeder.cmd(f"Edit Fault.F phases=1 bus1={b}.{p} bus2={b}.0 r={r} enabled=yes")
                if feeder.solve(controls=False):
                    cur.append(_fault_current())
                else:
                    n_fail += 1
        feeder.cmd("Edit Fault.F enabled=no")
        a = np.array(cur)
        out["by_resistance"][str(r)] = {
            "faults": int(len(a)), "not_converged": n_fail,
            "fault_current_a": {"median": round(float(np.median(a)), 2), "min": round(float(a.min()), 2),
                                "max": round(float(a.max()), 2)},
            "share_of_head_current": {"median": round(float(np.median(a) / i_head), 4),
                                      "min": round(float(a.min() / i_head), 4),
                                      "max": round(float(a.max() / i_head), 4)},
        }
    return out


def main() -> None:
    t0 = time.time()
    res = {"simulation_only": True,
           "method": "nominal load (level 1.0); head current = largest phase of the feeder-head device before the "
                     "fault; one SLG fault per zone bus and phase, regulator taps frozen",
           "feeders": {n: measure(n) for n in ("ieee123", "ieee34")},
           "runtime_s": None}
    res["runtime_s"] = round(time.time() - t0, 1)
    transfer.SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    path = transfer.SUMMARY_DIR / "signal_to_load.json"
    path.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    provenance.record("signal_to_load", [path])
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
