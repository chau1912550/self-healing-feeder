"""Fault isolation and service restoration (the "I" and "SR" in FLISR).

Sequence for a fault in zone Zf:
  1. The feeder-head recloser trips and locks out (whole feeder dark).
  2. Isolate: open the device feeding Zf and every device leaving Zf.
  3. Re-close the head: zones upstream of Zf come back.
  4. Zones downstream of Zf form dark "islands". For each island, try tie
     switches; close one only if a power flow shows every energized node within
     ANSI C84.1 Range A and every line under its emergency rating. If the whole
     island does not fit, try smaller connected pieces and keep the largest.

A stuck switch (one that fails to open when told to) widens step 2: the zone on its other side is
isolated together with Zf, and the next devices out are opened instead (isolated_area).
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
    area: set[str] = field(default_factory=set)           # zones isolated (Zf, plus one more if a switch stuck)
    stuck: str | None = None                              # device that failed to open, if any


def _tie_zone(zones: Zones, bus: str) -> str:
    return zones.bus_zone.get(bus, EXTERNAL)


def isolated_area(zones: Zones, zf: str, stuck: str | None = None) -> tuple[str, set[str]]:
    """(top zone, zones isolated) for a fault in zone Zf. A stuck device on Zf's boundary
    joins the zone on its other side to the isolated area: Zf's own device -> the parent zone,
    a device leaving Zf -> that child zone. Devices are named after the zone they feed."""
    if stuck is None:
        return zf, {zf}
    if stuck == zf and zones.parent[zf]:
        return zones.parent[zf], {zf, zones.parent[zf]}
    if stuck in zones.children(zf):
        return zf, {zf, stuck}
    raise ValueError(f"{stuck} is not a device on the boundary of zone {zf}")


def first_device(zones: Zones, zf: str) -> str:
    """The device opened first to isolate Zf: the one feeding it, or for zone Sw1 (whose
    feeder-head recloser is already open after lockout) the first device leaving it."""
    return zf if zones.parent[zf] else zones.children(zf)[0]


def area_exits(zones: Zones, area: set[str]) -> list[str]:
    """Devices leaving the isolated area (each feeds a zone outside it)."""
    return [c for z in zones.names if z in area for c in zones.children(z) if c not in area]


def islands_after_isolation(zones: Zones, zf: str, area: set[str] | None = None) -> list[list[str]]:
    exits = zones.children(zf) if area is None else area_exits(zones, area)
    return [[c] + zones.downstream(c) for c in exits]


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
                 ties_closed: list[str], area: set[str] | None = None) -> None:
    """Set every device: open around Zf (or around the isolated area, whose top zone is zf), and
    inside dark islands close a device only when both zones it joins are being energized."""
    area = {zf} if area is None else area
    feeder.set_normal_configuration()
    dark = {z for isl in islands_after_isolation(zones, zf, area) for z in isl}
    feeder.open_device(zf)
    for c in area_exits(zones, area):
        feeder.open_device(c)
    for z in dark:
        p = zones.parent[z]
        if z in energized_extra and p in energized_extra:
            feeder.close_device(z)
        elif p not in area:
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


REASONS = ("undervoltage", "overvoltage", "overload", "nonconverged")


def classify(res: dict) -> list[str]:
    """Why a power-flow check failed: a subset of REASONS, empty if it passed.
    A run that did not converge has meaningless voltages, so it gets only that label."""
    if not res["converged"]:
        return ["nonconverged"]
    out = []
    if res["vmin"] < config.V_MIN_PU - config.V_TOL:
        out.append("undervoltage")
    if res["vmax"] > config.V_MAX_PU + config.V_TOL:
        out.append("overvoltage")
    if res["overloads"]:
        out.append("overload")
    return out


def plan_restoration(zones: Zones, zf: str, stuck: str | None = None) -> Plan:
    """Isolation and restoration for a fault in zone Zf. `stuck` names a device on Zf's boundary
    that fails to open (failure injection); None is the normal case used by the study."""
    fault_zone = zf
    zf, area = isolated_area(zones, fault_zone, stuck)     # zf is now the top of the isolated area
    plan = Plan(fault_zone=fault_zone, opened=[zf] + area_exits(zones, area), area=set(area), stuck=stuck)
    plan.steps.append(f"Feeder-head recloser Sw1 trips and locks out (fault in zone {fault_zone}).")
    if stuck:
        plan.steps.append(f"{stuck} is stuck and does not open: zone {', '.join(sorted(area - {fault_zone}))} "
                          f"is isolated with zone {fault_zone}.")
    plan.steps.append("Isolate: open " + ", ".join(plan.opened) + ".")
    islands = islands_after_isolation(zones, zf, area)
    upstream = set(zones.names) - area - {z for isl in islands for z in isl}
    if zf != "Sw1":
        plan.steps.append("Re-close Sw1: zones " + ", ".join(sorted(upstream)) + " restored.")
    energized = set(upstream)
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
                if outside in area or (outside != EXTERNAL and outside not in energized):
                    continue
                island = next(isl for isl in islands if inside in isl)
                subsets = connected_subsets(zones, island, inside)
                subsets.sort(key=lambda s: -sum(zones.kw[z] for z in s))
                for subset in subsets:
                    trial = energized | subset
                    apply_states(zones, zf, trial - upstream, used_ties + [tie], area)
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
    apply_states(zones, zf, energized - upstream, used_ties, area)
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
        if z == zf or z in plan.area:
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
