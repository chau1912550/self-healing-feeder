"""Phase 2b of the transfer study: from predicted zone to bus ranking (research/gnn-transfer/PLAN.md).

    .venv\\Scripts\\python scripts\\transfer_bus_stage.py

Compares on both IEEE 123-bus (GroupKFold by bus) and IEEE 34-bus (zero-shot from 123-bus + in-domain):
  0. Random bus inside the predicted zone (analytical expectation).
  1. Apparent impedance / 3-phase Takagi reactance method (pure OpenDSS 3x3 line impedance, zero training).
  2. Small Bus-Graph GNN on the feeder bus tree (measurements only at devices + OpenDSS bus structure).

Writes results/transfer/phase2b_bus_location.json with a provenance record. Simulation only.
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

from shf import bus_locator as bl, provenance, transfer, transfer_models as tm  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=tm.N_FOLDS)
    args = ap.parse_args()

    t0 = time.time()
    torch.set_num_threads(2)

    p2 = json.loads((transfer.SUMMARY_DIR / "phase2_ieee123.json").read_text(encoding="utf-8"))
    gbdt_kw = dict(p2["frozen_for_phase3"]["per_node_gbdt"])
    base_gbdt, _, _ = tm.load_frozen_models()

    # ------------------------------------------------------------------
    # 1. IEEE 123-bus: OpenDSS impedances + phasor sweep + Stage 1 OOF zones
    # ------------------------------------------------------------------
    print("1) IEEE 123-bus: building OpenDSS bus impedance model and sweeping phasors...")
    t1 = time.time()
    fbm123 = bl.build_feeder_bus_model("ieee123")
    sw123 = bl.sweep_with_phasors(fbm123, seed=args.seed)
    print(f"   ieee123: {len(sw123['y_bus'])} events, {len(fbm123.buses)} buses ({time.time() - t1:.1f}s)")

    # Stage 1 out-of-fold predicted zones on IEEE 123-bus (5-fold GroupKFold by bus).
    ds123 = tm.GraphDataset(
        feeder="ieee123", X=sw123["X"], y=sw123["y_zone"],
        parent=np.array([fbm123.grid.devices.index(fbm123.grid.parent[d]) if fbm123.grid.parent[d] else -1
                         for d in fbm123.grid.devices], dtype=np.int64),
        features=list(transfer.FEATURES), devices=list(fbm123.grid.devices),
        bus=sw123["bus"], ftype=sw123["ftype"], phases=np.full(len(sw123["y_bus"]), "", dtype=str),
        r=sw123["r"], scenario=np.zeros(len(sw123["y_bus"]), dtype=int),
        load_mult=np.ones(len(sw123["y_bus"]), dtype=float),
    )
    stage1_123 = tm.cv_gbdt(ds123, eval_missing=False, seed=args.seed, **gbdt_kw)
    pred_zone_123 = stage1_123["pred"]
    print(f"   Stage-1 OOF zone accuracy (ieee123) = {stage1_123['accuracy']:.4f}")

    # Stage 2 on IEEE 123-bus (inside Stage-1 predicted zone, plus oracle zone).
    rand_123 = bl.random_zone_baseline(fbm123, sw123["y_zone"], pred_zone_123, sw123["ftype"], sw123["r"])

    xerr_123, rest_123, compat_123 = bl.takagi_bus_residuals(
        fbm123, sw123["V_post"], sw123["I_post"], sw123["dI"], pred_zone_123,
    )
    react_scores_123 = bl.reactance_scores(fbm123, xerr_123, rest_123, compat_123, pred_zone_123)
    react_123 = bl.evaluate_bus_scores(fbm123, react_scores_123, sw123["y_bus"], sw123["ftype"], sw123["r"])

    # Oracle-zone reactance diagnostic on IEEE 123-bus.
    xerr_123_o, rest_123_o, compat_123_o = bl.takagi_bus_residuals(
        fbm123, sw123["V_post"], sw123["I_post"], sw123["dI"], sw123["y_zone"],
    )
    react_123_oracle = bl.evaluate_bus_scores(
        fbm123, bl.reactance_scores(fbm123, xerr_123_o, rest_123_o, compat_123_o, sw123["y_zone"]),
        sw123["y_bus"], sw123["ftype"], sw123["r"],
    )
    print(f"   ieee123 Random baseline  : top-1={rand_123['top1']:.4f}, top-3={rand_123['top3']:.4f}")
    print(f"   ieee123 Reactance (pred) : top-1={react_123['top1']:.4f}, top-3={react_123['top3']:.4f} "
          f"(oracle zone: top-1={react_123_oracle['top1']:.4f}, top-3={react_123_oracle['top3']:.4f})")

    # Small Bus-Graph GNN on IEEE 123-bus (5-fold GroupKFold by bus).
    print("   Training BusGraphGNN on ieee123 (5-fold GroupKFold by bus)...")
    t2 = time.time()
    Xbus_123 = bl.build_bus_graph_features(fbm123, sw123["X"], xerr_123, rest_123, compat_123, pred_zone_123)
    bus_gnn_kw = {"hidden": 48, "n_layers": 2, "dropout": 0.1, "lr": 3e-3, "epochs": 25, "batch_size": 256}
    bgnn_scores_123 = bl.cv_bus_gnn(fbm123, Xbus_123, sw123["y_bus"], sw123["bus"], pred_zone_123,
                                    seed=args.seed, n_jobs=args.jobs, threads_per_worker=2, **bus_gnn_kw)
    bgnn_123 = bl.evaluate_bus_scores(fbm123, bgnn_scores_123, sw123["y_bus"], sw123["ftype"], sw123["r"])
    print(f"   ieee123 BusGraphGNN (CV) : top-1={bgnn_123['top1']:.4f}, top-3={bgnn_123['top3']:.4f} "
          f"({time.time() - t2:.1f}s)")

    # Fit full BusGraphGNN on IEEE 123-bus ONLY for zero-shot evaluation on IEEE 34-bus.
    zmask_123 = fbm123.bus_zone_idx[None, :] == pred_zone_123[:, None]
    bus_gnn_123_full = bl.train_bus_gnn(Xbus_123, sw123["y_bus"], fbm123.bus_parent, zmask_123,
                                        seed=args.seed, **bus_gnn_kw)
    bgnn_params = sum(p.numel() for p in bus_gnn_123_full.parameters())

    # ------------------------------------------------------------------
    # 2. IEEE 34-bus: OpenDSS impedances + phasor sweep + Stage 1 zero-shot zones
    # ------------------------------------------------------------------
    print("\n2) IEEE 34-bus: building OpenDSS bus impedance model and sweeping phasors...")
    t3 = time.time()
    fbm34 = bl.build_feeder_bus_model("ieee34")
    sw34 = bl.sweep_with_phasors(fbm34, seed=args.seed)
    parent34 = np.array([fbm34.grid.devices.index(fbm34.grid.parent[d]) if fbm34.grid.parent[d] else -1
                         for d in fbm34.grid.devices], dtype=np.int64)
    pred_zone_34 = base_gbdt.predict(sw34["X"], parent34)
    s1_acc_34 = float((pred_zone_34 == sw34["y_zone"]).mean())
    print(f"   ieee34: {len(sw34['y_bus'])} events, {len(fbm34.buses)} buses ({time.time() - t3:.1f}s)")
    print(f"   Stage-1 zero-shot zone accuracy (ieee34) = {s1_acc_34:.4f}")

    rand_34 = bl.random_zone_baseline(fbm34, sw34["y_zone"], pred_zone_34, sw34["ftype"], sw34["r"])

    xerr_34, rest_34, compat_34 = bl.takagi_bus_residuals(
        fbm34, sw34["V_post"], sw34["I_post"], sw34["dI"], pred_zone_34,
    )
    react_scores_34 = bl.reactance_scores(fbm34, xerr_34, rest_34, compat_34, pred_zone_34)
    react_34 = bl.evaluate_bus_scores(fbm34, react_scores_34, sw34["y_bus"], sw34["ftype"], sw34["r"])

    xerr_34_o, rest_34_o, compat_34_o = bl.takagi_bus_residuals(
        fbm34, sw34["V_post"], sw34["I_post"], sw34["dI"], sw34["y_zone"],
    )
    react_34_oracle = bl.evaluate_bus_scores(
        fbm34, bl.reactance_scores(fbm34, xerr_34_o, rest_34_o, compat_34_o, sw34["y_zone"]),
        sw34["y_bus"], sw34["ftype"], sw34["r"],
    )
    print(f"   ieee34 Random baseline   : top-1={rand_34['top1']:.4f}, top-3={rand_34['top3']:.4f}")
    print(f"   ieee34 Reactance (pred)  : top-1={react_34['top1']:.4f}, top-3={react_34['top3']:.4f} "
          f"(oracle zone: top-1={react_34_oracle['top1']:.4f}, top-3={react_34_oracle['top3']:.4f})")

    # BusGraphGNN on IEEE 34-bus: zero-shot (trained on 123 only) + in-domain GroupKFold.
    Xbus_34 = bl.build_bus_graph_features(fbm34, sw34["X"], xerr_34, rest_34, compat_34, pred_zone_34)
    zmask_34 = fbm34.bus_zone_idx[None, :] == pred_zone_34[:, None]
    bgnn_zs_scores_34 = bl.predict_bus_gnn(bus_gnn_123_full, Xbus_34, fbm34.bus_parent, zmask_34)
    bgnn_zs_34 = bl.evaluate_bus_scores(fbm34, bgnn_zs_scores_34, sw34["y_bus"], sw34["ftype"], sw34["r"])

    bgnn_id_scores_34 = bl.cv_bus_gnn(fbm34, Xbus_34, sw34["y_bus"], sw34["bus"], pred_zone_34,
                                      seed=args.seed, n_jobs=args.jobs, threads_per_worker=2, **bus_gnn_kw)
    bgnn_id_34 = bl.evaluate_bus_scores(fbm34, bgnn_id_scores_34, sw34["y_bus"], sw34["ftype"], sw34["r"])
    print(f"   ieee34 BusGraphGNN (zero): top-1={bgnn_zs_34['top1']:.4f}, top-3={bgnn_zs_34['top3']:.4f}")
    print(f"   ieee34 BusGraphGNN (in-d): top-1={bgnn_id_34['top1']:.4f}, top-3={bgnn_id_34['top3']:.4f}")

    summary = {
        "phase": "phase2b_bus_location",
        "simulation_only": True,
        "seed": args.seed,
        "bus_gnn_config": {**bus_gnn_kw, "in_features": 28, "parameter_count": bgnn_params},
        "ieee123": {
            "events": int(len(sw123["y_bus"])),
            "buses": len(fbm123.buses),
            "zones": len(fbm123.grid.devices),
            "stage1_zone_model": "PerNodeGBDT (5-fold GroupKFold OOF on ieee123)",
            "stage1_zone_accuracy": float(stage1_123["accuracy"]),
            "random_in_zone": rand_123,
            "reactance_takagi": react_123,
            "reactance_takagi_oracle_zone": {
                "top1": react_123_oracle["top1"], "top3": react_123_oracle["top3"],
            },
            "bus_graph_gnn_cv": bgnn_123,
        },
        "ieee34": {
            "events": int(len(sw34["y_bus"])),
            "buses": len(fbm34.buses),
            "zones": len(fbm34.grid.devices),
            "stage1_zone_model": "PerNodeGBDT (zero-shot from ieee123)",
            "stage1_zone_accuracy": s1_acc_34,
            "random_in_zone": rand_34,
            "reactance_takagi": react_34,
            "reactance_takagi_oracle_zone": {
                "top1": react_34_oracle["top1"], "top3": react_34_oracle["top3"],
            },
            "bus_graph_gnn_zero_shot": bgnn_zs_34,
            "bus_graph_gnn_in_domain_cv": bgnn_id_34,
        },
        "runtime_s": round(time.time() - t0, 1),
    }

    transfer.SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    out = transfer.SUMMARY_DIR / "phase2b_bus_location.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    provenance.record("transfer_phase2b", [out])
    print(f"\nWrote {out} and provenance record in {summary['runtime_s']} s")


if __name__ == "__main__":
    main()
