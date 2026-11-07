"""Export simulated incidents for the role-based monitor demo (docs/monitor/).

Picks 40 simulated faults (4 per zone, mixed fault types and resistances), trains the
ML model on every bus EXCEPT the picked buses, and scores the picked faults, so each
incident's prediction is for a bus the model never saw (same idea as GroupKFold).
Also computes the fault-indicator (FPI) baseline for each incident and bundles the
zone tree, restoration plans and feeder map into docs/monitor/data.json
(served with the report page on GitHub Pages at /monitor/).

    .venv\\Scripts\\python scripts\\export_control_room.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shf import model  # noqa: E402
from shf.faults import DEVICES  # noqa: E402

RES = ROOT / "results"
OUT = ROOT / "docs" / "monitor" / "data.json"


def rcsv(p: Path) -> list[dict]:
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pick_incidents(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """4 faults per zone: one phase fault, one low-R SLG, one mid-R SLG, one high-R SLG."""
    rows = []
    groups = [
        lambda d: d[d.ftype.isin(["3PH", "LL", "LLG"])],
        lambda d: d[(d.ftype == "SLG") & (d.r <= 10)],
        lambda d: d[(d.ftype == "SLG") & (d.r.between(25, 100))],
        lambda d: d[(d.ftype == "SLG") & (d.r >= 200)],
    ]
    used_buses: set[str] = set()
    for zone in sorted(df.zone.unique()):
        dz = df[df.zone == zone]
        for g in groups:
            cand = g(dz[~dz.bus.isin(used_buses)])
            if cand.empty:
                cand = g(dz)
            if cand.empty:
                continue
            r = cand.iloc[int(rng.integers(len(cand)))]
            rows.append(r)
            used_buses.add(r.bus)
    return pd.DataFrame(rows)


def main() -> None:
    df = pd.read_csv(ROOT / "data" / "generated" / "dataset.csv.gz", dtype={"bus": str})
    df = df[df.converged].reset_index(drop=True)
    rng = np.random.default_rng(7)
    inc = pick_incidents(df, rng)
    held = set(inc.bus)

    cols = model.feature_columns(df, "full")
    train = df[~df.bus.isin(held)]
    Xtr = model.sensor_dropout(train[cols].to_numpy(dtype=float), cols, np.random.default_rng(0))
    clf = model.make_model(0).fit(Xtr, train["zone"].to_numpy())
    proba = clf.predict_proba(inc[cols].to_numpy(dtype=float))
    classes = list(clf.classes_)

    metrics = json.loads((RES / "metrics.json").read_text(encoding="utf-8"))
    pick = metrics["fault_location"]["fpi_baseline"]["pickups_A"]
    zones = rcsv(RES / "zones.csv")
    parent = {z["zone"]: (z["parent_zone"] or None) for z in zones}

    def depth(z: str) -> int:
        d = 0
        while parent[z]:
            z, d = parent[z], d + 1
        return d

    incidents = []
    for k, (_, r) in enumerate(inc.iterrows()):
        p = proba[k]
        order = np.argsort(-p)[:3]
        flagged = [d for d in DEVICES
                   if max(r[f"{d}_Ia"], r[f"{d}_Ib"], r[f"{d}_Ic"]) > pick[d][0]
                   or 3 * r[f"{d}_I0"] > pick[d][1]]
        fpi = max(flagged, key=depth) if flagged else "none"
        meas = {d: {key: round(float(r[f"{d}_{key}"]), 4 if key.startswith(("V", "dV")) else 1)
                    for key in ("Ia", "Ib", "Ic", "I0", "dIa", "dIb", "dIc", "Va", "Vb", "Vc", "dVa", "dVb", "dVc")}
                for d in DEVICES}
        incidents.append({
            "id": f"INC-{1001 + k}",
            "bus": r.bus, "zone": r.zone, "ftype": r.ftype, "phases": str(r.phases),
            "r_ohm": float(r.r), "load_mult": round(float(r.load_mult), 3),
            "ml_top": [{"zone": classes[i], "p": round(float(p[i]), 4)} for i in order],
            "fpi": fpi, "fpi_flagged": flagged,
            "meas": meas,
        })
    rng.shuffle(incidents)
    for k, it in enumerate(incidents):
        it["id"] = f"INC-{1001 + k}"

    orders, cur = {}, None
    for line in (RES / "switching_orders.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"## Fault in zone (\S+)", line)
        if m:
            cur = m.group(1); orders[cur] = []; continue
        m = re.match(r"\d+\. (.*)", line.strip())
        if m and cur:
            orders[cur].append(m.group(1))

    data = {
        "note": "Simulated incidents from the IEEE 123-bus fault sweep. ML predictions come from a model "
                "trained without the incident buses (unseen-bus test).",
        "geo": json.loads((RES / "feeder_geometry.json").read_text(encoding="utf-8")),
        "zones": zones,
        "restoration": rcsv(RES / "restoration.csv"),
        "orders": orders,
        "pickups": pick,
        "metrics": {
            "fpi_acc": metrics["fault_location"]["fpi_baseline"]["accuracy"],
            "ml_acc": metrics["fault_location"]["ml_full"]["accuracy"],
            "patrol_kft": metrics["patrol_kft"],
            "kwmin_reduction_pct": metrics["restoration"]["kWmin_reduction_pct_weighted_by_line_length"],
            "timing_min": metrics["restoration"]["timing_assumption_min"],
            "total_kw": metrics["base_case"]["total_kW"],
        },
        "incidents": incidents,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    right = sum(i["ml_top"][0]["zone"] == i["zone"] for i in incidents)
    fpi_right = sum(i["fpi"] == i["zone"] for i in incidents)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB): {len(incidents)} incidents, "
          f"ML right {right}, FPI right {fpi_right}")


if __name__ == "__main__":
    main()
