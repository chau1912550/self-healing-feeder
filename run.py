"""Run the whole study: dataset to data/generated/, model to models/, metrics,
tables and figures to results/.

    python run.py            # full pipeline (about 5-8 minutes)
    python run.py --quick    # 1 loading scenario per fault, faster check
"""
from __future__ import annotations

import argparse
import json
import pickle
import time

import numpy as np
import pandas as pd

from shf import baseline, config, dashboard, faults, feeder, model, report, restoration, topology


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="1 loading scenario per fault case")
    args = ap.parse_args()
    if args.quick:
        config.SCENARIOS_PER_CASE = 1
    out = config.RESULTS
    fig = config.FIGURES
    for d in (out, fig, config.GENERATED, config.MODELS):
        d.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    metrics: dict = {}

    print("1) Feeder and zones")
    feeder.load_feeder()
    zones = topology.find_zones()
    length = topology.zone_line_length_kft(zones)
    ztable = pd.DataFrame({
        "zone": zones.names,
        "fed_by": [config.SECTIONALIZERS[z] for z in zones.names],
        "parent_zone": [zones.parent[z] for z in zones.names],
        "kW": [zones.kw[z] for z in zones.names],
        "load_points": [zones.load_points[z] for z in zones.names],
        "line_kft": [round(length[z], 3) for z in zones.names],
        "buses": [" ".join(zones.members[z]) for z in zones.names],
    })
    ztable.to_csv(out / "zones.csv", index=False)
    report.feeder_map(zones, fig / "feeder_zones.png")
    base = restoration.check_power_flow(zones, set(zones.names))
    metrics["base_case"] = {"source_kW": -feeder.dss.Circuit.TotalPower()[0],
                            "vmin_pu": base["vmin"], "vmax_pu": base["vmax"],
                            "zones": len(zones.names), "total_kW": sum(zones.kw.values())}

    print("2) Fault simulations")
    df = faults.generate(zones, noise=True)
    df.to_csv(config.GENERATED / "dataset.csv.gz", index=False)
    metrics["dataset"] = {"rows": len(df), "converged_share": float(df["converged"].mean()),
                          "by_type": df["ftype"].value_counts().to_dict()}
    df = df[df["converged"]].reset_index(drop=True)

    print("3) Conventional fault passage indication (baseline)")
    pick = baseline.pickups(faults.peak_load_currents())
    fpi = baseline.predict(df, zones, pick)

    print("4) ML cross-validation (grouped by fault bus)")
    res_full = model.cross_validate(df, "full")
    res_mag = model.cross_validate(df, "magnitude")

    y = df["zone"].to_numpy()
    def summary(pred):
        return {"accuracy": float((pred == y).mean()),
                "by_fault_type": model.breakdown(df, pred, "ftype").round(4).to_dict(),
                "slg_by_resistance": model.breakdown(df[df.ftype == "SLG"],
                                                     pred[df.ftype == "SLG"], "r").round(4).to_dict()}
    metrics["fault_location"] = {
        "fpi_baseline": {**summary(fpi), "no_device_flagged": float((fpi == "none").mean()),
                         "pickups_A": {d: [round(a), round(b)] for d, (a, b) in pick.items()}},
        "ml_magnitude_only": {**summary(res_mag["pred"]),
                              "missing_sensor_accuracy": res_mag["missing_sensor_accuracy"]},
        "ml_full": {**summary(res_full["pred"]),
                    "missing_sensor_accuracy": res_full["missing_sensor_accuracy"]},
    }
    report.accuracy_vs_resistance(df, {
        "Conventional FPI (2x peak-load pickup)": fpi,
        "ML, magnitudes only": res_mag["pred"],
        "ML, magnitudes + pre/post-fault change": res_full["pred"],
    }, fig / "accuracy_vs_resistance.png")
    report.confusion(df, res_full["pred"], zones.names, fig / "confusion_ml.png",
                     "ML (full features): true vs predicted zone")
    report.confusion(df, fpi, zones.names, fig / "confusion_fpi.png",
                     "Conventional FPI: true vs predicted zone")

    # Patrol: after the head recloser locks out, a crew without fault location
    # patrols the whole feeder. With a correct zone it patrols only that zone.
    total_kft = sum(length.values())
    def patrol(pred):
        return float(np.where(pred == y, df["zone"].map(length), total_kft).mean())
    metrics["patrol_kft"] = {"no_location": total_kft, "fpi": patrol(fpi),
                             "ml_full": patrol(res_full["pred"])}

    print("5) Final model trained on all data")
    final_model, cols = model.fit_full(df, "full")
    with open(config.MODELS / "model.pkl", "wb") as f:
        pickle.dump({"model": final_model, "columns": cols}, f)

    print("6) Isolation and restoration for every fault zone")
    rows, orders = [], ["# Automated switching orders (simulated)\n"]
    w = {z: length[z] / total_kft for z in zones.names}   # fault rate ~ line length
    saved_weighted = 0.0
    for zf in zones.names:
        plan = restoration.plan_restoration(zones, zf)
        km = restoration.kw_minutes(zones, plan)
        final = plan.checks[-1]
        healthy_out = sum(zones.kw[z] for z in zones.downstream(zf))
        by_tie = sum(zones.kw[z] for z in plan.restored_by_tie)
        reduction = 1 - km["automated"] / km["conventional"]
        saved_weighted += w[zf] * reduction
        rows.append({
            "fault_zone": zf, "ties_closed": " ".join(plan.closed_ties) or "-",
            "restored_by_tie": " ".join(sorted(plan.restored_by_tie)) or "-",
            "unserved_healthy": " ".join(sorted(plan.unserved)) or "-",
            "kW_downstream_healthy": healthy_out, "kW_restored_by_tie": by_tie,
            "power_flow_checks": len(plan.checks) - 1,
            "power_flow_rejected": sum(not c["ok"] for c in plan.checks[:-1]),
            "final_vmin_pu": round(final["vmin"], 4), "final_vmax_pu": round(final["vmax"], 4),
            "final_overloads": len(final["overloads"]), "radial": final["radial"],
            "kWmin_conventional": round(km["conventional"]), "kWmin_automated": round(km["automated"]),
            "kWmin_reduction_pct": round(100 * reduction, 1),
        })
        orders.append(f"\n## Fault in zone {zf}\n")
        orders += [f"{i}. {s}\n" for i, s in enumerate(plan.steps, 1)]
    restoration.reset(zones)
    rest = pd.DataFrame(rows)
    rest.to_csv(out / "restoration.csv", index=False)
    (out / "switching_orders.md").write_text("".join(orders), encoding="utf-8")
    metrics["restoration"] = {
        "all_final_states_within_limits": bool((rest.final_overloads == 0).all()
                                               and (rest.final_vmin_pu >= config.V_MIN_PU - config.V_TOL).all()
                                               and (rest.final_vmax_pu <= config.V_MAX_PU + config.V_TOL).all()),
        "all_radial": bool(rest.radial.all()),
        "kW_restored_by_tie_total": float(rest.kW_restored_by_tie.sum()),
        "kW_downstream_healthy_total": float(rest.kW_downstream_healthy.sum()),
        "kWmin_reduction_pct_weighted_by_line_length": round(100 * saved_weighted, 1),
        "timing_assumption_min": {"automated": config.T_AUTOMATED_MIN,
                                  "manual": config.T_MANUAL_MIN, "repair": config.T_REPAIR_MIN},
    }
    metrics["runtime_s"] = round(time.time() - t0, 1)
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2, default=float), encoding="utf-8")
    print(json.dumps({k: metrics[k] for k in ("base_case", "patrol_kft", "restoration")},
                     indent=2, default=float))
    fl = metrics["fault_location"]
    print("accuracy: FPI %.3f | ML magnitude %.3f | ML full %.3f" % (
        fl["fpi_baseline"]["accuracy"], fl["ml_magnitude_only"]["accuracy"], fl["ml_full"]["accuracy"]))
    print(f"done in {metrics['runtime_s']} s")
    print("7) Report page")
    dashboard.build()   # error-analysis section shows as stale until scripts/error_analysis.py is re-run


if __name__ == "__main__":
    main()
