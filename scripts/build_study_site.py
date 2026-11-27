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
import statistics
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


# ---------------------------------------------------------------------------
# verified extension branches -> window.STUDY.extensions
# ---------------------------------------------------------------------------
def _opt_dict(d: dict) -> dict:
    """Drop keys whose value is None so JSON exports carry zero unexpected nulls."""
    return {k: v for k, v in d.items() if v is not None}


def _tr_model(m: dict) -> dict:
    bft = m.get("by_fault_type") or {}
    slg_r = m.get("slg_by_resistance") or {}
    return _opt_dict({
        "accuracy": m.get("accuracy"),
        "slg": bft.get("SLG"),
        "slg_200": slg_r.get("200.0"),
        "slg_400": slg_r.get("400.0"),
        "missing_sensor_mean": m.get("missing_sensor_mean"),
        "missing_sensor_min": m.get("missing_sensor_min"),
        "fold_std": m.get("fold_std"),
    })


def _tr_fs(fs: dict) -> dict:
    mods = fs.get("models") or {}

    def _one(key: str) -> dict:
        m = mods.get(key) or {}
        return _opt_dict({
            "accuracy_mean": m.get("accuracy_mean"),
            "accuracy_std": m.get("accuracy_std"),
            "slg": (m.get("by_fault_type") or {}).get("SLG"),
            "missing_sensor_mean": m.get("missing_sensor_mean"),
        })

    return _opt_dict({
        "fraction": fs.get("fraction"),
        "train_buses": fs.get("train_buses"),
        "test_buses": fs.get("test_buses"),
        "n_repeats": fs.get("n_repeats"),
        "per_node_gbdt": _one("per_node_gbdt"),
        "zone_tree_gnn": _one("gnn"),
    })


def _s2_entry(m: dict) -> dict:
    t1 = m.get("by_fault_type_top1") or {}
    t3 = m.get("by_fault_type_top3") or {}
    return _opt_dict({
        "top1": m.get("top1"),
        "top3": m.get("top3"),
        "phase_faults_top1": m.get("phase_faults_top1"),
        "phase_faults_top3": m.get("phase_faults_top3"),
        "slg_top1": t1.get("SLG"),
        "slg_top3": t3.get("SLG"),
        "p3ph_top3": t3.get("3PH"),
        "ll_top3": t3.get("LL"),
        "llg_top3": t3.get("LLG"),
    })


def _ag_model(m: dict, *, include_1k_10k: bool = False) -> dict:
    bft = m.get("by_fault_type") or {}
    slg_r = m.get("slg_by_resistance") or {}
    out = {
        "overall_accuracy": m.get("overall_accuracy"),
        "fault_zone_accuracy": m.get("fault_zone_accuracy"),
        "fault_detection_recall": m.get("fault_detection_recall"),
        "nofault_fpr": m.get("nofault_fpr"),
        "reconfig_and_loop_accuracy": m.get("reconfig_and_loop_accuracy"),
        "looped_accuracy": m.get("looped_accuracy"),
        "slg": bft.get("SLG"),
        "phase_faults_accuracy": m.get("phase_faults_accuracy"),
        "slg_200": slg_r.get("200.0"),
        "slg_400": slg_r.get("400.0"),
        "missing_sensor_mean": m.get("missing_sensor_mean"),
        "missing_sensor_min": m.get("missing_sensor_min"),
        "by_der_band": m.get("fault_acc_by_der_band"),
    }
    if include_1k_10k:
        hif_vals = [slg_r[k] for k in ("1000.0", "2500.0", "5000.0", "10000.0") if k in slg_r]
        out["slg_1000"] = slg_r.get("1000.0")
        out["slg_10000"] = slg_r.get("10000.0")
        if hif_vals:
            out["slg_hif_1k_10k"] = round(sum(hif_vals) / len(hif_vals), 4)
    return _opt_dict(out)


def _ag_fs(fs: dict) -> dict:
    mods = fs.get("models") or {}

    def _one(key: str) -> dict:
        m = mods.get(key) or {}
        return _opt_dict({
            "overall_accuracy_mean": m.get("overall_accuracy_mean"),
            "overall_accuracy_std": m.get("overall_accuracy_std"),
            "nofault_fpr_mean": m.get("nofault_fpr_mean"),
            "missing_sensor_mean": m.get("missing_sensor_mean"),
        })

    return _opt_dict({
        "fraction": fs.get("fraction"),
        "train_fault_buses": fs.get("train_fault_buses"),
        "test_fault_buses": fs.get("test_fault_buses"),
        "train_nofault_events": fs.get("train_nofault_events"),
        "n_repeats": fs.get("n_repeats"),
        "per_node_gbdt": _one("per_node_gbdt"),
        "active_gatv2": _one("active_gatv2"),
    })


def _conf_block(d: dict) -> dict:
    """Compact summary of a conformal evaluation block (scalar or {mean, std, ...} dicts)."""
    def _val(key: str):
        v = d.get(key)
        return v.get("mean") if isinstance(v, dict) else v

    return _opt_dict({
        "coverage": _val("coverage"),
        "coverage_fault": _val("coverage_fault"),
        "coverage_nofault": _val("coverage_nofault"),
        "avg_set_size": _val("avg_set_size"),
        "singleton_share": _val("singleton_share"),
        "singleton_accuracy": _val("singleton_accuracy"),
        "raw_argmax_accuracy": _val("raw_argmax_accuracy"),
        "nofault_auto_trip": _val("nofault_autonomous_trip_share"),
    })


def _calsize_row(row: dict) -> dict:
    return _opt_dict({
        "fraction": row.get("fraction"),
        "cal_fault_buses": row.get("cal_fault_buses"),
        "cal_nofault_events": row.get("cal_nofault_events"),
        "coverage_mean": row.get("coverage_mean"),
        "coverage_p10": row.get("coverage_p10"),
        "avg_set_size": row.get("avg_set_size"),
        "singleton_share": row.get("singleton_share"),
        "singleton_accuracy": row.get("singleton_accuracy"),
        "nofault_auto_trip": row.get("nofault_autonomous_trip_share"),
        "meets_criterion": row.get("meets_criterion"),
        "meets_full_a3_recal": row.get("meets_full_a3_recal"),
    })


def _hf_pass(m: dict) -> dict:
    slg_r = m.get("slg_by_resistance") or {}
    reg = m.get("by_arc_regime") or {}
    return _opt_dict({
        "accuracy": m.get("accuracy"),
        "slg_100": slg_r.get("100.0"),
        "slg_200": slg_r.get("200.0"),
        "slg_400": slg_r.get("400.0") if "400.0" in slg_r else m.get("slg_400_accuracy"),
        "slg_200_400": m.get("slg_200_400_accuracy"),
        "slg_low_r_0_50": m.get("slg_low_r_0_50_accuracy"),
        "phase_faults": m.get("phase_faults_accuracy"),
        "arcing_accuracy": m.get("arcing_accuracy"),
        "missing_sensor_mean": m.get("missing_sensor_mean"),
        "missing_sensor_slg_200_400_mean": m.get("missing_sensor_slg_200_400_mean"),
        "intermittent": reg.get("intermittent"),
        "continuous": reg.get("continuous"),
        "by_arc_surface": m.get("by_arc_surface"),
    })


def _hf_act(m: dict, *, include_1k_10k: bool = False) -> dict:
    slg_r = m.get("slg_by_resistance") or {}
    reg = m.get("by_arc_regime") or {}
    out = {
        "overall_accuracy": m.get("overall_accuracy"),
        "fault_zone_accuracy": m.get("fault_zone_accuracy"),
        "nofault_fpr": m.get("nofault_fpr"),
        "looped_accuracy": m.get("looped_accuracy"),
        "slg_200": slg_r.get("200.0"),
        "slg_400": slg_r.get("400.0") if "400.0" in slg_r else m.get("slg_400_accuracy"),
        "slg_200_400": m.get("slg_200_400_accuracy"),
        "arcing_accuracy": m.get("arcing_accuracy"),
        "missing_sensor_mean": m.get("missing_sensor_mean"),
        "missing_sensor_slg_200_400_mean": m.get("missing_sensor_slg_200_400_mean"),
        "intermittent": reg.get("intermittent"),
        "continuous": reg.get("continuous"),
        "by_arc_surface": m.get("by_arc_surface"),
        "nofault_fpr_by_disturbance": m.get("nofault_fpr_by_disturbance"),
    }
    if include_1k_10k:
        out["slg_hif_1k_10k"] = m.get("slg_hif_1k_10k_accuracy")
        out["slg_10000"] = slg_r.get("10000.0")
    return _opt_dict(out)


def _hf_pair(ab: dict, mkey: str, fn) -> dict:
    b = (ab.get("60Hz_only") or {}).get(mkey) or {}
    e = (ab.get("60Hz_plus_edge") or {}).get(mkey) or {}
    return {"base": fn(b), "edge": fn(e)}


def _hf_fs_pair(ab: dict, mkey: str) -> dict:
    def _one(d: dict) -> dict:
        return _opt_dict({
            "accuracy_mean": d.get("accuracy_mean"),
            "accuracy_std": d.get("accuracy_std"),
            "slg_200_400": d.get("slg_200_400_accuracy"),
            "missing_sensor_mean": d.get("missing_sensor_mean"),
        })

    return {
        "base": _one((ab.get("60Hz_only") or {}).get(mkey) or {}),
        "edge": _one((ab.get("60Hz_plus_edge") or {}).get(mkey) or {}),
    }


def _hf_afs_pair(ab: dict, mkey: str) -> dict:
    def _one(d: dict) -> dict:
        return _opt_dict({
            "overall_accuracy_mean": d.get("overall_accuracy_mean"),
            "overall_accuracy_std": d.get("overall_accuracy_std"),
            "slg_hif_1k_10k_mean": d.get("slg_hif_1k_10k_mean"),
            "nofault_fpr_mean": d.get("nofault_fpr_mean"),
            "missing_sensor_mean": d.get("missing_sensor_mean"),
        })

    return {
        "base": _one((ab.get("60Hz_only") or {}).get(mkey) or {}),
        "edge": _one((ab.get("60Hz_plus_edge") or {}).get(mkey) or {}),
    }


def _hf_conf_pair(conf: dict, mkey: str) -> dict:
    res = conf.get("results") or {}

    def _one(ab_key: str) -> dict:
        t95 = (((res.get(ab_key) or {}).get(mkey) or {}).get("aps_rand") or {}).get("target_95") or {}
        return _opt_dict({
            "ieee123": _conf_block(t95.get("ieee123_cross_conformal") or {}),
            "ieee34_zero_shot": _conf_block(t95.get("ieee34_zero_shot_q_from_123") or {}),
            "ieee34_recal_5pct": _conf_block(t95.get("ieee34_recal_5pct_buses") or {}),
            "ieee34_recal_20pct": _conf_block(t95.get("ieee34_recal_20pct_buses") or {}),
        })

    return {"base": _one("60Hz_only"), "edge": _one("60Hz_plus_edge")}


def build_extensions(built_from: list[str]) -> dict:
    """Build compact, 100%-result-backed summaries for all 8 verified extension branches."""
    def _load(rel: str) -> dict | None:
        p = ROOT / rel
        if not p.exists():
            return None
        if rel not in built_from:
            built_from.append(rel)
        return json.loads(p.read_text(encoding="utf-8"))

    ext: dict = {}

    # 1. Cross-feeder transfer (IEEE 123-bus -> IEEE 34-bus + Stage-2 bus ranking + signal-to-load)
    p2 = _load("results/transfer/phase2_ieee123.json")
    p3 = _load("results/transfer/phase3_ieee34.json")
    p2b = _load("results/transfer/phase2b_bus_location.json")
    s2l = _load("results/transfer/signal_to_load.json")
    if p2 and p3 and p2b and s2l:
        def _s2l_feeder(fdict: dict, rkeys: tuple[str, ...]) -> dict:
            by_r = fdict.get("by_resistance") or {}
            out_r = {}
            for rk in rkeys:
                if rk in by_r:
                    k_clean = rk[:-2] if rk.endswith(".0") else rk.replace(".", "p")
                    out_r[k_clean] = _opt_dict({
                        "fault_current_median_a": (by_r[rk].get("fault_current_a") or {}).get("median"),
                        "share_of_head_median": (by_r[rk].get("share_of_head_current") or {}).get("median"),
                    })
            return _opt_dict({
                "head_device": fdict.get("head_device"),
                "head_current_a": fdict.get("head_current_a"),
                "nominal_kv_ln": fdict.get("nominal_kv_ln"),
                "by_r": out_r,
            })

        s2l_f = s2l.get("feeders") or {}
        p2_gnn = (p2.get("models") or {}).get("gnn") or {}
        p2b_123 = p2b.get("ieee123") or {}
        p2b_34 = p2b.get("ieee34") or {}
        ext["transfer"] = {
            "simulation_only": True,
            "n_features": len(p2.get("features") or []),
            "ieee123_cv": {
                "events": p2.get("events"),
                "buses": p2.get("buses"),
                "zones": len(p2.get("devices") or []),
                "fpi": _tr_model((p2.get("models") or {}).get("fpi") or {}),
                "per_node_gbdt": _tr_model((p2.get("models") or {}).get("per_node_gbdt") or {}),
                "zone_tree_gnn": _opt_dict({**_tr_model(p2_gnn), "params": p2_gnn.get("parameter_count")}),
            },
            "ieee34": {
                "events": p3.get("events"),
                "buses": p3.get("buses"),
                "zones": len(p3.get("devices") or []),
                "fpi": _tr_model(p3.get("fpi") or {}),
                "zero_shot": {
                    "per_node_gbdt": _tr_model((p3.get("zero_shot") or {}).get("per_node_gbdt") or {}),
                    "zone_tree_gnn": _tr_model((p3.get("zero_shot") or {}).get("gnn") or {}),
                },
                "in_domain_cv": {
                    "per_node_gbdt": _tr_model((p3.get("in_domain_upper_bound") or {}).get("per_node_gbdt") or {}),
                    "zone_tree_gnn": _tr_model((p3.get("in_domain_upper_bound") or {}).get("gnn") or {}),
                },
                "few_shot": {
                    "pct_5": _tr_fs((p3.get("few_shot") or {}).get("pct_5") or {}),
                    "pct_20": _tr_fs((p3.get("few_shot") or {}).get("pct_20") or {}),
                },
                "criteria": _opt_dict({
                    "per_node_gbdt": ((p3.get("pre_committed_criteria") or {}).get("per_node_gbdt") or {}).get("outcome"),
                    "zone_tree_gnn": ((p3.get("pre_committed_criteria") or {}).get("gnn") or {}).get("outcome"),
                }),
            },
            "stage2_bus": {
                "bus_gnn_params": (p2b.get("bus_gnn_config") or {}).get("parameter_count"),
                "ieee123": {
                    "events": p2b_123.get("events"),
                    "buses": p2b_123.get("buses"),
                    "zones": p2b_123.get("zones"),
                    "stage1_acc": p2b_123.get("stage1_zone_accuracy"),
                    "random_in_zone": _s2_entry(p2b_123.get("random_in_zone") or {}),
                    "takagi": _s2_entry(p2b_123.get("reactance_takagi") or {}),
                    "takagi_oracle_zone": _opt_dict({
                        "top1": (p2b_123.get("reactance_takagi_oracle_zone") or {}).get("top1"),
                        "top3": (p2b_123.get("reactance_takagi_oracle_zone") or {}).get("top3"),
                    }),
                    "bus_gnn_cv": _s2_entry(p2b_123.get("bus_graph_gnn_cv") or {}),
                },
                "ieee34": {
                    "events": p2b_34.get("events"),
                    "buses": p2b_34.get("buses"),
                    "zones": p2b_34.get("zones"),
                    "stage1_acc": p2b_34.get("stage1_zone_accuracy"),
                    "random_in_zone": _s2_entry(p2b_34.get("random_in_zone") or {}),
                    "takagi": _s2_entry(p2b_34.get("reactance_takagi") or {}),
                    "takagi_oracle_zone": _opt_dict({
                        "top1": (p2b_34.get("reactance_takagi_oracle_zone") or {}).get("top1"),
                        "top3": (p2b_34.get("reactance_takagi_oracle_zone") or {}).get("top3"),
                    }),
                    "bus_gnn_zero_shot": _s2_entry(p2b_34.get("bus_graph_gnn_zero_shot") or {}),
                    "bus_gnn_in_domain_cv": _s2_entry(p2b_34.get("bus_graph_gnn_in_domain_cv") or {}),
                },
            },
            "signal_to_load": {
                "ieee123": _s2l_feeder(s2l_f.get("ieee123") or {}, ("100.0", "400.0")),
                "ieee34": _s2l_feeder(s2l_f.get("ieee34") or {}, ("100.0", "400.0", "1000.0", "2500.0", "10000.0")),
                "ieee37": _s2l_feeder(s2l_f.get("ieee37") or {}, ("0.01", "100.0", "400.0")),
            },
        }

    # 2. Multi-feeder zero-shot benchmark (15 IEEE/EPRI/CIGRE feeders audited; 12 evaluated, 3 excluded)
    mf = _load("results/transfer/multi_feeder_benchmark.json")
    if mf:
        mfc = mf.get("counts") or {}
        evaluated_rows: list[dict] = []
        excluded_rows: list[dict] = []
        for r in mf.get("reference_feeders") or []:
            ds_ref = _load(f"results/transfer/dataset_{r.get('feeder')}.json") or {}
            ds_dev = ds_ref.get("devices") or []
            # 400 ohm ground-fault accuracy: CV on IEEE 123-bus, zero-shot on the reference unseen feeders
            ph = _load("results/transfer/phase2_ieee123.json" if r.get("feeder") == "ieee123"
                       else f"results/transfer/phase3_{r.get('feeder')}.json") or {}
            ph_m = ph.get("models") if r.get("feeder") == "ieee123" else ph.get("zero_shot")
            ph_m = ph_m or {}
            r400 = lambda m: ((m or {}).get("slg_by_resistance") or {}).get("400.0")
            evaluated_rows.append(_opt_dict({
                "gbdt_slg400": r400(ph_m.get("per_node_gbdt")),
                "gnn_slg400": r400(ph_m.get("gnn")),
                "fpi_slg400": r400((ph.get("models") or {}).get("fpi") if r.get("feeder") == "ieee123" else ph.get("fpi")),
                "fault_buses": sum(int(x.get("buses") or 0) for x in ds_dev) or None,
                "devices": len(ds_dev) or None,
                "nominal_kw": round(sum(float(x.get("kw_nominal") or 0) for x in ds_dev), 1) or None,
                "scenarios": ds_ref.get("scenarios"),
                "placement": ds_ref.get("placement"),
                "feeder": r.get("feeder"),
                "label": r.get("label"),
                "family": r.get("family"),
                "role": "train_cv" if r.get("status") == "reference_train_cv" else "reference_unseen",
                "status": r.get("status"),
                "verdict": r.get("verdict"),
                "freq_hz": r.get("freq_hz"),
                "head_kv_ll": r.get("head_kv_ll"),
                "zones": r.get("zones"),
                "cycles": r.get("cycles"),
                "events": r.get("events_converged"),
                "fpi_acc": r.get("fpi_acc"),
                "gbdt_acc": r.get("gbdt_acc"),
                "gnn_acc": r.get("gnn_acc"),
                "gbdt_phase": r.get("gbdt_phase"),
                "gnn_phase": r.get("gnn_phase"),
                "gbdt_slg": r.get("gbdt_slg"),
                "gnn_slg": r.get("gnn_slg"),
                "gbdt_miss": r.get("gbdt_miss"),
                "gnn_miss": r.get("gnn_miss"),
                "chance": (1.0 / r["zones"]) if r.get("zones") else None,
                "slg400_share": (r["slg_400_a"] / r["head_current_a"])
                if r.get("slg_400_a") and r.get("head_current_a") else None,
            }))
        new_eval_rows: list[dict] = []
        for r in mf.get("new_feeders") or []:
            if r.get("fpi") and r.get("zero_shot_gbdt") and r.get("zero_shot_gnn"):
                zg, zn = r["zero_shot_gbdt"], r["zero_shot_gnn"]
                row = _opt_dict({
                    "feeder": r.get("feeder"),
                    "label": r.get("label"),
                    "family": r.get("family"),
                    "role": "new_unseen",
                    "status": r.get("status"),
                    "verdict": r.get("verdict"),
                    "freq_hz": r.get("freq_hz"),
                    "head_kv_ll": r.get("head_kv_ll"),
                    "zones": r.get("zones"),
                    "cycles": r.get("cycles"),
                    "events": r.get("events_converged"),
                    "total_buses": r.get("total_buses"),
                    "fpi_acc": (r.get("fpi") or {}).get("accuracy"),
                    "gbdt_acc": zg.get("accuracy"),
                    "gnn_acc": zn.get("accuracy"),
                    "gbdt_phase": zg.get("phase_faults_accuracy"),
                    "gnn_phase": zn.get("phase_faults_accuracy"),
                    "gbdt_slg": (zg.get("by_fault_type") or {}).get("SLG"),
                    "gnn_slg": (zn.get("by_fault_type") or {}).get("SLG"),
                    "gbdt_miss": zg.get("missing_sensor_mean"),
                    "gnn_miss": zn.get("missing_sensor_mean"),
                    "margin_over_fpi": r.get("margin_over_fpi"),
                    "chance": (1.0 / r["zones"]) if r.get("zones") else None,
                    "slg400_share": (((r.get("signal_to_load") or {}).get("by_resistance") or {})
                                     .get("400.0") or {}).get("share_of_head_median"),
                    "sampled_buses": r.get("sampled_buses"),
                    "eligible_buses": r.get("primary_eligible_buses"),
                    "scenarios": r.get("scenarios"),
                    "description": r.get("description"),
                    "devices": len(r.get("devices") or []) or None,
                    "nominal_kw": r.get("nominal_kw"),
                    "sampling_mode": r.get("sampling_mode"),
                    "fpi_slg400": ((r.get("fpi") or {}).get("slg_by_resistance") or {}).get("400.0"),
                    "gbdt_slg400": (zg.get("slg_by_resistance") or {}).get("400.0"),
                    "gnn_slg400": (zn.get("slg_by_resistance") or {}).get("400.0"),
                })
                evaluated_rows.append(row)
                new_eval_rows.append(row)
            else:
                excluded_rows.append(_opt_dict({
                    "feeder": r.get("feeder"),
                    "label": r.get("label"),
                    "family": r.get("family"),
                    "status": r.get("status"),
                    "verdict": r.get("verdict"),
                    "freq_hz": r.get("freq_hz"),
                    "total_buses": r.get("total_buses"),
                    "cycles": r.get("cycles"),
                    "reason": r.get("reason"),
                }))
        mf_prov = _load("results/provenance/transfer_multi_feeder_benchmark.json") or {}
        # spread of cross-validated accuracy over the hyperparameter settings tried (selection on the same folds)
        audit: dict = {}
        p2t = ((p2 or {}).get("tuning_ieee123_only") or {}) if p2 else {}
        ag123 = _load("results/active_grid/phase_active_ieee123.json") or {}
        agt = ag123.get("tuning_ieee123_only") or {}
        for key, trials, acc_key in (("passive_gbdt", p2t.get("per_node_gbdt"), "accuracy"),
                                     ("passive_gnn", p2t.get("gnn"), "accuracy"),
                                     ("active_gbdt", agt.get("per_node_gbdt"), "overall_accuracy"),
                                     ("active_gatv2", agt.get("active_gatv2"), "overall_accuracy")):
            accs = [t.get(acc_key) for t in (trials or []) if t.get(acc_key) is not None]
            if accs:
                audit[key] = {"n_configs": len(accs), "best": max(accs), "worst": min(accs), "spread": max(accs) - min(accs)}
        best_pick = [r for r in new_eval_rows if r.get("gbdt_acc") is not None and r.get("gnn_acc") is not None]
        audit["benchmark_gbdt_pass"] = sum(1 for r in best_pick if r["gbdt_acc"] >= 0.80 and r["gbdt_acc"] - r["fpi_acc"] >= 0.15)
        audit["benchmark_gnn_pass"] = sum(1 for r in best_pick if r["gnn_acc"] >= 0.80 and r["gnn_acc"] - r["fpi_acc"] >= 0.15)
        audit["benchmark_n"] = len(best_pick)
        audit["gnn_params"] = (((p2 or {}).get("models") or {}).get("gnn") or {}).get("parameter_count")
        audit["gatv2_params"] = ((ag123.get("models") or {}).get("active_gatv2") or {}).get("parameter_count")
        ext["multi_feeder"] = {
            "simulation_only": True,
            "audit": audit,
            "run_record": _opt_dict({"written_utc": mf_prov.get("written_utc"), "git_commit": mf_prov.get("git_commit"),
                                     "source_clean": mf_prov.get("source_clean")}),
            "counts": {
                "total_audited": int(mfc.get("reference_feeders", 0)) + int(mfc.get("new_feeders_audited", 0)),
                "total_evaluated": len(evaluated_rows),
                "reference_feeders": mfc.get("reference_feeders"),
                "new_feeders_audited": mfc.get("new_feeders_audited"),
                "new_feeders_evaluated": mfc.get("new_feeders_evaluated"),
                "total_unseen_evaluated": mfc.get("total_unseen_evaluated"),
                "pass_new": mfc.get("pass"),
                "out_of_scope_or_unavailable": mfc.get("out_of_scope_or_unavailable"),
            },
            "summary": _opt_dict({
                "new_events_total": sum(r["events"] for r in new_eval_rows),
                "all_events_total": sum(r["events"] for r in evaluated_rows),
                "new_fpi_min": min(r["fpi_acc"] for r in new_eval_rows) if new_eval_rows else None,
                "new_fpi_max": max(r["fpi_acc"] for r in new_eval_rows) if new_eval_rows else None,
                "new_gbdt_min": min(r["gbdt_acc"] for r in new_eval_rows) if new_eval_rows else None,
                "new_gbdt_max": max(r["gbdt_acc"] for r in new_eval_rows) if new_eval_rows else None,
                "new_gnn_min": min(r["gnn_acc"] for r in new_eval_rows) if new_eval_rows else None,
                "new_gnn_max": max(r["gnn_acc"] for r in new_eval_rows) if new_eval_rows else None,
            }),
            "feeders": evaluated_rows,
            "excluded": excluded_rows,
        }

    # 3. Active distribution grids (DER 0-50%, closed loops, disturbances) & Split Conformal safety
    ag123 = _load("results/active_grid/phase_active_ieee123.json")
    ag34 = _load("results/active_grid/phase_active_ieee34.json")
    agconf = _load("results/active_grid/conformal_safety.json")
    agpost = _load("results/active_grid/conformal_posthoc.json")
    agcal = _load("results/active_grid/conformal_calsize.json")
    if ag123 and ag34 and agconf and agpost and agcal:
        def _cal_map(cal_m: dict) -> dict:
            by_f = {f"pct_{int(round(r['fraction'] * 100))}": _calsize_row(r) for r in (cal_m.get("by_fraction") or [])}
            sf = cal_m.get("smallest_fraction_meeting_criterion")
            return {
                "by_fraction": by_f,
                "criterion_met": sf is not None,
                "smallest_fraction_label": f"{int(round(sf * 100))}%" if sf is not None else "none (≤40%)",
            }

        def _conf_rand_model(mkey: str) -> dict:
            t95 = (((agpost.get("results") or {}).get(mkey) or {}).get("aps_rand") or {}).get("target_95") or {}
            return {
                "ieee123": _conf_block(t95.get("ieee123_cross_conformal") or {}),
                "ieee34_zero_shot": _conf_block(t95.get("ieee34_zero_shot_q_from_123") or {}),
                "ieee34_recal_5pct_10d": _conf_block(t95.get("ieee34_recal_5pct_buses") or {}),
                "ieee34_calsize": _cal_map((agcal.get("models") or {}).get(mkey) or {}),
            }

        def _conf_det_model(mkey: str) -> dict:
            c123 = ((agconf.get("ieee123_bus_disjoint_cv") or {}).get(mkey) or {}).get("target_95") or {}
            c34 = (agconf.get("ieee34_transfer") or {}).get(mkey) or {}
            z34 = (c34.get("zero_shot_q_from_123") or {}).get("target_95") or {}
            r34 = (c34.get("recal_5pct_buses_no_retrain") or {}).get("target_95") or {}
            return {
                "ieee123": _opt_dict({
                    "coverage": c123.get("empirical_coverage"),
                    "avg_set_size": c123.get("avg_set_size"),
                    "autonomous_share": c123.get("autonomous_share"),
                    "autonomous_accuracy": c123.get("autonomous_accuracy"),
                    "autonomous_nofault_fpr": c123.get("autonomous_nofault_fpr"),
                }),
                "ieee34_zero_shot": _opt_dict({
                    "coverage": z34.get("empirical_coverage"),
                    "avg_set_size": z34.get("avg_set_size"),
                    "autonomous_share": z34.get("autonomous_share"),
                    "autonomous_accuracy": z34.get("autonomous_accuracy"),
                    "autonomous_nofault_fpr": z34.get("autonomous_nofault_fpr"),
                }),
                "ieee34_recal_5pct": _opt_dict({
                    "coverage": r34.get("empirical_coverage_mean"),
                    "avg_set_size": r34.get("avg_set_size_mean"),
                    "autonomous_share": r34.get("autonomous_share_mean"),
                    "autonomous_accuracy": r34.get("autonomous_accuracy_mean"),
                    "autonomous_nofault_fpr": r34.get("autonomous_nofault_fpr_mean"),
                }),
            }

        ag123_gat = (ag123.get("models") or {}).get("active_gatv2") or {}
        ag34_crit = ag34.get("pre_committed_criteria") or {}
        ext["active_grid"] = {
            "simulation_only": True,
            "der_range_pct": [0, 50],
            "ieee123": {
                "events": ag123.get("events"),
                "fault_events": ag123.get("fault_events"),
                "nofault_events": ag123.get("nofault_events"),
                "topologies": ag123.get("topologies"),
                "n_topologies": len(ag123.get("topologies") or []),
                "fpi": _ag_model((ag123.get("models") or {}).get("fpi") or {}),
                "per_node_gbdt": _ag_model((ag123.get("models") or {}).get("per_node_gbdt") or {}),
                "active_gatv2": _opt_dict({**_ag_model(ag123_gat), "params": ag123_gat.get("parameter_count")}),
            },
            "ieee34": {
                "events": ag34.get("events"),
                "fault_events": ag34.get("fault_events"),
                "nofault_events": ag34.get("nofault_events"),
                "topologies": ag34.get("topologies"),
                "n_topologies": len(ag34.get("topologies") or []),
                "fpi": _ag_model(ag34.get("fpi") or {}, include_1k_10k=True),
                "zero_shot": {
                    "per_node_gbdt": _ag_model((ag34.get("zero_shot") or {}).get("per_node_gbdt") or {}, include_1k_10k=True),
                    "active_gatv2": _ag_model((ag34.get("zero_shot") or {}).get("active_gatv2") or {}, include_1k_10k=True),
                },
                "in_domain_cv": {
                    "per_node_gbdt": _ag_model((ag34.get("in_domain_upper_bound") or {}).get("per_node_gbdt") or {}, include_1k_10k=True),
                    "active_gatv2": _ag_model((ag34.get("in_domain_upper_bound") or {}).get("active_gatv2") or {}, include_1k_10k=True),
                },
                "few_shot": {
                    "pct_5": _ag_fs((ag34.get("few_shot") or {}).get("pct_5") or {}),
                    "pct_20": _ag_fs((ag34.get("few_shot") or {}).get("pct_20") or {}),
                },
                "criteria": _opt_dict({
                    "c1_breaks_fpi": (ag34_crit.get("C1_breaks_legacy_fpi") or {}).get("met"),
                    "c2_gatv2_margin_ge_25pct": (ag34_crit.get("C2_zero_shot_transfer_and_gnn_value") or {}).get("gatv2_margin_ge_25pct"),
                    "c2_gatv2_fpr_le_5pct": (ag34_crit.get("C2_zero_shot_transfer_and_gnn_value") or {}).get("gatv2_fpr_le_5pct"),
                    "c3_conformal_95_met": (ag34_crit.get("C3_conformal_safety_95") or {}).get("met"),
                }),
            },
            "conformal_aps_det_95": {
                "per_node_gbdt": _conf_det_model("per_node_gbdt"),
                "active_gatv2": _conf_det_model("active_gatv2"),
            },
            "conformal_aps_rand_95": {
                "calsize_draws": agcal.get("draws"),
                "calsize_criterion": agcal.get("criterion"),
                "per_node_gbdt": _conf_rand_model("per_node_gbdt"),
                "active_gatv2": _conf_rand_model("active_gatv2"),
            },
        }

    # 4. Underground ungrounded-delta physical boundary (IEEE 37-bus)
    p37 = _load("results/transfer/phase3_ieee37.json")
    p2b37 = _load("results/transfer/phase2b_bus_ieee37.json")
    ag37 = _load("results/active_grid_ieee37/phase_active_ieee37.json")
    ag37post = _load("results/active_grid_ieee37/conformal_posthoc.json")
    ag37cal = _load("results/active_grid_ieee37/conformal_calsize.json")
    if p37 and p2b37 and ag37 and ag37cal:
        def _p37_m(m: dict) -> dict:
            return _opt_dict({
                "accuracy": m.get("accuracy"),
                "phase_faults_accuracy": m.get("phase_faults_accuracy"),
                "slg": (m.get("by_fault_type") or {}).get("SLG"),
                "missing_sensor_mean": m.get("missing_sensor_mean"),
                "missing_sensor_min": m.get("missing_sensor_min"),
            })

        def _conf37_model(mkey: str) -> dict:
            cal_m = (ag37cal.get("models") or {}).get(mkey) or {}
            by_f = {f"pct_{int(round(r['fraction'] * 100))}": _calsize_row(r) for r in (cal_m.get("by_fraction") or [])}
            out = {
                "raw_argmax_accuracy": cal_m.get("raw_argmax_accuracy_full"),
                "raw_nofault_fpr": cal_m.get("raw_nofault_fpr_full"),
                "by_fraction": by_f,
                "smallest_fraction_meeting_criterion": cal_m.get("smallest_fraction_meeting_criterion"),
                "smallest_fraction_meeting_full_a3_recal": cal_m.get("smallest_fraction_meeting_full_a3_recal"),
            }
            if ag37post:
                t95 = (((ag37post.get("results") or {}).get(mkey) or {}).get("aps_rand") or {}).get("target_95") or {}
                out["zero_shot_q123"] = _conf_block(t95.get("ieee37_zero_shot_q_from_123") or {})
                out["recal_5pct_10d"] = _conf_block(t95.get("ieee37_recal_5pct_buses") or {})
            return _opt_dict(out)

        p2b37_i = p2b37.get("ieee37") or {}
        ag37_a2 = (ag37.get("pre_committed_criteria") or {}).get("A2_zero_shot_active_transfer") or {}
        ext["ieee37"] = {
            "simulation_only": True,
            "passive": {
                "events": p37.get("events"),
                "buses": p37.get("buses"),
                "zones": len(p37.get("devices") or []),
                "fpi": _p37_m(p37.get("fpi") or {}),
                "zero_shot": {
                    "per_node_gbdt": _p37_m((p37.get("zero_shot") or {}).get("per_node_gbdt") or {}),
                    "zone_tree_gnn": _p37_m((p37.get("zero_shot") or {}).get("gnn") or {}),
                },
                "in_domain_cv": {
                    "per_node_gbdt": _p37_m((p37.get("in_domain_upper_bound") or {}).get("per_node_gbdt") or {}),
                    "zone_tree_gnn": _p37_m((p37.get("in_domain_upper_bound") or {}).get("gnn") or {}),
                },
                "few_shot": {
                    "pct_5": _tr_fs((p37.get("few_shot") or {}).get("pct_5") or {}),
                    "pct_20": _tr_fs((p37.get("few_shot") or {}).get("pct_20") or {}),
                },
                "verdict_gbdt": ((p37.get("pre_committed_criteria") or {}).get("per_node_gbdt") or {}).get("zero_shot_verdict"),
                "verdict_gnn": ((p37.get("pre_committed_criteria") or {}).get("gnn") or {}).get("zero_shot_verdict"),
            },
            "stage2_bus": {
                "stage1_acc": p2b37_i.get("stage1_zone_accuracy"),
                "stage1_phase_acc": p2b37_i.get("stage1_phase_faults_zone_accuracy"),
                "random_in_zone": _s2_entry(p2b37_i.get("random_in_zone") or {}),
                "takagi": _s2_entry(p2b37_i.get("reactance_takagi") or {}),
                "takagi_oracle_zone": _s2_entry(p2b37_i.get("reactance_takagi_oracle_zone") or {}),
                "bus_gnn_zero_shot": _s2_entry(p2b37_i.get("bus_graph_gnn_zero_shot") or {}),
                "bus_gnn_in_domain_cv": _s2_entry(p2b37_i.get("bus_graph_gnn_in_domain_cv") or {}),
                "verdict": ((p2b37.get("pre_committed_criteria") or {}).get("stage1_predicted_zone") or {}).get("verdict"),
            },
            "active": {
                "events": ag37.get("events"),
                "fault_events": ag37.get("fault_events"),
                "nofault_events": ag37.get("nofault_events"),
                "topologies": ag37.get("topologies"),
                "fpi": _ag_model(ag37.get("fpi") or {}),
                "zero_shot": {
                    "per_node_gbdt": _ag_model((ag37.get("zero_shot") or {}).get("per_node_gbdt") or {}),
                    "active_gatv2": _ag_model((ag37.get("zero_shot") or {}).get("active_gatv2") or {}),
                },
                "in_domain_cv": {
                    "per_node_gbdt": _ag_model((ag37.get("in_domain_upper_bound") or {}).get("per_node_gbdt") or {}),
                    "active_gatv2": _ag_model((ag37.get("in_domain_upper_bound") or {}).get("active_gatv2") or {}),
                },
                "few_shot": {
                    "pct_5": _ag_fs((ag37.get("few_shot") or {}).get("pct_5") or {}),
                    "pct_20": _ag_fs((ag37.get("few_shot") or {}).get("pct_20") or {}),
                },
                "verdict": ag37_a2.get("verdict"),
                "verdict_gbdt": (ag37_a2.get("per_node_gbdt") or {}).get("verdict"),
                "verdict_gatv2": (ag37_a2.get("active_gatv2") or {}).get("verdict"),
            },
            "conformal_aps_rand_95": {
                "draws": ag37cal.get("draws"),
                "per_node_gbdt": _conf37_model("per_node_gbdt"),
                "active_gatv2": _conf37_model("active_gatv2"),
            },
        }

    # 5. Two-tier Edge HIF-Sensor -> Graph FLISR (clean 60 Hz paired ablation)
    hf_p123 = _load("results/hif_fusion/passive_ieee123.json")
    hf_p34 = _load("results/hif_fusion/passive_ieee34.json")
    hf_a123 = _load("results/hif_fusion/active_ieee123.json")
    hf_a34 = _load("results/hif_fusion/active_ieee34.json")
    hf_conf = _load("results/hif_fusion/conformal_hif.json")
    if hf_p123 and hf_p34 and hf_a123 and hf_a34 and hf_conf:
        hf_crit = hf_a34.get("pre_committed_criteria") or {}
        ext["hif_fusion"] = {
            "simulation_only": True,
            "tier1_model_sha256": hf_p123.get("tier1_model_sha256"),
            "verdicts": _opt_dict({
                "H1": (hf_crit.get("H1_ieee123_hif_gain") or {}).get("verdict"),
                "H2": (hf_crit.get("H2_ieee34_zero_shot") or {}).get("verdict"),
                "H3": (hf_crit.get("H3_nofault_7_disturbances") or {}).get("verdict"),
                "H4": (hf_crit.get("H4_missing_sensor_and_conformal") or {}).get("verdict"),
            }),
            "passive_123": {
                "events": hf_p123.get("events"),
                "arcing_events": hf_p123.get("arcing_events"),
                "fpi": _hf_pass(hf_p123.get("fpi") or {}),
                "per_node_gbdt": _hf_pair(hf_p123.get("ablations") or {}, "per_node_gbdt", _hf_pass),
                "zone_tree_gnn": _hf_pair(hf_p123.get("ablations") or {}, "zone_tree_gnn", _hf_pass),
            },
            "passive_34": {
                "events": hf_p34.get("events"),
                "arcing_events": hf_p34.get("arcing_events"),
                "fpi": _hf_pass(hf_p34.get("fpi") or {}),
                "zero_shot": {
                    "per_node_gbdt": _hf_pair(hf_p34.get("zero_shot") or {}, "per_node_gbdt", _hf_pass),
                    "zone_tree_gnn": _hf_pair(hf_p34.get("zero_shot") or {}, "zone_tree_gnn", _hf_pass),
                },
                "few_shot_20pct": {
                    "per_node_gbdt": _hf_fs_pair(((hf_p34.get("few_shot") or {}).get("pct_20") or {}).get("ablations") or {}, "per_node_gbdt"),
                    "zone_tree_gnn": _hf_fs_pair(((hf_p34.get("few_shot") or {}).get("pct_20") or {}).get("ablations") or {}, "zone_tree_gnn"),
                },
            },
            "active_123": {
                "events": hf_a123.get("events"),
                "fault_events": hf_a123.get("fault_events"),
                "nofault_events": hf_a123.get("nofault_events"),
                "arcing_events": hf_a123.get("arcing_events"),
                "fpi": _hf_act(hf_a123.get("fpi") or {}),
                "active_per_node_gbdt": _hf_pair(hf_a123.get("ablations") or {}, "active_per_node_gbdt", _hf_act),
                "active_grid_gatv2": _hf_pair(hf_a123.get("ablations") or {}, "active_grid_gatv2", _hf_act),
            },
            "active_34": {
                "events": hf_a34.get("events"),
                "fault_events": hf_a34.get("fault_events"),
                "nofault_events": hf_a34.get("nofault_events"),
                "arcing_events": hf_a34.get("arcing_events"),
                "fpi": _hf_act(hf_a34.get("fpi") or {}, include_1k_10k=True),
                "zero_shot": {
                    "active_per_node_gbdt": _hf_pair(hf_a34.get("zero_shot") or {}, "active_per_node_gbdt", lambda m: _hf_act(m, include_1k_10k=True)),
                    "active_grid_gatv2": _hf_pair(hf_a34.get("zero_shot") or {}, "active_grid_gatv2", lambda m: _hf_act(m, include_1k_10k=True)),
                },
                "few_shot_20pct": {
                    "active_per_node_gbdt": _hf_afs_pair(((hf_a34.get("few_shot") or {}).get("pct_20") or {}).get("ablations") or {}, "active_per_node_gbdt"),
                    "active_grid_gatv2": _hf_afs_pair(((hf_a34.get("few_shot") or {}).get("pct_20") or {}).get("ablations") or {}, "active_grid_gatv2"),
                },
            },
            "conformal_aps_rand_95": {
                "active_per_node_gbdt": _hf_conf_pair(hf_conf, "active_per_node_gbdt"),
                "active_grid_gatv2": _hf_conf_pair(hf_conf, "active_grid_gatv2"),
            },
        }

    # 6. Branch-10 Realistic Two-tier HIF-Fusion v2 (Kirchhoff arc-path + 52a open-switch interlock)
    rp123 = _load("results/hif_fusion_realistic/passive_ieee123.json")
    rp34 = _load("results/hif_fusion_realistic/passive_ieee34.json")
    ra123 = _load("results/hif_fusion_realistic/active_ieee123.json")
    ra34 = _load("results/hif_fusion_realistic/active_ieee34.json")
    rconf = _load("results/hif_fusion_realistic/conformal_hif.json")
    rsum = _load("results/hif_fusion_realistic/summary.json")
    if rp123 and rp34 and ra123 and ra34 and rconf and rsum:
        r4_pairs = ((rsum.get("criteria_details") or {}).get("R4_missing_sensor_resilience") or {}).get("pairs") or {}
        t1m = rsum.get("tier1_edge_model") or {}
        ext["hif_fusion_realistic"] = {
            "available": True,
            "simulation_only": True,
            "runtime_s": rsum.get("runtime_s"),
            "tier1_edge_model": _opt_dict({
                "path": t1m.get("path"),
                "sha256": t1m.get("sha256"),
                "params": t1m.get("params"),
                "bytes": t1m.get("bytes"),
                "threshold": t1m.get("threshold"),
            }),
            "verdicts": {k: rsum["verdicts"][k] for k in ("R1", "R2", "R3", "R3a", "R3b", "R4") if k in (rsum.get("verdicts") or {})},
            "r4_summary": {
                "pairs_passed": sum(1 for v in r4_pairs.values() if v.get("ok_within_1pt")),
                "pairs_total": len(r4_pairs),
                "failed_pairs": [k for k, v in r4_pairs.items() if not v.get("ok_within_1pt")],
                "pairs": {
                    k: _opt_dict({
                        "base_miss": v.get("base_missing_mean"),
                        "edge_miss": v.get("fused_missing_mean"),
                        "delta_miss": v.get("delta_missing_mean"),
                        "base_miss_200_400": v.get("base_missing_slg_200_400_mean"),
                        "edge_miss_200_400": v.get("fused_missing_slg_200_400_mean"),
                        "ok": v.get("ok_within_1pt"),
                    })
                    for k, v in r4_pairs.items()
                },
            },
            "passive_123": {
                "events": rp123.get("events"),
                "buses": rp123.get("buses"),
                "arcing_events": rp123.get("arcing_events"),
                "intermittent_events": rp123.get("intermittent_arc_events"),
                "continuous_events": rp123.get("continuous_arc_events"),
                "fpi": _hf_pass(rp123.get("fpi") or {}),
                "ml_full": _hf_pair(rp123.get("ablations") or {}, "ml_full", _hf_pass),
                "per_node_gbdt": _hf_pair(rp123.get("ablations") or {}, "per_node_gbdt", _hf_pass),
                "zone_tree_gnn": _hf_pair(rp123.get("ablations") or {}, "zone_tree_gnn", _hf_pass),
            },
            "passive_34": {
                "events": rp34.get("events"),
                "buses": rp34.get("buses"),
                "arcing_events": rp34.get("arcing_events"),
                "intermittent_events": rp34.get("intermittent_arc_events"),
                "continuous_events": rp34.get("continuous_arc_events"),
                "fpi": _hf_pass(rp34.get("fpi") or {}),
                "zero_shot": {
                    "per_node_gbdt": _hf_pair(rp34.get("zero_shot") or {}, "per_node_gbdt", _hf_pass),
                    "zone_tree_gnn": _hf_pair(rp34.get("zero_shot") or {}, "zone_tree_gnn", _hf_pass),
                },
                "few_shot_5pct": {
                    "per_node_gbdt": _hf_fs_pair(((rp34.get("few_shot") or {}).get("pct_5") or {}).get("ablations") or {}, "per_node_gbdt"),
                    "zone_tree_gnn": _hf_fs_pair(((rp34.get("few_shot") or {}).get("pct_5") or {}).get("ablations") or {}, "zone_tree_gnn"),
                },
                "few_shot_20pct": {
                    "per_node_gbdt": _hf_fs_pair(((rp34.get("few_shot") or {}).get("pct_20") or {}).get("ablations") or {}, "per_node_gbdt"),
                    "zone_tree_gnn": _hf_fs_pair(((rp34.get("few_shot") or {}).get("pct_20") or {}).get("ablations") or {}, "zone_tree_gnn"),
                },
            },
            "active_123": {
                "events": ra123.get("events"),
                "fault_events": ra123.get("fault_events"),
                "nofault_events": ra123.get("nofault_events"),
                "arcing_events": ra123.get("arcing_events"),
                "fpi": _hf_act(ra123.get("fpi") or {}),
                "active_per_node_gbdt": _hf_pair(ra123.get("ablations") or {}, "active_per_node_gbdt", _hf_act),
                "active_grid_gatv2": _hf_pair(ra123.get("ablations") or {}, "active_grid_gatv2", _hf_act),
            },
            "active_34": {
                "events": ra34.get("events"),
                "fault_events": ra34.get("fault_events"),
                "nofault_events": ra34.get("nofault_events"),
                "arcing_events": ra34.get("arcing_events"),
                "fpi": _hf_act(ra34.get("fpi") or {}, include_1k_10k=True),
                "zero_shot": {
                    "active_per_node_gbdt": _hf_pair(ra34.get("zero_shot") or {}, "active_per_node_gbdt", lambda m: _hf_act(m, include_1k_10k=True)),
                    "active_grid_gatv2": _hf_pair(ra34.get("zero_shot") or {}, "active_grid_gatv2", lambda m: _hf_act(m, include_1k_10k=True)),
                },
                "few_shot_5pct": {
                    "active_per_node_gbdt": _hf_afs_pair(((ra34.get("few_shot") or {}).get("pct_5") or {}).get("ablations") or {}, "active_per_node_gbdt"),
                    "active_grid_gatv2": _hf_afs_pair(((ra34.get("few_shot") or {}).get("pct_5") or {}).get("ablations") or {}, "active_grid_gatv2"),
                },
                "few_shot_20pct": {
                    "active_per_node_gbdt": _hf_afs_pair(((ra34.get("few_shot") or {}).get("pct_20") or {}).get("ablations") or {}, "active_per_node_gbdt"),
                    "active_grid_gatv2": _hf_afs_pair(((ra34.get("few_shot") or {}).get("pct_20") or {}).get("ablations") or {}, "active_grid_gatv2"),
                },
            },
            "conformal_aps_rand_95": {
                "active_per_node_gbdt": _hf_conf_pair(rconf, "active_per_node_gbdt"),
                "active_grid_gatv2": _hf_conf_pair(rconf, "active_grid_gatv2"),
            },
        }

    # 7. 8,760-hour PJM AEP 2017 seasonal restoration study
    hr = _load("results/hourly/hourly.json")
    ls_info = _load("results/hourly/load_shape_info.json")
    if hr and ls_info:
        ls_csv = ROOT / "results" / "hourly" / "load_shape.csv"
        mult_median = None
        if ls_csv.exists():
            rel_csv = "results/hourly/load_shape.csv"
            if rel_csv not in built_from:
                built_from.append(rel_csv)
            with open(ls_csv, encoding="utf-8") as f:
                mults = [float(row["mult"]) for row in csv.DictReader(f)]
            if mults:
                mult_median = round(statistics.median(mults), 5)

        byl = hr.get("by_level") or {}
        lv_list = byl.get("level") or []

        def _at_level(target: float) -> dict:
            idx = lv_list.index(target)
            return {
                "level": lv_list[idx],
                "pct_restored": byl["pct_restored"][idx],
                "kw_restored_by_tie": byl["kW_restored_by_tie"][idx],
                "rej_undervoltage": byl["rejected_undervoltage"][idx],
                "rej_overvoltage": byl["rejected_overvoltage"][idx],
                "rej_overload": byl["rejected_overload"][idx],
            }

        yr = hr.get("year") or {}
        lmin = yr.get("level_min", 0.45)
        yr_idxs = [i for i, lv in enumerate(lv_list) if lmin <= lv <= 1.0]
        td = hr.get("typical_day") or {}

        def _season(sk: str) -> dict:
            s = td.get(sk) or {}
            pr = s.get("pct_restored") or []
            prh = s.get("pct_restored_held") or []
            ms = s.get("mult") or []
            return _opt_dict({
                "days": s.get("days"),
                "mult_min": min(ms) if ms else None,
                "mult_max": max(ms) if ms else None,
                "pct_restored_min": min(pr) if pr else None,
                "pct_restored_max": max(pr) if pr else None,
                "pct_restored_mean": round(sum(pr) / len(pr), 4) if pr else None,
                "pct_restored_held_mean": round(sum(prh) / len(prh), 4) if prh else None,
            })

        lim = hr.get("limits") or {}
        ext["hourly"] = _opt_dict({
            "year": ls_info.get("year"),
            "hours": ls_info.get("hours"),
            "peak_mw": ls_info.get("peak_mw"),
            "source": ls_info.get("source"),
            "hold_hours": hr.get("hold_hours"),
            "kw_downstream_healthy_total": hr.get("kW_downstream_healthy_total"),
            "mult_min": yr.get("mult_min"),
            "mult_median": mult_median,
            "mult_mean": yr.get("mult_mean"),
            "mult_max": yr.get("mult_max"),
            "levels": hr.get("levels"),
            "annual": _opt_dict({
                "pct_restored_mean": yr.get("pct_restored_mean"),
                "pct_restored_held_mean": yr.get("pct_restored_held_mean"),
                "share_hours_held_lower": yr.get("share_hours_held_lower"),
                "share_hours_at_peak_plan": yr.get("share_hours_at_peak_plan"),
                "hours_undervoltage_rejections": yr.get("hours_with_undervoltage_rejections"),
                "hours_overvoltage_rejections": yr.get("hours_with_overvoltage_rejections"),
                "hours_overload_rejections": yr.get("hours_with_overload_rejections"),
                "hours_nonconverged_rejections": yr.get("hours_with_nonconverged_rejections"),
                "best_pct_in_year": max(byl["pct_restored"][i] for i in yr_idxs) if yr_idxs else None,
                "worst_pct_in_year": min(byl["pct_restored"][i] for i in yr_idxs) if yr_idxs else None,
            }),
            "at_levels": {
                "off_peak_045": _at_level(lmin),
                "median_066": _at_level(0.66),
                "mean_067": _at_level(0.67),
                "peak_100": _at_level(1.0),
                "overload_110": _at_level(1.1),
            },
            "seasonal": {
                "summer": _season("summer"),
                "winter": _season("winter"),
            },
            "limits": _opt_dict({
                "overvoltage_hours": lim.get("hours"),
                "max_vmax_pu": lim.get("max_vmax_pu"),
                "zones": lim.get("zones"),
            }),
        })

    # 8. Relay COMTRADE (IEC 60255-24), LTspice circuit verification & SHA-256 provenance counts
    ct = _load("results/comtrade/summary.json")
    sp = _load("results/spice/summary.json")
    prov_dir = RES / "provenance"
    prov_manifests = sorted(prov_dir.glob("*.json")) if prov_dir.exists() else []
    tier2_files = 0
    if prov_manifests:
        if "results/provenance/*.json" not in built_from:
            built_from.append("results/provenance/*.json")
        for pf in prov_manifests:
            tier2_files += len(json.loads(pf.read_text(encoding="utf-8")).get("files") or {})
    t1_prov = _load("hif_sensor/results/provenance/manifest.json")
    tier1_files = len(t1_prov.get("files") or []) if t1_prov else 0
    if ct and sp:
        ct_c = ct.get("counts") or {}
        ct_p = ct.get("parity") or {}
        sp_m = sp.get("model") or {}
        sp_f = sp.get("fault_rms_a") or {}
        sp_pk = sp.get("first_peak") or {}
        sp_fe = sp.get("frontend") or {}
        sp_h = (sp.get("hif") or {}).get("cases") or {}

        def _sp_hif(rk: str) -> dict:
            c = sp_h.get(rk) or {}
            return _opt_dict({
                "r_fault": c.get("r_fault"),
                "irms_arc_a": c.get("irms_arc"),
                "i1_arc_a": c.get("i1_arc"),
                "h3_pct": c.get("h3_arc_pct"),
                "h5_pct": c.get("h5_arc_pct"),
                "thd_pct": c.get("thd_arc_pct"),
                "adc_counts_span": c.get("adc_counts_span_arc"),
                "dft_error_pct": c.get("dft_error_arc_pct"),
            })

        ext["comtrade_spice"] = {
            "comtrade": {
                "status": ct.get("status"),
                "counts": _opt_dict({
                    "public_samples": ct_c.get("public_samples"),
                    "public_passed": ct_c.get("public_passed"),
                    "synthetic_opendss_events": ct_c.get("synthetic_opendss_events"),
                    "synthetic_opendss_passed": ct_c.get("synthetic_opendss_passed"),
                    "synthetic_ltspice_records": ct_c.get("synthetic_ltspice_records"),
                    "synthetic_ltspice_passed": ct_c.get("synthetic_ltspice_passed"),
                    "synthetic_hif_records": ct_c.get("synthetic_hif_records"),
                    "synthetic_hif_passed": ct_c.get("synthetic_hif_passed"),
                    "total_verified": ct_c.get("total_verified"),
                    "total_passed": ct_c.get("total_passed"),
                }),
                "parity": _opt_dict({
                    "opendss_max_tier2_abs_err": ct_p.get("opendss_max_tier2_abs_err"),
                    "opendss_max_tier2_rel_err": ct_p.get("opendss_max_tier2_rel_err"),
                    "opendss_max_transfer_abs_err": ct_p.get("opendss_max_transfer_abs_err"),
                    "opendss_max_active_abs_err": ct_p.get("opendss_max_active_abs_err"),
                    "opendss_tier2_model_matches": ct_p.get("opendss_tier2_model_matches"),
                    "opendss_transfer_gbdt_matches": ct_p.get("opendss_transfer_gbdt_matches"),
                    "opendss_transfer_gnn_matches": ct_p.get("opendss_transfer_gnn_matches"),
                    "opendss_total_events": ct_p.get("opendss_total_events"),
                    "ltspice_bolted_rms_rel_err_pct": ct_p.get("ltspice_bolted_rms_rel_err_pct"),
                    "ltspice_hif100_i1_rel_err_pct": ct_p.get("ltspice_hif100_i1_rel_err_pct"),
                    "hif_roundtrip_max_feat_abs_err": ct_p.get("hif_roundtrip_max_feat_abs_err"),
                    "hif_roundtrip_p_hif_abs_err": ct_p.get("hif_roundtrip_p_hif_abs_err"),
                }),
                "public_list": [
                    _opt_dict({
                        "id": s.get("id"),
                        "rev_year": s.get("rev_year"),
                        "format": s.get("data_format"),
                        "freq_hz": s.get("frequency_hz"),
                        "sample_rate_hz": s.get("sample_rate_hz"),
                        "n_samples": s.get("n_samples"),
                        "license": s.get("license"),
                        "ok": s.get("ok"),
                    })
                    for s in (ct.get("public_samples") or [])
                ],
            },
            "spice": {
                "bus": sp.get("bus"),
                "dc_offset": _opt_dict({
                    "x_over_r": sp_m.get("x_over_r"),
                    "tau_ms": sp_m.get("tau_ms"),
                    "ltspice_steady_a": sp_f.get("ltspice_steady"),
                    "thevenin_a": sp_f.get("thevenin"),
                    "opendss_3ph_sw1_a": sp_f.get("opendss_3ph_sw1"),
                    "peak_no_offset_a": (sp_pk.get("no_offset") or {}).get("peak_a"),
                    "peak_max_offset_a": (sp_pk.get("max_offset") or {}).get("peak_a"),
                    "asymmetry_max_offset": (sp_pk.get("max_offset") or {}).get("asymmetry"),
                    "asymmetry_ansi": sp.get("asymmetry_ansi_estimate"),
                    "dc_left_1cycle": sp.get("dc_left_after_one_cycle"),
                }),
                "frontend": _opt_dict({
                    "ct_ratio": sp_fe.get("ct_ratio"),
                    "bits": sp_fe.get("bits"),
                    "fc_hz": sp_fe.get("fc_hz"),
                    "vadc_min": sp_fe.get("vadc_min"),
                    "vadc_max": sp_fe.get("vadc_max"),
                    "clipped_samples": sp_fe.get("clipped_samples"),
                    "primary_amps_per_count": sp_fe.get("primary_amps_per_count"),
                    "dft_settle_ms": sp_fe.get("dft_settle_ms_within_5pct"),
                    "dft_max_over_steady": sp_fe.get("dft_max_over_steady"),
                }),
                "hif_arc": {
                    "r100": _sp_hif("100"),
                    "r400": _sp_hif("400"),
                },
            },
            "provenance": {
                "tier2_manifests": len(prov_manifests),
                "tier2_recorded_files": tier2_files,
                "tier1_manifests": 1 if t1_prov else 0,
                "tier1_recorded_files": tier1_files,
                "total_manifests": len(prov_manifests) + (1 if t1_prov else 0),
                "total_recorded_files": tier2_files + tier1_files,
            },
        }

    return ext


def copy_feeder_maps(built_from: list[str]) -> None:
    """Publish the feeder drawing data next to the page (results/feeders/feeder_maps.json)."""
    src = ROOT / "results" / "feeders" / "feeder_maps.json"
    if src.exists():
        (ROOT / "docs" / "study" / "feeder_maps.json").write_bytes(src.read_bytes())
        built_from.append("results/feeders/feeder_maps.json")


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
        "zone_load_spread": config.ZONE_LOAD_SPREAD, "zone_load_clip": list(config.ZONE_LOAD_CLIP),
        "load_drift_zone": config.LOAD_DRIFT_ZONE, "load_drift_spot": config.LOAD_DRIFT_SPOT,
        "scenarios_per_case": config.SCENARIOS_PER_CASE,
        "slg_resistances": config.SLG_RESISTANCES, "phase_resistances": config.PHASE_RESISTANCES,
        "hif_arc_min_r": config.HIF_ARC_MIN_R, "hif_intermittent_prob": config.HIF_INTERMITTENT_PROB,
        "hif_duty_range": list(config.HIF_DUTY_RANGE), "hif_r_eff_max": config.HIF_R_EFF_MAX,
        "noise_mag": config.NOISE_MAG, "noise_ang_deg": config.NOISE_ANG_DEG,
        "ct_bias_mag": config.CT_BIAS_MAG, "ct_bias_ang_deg": config.CT_BIAS_ANG_DEG,
        "pt_bias_mag": config.PT_BIAS_MAG, "pt_bias_ang_deg": config.PT_BIAS_ANG_DEG,
        "noise_i_floor_a": config.NOISE_I_FLOOR_A, "noise_v_floor_pu": config.NOISE_V_FLOOR_PU,
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

    tier1 = {}
    hif_res = ROOT / "hif_sensor" / "results"
    if (hif_res / "metrics.json").exists():
        hm = json.loads((hif_res / "metrics.json").read_text(encoding="utf-8"))
        hv = json.loads((hif_res / "real_vehif.json").read_text(encoding="utf-8")) if (hif_res / "real_vehif.json").exists() else {}
        hp = json.loads((hif_res / "phase15_vehif.json").read_text(encoding="utf-8")) if (hif_res / "phase15_vehif.json").exists() else {}
        hc = json.loads((hif_res / "c_firmware_verify.json").read_text(encoding="utf-8")) if (hif_res / "c_firmware_verify.json").exists() else {}
        hl = json.loads((ROOT / "hif_sensor" / "circuit" / "ltspice_results.json").read_text(encoding="utf-8")) if (ROOT / "hif_sensor" / "circuit" / "ltspice_results.json").exists() else {}
        j20 = hp.get("few_shot_adaptation", {}).get("by_fraction", {}).get("0.2", {}).get("joint_mlp_int8", {})
        z0 = hp.get("few_shot_adaptation", {}).get("zero_shot_phase0", {})
        c0 = hc.get("phase0_official_6_vectors", {})
        tier1 = {
            "params": hm["model"]["params"],
            "bytes": hm["model"]["bytes_int8_weights_float_bias"],
            "sim_det": hm["test_ml_int8"]["detection_rate"],
            "sim_fa": hm["test_ml_int8"]["false_alarm_rate_normal"],
            "f51_det": hm["test_baselines"]["residual_overcurrent_51N"]["detection_rate"],
            "fc_ltspice": hl.get("ac", {}).get("f_minus3dB_Hz", 2045.1),
            "nyq_60_db": hl.get("ac", {}).get("attenuation_at_7680Hz_dB", 46.4),
            "nyq_50r_db": hp.get("freq_50hz_vs_60hz", {}).get("hardware_50hz_vn_retuned_R1p2", {}).get("attenuation_at_nyquist_dB", 46.7),
            "vehif_n": hv.get("real_faults", {}).get("recordings", 250),
            "vehif_det": hv.get("real_faults", {}).get("detection_rate"),
            "vehif_bg_fa": hv.get("background_recordings", {}).get("alarm_rate"),
            "p15_zs": z0.get("real_detection_mean"),
            "p15_det": j20.get("real_detection_mean"),
            "p15_02_zs": z0.get("real_0_to_2A_mean"),
            "p15_02_det": j20.get("real_0_to_2A_mean"),
            "p15_bg_fa": j20.get("real_bg_fa_mean"),
            "c_agree": c0.get("decision_agreement"),
            "c_err": f"{c0.get('max_abs_prob_error', 0):.2e}",
            "c_us": c0.get("host_latency_us_per_inference"),
        }

    hif_real_dir = RES / "hif_fusion_realistic"
    hif_realistic = {"available": False, "status": "NOT_RUN_YET"}
    hif_real_built: list[str] = []
    if (hif_real_dir / "passive_ieee123.json").exists():
        rp123 = json.loads((hif_real_dir / "passive_ieee123.json").read_text(encoding="utf-8"))
        rsum = json.loads((hif_real_dir / "summary.json").read_text(encoding="utf-8")) if (hif_real_dir / "summary.json").exists() else {}
        hif_real_built.append("results/hif_fusion_realistic/passive_ieee123.json")
        if rsum:
            hif_real_built.append("results/hif_fusion_realistic/summary.json")
        ab = rp123.get("ablations") or {}
        b60, fed = ab.get("60Hz_only") or {}, ab.get("60Hz_plus_edge") or {}

        def _pair(mkey: str) -> dict:
            bm, fm = b60.get(mkey) or {}, fed.get(mkey) or {}
            return {
                "acc_60": bm.get("accuracy"),
                "acc_edge": fm.get("accuracy"),
                "slg_200_400_60": bm.get("slg_200_400_accuracy"),
                "slg_200_400_edge": fm.get("slg_200_400_accuracy"),
                "slg_400_60": (bm.get("slg_by_resistance") or {}).get("400.0"),
                "slg_400_edge": (fm.get("slg_by_resistance") or {}).get("400.0"),
                "miss_60": bm.get("missing_sensor_mean"),
                "miss_edge": fm.get("missing_sensor_mean"),
            }

        hif_realistic = {
            "available": True,
            "simulation_only": True,
            "events": rp123.get("events"),
            "ml_full": _pair("ml_full"),
            "per_node_gbdt": _pair("per_node_gbdt"),
            "zone_tree_gnn": _pair("zone_tree_gnn"),
            "criteria": rsum.get("verdicts") or rsum.get("pre_committed_criteria") or rsum.get("criteria") or {},
        }

    built_from = [
        "results/metrics.json", "results/zones.csv", "results/restoration.csv",
        "results/switching_orders.md", "results/feeder_geometry.json",
        "results/error_analysis/error_analysis.json", "results/error_analysis/per_zone_ml.csv",
        "results/error_analysis/per_zone_fpi.csv", "results/error_analysis/confusion_ml.csv",
        "results/error_analysis/per_bus_ml.csv", "shf/config.py", "shf/model.py",
        "hif_sensor/results/metrics.json", "hif_sensor/results/real_vehif.json",
        "hif_sensor/results/phase15_vehif.json", "hif_sensor/results/c_firmware_verify.json",
    ]
    if (ROOT / "hif_sensor" / "circuit" / "ltspice_results.json").exists():
        built_from.append("hif_sensor/circuit/ltspice_results.json")
    for rel in hif_real_built:
        if rel not in built_from:
            built_from.append(rel)

    extensions = build_extensions(built_from)
    copy_feeder_maps(built_from)

    study = {
        "built_from": built_from,
        "config": cfg, "model": mdl, "metrics": metrics, "errors": errors,
        "per_zone_ml": per_zone_ml, "per_zone_fpi": per_zone_fpi, "confusion": confusion,
        "zones": zones, "devices": devices, "ties": ties,
        "restoration": rest, "orders": orders, "steps": steps,
        "geo": geo, "folds": folds_by_bus(per_bus),
        "per_bus": [{k: r[k] for k in ("bus", "zone", "faults", "ml_wrong")} for r in per_bus],
        "derived": derived, "references": references(), "tier1": tier1,
        "hif_fusion_realistic": hif_realistic,
        "extensions": extensions,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(study, ensure_ascii=False, separators=(",", ":"), default=float)
    OUT.write_text("/* Generated by scripts/build_study_site.py from results/ and shf/config.py. Do not edit. */\n"
                   f"window.STUDY = {body};\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.1f} KiB): "
          f"{len(zones)} zones, {len(rest)} restoration cases, {len(study['folds'])} buses in folds, "
          f"{len(extensions)} extensions")


if __name__ == "__main__":
    main()
