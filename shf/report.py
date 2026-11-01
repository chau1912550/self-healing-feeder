"""Figures for the README."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import config  # noqa: E402
from .topology import Zones, read_bus_coords  # noqa: E402

ZONE_COLORS = plt.get_cmap("tab10")


def feeder_map(zones: Zones, path) -> None:
    xy = read_bus_coords()
    color = {z: ZONE_COLORS(i % 10) for i, z in enumerate(zones.names)}
    fig, ax = plt.subplots(figsize=(13, 8))
    devices = {d.lower() for d in config.SECTIONALIZERS}
    ties = {t.lower() for t in config.TIES}
    for u, v, d in zones.graph.edges(data=True):
        if u not in xy or v not in xy:
            continue
        (x1, y1), (x2, y2) = xy[u], xy[v]
        if d["name"] in ties:
            ax.plot([x1, x2], [y1, y2], "k--", lw=1.5)
            ax.annotate(d["name"].capitalize() + " (tie)", ((x1 + x2) / 2, (y1 + y2) / 2),
                        fontsize=8, color="k")
            continue
        z = zones.bus_zone.get(v) if d["name"] in devices else zones.bus_zone.get(u)
        ax.plot([x1, x2], [y1, y2], color=color.get(z, "0.6"), lw=2.2)
        if d["name"] in devices:
            ax.plot((x1 + x2) / 2, (y1 + y2) / 2, "s", ms=9, mfc="white", mec="k")
            ax.annotate(d["name"].upper() if d["name"].startswith("l") else d["name"].capitalize(),
                        ((x1 + x2) / 2, (y1 + y2) / 2), xytext=(4, 4),
                        textcoords="offset points", fontsize=8, weight="bold")
    for z in zones.names:
        ax.plot([], [], color=color[z], lw=4,
                label=f"zone {z}: {zones.kw[z]:.0f} kW, {zones.load_points[z]} loads")
    if "450" in xy:
        ax.annotate("Sw9 tie -> adjacent feeder", xy["450"], xytext=(-150, 8),
                    textcoords="offset points", fontsize=8, weight="bold")
    ax.set_title("IEEE 123-bus feeder: switching zones (squares = automated devices)")
    ax.set_aspect("equal")
    ax.axis("off")
    ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=9, frameon=False)
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
