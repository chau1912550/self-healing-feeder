"""Feeder graph, switching zones and the zone tree.

A *zone* is the set of buses between switching devices: if you open every
sectionalizer and tie, each connected piece of the feeder is one zone. A zone
is named after the device that feeds it in the normal configuration, e.g.
zone "Sw3" is everything downstream of switch Sw3 up to the next device.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
import opendssdirect as dss

from . import config, feeder


def _bus(name: str) -> str:
    return name.split(".")[0].lower()


def build_graph() -> nx.Graph:
    """Undirected graph of buses; each edge stores the OpenDSS element name."""
    g = nx.Graph()
    for kind in ("Line", "Transformer"):
        names = dss.Lines.AllNames() if kind == "Line" else dss.Transformers.AllNames()
        for name in names:
            dss.Circuit.SetActiveElement(f"{kind}.{name}")
            buses = [_bus(b) for b in dss.CktElement.BusNames()]
            u, v = buses[0], buses[1]
            g.add_edge(u, v, element=f"{kind}.{name}".lower(), name=name.lower())
    return g


@dataclass
class Zones:
    graph: nx.Graph
    bus_zone: dict[str, str]                     # bus -> zone name
    members: dict[str, list[str]]                # zone -> buses
    parent: dict[str, str | None]                # zone -> upstream zone (normal config)
    device_ends: dict[str, tuple[str, str]]      # device -> (upstream bus, downstream bus)
    tie_ends: dict[str, tuple[str, str]]         # tie -> (bus1, bus2)
    kw: dict[str, float] = field(default_factory=dict)
    load_points: dict[str, int] = field(default_factory=dict)

    @property
    def names(self) -> list[str]:
        return list(self.members)

    def children(self, zone: str) -> list[str]:
        return [z for z, p in self.parent.items() if p == zone]

    def downstream(self, zone: str) -> list[str]:
        """All zones below `zone` in the normal radial configuration (excluding itself)."""
        out, stack = [], list(self.children(zone))
        while stack:
            z = stack.pop()
            out.append(z)
            stack.extend(self.children(z))
        return out


def find_zones() -> Zones:
    g = build_graph()
    devices = {d.lower() for d in config.SECTIONALIZERS}
    ties = {t.lower() for t in config.TIES} | {"sw8"}

    # Normal radial tree: all sectionalizers closed, ties open.
    radial = g.copy()
    radial.remove_edges_from([(u, v) for u, v, d in g.edges(data=True) if d["name"] in ties])
    depth = nx.single_source_shortest_path_length(radial, config.SOURCE_BUS)

    device_ends, tie_ends = {}, {}
    for u, v, d in g.edges(data=True):
        if d["name"] in devices:
            up, down = (u, v) if depth[u] < depth[v] else (v, u)
            device_ends[_canonical(d["name"])] = (up, down)
        elif d["name"] in ties and d["name"] != "sw8":
            tie_ends[_canonical(d["name"])] = (u, v)

    cut = g.copy()
    cut.remove_edges_from([(u, v) for u, v, d in g.edges(data=True)
                           if d["name"] in devices or d["name"] in ties])
    bus_zone, members = {}, {}
    for dev, (up, down) in device_ends.items():
        comp = nx.node_connected_component(cut, down)
        buses = sorted(b for b in comp if b not in config.EXCLUDED_BUSES and not b.startswith("fdr2"))
        members[dev] = buses
        for b in comp:
            bus_zone[b] = dev
    parent = {dev: bus_zone.get(up) for dev, (up, _) in device_ends.items()}

    zones = Zones(g, bus_zone, members, parent, device_ends, tie_ends)
    kw_bus = feeder.load_kw_by_bus()
    cnt_bus = feeder.load_count_by_bus()
    for z, buses in members.items():
        zones.kw[z] = sum(kw_bus.get(b, 0.0) for b in buses)
        zones.load_points[z] = sum(cnt_bus.get(b, 0) for b in buses)
    return zones


def zone_line_length_kft(zones: Zones) -> dict[str, float]:
    """Conductor length per zone. Each line counts toward the zone of its
    downstream bus (so a device's own line belongs to the zone it feeds)."""
    depth = nx.single_source_shortest_path_length(zones.graph, config.SOURCE_BUS)
    out = {z: 0.0 for z in zones.names}
    for name in dss.Lines.AllNames():
        dss.Lines.Name(name)
        u, v = _bus(dss.Lines.Bus1()), _bus(dss.Lines.Bus2())
        down = v if depth.get(v, 0) >= depth.get(u, 0) else u
        z = zones.bus_zone.get(down)
        if z in out:
            out[z] += dss.Lines.Length()
    return out


def closed_graph_has_loop() -> bool:
    """True if the currently closed lines/transformers form a loop (non-radial).

    Single-phase regulator units of one bank (e.g. reg4a/b/c, all 160-160r)
    join the same two buses; they are one connection, not a loop, so parallel
    elements between the same bus pair collapse into one edge."""
    g = nx.Graph()
    for kind in ("Line", "Transformer"):
        names = dss.Lines.AllNames() if kind == "Line" else dss.Transformers.AllNames()
        for name in names:
            dss.Circuit.SetActiveElement(f"{kind}.{name}")
            if dss.CktElement.IsOpen(1, 0) or dss.CktElement.IsOpen(2, 0):
                continue
            b = [_bus(x) for x in dss.CktElement.BusNames()]
            g.add_edge(b[0], b[1])
    return len(nx.cycle_basis(g)) > 0


def _canonical(lower_name: str) -> str:
    """Map lower-case OpenDSS names back to the spelling used in config."""
    for name in list(config.SECTIONALIZERS) + list(config.TIES):
        if name.lower() == lower_name:
            return name
    return lower_name


def read_bus_coords() -> dict[str, tuple[float, float]]:
    path = config.FEEDER_MASTER.parent / "BusCoords.dat"
    coords = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3:
            coords[parts[0].lower()] = (float(parts[1]), float(parts[2]))
    return coords
