"""Thin wrapper around OpenDSS (via OpenDSSDirect.py) for the IEEE 123-bus feeder.

OpenDSS keeps one global circuit in memory, so this module exposes plain
functions that act on "the" circuit instead of a class with its own state.
"""
from __future__ import annotations

import cmath
import math

import numpy as np
import opendssdirect as dss

from . import config

A = cmath.rect(1.0, 2 * math.pi / 3)  # 120-degree operator for sequence components


def cmd(text: str) -> str:
    """Run one OpenDSS command and raise if OpenDSS reports an error."""
    out = dss.Text.Command(text)
    return out or ""


def load_feeder() -> None:
    """Compile the IEEE 123-bus case plus our additions and solve the base case."""
    cmd("Clear")
    cmd(f'Redirect "{config.FEEDER_MASTER}"')
    for line in config.ADJACENT_FEEDER_DSS:
        cmd(line)
    cmd("Set VoltageBases=[4.16, 0.48]")
    cmd("CalcVoltageBases")
    _assign_ampacities()
    set_load_level(1.0)
    solve(controls=True)


def _assign_ampacities() -> None:
    for name in dss.Lines.AllNames():
        dss.Lines.Name(name)
        code = dss.Lines.LineCode()
        if code in config.LINECODE_AMPACITY:
            amps = config.LINECODE_AMPACITY[code]
        elif dss.Lines.IsSwitch():
            amps = config.SWITCH_AMPACITY
        else:
            continue
        dss.Lines.NormAmps(amps)
        dss.Lines.EmergAmps(amps * config.EMERGENCY_FACTOR)


def set_load_level(mult: float) -> None:
    cmd(f"Set LoadMult={mult}")


def base_loads() -> list[tuple[str, float, float]]:
    """(name, kW, kvar) of every spot load as defined in the IEEE case."""
    out = []
    for name in dss.Loads.AllNames():
        dss.Loads.Name(name)
        out.append((name, dss.Loads.kW(), dss.Loads.kvar()))
    return out


def scale_loads(base: list[tuple[str, float, float]], factors) -> None:
    """Scale each spot load individually (same factor on kW and kvar)."""
    for (name, kw, kvar), f in zip(base, factors):
        dss.Loads.Name(name)
        dss.Loads.kW(kw * f)
        dss.Loads.kvar(kvar * f)


def solve(controls: bool = True) -> bool:
    """Snapshot power flow. controls=False freezes regulator taps (fault studies)."""
    cmd("Set ControlMode=" + ("STATIC" if controls else "OFF"))
    cmd("Set Mode=Snapshot")
    # A regulator fed from its "load" side (after a tie closes) can run its tap
    # to the end stop; allow enough control iterations for that.
    cmd("Set MaxControlIter=100")
    try:
        dss.Solution.Solve()
    except Exception:  # OpenDSS raises on non-convergence / control hunting
        return False
    return bool(dss.Solution.Converged())


# ---------------------------------------------------------------------------
# Switch control
# ---------------------------------------------------------------------------
def open_device(name: str) -> None:
    # Ties are modeled open at terminal 2, sectionalizers we open at terminal 1.
    term = 2 if name in config.TIES else 1
    cmd(f"Open Line.{name} term={term}")


def close_device(name: str) -> None:
    cmd(f"Close Line.{name} term=1")
    cmd(f"Close Line.{name} term=2")


def set_normal_configuration() -> None:
    for name in config.SECTIONALIZERS:
        close_device(name)
    for name in config.TIES:
        open_device(name)
    cmd("Open Line.Sw8 term=2")


def is_closed(name: str) -> bool:
    dss.Circuit.SetActiveElement(f"Line.{name}")
    n = dss.CktElement.NumPhases()
    return not (dss.CktElement.IsOpen(1, 0) or dss.CktElement.IsOpen(2, 0)) and n > 0


# ---------------------------------------------------------------------------
# Measurements (what a recloser / automated switch would report to SCADA)
# ---------------------------------------------------------------------------
def device_measurement(name: str) -> dict:
    """Phase currents and voltages at the upstream terminal of a 3-phase device."""
    dss.Circuit.SetActiveElement(f"Line.{name}")
    nph = dss.CktElement.NumPhases()
    cur = dss.CktElement.Currents()
    i_ph = [complex(cur[2 * k], cur[2 * k + 1]) for k in range(nph)]
    bus = dss.CktElement.BusNames()[0].split(".")[0]
    dss.Circuit.SetActiveBus(bus)
    nodes = dss.Bus.Nodes()
    pu = dss.Bus.PuVoltage()
    v_by_node = {n: complex(pu[2 * k], pu[2 * k + 1]) for k, n in enumerate(nodes)}
    v_ph = [v_by_node.get(p, 0j) for p in (1, 2, 3)]
    ia, ib, ic = (i_ph + [0j, 0j, 0j])[:3]
    i0 = (ia + ib + ic) / 3
    i2 = (ia + A * A * ib + A * ic) / 3
    return {"i": np.array([ia, ib, ic]), "v": np.array(v_ph), "i0": i0, "i2": i2, "bus": bus}


def bus_phases(bus: str) -> list[int]:
    dss.Circuit.SetActiveBus(bus)
    return sorted(n for n in dss.Bus.Nodes() if n in (1, 2, 3))


def all_node_voltages_pu() -> dict[str, float]:
    names = dss.Circuit.AllNodeNames()
    mags = dss.Circuit.AllBusMagPu()
    return dict(zip(names, mags))


def load_kw_by_bus() -> dict[str, float]:
    """Nominal kW of each spot load, summed per bus (LoadMult not applied)."""
    out: dict[str, float] = {}
    for name in dss.Loads.AllNames():
        dss.Loads.Name(name)
        dss.Circuit.SetActiveElement(f"Load.{name}")
        bus = dss.CktElement.BusNames()[0].split(".")[0]
        out[bus] = out.get(bus, 0.0) + dss.Loads.kW()
    return out


def load_count_by_bus() -> dict[str, int]:
    out: dict[str, int] = {}
    for name in dss.Loads.AllNames():
        dss.Circuit.SetActiveElement(f"Load.{name}")
        bus = dss.CktElement.BusNames()[0].split(".")[0]
        out[bus] = out.get(bus, 0) + 1
    return out


def line_loading() -> dict[str, tuple[float, float, float]]:
    """Per line: (max phase current A, normal amps, emergency amps)."""
    out = {}
    for name in dss.Lines.AllNames():
        dss.Lines.Name(name)
        dss.Circuit.SetActiveElement(f"Line.{name}")
        nph = dss.CktElement.NumPhases()
        mags = dss.CktElement.CurrentsMagAng()[0::2][:nph]
        out[name] = (max(mags) if mags else 0.0, dss.Lines.NormAmps(), dss.Lines.EmergAmps())
    return out
