"""End-to-end Active-Grid GNN + Split Conformal Prediction experiment (research/active-grid-gnn/PLAN.md
and research/ieee37-underground/PLAN.md).

Designed to run on a Kaggle GPU VM (free cloud compute, offline OpenDSS wheels), or locally with --quick.
    python -u scripts/active_grid_run.py                          # IEEE 123-bus -> IEEE 34-bus -> results/active_grid/
    python -u scripts/active_grid_run.py --test-feeder ieee37     # IEEE 123-bus -> IEEE 37-bus -> results/active_grid_ieee37/

Outputs (all recorded via shf.provenance.record(...)):
  results/active_grid/ (or results/active_grid_ieee37/):
    dataset_summary.json
    phase_active_ieee123.json
    phase_active_<test_feeder>.json
    conformal_safety.json

Simulation only. Nothing here is field data.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import sklearn
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shf import active_grid as ag, active_models as am, provenance  # noqa: E402

GBDT_GRID = [
    {"name": "gbdt_L31_lr0.10_i300", "max_iter": 300, "learning_rate": 0.10, "max_leaf_nodes": 31},
    {"name": "gbdt_L63_lr0.05_i300", "max_iter": 300, "learning_rate": 0.05, "max_leaf_nodes": 63},
]

GAT_GRID = [
    {"name": "gatv2_2L_h64", "n_layers": 2, "hidden": 64, "n_heads": 4, "dropout": 0.1,
     "lr": 2e-3, "weight_decay": 1e-4, "epochs": 45, "batch_size": 256},
    {"name": "gatv2_3L_h64", "n_layers": 3, "hidden": 64, "n_heads": 4, "dropout": 0.1,
     "lr": 2e-3, "weight_decay": 1e-4, "epochs": 45, "batch_size": 256},
    {"name": "gatv2_3L_h96", "n_layers": 3, "hidden": 96, "n_heads": 4, "dropout": 0.1,
     "lr": 2e-3, "weight_decay": 1e-4, "epochs": 45, "batch_size": 256},
]


def _cv_fpi(ds: am.ActiveGraphDataset) -> dict:
    folds = [te for _, te in am.make_bus_group_folds(ds)]
    pred = am.active_fpi_predict(ds.X, ds.adj, ds.topo_id)
    miss = {d: int((am.active_fpi_predict(am.blank_active_sensor(ds.X, i), ds.adj, ds.topo_id) == ds.y).sum())
            for i, d in enumerate(ds.devices)}
    return am.evaluate_active(ds, pred, folds, miss)


def _cv_gbdt(ds: am.ActiveGraphDataset, *, seed: int = 0, sensor_dropout: float = am.DROPOUT_RATE,
             eval_missing: bool = True, **kw) -> tuple[dict, np.ndarray]:
    splits = am.make_bus_group_folds(ds)
    oof_probs = np.zeros((len(ds.y), ds.n_nodes + 1), dtype=np.float64)
    folds = [te for _, te in splits]
    miss = {d: 0 for d in ds.devices} if eval_missing else None
    for fi, (tr, te) in enumerate(splits):
        clf = am.ActivePerNodeGBDT(sensor_dropout=sensor_dropout, seed=seed + fi, **kw)
        clf.fit(ds.X[tr], ds.y[tr], ds.adj, ds.topo_id[tr])
        oof_probs[te] = clf.predict_proba(ds.X[te], ds.adj, ds.topo_id[te])
        if eval_missing and miss is not None:
            for i, d in enumerate(ds.devices):
                pm = clf.predict(am.blank_active_sensor(ds.X[te], i), ds.adj, ds.topo_id[te])
                miss[d] += int((pm == ds.y[te]).sum())
    res = am.evaluate_active(ds, oof_probs.argmax(axis=1), folds, miss)
    return res, oof_probs


def _cv_gat(ds: am.ActiveGraphDataset, *, seed: int = 0, sensor_dropout: float = am.DROPOUT_RATE,
            eval_missing: bool = True, device: torch.device | None = None, **kw) -> tuple[dict, np.ndarray]:
    splits = am.make_bus_group_folds(ds)
    oof_probs = np.zeros((len(ds.y), ds.n_nodes + 1), dtype=np.float64)
    folds = [te for _, te in splits]
    miss = {d: 0 for d in ds.devices} if eval_missing else None
    for fi, (tr, te) in enumerate(splits):
        net = am.train_active_gat(ds.X[tr], ds.y[tr], ds.adj, ds.is_tie, ds.topo_id[tr],
                                  sensor_dropout=sensor_dropout, seed=seed + fi, device=device, **kw)
        oof_probs[te] = am.predict_proba_gat(net, ds.X[te], ds.adj, ds.is_tie, ds.topo_id[te], device=device)
        if eval_missing and miss is not None:
            for i, d in enumerate(ds.devices):
                pm = am.predict_proba_gat(net, am.blank_active_sensor(ds.X[te], i),
                                          ds.adj, ds.is_tie, ds.topo_id[te], device=device).argmax(axis=1)
                miss[d] += int((pm == ds.y[te]).sum())
    res = am.evaluate_active(ds, oof_probs.argmax(axis=1), folds, miss)
    return res, oof_probs


def _few_shot_active(ds: am.ActiveGraphDataset, frac: float, *, base_gbdt: am.ActivePerNodeGBDT,
                     base_gat: am.ActiveGridGATv2, n_repeats: int = 5, seed: int = 0,
                     device: torch.device | None = None) -> dict:
    fault_buses = np.array(sorted(np.unique(ds.bus[ds.y < ds.nofault_class])))
    nf_idx_all = np.flatnonzero(ds.y == ds.nofault_class)
    n_tr_b = max(1, int(round(frac * len(fault_buses))))
    n_tr_nf = max(10, int(round(frac * len(nf_idx_all))))

    out_models = {}
    for mname in ("per_node_gbdt", "active_gatv2"):
        rng = np.random.default_rng(seed)
        split_accs, split_fprs, miss_means = [], [], []
        for rep in range(n_repeats):
            chosen_b = set(rng.choice(fault_buses, size=n_tr_b, replace=False).tolist())
            chosen_nf = set(rng.choice(nf_idx_all, size=n_tr_nf, replace=False).tolist())
            tr_mask = np.array([(b in chosen_b) or (i in chosen_nf) for i, b in enumerate(ds.bus)])
            te_mask = ~tr_mask
            assert set(ds.bus[tr_mask]).isdisjoint(set(ds.bus[te_mask]))

            if mname == "per_node_gbdt":
                m = am.finetune_active_gbdt(base_gbdt, ds.X[tr_mask], ds.y[tr_mask],
                                            ds.adj, ds.topo_id[tr_mask], seed=seed + rep)
                pred = m.predict(ds.X[te_mask], ds.adj, ds.topo_id[te_mask])
                mh = [float((m.predict(am.blank_active_sensor(ds.X[te_mask], i), ds.adj,
                                       ds.topo_id[te_mask]) == ds.y[te_mask]).mean())
                      for i in range(ds.n_nodes)]
            else:
                m = am.finetune_active_gat(base_gat, ds.X[tr_mask], ds.y[tr_mask], ds.adj, ds.is_tie,
                                           ds.topo_id[tr_mask], seed=seed + rep, device=device)
                pred = am.predict_proba_gat(m, ds.X[te_mask], ds.adj, ds.is_tie,
                                            ds.topo_id[te_mask], device=device).argmax(axis=1)
                mh = [float((am.predict_proba_gat(m, am.blank_active_sensor(ds.X[te_mask], i),
                                                  ds.adj, ds.is_tie, ds.topo_id[te_mask],
                                                  device=device).argmax(axis=1) == ds.y[te_mask]).mean())
                      for i in range(ds.n_nodes)]

            y_te = ds.y[te_mask]
            split_accs.append(float((pred == y_te).mean()))
            is_nf_te = y_te == ds.nofault_class
            split_fprs.append(float((pred[is_nf_te] != ds.nofault_class).mean()) if is_nf_te.any() else 0.0)
            miss_means.append(float(np.mean(mh)))

        out_models[mname] = {
            "overall_accuracy_mean": round(float(np.mean(split_accs)), 4),
            "overall_accuracy_std": round(float(np.std(split_accs)), 4),
            "split_accuracies": [round(a, 4) for a in split_accs],
            "nofault_fpr_mean": round(float(np.mean(split_fprs)), 4),
            "missing_sensor_mean": round(float(np.mean(miss_means)), 4),
        }

    return {
        "fraction": frac,
        "train_fault_buses": n_tr_b,
        "test_fault_buses": int(len(fault_buses) - n_tr_b),
        "train_nofault_events": n_tr_nf,
        "n_repeats": n_repeats,
        "models": out_models,
    }


def _conformal_in_domain_cv(ds: am.ActiveGraphDataset, oof_probs: np.ndarray,
                            alphas: tuple[float, ...] = (0.10, 0.05)) -> dict:
    """Bus-disjoint cross-conformal evaluation on IEEE 123-bus OOF probabilities."""
    splits = am.make_bus_group_folds(ds)
    out = {}
    for alpha in alphas:
        q_hats = []
        all_sets, all_y, all_probs = [], [], []
        for tr, te in splits:
            # Calibrate q_hat strictly on the other 4 folds (disjoint fault buses).
            q_hat = am.conformal_calibrate(oof_probs[tr], ds.y[tr], alpha=alpha)
            q_hats.append(q_hat)
            all_sets.append(am.conformal_predict_sets(oof_probs[te], q_hat))
            all_y.append(ds.y[te])
            all_probs.append(oof_probs[te])
        sets = np.concatenate(all_sets, axis=0)
        y_all = np.concatenate(all_y, axis=0)
        p_all = np.concatenate(all_probs, axis=0)
        sizes = sets.sum(axis=1)
        covered = sets[np.arange(len(y_all)), y_all]
        auto = sizes == 1
        defer = sizes >= 2
        pred = p_all.argmax(axis=1)
        is_nf = y_all == ds.nofault_class
        out[f"target_{int(round(100 * (1 - alpha)))}"] = {
            "alpha": alpha,
            "q_hat_mean": round(float(np.mean(q_hats)), 5),
            "empirical_coverage": round(float(covered.mean()), 4),
            "avg_set_size": round(float(sizes.mean()), 3),
            "autonomous_share": round(float(auto.mean()), 4),
            "autonomous_accuracy": round(float((pred[auto] == y_all[auto]).mean()), 4) if auto.any() else None,
            "raw_argmax_accuracy": round(float((pred == y_all).mean()), 4),
            "defer_share": round(float(defer.mean()), 4),
            "defer_coverage": round(float(covered[defer].mean()), 4) if defer.any() else None,
            "autonomous_nofault_fpr": round(float((pred[auto & is_nf] != ds.nofault_class).mean()), 4)
            if (auto & is_nf).any() else 0.0,
            "raw_nofault_fpr": round(float((pred[is_nf] != ds.nofault_class).mean()), 4),
        }
    return out


def _conformal_34_recal(ds34: am.ActiveGraphDataset, probs34: np.ndarray,
                        probs123_oof: np.ndarray, y123: np.ndarray,
                        alphas: tuple[float, ...] = (0.10, 0.05),
                        n_repeats: int = 10, seed: int = 0) -> dict:
    """Evaluate conformal sets on IEEE 34-bus: zero-shot q_hat from 123-bus vs 5%-bus recalibration."""
    fault_buses = np.array(sorted(np.unique(ds34.bus[ds34.y < ds34.nofault_class])))
    nf_idx = np.flatnonzero(ds34.y == ds34.nofault_class)
    n_cal_b = max(1, int(round(0.05 * len(fault_buses))))
    n_cal_nf = max(10, int(round(0.05 * len(nf_idx))))

    zs_out, recal_out = {}, {}
    for alpha in alphas:
        key = f"target_{int(round(100 * (1 - alpha)))}"
        q_zs = am.conformal_calibrate(probs123_oof, y123, alpha=alpha)
        zs_out[key] = am.evaluate_conformal(probs34, ds34.y, q_zs, ds34.nofault_class)

        rng = np.random.default_rng(seed)
        rep_metrics = []
        for _ in range(n_repeats):
            cb = set(rng.choice(fault_buses, size=n_cal_b, replace=False).tolist())
            cnf = set(rng.choice(nf_idx, size=n_cal_nf, replace=False).tolist())
            cal_m = np.array([(b in cb) or (i in cnf) for i, b in enumerate(ds34.bus)])
            te_m = ~cal_m
            q_rc = am.conformal_calibrate(probs34[cal_m], ds34.y[cal_m], alpha=alpha)
            rep_metrics.append(am.evaluate_conformal(probs34[te_m], ds34.y[te_m], q_rc, ds34.nofault_class))
        auto_accs = [m["autonomous_accuracy"] for m in rep_metrics if m["autonomous_accuracy"] is not None]
        recal_out[key] = {
            "alpha": alpha,
            "cal_fault_buses": n_cal_b,
            "cal_nofault_events": n_cal_nf,
            "n_repeats": n_repeats,
            "q_hat_mean": round(float(np.mean([m["q_hat"] for m in rep_metrics])), 5),
            "empirical_coverage_mean": round(float(np.mean([m["empirical_coverage"] for m in rep_metrics])), 4),
            "empirical_coverage_std": round(float(np.std([m["empirical_coverage"] for m in rep_metrics])), 4),
            "avg_set_size_mean": round(float(np.mean([m["avg_set_size"] for m in rep_metrics])), 3),
            "autonomous_share_mean": round(float(np.mean([m["autonomous_share"] for m in rep_metrics])), 4),
            "autonomous_accuracy_mean": round(float(np.mean(auto_accs)), 4) if auto_accs else None,
            "raw_argmax_accuracy_mean": round(float(np.mean([m["raw_argmax_accuracy"] for m in rep_metrics])), 4),
            "autonomous_nofault_fpr_mean": round(float(np.mean([m["autonomous_nofault_fpr"] for m in rep_metrics])), 4),
        }
    return {"zero_shot_q_from_123": zs_out, "recal_5pct_buses_no_retrain": recal_out}


def _phase_fault_acc(ds: am.ActiveGraphDataset, pred: np.ndarray) -> float:
    mask = np.isin(ds.ftype, ("3PH", "LL", "LLG"))
    return round(float((pred[mask] == ds.y[mask]).mean()), 4) if mask.any() else 0.0


def _eval_ieee37_criteria(
    *,
    fpi_res: dict,
    zs_gbdt: dict,
    zs_gat: dict,
    ub_gbdt: dict,
    ub_gat: dict,
    fs20: dict,
) -> dict:
    """Evaluate active IEEE 37-bus results against research/ieee37-underground/PLAN.md Section 4.3."""
    a1_met = bool(fpi_res["overall_accuracy"] < 0.55 or fpi_res["nofault_fpr"] > 0.15)

    def _model_a2(name: str, zs: dict, ub: dict, fs20_m: dict) -> dict:
        margin_all = zs["overall_accuracy"] - fpi_res["overall_accuracy"]
        margin_ph = zs["phase_faults_accuracy"] - fpi_res["phase_faults_accuracy"]
        gap = ub["overall_accuracy"] - zs["overall_accuracy"]
        fs20_acc = fs20_m["overall_accuracy_mean"]
        fs20_fpr = fs20_m["nofault_fpr_mean"]
        gap_closed = ((fs20_acc - zs["overall_accuracy"]) / gap) if gap > 1e-9 else None
        fs20_helps = (gap_closed is not None and gap_closed >= 0.50 and fs20_fpr < zs["nofault_fpr"])
        a2_main = (margin_all >= 0.25) and (zs["nofault_fpr"] <= 0.05)
        a2_partial = (not a2_main) and ((margin_all >= 0.15) or (margin_ph >= 0.25) or fs20_helps)
        verdict = "A2-Main" if a2_main else ("A2-Partial" if a2_partial else "A2-Fail")
        return {
            "model": name,
            "verdict": verdict,
            "a2_main_met": bool(a2_main),
            "a2_partial_met": bool(a2_partial),
            "margin_over_fpi": round(margin_all, 4),
            "phase_faults_margin_over_fpi": round(margin_ph, 4),
            "nofault_fpr": round(zs["nofault_fpr"], 4),
            "few_shot_20pct_gap_closed": round(float(gap_closed), 4) if gap_closed is not None else None,
            "few_shot_20pct_fpr": round(fs20_fpr, 4),
        }

    m_gbdt = _model_a2("per_node_gbdt", zs_gbdt, ub_gbdt, fs20["models"]["per_node_gbdt"])
    m_gat = _model_a2("active_gatv2", zs_gat, ub_gat, fs20["models"]["active_gatv2"])
    any_main = m_gbdt["a2_main_met"] or m_gat["a2_main_met"]
    any_partial = m_gbdt["a2_partial_met"] or m_gat["a2_partial_met"]
    overall_a2 = "A2-Main" if any_main else ("A2-Partial" if any_partial else "A2-Fail")

    return {
        "A1_breaks_legacy_fpi": {
            "met": a1_met,
            "fpi_37_acc": round(fpi_res["overall_accuracy"], 4),
            "fpi_37_fpr": round(fpi_res["nofault_fpr"], 4),
        },
        "A2_zero_shot_active_transfer": {
            "verdict": overall_a2,
            "per_node_gbdt": m_gbdt,
            "active_gatv2": m_gat,
            "gbdt_vs_gatv2_zero_shot_37": {
                "gbdt_acc": round(zs_gbdt["overall_accuracy"], 4),
                "gatv2_acc": round(zs_gat["overall_accuracy"], 4),
                "gbdt_phase_acc": zs_gbdt["phase_faults_accuracy"],
                "gatv2_phase_acc": zs_gat["phase_faults_accuracy"],
                "gbdt_loop": round(zs_gbdt["looped_accuracy"], 4),
                "gatv2_loop": round(zs_gat["looped_accuracy"], 4),
                "gbdt_high_der": zs_gbdt["fault_acc_by_der_band"]["high_30_50pct"],
                "gatv2_high_der": zs_gat["fault_acc_by_der_band"]["high_30_50pct"],
                "gbdt_fpr": round(zs_gbdt["nofault_fpr"], 4),
                "gatv2_fpr": round(zs_gat["nofault_fpr"], 4),
                "gbdt_miss": round(zs_gbdt["missing_sensor_mean"], 4),
                "gatv2_miss": round(zs_gat["missing_sensor_mean"], 4),
            },
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--skip-sweep", action="store_true", help="reuse existing active_*.npz files")
    ap.add_argument("--quick", action="store_true", help="smaller epochs/repeats for smoke check")
    ap.add_argument("--test-feeder", choices=["ieee34", "ieee37"], default="ieee34",
                    help="unseen target feeder: ieee34 (default -> results/active_grid/) or "
                         "ieee37 (-> results/active_grid_ieee37/)")
    ap.add_argument("--extra-r34", default="",
                    help="comma list of extra 34-bus SLG resistances (ohm); writes to results/active_grid_hard34/ "
                         "(PLAN.md Addendum B2) and leaves the main results untouched")
    args = ap.parse_args()
    test_feeder = args.test_feeder
    producer = "active_grid"
    if test_feeder == "ieee37":
        if args.extra_r34:
            raise SystemExit("--extra-r34 only applies when --test-feeder ieee34")
        ag.ACTIVE_SUMMARY_DIR = ag.config.RESULTS / "active_grid_ieee37"
        producer = "active_grid_ieee37"
    elif args.extra_r34:
        extra = [float(x) for x in args.extra_r34.split(",") if x.strip()]
        ag.SLG_R_BY_FEEDER["ieee34"] = sorted(set(ag.SLG_R_BY_FEEDER["ieee34"]) | set(extra))
        ag.ACTIVE_SUMMARY_DIR = ag.config.RESULTS / "active_grid_hard34"
        producer = "active_grid_hard34"
        print("Addendum B2: 34-bus SLG resistances", ag.SLG_R_BY_FEEDER["ieee34"])

    t0 = time.time()
    dev = am.get_device(prefer_gpu=True)
    print(f"Running Active-Grid GNN + Conformal study (ieee123 -> {test_feeder}) on device: {dev} "
          f"(torch {torch.__version__}, cuda={torch.cuda.is_available()})")

    # ------------------------------------------------------------------
    # 1. OpenDSS Active-Grid Sweeps (DER 0-50%, Reconfig/Loop, HIF, NO_FAULT)
    # ------------------------------------------------------------------
    ag.ACTIVE_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    if not args.skip_sweep:
        print("\n=== Step 1: OpenDSS active-grid sweeps ===")
        s123 = ag.sweep_active("ieee123", seed=args.seed, scenarios_per_topo=1, verbose=True)
        test_scenarios = 2 if test_feeder == "ieee34" else 1
        s_test = ag.sweep_active(test_feeder, seed=args.seed + 1, scenarios_per_topo=test_scenarios, verbose=True)
        ds_summary = {
            "simulation_only": True,
            "seed": args.seed,
            "der_penetration_range": list(ag.DER_PEN_RANGE),
            "features": ag.ACTIVE_FEATURES,
            "ieee123": s123,
            test_feeder: s_test,
        }
        p_ds = ag.ACTIVE_SUMMARY_DIR / "dataset_summary.json"
        p_ds.write_text(json.dumps(ds_summary, indent=2) + "\n", encoding="utf-8")
    else:
        p_ds = ag.ACTIVE_SUMMARY_DIR / "dataset_summary.json"

    ds123 = am.load_active_dataset("ieee123")
    print(f"\nLoaded active ieee123: {len(ds123.y)} events "
          f"({int((ds123.y < ds123.nofault_class).sum())} faults, "
          f"{int((ds123.y == ds123.nofault_class).sum())} non-faults), "
          f"{ds123.n_nodes} devices, {len(ds123.topo_names)} topologies")

    # ------------------------------------------------------------------
    # 2. IEEE 123-bus ONLY: FPI, ActivePerNodeGBDT, ActiveGridGATv2 (5-fold GroupKFold)
    # ------------------------------------------------------------------
    print("\n=== Step 2: IEEE 123-bus training & 5-fold GroupKFold by bus ===")
    fpi123 = _cv_fpi(ds123)
    print(f"  FPI (123): acc={fpi123['overall_accuracy']:.4f}, fault_acc={fpi123['fault_zone_accuracy']:.4f}, "
          f"FPR={fpi123['nofault_fpr']:.4f}, loop={fpi123['looped_accuracy']:.4f}")

    gbdt_grid = GBDT_GRID[:1] if args.quick else GBDT_GRID
    gbdt_trials, gbdt_store = [], {}
    for cfg in gbdt_grid:
        ts = time.time()
        kw = {k: v for k, v in cfg.items() if k != "name"}
        if args.quick:
            kw["max_iter"] = 80
        res, oof = _cv_gbdt(ds123, seed=args.seed, eval_missing=True, **kw)
        dt = round(time.time() - ts, 1)
        gbdt_store[cfg["name"]] = (res, oof, kw)
        gbdt_trials.append({"name": cfg["name"], "params": kw, "overall_accuracy": res["overall_accuracy"],
                            "fault_zone_accuracy": res["fault_zone_accuracy"], "nofault_fpr": res["nofault_fpr"],
                            "looped_accuracy": res["looped_accuracy"], "missing_sensor_mean": res["missing_sensor_mean"],
                            "runtime_s": dt})
        print(f"  {cfg['name']:24s} acc={res['overall_accuracy']:.4f} (fault={res['fault_zone_accuracy']:.4f}, "
              f"FPR={res['nofault_fpr']:.4f}, loop={res['looped_accuracy']:.4f}, "
              f"miss={res['missing_sensor_mean']:.4f}) [{dt}s]")
    best_gbdt_t = max(gbdt_trials, key=lambda x: x["overall_accuracy"])
    gbdt123_res, gbdt123_oof, best_gbdt_kw = gbdt_store[best_gbdt_t["name"]]

    gat_grid = GAT_GRID[:1] if args.quick else GAT_GRID
    gat_trials, gat_store = [], {}
    for cfg in gat_grid:
        ts = time.time()
        kw = {k: v for k, v in cfg.items() if k != "name"}
        if args.quick:
            kw["epochs"] = 8
        res, oof = _cv_gat(ds123, seed=args.seed, eval_missing=True, device=dev, **kw)
        dt = round(time.time() - ts, 1)
        gat_store[cfg["name"]] = (res, oof, kw)
        gat_trials.append({"name": cfg["name"], "params": kw, "overall_accuracy": res["overall_accuracy"],
                           "fault_zone_accuracy": res["fault_zone_accuracy"], "nofault_fpr": res["nofault_fpr"],
                           "looped_accuracy": res["looped_accuracy"], "missing_sensor_mean": res["missing_sensor_mean"],
                           "runtime_s": dt})
        print(f"  {cfg['name']:24s} acc={res['overall_accuracy']:.4f} (fault={res['fault_zone_accuracy']:.4f}, "
              f"FPR={res['nofault_fpr']:.4f}, loop={res['looped_accuracy']:.4f}, "
              f"miss={res['missing_sensor_mean']:.4f}) [{dt}s]")
    best_gat_t = max(gat_trials, key=lambda x: x["overall_accuracy"])
    gat123_res, gat123_oof, best_gat_kw = gat_store[best_gat_t["name"]]

    # Fit final frozen models on all IEEE 123-bus events.
    print("\n  Fitting final frozen IEEE 123-bus models...")
    final_gbdt = am.ActivePerNodeGBDT(seed=args.seed, **best_gbdt_kw).fit(
        ds123.X, ds123.y, ds123.adj, ds123.topo_id,
    )
    final_gat = am.train_active_gat(
        ds123.X, ds123.y, ds123.adj, ds123.is_tie, ds123.topo_id,
        seed=args.seed, device=dev, **best_gat_kw,
    )
    gat_params = sum(p.numel() for p in final_gat.parameters())

    frozen_key = f"frozen_for_{test_feeder}"
    p123 = ag.ACTIVE_SUMMARY_DIR / "phase_active_ieee123.json"
    p123_obj = {
        "phase": "active_ieee123",
        "simulation_only": True,
        "feeder": "ieee123",
        "events": int(len(ds123.y)),
        "fault_events": int((ds123.y < ds123.nofault_class).sum()),
        "nofault_events": int((ds123.y == ds123.nofault_class).sum()),
        "topologies": ds123.topo_names,
        "devices": ds123.devices,
        "validation": {"method": "GroupKFold", "group_by": "bus", "n_splits": am.N_FOLDS},
        "models": {
            "fpi": fpi123,
            "per_node_gbdt": {"selected": best_gbdt_t["name"], "params": best_gbdt_kw, **gbdt123_res},
            "active_gatv2": {"selected": best_gat_t["name"], "params": best_gat_kw,
                             "parameter_count": gat_params, **gat123_res},
        },
        "tuning_ieee123_only": {"per_node_gbdt": gbdt_trials, "active_gatv2": gat_trials},
        frozen_key: {"per_node_gbdt": best_gbdt_kw, "active_gatv2": best_gat_kw},
        "device": str(dev),
        "versions": {"torch": torch.__version__, "sklearn": sklearn.__version__, "numpy": np.__version__},
    }
    p123.write_text(json.dumps(p123_obj, indent=2) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # 3. Unseen Active Target Feeder Transfer (Zero-shot, Upper bound, Few-shot)
    # ------------------------------------------------------------------
    print(f"\n=== Step 3: Unseen Active {test_feeder} transfer evaluation ===")
    ds_te = am.load_active_dataset(test_feeder)
    print(f"Loaded active {test_feeder}: {len(ds_te.y)} events "
          f"({int((ds_te.y < ds_te.nofault_class).sum())} faults, "
          f"{int((ds_te.y == ds_te.nofault_class).sum())} non-faults), "
          f"{ds_te.n_nodes} devices, {len(ds_te.topo_names)} topologies")

    fpi_te = _cv_fpi(ds_te)
    fpi_te_pred = am.active_fpi_predict(ds_te.X, ds_te.adj, ds_te.topo_id)
    fpi_te["phase_faults_accuracy"] = _phase_fault_acc(ds_te, fpi_te_pred)
    print(f"  FPI ({test_feeder}): acc={fpi_te['overall_accuracy']:.4f}, fault_acc={fpi_te['fault_zone_accuracy']:.4f}, "
          f"phase={fpi_te['phase_faults_accuracy']:.4f}, FPR={fpi_te['nofault_fpr']:.4f}, loop={fpi_te['looped_accuracy']:.4f}")

    # Zero-shot GBDT
    zs_gbdt_probs = final_gbdt.predict_proba(ds_te.X, ds_te.adj, ds_te.topo_id)
    zs_gbdt_miss = {d: int((final_gbdt.predict(am.blank_active_sensor(ds_te.X, i),
                                               ds_te.adj, ds_te.topo_id) == ds_te.y).sum())
                    for i, d in enumerate(ds_te.devices)}
    zs_gbdt_res = am.evaluate_active(ds_te, zs_gbdt_probs.argmax(axis=1), None, zs_gbdt_miss)
    zs_gbdt_res["phase_faults_accuracy"] = _phase_fault_acc(ds_te, zs_gbdt_probs.argmax(axis=1))

    # Zero-shot GATv2
    zs_gat_probs = am.predict_proba_gat(final_gat, ds_te.X, ds_te.adj, ds_te.is_tie, ds_te.topo_id, device=dev)
    zs_gat_miss = {d: int((am.predict_proba_gat(final_gat, am.blank_active_sensor(ds_te.X, i),
                                                ds_te.adj, ds_te.is_tie, ds_te.topo_id,
                                                device=dev).argmax(axis=1) == ds_te.y).sum())
                   for i, d in enumerate(ds_te.devices)}
    zs_gat_res = am.evaluate_active(ds_te, zs_gat_probs.argmax(axis=1), None, zs_gat_miss)
    zs_gat_res["phase_faults_accuracy"] = _phase_fault_acc(ds_te, zs_gat_probs.argmax(axis=1))

    print(f"  Zero-shot GBDT ({test_feeder}): acc={zs_gbdt_res['overall_accuracy']:.4f}, "
          f"fault={zs_gbdt_res['fault_zone_accuracy']:.4f}, phase={zs_gbdt_res['phase_faults_accuracy']:.4f}, "
          f"FPR={zs_gbdt_res['nofault_fpr']:.4f}, loop={zs_gbdt_res['looped_accuracy']:.4f}, "
          f"miss={zs_gbdt_res['missing_sensor_mean']:.4f}")
    print(f"  Zero-shot GATv2({test_feeder}): acc={zs_gat_res['overall_accuracy']:.4f}, "
          f"fault={zs_gat_res['fault_zone_accuracy']:.4f}, phase={zs_gat_res['phase_faults_accuracy']:.4f}, "
          f"FPR={zs_gat_res['nofault_fpr']:.4f}, loop={zs_gat_res['looped_accuracy']:.4f}, "
          f"miss={zs_gat_res['missing_sensor_mean']:.4f}")

    # In-domain upper bound on unseen target feeder (5-fold GroupKFold, frozen hyperparams)
    ub_gbdt_res, ub_gbdt_oof = _cv_gbdt(ds_te, seed=args.seed, eval_missing=True, **best_gbdt_kw)
    ub_gbdt_res["phase_faults_accuracy"] = _phase_fault_acc(ds_te, ub_gbdt_oof.argmax(axis=1))
    ub_gat_res, ub_gat_oof = _cv_gat(ds_te, seed=args.seed, eval_missing=True, device=dev, **best_gat_kw)
    ub_gat_res["phase_faults_accuracy"] = _phase_fault_acc(ds_te, ub_gat_oof.argmax(axis=1))
    print(f"  In-domain GBDT ({test_feeder}): acc={ub_gbdt_res['overall_accuracy']:.4f}, FPR={ub_gbdt_res['nofault_fpr']:.4f}")
    print(f"  In-domain GATv2({test_feeder}): acc={ub_gat_res['overall_accuracy']:.4f}, FPR={ub_gat_res['nofault_fpr']:.4f}")

    # Few-shot 5% & 20%
    n_rep = 2 if args.quick else 5
    fs5 = _few_shot_active(ds_te, 0.05, base_gbdt=final_gbdt, base_gat=final_gat,
                           n_repeats=n_rep, seed=args.seed, device=dev)
    fs20 = _few_shot_active(ds_te, 0.20, base_gbdt=final_gbdt, base_gat=final_gat,
                            n_repeats=n_rep, seed=args.seed + 100, device=dev)
    print(f"  Few-shot 5% : GBDT={fs5['models']['per_node_gbdt']['overall_accuracy_mean']:.4f}, "
          f"GATv2={fs5['models']['active_gatv2']['overall_accuracy_mean']:.4f}")
    print(f"  Few-shot 20%: GBDT={fs20['models']['per_node_gbdt']['overall_accuracy_mean']:.4f}, "
          f"GATv2={fs20['models']['active_gatv2']['overall_accuracy_mean']:.4f}")

    # Save the class probabilities the conformal step uses, so scripts/active_conformal_posthoc.py
    # and scripts/active_conformal_calsize.py compare nonconformity scores on exactly these numbers and splits.
    fold_id123 = np.full(len(ds123.y), -1, dtype=np.int64)
    for fi, (_, te) in enumerate(am.make_bus_group_folds(ds123)):
        fold_id123[te] = fi
    probs_path = ag.transfer.OUT_DIR / ("active_probs.npz" if producer == "active_grid" else f"{producer}_probs.npz")
    probs_path.parent.mkdir(parents=True, exist_ok=True)
    tag = "34" if test_feeder == "ieee34" else "37"
    np.savez_compressed(
        probs_path,
        test_feeder=np.array(test_feeder),
        gbdt123_oof=gbdt123_oof, gat123_oof=gat123_oof, y123=ds123.y, fold_id123=fold_id123,
        nofault123=np.int64(ds123.nofault_class),
        **{
            f"gbdt{tag}_zs": zs_gbdt_probs,
            f"gat{tag}_zs": zs_gat_probs,
            f"y{tag}": ds_te.y,
            f"bus{tag}": ds_te.bus.astype(str),
            f"nofault{tag}": np.int64(ds_te.nofault_class),
        },
    )
    print(f"  Saved conformal input probabilities to {probs_path}")

    # ------------------------------------------------------------------
    # 4. Split Conformal Prediction (APS at 90% and 95% target coverage)
    # ------------------------------------------------------------------
    print("\n=== Step 4: Split Conformal Prediction (APS 90% and 95%) ===")
    conf_123_gbdt = _conformal_in_domain_cv(ds123, gbdt123_oof)
    conf_123_gat = _conformal_in_domain_cv(ds123, gat123_oof)
    conf_te_gbdt = _conformal_34_recal(ds_te, zs_gbdt_probs, gbdt123_oof, ds123.y,
                                       n_repeats=3 if args.quick else 10, seed=args.seed)
    conf_te_gat = _conformal_34_recal(ds_te, zs_gat_probs, gat123_oof, ds123.y,
                                      n_repeats=3 if args.quick else 10, seed=args.seed)

    print("  GATv2 Conformal 95% (ieee123 CV):", conf_123_gat["target_95"])
    print(f"  GATv2 Conformal 95% ({test_feeder} zero-shot q):", conf_te_gat["zero_shot_q_from_123"]["target_95"])
    print(f"  GATv2 Conformal 95% ({test_feeder} 5%-bus recal):", conf_te_gat["recal_5pct_buses_no_retrain"]["target_95"])

    # ------------------------------------------------------------------
    # 5. Pre-committed criteria evaluation
    # ------------------------------------------------------------------
    if test_feeder == "ieee34":
        c1_pass = (fpi123["overall_accuracy"] < 0.55 or fpi123["nofault_fpr"] > 0.15) and (
            fpi_te["overall_accuracy"] < 0.55 or fpi_te["nofault_fpr"] > 0.15)
        c2_margin = zs_gat_res["overall_accuracy"] - fpi_te["overall_accuracy"]
        c2_fpr_ok = zs_gat_res["nofault_fpr"] <= 0.05
        c2_beats_gbdt_overall = zs_gat_res["overall_accuracy"] > zs_gbdt_res["overall_accuracy"]
        c2_beats_gbdt_loop = (zs_gat_res["looped_accuracy"] or 0.0) > (zs_gbdt_res["looped_accuracy"] or 0.0)
        c2_beats_gbdt_miss = zs_gat_res["missing_sensor_mean"] > zs_gbdt_res["missing_sensor_mean"]
        c3_cov_123 = conf_123_gat["target_95"]["empirical_coverage"] >= 0.93
        c3_cov_34_rc = conf_te_gat["recal_5pct_buses_no_retrain"]["target_95"]["empirical_coverage_mean"] >= 0.94
        c3_auto_safer = (conf_te_gat["recal_5pct_buses_no_retrain"]["target_95"]["autonomous_accuracy_mean"]
                         >= conf_te_gat["recal_5pct_buses_no_retrain"]["target_95"]["raw_argmax_accuracy_mean"])

        criteria = {
            "C1_breaks_legacy_fpi": {
                "met": bool(c1_pass),
                "fpi_123_acc": round(fpi123["overall_accuracy"], 4),
                "fpi_123_fpr": round(fpi123["nofault_fpr"], 4),
                "fpi_34_acc": round(fpi_te["overall_accuracy"], 4),
                "fpi_34_fpr": round(fpi_te["nofault_fpr"], 4),
            },
            "C2_zero_shot_transfer_and_gnn_value": {
                "gatv2_margin_over_fpi": round(c2_margin, 4),
                "gatv2_margin_ge_25pct": bool(c2_margin >= 0.25),
                "gatv2_fpr_le_5pct": bool(c2_fpr_ok),
                "gatv2_beats_gbdt_overall_on_34": bool(c2_beats_gbdt_overall),
                "gatv2_beats_gbdt_looped_on_34": bool(c2_beats_gbdt_loop),
                "gatv2_beats_gbdt_missing_sensor_on_34": bool(c2_beats_gbdt_miss),
                "gbdt_vs_gatv2_zero_shot_34": {
                    "gbdt_acc": round(zs_gbdt_res["overall_accuracy"], 4),
                    "gatv2_acc": round(zs_gat_res["overall_accuracy"], 4),
                    "gbdt_loop": round(zs_gbdt_res["looped_accuracy"], 4),
                    "gatv2_loop": round(zs_gat_res["looped_accuracy"], 4),
                    "gbdt_miss": round(zs_gbdt_res["missing_sensor_mean"], 4),
                    "gatv2_miss": round(zs_gat_res["missing_sensor_mean"], 4),
                },
            },
            "C3_conformal_safety_95": {
                "met": bool(c3_cov_123 and c3_cov_34_rc and c3_auto_safer),
                "ieee123_coverage_95": conf_123_gat["target_95"]["empirical_coverage"],
                "ieee34_zs_coverage_95": conf_te_gat["zero_shot_q_from_123"]["target_95"]["empirical_coverage"],
                "ieee34_recal5pct_coverage_95": conf_te_gat["recal_5pct_buses_no_retrain"]["target_95"]["empirical_coverage_mean"],
                "ieee34_recal5pct_auto_acc": conf_te_gat["recal_5pct_buses_no_retrain"]["target_95"]["autonomous_accuracy_mean"],
                "ieee34_recal5pct_raw_acc": conf_te_gat["recal_5pct_buses_no_retrain"]["target_95"]["raw_argmax_accuracy_mean"],
            },
        }
    else:
        criteria = _eval_ieee37_criteria(
            fpi_res=fpi_te, zs_gbdt=zs_gbdt_res, zs_gat=zs_gat_res,
            ub_gbdt=ub_gbdt_res, ub_gat=ub_gat_res, fs20=fs20,
        )

    p_te = ag.ACTIVE_SUMMARY_DIR / f"phase_active_{test_feeder}.json"
    p_te_obj = {
        "phase": f"active_{test_feeder}_transfer",
        "simulation_only": True,
        "train_feeder": "ieee123",
        "test_feeder": test_feeder,
        "events": int(len(ds_te.y)),
        "fault_events": int((ds_te.y < ds_te.nofault_class).sum()),
        "nofault_events": int((ds_te.y == ds_te.nofault_class).sum()),
        "topologies": ds_te.topo_names,
        "devices": ds_te.devices,
        "frozen_hyperparameters_from_123": p123_obj[frozen_key],
        "fpi": fpi_te,
        "zero_shot": {"per_node_gbdt": zs_gbdt_res, "active_gatv2": zs_gat_res},
        "in_domain_upper_bound": {"per_node_gbdt": ub_gbdt_res, "active_gatv2": ub_gat_res},
        "few_shot": {"pct_5": fs5, "pct_20": fs20},
        "pre_committed_criteria": criteria,
        "runtime_s": round(time.time() - t0, 1),
    }
    if test_feeder == "ieee37":
        p_te_obj["plan"] = "research/ieee37-underground/PLAN.md"
    p_te.write_text(json.dumps(p_te_obj, indent=2) + "\n", encoding="utf-8")

    pconf = ag.ACTIVE_SUMMARY_DIR / "conformal_safety.json"
    pconf_obj: dict = {
        "phase": "active_conformal_safety",
        "simulation_only": True,
        "method": "Split Conformal Adaptive Prediction Sets (APS, Romano et al. 2020)",
        "ieee123_bus_disjoint_cv": {"per_node_gbdt": conf_123_gbdt, "active_gatv2": conf_123_gat},
        f"{test_feeder}_transfer": {"per_node_gbdt": conf_te_gbdt, "active_gatv2": conf_te_gat},
    }
    if test_feeder == "ieee34":
        pconf_obj["criteria_c3"] = criteria["C3_conformal_safety_95"]
    else:
        pconf_obj["note"] = ("Deterministic APS (aps_det) logged for schema parity; pre-registered randomized APS "
                             "(aps_rand at 95%) is evaluated by active_conformal_posthoc.py and active_conformal_calsize.py.")
    pconf.write_text(json.dumps(pconf_obj, indent=2) + "\n", encoding="utf-8")

    recorded_files = [p for p in (p_ds, p123, p_te, pconf) if p.exists()]
    provenance.record(producer, recorded_files)
    print("\n=== Pre-committed criteria summary ===")
    print(json.dumps(criteria, indent=2))
    print(f"\nDone in {round(time.time() - t0, 1)} s. Recorded provenance for {len(recorded_files)} files.")


if __name__ == "__main__":
    main()
