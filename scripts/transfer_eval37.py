"""Phase 3 transfer evaluation on the third unseen feeder: urban underground IEEE 37-bus (4.8 kV, 3-wire delta).

    .venv\\Scripts\\python scripts\\transfer_eval37.py

Loads the frozen IEEE 123-bus models from models/transfer/ and frozen hyperparameters from
results/transfer/phase2_ieee123.json (zero retraining on 123-bus, zero hyperparameter tuning on 37-bus),
evaluates them on data/generated/transfer_ieee37.npz, and writes results/transfer/phase3_ieee37.json
with a provenance record. Pre-committed criteria follow research/ieee37-underground/PLAN.md Section 4.1.
Simulation only.
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

PHASE_FAULT_TYPES = ("3PH", "LL", "LLG")


def _phase_fault_acc(ds: tm.GraphDataset, pred: np.ndarray) -> float:
    mask = np.isin(ds.ftype, PHASE_FAULT_TYPES)
    return float((pred[mask] == ds.y[mask]).mean())


def _with_phase_acc(res: dict, ds: tm.GraphDataset) -> dict:
    out = {k: v for k, v in res.items() if k != "pred"}
    out["phase_faults_accuracy"] = round(_phase_fault_acc(ds, res["pred"]), 4)
    return out


def _criterion_check(
    *,
    zs_acc: float,
    fpi_acc: float,
    ub_acc: float,
    zs_phase: float,
    fpi_phase: float,
    ub_phase: float,
    zs_miss: float,
    fs5_acc: float,
    fs5_miss: float,
    fs20_acc: float,
    fs20_miss: float,
) -> dict:
    """Evaluate one model against pre-committed criteria in research/ieee37-underground/PLAN.md Section 4.1."""
    margin_overall = zs_acc - fpi_acc
    gap_overall = ub_acc - zs_acc
    margin_phase = zs_phase - fpi_phase
    gap_phase = ub_phase - zs_phase

    p1_main = (margin_overall >= 0.15) and (gap_overall <= 0.10)
    p1_partial = (not p1_main) and (margin_phase >= 0.15) and (gap_phase <= 0.10)

    def _fewshot_check(fs_acc: float, fs_miss: float) -> tuple[float | None, float, bool]:
        miss_delta = fs_miss - zs_miss
        if gap_overall > 1e-9:
            closed = (fs_acc - zs_acc) / gap_overall
            effective = (closed >= 0.50) and (miss_delta >= -0.05)
            return round(float(closed), 4), round(float(miss_delta), 4), bool(effective)
        # No positive gap to upper bound; check no regression.
        effective = (fs_acc >= zs_acc - 1e-9) and (miss_delta >= -0.05)
        return None, round(float(miss_delta), 4), bool(effective)

    fs5_closed, fs5_md, fs5_eff = _fewshot_check(fs5_acc, fs5_miss)
    fs20_closed, fs20_md, fs20_eff = _fewshot_check(fs20_acc, fs20_miss)

    zero_shot_failed_both = (margin_overall < 0.15) and (margin_phase < 0.15)
    p1_fail = zero_shot_failed_both or (gap_overall > 1e-9 and not fs20_eff)

    if p1_main:
        zero_shot_verdict = "P1-Main"
    elif p1_partial:
        zero_shot_verdict = "P1-Partial"
    else:
        zero_shot_verdict = "P1-Fail"

    return {
        "zero_shot_verdict": zero_shot_verdict,
        "p1_main_met": bool(p1_main),
        "p1_partial_phase_faults_met": bool(p1_partial),
        "p1_fewshot_5pct_effective": bool(fs5_eff),
        "p1_fewshot_20pct_effective": bool(fs20_eff),
        "p1_fail_triggered": bool(p1_fail),
        "zero_shot_acc": round(zs_acc, 4),
        "fpi_acc": round(fpi_acc, 4),
        "upper_bound_acc": round(ub_acc, 4),
        "margin_over_fpi": round(margin_overall, 4),
        "gap_to_upper_bound": round(gap_overall, 4),
        "zero_shot_phase_faults_acc": round(zs_phase, 4),
        "fpi_phase_faults_acc": round(fpi_phase, 4),
        "upper_bound_phase_faults_acc": round(ub_phase, 4),
        "phase_faults_margin_over_fpi": round(margin_phase, 4),
        "phase_faults_gap_to_upper_bound": round(gap_phase, 4),
        "few_shot_5pct_acc": round(fs5_acc, 4),
        "few_shot_5pct_gap_closed": fs5_closed,
        "few_shot_5pct_missing_sensor_delta": fs5_md,
        "few_shot_20pct_acc": round(fs20_acc, 4),
        "few_shot_20pct_gap_closed": fs20_closed,
        "few_shot_20pct_missing_sensor_delta": fs20_md,
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
    ds = tm.load_dataset("ieee37")
    print(f"Loaded ieee37 (unseen underground delta feeder): {len(ds.y)} events, {len(ds.devices)} devices, "
          f"{len(np.unique(ds.bus))} unique buses, {len(ds.features)} features")

    print("\n1) FPI baseline on IEEE 37-bus")
    fpi_res = tm.cv_fpi(ds)
    fpi_out = _with_phase_acc(fpi_res, ds)
    print(f"   FPI accuracy = {fpi_out['accuracy']:.4f} (phase={fpi_out['phase_faults_accuracy']:.4f}, "
          f"SLG={fpi_out['by_fault_type'].get('SLG')}, "
          f"no_flagged={fpi_out['no_device_flagged']:.4f}, "
          f"missing_mean={fpi_out['missing_sensor_mean']:.4f})")

    print("\n2) Zero-shot transfer (trained on IEEE 123-bus ONLY, never saw IEEE 37-bus)")
    zs_gbdt = tm.eval_zero_shot_gbdt(base_gbdt, ds, eval_missing=True)
    zs_gnn = tm.eval_zero_shot_gnn(base_gnn, ds, eval_missing=True)
    zs_gbdt_out = _with_phase_acc(zs_gbdt, ds)
    zs_gnn_out = _with_phase_acc(zs_gnn, ds)
    print(f"   Zero-shot Per-node GBDT = {zs_gbdt_out['accuracy']:.4f} "
          f"(phase={zs_gbdt_out['phase_faults_accuracy']:.4f}, SLG={zs_gbdt_out['by_fault_type'].get('SLG')}, "
          f"missing_mean={zs_gbdt_out['missing_sensor_mean']:.4f})")
    print(f"   Zero-shot Zone-tree GNN = {zs_gnn_out['accuracy']:.4f} "
          f"(phase={zs_gnn_out['phase_faults_accuracy']:.4f}, SLG={zs_gnn_out['by_fault_type'].get('SLG')}, "
          f"missing_mean={zs_gnn_out['missing_sensor_mean']:.4f})")

    print("\n3) In-domain upper bound on IEEE 37-bus (5-fold GroupKFold by bus, frozen hyperparams)")
    gbdt_kw = dict(frozen["per_node_gbdt"])
    gnn_kw = dict(frozen["gnn"])
    ub_gbdt = tm.cv_gbdt(ds, eval_missing=True, seed=args.seed, **gbdt_kw)
    ub_gnn = tm.cv_gnn(ds, eval_missing=True, n_jobs=args.jobs, threads_per_worker=2,
                       seed=args.seed, **gnn_kw)
    ub_gbdt_out = _with_phase_acc(ub_gbdt, ds)
    ub_gnn_out = _with_phase_acc(ub_gnn, ds)
    print(f"   In-domain GBDT = {ub_gbdt_out['accuracy']:.4f} (phase={ub_gbdt_out['phase_faults_accuracy']:.4f}, "
          f"SLG={ub_gbdt_out['by_fault_type'].get('SLG')}, std={ub_gbdt_out['fold_std']:.4f}, "
          f"missing_mean={ub_gbdt_out['missing_sensor_mean']:.4f})")
    print(f"   In-domain GNN  = {ub_gnn_out['accuracy']:.4f} (phase={ub_gnn_out['phase_faults_accuracy']:.4f}, "
          f"SLG={ub_gnn_out['by_fault_type'].get('SLG')}, std={ub_gnn_out['fold_std']:.4f}, "
          f"missing_mean={ub_gnn_out['missing_sensor_mean']:.4f})")

    print(f"\n4) Few-shot fine-tuning on IEEE 37-bus ({args.repeats} random bus splits each)")
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
            zs_acc=zs_gbdt_out["accuracy"],
            fpi_acc=fpi_out["accuracy"],
            ub_acc=ub_gbdt_out["accuracy"],
            zs_phase=zs_gbdt_out["phase_faults_accuracy"],
            fpi_phase=fpi_out["phase_faults_accuracy"],
            ub_phase=ub_gbdt_out["phase_faults_accuracy"],
            zs_miss=zs_gbdt_out["missing_sensor_mean"],
            fs5_acc=fs5["models"]["per_node_gbdt"]["accuracy_mean"],
            fs5_miss=fs5["models"]["per_node_gbdt"]["missing_sensor_mean"],
            fs20_acc=fs20["models"]["per_node_gbdt"]["accuracy_mean"],
            fs20_miss=fs20["models"]["per_node_gbdt"]["missing_sensor_mean"],
        ),
        "gnn": _criterion_check(
            zs_acc=zs_gnn_out["accuracy"],
            fpi_acc=fpi_out["accuracy"],
            ub_acc=ub_gnn_out["accuracy"],
            zs_phase=zs_gnn_out["phase_faults_accuracy"],
            fpi_phase=fpi_out["phase_faults_accuracy"],
            ub_phase=ub_gnn_out["phase_faults_accuracy"],
            zs_miss=zs_gnn_out["missing_sensor_mean"],
            fs5_acc=fs5["models"]["gnn"]["accuracy_mean"],
            fs5_miss=fs5["models"]["gnn"]["missing_sensor_mean"],
            fs20_acc=fs20["models"]["gnn"]["accuracy_mean"],
            fs20_miss=fs20["models"]["gnn"]["missing_sensor_mean"],
        ),
    }
    print("\nPre-committed criteria verdict (research/ieee37-underground/PLAN.md Section 4.1):")
    print(json.dumps(criteria, indent=2))

    summary = {
        "phase": "phase3_ieee37_transfer",
        "simulation_only": True,
        "plan": "research/ieee37-underground/PLAN.md",
        "train_feeder": "ieee123",
        "test_feeder": "ieee37",
        "events": int(len(ds.y)),
        "buses": int(len(np.unique(ds.bus))),
        "devices": ds.devices,
        "features": ds.features,
        "frozen_hyperparameters_from_phase2": frozen,
        "seed": args.seed,
        "fpi": fpi_out,
        "zero_shot": {
            "per_node_gbdt": zs_gbdt_out,
            "gnn": zs_gnn_out,
        },
        "in_domain_upper_bound": {
            "validation": {"method": "GroupKFold", "group_by": "bus", "n_splits": tm.N_FOLDS},
            "per_node_gbdt": ub_gbdt_out,
            "gnn": ub_gnn_out,
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
    out = transfer.SUMMARY_DIR / "phase3_ieee37.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    provenance.record("transfer_phase3_ieee37", [out])
    print(f"\nWrote {out} and provenance record in {summary['runtime_s']} s")


if __name__ == "__main__":
    main()
