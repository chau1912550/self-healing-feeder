"""Figures for the README.

    python -m shf.report      # redraw only the feeder map (results/figures/feeder_zones.png)
"""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import opendssdirect as dss  # noqa: E402
import pandas as pd  # noqa: E402

from . import config, feeder  # noqa: E402
from .topology import Zones, find_zones, read_bus_coords  # noqa: E402

ZONE_COLORS = plt.get_cmap("tab10")


PHASE_WIDTH = {3: 3.0, 2: 2.0, 1: 1.1}   # line width shows how many phases a section carries
UNDERGROUND_CODES = {"12"}              # IEEE linecode 12 = 1/0 AA underground cable


def _line_info() -> dict[str, tuple[int, bool]]:
    """OpenDSS line name -> (number of phases, underground?)."""
    out = {}
    for name in dss.Lines.AllNames():
        dss.Lines.Name(name)
        out[name.lower()] = (dss.Lines.Phases(), dss.Lines.LineCode() in UNDERGROUND_CODES)
    return out


def _capacitors() -> list[tuple[str, str, float]]:
    """(name, bus, kvar) of every shunt capacitor bank."""
    out = []
    for name in dss.Capacitors.AllNames():
        dss.Capacitors.Name(name)   # the Capacitors interface has its own active element
        dss.Circuit.SetActiveElement(f"Capacitor.{name}")
        out.append((name.upper(), dss.CktElement.BusNames()[0].split(".")[0].lower(), dss.Capacitors.kvar()))
    return out


# Hand-placed label spots (feeder coordinates) so zone names sit in empty space, not on lines
ZONE_LABEL_XY = {"Sw1": (420, 1900), "L13": (1200, 2470), "Sw2": (2320, 1670), "Sw3": (2300, 2450),
                 "L45": (2470, 3420), "L61": (2860, 2420), "Sw4": (4370, 1110), "L68": (4350, 2260),
                 "Sw5": (3970, 3210), "L77": (2140, 580)}
DEVICE_LABEL_OFFSET = {"L68": (9, -4)}           # points; default is up and to the right
REGULATORS = {"9": ("Reg 2", (-10, 9)), "25": ("Reg 3", (-10, 9)), "160": ("Reg 4", (-12, -20))}


def feeder_geometry(zones: Zones) -> dict:
    """Everything the 3D feeder model on the report page draws, in feeder coordinates.
    Written to results/feeder_geometry.json next to the 2D map."""
    xy = read_bus_coords()
    lines = _line_info()
    devices = {d.lower() for d in config.SECTIONALIZERS}
    ties = {t.lower() for t in config.TIES} | {"sw8"}
    keep = lambda b: b in xy and b not in config.EXCLUDED_BUSES and not (b[-1] in "rs" and b[:-1] in xy)  # noqa: E731
    edges, tie_rows = [], []
    for u, v, d in zones.graph.edges(data=True):
        if u not in xy or v not in xy or d["element"].startswith("transformer"):
            continue
        if d["name"] in ties:
            tie_rows.append([d["name"].capitalize(), u, v])
            continue
        phases, ug = lines.get(d["name"], (3, False))
        z = zones.bus_zone.get(v) if d["name"] in devices else zones.bus_zone.get(u)
        edges.append([u, v, z, phases, int(ug)])
    if "450" in xy:
        tie_rows.append(["Sw9", "450", None])   # leads off the map to the adjacent feeder
    dev_rows = []
    for name, (up, down) in zones.device_ends.items():
        f = 0.7 if name == "Sw1" else 0.5
        x = xy[up][0] + f * (xy[down][0] - xy[up][0])
        y = xy[up][1] + f * (xy[down][1] - xy[up][1])
        kind = "recloser" if name == "Sw1" else "ieee" if name.startswith("Sw") else "added"
        dev_rows.append([name, kind, round(x, 1), round(y, 1), zones.bus_zone.get(down)])
    return {
        "buses": {b: list(p) for b, p in xy.items() if keep(b)},
        "bus_zone": {b: zones.bus_zone.get(b) for b in xy if keep(b)},
        "loads": {b: round(k, 1) for b, k in feeder.load_kw_by_bus().items() if b in xy},
        "edges": edges, "ties": tie_rows, "devices": dev_rows,
        "regs": [[t, b, *xy[b]] for b, (t, _) in REGULATORS.items() if b in xy],
        "caps": [[n, b, kvar, *xy[b]] for n, b, kvar in _capacitors() if b in xy],
        "source": [config.SOURCE_BUS, *xy[config.SOURCE_BUS]],
        "zones": [{"name": z, "color": matplotlib.colors.to_hex(ZONE_COLORS(i % 10)),
                   "label": list(ZONE_LABEL_XY.get(z, xy[zones.members[z][0]]))} for i, z in enumerate(zones.names)],
    }


def feeder_map(zones: Zones, path) -> None:
    """One-line map of the feeder: zones, phases, switching devices, ties, regulators,
    capacitors, loads and bus numbers. Needs the feeder loaded in OpenDSS. Also writes
    results/feeder_geometry.json for the 3D model on the report page."""
    (config.RESULTS / "feeder_geometry.json").write_text(json.dumps(feeder_geometry(zones)), encoding="utf-8")
    xy = read_bus_coords()
    color = {z: ZONE_COLORS(i % 10) for i, z in enumerate(zones.names)}
    lines = _line_info()
    devices = {d.lower() for d in config.SECTIONALIZERS}
    ties = {t.lower() for t in config.TIES} | {"sw8"}   # Sw8: IEEE 1-phase tie, kept open and unused
    fig, ax = plt.subplots(figsize=(16, 10.5))
    mid = lambda a, b: ((xy[a][0] + xy[b][0]) / 2, (xy[a][1] + xy[b][1]) / 2)  # noqa: E731
    label_box = dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85)

    # --- line sections, coloured by zone; width = phases; dashed = underground cable
    for u, v, d in zones.graph.edges(data=True):
        if u not in xy or v not in xy or d["name"] in ties or d["element"].startswith("transformer.reg"):
            continue
        phases, ug = lines.get(d["name"], (3, False))
        z = zones.bus_zone.get(v) if d["name"] in devices else zones.bus_zone.get(u)
        (x1, y1), (x2, y2) = xy[u], xy[v]
        ax.plot([x1, x2], [y1, y2], color=color.get(z, "0.6"), lw=PHASE_WIDTH.get(phases, 2),
                ls=(0, (3, 1.5)) if ug else "-", solid_capstyle="round", zorder=2)

    # --- normally-open ties: dashed black with an open-switch circle
    for u, v, d in zones.graph.edges(data=True):
        if d["name"] not in ties or u not in xy or v not in xy:
            continue
        ax.plot([xy[u][0], xy[v][0]], [xy[u][1], xy[v][1]], color="k", lw=1.3, ls="--", zorder=3)
        x, y = mid(u, v)
        ax.plot(x, y, "o", ms=9, mfc="white", mec="k", mew=1.6, zorder=6)
        text = "Sw8 tie (1-phase, open, not used)" if d["name"] == "sw8" else f"{d['name'].capitalize()} tie (open)"
        ax.annotate(text, (x, y), xytext=(7, -3), textcoords="offset points", fontsize=8, bbox=label_box, zorder=7)
    if "450" in xy:   # Sw9 leads off the map to the adjacent feeder
        (x0, y0), x1 = xy["450"], xy["450"][0] + 700
        ax.plot([x0, x1], [y0, y0], color="k", lw=1.3, ls="--", zorder=3)
        ax.plot((x0 + x1) / 2, y0, "o", ms=9, mfc="white", mec="k", mew=1.6, zorder=6)
        ax.plot(x1, y0, "o", ms=16, mfc="white", mec="k", mew=1.6, zorder=6)
        ax.text(x1, y0, "~", ha="center", va="center", fontsize=12, zorder=7)
        ax.annotate("Sw9 tie (open)\nto adjacent feeder, 4.16 kV", (x1, y0), xytext=(-40, 14),
                    textcoords="offset points", fontsize=8, ha="center", bbox=label_box, zorder=7)

    # --- loads: dots sized by connected kW
    kw = feeder.load_kw_by_bus()
    for b, k in kw.items():
        if b in xy:
            ax.scatter(*xy[b], s=8 + 0.55 * k, color="0.15", alpha=0.75, lw=0, zorder=4)

    # --- substation, voltage regulators, capacitor banks
    sx, sy = xy[config.SOURCE_BUS]
    ax.plot(sx, sy, "s", ms=15, mfc="0.15", mec="k", zorder=6)
    ax.annotate("Substation\n4.16 kV source\n+ Reg 1", (sx, sy), xytext=(0, -40), textcoords="offset points",
                ha="center", fontsize=8.5, weight="bold", bbox=label_box, zorder=7)
    for b, (text, offset) in REGULATORS.items():
        if b in xy:
            ax.plot(*xy[b], "h", ms=12, mfc="#ffe08a", mec="k", mew=1.2, zorder=5)
            ax.annotate(text, xy[b], xytext=offset, textcoords="offset points", fontsize=8,
                        weight="bold", ha="right", bbox=label_box, zorder=7)
    for name, b, kvar in _capacitors():
        if b in xy:
            ax.plot(*xy[b], "D", ms=8, mfc="#9be7ff", mec="k", mew=1.1, zorder=6)
            ax.annotate(f"{name} {kvar:.0f} kvar", xy[b], xytext=(7, -10), textcoords="offset points",
                        fontsize=7.5, bbox=label_box, zorder=7)

    # --- switching devices: recloser, IEEE switches, switches added in this study
    for name, (up, down) in zones.device_ends.items():
        if up not in xy or down not in xy:
            continue
        x, y = mid(up, down)
        if name == "Sw1":   # drawn nearer bus 149 so it does not merge with the substation symbol
            x, y = xy[up][0] + 0.7 * (xy[down][0] - xy[up][0]), xy[up][1] + 0.7 * (xy[down][1] - xy[up][1])
            style, text = dict(marker="s", mfc="k", mec="k"), "Sw1 recloser"
        elif name.startswith("Sw"):
            style, text = dict(marker="s", mfc="white", mec="k"), name
        else:
            style, text = dict(marker="D", mfc="white", mec="#1f4e9c"), f"{name} (added)"
        ax.plot(x, y, ls="none", ms=10, mew=1.8, zorder=6, **style)
        ax.annotate(text, (x, y), xytext=DEVICE_LABEL_OFFSET.get(name, (6, 6)), textcoords="offset points",
                    fontsize=8.5, weight="bold", bbox=label_box, zorder=7)

    # --- bus numbers (small), then one label per zone near its middle
    for b, (x, y) in xy.items():
        if b[-1] in "rs" and b[:-1] in xy or b in config.EXCLUDED_BUSES:
            continue
        ax.annotate(b, (x, y), xytext=(2, 2), textcoords="offset points", fontsize=5.2, color="0.45", zorder=5)
    for z in zones.names:
        if z in ZONE_LABEL_XY:
            bx, by = ZONE_LABEL_XY[z]
        else:   # a zone without a hand-placed spot: the bus nearest its centre
            pts = [xy[b] for b in zones.members[z] if b in xy]
            cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
            bx, by = min(pts, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
        ax.text(bx, by, f"{z}\n{zones.kw[z]:.0f} kW", ha="center", va="center", fontsize=8.5, weight="bold",
                color=color[z], bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=color[z], lw=1.2), zorder=8)

    # --- legends: zones, then symbols
    zone_handles = [plt.Line2D([], [], color=color[z], lw=4,
                               label=f"{z}: {zones.kw[z]:.0f} kW, {zones.load_points[z]} loads") for z in zones.names]
    leg = ax.legend(handles=zone_handles, title="Switching zones", loc="upper left", bbox_to_anchor=(1.0, 1.0),
                    fontsize=9, title_fontsize=10, frameon=False)
    ax.add_artist(leg)
    sym = [
        plt.Line2D([], [], color="0.3", lw=PHASE_WIDTH[3], label="3-phase line"),
        plt.Line2D([], [], color="0.3", lw=PHASE_WIDTH[2], label="2-phase line"),
        plt.Line2D([], [], color="0.3", lw=PHASE_WIDTH[1], label="1-phase line"),
        plt.Line2D([], [], color="0.3", lw=2, ls=(0, (3, 1.5)), label="underground cable"),
        plt.Line2D([], [], color="k", lw=1.3, ls="--", marker="o", ms=8, mfc="white", label="normally-open tie switch"),
        plt.Line2D([], [], ls="none", marker="s", ms=12, mfc="0.15", mec="k", label="substation (source bus 150)"),
        plt.Line2D([], [], ls="none", marker="s", ms=9, mfc="k", mec="k", label="feeder-head recloser"),
        plt.Line2D([], [], ls="none", marker="s", ms=9, mfc="white", mec="k", mew=1.8, label="IEEE sectionalizing switch"),
        plt.Line2D([], [], ls="none", marker="D", ms=8, mfc="white", mec="#1f4e9c", mew=1.8,
                   label="automated switch added here"),
        plt.Line2D([], [], ls="none", marker="h", ms=11, mfc="#ffe08a", mec="k", label="voltage regulator"),
        plt.Line2D([], [], ls="none", marker="D", ms=7, mfc="#9be7ff", mec="k", label="capacitor bank"),
        *[plt.scatter([], [], s=8 + 0.55 * k, color="0.15", alpha=0.75, lw=0, label=f"load, {k} kW")
          for k in (20, 40, 80)],
    ]
    ax.legend(handles=sym, title="Symbols", loc="lower left", bbox_to_anchor=(1.0, 0.0), fontsize=8.5,
              title_fontsize=10, frameon=False, labelspacing=0.9)
    ax.set_title("IEEE 123-bus test feeder, 4.16 kV: switching zones, devices and equipment", fontsize=14, pad=12)
    ax.text(0, -0.01, "Small gray numbers are bus IDs. Bus positions come from the IEEE test case and are not to scale.",
            transform=ax.transAxes, fontsize=8, color="0.4", va="top")
    ax.set_aspect("equal")
    ax.axis("off")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def accuracy_vs_resistance(df: pd.DataFrame, preds: dict[str, np.ndarray], path) -> None:
    slg = df["ftype"] == "SLG"
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for label, pred in preds.items():
        acc = pd.Series(pred[slg] == df.loc[slg, "zone"].to_numpy()).groupby(
            df.loc[slg, "r"].to_numpy()).mean()
        ax.plot(acc.index, acc.values * 100, marker="o", label=label)
    ax.set_xscale("log")
    ax.set_xlabel("Fault resistance (ohm), line-to-ground faults")
    ax.set_ylabel("Faulted zone identified correctly (%)")
    ax.set_ylim(0, 102)
    ax.grid(alpha=0.3)
    ax.legend()
    ax.set_title("Fault location accuracy vs fault resistance (unseen buses)")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def confusion(df: pd.DataFrame, pred: np.ndarray, labels: list[str], path, title: str) -> None:
    m = pd.crosstab(pd.Categorical(df["zone"], labels), pd.Categorical(pred, labels + ["none"]),
                    dropna=False).reindex(index=labels, columns=labels + ["none"], fill_value=0)
    pct = m.div(m.sum(axis=1), axis=0) * 100
    fig, ax = plt.subplots(figsize=(7.5, 6))
    im = ax.imshow(pct.values, cmap="Blues", vmin=0, vmax=100)
    ax.set_xticks(range(len(pct.columns)), pct.columns, rotation=45)
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xlabel("Predicted zone")
    ax.set_ylabel("True zone")
    for i in range(pct.shape[0]):
        for j in range(pct.shape[1]):
            if pct.values[i, j] >= 0.5:
                ax.text(j, i, f"{pct.values[i, j]:.0f}", ha="center", va="center", fontsize=7,
                        color="white" if pct.values[i, j] > 60 else "black")
    fig.colorbar(im, ax=ax, label="% of faults in true zone")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    feeder.load_feeder()
    config.FIGURES.mkdir(parents=True, exist_ok=True)
    feeder_map(find_zones(), config.FIGURES / "feeder_zones.png")
    print("wrote", config.FIGURES / "feeder_zones.png")
