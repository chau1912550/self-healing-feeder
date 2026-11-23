"""Phase 3 of the transfer study: zero-shot, in-domain upper bound, and few-shot test on IEEE 34-bus.

    .venv\\Scripts\\python scripts\\transfer_eval34.py

Loads the frozen IEEE 123-bus models from models/transfer/ and frozen hyperparameters from
results/transfer/phase2_ieee123.json, evaluates them once on data/generated/transfer_ieee34.npz,
writes results/transfer/phase3_ieee34.json with a provenance record. Simulation only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run from anywhere

from shf import provenance, transfer, transfer_models as tm  # noqa: E402


def _strip_pred(res: dict) -> dict:
    return {k: v for k, v in res.items() if k != "pred"}


def _criterion_check(zero_acc: float, fpi_acc: float, upper_acc: float, few5_acc: float) -> dict:
    """Evaluate one model against the success criteria fixed in research/gnn-transfer/PLAN.md."""
    above_fpi = zero_acc > fpi_acc
    margin_over_fpi = zero_acc - fpi_acc
    gap_to_upper = upper_acc - zero_acc
    few5_gap = upper_acc - few5_acc
    if above_fpi and gap_to_upper <= 0.10:
        outcome = "main_success"
    elif above_fpi and few5_gap < 0.5 * max(gap_to_upper, 1e-9):
        outcome = "weaker_success_fewshot"
    elif above_fpi:
        outcome = "above_fpi_large_gap"
    else:
        outcome = "failure_not_above_fpi"
    return {
        "outcome": outcome,
        "zero_shot_acc": round(zero_acc, 4),
        "fpi_acc": round(fpi_acc, 4),
        "upper_bound_acc": round(upper_acc, 4),
        "few_shot_5pct_acc": round(few5_acc, 4),
        "margin_over_fpi": round(margin_over_fpi, 4),
        "gap_to_upper_bound": round(gap_to_upper, 4),
        "few_shot_5pct_gap_to_upper": round(few5_gap, 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--repeats", type=int, default=10, help="random bus splits per few-shot level")
    ap.add_argument("--jobs", type=int, default=tm.N_FOLDS, help="parallel workers for in-domain GNN CV")
    args = ap.parse_args()

    t0 = time.time()
    torch.set_num_threads(2)

    p2_path = transfer.SUMMARY_DIR / "phase2_ieee123.json"
    p2 = json.loads(p2_path.read_text(encoding="utf-8"))
    frozen = p2["frozen_for_phase3"]

    base_gbdt, base_gnn, meta = tm.load_frozen_models()
    ds = tm.load_dataset("ieee34")
    print(f"Loaded ieee34 (unseen feeder): {len(ds.y)} events, {len(ds.devices)} devices, "
          f"{len(np.unique(ds.bus))} unique buses, {len(ds.features)} features")

    print("\n1) FPI baseline on IEEE 34-bus")
    fpi_res = tm.cv_fpi(ds)
    print(f"   FPI accuracy = {fpi_res['accuracy']:.4f} "
          f"(no_flagged={fpi_res['no_device_flagged']:.4f}, "
          f"missing_mean={fpi_res['missing_sensor_mean']:.4f})")

    print("\n2) Zero-shot transfer (trained on IEEE 123-bus ONLY, never saw IEEE 34-bus)")
    zs_gbdt = tm.eval_zero_shot_gbdt(base_gbdt, ds, eval_missing=True)
    zs_gnn = tm.eval_zero_shot_gnn(base_gnn, ds, eval_missing=True)
    print(f"   Zero-shot Per-node GBDT = {zs_gbdt['accuracy']:.4f} "
          f"(missing_mean={zs_gbdt['missing_sensor_mean']:.4f}, min={zs_gbdt['missing_sensor_min']:.4f})")
    print(f"   Zero-shot Zone-tree GNN = {zs_gnn['accuracy']:.4f} "
          f"(missing_mean={zs_gnn['missing_sensor_mean']:.4f}, min={zs_gnn['missing_sensor_min']:.4f})")

    print("\n3) In-domain upper bound on IEEE 34-bus (5-fold GroupKFold by bus, frozen hyperparams)")
    gbdt_kw = {k: v for k, v in frozen["per_node_gbdt"].items()}
    gnn_kw = {k: v for k, v in frozen["gnn"].items()}
    ub_gbdt = tm.cv_gbdt(ds, eval_missing=True, seed=args.seed, **gbdt_kw)
    ub_gnn = tm.cv_gnn(ds, eval_missing=True, n_jobs=args.jobs, threads_per_worker=2,
                       seed=args.seed, **gnn_kw)
    print(f"   In-domain GBDT = {ub_gbdt['accuracy']:.4f} "
          f"(std={ub_gbdt['fold_std']:.4f}, missing_mean={ub_gbdt['missing_sensor_mean']:.4f})")
    print(f"   In-domain GNN  = {ub_gnn['accuracy']:.4f} "
          f"(std={ub_gnn['fold_std']:.4f}, missing_mean={ub_gnn['missing_sensor_mean']:.4f})")

    print(f"\n4) Few-shot fine-tuning on IEEE 34-bus ({args.repeats} random bus splits each)")
    fs5 = tm.few_shot_eval(ds, 0.05, base_gbdt=base_gbdt, base_gnn=base_gnn,
                           n_repeats=args.repeats, seed=args.seed,
                           sensor_dropout=meta["sensor_dropout"])
    print(f"   5% ({fs5['train_buses']} train / {fs5['test_buses']} test buses): "
          f"GBDT={fs5['models']['per_node_gbdt']['accuracy_mean']:.4f}±{fs5['models']['per_node_gbdt']['accuracy_std']:.4f}, "
          f"GNN={fs5['models']['gnn']['accuracy_mean']:.4f}±{fs5['models']['gnn']['accuracy_std']:.4f}")

    fs20 = tm.few_shot_eval(ds, 0.20, base_gbdt=base_gbdt, base_gnn=base_gnn,
                            n_repeats=args.repeats, seed=args.seed + 100,
                            sensor_dropout=meta["sensor_dropout"])
    print(f"   20% ({fs20['train_buses']} train / {fs20['test_buses']} test buses): "
          f"GBDT={fs20['models']['per_node_gbdt']['accuracy_mean']:.4f}±{fs20['models']['per_node_gbdt']['accuracy_std']:.4f}, "
          f"GNN={fs20['models']['gnn']['accuracy_mean']:.4f}±{fs20['models']['gnn']['accuracy_std']:.4f}")

    criteria = {
        "per_node_gbdt": _criterion_check(
            zs_gbdt["accuracy"], fpi_res["accuracy"], ub_gbdt["accuracy"],
            fs5["models"]["per_node_gbdt"]["accuracy_mean"],
        ),
        "gnn": _criterion_check(
            zs_gnn["accuracy"], fpi_res["accuracy"], ub_gnn["accuracy"],
            fs5["models"]["gnn"]["accuracy_mean"],
        ),
    }
    print("\nPre-committed criteria verdict:")
    print(json.dumps(criteria, indent=2))

    summary = {
        "phase": "phase3_ieee34_transfer",
        "simulation_only": True,
        "train_feeder": "ieee123",
        "test_feeder": "ieee34",
        "events": int(len(ds.y)),
        "buses": int(len(np.unique(ds.bus))),
        "devices": ds.devices,
        "features": ds.features,
        "frozen_hyperparameters_from_phase2": frozen,
        "seed": args.seed,
        "fpi": _strip_pred(fpi_res),
        "zero_shot": {
            "per_node_gbdt": _strip_pred(zs_gbdt),
            "gnn": _strip_pred(zs_gnn),
        },
        "in_domain_upper_bound": {
            "validation": {"method": "GroupKFold", "group_by": "bus", "n_splits": tm.N_FOLDS},
            "per_node_gbdt": _strip_pred(ub_gbdt),
            "gnn": _strip_pred(ub_gnn),
        },
        "few_shot": {
            "fine_tune_config": {
                "gbdt": {"method": "warm_start", "extra_iter": 50, "learning_rate": 0.05},
                "gnn": {"method": "adamw_finetune_frozen_norm", "epochs": 25, "lr": 5e-4, "batch_size": 64},
            },
            "pct_5": fs5,
            "pct_20": fs20,
        },
        "pre_committed_criteria": criteria,
        "runtime_s": round(time.time() - t0, 1),
    }

    transfer.SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    out = transfer.SUMMARY_DIR / "phase3_ieee34.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    provenance.record("transfer_phase3", [out])
    print(f"\nWrote {out} and provenance record in {summary['runtime_s']} s")


if __name__ == "__main__":
    main()
