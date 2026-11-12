"""Build the data file for the study page (docs/study/).

    .venv\\Scripts\\python scripts\\build_study_site.py      # about 2 s, after run.py and error_analysis.py

The study page (docs/study/index.html, study.css, study.js) is hand-written and holds no result
numbers. Everything it shows comes from one generated file, docs/study/data.js, which this script
writes from results/ and shf/config.py:

    window.STUDY = { config, model, metrics, errors, zones, restoration, steps, geo, folds, ... };

It is a plain script assignment (not JSON fetched at run time), so the page also works when it is
opened by double-click from disk. Re-running the study only needs this script afterwards.
"""
from __future__ import annotations

import csv
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shf import config, model  # noqa: E402
from shf.faults import DEVICES  # noqa: E402

RES = config.RESULTS
OUT = ROOT / "docs" / "study" / "data.js"


def num(v: str):
    """CSV cell -> int / float / bool / str."""
    if v in ("True", "False"):
        return v == "True"
    try:
        f = float(v)
    except ValueError:
        return v
    return int(f) if f.is_integer() and "." not in v else f


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [{k: num(v) for k, v in row.items()} for row in csv.DictReader(f)]


def words(cell) -> list[str]:
    """'Sw9 Sw7' -> ['Sw9', 'Sw7']; '-' or '' -> []."""
    return [] if cell in ("-", "", None) else str(cell).split()


def dss_value(lines: list[str], key: str) -> float:
    for ln in lines:
        m = re.search(rf"\b{key}=([\d.]+)", ln)
        if m:
            return float(m.group(1))
    raise KeyError(key)


def base_kv() -> float:
    """Nominal line-to-line voltage of the studied circuit, from the OpenDSS master file."""
    text = config.FEEDER_MASTER.read_text(errors="ignore")
    return float(re.search(r"basekv=([\d.]+)", text, re.I).group(1))


# ---------------------------------------------------------------------------
# switching orders -> structured steps for the fault stepper
# ---------------------------------------------------------------------------
def parse_orders(path: Path) -> dict[str, list[str]]:
    orders, cur = {}, None
    for ln in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"## Fault in zone (\S+)", ln)
        if m:
            cur = m.group(1)
            orders[cur] = []
        elif cur and re.match(r"\d+\. ", ln):
            orders[cur].append(re.sub(r"^\d+\. ", "", ln).strip())
    return orders


def zone_list(text: str) -> list[str]:
    return [z.strip() for z in text.split(",") if z.strip()]


def build_steps(zf: str, lines: list[str], parent: dict, rrow: dict) -> list[dict]:
    """One state per step: which zones have power, which devices are open, which ties closed.

    Device rule (as in shf/restoration.apply_states): a device inside a dark island stays
    closed only when both zones it joins are energized; ties are open until closed."""
    zones = list(parent)
    children = {z: [c for c in zones if parent[c] == z] for z in zones}

    def below(z):
        out, st = [], list(children[z])
        while st:
            c = st.pop()
            out.append(c)
            st.extend(children[c])
        return out

    island = set()
    for c in children[zf]:
        island |= {c, *below(c)}
    steps = [{"key": "normal", "energized": zones, "restored": [], "open": [], "ties": [], "fault": None},
             {"key": "fault", "energized": zones, "restored": [], "open": [], "ties": [], "fault": zf},
             {"key": "lockout", "energized": [], "restored": [], "open": ["Sw1"], "ties": [], "fault": zf}]
    opened, energized, restored, ties = [], set(), set(), []

    def dev_open(final=False):
        out = set(opened)
        if "Sw1" not in energized and zf != "Sw1" and not any(s["key"] == "reclose" for s in steps):
            out.add("Sw1")
        for z in island:
            p = parent[z]
            if p == zf:
                continue
            if not (z in energized and p in energized):
                out.add(z)
        return sorted(out)

    for ln in lines[1:]:
        if m := re.match(r"Isolate: open (.+)\.$", ln):
            opened = zone_list(m.group(1))
            steps.append({"key": "isolate", "energized": [], "restored": [], "open": sorted(set(opened) | {"Sw1"}),
                          "ties": [], "fault": zf, "opened": opened})
        elif m := re.match(r"Re-close Sw1: zones (.+) restored\.$", ln):
            energized |= set(zone_list(m.group(1)))
            steps.append({"key": "reclose", "energized": sorted(energized), "restored": [],
                          "open": [], "ties": [], "fault": zf, "zones": zone_list(m.group(1))})
            steps[-1]["open"] = dev_open()
        elif m := re.match(r"Close tie (\S+) \(from (.+?)\): zones (.+) restored; Vmin ([\d.]+) pu, Vmax ([\d.]+) pu\.$", ln):
            tie, src, zs = m.group(1), m.group(2), zone_list(m.group(3))
            energized |= set(zs)
            restored |= set(zs)
            ties.append(tie)
            steps.append({"key": "tie", "tie": tie, "from": src.replace("zone ", ""), "zones": zs,
                          "vmin": float(m.group(4)), "vmax": float(m.group(5)),
                          "energized": sorted(energized), "restored": sorted(restored),
                          "open": dev_open(), "ties": list(ties), "fault": zf})
        elif m := re.match(r"Still dark until repair: zones (.+)\.$", ln):
            pass   # the final step below lists them from restoration.csv
    final = {"key": "final", "energized": sorted(energized), "restored": sorted(restored),
             "open": dev_open(), "ties": list(ties), "fault": zf,
             "unserved": words(rrow["unserved_healthy"]),
             "vmin": rrow["final_vmin_pu"], "vmax": rrow["final_vmax_pu"],
             "checks": rrow["power_flow_checks"], "rejected": rrow["power_flow_rejected"],
             "overloads": rrow["final_overloads"], "radial": rrow["radial"]}
    steps.append(final)
    # consistency with restoration.csv: the parsed orders and the table must agree
    assert sorted(restored) == sorted(words(rrow["restored_by_tie"])), (zf, restored, rrow)
    assert ties == words(rrow["ties_closed"]), (zf, ties, rrow)
    assert set(zones) - {zf} - energized == set(words(rrow["unserved_healthy"])), (zf, energized, rrow)
    return steps


# ---------------------------------------------------------------------------
def references() -> list[dict]:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    block = text.split("## References", 1)[1].split("\n## ", 1)[0]
    out = []
    for ln in block.splitlines():
        if not ln.startswith("- "):
            continue
        body = ln[2:].strip()
        m = re.search(r"\s+[—-]\s+(https?://\S+)(.*)$", body)
        url = m.group(1) if m else None
        label = body[: m.start()].strip() if m else body
        extra = m.group(2).strip() if m else ""
        out.append({"text": label.replace("*", ""), "url": url, "extra": extra.replace("*", "")})
    return out


def folds_by_bus(per_bus: list[dict]) -> dict[str, int]:
    """Which GroupKFold fold each fault bus is tested in. GroupKFold only looks at the group
    labels, so the per-bus fault counts reproduce the assignment model.cross_validate uses."""
    groups = np.concatenate([[str(r["bus"])] * int(r["faults"]) for r in per_bus])
    out = {}
    for k, (_, test) in enumerate(GroupKFold(n_splits=model.N_FOLDS).split(groups, groups, groups)):
        for b in np.unique(groups[test]):
            out[str(b)] = k
    return out


def main() -> None:
    metrics = json.loads((RES / "metrics.json").read_text(encoding="utf-8"))
    errors = json.loads((RES / "error_analysis" / "error_analysis.json").read_text(encoding="utf-8"))
    geo = json.loads((RES / "feeder_geometry.json").read_text(encoding="utf-8"))
    zones = read_csv(RES / "zones.csv")
    for z in zones:
        z["parent_zone"] = z["parent_zone"] or None
        z["buses"] = str(z["buses"]).split()
    rest = read_csv(RES / "restoration.csv")
    orders = parse_orders(RES / "switching_orders.md")
    per_zone_ml = read_csv(RES / "error_analysis" / "per_zone_ml.csv")
    per_zone_fpi = read_csv(RES / "error_analysis" / "per_zone_fpi.csv")
    with open(RES / "error_analysis" / "confusion_ml.csv", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    confusion = {"labels": rows[0][1:], "rows": {r[0]: [int(x) for x in r[1:]] for r in rows[1:]}}
    per_bus = read_csv(RES / "error_analysis" / "per_bus_ml.csv")
    for r in per_bus:
        r["bus"] = str(r["bus"])

    parent = {z["zone"]: z["parent_zone"] for z in zones}
    rrows = {r["fault_zone"]: r for r in rest}
    steps = {zf: build_steps(zf, orders[zf], parent, rrows[zf]) for zf in parent}

    # assumptions, all from config.py
    kv = base_kv()
    amp_groups = {}
    for code, a in config.LINECODE_AMPACITY.items():
        amp_groups.setdefault(a, []).append(code)
    cfg = {
        "base_kv": kv,
        "v_phase": kv * 1000 / math.sqrt(3),
        "v_min_pu": config.V_MIN_PU, "v_max_pu": config.V_MAX_PU, "v_tol": config.V_TOL,
        "emergency_factor": config.EMERGENCY_FACTOR, "switch_ampacity": config.SWITCH_AMPACITY,
        "ampacity_by_linecodes": [{"amps": a, "linecodes": c} for a, c in amp_groups.items()],
        "load_mult_range": list(config.LOAD_MULT_RANGE), "load_spread": config.LOAD_SPREAD,
        "scenarios_per_case": config.SCENARIOS_PER_CASE,
        "slg_resistances": config.SLG_RESISTANCES, "phase_resistances": config.PHASE_RESISTANCES,
        "noise_mag": config.NOISE_MAG, "noise_ang_deg": config.NOISE_ANG_DEG,
        "fpi_phase_factor": config.FPI_PHASE_FACTOR, "fpi_ground_factor": config.FPI_GROUND_FACTOR,
        "fpi_ground_margin": config.FPI_GROUND_MARGIN,
        "t_automated": config.T_AUTOMATED_MIN, "t_manual": config.T_MANUAL_MIN, "t_repair": config.T_REPAIR_MIN,
        "sectionalizers": config.SECTIONALIZERS, "ties": config.TIES,
        "adjacent_pu": dss_value(config.ADJACENT_FEEDER_DSS, "pu"),
        "adjacent_len_kft": dss_value([l for l in config.ADJACENT_FEEDER_DSS if "Trunk" in l], "length"),
        "source_bus": config.SOURCE_BUS,
    }
    m = model.make_model()
    mdl = {
        "n_folds": model.N_FOLDS, "dropout_rate": model.DROPOUT_RATE,
        "params": {k: m.get_params()[k] for k in ("max_iter", "learning_rate", "max_leaf_nodes")},
        "devices": DEVICES,
        "features_full": [c.split("_", 1)[1] for c in model.feature_columns(None, "full") if c.startswith(DEVICES[0] + "_")],
        "features_mag": [c.split("_", 1)[1] for c in model.feature_columns(None, "magnitude") if c.startswith(DEVICES[0] + "_")],
    }
    mdl["n_full"] = len(model.feature_columns(None, "full"))
    mdl["n_mag"] = len(model.feature_columns(None, "magnitude"))

    fl = metrics["fault_location"]
    pick = fl["fpi_baseline"]["pickups_A"]
    devices = [{"name": d, "kind": k, "origin": "ieee" if k in ("recloser", "ieee") else "added",
                "desc": config.SECTIONALIZERS[d],
                "phase_pickup": pick[d][0], "ground_pickup": pick[d][1],
                "peak_load_A": pick[d][0] / config.FPI_PHASE_FACTOR}
               for d, k, *_ in geo["devices"]]
    ties = [{"name": t, "desc": config.TIES[t], "origin": "added" if config.TIES[t].startswith("Added") else "ieee", "ends": [a, b]}
            for t, a, b in geo["ties"] if t in config.TIES]

    total_kft = sum(z["line_kft"] for z in zones)
    defer95 = next(t for t in errors["defer_low_confidence"] if t["threshold"] == max(
        x["threshold"] for x in errors["defer_low_confidence"]))
    derived = {
        "n_buses_map": len(geo["buses"]),
        "n_fault_buses": len(per_bus),
        "n_zones": len(zones),
        "n_devices": len(DEVICES),
        "n_devices_ieee": sum(d["origin"] == "ieee" for d in devices),
        "n_devices_added": sum(d["origin"] == "added" for d in devices),
        "n_ties": len(ties),
        "total_kft": total_kft,
        "total_kw": sum(z["kW"] for z in zones),
        "patrol_cut": 1 - metrics["patrol_kft"]["ml_full"] / metrics["patrol_kft"]["no_location"],
        "rejected_total": sum(r["power_flow_rejected"] for r in rest),
        "checks_total": sum(r["power_flow_checks"] for r in rest),
        "restored_share": metrics["restoration"]["kW_restored_by_tie_total"]
                          / metrics["restoration"]["kW_downstream_healthy_total"],
        "kwmin_min": min(rest, key=lambda r: r["kWmin_reduction_pct"]),
        "kwmin_max": max(rest, key=lambda r: r["kWmin_reduction_pct"]),
        "errors_high_r_share": errors["ml_errors_slg_200_ohm_or_more"] / errors["ml_errors"],
        "error_share": errors["ml_errors"] / errors["faults"],
        "slg_errors": round(errors["ml_error_rate_by_type"]["SLG"] * metrics["dataset"]["by_type"]["SLG"]),
        "defer_max": defer95,
        "defer_cut": 1 - defer95["errors_kept"] / errors["ml_errors"],
        "missing_worst": min(fl["ml_full"]["missing_sensor_accuracy"].items(), key=lambda kv: kv[1]),
        "missing_best": max(fl["ml_full"]["missing_sensor_accuracy"].items(), key=lambda kv: kv[1]),
        "upstream_errors": errors["ml_error_direction"].get("predicted parent (1 zone upstream)", 0)
                           + errors["ml_error_direction"].get("further upstream", 0),
        "one_zone_errors": errors["ml_error_direction"].get("predicted parent (1 zone upstream)", 0)
                           + errors["ml_error_direction"].get("predicted child (1 zone downstream)", 0),
        "same_path_errors": sum(v for k, v in errors["ml_error_direction"].items()
                                if k not in ("unrelated branch", "sibling (same parent)")),
        "i_fault_at_max_r": kv * 1000 / math.sqrt(3) / max(config.SLG_RESISTANCES),
        "max_r": max(config.SLG_RESISTANCES),
        "min_ground_pickup": min(p[1] for p in pick.values()),
        "max_ground_pickup": max(p[1] for p in pick.values()),
        "final_vmax_max": max(r["final_vmax_pu"] for r in rest),
        "final_vmin_min": min(r["final_vmin_pu"] for r in rest),
        "final_overloads_total": sum(r["final_overloads"] for r in rest),
        "hops_min": min(errors["ml_error_rate_by_hops_to_boundary"].values()),
        "hops_max": max(errors["ml_error_rate_by_hops_to_boundary"].values()),
        "fpi_errors": round((1 - fl["fpi_baseline"]["accuracy"]) * metrics["dataset"]["rows"]),
    }
    derived["ml_wrong_share_upstream"] = derived["upstream_errors"] / errors["ml_errors"]
    derived["one_zone_share"] = derived["one_zone_errors"] / errors["ml_errors"]
    derived["same_path_share"] = derived["same_path_errors"] / errors["ml_errors"]
    devmax = max(devices, key=lambda d: d["peak_load_A"])
    derived["noise_at_max_load"] = devmax["peak_load_A"] * config.NOISE_MAG
    derived["max_load_device"] = devmax["name"]
    derived["max_load_A"] = devmax["peak_load_A"]

    study = {
        "built_from": ["results/metrics.json", "results/zones.csv", "results/restoration.csv",
                       "results/switching_orders.md", "results/feeder_geometry.json",
                       "results/error_analysis/error_analysis.json", "results/error_analysis/per_zone_ml.csv",
                       "results/error_analysis/per_zone_fpi.csv", "results/error_analysis/confusion_ml.csv",
                       "results/error_analysis/per_bus_ml.csv", "shf/config.py", "shf/model.py"],
        "config": cfg, "model": mdl, "metrics": metrics, "errors": errors,
        "per_zone_ml": per_zone_ml, "per_zone_fpi": per_zone_fpi, "confusion": confusion,
        "zones": zones, "devices": devices, "ties": ties,
        "restoration": rest, "orders": orders, "steps": steps,
        "geo": geo, "folds": folds_by_bus(per_bus),
        "per_bus": [{k: r[k] for k in ("bus", "zone", "faults", "ml_wrong")} for r in per_bus],
        "derived": derived, "references": references(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(study, ensure_ascii=False, separators=(",", ":"), default=float)
    OUT.write_text("/* Generated by scripts/build_study_site.py from results/ and shf/config.py. Do not edit. */\n"
                   f"window.STUDY = {body};\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.1f} KiB): "
          f"{len(zones)} zones, {len(rest)} restoration cases, {len(study['folds'])} buses in folds")


if __name__ == "__main__":
    main()
