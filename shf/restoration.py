"""Fault isolation and service restoration (the "I" and "SR" in FLISR).

Sequence for a fault in zone Zf:
  1. The feeder-head recloser trips and locks out (whole feeder dark).
  2. Isolate: open the device feeding Zf and every device leaving Zf.
  3. Re-close the head: zones upstream of Zf come back.
  4. Zones downstream of Zf form dark "islands". For each island, try tie
     switches; close one only if a power flow shows every energized node within
     ANSI C84.1 Range A and every line under its emergency rating. If the whole
     island does not fit, try smaller connected pieces and keep the largest.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import config, feeder
from .topology import Zones, closed_graph_has_loop

EXTERNAL = "adjacent-feeder"


@dataclass
class Plan:
    fault_zone: str
    opened: list[str]                         # devices opened to isolate Zf
    closed_ties: list[str] = field(default_factory=list)
    shed_at: list[str] = field(default_factory=list)      # devices left open to limit pickup
    energized: set[str] = field(default_factory=set)      # zones with power at the end
    restored_by_tie: set[str] = field(default_factory=set)
    unserved: set[str] = field(default_factory=set)       # healthy zones still dark
    checks: list[dict] = field(default_factory=list)      # every power-flow check made
    steps: list[str] = field(default_factory=list)        # human-readable switching order


def _tie_zone(zones: Zones, bus: str) -> str:
    return zones.bus_zone.get(bus, EXTERNAL)


def islands_after_isolation(zones: Zones, zf: str) -> list[list[str]]:
    return [[c] + zones.downstream(c) for c in zones.children(zf)]


def connected_subsets(zones: Zones, island: list[str], entry: str) -> list[frozenset[str]]:
    """All connected sets of island zones that contain the tie entry zone."""
    nbrs = {z: set() for z in island}
    for z in island:
        p = zones.parent[z]
        if p in nbrs:
            nbrs[z].add(p)
            nbrs[p].add(z)
    out, frontier = {frozenset([entry])}, [frozenset([entry])]
    while frontier:
        nxt = []
        for s in frontier:
            for z in s:
                for n in nbrs[z] - s:
                    t = s | {n}
                    if t not in out:
                        out.add(t)
                        nxt.append(t)
        frontier = nxt
    return sorted(out, key=lambda s: -len(s))


def apply_states(zones: Zones, zf: str, energized_extra: set[str],
                 ties_closed: list[str]) -> None:
    """Set every device: open around Zf, and inside dark islands close a device
    only when both zones it joins are being energized."""
    feeder.set_normal_configuration()
    dark = {z for isl in islands_after_isolation(zones, zf) for z in isl}
    feeder.open_device(zf)
    for c in zones.children(zf):
        feeder.open_device(c)
    for z in dark:
        p = zones.parent[z]
        if z in energized_extra and p in energized_extra:
            feeder.close_device(z)
        elif p != zf:
            feeder.open_device(z)
    for t in ties_closed:
        feeder.close_device(t)


def check_power_flow(zones: Zones, energized: set[str]) -> dict:
    ok_conv = feeder.solve(controls=True)
    buses = {b for z in energized for b in zones.members[z]}
    v = feeder.all_node_voltages_pu()
    vals = [mag for node, mag in v.items() if node.split(".")[0] in buses]
    vmin, vmax = (min(vals), max(vals)) if vals else (1.0, 1.0)
    over = []
    for name, (amps, _norm, emerg) in feeder.line_loading().items():
        if emerg > 0 and amps > emerg:
            over.append((name, round(amps, 1), emerg))
    ok = (ok_conv and vmin >= config.V_MIN_PU - config.V_TOL
          and vmax <= config.V_MAX_PU + config.V_TOL and not over)
    return {"ok": ok, "converged": ok_conv, "vmin": vmin, "vmax": vmax, "overloads": over}


def plan_restoration(zones: Zones, zf: str) -> Plan:
    plan = Plan(fault_zone=zf, opened=[zf] + zones.children(zf))
    plan.steps.append(f"Feeder-head recloser Sw1 trips and locks out (fault in zone {zf}).")
    plan.steps.append("Isolate: open " + ", ".join(plan.opened) + ".")
    upstream = set(zones.names) - {zf} - {z for isl in islands_after_isolation(zones, zf) for z in isl}
    if zf != "Sw1":
        plan.steps.append("Re-close Sw1: zones " + ", ".join(sorted(upstream)) + " restored.")
    energized = set(upstream)
    islands = islands_after_isolation(zones, zf)
    dark = {z for isl in islands for z in isl}
    used_ties: list[str] = []

    # Greedy: each round, find the largest feasible pickup for every usable tie
    # and close the tie that restores the most kW. Repeat until nothing fits.
    while True:
        best = None
        for tie, (b1, b2) in zones.tie_ends.items():
            if tie in used_ties:
                continue
            z1, z2 = _tie_zone(zones, b1), _tie_zone(zones, b2)
            for inside, outside in ((z1, z2), (z2, z1)):
                if inside not in dark or inside in energized:
                    continue
                if outside == zf or (outside != EXTERNAL and outside not in energized):
                    continue
                island = next(isl for isl in islands if inside in isl)
                subsets = connected_subsets(zones, island, inside)
                subsets.sort(key=lambda s: -sum(zones.kw[z] for z in s))
                for subset in subsets:
                    trial = energized | subset
                    apply_states(zones, zf, trial - upstream, used_ties + [tie])
                    res = check_power_flow(zones, trial)
                    res.update(tie=tie, zones=sorted(subset))
                    plan.checks.append(res)
                    if res["ok"]:
                        kw = sum(zones.kw[z] for z in subset)
                        if best is None or kw > best[0]:
                            best = (kw, tie, outside, subset, res)
                        break
        if best is None:
            break
        _, tie, outside, subset, res = best
        energized |= subset
        used_ties.append(tie)
        plan.restored_by_tie |= set(subset)
        src = "adjacent feeder" if outside == EXTERNAL else f"zone {outside}"
        plan.steps.append(
            f"Close tie {tie} (from {src}): zones {', '.join(sorted(subset))} "
            f"restored; Vmin {res['vmin']:.3f} pu, Vmax {res['vmax']:.3f} pu.")
    plan.closed_ties = used_ties
    plan.energized = energized
    plan.unserved = dark - energized
    plan.shed_at = sorted(z for z in plan.unserved if zones.parent[z] in energized)
    if plan.unserved:
        plan.steps.append("Still dark until repair: zones " + ", ".join(sorted(plan.unserved)) + ".")
    # leave the circuit in its final restored state for inspection, then reset
    apply_states(zones, zf, energized - upstream, used_ties)
    final = check_power_flow(zones, energized)
    final["radial"] = not closed_graph_has_loop()
    plan.checks.append({**final, "tie": "final", "zones": sorted(energized)})
    return plan


def kw_minutes(zones: Zones, plan: Plan) -> dict:
    """Interrupted kW-minutes, conventional vs automated (timing in config)."""
    zf = plan.fault_zone
    repair = config.T_MANUAL_MIN + config.T_REPAIR_MIN
    conventional = 0.0
    automated = 0.0
    for z in zones.names:
        kw = zones.kw[z]
        if z == zf:
            conventional += kw * repair
            automated += kw * repair
        elif z in plan.unserved:
            # no tie can carry this zone within limits, so a crew could not
            # restore it before the repair either
            conventional += kw * repair
            automated += kw * repair
        else:
            conventional += kw * config.T_MANUAL_MIN
            automated += kw * config.T_AUTOMATED_MIN
    return {"conventional": conventional, "automated": automated}


def reset(zones: Zones) -> None:
    feeder.set_normal_configuration()
    feeder.solve(controls=True)
