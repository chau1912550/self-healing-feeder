"""Phase 2b of the transfer study: from predicted zone to bus ranking (research/gnn-transfer/PLAN.md
and research/ieee37-underground/PLAN.md).

    .venv\\Scripts\\python scripts\\transfer_bus_stage.py                    # ieee123 + ieee34 -> phase2b_bus_location.json
    .venv\\Scripts\\python scripts\\transfer_bus_stage.py --feeder ieee37    # ieee123 (train) -> ieee37 -> phase2b_bus_ieee37.json

Compares on IEEE 123-bus (GroupKFold by bus) and unseen target feeders (zero-shot from 123-bus + in-domain):
  0. Random bus inside the predicted zone (analytical expectation).
  1. Apparent impedance / 3-phase Takagi reactance method (pure OpenDSS 3x3 line impedance, zero training).
  2. Small Bus-Graph GNN on the feeder bus tree (measurements only at devices + OpenDSS bus structure).

Writes results/transfer/phase2b_bus_location.json (default) or results/transfer/phase2b_bus_ieee37.json
(--feeder ieee37) with a provenance record. Simulation only.
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

PHASE_FAULT_TYPES = ("3PH", "LL", "LLG")


def _phase_fault_top1_top3_scores(scores: np.ndarray, y_bus: np.ndarray, ftype: np.ndarray) -> tuple[float, float]:
    mask = np.isin(ftype, PHASE_FAULT_TYPES)
    order = np.argsort(-scores[mask], axis=1)
    hit1 = order[:, 0] == y_bus[mask]
    hit3 = (order[:, :3] == y_bus[mask, None]).any(axis=1)
    return round(float(hit1.mean()), 4), round(float(hit3.mean()), 4)


def _phase_fault_top1_top3_random(fbm: bl.FeederBusModel, y_zone: np.ndarray,
                                  pred_zone: np.ndarray, ftype: np.ndarray) -> tuple[float, float]:
    sizes = np.array([len(idxs) for idxs in fbm.zone_bus_indices], dtype=float)
    mask = np.isin(ftype, PHASE_FAULT_TYPES)
    z_ok = pred_zone[mask] == y_zone[mask]
    sz = sizes[np.maximum(pred_zone[mask], 0)]
    p1 = np.where(z_ok, 1.0 / sz, 0.0)
    p3 = np.where(z_ok, np.minimum(3.0, sz) / sz, 0.0)
    return round(float(p1.mean()), 4), round(float(p3.mean()), 4)


def _p2_criteria_check(takagi_top3: float, rand_top3: float,
                       takagi_phase_top3: float, rand_phase_top3: float) -> dict:
    """Evaluate Stage-2 Takagi reactance against research/ieee37-underground/PLAN.md Section 4.2."""
    margin_overall = takagi_top3 - rand_top3
    margin_phase = takagi_phase_top3 - rand_phase_top3
    p2_main = margin_overall >= 0.15
    p2_partial = (not p2_main) and (margin_phase >= 0.20)
    verdict = "P2-Main" if p2_main else ("P2-Partial" if p2_partial else "P2-Fail")
    return {
        "verdict": verdict,
        "p2_main_met": bool(p2_main),
        "p2_partial_phase_faults_met": bool(p2_partial),
        "takagi_top3": round(takagi_top3, 4),
        "random_top3": round(rand_top3, 4),
        "margin_over_random_top3": round(margin_overall, 4),
        "takagi_phase_faults_top3": round(takagi_phase_top3, 4),
        "random_phase_faults_top3": round(rand_phase_top3, 4),
        "phase_faults_margin_over_random_top3": round(margin_phase, 4),
    }


def _eval_ieee37_stage2(args: argparse.Namespace, base_gbdt: tm.PerNodeGBDT,
                        bus_gnn_123_full: bl.BusGraphGNN, bus_gnn_kw: dict,
                        bgnn_params: int, t0: float) -> None:
    print("\n2) IEEE 37-bus: building OpenDSS bus impedance model and sweeping phasors...")
    t3 = time.time()
    fbm37 = bl.build_feeder_bus_model("ieee37")
    sw37 = bl.sweep_with_phasors(fbm37, seed=args.seed)
    parent37 = np.array([fbm37.grid.devices.index(fbm37.grid.parent[d]) if fbm37.grid.parent[d] else -1
                         for d in fbm37.grid.devices], dtype=np.int64)
    pred_zone_37 = base_gbdt.predict(sw37["X"], parent37)
    s1_acc_37 = float((pred_zone_37 == sw37["y_zone"]).mean())
    phase_mask = np.isin(sw37["ftype"], PHASE_FAULT_TYPES)
    s1_phase_acc_37 = float((pred_zone_37[phase_mask] == sw37["y_zone"][phase_mask]).mean())
    print(f"   ieee37: {len(sw37['y_bus'])} events, {len(fbm37.buses)} buses ({time.time() - t3:.1f}s)")
    print(f"   Stage-1 zero-shot zone accuracy (ieee37) = {s1_acc_37:.4f} (phase={s1_phase_acc_37:.4f})")

    rand_37 = bl.random_zone_baseline(fbm37, sw37["y_zone"], pred_zone_37, sw37["ftype"], sw37["r"])
    r_p1, r_p3 = _phase_fault_top1_top3_random(fbm37, sw37["y_zone"], pred_zone_37, sw37["ftype"])
    rand_37["phase_faults_top1"], rand_37["phase_faults_top3"] = r_p1, r_p3

    rand_37_o = bl.random_zone_baseline(fbm37, sw37["y_zone"], sw37["y_zone"], sw37["ftype"], sw37["r"])
    ro_p1, ro_p3 = _phase_fault_top1_top3_random(fbm37, sw37["y_zone"], sw37["y_zone"], sw37["ftype"])
    rand_37_o["phase_faults_top1"], rand_37_o["phase_faults_top3"] = ro_p1, ro_p3

    xerr_37, rest_37, compat_37 = bl.takagi_bus_residuals(
        fbm37, sw37["V_post"], sw37["I_post"], sw37["dI"], pred_zone_37,
    )
    react_scores_37 = bl.reactance_scores(fbm37, xerr_37, rest_37, compat_37, pred_zone_37)
    react_37 = bl.evaluate_bus_scores(fbm37, react_scores_37, sw37["y_bus"], sw37["ftype"], sw37["r"])
    react_37["phase_faults_top1"], react_37["phase_faults_top3"] = _phase_fault_top1_top3_scores(
        react_scores_37, sw37["y_bus"], sw37["ftype"]
    )

    xerr_37_o, rest_37_o, compat_37_o = bl.takagi_bus_residuals(
        fbm37, sw37["V_post"], sw37["I_post"], sw37["dI"], sw37["y_zone"],
    )
    react_scores_37_o = bl.reactance_scores(fbm37, xerr_37_o, rest_37_o, compat_37_o, sw37["y_zone"])
    react_37_oracle = bl.evaluate_bus_scores(fbm37, react_scores_37_o, sw37["y_bus"], sw37["ftype"], sw37["r"])
    react_37_oracle["phase_faults_top1"], react_37_oracle["phase_faults_top3"] = _phase_fault_top1_top3_scores(
        react_scores_37_o, sw37["y_bus"], sw37["ftype"]
    )
    print(f"   ieee37 Random baseline   : top-1={rand_37['top1']:.4f}, top-3={rand_37['top3']:.4f} "
          f"(phase top-3={rand_37['phase_faults_top3']:.4f})")
    print(f"   ieee37 Reactance (pred)  : top-1={react_37['top1']:.4f}, top-3={react_37['top3']:.4f} "
          f"(phase top-3={react_37['phase_faults_top3']:.4f})")
    print(f"   ieee37 Reactance (oracle): top-1={react_37_oracle['top1']:.4f}, top-3={react_37_oracle['top3']:.4f} "
          f"(phase top-3={react_37_oracle['phase_faults_top3']:.4f})")

    # BusGraphGNN on IEEE 37-bus: zero-shot (trained on 123 only) + in-domain GroupKFold (on pred & oracle zones).
    Xbus_37 = bl.build_bus_graph_features(fbm37, sw37["X"], xerr_37, rest_37, compat_37, pred_zone_37)
    zmask_37 = fbm37.bus_zone_idx[None, :] == pred_zone_37[:, None]
    bgnn_zs_scores_37 = bl.predict_bus_gnn(bus_gnn_123_full, Xbus_37, fbm37.bus_parent, zmask_37)
    bgnn_zs_37 = bl.evaluate_bus_scores(fbm37, bgnn_zs_scores_37, sw37["y_bus"], sw37["ftype"], sw37["r"])
    bgnn_zs_37["phase_faults_top1"], bgnn_zs_37["phase_faults_top3"] = _phase_fault_top1_top3_scores(
        bgnn_zs_scores_37, sw37["y_bus"], sw37["ftype"]
    )

    bgnn_id_scores_37 = bl.cv_bus_gnn(fbm37, Xbus_37, sw37["y_bus"], sw37["bus"], pred_zone_37,
                                      seed=args.seed, n_jobs=args.jobs, threads_per_worker=2, **bus_gnn_kw)
    bgnn_id_37 = bl.evaluate_bus_scores(fbm37, bgnn_id_scores_37, sw37["y_bus"], sw37["ftype"], sw37["r"])
    bgnn_id_37["phase_faults_top1"], bgnn_id_37["phase_faults_top3"] = _phase_fault_top1_top3_scores(
        bgnn_id_scores_37, sw37["y_bus"], sw37["ftype"]
    )

    # Oracle-zone BusGraphGNN zero-shot diagnostic (isolates Stage-2 bus ranking from Stage-1 SLG zone errors).
    Xbus_37_o = bl.build_bus_graph_features(fbm37, sw37["X"], xerr_37_o, rest_37_o, compat_37_o, sw37["y_zone"])
    zmask_37_o = fbm37.bus_zone_idx[None, :] == sw37["y_zone"][:, None]
    bgnn_zs_scores_37_o = bl.predict_bus_gnn(bus_gnn_123_full, Xbus_37_o, fbm37.bus_parent, zmask_37_o)
    bgnn_zs_37_o = bl.evaluate_bus_scores(fbm37, bgnn_zs_scores_37_o, sw37["y_bus"], sw37["ftype"], sw37["r"])
    bgnn_zs_37_o["phase_faults_top1"], bgnn_zs_37_o["phase_faults_top3"] = _phase_fault_top1_top3_scores(
        bgnn_zs_scores_37_o, sw37["y_bus"], sw37["ftype"]
    )
    print(f"   ieee37 BusGraphGNN (zero): top-1={bgnn_zs_37['top1']:.4f}, top-3={bgnn_zs_37['top3']:.4f} "
          f"(phase top-3={bgnn_zs_37['phase_faults_top3']:.4f})")
    print(f"   ieee37 BusGraphGNN (in-d): top-1={bgnn_id_37['top1']:.4f}, top-3={bgnn_id_37['top3']:.4f} "
          f"(phase top-3={bgnn_id_37['phase_faults_top3']:.4f})")

    criteria = {
        "stage1_predicted_zone": _p2_criteria_check(
            react_37["top3"], rand_37["top3"],
            react_37["phase_faults_top3"], rand_37["phase_faults_top3"],
        ),
        "oracle_zone": _p2_criteria_check(
            react_37_oracle["top3"], rand_37_o["top3"],
            react_37_oracle["phase_faults_top3"], rand_37_o["phase_faults_top3"],
        ),
    }
    print("\nPre-committed Stage-2 criteria verdict (research/ieee37-underground/PLAN.md Section 4.2):")
    print(json.dumps(criteria, indent=2))

    summary = {
        "phase": "phase2b_bus_location_ieee37",
        "simulation_only": True,
        "plan": "research/ieee37-underground/PLAN.md",
        "train_feeder": "ieee123",
        "test_feeder": "ieee37",
        "seed": args.seed,
        "bus_gnn_config": {**bus_gnn_kw, "in_features": 28, "parameter_count": bgnn_params},
        "ieee37": {
            "events": int(len(sw37["y_bus"])),
            "buses": len(fbm37.buses),
            "zones": len(fbm37.grid.devices),
            "zone_bus_counts": {d: len(fbm37.grid.members[d]) for d in fbm37.grid.devices},
            "stage1_zone_model": "PerNodeGBDT (zero-shot from ieee123)",
            "stage1_zone_accuracy": s1_acc_37,
            "stage1_phase_faults_zone_accuracy": s1_phase_acc_37,
            "random_in_zone": rand_37,
            "random_in_zone_oracle": rand_37_o,
            "reactance_takagi": react_37,
            "reactance_takagi_oracle_zone": react_37_oracle,
            "bus_graph_gnn_zero_shot": bgnn_zs_37,
            "bus_graph_gnn_zero_shot_oracle_zone": bgnn_zs_37_o,
            "bus_graph_gnn_in_domain_cv": bgnn_id_37,
        },
        "pre_committed_criteria": criteria,
        "runtime_s": round(time.time() - t0, 1),
    }

    transfer.SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    out = transfer.SUMMARY_DIR / "phase2b_bus_ieee37.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    provenance.record("transfer_phase2b_ieee37", [out])
    print(f"\nWrote {out} and provenance record in {summary['runtime_s']} s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feeder", choices=["default", "ieee37"], default="default",
                    help="default runs ieee123+ieee34 -> phase2b_bus_location.json; "
                         "ieee37 fits BusGraphGNN on ieee123 only and evaluates ieee37 -> phase2b_bus_ieee37.json")
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

    xerr_123, rest_123, compat_123 = bl.takagi_bus_residuals(
        fbm123, sw123["V_post"], sw123["I_post"], sw123["dI"], pred_zone_123,
    )
    Xbus_123 = bl.build_bus_graph_features(fbm123, sw123["X"], xerr_123, rest_123, compat_123, pred_zone_123)
    bus_gnn_kw = {"hidden": 48, "n_layers": 2, "dropout": 0.1, "lr": 3e-3, "epochs": 25, "batch_size": 256}

    # Fit full BusGraphGNN on IEEE 123-bus ONLY for zero-shot evaluation on unseen target feeders.
    zmask_123 = fbm123.bus_zone_idx[None, :] == pred_zone_123[:, None]
    bus_gnn_123_full = bl.train_bus_gnn(Xbus_123, sw123["y_bus"], fbm123.bus_parent, zmask_123,
                                        seed=args.seed, **bus_gnn_kw)
    bgnn_params = sum(p.numel() for p in bus_gnn_123_full.parameters())

    if args.feeder == "ieee37":
        _eval_ieee37_stage2(args, base_gbdt, bus_gnn_123_full, bus_gnn_kw, bgnn_params, t0)
        return

    # Stage 2 on IEEE 123-bus (inside Stage-1 predicted zone, plus oracle zone).
    rand_123 = bl.random_zone_baseline(fbm123, sw123["y_zone"], pred_zone_123, sw123["ftype"], sw123["r"])
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
    bgnn_scores_123 = bl.cv_bus_gnn(fbm123, Xbus_123, sw123["y_bus"], sw123["bus"], pred_zone_123,
                                    seed=args.seed, n_jobs=args.jobs, threads_per_worker=2, **bus_gnn_kw)
    bgnn_123 = bl.evaluate_bus_scores(fbm123, bgnn_scores_123, sw123["y_bus"], sw123["ftype"], sw123["r"])
    print(f"   ieee123 BusGraphGNN (CV) : top-1={bgnn_123['top1']:.4f}, top-3={bgnn_123['top3']:.4f} "
          f"({time.time() - t2:.1f}s)")

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
