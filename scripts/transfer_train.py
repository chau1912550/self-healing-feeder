"""Phase 2 of the transfer study: train and compare FPI, per-node GBDT, and GNN on IEEE 123-bus only.

    .venv\\Scripts\\python scripts\\transfer_train.py

Strictly uses data/generated/transfer_ieee123.npz (GroupKFold by fault bus, 5 folds). Never touches
IEEE 34-bus data. Saves frozen full-feeder models to models/transfer/ for Phase 3 and writes
results/transfer/phase2_ieee123.json with a provenance record. Simulation only.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import sklearn
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run from anywhere

from shf import config, provenance, transfer, transfer_models as tm  # noqa: E402

GBDT_GRID = [
    {"name": "gbdt_L31_lr0.10_i300", "max_iter": 300, "learning_rate": 0.10, "max_leaf_nodes": 31},
    {"name": "gbdt_L63_lr0.05_i300", "max_iter": 300, "learning_rate": 0.05, "max_leaf_nodes": 63},
    {"name": "gbdt_L31_lr0.05_i400", "max_iter": 400, "learning_rate": 0.05, "max_leaf_nodes": 31},
]

GNN_GRID = [
    {"name": "gnn_2layer_h64", "n_layers": 2, "hidden": 64, "dropout": 0.1, "lr": 2e-3,
     "weight_decay": 1e-4, "epochs": 40, "batch_size": 256},
    {"name": "gnn_3layer_h64", "n_layers": 3, "hidden": 64, "dropout": 0.1, "lr": 2e-3,
     "weight_decay": 1e-4, "epochs": 40, "batch_size": 256},
    {"name": "gnn_2layer_h96", "n_layers": 2, "hidden": 96, "dropout": 0.1, "lr": 2e-3,
     "weight_decay": 1e-4, "epochs": 40, "batch_size": 256},
    {"name": "gnn_3layer_h96", "n_layers": 3, "hidden": 96, "dropout": 0.1, "lr": 2e-3,
     "weight_decay": 1e-4, "epochs": 40, "batch_size": 256},
]


def _strip_pred(res: dict) -> dict:
    return {k: v for k, v in res.items() if k != "pred"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--sensor-dropout", type=float, default=tm.DROPOUT_RATE)
    ap.add_argument("--jobs", type=int, default=tm.N_FOLDS, help="parallel worker processes for GNN folds")
    args = ap.parse_args()

    t0 = time.time()
    torch.set_num_threads(2)
    ds = tm.load_dataset("ieee123")
    print(f"Loaded ieee123: {len(ds.y)} events, {len(ds.devices)} devices, "
          f"{len(np.unique(ds.bus))} unique buses, {len(ds.features)} features")

    print("\n1) FPI rule (relative pickups on graph features)")
    t1 = time.time()
    fpi_res = tm.cv_fpi(ds)
    print(f"   FPI accuracy = {fpi_res['accuracy']:.4f} "
          f"(no_flagged={fpi_res['no_device_flagged']:.4f}, "
          f"missing_mean={fpi_res['missing_sensor_mean']:.4f}, {time.time() - t1:.1f}s)")

    print("\n2) Per-node Gradient Boosting: hyperparameter selection on ieee123 (5-fold GroupKFold by bus)")
    gbdt_trials = []
    gbdt_full_res: dict[str, dict] = {}
    for cfg in GBDT_GRID:
        ts = time.time()
        kw = {k: v for k, v in cfg.items() if k != "name"}
        r = tm.cv_gbdt(ds, eval_missing=True, sensor_dropout=args.sensor_dropout, seed=args.seed, **kw)
        dt = round(time.time() - ts, 1)
        gbdt_full_res[cfg["name"]] = r
        trial = {"name": cfg["name"], "params": kw, "accuracy": r["accuracy"],
                 "missing_sensor_mean": r["missing_sensor_mean"],
                 "fold_accuracies": r["fold_accuracies"], "fold_std": r["fold_std"], "runtime_s": dt}
        gbdt_trials.append(trial)
        print(f"   {cfg['name']:24s} acc={r['accuracy']:.4f} (std={r['fold_std']:.4f}, "
              f"miss_mean={r['missing_sensor_mean']:.4f}) [{dt}s]")
    best_gbdt = max(gbdt_trials, key=lambda x: x["accuracy"])
    gbdt_res = gbdt_full_res[best_gbdt["name"]]
    print(f"   -> Selected GBDT: {best_gbdt['name']} "
          f"(acc={gbdt_res['accuracy']:.4f}, missing_mean={gbdt_res['missing_sensor_mean']:.4f}, "
          f"missing_min={gbdt_res['missing_sensor_min']:.4f})")

    print(f"\n3) Zone-tree GNN (plain PyTorch, CPU, {args.jobs} workers): "
          f"hyperparameter selection on ieee123 (5-fold GroupKFold by bus)")
    gnn_trials = []
    gnn_full_res: dict[str, dict] = {}
    for cfg in GNN_GRID:
        ts = time.time()
        kw = {k: v for k, v in cfg.items() if k != "name"}
        r = tm.cv_gnn(ds, eval_missing=True, n_jobs=args.jobs, threads_per_worker=2,
                      sensor_dropout=args.sensor_dropout, seed=args.seed, **kw)
        dt = round(time.time() - ts, 1)
        gnn_full_res[cfg["name"]] = r
        trial = {"name": cfg["name"], "params": kw, "accuracy": r["accuracy"],
                 "missing_sensor_mean": r["missing_sensor_mean"],
                 "fold_accuracies": r["fold_accuracies"], "fold_std": r["fold_std"], "runtime_s": dt}
        gnn_trials.append(trial)
        print(f"   {cfg['name']:24s} acc={r['accuracy']:.4f} (std={r['fold_std']:.4f}, "
              f"miss_mean={r['missing_sensor_mean']:.4f}) [{dt}s]")
    best_gnn = max(gnn_trials, key=lambda x: x["accuracy"])
    gnn_res = gnn_full_res[best_gnn["name"]]
    print(f"   -> Selected GNN: {best_gnn['name']} "
          f"(acc={gnn_res['accuracy']:.4f}, missing_mean={gnn_res['missing_sensor_mean']:.4f}, "
          f"missing_min={gnn_res['missing_sensor_min']:.4f})")

    print("\n4) Fit final models on all ieee123 events with frozen hyperparameters (for Phase 3)")
    model_dir = config.MODELS / "transfer"
    model_dir.mkdir(parents=True, exist_ok=True)
    final_gbdt = tm.PerNodeGBDT(sensor_dropout=args.sensor_dropout, seed=args.seed,
                                **best_gbdt["params"]).fit(ds.X, ds.y, ds.parent)
    with open(model_dir / "per_node_gbdt_ieee123.pkl", "wb") as f:
        pickle.dump({"model": final_gbdt, "params": best_gbdt["params"],
                     "sensor_dropout": args.sensor_dropout, "features": ds.features}, f)

    final_gnn = tm.train_gnn(ds.X, ds.y, ds.parent, sensor_dropout=args.sensor_dropout,
                             seed=args.seed, **best_gnn["params"])
    n_params = sum(p.numel() for p in final_gnn.parameters())
    torch.save({
        "state_dict": final_gnn.state_dict(),
        "arch": {"in_features": final_gnn.in_features, "hidden": final_gnn.hidden,
                 "n_layers": final_gnn.n_layers, "dropout": final_gnn.dropout},
        "params": best_gnn["params"],
        "sensor_dropout": args.sensor_dropout,
        "features": ds.features,
        "seed": args.seed,
    }, model_dir / "gnn_ieee123.pt")
    print(f"   Saved models to {model_dir} (GNN parameters: {n_params:,})")

    summary = {
        "phase": "phase2_ieee123",
        "simulation_only": True,
        "feeder": "ieee123",
        "events": int(len(ds.y)),
        "buses": int(len(np.unique(ds.bus))),
        "devices": ds.devices,
        "features": ds.features,
        "validation": {"method": "GroupKFold", "group_by": "bus", "n_splits": tm.N_FOLDS},
        "sensor_dropout_rate": args.sensor_dropout,
        "seed": args.seed,
        "fpi_rule": {
            "description": (
                "Graph-level relative pickup FPI: flags when max(|I_post|/base) > FPI_PHASE_FACTOR (2.0) "
                "or 3*|dI0|/base > FPI_GROUND_FACTOR (0.5); picks deepest flagged node."
            ),
            "phase_factor": config.FPI_PHASE_FACTOR,
            "ground_factor": config.FPI_GROUND_FACTOR,
        },
        "models": {
            "fpi": _strip_pred(fpi_res),
            "per_node_gbdt": {
                "selected": best_gbdt["name"],
                "params": best_gbdt["params"],
                **_strip_pred(gbdt_res),
            },
            "gnn": {
                "selected": best_gnn["name"],
                "params": best_gnn["params"],
                "parameter_count": n_params,
                **_strip_pred(gnn_res),
            },
        },
        "tuning_ieee123_only": {
            "per_node_gbdt": gbdt_trials,
            "gnn": gnn_trials,
        },
        "frozen_for_phase3": {
            "per_node_gbdt": {**best_gbdt["params"], "sensor_dropout": args.sensor_dropout},
            "gnn": {**best_gnn["params"], "sensor_dropout": args.sensor_dropout},
        },
        "versions": {
            "torch": torch.__version__,
            "sklearn": sklearn.__version__,
            "numpy": np.__version__,
        },
        "runtime_s": round(time.time() - t0, 1),
    }

    transfer.SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    out = transfer.SUMMARY_DIR / "phase2_ieee123.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    provenance.record("transfer_phase2", [out])
    print(f"\nWrote {out} and provenance record in {summary['runtime_s']} s")


if __name__ == "__main__":
    main()
