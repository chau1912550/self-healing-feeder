"""Maps of every test feeder for the study page: bus positions, lines and switching zones.

For each circuit used in the study it compiles the official OpenDSS model in data/feeder/, places the
switching devices with the same rule the benchmark used (IEEE 123-bus keeps the study's own devices),
and writes bus coordinates, energized lines, zones (parent device, kW, bus count) and the head bus.
Where a model has no bus coordinates for most buses, a layered tree layout is used and flagged.

    .venv\\Scripts\\python scripts\\export_feeder_maps.py          # about a minute, no fault simulation

Writes results/feeders/feeder_maps.json with a run record. Simulation models only; drawing data, no results.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import networkx as nx
import opendssdirect as dss

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from shf import config, feeder, provenance, transfer  # noqa: E402
import multi_feeder_eval as mfe  # noqa: E402

OUT = config.RESULTS / "feeders" / "feeder_maps.json"
ORDER = ["ieee123", "ieee34", "ieee37", "ieee13", "eu_lv", "ieee8500",
         "epri_ckt5", "epri_ckt7", "epri_ckt24", "epri_j1", "epri_k1", "epri_m1"]
LABELS = {"ieee123": "IEEE 123-bus", "ieee34": "IEEE 34-bus", "ieee37": "IEEE 37-bus"}
MIN_COORD_SHARE = 0.15         # below this share of buses with coordinates, use a tree layout instead
COORD_FILES = {"ieee123": config.ROOT / "data" / "feeder" / "ieee123" / "BusCoords.dat",
               "ieee34": config.ROOT / "data" / "feeder" / "ieee34" / "IEEE34_BusXY.csv"}


def _coords(buses: list[str]) -> tuple[dict[str, tuple[float, float]], float]:
    xy = {}
    for b in buses:
        dss.Circuit.SetActiveBus(b)
        if dss.Bus.Coorddefined():
            x, y = float(dss.Bus.X()), float(dss.Bus.Y())
            if x != 0.0 or y != 0.0:
                xy[b] = (x, y)
    return xy, (len(xy) / len(buses) if buses else 0.0)


def _tree_layout(tree: nx.DiGraph, root: str) -> dict[str, tuple[float, float]]:
    """Layered layout: x = depth, y = leaf order (parents centred over their children)."""
    pos, nxt = {}, [0.0]

    def place(n: str, depth: int) -> float:
        kids = list(tree.successors(n))
        if not kids:
            y = nxt[0]
            nxt[0] += 1.0
        else:
            ys = [place(k, depth + 1) for k in kids]
            y = sum(ys) / len(ys)
        pos[n] = (float(depth), -y)
        return y

    sys.setrecursionlimit(max(10000, 4 * tree.number_of_nodes()))
    place(root, 0)
    return pos


def _pack(name: str, label: str, grid: transfer.Grid, g: nx.Graph, root: str, hz: float) -> dict:
    zone_of = {b: z for z, bs in grid.members.items() for b in bs}
    buses = sorted(set(g.nodes))
    if name in COORD_FILES:
        dss.Text.Command(f'BusCoords "{COORD_FILES[name]}"')
    xy, share = _coords(buses)
    layout = "bus coordinates"
    if MIN_COORD_SHARE <= share < 1.0:
        # buses without coordinates (mostly secondary drops) are drawn at their nearest upstream bus that has one
        comp = nx.node_connected_component(g, root)
        tree = nx.bfs_tree(g.subgraph(comp), root)
        for b in nx.topological_sort(tree):
            if b not in xy:
                p = next(iter(tree.predecessors(b)), None)
                if p is not None and p in xy:
                    xy[b] = xy[p]
        layout = "bus coordinates; buses without one drawn at their nearest upstream bus"
    if share < MIN_COORD_SHARE:
        comp = nx.node_connected_component(g, root)
        xy = _tree_layout(nx.bfs_tree(g.subgraph(comp), root), root)
        layout = "tree layout (model has too few bus coordinates)"
    keep = [b for b in buses if b in xy]
    xs, ys = [xy[b][0] for b in keep], [xy[b][1] for b in keep]
    x0, y0, span = min(xs), min(ys), max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    idx = {b: i for i, b in enumerate(keep)}
    zone_idx = {z: i for i, z in enumerate(grid.devices)}
    bus_rows = [[b, round(1000 * (xy[b][0] - x0) / span), round(1000 * (xy[b][1] - y0) / span),
                 zone_idx.get(zone_of.get(b), -1)] for b in keep]
    edges = []
    for u, v in g.edges():
        if u in idx and v in idx:
            z = zone_of.get(v, zone_of.get(u))
            edges.append([idx[u], idx[v], zone_idx.get(z, -1)])
    head_bus = None
    first = grid.devices[0]
    for b in grid.members[first]:
        head_bus = b
        break
    dss.Circuit.SetActiveBus(root)
    kv_root = float(dss.Bus.kVBase()) * 3 ** 0.5
    zones = []
    for z in grid.devices:
        start = None
        line = grid.line[z]
        for u, v, d in g.edges(data=True):
            if d.get("name") == line.lower():
                start = v if zone_of.get(v) == z else u
                break
        dss.Circuit.SetActiveBus(start or grid.members[z][0])
        zones.append({"name": z, "parent": grid.parent.get(z), "kw": round(float(grid.kw.get(z, 0.0)), 1),
                      "buses": len(grid.members[z]), "line": line, "start": idx.get(start),
                      "kv_ll": round(float(dss.Bus.kVBase()) * 3 ** 0.5, 3)})
    return {"label": label, "hz": hz, "root": root, "root_kv_ll": round(kv_root, 3), "layout": layout,
            "buses_in_model": len(buses), "buses_drawn": len(keep), "coord_share": round(share, 4),
            "head_bus": idx.get(head_bus), "zones": zones, "buses": bus_rows, "edges": edges}


def main() -> None:
    t0 = time.time()
    out = {"simulation_only": True, "what": "OpenDSS test-feeder drawing data: bus positions, energized lines, zones",
           "placement": f"IEEE 123-bus: study devices; others: PLACEMENT_RULE, branch share {transfer.BRANCH_SHARE}",
           "feeders": {}}
    for name in ORDER:
        ts = time.time()
        if name == "ieee123":
            transfer.load_feeder("ieee123")
            feeder.set_normal_configuration()
            feeder.solve(controls=True)
            grid, g, root = transfer.study_grid(), transfer.bus_graph(), "150"
            hz, label = float(dss.Solution.Frequency()), LABELS[name]
        elif name in ("ieee34", "ieee37"):
            transfer.load_feeder(name)
            grid, g, root = transfer.placement_rule(name), transfer.bus_graph(), transfer.FEEDERS[name]["root"]
            hz, label = float(dss.Solution.Frequency()), LABELS[name]
        else:
            spec = mfe.FEEDER_SPECS[name]
            conv, root, hz, _ = mfe._compile_feeder(spec)
            if not conv:
                print(f"{name}: base case did not converge, skipped")
                continue
            g = mfe._energized_graph()
            grid, _ = mfe._general_placement_rule(name, g, root)
            label = spec["label"]
        if root not in g:
            root = next(iter(g.nodes))
        out["feeders"][name] = _pack(name, label, grid, g, root, hz)
        f = out["feeders"][name]
        print(f"{name:10s} zones {len(f['zones']):2d}  buses {f['buses_drawn']:5d}/{f['buses_in_model']:5d}  "
              f"coords {f['coord_share']:.2f}  {f['layout'][:16]}  [{time.time() - ts:.1f}s]")
    out["runtime_s"] = round(time.time() - t0, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n", encoding="utf-8")
    provenance.record("feeder_maps", [OUT])
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KiB) in {out['runtime_s']} s")


if __name__ == "__main__":
    main()
