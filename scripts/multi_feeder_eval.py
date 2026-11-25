"""Multi-feeder cross-feeder zero-shot benchmark (research/multi-feeder-benchmark/PLAN.md).

Evaluates the exact frozen IEEE 123-bus Stage-1 models (PerNodeGBDT & ZoneTreeGNN, zero retraining)
plus Graph FPI and OpenDSS SLG signal-to-load ratio across official IEEE & EPRI OpenDSS feeders.

Designed to run in parallel across multiple Kaggle VMs by passing --feeders per group, then merging:
    python scripts/multi_feeder_eval.py --feeders ieee13,eu_lv,ieee342,cigre_mv --out-dir out_g1
    python scripts/multi_feeder_eval.py --feeders epri_ckt5,epri_ckt7,epri_ckt24 --out-dir out_g2
    python scripts/multi_feeder_eval.py --feeders ieee8500,ieee9500,epri_j1,epri_k1,epri_m1 --out-dir out_g3
    python scripts/multi_feeder_eval.py --merge out_g1,out_g2,out_g3

Simulation only. Nothing here is field data.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path

import networkx as nx
import numpy as np
import opendssdirect as dss
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shf import config, faults, feeder, provenance, transfer, transfer_models as tm  # noqa: E402

FEEDER_DIR = config.ROOT / "data" / "feeder"
PHASE_FAULT_TYPES = ("3PH", "LL", "LLG")
S2L_RESISTANCES = (0.01, 1.0, 10.0, 100.0, 400.0)
MAX_SAMPLE_BUSES = 60
MIN_BUSES_PER_ZONE = 3

FEEDER_SPECS: dict[str, dict] = {
    "ieee13": {
        "label": "IEEE 13-bus",
        "family": "IEEE",
        "master": "ieee13/IEEE13Nodeckt.dss",
        "description": "4.16 kV compact heavily unbalanced overhead + underground",
        "max_buses": 80,
        "scenarios": 3,
    },
    "eu_lv": {
        "label": "IEEE European LV",
        "family": "IEEE",
        "master": "eu_lv/Master.dss",
        "description": "0.416 kV 50 Hz European radial LV cable feeder (907 buses)",
        "max_buses": MAX_SAMPLE_BUSES,
        "scenarios": 1,
    },
    "ieee342": {
        "label": "IEEE 342-Node (LV Network)",
        "family": "IEEE",
        "master": "ieee342/Master.dss",
        "description": "13.8/0.208 kV heavily meshed secondary network (71 cycles)",
        "max_buses": MAX_SAMPLE_BUSES,
        "scenarios": 1,
    },
    "ieee8500": {
        "label": "IEEE 8500-Node",
        "family": "IEEE",
        "master": "ieee8500/Master-unbal.dss",
        "description": "12.47 kV massive North American radial MV+LV feeder",
        "max_buses": MAX_SAMPLE_BUSES,
        "scenarios": 1,
    },
    "ieee9500": {
        "label": "IEEE 9500-Node",
        "family": "IEEE",
        "master": "ieee9500/ieee9500_base.dss",
        "description": "12.47 kV large active-ready test system",
        "max_buses": MAX_SAMPLE_BUSES,
        "scenarios": 1,
    },
    "epri_ckt5": {
        "label": "EPRI Ckt5",
        "family": "EPRI",
        "master": "epri_ckt5/Master_ckt5.dss",
        "description": "12.47 kV real-utility-scale radial feeder",
        "max_buses": MAX_SAMPLE_BUSES,
        "scenarios": 1,
    },
    "epri_ckt7": {
        "label": "EPRI Ckt7",
        "family": "EPRI",
        "master": "epri_ckt7/Master_ckt7.dss",
        "description": "12.47 kV utility radial feeder",
        "max_buses": MAX_SAMPLE_BUSES,
        "scenarios": 1,
    },
    "epri_ckt24": {
        "label": "EPRI Ckt24",
        "family": "EPRI",
        "master": "epri_ckt24/master_ckt24.dss",
        "description": "34.5/13.2 kV large utility feeder (2 internal step-down loops)",
        "max_buses": MAX_SAMPLE_BUSES,
        "scenarios": 1,
    },
    "epri_j1": {
        "label": "EPRI J1",
        "family": "EPRI",
        "master": "epri_j1/Master_noPV.dss",
        "description": "12.47 kV EPRI DPV utility feeder J1",
        "max_buses": MAX_SAMPLE_BUSES,
        "scenarios": 1,
    },
    "epri_k1": {
        "label": "EPRI K1",
        "family": "EPRI",
        "master": "epri_k1/Master_NoPV.dss",
        "description": "13.2 kV EPRI DPV utility feeder K1",
        "max_buses": MAX_SAMPLE_BUSES,
        "scenarios": 1,
    },
    "epri_m1": {
        "label": "EPRI M1",
        "family": "EPRI",
        "master": "epri_m1/Master_NoPV.dss",
        "description": "12.47 kV EPRI DPV utility feeder M1",
        "max_buses": MAX_SAMPLE_BUSES,
        "scenarios": 1,
    },
    "cigre_mv": {
        "label": "CIGRE MV (20 kV, 50 Hz)",
        "family": "CIGRE",
        "master": None,
        "description": "Not included in official dss-extensions/electricdss-tst OpenDSS repository",
        "max_buses": MAX_SAMPLE_BUSES,
        "scenarios": 1,
    },
}


def _bus_name(s: str) -> str:
    return s.split(".")[0].lower()


def _bus_kv_ll(bus: str) -> float:
    dss.Circuit.SetActiveBus(bus)
    return float(dss.Bus.kVBase()) * math.sqrt(3.0)


def _compile_feeder(spec: dict) -> tuple[bool, str, float, float]:
    master = FEEDER_DIR / spec["master"]
    dss.Text.Command("Clear")
    dss.Text.Command(f'Compile "{master}"')
    dss.Text.Command("Set mode=snapshot")
    dss.Text.Command("Set maxiterations=200")
    dss.Text.Command("Set maxcontroliter=200")
    dss.Text.Command("Solve")
    conv = bool(dss.Solution.Converged())
    freq = float(dss.Solution.Frequency())
    dss.Vsources.First()
    dss.Circuit.SetActiveElement("Vsource." + dss.Vsources.Name())
    root = _bus_name(dss.CktElement.BusNames()[0])
    tot_kw = float(-dss.Circuit.TotalPower()[0])
    if not math.isfinite(tot_kw):
        conv = False
        tot_kw = 0.0
    return conv, root, freq, tot_kw


def _energized_graph() -> nx.Graph:
    """Undirected energized bus graph from enabled, closed Line / Transformer / Reactor elements."""
    g = nx.Graph()
    for kind, getter in (
        ("Line", dss.Lines.AllNames),
        ("Transformer", dss.Transformers.AllNames),
        ("Reactor", dss.Reactors.AllNames),
    ):
        for n in getter():
            dss.Circuit.SetActiveElement(f"{kind}.{n}")
            if not dss.CktElement.Enabled():
                continue
            if dss.CktElement.IsOpen(1, 0) or dss.CktElement.IsOpen(2, 0):
                continue
            bs = dss.CktElement.BusNames()
            if len(bs) >= 2:
                u, v = _bus_name(bs[0]), _bus_name(bs[1])
                if u != v:
                    if not g.has_edge(u, v) or kind == "Transformer":
                        g.add_edge(u, v, kind=kind, name=n.lower())
    return g


def _general_placement_rule(name: str, g: nx.Graph, root: str) -> tuple[transfer.Grid, int]:
    """Exact BRANCH_SHARE=0.05 placement rule generalized to handle substation transformers/reactors
    and minor local loops (<=5 cycles) via BFS tree partitioning."""
    comp = nx.node_connected_component(g, root)
    sub = g.subgraph(comp)
    cycles = sub.number_of_edges() - sub.number_of_nodes() + 1
    tree = nx.bfs_tree(sub, root)

    kw_bus: dict[str, float] = {}
    for ln in dss.Loads.AllNames():
        dss.Loads.Name(ln)
        dss.Circuit.SetActiveElement(f"Load.{ln}")
        if not dss.CktElement.Enabled():
            continue
        b = _bus_name(dss.CktElement.BusNames()[0])
        kw_bus[b] = kw_bus.get(b, 0.0) + float(dss.Loads.kW())

    # O(N) post-order DFS for subtree load & bus counts (fast even on 6,000-bus feeders)
    down: dict[str, float] = {}
    sub_cnt: dict[str, int] = {}
    for b in nx.dfs_postorder_nodes(tree, root):
        down[b] = kw_bus.get(b, 0.0) + sum(down[c] for c in tree.successors(b))
        sub_cnt[b] = 1 + sum(sub_cnt[c] for c in tree.successors(b))
    total = down[root] or 1.0

    def first_line(u: str, v: str) -> tuple[str | None, str | None]:
        while sub.edges[u, v]["kind"] != "Line":
            nxt = [c for c in tree.successors(v) if down[c] >= transfer.BRANCH_SHARE * total]
            if not nxt:
                nxt = list(tree.successors(v))
            if len(nxt) != 1:
                # Substation bus splits into multiple loaded feeders or unloaded stubs; pick heaviest loaded trunk
                if not nxt:
                    return None, None
                best = max(nxt, key=lambda c: (sub_cnt[c] > 3, down[c], sub_cnt[c]))
                u, v = v, best
                continue
            u, v = v, nxt[0]
        return sub.edges[u, v]["name"], v

    # Head recloser: walk from root along the heaviest loaded detailed feeder branch (>3 buses) to its first Line
    root_kids = list(tree.successors(root))
    if not root_kids:
        raise ValueError("Root bus has no outgoing energized edge")
    main_kid = max(root_kids, key=lambda c: (sub_cnt[c] > 3, down[c], sub_cnt[c]))
    head_line, head_bus = first_line(root, main_kid)
    if not head_line or not head_bus:
        raise ValueError("Could not locate head recloser line")

    chosen: dict[str, str] = {head_line: head_bus}
    # Walk only the subtree under head_bus (avoids putting switches on lumped neighbor-feeder stubs)
    head_sub_nodes = nx.descendants(tree, head_bus) | {head_bus}
    head_total = down[head_bus] or total
    for b in head_sub_nodes:
        kids = list(tree.successors(b))
        big = [c for c in kids if down[c] >= transfer.BRANCH_SHARE * head_total]
        if len(kids) >= 2 and len(big) >= 2:
            for c in big:
                ln, st = first_line(b, c)
                if ln and st:
                    chosen[ln] = st

    # Order switches by BFS depth from root, then line name
    order = sorted(chosen.keys(), key=lambda ln: (nx.shortest_path_length(tree, root, chosen[ln]), ln))
    dev_names = {ln: f"D{i + 1}" for i, ln in enumerate(order)}
    start_bus_to_dev = {chosen[ln]: dev_names[ln] for ln in order}

    # Partition every bus in head_sub_nodes by walking up BFS tree to its nearest upstream switch
    members: dict[str, list[str]] = {dev_names[ln]: [] for ln in order}
    bus_dev: dict[str, str] = {}
    for b in sorted(head_sub_nodes):
        cur = b
        owner = None
        while True:
            if cur in start_bus_to_dev:
                owner = start_bus_to_dev[cur]
                break
            preds = list(tree.predecessors(cur))
            if not preds:
                break
            cur = preds[0]
        if owner:
            members[owner].append(b)
            bus_dev[b] = owner

    # Parent device for each switch: walk up from switch's upstream bus
    parent: dict[str, str | None] = {}
    for ln in order:
        dname = dev_names[ln]
        st_bus = chosen[ln]
        preds = list(tree.predecessors(st_bus))
        p_dev = None
        cur = preds[0] if preds else None
        while cur is not None:
            if cur in bus_dev and bus_dev[cur] != dname:
                p_dev = bus_dev[cur]
                break
            pr = list(tree.predecessors(cur))
            cur = pr[0] if pr else None
        parent[dname] = p_dev

    grid = transfer.Grid(
        name=name,
        devices=[dev_names[ln] for ln in order],
        line={dev_names[ln]: ln for ln in order},
        parent=parent,
        members=members,
        kw={dev_names[ln]: sum(kw_bus.get(x, 0.0) for x in members[dev_names[ln]]) for ln in order},
    )
    return grid, cycles


def _select_primary_buses(grid: transfer.Grid, head_kv_ll: float, max_buses: int, seed: int) -> tuple[dict[str, list[str]], int]:
    """Filter to primary buses (kV_LL >= 1.0 kV for MV feeders; all buses for LV feeders) and
    apply deterministic stratified sampling across zones when count > max_buses."""
    is_mv = head_kv_ll >= 1.0
    eligible: dict[str, list[str]] = {}
    for d in grid.devices:
        bs = []
        for b in grid.members[d]:
            ph = feeder.bus_phases(b)
            if not ph:
                continue
            kv = _bus_kv_ll(b)
            if is_mv and kv < 1.0:
                continue
            bs.append(b)
        eligible[d] = sorted(bs)

    total_eligible = sum(len(v) for v in eligible.values())
    if total_eligible <= max_buses:
        return eligible, total_eligible

    rng = np.random.default_rng(seed)
    # Allocate at least MIN_BUSES_PER_ZONE per zone (capped by zone size), remainder proportional
    alloc = {d: min(len(eligible[d]), MIN_BUSES_PER_ZONE) for d in grid.devices}
    used = sum(alloc.values())
    rem = max(0, max_buses - used)
    if rem > 0:
        leftovers = {d: max(0, len(eligible[d]) - alloc[d]) for d in grid.devices}
        tot_left = sum(leftovers.values())
        if tot_left > 0:
            raw = {d: rem * leftovers[d] / tot_left for d in grid.devices}
            add = {d: min(leftovers[d], int(math.floor(raw[d]))) for d in grid.devices}
            for d in grid.devices:
                alloc[d] += add[d]
            spare = max_buses - sum(alloc.values())
            frac_order = sorted(grid.devices, key=lambda d: (-(raw[d] - add[d]), d))
            for d in frac_order:
                if spare <= 0:
                    break
                if alloc[d] < len(eligible[d]):
                    alloc[d] += 1
                    spare -= 1

    sampled: dict[str, list[str]] = {}
    for d in grid.devices:
        pool = eligible[d]
        k = alloc[d]
        if k >= len(pool):
            sampled[d] = list(pool)
        elif k > 0:
            idx = sorted(rng.choice(len(pool), size=k, replace=False).tolist())
            sampled[d] = [pool[i] for i in idx]
        else:
            sampled[d] = []
    return sampled, total_eligible


def _measure_signal_to_load(grid: transfer.Grid, sampled_members: dict[str, list[str]]) -> dict:
    """Measure nominal feeder-head current and SLG median fault current across S2L_RESISTANCES."""
    head_dev = grid.devices[0]
    m_head = feeder.device_measurement(grid.line[head_dev])
    head_a = float(np.max(np.abs(m_head["i"])))
    head_kv_ln = float(_bus_kv_ll(m_head["bus"]) / math.sqrt(3.0))

    buses = [b for d in grid.devices for b in sampled_members[d]]
    first = buses[0]
    p0 = feeder.bus_phases(first)[0]
    feeder.cmd(f"New Fault.F_s2l phases=1 bus1={first}.{p0} bus2={first}.0 r=1 enabled=no")

    by_r: dict[str, dict] = {}
    for r in S2L_RESISTANCES:
        amps = []
        non_conv = 0
        for b in buses:
            for p in feeder.bus_phases(b):
                feeder.cmd(f"Edit Fault.F_s2l phases=1 bus1={b}.{p} bus2={b}.0 r={r} enabled=yes")
                ok = feeder.solve(controls=False)
                if not ok:
                    non_conv += 1
                    continue
                dss.Circuit.SetActiveElement("Fault.F_s2l")
                raw = dss.CktElement.CurrentsMagAng()
                if raw:
                    amps.append(float(raw[0]))
        feeder.cmd("Edit Fault.F_s2l enabled=no")
        if amps:
            med = float(np.median(amps))
            by_r[str(r)] = {
                "n": len(amps),
                "non_converged": non_conv,
                "fault_current_a_median": round(med, 3),
                "share_of_head_median": round(med / max(head_a, 1e-6), 5),
            }
        else:
            by_r[str(r)] = {"n": 0, "non_converged": non_conv, "fault_current_a_median": None, "share_of_head_median": None}
    feeder.solve(controls=True)
    return {
        "head_device": head_dev,
        "head_line": grid.line[head_dev],
        "head_current_a": round(head_a, 2),
        "head_kv_ln": round(head_kv_ln, 3),
        "head_kv_ll": round(head_kv_ln * math.sqrt(3.0), 3),
        "by_resistance": by_r,
    }


def _phase_acc(ds: tm.GraphDataset, pred: np.ndarray) -> float | None:
    mask = np.isin(ds.ftype, PHASE_FAULT_TYPES)
    if not mask.any():
        return None
    return round(float((pred[mask] == ds.y[mask]).mean()), 4)


def evaluate_one(name: str, base_gbdt, base_gnn, seed: int = 0) -> dict:
    t0 = time.time()
    spec = FEEDER_SPECS[name]
    print(f"\n=== [{name}] {spec['label']} ===", flush=True)

    if spec["master"] is None:
        return {
            "feeder": name,
            "label": spec["label"],
            "family": spec["family"],
            "status": "not_available",
            "verdict": "Not available",
            "reason": "No official OpenDSS test circuit in dss-extensions/electricdss-tst; not fabricated.",
            "runtime_s": round(time.time() - t0, 2),
        }

    conv, root, freq, tot_kw = _compile_feeder(spec)
    n_total_buses = int(dss.Circuit.NumBuses())
    n_lines = int(dss.Lines.Count())
    if not conv:
        return {
            "feeder": name,
            "label": spec["label"],
            "family": spec["family"],
            "status": "non_converged_base_case",
            "verdict": "Non-converged",
            "freq_hz": freq,
            "total_buses": n_total_buses,
            "total_lines": n_lines,
            "reason": f"Unmodified OpenDSS circuit failed base-case snapshot convergence in OpenDSSDirect 0.9.4 (iter={dss.Solution.Iterations()}).",
            "runtime_s": round(time.time() - t0, 2),
        }

    g = _energized_graph()
    comp = nx.node_connected_component(g, root) if root in g else set()
    sub = g.subgraph(comp)
    cycles = sub.number_of_edges() - sub.number_of_nodes() + 1 if comp else -1
    if cycles > 5:
        return {
            "feeder": name,
            "label": spec["label"],
            "family": spec["family"],
            "status": "incompatible_meshed",
            "verdict": "Incompatible (meshed)",
            "freq_hz": freq,
            "total_buses": n_total_buses,
            "connected_buses": len(comp),
            "total_lines": n_lines,
            "nominal_kw": round(tot_kw, 1),
            "cycles": int(cycles),
            "reason": f"Heavily meshed secondary network ({cycles} closed cycles); radial tree PLACEMENT_RULE and tree-based ZoneTreeGNN do not apply.",
            "runtime_s": round(time.time() - t0, 2),
        }

    grid, _ = _general_placement_rule(name, g, root)
    head_m = feeder.device_measurement(grid.line[grid.devices[0]])
    head_kv_ll = _bus_kv_ll(head_m["bus"])
    sampled_members, total_eligible = _select_primary_buses(grid, head_kv_ll, spec["max_buses"], seed)
    n_sampled = sum(len(v) for v in sampled_members.values())

    print(
        f"  Compiled: {freq:.0f} Hz, {head_kv_ll:.2f} kV LL, {n_total_buses} buses "
        f"({total_eligible} primary eligible -> {n_sampled} sampled), {len(grid.devices)} zones, cycles={cycles}",
        flush=True,
    )

    s2l = _measure_signal_to_load(grid, sampled_members)
    print(
        f"  Signal-to-load: head={s2l['head_current_a']} A, "
        f"0.01Ω={s2l['by_resistance']['0.01']['fault_current_a_median']} A, "
        f"400Ω={s2l['by_resistance']['400.0']['fault_current_a_median']} A",
        flush=True,
    )

    # Build fault cases on sampled primary buses
    class _Z:
        members = sampled_members

    cases = faults.fault_cases(_Z)
    scenarios = int(spec["scenarios"])
    rng = np.random.default_rng(seed)
    base = feeder.base_loads()
    struct = transfer.structure(grid)
    first = next(b for d in grid.devices for b in sampled_members[d])
    p0 = feeder.bus_phases(first)[0]
    feeder.cmd(f"New Fault.F_eval phases=1 bus1={first}.{p0} bus2={first}.0 r=1 enabled=no")

    index = {d: i for i, d in enumerate(grid.devices)}
    bus_zone = grid.bus_zone
    X_list, y_list, meta = [], [], []

    def snap():
        clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
        return faults._perturb(clean, rng)

    for s in range(scenarios):
        for c in cases:
            mult = float(rng.uniform(*config.LOAD_MULT_RANGE))
            spread = np.clip(rng.normal(1.0, config.LOAD_SPREAD, len(base)), 0.3, 1.7)
            feeder.scale_loads(base, spread)
            feeder.set_load_level(mult)
            feeder.cmd("Edit Fault.F_eval enabled=no")
            ok_pre = feeder.solve(controls=True)
            pre = snap()
            feeder.cmd(f"Edit Fault.F_eval {c['spec']} enabled=yes")
            ok_post = feeder.solve(controls=False)
            if ok_pre and ok_post:
                X_list.append(transfer.node_features(grid, pre, snap(), struct))
                y_list.append(index[bus_zone[c["bus"]]])
                meta.append((c["bus"], c["ftype"], c["phases"], c["r"], s, mult, True))
            else:
                meta.append((c["bus"], c["ftype"], c["phases"], c["r"], s, mult, False))
        print(f"  scenario {s + 1}/{scenarios}: {len(X_list)}/{len(meta)} converged ({time.time() - t0:.1f}s)", flush=True)

    feeder.cmd("Edit Fault.F_eval enabled=no")
    feeder.scale_loads(base, np.ones(len(base)))
    feeder.set_load_level(1.0)

    n_attempted = len(meta)
    n_conv = len(X_list)
    if n_conv == 0:
        return {
            "feeder": name,
            "label": spec["label"],
            "family": spec["family"],
            "status": "non_converged_faults",
            "verdict": "Non-converged",
            "runtime_s": round(time.time() - t0, 2),
        }

    conv_meta = [m for m in meta if m[6]]
    parent_idx = np.array([index[grid.parent[d]] if grid.parent[d] else -1 for d in grid.devices], dtype=np.int64)
    ds = tm.GraphDataset(
        feeder=name,
        X=np.stack(X_list).astype(np.float32),
        y=np.array(y_list, dtype=np.int64),
        parent=parent_idx,
        features=list(transfer.FEATURES),
        devices=list(grid.devices),
        bus=np.array([m[0] for m in conv_meta], dtype=str),
        ftype=np.array([m[1] for m in conv_meta], dtype=str),
        phases=np.array([m[2] for m in conv_meta], dtype=str),
        r=np.array([m[3] for m in conv_meta], dtype=float),
        scenario=np.array([m[4] for m in conv_meta], dtype=np.int64),
        load_mult=np.array([m[5] for m in conv_meta], dtype=float),
    )

    fpi_res = tm.cv_fpi(ds)
    gbdt_res = tm.eval_zero_shot_gbdt(base_gbdt, ds, eval_missing=True)
    gnn_res = tm.eval_zero_shot_gnn(base_gnn, ds, eval_missing=True)

    def _pack(res: dict) -> dict:
        out = {k: v for k, v in res.items() if k != "pred"}
        out["phase_faults_accuracy"] = _phase_acc(ds, res["pred"])
        return out

    fpi_out = _pack(fpi_res)
    gbdt_out = _pack(gbdt_res)
    gnn_out = _pack(gnn_res)

    best_acc = max(gbdt_out["accuracy"], gnn_out["accuracy"])
    best_model = "per_node_gbdt" if gbdt_out["accuracy"] >= gnn_out["accuracy"] else "gnn"
    best_phase = max(gbdt_out["phase_faults_accuracy"] or 0.0, gnn_out["phase_faults_accuracy"] or 0.0)
    margin = best_acc - fpi_out["accuracy"]

    if margin >= 0.15 and best_acc >= 0.80:
        verdict = "Pass"
    elif margin >= 0.10 or best_phase >= 0.85:
        verdict = "Partial"
    else:
        verdict = "Fail"

    print(
        f"  DONE [{name}] FPI={fpi_out['accuracy']:.4f} | GBDT={gbdt_out['accuracy']:.4f} "
        f"(phase={gbdt_out['phase_faults_accuracy']}, SLG={gbdt_out['by_fault_type'].get('SLG')}) | "
        f"GNN={gnn_out['accuracy']:.4f} (phase={gnn_out['phase_faults_accuracy']}, SLG={gnn_out['by_fault_type'].get('SLG')}) "
        f"-> {verdict}",
        flush=True,
    )

    return {
        "feeder": name,
        "label": spec["label"],
        "family": spec["family"],
        "description": spec["description"],
        "status": "semi_looped_evaluated" if cycles > 0 else "evaluated",
        "verdict": verdict,
        "best_zero_shot_model": best_model,
        "freq_hz": freq,
        "head_kv_ll": round(head_kv_ll, 3),
        "total_buses": n_total_buses,
        "primary_eligible_buses": total_eligible,
        "sampled_buses": n_sampled,
        "sampling_mode": "all_primary" if n_sampled == total_eligible else f"stratified_{n_sampled}_seed{seed}",
        "zones": len(grid.devices),
        "devices": list(grid.devices),
        "cycles": int(cycles),
        "nominal_kw": round(tot_kw, 1),
        "scenarios": scenarios,
        "events_attempted": n_attempted,
        "events_converged": n_conv,
        "converged_share": round(n_conv / max(n_attempted, 1), 4),
        "signal_to_load": s2l,
        "fpi": fpi_out,
        "zero_shot_gbdt": gbdt_out,
        "zero_shot_gnn": gnn_out,
        "margin_over_fpi": round(margin, 4),
        "runtime_s": round(time.time() - t0, 1),
    }


def merge_results(dirs: list[Path]) -> None:
    """Merge per-feeder JSONs from parallel Kaggle outputs with existing 123/34/37 results."""
    feeders: dict[str, dict] = {}
    for d in dirs:
        for p in sorted(d.rglob("feeder_*.json")):
            obj = json.loads(p.read_text(encoding="utf-8"))
            feeders[obj["feeder"]] = obj

    # Include the 3 existing reference feeders from results/transfer/ for a unified master table
    ref_rows = []
    p2 = json.loads((transfer.SUMMARY_DIR / "phase2_ieee123.json").read_text(encoding="utf-8"))
    p34 = json.loads((transfer.SUMMARY_DIR / "phase3_ieee34.json").read_text(encoding="utf-8"))
    p37 = json.loads((transfer.SUMMARY_DIR / "phase3_ieee37.json").read_text(encoding="utf-8"))
    s2l = json.loads((transfer.SUMMARY_DIR / "signal_to_load.json").read_text(encoding="utf-8"))

    ref_rows.append({
        "feeder": "ieee123", "label": "IEEE 123-bus (Train, 5-fold CV)", "family": "IEEE",
        "status": "reference_train_cv", "verdict": "Train CV",
        "freq_hz": 60.0, "head_kv_ll": 4.16, "zones": 10, "cycles": 0,
        "events_converged": p2["events"],
        "head_current_a": s2l["feeders"]["ieee123"]["head_current_a"],
        "slg_400_a": s2l["feeders"]["ieee123"]["by_resistance"]["400.0"]["fault_current_a"]["median"],
        "fpi_acc": p2["models"]["fpi"]["accuracy"],
        "gbdt_acc": p2["models"]["per_node_gbdt"]["accuracy"],
        "gnn_acc": p2["models"]["gnn"]["accuracy"],
        "gbdt_phase": None, "gnn_phase": None,
        "gbdt_slg": p2["models"]["per_node_gbdt"]["by_fault_type"]["SLG"],
        "gnn_slg": p2["models"]["gnn"]["by_fault_type"]["SLG"],
        "gbdt_miss": p2["models"]["per_node_gbdt"]["missing_sensor_mean"],
        "gnn_miss": p2["models"]["gnn"]["missing_sensor_mean"],
    })
    for fid, lab, kv, obj in (
        ("ieee34", "IEEE 34-bus (Unseen overhead)", 24.9, p34),
        ("ieee37", "IEEE 37-bus (Unseen underground delta)", 4.8, p37),
    ):
        ref_rows.append({
            "feeder": fid, "label": lab, "family": "IEEE",
            "status": "reference_evaluated",
            "verdict": "Pass" if fid == "ieee34" else "Partial (phase only)",
            "freq_hz": 60.0, "head_kv_ll": kv, "zones": len(obj["devices"]), "cycles": 0,
            "events_converged": obj["events"],
            "head_current_a": s2l["feeders"][fid]["head_current_a"],
            "slg_400_a": s2l["feeders"][fid]["by_resistance"]["400.0"]["fault_current_a"]["median"],
            "fpi_acc": obj["fpi"]["accuracy"],
            "gbdt_acc": obj["zero_shot"]["per_node_gbdt"]["accuracy"],
            "gnn_acc": obj["zero_shot"]["gnn"]["accuracy"],
            "gbdt_phase": obj["zero_shot"]["per_node_gbdt"].get("phase_faults_accuracy"),
            "gnn_phase": obj["zero_shot"]["gnn"].get("phase_faults_accuracy"),
            "gbdt_slg": obj["zero_shot"]["per_node_gbdt"]["by_fault_type"]["SLG"],
            "gnn_slg": obj["zero_shot"]["gnn"]["by_fault_type"]["SLG"],
            "gbdt_miss": obj["zero_shot"]["per_node_gbdt"]["missing_sensor_mean"],
            "gnn_miss": obj["zero_shot"]["gnn"]["missing_sensor_mean"],
        })

    order = [
        "ieee13", "eu_lv", "ieee8500", "epri_ckt5", "epri_ckt7", "epri_ckt24",
        "epri_j1", "epri_k1", "epri_m1", "ieee342", "ieee9500", "cigre_mv",
    ]
    ordered_new = [feeders[k] for k in order if k in feeders] + [v for k, v in feeders.items() if k not in order]

    evaluated = [x for x in ordered_new if x["status"] in ("evaluated", "semi_looped_evaluated")]
    summary = {
        "phase": "multi_feeder_zero_shot_benchmark",
        "simulation_only": True,
        "plan": "research/multi-feeder-benchmark/PLAN.md",
        "train_feeder": "ieee123",
        "frozen_models": ["models/transfer/per_node_gbdt_ieee123.pkl", "models/transfer/gnn_ieee123.pt"],
        "counts": {
            "reference_feeders": len(ref_rows),
            "new_feeders_audited": len(ordered_new),
            "new_feeders_evaluated": len(evaluated),
            "total_unseen_evaluated": 2 + len(evaluated),
            "pass": sum(1 for x in evaluated if x["verdict"] == "Pass"),
            "partial": sum(1 for x in evaluated if x["verdict"] == "Partial"),
            "fail": sum(1 for x in evaluated if x["verdict"] == "Fail"),
            "out_of_scope_or_unavailable": len(ordered_new) - len(evaluated),
        },
        "reference_feeders": ref_rows,
        "new_feeders": ordered_new,
    }

    out_json = transfer.SUMMARY_DIR / "multi_feeder_benchmark.json"
    out_csv = transfer.SUMMARY_DIR / "multi_feeder_benchmark.csv"
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    # Write clean CSV evidence table across all feeders
    cols = [
        "feeder", "label", "family", "status", "verdict", "freq_hz", "head_kv_ll", "zones",
        "cycles", "events_converged", "head_current_a", "slg_400_a",
        "fpi_acc", "gbdt_zero_shot_acc", "gnn_zero_shot_acc",
        "gbdt_phase_acc", "gnn_phase_acc", "gbdt_slg_acc", "gnn_slg_acc",
        "gbdt_missing_sensor", "gnn_missing_sensor",
    ]
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in ref_rows:
            w.writerow({
                "feeder": r["feeder"], "label": r["label"], "family": r["family"],
                "status": r["status"], "verdict": r["verdict"], "freq_hz": r["freq_hz"],
                "head_kv_ll": r["head_kv_ll"], "zones": r["zones"], "cycles": r["cycles"],
                "events_converged": r["events_converged"], "head_current_a": r["head_current_a"],
                "slg_400_a": r["slg_400_a"], "fpi_acc": r["fpi_acc"],
                "gbdt_zero_shot_acc": r["gbdt_acc"], "gnn_zero_shot_acc": r["gnn_acc"],
                "gbdt_phase_acc": r["gbdt_phase"], "gnn_phase_acc": r["gnn_phase"],
                "gbdt_slg_acc": r["gbdt_slg"], "gnn_slg_acc": r["gnn_slg"],
                "gbdt_missing_sensor": r["gbdt_miss"], "gnn_missing_sensor": r["gnn_miss"],
            })
        for x in ordered_new:
            is_ev = x["status"] in ("evaluated", "semi_looped_evaluated")
            w.writerow({
                "feeder": x["feeder"], "label": x["label"], "family": x["family"],
                "status": x["status"], "verdict": x["verdict"],
                "freq_hz": x.get("freq_hz"), "head_kv_ll": x.get("head_kv_ll"),
                "zones": x.get("zones"), "cycles": x.get("cycles"),
                "events_converged": x.get("events_converged"),
                "head_current_a": x["signal_to_load"]["head_current_a"] if is_ev else None,
                "slg_400_a": x["signal_to_load"]["by_resistance"]["400.0"]["fault_current_a_median"] if is_ev else None,
                "fpi_acc": x["fpi"]["accuracy"] if is_ev else None,
                "gbdt_zero_shot_acc": x["zero_shot_gbdt"]["accuracy"] if is_ev else None,
                "gnn_zero_shot_acc": x["zero_shot_gnn"]["accuracy"] if is_ev else None,
                "gbdt_phase_acc": x["zero_shot_gbdt"].get("phase_faults_accuracy") if is_ev else None,
                "gnn_phase_acc": x["zero_shot_gnn"].get("phase_faults_accuracy") if is_ev else None,
                "gbdt_slg_acc": x["zero_shot_gbdt"]["by_fault_type"].get("SLG") if is_ev else None,
                "gnn_slg_acc": x["zero_shot_gnn"]["by_fault_type"].get("SLG") if is_ev else None,
                "gbdt_missing_sensor": x["zero_shot_gbdt"].get("missing_sensor_mean") if is_ev else None,
                "gnn_missing_sensor": x["zero_shot_gnn"].get("missing_sensor_mean") if is_ev else None,
            })

    provenance.record("transfer_multi_feeder_benchmark", [out_json, out_csv])
    print(f"Merged {len(ordered_new)} new feeders + {len(ref_rows)} reference feeders -> {out_json} & {out_csv}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feeders", type=str, default="", help="Comma-separated feeder names to evaluate")
    ap.add_argument("--out-dir", type=str, default="results/transfer/multi_feeder_parts")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--merge", type=str, default="", help="Comma-separated directories of feeder_*.json to merge")
    args = ap.parse_args()

    if args.merge:
        dirs = [Path(p.strip()) for p in args.merge.split(",") if p.strip()]
        merge_results(dirs)
        return

    torch.set_num_threads(2)
    base_gbdt, base_gnn, _ = tm.load_frozen_models()
    names = [s.strip() for s in args.feeders.split(",") if s.strip()]
    if not names:
        names = list(FEEDER_SPECS.keys())
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for name in names:
        res = evaluate_one(name, base_gbdt, base_gnn, seed=args.seed)
        p = out_dir / f"feeder_{name}.json"
        p.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
        print(f"  Wrote {p}", flush=True)


if __name__ == "__main__":
    main()
