"""Feeder-independent fault data for the transfer study (research/gnn-transfer/PLAN.md).

The main study's features are columns tied to named devices of the 123-bus feeder, so a model trained
on them cannot run on another feeder. Here every fault event becomes a small graph:

  nodes  = measurement devices (switches), edges = the zone tree (device -> its upstream device),
  node features = relative quantities that mean the same on any feeder (incremental current / the
                  device's own pre-fault current, voltages in pu, voltage drops, position in the tree),
  label  = the device whose zone holds the fault.

IEEE 123-bus uses the study's own 10 devices and zones (shf.topology). A feeder the models never see
gets its devices from PLACEMENT_RULE, fixed on 2026-11-21 before any transfer result existed:

  a recloser on the first line leaving the substation bus; then at every bus where the feeder splits
  into two or more branches that each carry at least BRANCH_SHARE of the feeder's nominal load, a
  switch on the first line of each of those branches (after a transformer, the first line beyond it).

Simulation only. Nothing here is field data.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import numpy as np
import opendssdirect as dss

from . import config, faults, feeder

BRANCH_SHARE = 0.05
FEEDERS = {
    "ieee34": {"master": config.ROOT / "data" / "feeder" / "ieee34" / "ieee34Mod1.dss", "root": "800",
               "voltage_bases": [69, 24.9, 4.16, 0.48]},
}
OUT_DIR = config.ROOT / "data" / "generated"
SUMMARY_DIR = config.RESULTS / "transfer"
FEATURES = ["dIa", "dIb", "dIc", "Ia", "Ib", "Ic", "dI0", "dI2",
            "Va", "Vb", "Vc", "dVa", "dVb", "dVc", "has_a", "has_b", "has_c",
            "depth", "n_children", "share_down", "share_own"]


@dataclass
class Grid:
    name: str
    devices: list[str]                        # node order
    line: dict[str, str]                      # device -> OpenDSS line name
    parent: dict[str, str | None]             # device -> upstream device
    members: dict[str, list[str]]             # device -> buses of the zone it feeds
    kw: dict[str, float] = field(default_factory=dict)

    @property
    def bus_zone(self) -> dict[str, str]:
        return {b: z for z, bs in self.members.items() for b in bs}

    def depth(self, d: str) -> int:
        n = 0
        while self.parent[d]:
            d, n = self.parent[d], n + 1
        return n

    def subtree(self, d: str) -> list[str]:
        out, stack = [], [d]
        while stack:
            z = stack.pop()
            out.append(z)
            stack.extend(c for c in self.devices if self.parent[c] == z)
        return out


def _bus(s: str) -> str:
    return s.split(".")[0].lower()


def bus_graph() -> nx.Graph:
    """Buses joined by every line and transformer of the compiled circuit."""
    g = nx.Graph()
    for kind, names in (("Line", dss.Lines.AllNames()), ("Transformer", dss.Transformers.AllNames())):
        for n in names:
            dss.Circuit.SetActiveElement(f"{kind}.{n}")
            b = dss.CktElement.BusNames()
            if len(b) >= 2 and _bus(b[0]) != _bus(b[1]):
                g.add_edge(_bus(b[0]), _bus(b[1]), kind=kind, name=n.lower())
    return g


def load_feeder(name: str) -> None:
    """Compile and solve a feeder. ieee123 is the study's own model (shf.feeder)."""
    if name == "ieee123":
        feeder.load_feeder()
        return
    spec = FEEDERS[name]
    feeder.cmd("Clear")
    feeder.cmd(f'Compile "{spec["master"]}"')
    feeder.cmd(f"Set VoltageBases={spec['voltage_bases']}")
    feeder.cmd("CalcVoltageBases")
    feeder.solve(controls=True)


def placement_rule(name: str) -> Grid:
    """Devices and zones for a feeder the models never trained on (see the module docstring)."""
    root = FEEDERS[name]["root"]
    g = bus_graph()
    tree = nx.bfs_tree(g, root)
    kw_bus = {k.lower(): v for k, v in feeder.load_kw_by_bus().items()}
    down = {b: sum(kw_bus.get(x, 0.0) for x in nx.descendants(tree, b) | {b}) for b in tree.nodes}
    total = down[root]

    def first_line(u, v):                     # the branch's first line element, past transformers
        while g.edges[u, v]["kind"] != "Line":
            nxt = list(tree.successors(v))
            if len(nxt) != 1:
                raise ValueError(f"branch {u}-{v} has no single line after its transformer")
            u, v = v, nxt[0]
        return g.edges[u, v]["name"], v

    head_line, head_bus = first_line(root, next(iter(tree.successors(root))))
    chosen = {head_line: head_bus}
    for b in tree.nodes:
        kids = list(tree.successors(b))
        big = [c for c in kids if down[c] >= BRANCH_SHARE * total]
        if len(kids) >= 2 and len(big) >= 2:
            for c in big:
                ln, start = first_line(b, c)
                chosen[ln] = start
    # zones: cut the device lines; each device feeds the component on its downstream side
    cut = g.copy()
    ends = {}
    for ln in chosen:
        for u, v, d in g.edges(data=True):
            if d["name"] == ln:
                up, dn = (u, v) if v in nx.descendants(tree, u) else (v, u)
                ends[ln] = (up, dn)
                cut.remove_edge(u, v)
    order = sorted(chosen, key=lambda ln: (nx.shortest_path_length(tree, root, ends[ln][1]), ln))
    names = {ln: f"D{i + 1}" for i, ln in enumerate(order)}
    members, bus_dev = {}, {}
    for ln in order:
        comp = sorted(nx.node_connected_component(cut, ends[ln][1]))
        members[names[ln]] = comp
        for x in comp:
            bus_dev[x] = names[ln]
    parent = {names[ln]: bus_dev.get(ends[ln][0]) for ln in order}
    grid = Grid(name, [names[ln] for ln in order], {names[ln]: ln for ln in order}, parent, members)
    grid.kw = {z: sum(kw_bus.get(x, 0.0) for x in bs) for z, bs in members.items()}
    return grid


def study_grid() -> Grid:
    """IEEE 123-bus with the main study's 10 devices and zones, unchanged."""
    from .topology import find_zones
    z = find_zones()
    devs = list(config.SECTIONALIZERS)
    return Grid("ieee123", devs, {d: d for d in devs}, {d: z.parent[d] for d in devs},
                {d: list(z.members[d]) for d in devs}, dict(z.kw))


def structure(grid: Grid) -> np.ndarray:
    """Per node: depth, number of child devices, share of load downstream, share in its own zone."""
    total = sum(grid.kw.values()) or 1.0
    rows = []
    for d in grid.devices:
        kids = [c for c in grid.devices if grid.parent[c] == d]
        rows.append([grid.depth(d), len(kids), sum(grid.kw[z] for z in grid.subtree(d)) / total, grid.kw[d] / total])
    return np.array(rows, dtype=float)


def node_features(grid: Grid, pre: dict, post: dict, struct: np.ndarray) -> np.ndarray:
    """Relative quantities only: no amperes, no kV, no device names."""
    head = grid.devices[0]
    floor = 0.05 * max(np.abs(pre[head]["i"]).max(), 1e-6)     # protects lightly loaded devices
    out = []
    for k, d in enumerate(grid.devices):
        m, p = post[d], pre[d]
        base = max(np.abs(p["i"]).max(), floor)
        has = np.abs(p["v"]) > 0.1
        row = list(np.log1p(np.abs(m["i"] - p["i"]) / base)) + list(np.log1p(np.abs(m["i"]) / base))
        row += [np.log1p(abs(m["i0"] - p["i0"]) / base), np.log1p(abs(m["i2"] - p["i2"]) / base)]
        row += list(np.abs(m["v"]) * has) + list((np.abs(m["v"]) - np.abs(p["v"])) * has) + list(has.astype(float))
        row += list(struct[k])
        out.append(row)
    return np.array(out, dtype=np.float32)


def fault_cases(grid: Grid) -> list[dict]:
    """Same fault types and resistances as the main study (shf.faults.fault_cases)."""
    class _Z:                                  # the shape shf.faults.fault_cases expects
        members = grid.members
    return faults.fault_cases(_Z)


def sweep(name: str, seed: int = 0, scenarios: int | None = None, verbose: bool = True) -> dict:
    """Run the fault sweep on a feeder and store graph samples in data/generated/transfer_<name>.npz."""
    load_feeder(name)
    grid = study_grid() if name == "ieee123" else placement_rule(name)
    if name == "ieee123":
        feeder.set_normal_configuration()
    scenarios = scenarios or config.SCENARIOS_PER_CASE
    rng = np.random.default_rng(seed)
    cases = fault_cases(grid)
    base = feeder.base_loads()
    struct = structure(grid)
    first = grid.members[grid.devices[0]][0]
    feeder.cmd(f"New Fault.F phases=1 bus1={first}.1 bus2={first}.0 r=1 enabled=no")
    X, y, meta, t0 = [], [], [], time.time()
    index = {d: i for i, d in enumerate(grid.devices)}
    bus_zone = grid.bus_zone

    def snap():
        clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
        return faults._perturb(clean, rng)

    for s in range(scenarios):
        for c in cases:
            mult = rng.uniform(*config.LOAD_MULT_RANGE)
            spread = np.clip(rng.normal(1.0, config.LOAD_SPREAD, len(base)), 0.3, 1.7)
            feeder.scale_loads(base, spread)
            feeder.set_load_level(mult)
            feeder.cmd("Edit Fault.F enabled=no")
            ok_pre = feeder.solve(controls=True)
            pre = snap()
            feeder.cmd(f"Edit Fault.F {c['spec']} enabled=yes")
            ok = feeder.solve(controls=False)
            X.append(node_features(grid, pre, snap(), struct))
            y.append(index[bus_zone[c["bus"]]])
            meta.append((c["bus"], c["ftype"], c["phases"], c["r"], s, mult, bool(ok and ok_pre)))
        if verbose:
            print(f"  {name} scenario {s + 1}/{scenarios}: {len(cases)} faults, {time.time() - t0:.0f} s")
    feeder.cmd("Edit Fault.F enabled=no")
    feeder.scale_loads(base, np.ones(len(base)))
    feeder.set_load_level(1.0)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    parent_idx = np.array([index[grid.parent[d]] if grid.parent[d] else -1 for d in grid.devices])
    m = np.array(meta, dtype=object)
    path = OUT_DIR / f"transfer_{name}.npz"
    np.savez_compressed(path, X=np.stack(X), y=np.array(y), parent=parent_idx, features=np.array(FEATURES),
                        devices=np.array(grid.devices), bus=m[:, 0].astype(str), ftype=m[:, 1].astype(str),
                        phases=m[:, 2].astype(str), r=m[:, 3].astype(float), scenario=m[:, 4].astype(int),
                        load_mult=m[:, 5].astype(float), converged=m[:, 6].astype(bool))
    summary = {
        "feeder": name, "events": len(y), "converged": int(m[:, 6].astype(bool).sum()),
        "devices": [{"name": d, "line": grid.line[d], "parent": grid.parent[d], "buses": len(grid.members[d]),
                     "kw_nominal": round(grid.kw[d], 1),
                     "events": int(sum(1 for v in y if v == index[d]))} for d in grid.devices],
        "features": FEATURES, "scenarios": scenarios, "seed": seed,
        "placement": "study devices (shf.topology)" if name == "ieee123" else
                     f"PLACEMENT_RULE, branch share {BRANCH_SHARE}",
        "runtime_s": round(time.time() - t0, 1),
    }
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    out = SUMMARY_DIR / f"dataset_{name}.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    from . import provenance
    provenance.record(f"transfer_sweep_{name}", [out])
    return summary
