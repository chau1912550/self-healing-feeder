"""Active, reconfigurable distribution grid fault & transient simulator (research/active-grid-gnn/PLAN.md).

Extends the passive radial transfer study with four open IEEE PES distribution-grid challenges:
  1. Current-limited Inverter-Based DERs (OpenDSS Generator Model=7, 0% to 50% penetration),
     injecting bidirectional pre-fault and fault currents.
  2. Dynamic network reconfiguration and closed-loop (non-tree) topologies via tie switches.
  3. Voltage-normalized High-Impedance Faults (SLG up to 400 ohm at 4.16 kV, up to 10,000 ohm at 24.9 kV).
  4. Non-fault operational distractors (class = NO_FAULT): capacitor switching, sudden PV cloud drops,
     and large spot-load steps, to test nuisance-trip rejection alongside fault location.

Every event is stored as a general dynamic graph (no fixed parent-child tree assumption):
  - X          : (E, N, 26) feeder-independent relative + directional node features
  - topo_id    : (E,) index into per-topology active adjacency `adj` (T, N, N) and `is_tie` (T, N, N)
  - y          : (E,) faulted zone index 0..N-1, or N for NO_FAULT

Simulation only. Nothing here is field data.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import opendssdirect as dss

from . import config, faults, feeder, transfer

ACTIVE_SUMMARY_DIR = config.RESULTS / "active_grid"

# ASSUMPTION: distributed 3-phase inverter-based DERs (OpenDSS Model=7 current-limited inverter).
DER_SPECS: dict[str, dict[str, Any]] = {
    "ieee123": {"kv": 4.16, "buses": ["48", "65", "76", "105"], "nominal_kw": 3490.0},
    "ieee34":  {"kv": 24.9, "buses": ["828", "844", "840"],     "nominal_kw": 2000.0},
}

# ASSUMPTION: adjacent 24.9 kV feeder behind a normally-open tie switch at bus 840 (zone D6) on IEEE 34-bus,
# mirroring Sw9 (450-fdr2) on IEEE 123-bus so both feeders support back-fed reconfiguration and closed loops.
IEEE34_ADJACENT_DSS = [
    "New Vsource.Fdr34Adj bus1=adj34src basekv=24.9 pu=1.02 phases=3 R1=0.5 X1=2.0 R0=0.5 X0=2.0",
    "New Line.Adj34Trunk phases=3 bus1=adj34src bus2=adj34 r1=0.3 x1=0.4 r0=0.8 x0=1.2 length=2.0 units=mi",
    "New Line.Tie34 phases=3 bus1=840 bus2=adj34 switch=yes r1=1e-3 r0=1e-3 x1=0 x0=0 c1=0 c0=0 length=0.001",
    "Open Line.Tie34 term=2",
]

# Voltage-normalized fault resistances (matching R / Z_base physical difficulty across 4.16 kV and 24.9 kV).
SLG_R_BY_FEEDER: dict[str, list[float]] = {
    "ieee123": [0.01, 1.0, 5.0, 10.0, 25.0, 50.0, 100.0, 200.0, 400.0],
    "ieee34":  [0.01, 5.0, 25.0, 100.0, 400.0, 1000.0, 2500.0, 5000.0, 10000.0],
}
PHASE_R_BY_FEEDER: dict[str, list[float]] = {
    "ieee123": [0.01, 0.5, 2.0],
    "ieee34":  [0.01, 2.0, 10.0],
}

DER_PEN_RANGE = (0.0, 0.50)                # ASSUMPTION: feeder-wide DER penetration 0%..50% of nominal load

ACTIVE_FEATURES = [
    "dIa", "dIb", "dIc", "Ia", "Ib", "Ic", "dI0", "dI2",
    "Va", "Vb", "Vc", "dVa", "dVb", "dVc", "has_a", "has_b", "has_c",
    "cos_vi_post", "cos_vi_pre", "cos_di_vpre", "power_rev",
    "is_closed", "active_deg", "share_own", "der_ratio", "is_source_adj",
]
N_ACTIVE_ELEC = 21                         # indices 0..20 depend on live sensor readings; 21..25 are grid state


@dataclass
class TopoSpec:
    name: str
    open_devices: tuple[str, ...]          # sectionalizer device names opened in this topology
    closed_ties: tuple[str, ...]           # tie line names closed in this topology
    tie_zone_links: tuple[tuple[str, str], ...]   # extra zone-to-zone links created by closed internal ties
    extra_source_zones: tuple[str, ...]    # zones directly fed by an external tie source when tie is closed
    is_looped: bool


TOPOLOGIES: dict[str, list[TopoSpec]] = {
    "ieee123": [
        TopoSpec("normal",       (),       (),       (),               (),       False),
        TopoSpec("reconfig_sw7", ("Sw2",), ("Sw7",), (("L45", "Sw5"),), (),       False),
        TopoSpec("reconfig_sw9", ("Sw4",), ("Sw9",), (),               ("L68",), False),
        TopoSpec("looped_sw7",   (),       ("Sw7",), (("L45", "Sw5"),), (),       True),
    ],
    "ieee34": [
        TopoSpec("normal",       (),       (),         (), (),      False),
        TopoSpec("reconfig_tie", ("D4",),  ("Tie34",), (), ("D6",), False),
        TopoSpec("looped_tie",   (),       ("Tie34",), (), ("D6",), True),
    ],
}


def load_active_feeder(name: str) -> tuple[transfer.Grid, list[str], list[str]]:
    """Compile feeder, attach adjacent tie (for ieee34) and Model=7 DERs (initially 0 kW).

    Returns (grid, der_names, cap_names).
    """
    transfer.load_feeder(name)
    grid = transfer.study_grid() if name == "ieee123" else transfer.placement_rule(name)
    if name == "ieee123":
        feeder.set_normal_configuration()
    elif name == "ieee34":
        for line in IEEE34_ADJACENT_DSS:
            feeder.cmd(line)
        feeder.cmd("CalcVoltageBases")
    else:
        raise ValueError(f"unsupported feeder: {name}")

    spec = DER_SPECS[name]
    der_names = []
    for k, bus in enumerate(spec["buses"]):
        gname = f"DER_{k + 1}"
        feeder.cmd(f"New Generator.{gname} bus1={bus} phases=3 kv={spec['kv']} kw=0.001 pf=1 "
                   "model=7 vmaxpu=1.15 vminpu=0.80 enabled=no")
        der_names.append(gname)

    caps = list(dss.Capacitors.AllNames())
    feeder.solve(controls=True)
    return grid, der_names, caps


def set_topology(name: str, grid: transfer.Grid, topo: TopoSpec) -> None:
    """Apply switch and tie states for `topo`."""
    all_ties = list(config.TIES) if name == "ieee123" else ["Tie34"]
    for d in grid.devices:
        ln = grid.line[d]
        if d in topo.open_devices:
            feeder.cmd(f"Open Line.{ln} term=1")
        else:
            feeder.cmd(f"Close Line.{ln} term=1")
            feeder.cmd(f"Close Line.{ln} term=2")
    for t in all_ties:
        if t in topo.closed_ties:
            feeder.cmd(f"Close Line.{t} term=1")
            feeder.cmd(f"Close Line.{t} term=2")
        else:
            feeder.cmd(f"Open Line.{t} term=2")
    if name == "ieee123":
        feeder.cmd("Open Line.Sw8 term=2")


def set_der_kw(der_names: list[str], kws: np.ndarray) -> None:
    """Set each inverter DER output (kW). Generators <= 0.1 kW are disabled cleanly."""
    for name, kw in zip(der_names, kws):
        if kw > 0.1:
            feeder.cmd(f"Edit Generator.{name} kw={float(kw):.2f} enabled=yes")
        else:
            feeder.cmd(f"Edit Generator.{name} kw=0.001 enabled=no")


def build_topology_matrices(grid: transfer.Grid, topos: list[TopoSpec]) -> tuple[np.ndarray, np.ndarray]:
    """Return (adj, is_tie) arrays of shape (T, N, N) float32 for all topologies of a feeder."""
    n = len(grid.devices)
    idx = {d: i for i, d in enumerate(grid.devices)}
    adj = np.zeros((len(topos), n, n), dtype=np.float32)
    is_tie = np.zeros((len(topos), n, n), dtype=np.float32)
    for ti, topo in enumerate(topos):
        for d in grid.devices:
            p = grid.parent[d]
            if p is not None and d not in topo.open_devices:
                u, v = idx[p], idx[d]
                adj[ti, u, v] = adj[ti, v, u] = 1.0
        for a, b in topo.tie_zone_links:
            u, v = idx[a], idx[b]
            adj[ti, u, v] = adj[ti, v, u] = 1.0
            is_tie[ti, u, v] = is_tie[ti, v, u] = 1.0
    return adj, is_tie


def _phase_cos(v: np.ndarray, i: np.ndarray, has: np.ndarray) -> float:
    """Average cos(angle(I) - angle(V)) across energized phases (real-power flow direction in [-1, 1])."""
    vals = []
    for k in range(3):
        if has[k] and abs(v[k]) > 1e-6 and abs(i[k]) > 1e-4:
            vals.append(float(np.real(v[k] * np.conj(i[k])) / (abs(v[k]) * abs(i[k]))))
    return float(np.mean(vals)) if vals else 0.0


def active_node_features(grid: transfer.Grid, topo: TopoSpec, adj_t: np.ndarray,
                         pre: dict[str, dict], post: dict[str, dict],
                         der_kw_by_zone: dict[str, float]) -> np.ndarray:
    """Build (N, 26) feeder-independent relative + directional features for an active-grid event."""
    # Reference floor from the largest pre-fault current among closed source-adjacent devices.
    source_devs = [grid.devices[0], *topo.extra_source_zones]
    head_max = max((np.abs(pre[d]["i"]).max() for d in source_devs if d in pre), default=1e-6)
    floor = 0.05 * max(float(head_max), 1e-6)
    total_kw = sum(grid.kw.values()) or 1.0
    deg = adj_t.sum(axis=1)

    rows = []
    for k, d in enumerate(grid.devices):
        m, p = post[d], pre[d]
        base = max(float(np.abs(p["i"]).max()), floor)
        has = np.abs(p["v"]) > 0.1
        di_vec = m["i"] - p["i"]

        # Directional phasor features: distinguish forward vs reverse DER / back-fed flows.
        cos_post = _phase_cos(m["v"], m["i"], has)
        cos_pre = _phase_cos(p["v"], p["i"], has)
        dom = int(np.argmax(np.abs(di_vec)))
        if has[dom] and abs(p["v"][dom]) > 1e-6 and abs(di_vec[dom]) > 1e-4:
            cos_di = float(np.real(p["v"][dom] * np.conj(di_vec[dom]))
                           / (abs(p["v"][dom]) * abs(di_vec[dom])))
        else:
            cos_di = 0.0
        power_rev = 1.0 if (cos_pre * cos_post < -0.05) else 0.0

        is_closed = 0.0 if d in topo.open_devices else 1.0
        share_own = grid.kw[d] / total_kw
        der_ratio = min(der_kw_by_zone.get(d, 0.0) / max(grid.kw[d], 20.0), 3.0)
        is_src = 1.0 if (k == 0 or d in topo.extra_source_zones) else 0.0

        row = list(np.log1p(np.abs(di_vec) / base)) + list(np.log1p(np.abs(m["i"]) / base))
        row += [float(np.log1p(abs(m["i0"] - p["i0"]) / base)),
                float(np.log1p(abs(m["i2"] - p["i2"]) / base))]
        row += list(np.abs(m["v"]) * has) + list((np.abs(m["v"]) - np.abs(p["v"])) * has)
        row += list(has.astype(float))
        row += [cos_post, cos_pre, cos_di, power_rev]
        row += [is_closed, float(deg[k]), float(share_own), float(der_ratio), is_src]
        rows.append(row)
    return np.array(rows, dtype=np.float32)


def active_fault_cases(name: str, grid: transfer.Grid) -> list[dict]:
    """Fault cases with voltage-normalized resistance grid for `name`."""
    slg_rs = SLG_R_BY_FEEDER[name]
    ph_rs = PHASE_R_BY_FEEDER[name]
    cases = []
    for zone, buses in grid.members.items():
        for bus in buses:
            ph = feeder.bus_phases(bus)
            for p in ph:
                for r in slg_rs:
                    cases.append(dict(bus=bus, zone=zone, ftype="SLG", phases=f"{p}", r=r,
                                      spec=f"phases=1 bus1={bus}.{p} bus2={bus}.0 r={r}"))
            for p, q in faults.PAIRS:
                if p in ph and q in ph:
                    for r in ph_rs:
                        cases.append(dict(bus=bus, zone=zone, ftype="LL", phases=f"{p}{q}", r=r,
                                          spec=f"phases=1 bus1={bus}.{p} bus2={bus}.{q} r={r}"))
                        cases.append(dict(bus=bus, zone=zone, ftype="LLG", phases=f"{p}{q}", r=r,
                                          spec=f"phases=2 bus1={bus}.{p}.{q} bus2={bus}.0.0 r={r}"))
            if ph == [1, 2, 3]:
                for r in ph_rs:
                    cases.append(dict(bus=bus, zone=zone, ftype="3PH", phases="123", r=r,
                                      spec=f"phases=3 bus1={bus}.1.2.3 bus2={bus}.0.0.0 r={r}"))
    return cases


def sweep_active(name: str, *, seed: int = 0, scenarios_per_topo: int = 1,
                 nofault_share: float = 0.15, out_path: Path | None = None,
                 verbose: bool = True) -> dict[str, Any]:
    """Simulate active-grid faults (across all topologies + 0-50% DER) and NO_FAULT operational transients."""
    t0 = time.time()
    grid, der_names, caps = load_active_feeder(name)
    topos = TOPOLOGIES[name]
    adj, is_tie = build_topology_matrices(grid, topos)
    cases = active_fault_cases(name, grid)
    base = feeder.base_loads()
    spec = DER_SPECS[name]
    bus_zone = grid.bus_zone
    dev_index = {d: i for i, d in enumerate(grid.devices)}
    der_zones = [bus_zone[b] for b in spec["buses"]]
    n_dev = len(grid.devices)
    nofault_label = n_dev

    first = grid.members[grid.devices[0]][0]
    feeder.cmd(f"New Fault.F phases=1 bus1={first}.1 bus2={first}.0 r=1 enabled=no")

    rng = np.random.default_rng(seed)

    def snap():
        clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
        return faults._perturb(clean, rng)

    def random_operating_point():
        mult = float(rng.uniform(*config.LOAD_MULT_RANGE))
        spread = np.clip(rng.normal(1.0, config.LOAD_SPREAD, len(base)), 0.3, 1.7)
        feeder.scale_loads(base, spread)
        feeder.set_load_level(mult)
        pen = float(rng.uniform(*DER_PEN_RANGE))
        w = np.clip(rng.normal(1.0, 0.25, len(der_names)), 0.1, 1.5)
        w = w / w.sum()
        der_kws = pen * spec["nominal_kw"] * w
        set_der_kw(der_names, der_kws)
        # Reset capacitors to enabled before pre-fault snapshot.
        for cname in caps:
            feeder.cmd(f"Edit Capacitor.{cname} enabled=yes")
        dz: dict[str, float] = {}
        for z, kw in zip(der_zones, der_kws):
            dz[z] = dz.get(z, 0.0) + float(kw)
        return mult, spread, pen, der_kws, dz

    X_list, y_list, topo_list = [], [], []
    bus_list, ftype_list, r_list, der_list, kind_list, conv_list = [], [], [], [], [], []

    n_fault_per_topo = scenarios_per_topo * len(cases)
    n_nf_per_topo = max(30, int(round(n_fault_per_topo * nofault_share / (1.0 - nofault_share))))

    for ti, topo in enumerate(topos):
        set_topology(name, grid, topo)

        # --- Fault events ---
        for _ in range(scenarios_per_topo):
            for c in cases:
                _, _, pen, _, dz = random_operating_point()
                feeder.cmd("Edit Fault.F enabled=no")
                ok_pre = feeder.solve(controls=True)
                pre = snap()
                feeder.cmd(f"Edit Fault.F {c['spec']} enabled=yes")
                ok_post = feeder.solve(controls=False)
                post = snap()

                X_list.append(active_node_features(grid, topo, adj[ti], pre, post, dz))
                y_list.append(dev_index[bus_zone[c["bus"]]])
                topo_list.append(ti)
                bus_list.append(c["bus"].lower())
                ftype_list.append(c["ftype"])
                r_list.append(float(c["r"]))
                der_list.append(pen)
                kind_list.append("fault")
                conv_list.append(bool(ok_pre and ok_post))

        # --- Non-fault operational transients (cap switch, PV cloud drop, load step) ---
        feeder.cmd("Edit Fault.F enabled=no")
        nf_kinds = ("cap_switch", "pv_cloud", "load_step")
        for nfi in range(n_nf_per_topo):
            kind = nf_kinds[nfi % len(nf_kinds)]
            mult, spread, pen, der_kws, dz = random_operating_point()
            if kind == "cap_switch" and caps:
                cname = caps[int(rng.integers(0, len(caps)))]
                start_on = bool(rng.random() < 0.5)
                feeder.cmd(f"Edit Capacitor.{cname} enabled={'yes' if start_on else 'no'}")
                ok_pre = feeder.solve(controls=True)
                pre = snap()
                feeder.cmd(f"Edit Capacitor.{cname} enabled={'no' if start_on else 'yes'}")
                ok_post = feeder.solve(controls=False)
                post = snap()
                feeder.cmd(f"Edit Capacitor.{cname} enabled=yes")
            elif kind == "pv_cloud":
                # Ensure noticeable PV generation before a cloud drop (pen >= 10%).
                if pen < 0.10:
                    pen = float(rng.uniform(0.15, DER_PEN_RANGE[1]))
                    w = np.clip(rng.normal(1.0, 0.25, len(der_names)), 0.1, 1.5)
                    der_kws = pen * spec["nominal_kw"] * (w / w.sum())
                    set_der_kw(der_names, der_kws)
                    dz = {}
                    for z, kw in zip(der_zones, der_kws):
                        dz[z] = dz.get(z, 0.0) + float(kw)
                ok_pre = feeder.solve(controls=True)
                pre = snap()
                # Sudden 50-85% cloud drop across DERs.
                drop = rng.uniform(0.15, 0.50, size=len(der_names))
                set_der_kw(der_names, der_kws * drop)
                ok_post = feeder.solve(controls=False)
                post = snap()
            else:
                # Sudden +30% to +80% step on 1..4 random spot loads.
                ok_pre = feeder.solve(controls=True)
                pre = snap()
                spread2 = spread.copy()
                pick = rng.choice(len(base), size=min(len(base), int(rng.integers(1, 5))), replace=False)
                spread2[pick] *= rng.uniform(1.30, 1.80, size=len(pick))
                feeder.scale_loads(base, spread2)
                ok_post = feeder.solve(controls=False)
                post = snap()

            X_list.append(active_node_features(grid, topo, adj[ti], pre, post, dz))
            y_list.append(nofault_label)
            topo_list.append(ti)
            bus_list.append(f"nf_{ti}_{nfi}")
            ftype_list.append("NO_FAULT")
            r_list.append(-1.0)
            der_list.append(pen)
            kind_list.append(kind)
            conv_list.append(bool(ok_pre and ok_post))

        if verbose:
            print(f"  active {name} topo '{topo.name}' ({ti + 1}/{len(topos)}): "
                  f"{n_fault_per_topo} faults + {n_nf_per_topo} non-faults [{time.time() - t0:.1f}s]")

    # Cleanly restore base circuit state.
    feeder.cmd("Edit Fault.F enabled=no")
    set_der_kw(der_names, np.zeros(len(der_names)))
    set_topology(name, grid, topos[0])
    feeder.scale_loads(base, np.ones(len(base)))
    feeder.set_load_level(1.0)

    out_dir = transfer.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    npz_path = out_path or (out_dir / f"active_{name}.npz")
    conv = np.array(conv_list, dtype=bool)
    np.savez_compressed(
        npz_path,
        X=np.stack(X_list),
        y=np.array(y_list, dtype=np.int64),
        topo_id=np.array(topo_list, dtype=np.int64),
        adj=adj,
        is_tie=is_tie,
        topo_names=np.array([t.name for t in topos]),
        topo_is_looped=np.array([t.is_looped for t in topos], dtype=bool),
        features=np.array(ACTIVE_FEATURES),
        devices=np.array(grid.devices),
        bus=np.array(bus_list, dtype=str),
        ftype=np.array(ftype_list, dtype=str),
        r=np.array(r_list, dtype=float),
        der_pct=np.array(der_list, dtype=float),
        event_kind=np.array(kind_list, dtype=str),
        converged=conv,
    )

    kinds_arr = np.array(kind_list)[conv]
    return {
        "feeder": name,
        "path": str(npz_path),
        "events_total": int(len(y_list)),
        "converged": int(conv.sum()),
        "converged_share": round(float(conv.mean()), 4),
        "fault_events": int((kinds_arr == "fault").sum()),
        "nofault_events": int((kinds_arr != "fault").sum()),
        "nofault_breakdown": {k: int((kinds_arr == k).sum()) for k in ("cap_switch", "pv_cloud", "load_step")},
        "devices": list(grid.devices),
        "topologies": [t.name for t in topos],
        "der_buses": spec["buses"],
        "der_pen_range": list(DER_PEN_RANGE),
        "slg_resistances_ohm": SLG_R_BY_FEEDER[name],
        "phase_resistances_ohm": PHASE_R_BY_FEEDER[name],
        "runtime_s": round(time.time() - t0, 1),
    }
