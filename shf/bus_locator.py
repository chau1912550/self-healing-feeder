"""Phase 2b of the transfer study: from predicted zone to bus ranking (research/gnn-transfer/PLAN.md).

Given a fault event and a predicted switching zone (from Stage 1), rank the buses inside that zone:
  0. Random baseline: analytical expectation of picking a bus of the predicted zone uniformly.
  1. Apparent impedance / 3-phase Takagi reactance method (IEEE Std C37.114): uses complex phasors
     (V, I, dI) at the zone's upstream device and the exact 3x3 path line-impedance matrices read
     from OpenDSS. Needs zero training data and works on any feeder.
  2. Small bus-graph GNN (BusGraphGNN, plain PyTorch on CPU): message passing on the full feeder
     bus tree, with electrical measurements placed only at device buses plus OpenDSS bus topology
     and normalized reactance residuals. Trained on IEEE 123-bus only (GroupKFold by bus) and
     tested zero-shot on IEEE 34-bus.

Expected physical limit (stated in PLAN.md before any run): with sensors only at zone boundaries,
two buses at the same electrical distance on different laterals produce nearly identical device
measurements, so top-3 bus accuracy and the confused-bus table are the honest metrics to quote.

Simulation only. Nothing here is field data.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any

import networkx as nx
import numpy as np
import opendssdirect as dss
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.model_selection import GroupKFold

from . import config, faults, feeder, transfer, transfer_models as tm


@dataclass
class FeederBusModel:
    name: str
    grid: transfer.Grid
    buses: list[str]                         # ordered buses in all zones (N_bus)
    bus_index: dict[str, int]                # bus name -> index 0..N_bus-1
    bus_zone_idx: np.ndarray                 # (N_bus,) int zone index 0..N_dev-1
    bus_parent: np.ndarray                   # (N_bus,) int parent bus index in feeder tree (-1 at root)
    bus_phases: np.ndarray                   # (N_bus, 3) bool [has_a, has_b, has_c]
    dev_bus_idx: np.ndarray                  # (N_dev,) int bus index where each device sits (-1 if outside zones)
    dev_kv_ln: np.ndarray                    # (N_dev,) float line-to-neutral kV base at each device
    z_path: np.ndarray                       # (N_bus, 3, 3) complex128 path impedance from bus's zone device
    z1_path: np.ndarray                      # (N_bus,) complex128 positive-sequence path impedance
    zone_bus_indices: list[np.ndarray]       # per zone: array of bus indices belonging to that zone
    zone_x_scale: np.ndarray                 # (N_dev,) float characteristic X1 scale (ohms) per zone


def _line_z3x3(line_name: str) -> tuple[np.ndarray, complex]:
    """Return (3x3 phase impedance matrix in ohms, scalar positive-sequence Z1) for an OpenDSS Line."""
    dss.Lines.Name(line_name)
    dss.Circuit.SetActiveElement(f"Line.{line_name}")
    nph = dss.Lines.Phases()
    length = dss.Lines.Length()
    rm = np.array(dss.Lines.RMatrix(), dtype=float).reshape(nph, nph) * length
    xm = np.array(dss.Lines.XMatrix(), dtype=float).reshape(nph, nph) * length
    zm = rm + 1j * xm
    nodes = [n for n in dss.CktElement.NodeOrder()[:nph] if n in (1, 2, 3)]
    z3 = np.zeros((3, 3), dtype=np.complex128)
    for a, pa in enumerate(nodes):
        for b, pb in enumerate(nodes):
            z3[pa - 1, pb - 1] = zm[a, b]
    z_self = float(np.mean(np.diag(zm).real)) + 1j * float(np.mean(np.diag(zm).imag))
    z_mut = (zm.sum() - np.trace(zm)) / (nph * (nph - 1)) if nph > 1 else 0j
    z1 = complex(z_self - z_mut)
    return z3, z1


def build_feeder_bus_model(name: str) -> FeederBusModel:
    """Read OpenDSS bus graph, phases, and exact 3x3 path impedances from each zone's device."""
    transfer.load_feeder(name)
    grid = transfer.study_grid() if name == "ieee123" else transfer.placement_rule(name)
    if name == "ieee123":
        feeder.set_normal_configuration()
        feeder.solve(controls=True)

    root = config.SOURCE_BUS.lower() if name == "ieee123" else transfer.FEEDERS[name]["root"].lower()
    g = transfer.bus_graph()
    tree = nx.bfs_tree(g, root)

    # Pre-read all line 3x3 matrices once.
    line_z: dict[str, tuple[np.ndarray, complex]] = {}
    for _, _, ed in g.edges(data=True):
        if ed["kind"] == "Line" and ed["name"] not in line_z:
            line_z[ed["name"]] = _line_z3x3(ed["name"])

    buses = [b.lower() for d in grid.devices for b in grid.members[d]]
    bus_index = {b: i for i, b in enumerate(buses)}
    n_bus = len(buses)
    n_dev = len(grid.devices)

    bus_zone_idx = np.zeros(n_bus, dtype=np.int64)
    bus_phases = np.zeros((n_bus, 3), dtype=bool)
    z_path = np.zeros((n_bus, 3, 3), dtype=np.complex128)
    z1_path = np.zeros(n_bus, dtype=np.complex128)
    dev_bus_names: list[str] = []
    dev_kv_ln = np.zeros(n_dev, dtype=float)
    dev_bus_idx = np.full(n_dev, -1, dtype=np.int64)
    zone_bus_indices: list[np.ndarray] = []

    for zi, d in enumerate(grid.devices):
        m = feeder.device_measurement(grid.line[d])
        db = m["bus"].lower()
        dev_bus_names.append(db)
        dss.Circuit.SetActiveBus(db)
        dev_kv_ln[zi] = float(dss.Bus.kVBase())
        # Map device to its downstream bus inside the zone if upstream bus is outside (e.g., 150r/800).
        if db in bus_index:
            dev_bus_idx[zi] = bus_index[db]
        else:
            # First bus of the zone closest to root in BFS tree.
            zone_bs = [b.lower() for b in grid.members[d]]
            best_b = min(zone_bs, key=lambda x: nx.shortest_path_length(tree, root, x))
            dev_bus_idx[zi] = bus_index[best_b]

        idxs = []
        for b_raw in grid.members[d]:
            b = b_raw.lower()
            bi = bus_index[b]
            idxs.append(bi)
            bus_zone_idx[bi] = zi
            ph = feeder.bus_phases(b)
            for p in ph:
                bus_phases[bi, p - 1] = True
            path = nx.shortest_path(g, db, b)
            z3_acc = np.zeros((3, 3), dtype=np.complex128)
            z1_acc = 0j
            for u, v in zip(path, path[1:]):
                ed = g.edges[u, v]
                if ed["kind"] == "Line":
                    z3_seg, z1_seg = line_z[ed["name"]]
                    z3_acc += z3_seg
                    z1_acc += z1_seg
            z_path[bi] = z3_acc
            z1_path[bi] = z1_acc
        zone_bus_indices.append(np.array(idxs, dtype=np.int64))

    # Build a single rooted tree over the zone buses (N_bus nodes) by climbing tree predecessors
    # until landing on another zone bus (the shallowest zone bus becomes root -1).
    bus_parent = np.full(n_bus, -1, dtype=np.int64)
    for b, bi in bus_index.items():
        cur = b
        while True:
            preds = list(tree.predecessors(cur))
            if not preds:
                break
            cur = preds[0]
            if cur in bus_index:
                bus_parent[bi] = bus_index[cur]
                break

    zone_x_scale = np.zeros(n_dev, dtype=float)
    for zi, idxs in enumerate(zone_bus_indices):
        xs = np.abs(z1_path[idxs].imag)
        scale = float(np.max(xs)) if len(xs) else 1.0
        zone_x_scale[zi] = max(scale, 0.1)

    return FeederBusModel(
        name=name, grid=grid, buses=buses, bus_index=bus_index, bus_zone_idx=bus_zone_idx,
        bus_parent=bus_parent, bus_phases=bus_phases, dev_bus_idx=dev_bus_idx, dev_kv_ln=dev_kv_ln,
        z_path=z_path, z1_path=z1_path, zone_bus_indices=zone_bus_indices, zone_x_scale=zone_x_scale,
    )


def sweep_with_phasors(fbm: FeederBusModel, seed: int = 0, scenarios: int | None = None) -> dict[str, Any]:
    """Run the exact Phase 1 fault sweep and also keep complex V (Volts LN) and I (Amps) per device."""
    name, grid = fbm.name, fbm.grid
    transfer.load_feeder(name)
    if name == "ieee123":
        feeder.set_normal_configuration()
    scenarios = scenarios or config.SCENARIOS_PER_CASE
    rng = np.random.default_rng(seed)
    cases = transfer.fault_cases(grid)
    base = feeder.base_loads()
    struct = transfer.structure(grid)
    first = grid.members[grid.devices[0]][0]
    feeder.cmd(f"New Fault.F phases=1 bus1={first}.1 bus2={first}.0 r=1 enabled=no")

    n_total = scenarios * len(cases)
    n_dev = len(grid.devices)
    X = np.empty((n_total, n_dev, len(transfer.FEATURES)), dtype=np.float32)
    V_post = np.empty((n_total, n_dev, 3), dtype=np.complex64)
    I_post = np.empty((n_total, n_dev, 3), dtype=np.complex64)
    dI = np.empty((n_total, n_dev, 3), dtype=np.complex64)
    y_zone = np.empty(n_total, dtype=np.int64)
    y_bus = np.empty(n_total, dtype=np.int64)
    bus_arr, ftype_arr, r_arr, conv_arr = [], [], [], []

    dev_index = {d: i for i, d in enumerate(grid.devices)}
    bus_zone = grid.bus_zone
    v_scale = (fbm.dev_kv_ln * 1000.0).astype(np.float64)

    def snap():
        clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
        return faults._perturb(clean, rng)

    k = 0
    for _ in range(scenarios):
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
            post = snap()

            X[k] = transfer.node_features(grid, pre, post, struct)
            for di, d in enumerate(grid.devices):
                V_post[k, di] = post[d]["v"] * v_scale[di]
                I_post[k, di] = post[d]["i"]
                dI[k, di] = post[d]["i"] - pre[d]["i"]
            b_low = c["bus"].lower()
            y_zone[k] = dev_index[bus_zone[c["bus"]]]
            y_bus[k] = fbm.bus_index[b_low]
            bus_arr.append(b_low)
            ftype_arr.append(c["ftype"])
            r_arr.append(float(c["r"]))
            conv_arr.append(bool(ok and ok_pre))
            k += 1

    feeder.cmd("Edit Fault.F enabled=no")
    feeder.scale_loads(base, np.ones(len(base)))
    feeder.set_load_level(1.0)

    conv = np.array(conv_arr, dtype=bool)
    return {
        "X": X[conv], "V_post": V_post[conv], "I_post": I_post[conv], "dI": dI[conv],
        "y_zone": y_zone[conv], "y_bus": y_bus[conv],
        "bus": np.array(bus_arr, dtype=str)[conv],
        "ftype": np.array(ftype_arr, dtype=str)[conv],
        "r": np.array(r_arr, dtype=float)[conv],
    }


# ---------------------------------------------------------------------------
# Method 1: Apparent impedance / 3-phase Takagi reactance ranking (zero training)
# ---------------------------------------------------------------------------

def takagi_bus_residuals(fbm: FeederBusModel, V_post: np.ndarray, I_post: np.ndarray,
                         dI: np.ndarray, zone_idx: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute per-bus (X_err_ohm, R_est_ohm, phase_compat) for every event against its zone's device.

    Uses the 3x3 OpenDSS path impedance matrix Z_path[b]:
      V_at_bus(b) = V_dev_post - Z_path[b] @ I_dev_post
    Then projects V_at_bus(b) onto the superimposed fault current dI_f (Takagi method, cancels R_f):
      X_err(b) = Im(V_f(b) * conj(dI_f)) / |dI_f|^2
      R_est(b) = Re(V_f(b) * conj(dI_f)) / |dI_f|^2

    Returns arrays of shape (E, N_bus) for X_err, R_est, and phase_compat (bool).
    """
    n_events = len(zone_idx)
    n_bus = len(fbm.buses)
    ev = np.arange(n_events)

    # Device measurements at each event's specified zone (predicted or oracle).
    v_dev = V_post[ev, zone_idx].astype(np.complex128)            # (E, 3)
    i_dev = I_post[ev, zone_idx].astype(np.complex128)            # (E, 3)
    di_dev = dI[ev, zone_idx].astype(np.complex128)               # (E, 3)

    # Detect faulted phase(s) from superimposed current magnitudes at the zone device.
    di_mag = np.abs(di_dev)                                       # (E, 3)
    di_max = np.maximum(di_mag.max(axis=1, keepdims=True), 1e-9)
    fault_ph = di_mag >= (0.45 * di_max)                          # (E, 3) bool
    n_fph = fault_ph.sum(axis=1)

    # Phase compatibility: candidate bus must have every detected faulted phase.
    # fault_ph: (E, 1, 3), bus_phases: (1, N_bus, 3) -> incompatible if fault_ph & ~bus_phases
    phase_compat = ~((fault_ph[:, None, :]) & (~fbm.bus_phases[None, :, :])).any(axis=-1)

    # Predicted bus voltage vector for all (event, bus): V_bus = v_dev - Z_path @ i_dev.
    # einsum: 'bij,ej->ebi' -> (E, N_bus, 3)
    v_drop = np.einsum("bij,ej->ebi", fbm.z_path, i_dev)
    v_bus = v_dev[:, None, :] - v_drop                            # (E, N_bus, 3)

    x_err = np.zeros((n_events, n_bus), dtype=np.float64)
    r_est = np.zeros((n_events, n_bus), dtype=np.float64)

    # Case 1: SLG (1 faulted phase)
    m1 = n_fph == 1
    if m1.any():
        p = di_mag[m1].argmax(axis=1)                             # (E1,)
        rows = np.flatnonzero(m1)
        vf = v_bus[rows, :, p]                                    # (E1, N_bus)
        dif = di_dev[rows, p][:, None]                            # (E1, 1)
        denom = np.maximum(np.abs(dif) ** 2, 1e-12)
        z_app = (vf * np.conj(dif)) / denom
        x_err[rows] = z_app.imag
        r_est[rows] = z_app.real

    # Case 2: LL or LLG (2 faulted phases -> phase-to-phase loop cancels fault resistance)
    m2 = n_fph == 2
    if m2.any():
        rows = np.flatnonzero(m2)
        order = np.argsort(di_mag[rows], axis=1)                  # ascending -> last 2 are faulted
        p1, p2 = order[:, 2], order[:, 1]
        vf = v_bus[rows, :, p1] - v_bus[rows, :, p2]
        dif = (di_dev[rows, p1] - di_dev[rows, p2])[:, None]
        denom = np.maximum(np.abs(dif) ** 2, 1e-12)
        z_app = (vf * np.conj(dif)) / denom
        x_err[rows] = z_app.imag
        r_est[rows] = z_app.real

    # Case 3: 3PH (all 3 phases -> positive-sequence loop)
    m3 = n_fph >= 3
    if m3.any():
        rows = np.flatnonzero(m3)
        a = feeder.A
        vf = (v_bus[rows, :, 0] + a * v_bus[rows, :, 1] + (a * a) * v_bus[rows, :, 2]) / 3.0
        dif = ((di_dev[rows, 0] + a * di_dev[rows, 1] + (a * a) * di_dev[rows, 2]) / 3.0)[:, None]
        denom = np.maximum(np.abs(dif) ** 2, 1e-12)
        z_app = (vf * np.conj(dif)) / denom
        x_err[rows] = z_app.imag
        r_est[rows] = z_app.real

    return x_err, r_est, phase_compat


def reactance_scores(fbm: FeederBusModel, x_err: np.ndarray, r_est: np.ndarray,
                     phase_compat: np.ndarray, zone_idx: np.ndarray) -> np.ndarray:
    """Higher score = better bus match inside `zone_idx`; buses outside the zone get -inf."""
    n_events, n_bus = x_err.shape
    in_zone = fbm.bus_zone_idx[None, :] == zone_idx[:, None]
    # Negative R_est means the bus is downstream of the fault; add a gentle penalty.
    neg_r_pen = np.maximum(0.0, -r_est - 0.5)
    cost = np.abs(x_err) + 0.5 * neg_r_pen + np.where(phase_compat, 0.0, 1e6)
    return np.where(in_zone, -cost, -np.inf)


def random_zone_baseline(fbm: FeederBusModel, y_zone: np.ndarray, pred_zone: np.ndarray,
                         ftype: np.ndarray, r: np.ndarray) -> dict[str, Any]:
    """Exact analytical top-1 / top-3 expectation of picking a random bus inside `pred_zone`."""
    sizes = np.array([len(idxs) for idxs in fbm.zone_bus_indices], dtype=float)
    z_ok = (pred_zone == y_zone)
    p1 = np.where(z_ok, 1.0 / sizes[np.maximum(pred_zone, 0)], 0.0)
    p3 = np.where(z_ok, np.minimum(3.0, sizes[np.maximum(pred_zone, 0)]) / sizes[np.maximum(pred_zone, 0)], 0.0)
    slg = ftype == "SLG"
    return {
        "top1": float(p1.mean()),
        "top3": float(p3.mean()),
        "by_fault_type_top1": {ft: round(float(p1[ftype == ft].mean()), 4) for ft in sorted(np.unique(ftype))},
        "by_fault_type_top3": {ft: round(float(p3[ftype == ft].mean()), 4) for ft in sorted(np.unique(ftype))},
        "slg_by_resistance_top3": {str(float(rv)): round(float(p3[slg & (r == rv)].mean()), 4)
                                   for rv in sorted(np.unique(r[slg]))},
    }


def evaluate_bus_scores(fbm: FeederBusModel, scores: np.ndarray, y_bus: np.ndarray,
                        ftype: np.ndarray, r: np.ndarray, top_confusions: int = 12) -> dict[str, Any]:
    """Compute top-1, top-3, breakdowns, and the top confused bus pairs with electrical distance |dX1|."""
    order = np.argsort(-scores, axis=1)                           # descending score
    top1_pred = order[:, 0]
    top3_preds = order[:, :3]
    hit1 = top1_pred == y_bus
    hit3 = (top3_preds == y_bus[:, None]).any(axis=1)
    slg = ftype == "SLG"

    # Error table: which bus pairs get confused most often, and how close are their X1 reactances?
    wrong = np.flatnonzero(~hit1)
    pair_counts = Counter((int(y_bus[i]), int(top1_pred[i])) for i in wrong)
    confusions = []
    for (tb, pb), cnt in pair_counts.most_common(top_confusions):
        same_zone = bool(fbm.bus_zone_idx[tb] == fbm.bus_zone_idx[pb])
        dx1 = abs(float(fbm.z1_path[tb].imag) - float(fbm.z1_path[pb].imag)) if same_zone else None
        confusions.append({
            "true_bus": fbm.buses[tb],
            "pred_bus": fbm.buses[pb],
            "zone": fbm.grid.devices[int(fbm.bus_zone_idx[tb])],
            "same_zone": same_zone,
            "count": int(cnt),
            "delta_x1_ohm": round(dx1, 4) if dx1 is not None else None,
        })

    return {
        "top1": float(hit1.mean()),
        "top3": float(hit3.mean()),
        "by_fault_type_top1": {ft: round(float(hit1[ftype == ft].mean()), 4) for ft in sorted(np.unique(ftype))},
        "by_fault_type_top3": {ft: round(float(hit3[ftype == ft].mean()), 4) for ft in sorted(np.unique(ftype))},
        "slg_by_resistance_top1": {str(float(rv)): round(float(hit1[slg & (r == rv)].mean()), 4)
                                   for rv in sorted(np.unique(r[slg]))},
        "slg_by_resistance_top3": {str(float(rv)): round(float(hit3[slg & (r == rv)].mean()), 4)
                                   for rv in sorted(np.unique(r[slg]))},
        "top_confused_bus_pairs": confusions,
    }


# ---------------------------------------------------------------------------
# Method 2: Small Bus-Graph GNN (measurements only at devices + bus graph)
# ---------------------------------------------------------------------------

def build_bus_graph_features(fbm: FeederBusModel, X_dev: np.ndarray, x_err: np.ndarray,
                             r_est: np.ndarray, phase_compat: np.ndarray,
                             zone_idx: np.ndarray) -> np.ndarray:
    """Build feeder-independent per-bus features (E, N_bus, 28) with measurements ONLY at device buses.

    Channels:
      0..16  : 17 relative electrical measurements from X_dev (non-zero ONLY at device buses!)
      17     : has_sensor (1.0 at device buses, 0.0 at all other buses)
      18..20 : bus_has_a, bus_has_b, bus_has_c (from OpenDSS topology)
      21     : phase_compat (1.0 if bus carries all detected faulted phases)
      22     : in_zone (1.0 if bus belongs to `zone_idx`)
      23     : log1p(|X_err| / zone_x_scale) (dimensionless reactance mismatch)
      24     : clip(X_err / zone_x_scale, -5, 5) (signed reactance mismatch)
      25     : log1p(max(0, -R_est) / zone_x_scale) (negative fault resistance violation)
      26     : |Z1(dev -> bus)| / zone_z1_max (relative electrical depth inside zone, 0..1)
      27     : log1p(max(0, R_est) / zone_x_scale) (estimated fault resistance scale)
    """
    n_events = X_dev.shape[0]
    n_bus = len(fbm.buses)
    feat = np.zeros((n_events, n_bus, 28), dtype=np.float32)

    # Place device electrical measurements ONLY at device buses.
    for di, bi in enumerate(fbm.dev_bus_idx):
        if bi >= 0:
            feat[:, bi, :tm.N_ELEC] = X_dev[:, di, :tm.N_ELEC]
            feat[:, bi, 17] = 1.0

    # Static OpenDSS bus phase indicators & relative impedance depth inside each bus's zone.
    feat[:, :, 18:21] = fbm.bus_phases[None, :, :].astype(np.float32)
    z1_mag = np.abs(fbm.z1_path)
    z1_frac = np.zeros(n_bus, dtype=np.float32)
    for idxs in fbm.zone_bus_indices:
        zmax = max(float(z1_mag[idxs].max()), 1e-6)
        z1_frac[idxs] = (z1_mag[idxs] / zmax).astype(np.float32)
    feat[:, :, 26] = z1_frac[None, :]

    in_zone = (fbm.bus_zone_idx[None, :] == zone_idx[:, None])
    scale = fbm.zone_x_scale[zone_idx][:, None]                   # (E, 1)

    feat[:, :, 21] = phase_compat.astype(np.float32)
    feat[:, :, 22] = in_zone.astype(np.float32)
    feat[:, :, 23] = np.log1p(np.abs(x_err) / scale).astype(np.float32)
    feat[:, :, 24] = np.clip(x_err / scale, -5.0, 5.0).astype(np.float32)
    feat[:, :, 25] = np.log1p(np.maximum(0.0, -r_est) / scale).astype(np.float32)
    feat[:, :, 27] = np.log1p(np.maximum(0.0, r_est) / scale).astype(np.float32)
    return feat


class BusGraphGNN(nn.Module):
    """Small message-passing GNN on the feeder bus tree, ranking buses inside the predicted zone."""

    def __init__(self, in_features: int = 28, hidden: int = 48, n_layers: int = 2, dropout: float = 0.1):
        super().__init__()
        self.in_features = in_features
        self.hidden = hidden
        self.n_layers = n_layers
        self.dropout = dropout
        self.register_buffer("feat_mean", torch.zeros(in_features))
        self.register_buffer("feat_std", torch.ones(in_features))
        self.encoder = nn.Sequential(
            nn.Linear(in_features, hidden),
            nn.LayerNorm(hidden),
            nn.GELU(),
        )
        self.layers = nn.ModuleList([tm.TreeMPLayer(hidden, dropout=dropout) for _ in range(n_layers)])
        self.readout = nn.Sequential(
            nn.Linear(hidden, hidden // 2),
            nn.GELU(),
            nn.Linear(hidden // 2, 1),
        )

    def set_normalizer(self, X_train: np.ndarray) -> None:
        flat = X_train.reshape(-1, self.in_features)
        mean = flat.mean(axis=0)
        std = flat.std(axis=0)
        std = np.where(std < 1e-6, 1.0, std)
        self.feat_mean.copy_(torch.from_numpy(mean.astype(np.float32)))
        self.feat_std.copy_(torch.from_numpy(std.astype(np.float32)))

    def forward(self, x: torch.Tensor, bus_parent: torch.Tensor, zone_mask: torch.Tensor) -> torch.Tensor:
        """Return masked per-bus logits of shape (B, N_bus); buses outside zone_mask get -1e9."""
        h = self.encoder((x - self.feat_mean) / self.feat_std)
        for layer in self.layers:
            h = layer(h, bus_parent)
        logits = self.readout(h).squeeze(-1)
        return logits.masked_fill(~zone_mask, -1e9)


def train_bus_gnn(X_bus: np.ndarray, y_bus: np.ndarray, bus_parent: np.ndarray,
                  zone_mask: np.ndarray, *, hidden: int = 48, n_layers: int = 2,
                  dropout: float = 0.1, lr: float = 3e-3, weight_decay: float = 1e-4,
                  epochs: int = 25, batch_size: int = 256, seed: int = 0) -> BusGraphGNN:
    """Train BusGraphGNN on CPU on events whose true bus lies inside zone_mask."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)

    valid = zone_mask[np.arange(len(y_bus)), y_bus]
    X_tr, y_tr, m_tr = X_bus[valid], y_bus[valid], zone_mask[valid]

    net = BusGraphGNN(in_features=X_tr.shape[-1], hidden=hidden, n_layers=n_layers, dropout=dropout)
    net.set_normalizer(X_tr)

    x_all = torch.from_numpy(X_tr.astype(np.float32))
    y_all = torch.from_numpy(y_tr.astype(np.int64))
    m_all = torch.from_numpy(m_tr.astype(bool))
    par_t = torch.from_numpy(bus_parent.astype(np.int64))

    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs, eta_min=lr * 0.05)

    n_ev = len(y_tr)
    net.train()
    for _ in range(epochs):
        perm = torch.from_numpy(rng.permutation(n_ev))
        for start in range(0, n_ev, batch_size):
            idx = perm[start:start + batch_size]
            opt.zero_grad(set_to_none=True)
            logits = net(x_all[idx], par_t, m_all[idx])
            loss = F.cross_entropy(logits, y_all[idx])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 2.0)
            opt.step()
        sched.step()
    net.eval()
    return net


@torch.no_grad()
def predict_bus_gnn(net: BusGraphGNN, X_bus: np.ndarray, bus_parent: np.ndarray,
                    zone_mask: np.ndarray, batch_size: int = 512) -> np.ndarray:
    """Per-bus score matrix of shape (E, N_bus), -1e9 outside zone_mask."""
    net.eval()
    par_t = torch.from_numpy(bus_parent.astype(np.int64))
    out = []
    for start in range(0, len(X_bus), batch_size):
        xb = torch.from_numpy(X_bus[start:start + batch_size].astype(np.float32))
        mb = torch.from_numpy(zone_mask[start:start + batch_size].astype(bool))
        out.append(net(xb, par_t, mb).numpy())
    return np.concatenate(out, axis=0)


def _bus_gnn_fold_worker(args: tuple) -> np.ndarray:
    X_tr, y_tr, m_tr, X_te, m_te, bus_parent, fold_kw, threads = args
    torch.set_num_threads(threads)
    net = train_bus_gnn(X_tr, y_tr, bus_parent, m_tr, **fold_kw)
    return predict_bus_gnn(net, X_te, bus_parent, m_te)


def cv_bus_gnn(fbm: FeederBusModel, X_bus: np.ndarray, y_bus: np.ndarray, bus_names: np.ndarray,
               zone_idx: np.ndarray, *, n_splits: int = tm.N_FOLDS, seed: int = 0,
               n_jobs: int = 1, threads_per_worker: int = 2, **kwargs: Any) -> np.ndarray:
    """Out-of-fold bus score matrix (E, N_bus) under GroupKFold by bus (unseen test buses)."""
    zone_mask = fbm.bus_zone_idx[None, :] == zone_idx[:, None]
    oof = np.full((len(y_bus), len(fbm.buses)), -1e9, dtype=np.float32)
    splits = list(GroupKFold(n_splits=n_splits).split(X_bus, y_bus, bus_names))
    jobs = []
    for fold_i, (tr, te) in enumerate(splits):
        fold_kw = dict(kwargs)
        fold_kw["seed"] = seed + fold_i
        jobs.append((X_bus[tr], y_bus[tr], zone_mask[tr], X_bus[te], zone_mask[te],
                     fbm.bus_parent, fold_kw, threads_per_worker))
    if n_jobs > 1:
        with ProcessPoolExecutor(max_workers=min(n_jobs, len(jobs))) as pool:
            outputs = list(pool.map(_bus_gnn_fold_worker, jobs))
    else:
        outputs = [_bus_gnn_fold_worker(j) for j in jobs]
    for (_, te), scores in zip(splits, outputs):
        oof[te] = scores
    return oof
