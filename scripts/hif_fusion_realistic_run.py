"""Two-Tier Edge HIF-Sensor -> Graph FLISR on Branch-10 Realistic Faults & Noise.

Pre-registered experiment (`research/hif-fusion-realistic/PLAN.md`): paired ablation
(`60Hz_only` vs `60Hz_plus_edge`) on identical realistic OpenDSS events (intermittent
Emanuel arcing `r_eff`, hierarchical zone loading + pre/post load drift, systematic
CT/PT bias + additive 0.5 A / 0.001 pu noise floors), using the frozen Tier-1 Edge
HIF-Sensor (`hif_sensor/results/model_int8.npz`, 417 params / 504 bytes int8 Tiny MLP,
verified SHA-256 `3ba5bd23685d7964a6cea0c94064c1e65a8bf3129d83ac129215d110218397c1`):

  1. Passive IEEE 123-bus realistic (11,448 faults, 5-fold GroupKFold by bus):
     - `fpi` (60 Hz floor)
     - `ml_full` (150 feat vs 170 feat +Edge — direct 1-to-1 comparison with 31.3% SLG 400 ohm in results/metrics.json)
     - `per_node_gbdt` (21 -> 23 feat)
     - `zone_tree_gnn` (2L h64, 21 -> 23 feat)
     Full breakdown: overall, SLG by resistance (0.01..400 ohm), SLG 200-400 ohm, SLG 400 ohm,
     5 Emanuel surfaces, intermittent (`arc_duty < 1.0`) vs continuous (`arc_duty == 1.0`),
     and 1-sensor-offline (simultaneous 60 Hz + Edge blanking).
  2. Passive IEEE 34-bus realistic (4,104 faults): zero-shot & few-shot (5%, 20%).
  3. Active realistic (IEEE 123-bus & IEEE 34-bus: 0-50% Model=7 DER, reconfigured/looped
     topologies, 7 NO_FAULT disturbances, ActivePerNodeGBDT & ActiveGridGATv2 + Split
     Conformal `aps_rand` 90%/95% with `U_SEED = 12345` + `lac`).
  4. Automatic scoring of pre-registered criteria R1-R4 (`PASS` / `PARTIAL` / `FAIL` / `NOT_RUN_YET`),
     Before/After comparison table vs `results/metrics.json` and legacy `results/hif_fusion/*.json`,
     and SHA-256 provenance lock via `shf.provenance.record("hif_fusion_realistic", ...)`.

Isolated outputs (NEVER modifies `results/hif_fusion/*`, `results/provenance/hif_fusion.json`,
`results/metrics.json`, or legacy `data/generated/hif_fusion_*.npz`):
  data/generated/hif_fusion_realistic_{passive,active}_{ieee123,ieee34}.npz
  data/generated/hif_fusion_realistic_probs.npz
  results/hif_fusion_realistic/{dataset_summary,passive_ieee123,passive_ieee34,active_ieee123,active_ieee34,conformal_hif,summary}.json
  results/provenance/hif_fusion_realistic.json

Usage:
  python -u scripts/hif_fusion_realistic_run.py --model-npz hif_sensor/results/model_int8.npz --workers 16

Simulation only. Nothing here is field data.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import sklearn
import torch
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hif_fusion_run as hfr  # noqa: E402
from shf import (  # noqa: E402
    active_grid as ag,
    active_models as am,
    config,
    hif_edge as he,
    hif_fusion as hf,
    provenance,
    transfer_models as tm,
)

OUT_DIR = config.RESULTS / "hif_fusion_realistic"
PRODUCER = "hif_fusion_realistic"

# Frozen hyperparameters (exact match to shf/model.py & scripts/hif_fusion_run.py; never tuned post-hoc).
FROZEN_ML_FULL = {"max_iter": 300, "learning_rate": 0.10, "max_leaf_nodes": 31, "sensor_dropout": 0.15}
FROZEN_PASSIVE_GBDT = dict(hfr.FROZEN_PASSIVE_GBDT)
FROZEN_PASSIVE_GNN = dict(hfr.FROZEN_PASSIVE_GNN)
FROZEN_ACTIVE_GBDT = dict(hfr.FROZEN_ACTIVE_GBDT)
FROZEN_ACTIVE_GAT = dict(hfr.FROZEN_ACTIVE_GAT)

_P_IDX = hfr._P_IDX
_P_PHIF_COL = hfr._P_PHIF_COL
_P_ALARM_COL = hfr._P_ALARM_COL


# ---------------------------------------------------------------------------
# Direct 1-to-1 `ml_full` (150 feat vs 170 feat +Edge) matching shf/model.py
# ---------------------------------------------------------------------------
def _ml_full_device_cols(dev_idx: int, n_devices: int, use_edge: bool) -> list[int]:
    """Column indices for device `dev_idx` in X_ml_full (150) or X_ml_full_fused (170)."""
    n_per_dev = len(hf.ML_FULL_DEVICE_KEYS)  # 15
    cols = list(range(dev_idx * n_per_dev, (dev_idx + 1) * n_per_dev))
    if use_edge:
        edge_base = n_devices * n_per_dev + 2 * dev_idx
        cols.extend([edge_base, edge_base + 1])
    return cols


def _build_ml_full_matrix(ds: hf.PassiveFusionDataset, use_edge: bool) -> tuple[np.ndarray, list[str]]:
    if ds.X_ml_full is None:
        raise ValueError("PassiveFusionDataset missing X_ml_full (must be generated with realistic=True on ieee123)")
    base_feats = list(ds.ml_full_features or hf._ml_full_feature_names(ds.devices))
    X_base = np.asarray(ds.X_ml_full, dtype=np.float32)
    if not use_edge:
        return X_base, base_feats
    edge_block = ds.X[:, :, [_P_PHIF_COL, _P_ALARM_COL]].reshape(len(ds.y), -1).astype(np.float32)
    edge_feats = [f"{d}_{k}" for d in ds.devices for k in ("p_hif", "hif_alarm")]
    return np.concatenate([X_base, edge_block], axis=1).astype(np.float32), base_feats + edge_feats


def _ml_full_dropout(
    X: np.ndarray,
    n_devices: int,
    use_edge: bool,
    rng: np.random.Generator,
    rate: float,
) -> np.ndarray:
    """Simultaneously blank 1 random device's 60-Hz (+Edge when fused) columns on `rate` of rows."""
    if rate <= 0.0:
        return X
    out = np.asarray(X, dtype=np.float32).copy()
    rows = np.flatnonzero(rng.random(len(out)) < rate)
    for r in rows:
        dev_i = int(rng.integers(0, n_devices))
        out[r, _ml_full_device_cols(dev_i, n_devices, use_edge)] = np.nan
    return out


def _blank_ml_full_sensor(X: np.ndarray, dev_idx: int, n_devices: int, use_edge: bool) -> np.ndarray:
    """Blank device `dev_idx` offline (both 60 Hz and Edge channels simultaneously when fused)."""
    out = np.asarray(X, dtype=np.float32).copy()
    out[:, _ml_full_device_cols(dev_idx, n_devices, use_edge)] = np.nan
    return out


# ---------------------------------------------------------------------------
# Realistic Metrics Helpers (adds SLG 0-50, SLG 400, intermittent vs continuous,
# and 5-surface breakdown on both all arcing and SLG 200-400 ohm)
# ---------------------------------------------------------------------------
def _safe_mean(mask: np.ndarray, values: np.ndarray) -> float | None:
    return round(float(values[mask].mean()), 4) if np.any(mask) else None


def _eval_passive_realistic(
    ds: hf.PassiveFusionDataset,
    pred: np.ndarray,
    *,
    fold_indices: list[np.ndarray] | None = None,
    missing_preds: dict[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    out = hfr._eval_passive(ds, pred, fold_indices=fold_indices, missing_preds=missing_preds)
    corr = pred == ds.y
    slg = ds.ftype == "SLG"
    slg_200_400 = slg & np.isin(ds.r, [200.0, 400.0])
    slg_400 = slg & (ds.r == 400.0)
    slg_0_50 = slg & (ds.r <= 50.0)
    arc_m = ds.is_arcing
    duty = ds.arc_duty if ds.arc_duty is not None else np.ones(len(ds.y), dtype=float)
    interm_m = arc_m & (duty < 1.0)
    cont_m = arc_m & (duty >= 1.0)

    out["slg_400_accuracy"] = _safe_mean(slg_400, corr)
    out["slg_low_r_0_50_accuracy"] = _safe_mean(slg_0_50, corr)
    out["by_arc_regime"] = {
        "intermittent": _safe_mean(interm_m, corr),
        "continuous": _safe_mean(cont_m, corr),
        "intermittent_count": int(interm_m.sum()),
        "continuous_count": int(cont_m.sum()),
    }
    out["by_arc_regime_slg_200_400"] = {
        "intermittent": _safe_mean(interm_m & slg_200_400, corr),
        "continuous": _safe_mean(cont_m & slg_200_400, corr),
        "intermittent_count": int((interm_m & slg_200_400).sum()),
        "continuous_count": int((cont_m & slg_200_400).sum()),
    }
    out["by_arc_surface_slg_200_400"] = {
        s: _safe_mean(arc_m & slg_200_400 & (ds.arc_surface == s), corr)
        for s in hf.SURFACE_NAMES
    }
    if missing_preds is not None and slg_400.any():
        out["missing_sensor_slg_400_mean"] = round(float(np.mean([
            float((pm[slg_400] == ds.y[slg_400]).mean()) for pm in missing_preds.values()
        ])), 4)
    elif missing_preds is not None:
        out["missing_sensor_slg_400_mean"] = None
    return out


def _eval_active_realistic(
    ds: hf.ActiveFusionDataset,
    pred: np.ndarray,
    *,
    fold_indices: list[np.ndarray] | None = None,
    missing_preds: dict[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    out = hfr._eval_active(ds, pred, fold_indices=fold_indices, missing_preds=missing_preds)
    corr = pred == ds.y
    slg = ds.ftype == "SLG"
    slg_200_400 = slg & np.isin(ds.r, [200.0, 400.0])
    slg_400 = slg & (ds.r == 400.0)
    slg_0_50 = slg & (ds.r <= 50.0)
    arc_m = ds.is_arcing
    duty = ds.arc_duty if ds.arc_duty is not None else np.ones(len(ds.y), dtype=float)
    interm_m = arc_m & (duty < 1.0)
    cont_m = arc_m & (duty >= 1.0)

    out["slg_400_accuracy"] = _safe_mean(slg_400, corr)
    out["slg_low_r_0_50_accuracy"] = _safe_mean(slg_0_50, corr)
    out["by_arc_regime"] = {
        "intermittent": _safe_mean(interm_m, corr),
        "continuous": _safe_mean(cont_m, corr),
        "intermittent_count": int(interm_m.sum()),
        "continuous_count": int(cont_m.sum()),
    }
    out["by_arc_regime_slg_200_400"] = {
        "intermittent": _safe_mean(interm_m & slg_200_400, corr),
        "continuous": _safe_mean(cont_m & slg_200_400, corr),
        "intermittent_count": int((interm_m & slg_200_400).sum()),
        "continuous_count": int((cont_m & slg_200_400).sum()),
    }
    out["by_arc_surface_slg_200_400"] = {
        s: _safe_mean(arc_m & slg_200_400 & (ds.arc_surface == s), corr)
        for s in hf.SURFACE_NAMES
    }
    if missing_preds is not None and slg_400.any():
        out["missing_sensor_slg_400_mean"] = round(float(np.mean([
            float((pm[slg_400] == ds.y[slg_400]).mean()) for pm in missing_preds.values()
        ])), 4)
    elif missing_preds is not None:
        out["missing_sensor_slg_400_mean"] = None
    return out


# ---------------------------------------------------------------------------
# Passive Realistic Runners (IEEE 123-bus + IEEE 34-bus)
# ---------------------------------------------------------------------------
def _run_passive_123_realistic(
    ds123: hf.PassiveFusionDataset,
    *,
    seed: int,
    quick: bool,
    device: torch.device,
) -> tuple[dict[str, Any], dict[str, Any]]:
    splits = list(GroupKFold(n_splits=tm.N_FOLDS).split(ds123.X, ds123.y, ds123.bus))
    folds = [te for _, te in splits]
    n_dev = len(ds123.devices)

    # 60 Hz FPI baseline
    X60 = ds123.X_60hz
    fpi_pred = tm.fpi_predict(X60, ds123.parent)
    fpi_miss = {d: tm.fpi_predict(tm.blank_sensor(X60, i), ds123.parent) for i, d in enumerate(ds123.devices)}
    fpi_res = _eval_passive_realistic(ds123, fpi_pred, fold_indices=folds, missing_preds=fpi_miss)
    fpi_res["no_device_flagged"] = float((fpi_pred < 0).mean())
    print(f"  [passive 123 realistic] FPI: acc={fpi_res['accuracy']:.4f}, SLG 400={fpi_res['slg_400_accuracy']}, "
          f"no_flag={fpi_res['no_device_flagged']:.4f}")

    ml_kw = dict(FROZEN_ML_FULL)
    gbdt_kw = dict(FROZEN_PASSIVE_GBDT)
    gnn_kw = dict(FROZEN_PASSIVE_GNN)
    if quick:
        ml_kw["max_iter"] = 40
        gbdt_kw["max_iter"] = 40
        gnn_kw["epochs"] = 6

    ablations: dict[str, Any] = {}
    frozen_models: dict[str, Any] = {}
    ml_feats_map: dict[str, list[str]] = {}

    for abl_name, use_edge in (("60Hz_only", False), ("60Hz_plus_edge", True)):
        X_in = ds123.X if use_edge else X60
        X_ml, ml_cols = _build_ml_full_matrix(ds123, use_edge=use_edge)
        ml_feats_map[abl_name] = ml_cols
        print(f"  [passive 123 realistic] ablation={abl_name} (ml_full={X_ml.shape[1]}, node={X_in.shape[-1]})")

        # 1. ml_full (150 vs 170 features) — direct 1-to-1 comparison with results/metrics.json
        t0_m = time.time()
        oof_m = np.empty(len(ds123.y), dtype=np.int64)
        miss_m = {d: np.empty(len(ds123.y), dtype=np.int64) for d in ds123.devices}
        for fi, (tr, te) in enumerate(splits):
            rng_f = np.random.default_rng(seed + fi)
            X_tr = _ml_full_dropout(X_ml[tr], n_dev, use_edge, rng_f, ml_kw["sensor_dropout"])
            clf_m = HistGradientBoostingClassifier(
                max_iter=ml_kw["max_iter"],
                learning_rate=ml_kw["learning_rate"],
                max_leaf_nodes=ml_kw["max_leaf_nodes"],
                random_state=seed + fi,
            ).fit(X_tr, ds123.y[tr])
            oof_m[te] = clf_m.predict(X_ml[te])
            for i, d in enumerate(ds123.devices):
                miss_m[d][te] = clf_m.predict(_blank_ml_full_sensor(X_ml[te], i, n_dev, use_edge))
        res_m = _eval_passive_realistic(ds123, oof_m, fold_indices=folds, missing_preds=miss_m)
        res_m["n_features"] = int(X_ml.shape[1])
        res_m["params"] = ml_kw
        res_m["runtime_s"] = round(time.time() - t0_m, 1)
        print(f"    ml_full     ({abl_name}): acc={res_m['accuracy']:.4f}, SLG 200-400={res_m['slg_200_400_accuracy']}, "
              f"SLG 400={res_m['slg_400_accuracy']}, interm={res_m['by_arc_regime']['intermittent']}, "
              f"miss={res_m['missing_sensor_mean']:.4f} [{res_m['runtime_s']}s]")

        # 2. PerNodeGBDT 5-fold CV
        t1 = time.time()
        oof_g = np.empty(len(ds123.y), dtype=np.int64)
        miss_g = {d: np.empty(len(ds123.y), dtype=np.int64) for d in ds123.devices}
        for fi, (tr, te) in enumerate(splits):
            clf = hfr.FusedPerNodeGBDT(use_edge=use_edge, seed=seed + fi, **gbdt_kw).fit(
                X_in[tr], ds123.y[tr], ds123.parent
            )
            oof_g[te] = clf.predict(X_in[te], ds123.parent)
            for i, d in enumerate(ds123.devices):
                miss_g[d][te] = clf.predict(hfr._blank_sensor(X_in[te], i, "passive", use_edge), ds123.parent)
        res_g = _eval_passive_realistic(ds123, oof_g, fold_indices=folds, missing_preds=miss_g)
        res_g["params"] = gbdt_kw
        res_g["runtime_s"] = round(time.time() - t1, 1)
        print(f"    PerNodeGBDT ({abl_name}): acc={res_g['accuracy']:.4f}, SLG 200-400={res_g['slg_200_400_accuracy']}, "
              f"SLG 400={res_g['slg_400_accuracy']}, interm={res_g['by_arc_regime']['intermittent']}, "
              f"miss={res_g['missing_sensor_mean']:.4f} [{res_g['runtime_s']}s]")

        # 3. ZoneTreeGNN 5-fold CV
        t2 = time.time()
        oof_n = np.empty(len(ds123.y), dtype=np.int64)
        miss_n = {d: np.empty(len(ds123.y), dtype=np.int64) for d in ds123.devices}
        for fi, (tr, te) in enumerate(splits):
            net = hfr._train_passive_gnn(
                X_in[tr], ds123.y[tr], ds123.parent, use_edge=use_edge, seed=seed + fi, device=device, **gnn_kw
            )
            oof_n[te] = hfr._predict_passive_gnn(net, X_in[te], ds123.parent, device=device)
            for i, d in enumerate(ds123.devices):
                miss_n[d][te] = hfr._predict_passive_gnn(
                    net, hfr._blank_sensor(X_in[te], i, "passive", use_edge), ds123.parent, device=device
                )
        res_n = _eval_passive_realistic(ds123, oof_n, fold_indices=folds, missing_preds=miss_n)
        res_n["params"] = gnn_kw
        res_n["runtime_s"] = round(time.time() - t2, 1)
        print(f"    ZoneTreeGNN ({abl_name}): acc={res_n['accuracy']:.4f}, SLG 200-400={res_n['slg_200_400_accuracy']}, "
              f"SLG 400={res_n['slg_400_accuracy']}, interm={res_n['by_arc_regime']['intermittent']}, "
              f"miss={res_n['missing_sensor_mean']:.4f} [{res_n['runtime_s']}s]")

        # Final frozen models trained on all 123-bus events for 34-bus transfer
        fin_g = hfr.FusedPerNodeGBDT(use_edge=use_edge, seed=seed, **gbdt_kw).fit(X_in, ds123.y, ds123.parent)
        fin_n = hfr._train_passive_gnn(X_in, ds123.y, ds123.parent, use_edge=use_edge, seed=seed, device=device, **gnn_kw)
        res_n["parameter_count"] = int(sum(p.numel() for p in fin_n.parameters()))

        ablations[abl_name] = {"ml_full": res_m, "per_node_gbdt": res_g, "zone_tree_gnn": res_n}
        frozen_models[abl_name] = {"per_node_gbdt": fin_g, "zone_tree_gnn": fin_n}

    duty = ds123.arc_duty if ds123.arc_duty is not None else np.ones(len(ds123.y), dtype=float)
    out = {
        "phase": "hif_fusion_realistic_passive_ieee123",
        "status": "COMPLETED",
        "simulation_only": True,
        "realistic_mode": True,
        "quick_mode": bool(quick),
        "feeder": "ieee123",
        "events": int(len(ds123.y)),
        "buses": int(len(np.unique(ds123.bus))),
        "arcing_events": int(ds123.is_arcing.sum()),
        "intermittent_arc_events": int((ds123.is_arcing & (duty < 1.0)).sum()),
        "continuous_arc_events": int((ds123.is_arcing & (duty >= 1.0)).sum()),
        "devices": ds123.devices,
        "features_ml_full_60hz": ml_feats_map["60Hz_only"],
        "features_ml_full_fused": ml_feats_map["60Hz_plus_edge"],
        "features_60hz": list(hf.PASSIVE_FUSED_FEATURES[:17]) + list(hf.PASSIVE_FUSED_FEATURES[19:]),
        "features_fused": ds123.features,
        "validation": {"method": "GroupKFold", "group_by": "bus", "n_splits": tm.N_FOLDS},
        "fpi": fpi_res,
        "ablations": ablations,
    }
    return out, frozen_models


def _run_passive_34_realistic(
    ds34: hf.PassiveFusionDataset,
    frozen_models: dict[str, Any],
    *,
    seed: int,
    quick: bool,
    device: torch.device,
) -> dict[str, Any]:
    X60 = ds34.X_60hz
    fpi_pred = tm.fpi_predict(X60, ds34.parent)
    fpi_miss = {d: tm.fpi_predict(tm.blank_sensor(X60, i), ds34.parent) for i, d in enumerate(ds34.devices)}
    fpi_res = _eval_passive_realistic(ds34, fpi_pred, missing_preds=fpi_miss)
    fpi_res["no_device_flagged"] = float((fpi_pred < 0).mean())

    zs_abl: dict[str, Any] = {}
    for abl_name, use_edge in (("60Hz_only", False), ("60Hz_plus_edge", True)):
        X_in = ds34.X if use_edge else X60
        fg = frozen_models[abl_name]["per_node_gbdt"]
        fn = frozen_models[abl_name]["zone_tree_gnn"]

        pg = fg.predict(X_in, ds34.parent)
        mg = {d: fg.predict(hfr._blank_sensor(X_in, i, "passive", use_edge), ds34.parent)
              for i, d in enumerate(ds34.devices)}
        rg = _eval_passive_realistic(ds34, pg, missing_preds=mg)

        pn = hfr._predict_passive_gnn(fn, X_in, ds34.parent, device=device)
        mn = {d: hfr._predict_passive_gnn(fn, hfr._blank_sensor(X_in, i, "passive", use_edge), ds34.parent, device=device)
              for i, d in enumerate(ds34.devices)}
        rn = _eval_passive_realistic(ds34, pn, missing_preds=mn)

        print(f"  [passive 34 realistic zero-shot {abl_name}] "
              f"GBDT acc={rg['accuracy']:.4f} (SLG 200-400={rg['slg_200_400_accuracy']}, miss={rg['missing_sensor_mean']:.4f}) | "
              f"GNN acc={rn['accuracy']:.4f} (SLG 200-400={rn['slg_200_400_accuracy']}, miss={rn['missing_sensor_mean']:.4f})")
        zs_abl[abl_name] = {"per_node_gbdt": rg, "zone_tree_gnn": rn}

    n_rep = 2 if quick else 10
    fs5 = hfr._few_shot_passive(ds34, 0.05, frozen_models=frozen_models, n_repeats=n_rep, seed=seed, quick=quick, device=device)
    fs20 = hfr._few_shot_passive(ds34, 0.20, frozen_models=frozen_models, n_repeats=n_rep, seed=seed + 100, quick=quick, device=device)
    duty = ds34.arc_duty if ds34.arc_duty is not None else np.ones(len(ds34.y), dtype=float)

    return {
        "phase": "hif_fusion_realistic_passive_ieee34",
        "status": "COMPLETED",
        "simulation_only": True,
        "realistic_mode": True,
        "quick_mode": bool(quick),
        "train_feeder": "ieee123",
        "test_feeder": "ieee34",
        "events": int(len(ds34.y)),
        "buses": int(len(np.unique(ds34.bus))),
        "arcing_events": int(ds34.is_arcing.sum()),
        "intermittent_arc_events": int((ds34.is_arcing & (duty < 1.0)).sum()),
        "continuous_arc_events": int((ds34.is_arcing & (duty >= 1.0)).sum()),
        "devices": ds34.devices,
        "fpi": fpi_res,
        "zero_shot": zs_abl,
        "few_shot": {"pct_5": fs5, "pct_20": fs20},
    }


# ---------------------------------------------------------------------------
# Active Realistic Runners (IEEE 123-bus + IEEE 34-bus + Conformal)
# ---------------------------------------------------------------------------
def _run_active_123_realistic(
    ds123: hf.ActiveFusionDataset,
    *,
    seed: int,
    quick: bool,
    device: torch.device,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, np.ndarray], np.ndarray]:
    splits = list(GroupKFold(n_splits=am.N_FOLDS).split(ds123.X, ds123.y, ds123.bus))
    folds = [te for _, te in splits]
    fold_id = np.full(len(ds123.y), -1, dtype=np.int64)
    for fi, (_, te) in enumerate(splits):
        fold_id[te] = fi

    X60 = ds123.X_60hz
    fpi_pred = am.active_fpi_predict(X60, ds123.adj, ds123.topo_id)
    fpi_miss = {d: am.active_fpi_predict(am.blank_active_sensor(X60, i), ds123.adj, ds123.topo_id)
                for i, d in enumerate(ds123.devices)}
    fpi_res = _eval_active_realistic(ds123, fpi_pred, fold_indices=folds, missing_preds=fpi_miss)

    gbdt_kw = dict(FROZEN_ACTIVE_GBDT)
    gat_kw = dict(FROZEN_ACTIVE_GAT)
    if quick:
        gbdt_kw["max_iter"] = 40
        gat_kw["epochs"] = 6

    ablations: dict[str, Any] = {}
    frozen_models: dict[str, Any] = {}
    oof_store: dict[str, np.ndarray] = {}

    for abl_name, use_edge in (("60Hz_only", False), ("60Hz_plus_edge", True)):
        X_in = ds123.X if use_edge else X60
        print(f"  [active 123 realistic] ablation={abl_name} (node_feat={X_in.shape[-1]}, edge_feat={5 if use_edge else 4})")

        # ActivePerNodeGBDT 5-fold CV
        t1 = time.time()
        oof_g = np.zeros((len(ds123.y), ds123.n_nodes + 1), dtype=np.float64)
        miss_g = {d: np.empty(len(ds123.y), dtype=np.int64) for d in ds123.devices}
        for fi, (tr, te) in enumerate(splits):
            clf = hfr.FusedActivePerNodeGBDT(use_edge=use_edge, seed=seed + fi, **gbdt_kw).fit(
                X_in[tr], ds123.y[tr], ds123.adj, ds123.topo_id[tr]
            )
            oof_g[te] = clf.predict_proba(X_in[te], ds123.adj, ds123.topo_id[te])
            for i, d in enumerate(ds123.devices):
                miss_g[d][te] = clf.predict(hfr._blank_sensor(X_in[te], i, "active", use_edge), ds123.adj, ds123.topo_id[te])
        res_g = _eval_active_realistic(ds123, oof_g.argmax(axis=1), fold_indices=folds, missing_preds=miss_g)
        res_g["params"] = gbdt_kw
        res_g["runtime_s"] = round(time.time() - t1, 1)
        print(f"    ActiveGBDT ({abl_name}): acc={res_g['overall_accuracy']:.4f}, SLG 200-400={res_g['slg_200_400_accuracy']}, "
              f"SLG 400={res_g['slg_400_accuracy']}, FPR={res_g['nofault_fpr']:.4f}, "
              f"miss={res_g['missing_sensor_mean']:.4f} [{res_g['runtime_s']}s]")

        # ActiveGridGATv2 5-fold CV
        t2 = time.time()
        oof_a = np.zeros((len(ds123.y), ds123.n_nodes + 1), dtype=np.float64)
        miss_a = {d: np.empty(len(ds123.y), dtype=np.int64) for d in ds123.devices}
        for fi, (tr, te) in enumerate(splits):
            tf = time.time()
            net = hfr._train_active_gat(
                X_in[tr], ds123.y[tr], ds123.adj, ds123.is_tie, ds123.topo_id[tr],
                use_edge=use_edge, seed=seed + fi, device=device, **gat_kw
            )
            oof_a[te] = hfr._predict_proba_gat(net, X_in[te], ds123.adj, ds123.is_tie, ds123.topo_id[te], device=device)
            for i, d in enumerate(ds123.devices):
                miss_a[d][te] = hfr._predict_proba_gat(
                    net, hfr._blank_sensor(X_in[te], i, "active", use_edge),
                    ds123.adj, ds123.is_tie, ds123.topo_id[te], device=device
                ).argmax(axis=1)
            print(f"      ActiveGATv2 ({abl_name}) fold {fi + 1}/{am.N_FOLDS} done in {time.time() - tf:.1f}s")
        res_a = _eval_active_realistic(ds123, oof_a.argmax(axis=1), fold_indices=folds, missing_preds=miss_a)
        res_a["params"] = gat_kw
        res_a["edge_features"] = 5 if use_edge else 4
        res_a["runtime_s"] = round(time.time() - t2, 1)
        print(f"    ActiveGATv2({abl_name}): acc={res_a['overall_accuracy']:.4f}, SLG 200-400={res_a['slg_200_400_accuracy']}, "
              f"SLG 400={res_a['slg_400_accuracy']}, FPR={res_a['nofault_fpr']:.4f}, "
              f"miss={res_a['missing_sensor_mean']:.4f} [{res_a['runtime_s']}s]")

        # Final frozen models on all 123-bus active events
        fin_g = hfr.FusedActivePerNodeGBDT(use_edge=use_edge, seed=seed, **gbdt_kw).fit(
            X_in, ds123.y, ds123.adj, ds123.topo_id
        )
        fin_a = hfr._train_active_gat(
            X_in, ds123.y, ds123.adj, ds123.is_tie, ds123.topo_id,
            use_edge=use_edge, seed=seed, device=device, **gat_kw
        )
        res_a["parameter_count"] = int(sum(p.numel() for p in fin_a.parameters()))

        ablations[abl_name] = {"active_per_node_gbdt": res_g, "active_grid_gatv2": res_a}
        frozen_models[abl_name] = {"active_per_node_gbdt": fin_g, "active_grid_gatv2": fin_a}
        oof_store[f"{abl_name}__gbdt"] = oof_g
        oof_store[f"{abl_name}__gatv2"] = oof_a

    duty = ds123.arc_duty if ds123.arc_duty is not None else np.ones(len(ds123.y), dtype=float)
    out = {
        "phase": "hif_fusion_realistic_active_ieee123",
        "status": "COMPLETED",
        "simulation_only": True,
        "realistic_mode": True,
        "quick_mode": bool(quick),
        "feeder": "ieee123",
        "events": int(len(ds123.y)),
        "fault_events": int((ds123.y < ds123.nofault_class).sum()),
        "nofault_events": int((ds123.y == ds123.nofault_class).sum()),
        "arcing_events": int(ds123.is_arcing.sum()),
        "intermittent_arc_events": int((ds123.is_arcing & (duty < 1.0)).sum()),
        "continuous_arc_events": int((ds123.is_arcing & (duty >= 1.0)).sum()),
        "topologies": ds123.topo_names,
        "devices": ds123.devices,
        "features_60hz": list(ag.ACTIVE_FEATURES),
        "features_fused": ds123.features,
        "validation": {"method": "GroupKFold", "group_by": "bus", "n_splits": am.N_FOLDS},
        "fpi": fpi_res,
        "ablations": ablations,
    }
    return out, frozen_models, oof_store, fold_id


def _run_active_34_realistic(
    ds34: hf.ActiveFusionDataset,
    frozen_models: dict[str, Any],
    *,
    seed: int,
    quick: bool,
    device: torch.device,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    X60 = ds34.X_60hz
    fpi_pred = am.active_fpi_predict(X60, ds34.adj, ds34.topo_id)
    fpi_miss = {d: am.active_fpi_predict(am.blank_active_sensor(X60, i), ds34.adj, ds34.topo_id)
                for i, d in enumerate(ds34.devices)}
    fpi_res = _eval_active_realistic(ds34, fpi_pred, missing_preds=fpi_miss)

    zs_abl: dict[str, Any] = {}
    zs_probs: dict[str, np.ndarray] = {}

    for abl_name, use_edge in (("60Hz_only", False), ("60Hz_plus_edge", True)):
        X_in = ds34.X if use_edge else X60
        fg = frozen_models[abl_name]["active_per_node_gbdt"]
        fa = frozen_models[abl_name]["active_grid_gatv2"]

        pg = fg.predict_proba(X_in, ds34.adj, ds34.topo_id)
        mg = {d: fg.predict(hfr._blank_sensor(X_in, i, "active", use_edge), ds34.adj, ds34.topo_id)
              for i, d in enumerate(ds34.devices)}
        rg = _eval_active_realistic(ds34, pg.argmax(axis=1), missing_preds=mg)

        pa = hfr._predict_proba_gat(fa, X_in, ds34.adj, ds34.is_tie, ds34.topo_id, device=device)
        ma = {d: hfr._predict_proba_gat(fa, hfr._blank_sensor(X_in, i, "active", use_edge),
                                        ds34.adj, ds34.is_tie, ds34.topo_id, device=device).argmax(axis=1)
              for i, d in enumerate(ds34.devices)}
        ra = _eval_active_realistic(ds34, pa.argmax(axis=1), missing_preds=ma)

        print(f"  [active 34 realistic zero-shot {abl_name}] GBDT acc={rg['overall_accuracy']:.4f} "
              f"(1-10k={rg['slg_hif_1k_10k_accuracy']}, FPR={rg['nofault_fpr']:.4f}, miss={rg['missing_sensor_mean']:.4f}) | "
              f"GATv2 acc={ra['overall_accuracy']:.4f} "
              f"(1-10k={ra['slg_hif_1k_10k_accuracy']}, FPR={ra['nofault_fpr']:.4f}, miss={ra['missing_sensor_mean']:.4f})")

        zs_abl[abl_name] = {"active_per_node_gbdt": rg, "active_grid_gatv2": ra}
        zs_probs[f"{abl_name}__gbdt"] = pg
        zs_probs[f"{abl_name}__gatv2"] = pa

    n_rep = 2 if quick else 5
    fs5 = hfr._few_shot_active(ds34, 0.05, frozen_models=frozen_models, n_repeats=n_rep, seed=seed, quick=quick, device=device)
    fs20 = hfr._few_shot_active(ds34, 0.20, frozen_models=frozen_models, n_repeats=n_rep, seed=seed + 100, quick=quick, device=device)
    duty = ds34.arc_duty if ds34.arc_duty is not None else np.ones(len(ds34.y), dtype=float)

    out = {
        "phase": "hif_fusion_realistic_active_ieee34",
        "status": "COMPLETED",
        "simulation_only": True,
        "realistic_mode": True,
        "quick_mode": bool(quick),
        "train_feeder": "ieee123",
        "test_feeder": "ieee34",
        "events": int(len(ds34.y)),
        "fault_events": int((ds34.y < ds34.nofault_class).sum()),
        "nofault_events": int((ds34.y == ds34.nofault_class).sum()),
        "arcing_events": int(ds34.is_arcing.sum()),
        "intermittent_arc_events": int((ds34.is_arcing & (duty < 1.0)).sum()),
        "continuous_arc_events": int((ds34.is_arcing & (duty >= 1.0)).sum()),
        "topologies": ds34.topo_names,
        "devices": ds34.devices,
        "fpi": fpi_res,
        "zero_shot": zs_abl,
        "few_shot": {"pct_5": fs5, "pct_20": fs20},
    }
    return out, zs_probs


# ---------------------------------------------------------------------------
# Pre-Registered Criteria R1-R4 Evaluation (research/hif-fusion-realistic/PLAN.md §4)
# ---------------------------------------------------------------------------
def _delta(fused_v: float | None, base_v: float | None) -> float | None:
    if fused_v is None or base_v is None:
        return None
    return round(float(fused_v - base_v), 4)


def _evaluate_r1_r4(
    p123: dict[str, Any],
    p34: dict[str, Any],
    a123: dict[str, Any] | None,
    a34: dict[str, Any] | None,
    conf: dict[str, Any] | None,
) -> dict[str, Any]:
    active_ran = (
        a123 is not None and a123.get("status") == "COMPLETED"
        and a34 is not None and a34.get("status") == "COMPLETED"
        and conf is not None and conf.get("status") == "COMPLETED"
    )

    # --- R1: Passive IEEE 123-bus realistic recovery (ml_full, per_node_gbdt, zone_tree_gnn) ---
    r1_models: dict[str, Any] = {}
    any_regress = False
    any_strong = False
    all_ge15 = True
    any_partial = False
    best_d400 = -999.0

    for m in ("ml_full", "per_node_gbdt", "zone_tree_gnn"):
        b = p123["ablations"]["60Hz_only"][m]
        f = p123["ablations"]["60Hz_plus_edge"][m]
        b400 = b["slg_by_resistance"].get("400.0")
        f400 = f["slg_by_resistance"].get("400.0")
        d400 = _delta(f400, b400) or 0.0
        d200_400 = _delta(f["slg_200_400_accuracy"], b["slg_200_400_accuracy"]) or 0.0
        d_low50 = _delta(f["slg_low_r_0_50_accuracy"], b["slg_low_r_0_50_accuracy"]) or 0.0
        d_low100 = _delta(f["slg_low_r_0_100_accuracy"], b["slg_low_r_0_100_accuracy"]) or 0.0
        d_phase = _delta(f["phase_faults_accuracy"], b["phase_faults_accuracy"]) or 0.0
        d_all = _delta(f["accuracy"], b["accuracy"]) or 0.0
        regress = (d_low50 < -0.005) or (d_phase < -0.005)

        any_regress |= regress
        best_d400 = max(best_d400, d400)
        if (d400 >= 0.25) and ((f400 or 0.0) >= 0.65) and (d200_400 >= 0.15):
            any_strong = True
        if d400 < 0.15:
            all_ge15 = False
        if (d400 >= 0.10) and (d200_400 >= 0.05):
            any_partial = True

        r1_models[m] = {
            "base_overall": round(float(b["accuracy"]), 4),
            "fused_overall": round(float(f["accuracy"]), 4),
            "delta_overall": d_all,
            "base_slg400": b400,
            "fused_slg400": f400,
            "delta_slg400": d400,
            "base_slg_200_400": b["slg_200_400_accuracy"],
            "fused_slg_200_400": f["slg_200_400_accuracy"],
            "delta_slg_200_400": d200_400,
            "base_slg_low_r_0_50": b["slg_low_r_0_50_accuracy"],
            "fused_slg_low_r_0_50": f["slg_low_r_0_50_accuracy"],
            "delta_slg_low_r_0_50": d_low50,
            "delta_slg_low_r_0_100": d_low100,
            "base_phase": b["phase_faults_accuracy"],
            "fused_phase": f["phase_faults_accuracy"],
            "delta_phase": d_phase,
            "regressed_phase_or_low_r_0_50_gt_0p5pt": bool(regress),
        }

    if any_regress or best_d400 < 0.10:
        r1_verdict = "FAIL"
    elif any_strong and all_ge15:
        r1_verdict = "PASS"
    elif any_partial:
        r1_verdict = "PARTIAL"
    else:
        r1_verdict = "FAIL"

    # --- R2: Intermittent vs Continuous arcing & all 5 Emanuel surfaces (IEEE 123-bus realistic) ---
    r2_models: dict[str, Any] = {}
    r2_graph_pass = False
    r2_graph_partial = False

    for m in ("ml_full", "per_node_gbdt", "zone_tree_gnn"):
        b = p123["ablations"]["60Hz_only"][m]
        f = p123["ablations"]["60Hz_plus_edge"][m]
        b_int = b["by_arc_regime"]["intermittent"]
        f_int = f["by_arc_regime"]["intermittent"]
        b_cnt = b["by_arc_regime"]["continuous"]
        f_cnt = f["by_arc_regime"]["continuous"]
        d_int = _delta(f_int, b_int) or 0.0
        d_cnt = _delta(f_cnt, b_cnt) or 0.0
        b_surf = b["by_arc_surface"]
        f_surf = f["by_arc_surface"]
        surf_vals = [v for v in f_surf.values() if v is not None]
        min_surf = min(surf_vals) if surf_vals else 0.0
        unimproved_below_60 = any(
            (f_surf[s] is not None and f_surf[s] < 0.60 and (b_surf[s] is None or f_surf[s] <= b_surf[s]))
            for s in hf.SURFACE_NAMES
        )
        below_75_still_improved = all(
            (f_surf[s] is None or f_surf[s] >= 0.75 or (b_surf[s] is not None and f_surf[s] > b_surf[s]))
            for s in hf.SURFACE_NAMES
        )
        m_pass = (d_int >= 0.15) and (min_surf >= 0.75)
        m_partial = (not unimproved_below_60) and (
            (0.05 <= d_int < 0.15)
            or (d_int >= 0.15 and 0.60 <= min_surf < 0.75 and below_75_still_improved)
        )
        if m in ("per_node_gbdt", "zone_tree_gnn"):
            r2_graph_pass |= m_pass
            r2_graph_partial |= m_partial

        r2_models[m] = {
            "base_intermittent": b_int,
            "fused_intermittent": f_int,
            "delta_intermittent": d_int,
            "base_continuous": b_cnt,
            "fused_continuous": f_cnt,
            "delta_continuous": d_cnt,
            "base_intermittent_slg_200_400": b["by_arc_regime_slg_200_400"]["intermittent"],
            "fused_intermittent_slg_200_400": f["by_arc_regime_slg_200_400"]["intermittent"],
            "base_continuous_slg_200_400": b["by_arc_regime_slg_200_400"]["continuous"],
            "fused_continuous_slg_200_400": f["by_arc_regime_slg_200_400"]["continuous"],
            "fused_by_arc_surface": f_surf,
            "fused_by_arc_surface_slg_200_400": f["by_arc_surface_slg_200_400"],
            "min_surface_accuracy": round(float(min_surf), 4),
            "unimproved_surface_below_60pct": bool(unimproved_below_60),
            "model_pass": bool(m_pass),
        }

    r2_verdict = "PASS" if r2_graph_pass else ("PARTIAL" if r2_graph_partial else "FAIL")

    # --- R3a: Passive IEEE 34-bus realistic zero-shot ---
    r3a_models: dict[str, Any] = {}
    r3a_any_pass = False
    r3a_any_partial = False
    for m in ("per_node_gbdt", "zone_tree_gnn"):
        b = p34["zero_shot"]["60Hz_only"][m]
        f = p34["zero_shot"]["60Hz_plus_edge"][m]
        d_all = _delta(f["accuracy"], b["accuracy"]) or 0.0
        b_200_400 = b["slg_200_400_accuracy"]
        f_200_400 = f["slg_200_400_accuracy"]
        d_200_400 = _delta(f_200_400, b_200_400) or 0.0
        base_ge95 = (b_200_400 is not None and b_200_400 >= 0.95)
        if base_ge95:
            m_pass = (d_all >= -0.005) and (d_200_400 >= -0.005)
            m_partial = False
        else:
            m_pass = (d_all >= -0.005) and (d_200_400 >= 0.03)
            m_partial = (d_all >= -0.005) and (0.0 <= d_200_400 < 0.03)
        r3a_any_pass |= m_pass
        r3a_any_partial |= m_partial
        r3a_models[m] = {
            "base_acc": round(float(b["accuracy"]), 4),
            "fused_acc": round(float(f["accuracy"]), 4),
            "delta_acc": d_all,
            "base_slg_200_400": b_200_400,
            "fused_slg_200_400": f_200_400,
            "delta_slg_200_400": d_200_400,
            "base_slg_200_400_ge_95pct": bool(base_ge95),
            "model_pass": bool(m_pass),
        }
    r3a_verdict = "PASS" if r3a_any_pass else ("PARTIAL" if r3a_any_partial else "FAIL")

    # --- R3b: Active realistic (123-bus + 34-bus + Conformal aps_rand 95%) ---
    if not active_ran:
        r3b_obj: dict[str, Any] = {
            "verdict": "NOT_RUN_YET",
            "status": "NOT_RUN_YET",
            "note": "Active realistic branch not run yet in this invocation; run without --skip-active or on Kaggle GPU.",
        }
        r3_verdict = "FAIL" if r3a_verdict == "FAIL" else "PARTIAL"
    else:
        assert a123 is not None and a34 is not None and conf is not None
        a123_models: dict[str, Any] = {}
        a123_pass = False
        a123_partial_core = False
        a123_fpr_reduced_any = False
        a123_best_d400 = -999.0

        for m in ("active_per_node_gbdt", "active_grid_gatv2"):
            b = a123["ablations"]["60Hz_only"][m]
            f = a123["ablations"]["60Hz_plus_edge"][m]
            b400 = b["slg_by_resistance"].get("400.0")
            f400 = f["slg_by_resistance"].get("400.0")
            d400 = _delta(f400, b400) or 0.0
            a123_best_d400 = max(a123_best_d400, d400)
            fpr_b, fpr_f = float(b["nofault_fpr"]), float(f["nofault_fpr"])
            dist_vals = [v for v in f["nofault_fpr_by_disturbance"].values() if v is not None]
            max_dist = max(dist_vals) if dist_vals else 0.0
            fpr_imp = fpr_f < fpr_b
            a123_fpr_reduced_any |= fpr_imp
            if (d400 >= 0.15) and fpr_imp and (fpr_f <= 0.06) and (max_dist <= 0.12):
                a123_pass = True
            if (d400 >= 0.05) and fpr_imp:
                a123_partial_core = True
            a123_models[m] = {
                "base_slg400": b400,
                "fused_slg400": f400,
                "delta_slg400": d400,
                "base_fpr": round(fpr_b, 4),
                "fused_fpr": round(fpr_f, 4),
                "delta_fpr": round(fpr_f - fpr_b, 4),
                "max_disturbance_fpr": round(max_dist, 4),
                "by_disturbance": f["nofault_fpr_by_disturbance"],
            }

        a34_models: dict[str, Any] = {}
        a34_pass = False
        a34_fpr_reduced_any = False
        for m in ("active_per_node_gbdt", "active_grid_gatv2"):
            b = a34["zero_shot"]["60Hz_only"][m]
            f = a34["zero_shot"]["60Hz_plus_edge"][m]
            d_hif = _delta(f["slg_hif_1k_10k_accuracy"], b["slg_hif_1k_10k_accuracy"]) or 0.0
            fpr_b, fpr_f = float(b["nofault_fpr"]), float(f["nofault_fpr"])
            fpr_red = fpr_b - fpr_f
            if fpr_red > 0.0:
                a34_fpr_reduced_any = True
            if (d_hif >= 0.05) and (fpr_red >= 0.05):
                a34_pass = True
            a34_models[m] = {
                "base_overall": round(float(b["overall_accuracy"]), 4),
                "fused_overall": round(float(f["overall_accuracy"]), 4),
                "base_hif_1k_10k": b["slg_hif_1k_10k_accuracy"],
                "fused_hif_1k_10k": f["slg_hif_1k_10k_accuracy"],
                "delta_hif_1k_10k": d_hif,
                "base_fpr": round(fpr_b, 4),
                "fused_fpr": round(fpr_f, 4),
                "fpr_reduction": round(fpr_red, 4),
            }

        conf_models: dict[str, Any] = {}
        conf_pass = False
        conf_non_deg_any = False
        for m in ("active_per_node_gbdt", "active_grid_gatv2"):
            cb = conf["results"]["60Hz_only"][m]["aps_rand"]
            cf = conf["results"]["60Hz_plus_edge"][m]["aps_rand"]
            non_deg = bool(cf["reading_rule"]["non_degenerate"])
            conf_non_deg_any |= non_deg
            b123 = cb["target_95"]["ieee123_cross_conformal"]
            f123 = cf["target_95"]["ieee123_cross_conformal"]
            s_ok = (f123["singleton_share"] >= b123["singleton_share"] - 1e-4)
            acc_ok = (f123["singleton_accuracy"] is not None and f123["singleton_accuracy"] >= 0.98)
            trip_ok = (f123["nofault_autonomous_trip_share"] is not None and f123["nofault_autonomous_trip_share"] <= 0.02)
            m_pass = bool(non_deg and s_ok and acc_ok and trip_ok)
            conf_pass |= m_pass
            conf_models[m] = {
                "non_degenerate": non_deg,
                "ieee123_cov95": f123["coverage"],
                "base_singleton_share": b123["singleton_share"],
                "fused_singleton_share": f123["singleton_share"],
                "fused_singleton_accuracy": f123["singleton_accuracy"],
                "fused_nofault_auto_trip_share": f123["nofault_autonomous_trip_share"],
                "pass": m_pass,
            }

        if (not a123_fpr_reduced_any) or (not a34_fpr_reduced_any) or (not conf_non_deg_any) or (a123_best_d400 < 0.05):
            r3b_v = "FAIL"
        elif a123_pass and a34_pass and conf_pass:
            r3b_v = "PASS"
        elif a123_partial_core and conf_non_deg_any:
            r3b_v = "PARTIAL"
        else:
            r3b_v = "FAIL"

        r3b_obj = {
            "verdict": r3b_v,
            "status": "COMPLETED",
            "active_ieee123": {"sub_pass": bool(a123_pass), "models": a123_models},
            "active_ieee34_zero_shot": {"sub_pass": bool(a34_pass), "models": a34_models},
            "conformal_aps_rand_95": {"sub_pass": bool(conf_pass), "models": conf_models},
        }
        if r3a_verdict == "PASS" and r3b_v == "PASS":
            r3_verdict = "PASS"
        elif r3a_verdict == "FAIL" or r3b_v == "FAIL":
            r3_verdict = "FAIL"
        else:
            r3_verdict = "PARTIAL"

    # --- R4: 1-sensor offline (simultaneous 60 Hz + Edge blanking) ---
    pairs: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
        ("passive_123_ml_full", p123["ablations"]["60Hz_only"]["ml_full"], p123["ablations"]["60Hz_plus_edge"]["ml_full"]),
        ("passive_123_gbdt", p123["ablations"]["60Hz_only"]["per_node_gbdt"], p123["ablations"]["60Hz_plus_edge"]["per_node_gbdt"]),
        ("passive_123_gnn", p123["ablations"]["60Hz_only"]["zone_tree_gnn"], p123["ablations"]["60Hz_plus_edge"]["zone_tree_gnn"]),
        ("passive_34_gbdt", p34["zero_shot"]["60Hz_only"]["per_node_gbdt"], p34["zero_shot"]["60Hz_plus_edge"]["per_node_gbdt"]),
        ("passive_34_gnn", p34["zero_shot"]["60Hz_only"]["zone_tree_gnn"], p34["zero_shot"]["60Hz_plus_edge"]["zone_tree_gnn"]),
    ]
    if active_ran:
        assert a123 is not None and a34 is not None
        pairs.extend([
            ("active_123_gbdt", a123["ablations"]["60Hz_only"]["active_per_node_gbdt"], a123["ablations"]["60Hz_plus_edge"]["active_per_node_gbdt"]),
            ("active_123_gatv2", a123["ablations"]["60Hz_only"]["active_grid_gatv2"], a123["ablations"]["60Hz_plus_edge"]["active_grid_gatv2"]),
            ("active_34_gbdt", a34["zero_shot"]["60Hz_only"]["active_per_node_gbdt"], a34["zero_shot"]["60Hz_plus_edge"]["active_per_node_gbdt"]),
            ("active_34_gatv2", a34["zero_shot"]["60Hz_only"]["active_grid_gatv2"], a34["zero_shot"]["60Hz_plus_edge"]["active_grid_gatv2"]),
        ])

    r4_pairs: dict[str, Any] = {}
    all_within_1pt = True
    for label, b_obj, f_obj in pairs:
        dm = round(float(f_obj["missing_sensor_mean"] - b_obj["missing_sensor_mean"]), 4)
        dm_hif = _delta(f_obj.get("missing_sensor_slg_200_400_mean"), b_obj.get("missing_sensor_slg_200_400_mean"))
        ok = dm >= -0.010
        all_within_1pt &= ok
        r4_pairs[label] = {
            "base_missing_mean": round(float(b_obj["missing_sensor_mean"]), 4),
            "fused_missing_mean": round(float(f_obj["missing_sensor_mean"]), 4),
            "delta_missing_mean": dm,
            "base_missing_slg_200_400_mean": b_obj.get("missing_sensor_slg_200_400_mean"),
            "fused_missing_slg_200_400_mean": f_obj.get("missing_sensor_slg_200_400_mean"),
            "delta_missing_slg_200_400_mean": dm_hif,
            "ok_within_1pt": bool(ok),
        }

    ml_p123 = r4_pairs["passive_123_ml_full"]
    gbdt_p123 = r4_pairs["passive_123_gbdt"]
    gnn_p123 = r4_pairs["passive_123_gnn"]
    ml_cond2 = (ml_p123["delta_missing_mean"] > 0.0) and ((ml_p123["delta_missing_slg_200_400_mean"] or 0.0) >= 0.05)
    graph_cond2 = any(
        (p["delta_missing_mean"] > 0.0) and ((p["delta_missing_slg_200_400_mean"] or 0.0) >= 0.05)
        for p in (gbdt_p123, gnn_p123)
    )
    best_p123_hif_dm = max(
        (p["delta_missing_slg_200_400_mean"] or -999.0) for p in (ml_p123, gbdt_p123, gnn_p123)
    )

    if not all_within_1pt or best_p123_hif_dm < 0.01:
        r4_verdict = "FAIL"
    elif ml_cond2 and graph_cond2:
        r4_verdict = "PASS"
    else:
        r4_verdict = "PARTIAL"

    return {
        "R1_passive_123_hif_recovery": {
            "verdict": r1_verdict,
            "any_regress_gt_0p5pt": bool(any_regress),
            "best_delta_slg400": round(float(best_d400), 4),
            "models": r1_models,
        },
        "R2_intermittent_and_5_surfaces": {
            "verdict": r2_verdict,
            "models": r2_models,
        },
        "R3_transfer_and_active_conformal": {
            "verdict": r3_verdict,
            "active_not_run_yet": not active_ran,
            "R3a_passive_34_zero_shot": {"verdict": r3a_verdict, "models": r3a_models},
            "R3b_active_and_conformal": r3b_obj,
        },
        "R4_missing_sensor_resilience": {
            "verdict": r4_verdict,
            "all_pairs_within_1pt": bool(all_within_1pt),
            "passive_123_ml_full_hif_ge_5pt": bool(ml_cond2),
            "passive_123_graph_hif_ge_5pt": bool(graph_cond2),
            "pairs": r4_pairs,
        },
    }


# ---------------------------------------------------------------------------
# Before/After Summary Builder (comparing vs results/metrics.json & legacy results/hif_fusion/)
# ---------------------------------------------------------------------------
def _load_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _build_before_after_summary(
    ds_summary: dict[str, Any],
    p123: dict[str, Any],
    p34: dict[str, Any],
    a123: dict[str, Any] | None,
    a34: dict[str, Any] | None,
    conf: dict[str, Any] | None,
    criteria: dict[str, Any],
    env_meta: dict[str, Any],
    *,
    quick: bool,
) -> dict[str, Any]:
    active_ran = (
        a123 is not None and a123.get("status") == "COMPLETED"
        and a34 is not None and a34.get("status") == "COMPLETED"
        and conf is not None and conf.get("status") == "COMPLETED"
    )

    # Read read-only reference baselines from results/metrics.json and legacy results/hif_fusion/*.json
    m_ref = _load_json_if_exists(config.RESULTS / "metrics.json")
    leg_p123 = _load_json_if_exists(config.RESULTS / "hif_fusion" / "passive_ieee123.json")
    leg_p34 = _load_json_if_exists(config.RESULTS / "hif_fusion" / "passive_ieee34.json")
    leg_a123 = _load_json_if_exists(config.RESULTS / "hif_fusion" / "active_ieee123.json")
    leg_a34 = _load_json_if_exists(config.RESULTS / "hif_fusion" / "active_ieee34.json")
    leg_conf = _load_json_if_exists(config.RESULTS / "hif_fusion" / "conformal_hif.json")

    def _p_row(obj: dict[str, Any]) -> dict[str, Any]:
        return {
            "overall": round(float(obj["accuracy"]), 4),
            "slg_100": obj["slg_by_resistance"].get("100.0"),
            "slg_200": obj["slg_by_resistance"].get("200.0"),
            "slg_400": obj["slg_by_resistance"].get("400.0"),
            "slg_200_400": obj.get("slg_200_400_accuracy"),
            "phase_faults": obj.get("phase_faults_accuracy"),
            "slg_low_r_0_50": obj.get("slg_low_r_0_50_accuracy"),
            "slg_low_r_0_100": obj.get("slg_low_r_0_100_accuracy"),
            "missing_sensor_mean": round(float(obj["missing_sensor_mean"]), 4) if obj.get("missing_sensor_mean") is not None else None,
            "missing_sensor_slg_200_400_mean": obj.get("missing_sensor_slg_200_400_mean"),
            "intermittent": obj.get("by_arc_regime", {}).get("intermittent"),
            "continuous": obj.get("by_arc_regime", {}).get("continuous"),
            "min_surface": (
                min(v for v in obj["by_arc_surface"].values() if v is not None)
                if obj.get("by_arc_surface") else None
            ),
        }

    def _a_row(obj: dict[str, Any]) -> dict[str, Any]:
        return {
            "overall": round(float(obj["overall_accuracy"]), 4),
            "fault_zone": round(float(obj["fault_zone_accuracy"]), 4),
            "slg_100": obj["slg_by_resistance"].get("100.0"),
            "slg_200": obj["slg_by_resistance"].get("200.0"),
            "slg_400": obj["slg_by_resistance"].get("400.0"),
            "slg_200_400": obj.get("slg_200_400_accuracy"),
            "slg_hif_1k_10k": obj.get("slg_hif_1k_10k_accuracy"),
            "nofault_fpr": round(float(obj["nofault_fpr"]), 4),
            "missing_sensor_mean": round(float(obj["missing_sensor_mean"]), 4) if obj.get("missing_sensor_mean") is not None else None,
            "missing_sensor_slg_200_400_mean": obj.get("missing_sensor_slg_200_400_mean"),
            "intermittent": obj.get("by_arc_regime", {}).get("intermittent"),
            "continuous": obj.get("by_arc_regime", {}).get("continuous"),
        }

    branch10_ref: dict[str, Any] = {}
    if m_ref is not None:
        fl = m_ref["fault_location"]
        for k in ("fpi_baseline", "ml_magnitude_only", "ml_full"):
            item = fl[k]
            ms = item.get("missing_sensor_accuracy")
            branch10_ref[k] = {
                "source": "results/metrics.json",
                "overall": round(float(item["accuracy"]), 4),
                "slg_100": item["slg_by_resistance"].get("100.0"),
                "slg_200": item["slg_by_resistance"].get("200.0"),
                "slg_400": item["slg_by_resistance"].get("400.0"),
                "missing_sensor_mean": round(float(np.mean(list(ms.values()))), 4) if ms else None,
            }

    legacy_ref: dict[str, Any] = {}
    if leg_p123 is not None:
        legacy_ref["passive_ieee123"] = {
            "source": "results/hif_fusion/passive_ieee123.json",
            "60Hz_only": {m: _p_row(leg_p123["ablations"]["60Hz_only"][m]) for m in ("per_node_gbdt", "zone_tree_gnn")},
            "60Hz_plus_edge": {m: _p_row(leg_p123["ablations"]["60Hz_plus_edge"][m]) for m in ("per_node_gbdt", "zone_tree_gnn")},
        }
    if leg_p34 is not None:
        legacy_ref["passive_ieee34_zero_shot"] = {
            "source": "results/hif_fusion/passive_ieee34.json",
            "60Hz_only": {m: _p_row(leg_p34["zero_shot"]["60Hz_only"][m]) for m in ("per_node_gbdt", "zone_tree_gnn")},
            "60Hz_plus_edge": {m: _p_row(leg_p34["zero_shot"]["60Hz_plus_edge"][m]) for m in ("per_node_gbdt", "zone_tree_gnn")},
        }
    if leg_a123 is not None:
        legacy_ref["active_ieee123"] = {
            "source": "results/hif_fusion/active_ieee123.json",
            "60Hz_only": {m: _a_row(leg_a123["ablations"]["60Hz_only"][m]) for m in ("active_per_node_gbdt", "active_grid_gatv2")},
            "60Hz_plus_edge": {m: _a_row(leg_a123["ablations"]["60Hz_plus_edge"][m]) for m in ("active_per_node_gbdt", "active_grid_gatv2")},
        }
    if leg_a34 is not None:
        legacy_ref["active_ieee34_zero_shot"] = {
            "source": "results/hif_fusion/active_ieee34.json",
            "60Hz_only": {m: _a_row(leg_a34["zero_shot"]["60Hz_only"][m]) for m in ("active_per_node_gbdt", "active_grid_gatv2")},
            "60Hz_plus_edge": {m: _a_row(leg_a34["zero_shot"]["60Hz_plus_edge"][m]) for m in ("active_per_node_gbdt", "active_grid_gatv2")},
        }
    if leg_conf is not None:
        legacy_ref["conformal_aps_rand_95_ieee123"] = {
            abl: {
                m: {
                    "coverage": leg_conf["results"][abl][m]["aps_rand"]["target_95"]["ieee123_cross_conformal"]["coverage"],
                    "singleton_share": leg_conf["results"][abl][m]["aps_rand"]["target_95"]["ieee123_cross_conformal"]["singleton_share"],
                    "singleton_accuracy": leg_conf["results"][abl][m]["aps_rand"]["target_95"]["ieee123_cross_conformal"]["singleton_accuracy"],
                    "nofault_auto_trip": leg_conf["results"][abl][m]["aps_rand"]["target_95"]["ieee123_cross_conformal"]["nofault_autonomous_trip_share"],
                }
                for m in ("active_per_node_gbdt", "active_grid_gatv2")
            }
            for abl in ("60Hz_only", "60Hz_plus_edge")
        }

    realistic_cur: dict[str, Any] = {
        "passive_ieee123": {
            "source": "results/hif_fusion_realistic/passive_ieee123.json",
            "fpi": _p_row(p123["fpi"]),
            "60Hz_only": {m: _p_row(p123["ablations"]["60Hz_only"][m]) for m in ("ml_full", "per_node_gbdt", "zone_tree_gnn")},
            "60Hz_plus_edge": {m: _p_row(p123["ablations"]["60Hz_plus_edge"][m]) for m in ("ml_full", "per_node_gbdt", "zone_tree_gnn")},
        },
        "passive_ieee34_zero_shot": {
            "source": "results/hif_fusion_realistic/passive_ieee34.json",
            "fpi": _p_row(p34["fpi"]),
            "60Hz_only": {m: _p_row(p34["zero_shot"]["60Hz_only"][m]) for m in ("per_node_gbdt", "zone_tree_gnn")},
            "60Hz_plus_edge": {m: _p_row(p34["zero_shot"]["60Hz_plus_edge"][m]) for m in ("per_node_gbdt", "zone_tree_gnn")},
        },
        "passive_ieee34_few_shot": p34["few_shot"],
    }
    if active_ran:
        assert a123 is not None and a34 is not None and conf is not None
        realistic_cur["active_ieee123"] = {
            "source": "results/hif_fusion_realistic/active_ieee123.json",
            "fpi": _a_row(a123["fpi"]),
            "60Hz_only": {m: _a_row(a123["ablations"]["60Hz_only"][m]) for m in ("active_per_node_gbdt", "active_grid_gatv2")},
            "60Hz_plus_edge": {m: _a_row(a123["ablations"]["60Hz_plus_edge"][m]) for m in ("active_per_node_gbdt", "active_grid_gatv2")},
        }
        realistic_cur["active_ieee34_zero_shot"] = {
            "source": "results/hif_fusion_realistic/active_ieee34.json",
            "fpi": _a_row(a34["fpi"]),
            "60Hz_only": {m: _a_row(a34["zero_shot"]["60Hz_only"][m]) for m in ("active_per_node_gbdt", "active_grid_gatv2")},
            "60Hz_plus_edge": {m: _a_row(a34["zero_shot"]["60Hz_plus_edge"][m]) for m in ("active_per_node_gbdt", "active_grid_gatv2")},
        }
        realistic_cur["conformal_aps_rand_95_ieee123"] = {
            abl: {
                m: {
                    "coverage": conf["results"][abl][m]["aps_rand"]["target_95"]["ieee123_cross_conformal"]["coverage"],
                    "singleton_share": conf["results"][abl][m]["aps_rand"]["target_95"]["ieee123_cross_conformal"]["singleton_share"],
                    "singleton_accuracy": conf["results"][abl][m]["aps_rand"]["target_95"]["ieee123_cross_conformal"]["singleton_accuracy"],
                    "nofault_auto_trip": conf["results"][abl][m]["aps_rand"]["target_95"]["ieee123_cross_conformal"]["nofault_autonomous_trip_share"],
                }
                for m in ("active_per_node_gbdt", "active_grid_gatv2")
            }
            for abl in ("60Hz_only", "60Hz_plus_edge")
        }
    else:
        realistic_cur["active_ieee123"] = {"status": "NOT_RUN_YET"}
        realistic_cur["active_ieee34_zero_shot"] = {"status": "NOT_RUN_YET"}
        realistic_cur["conformal_aps_rand_95_ieee123"] = {"status": "NOT_RUN_YET"}

    verdicts = {
        "R1": criteria["R1_passive_123_hif_recovery"]["verdict"],
        "R2": criteria["R2_intermittent_and_5_surfaces"]["verdict"],
        "R3": criteria["R3_transfer_and_active_conformal"]["verdict"],
        "R3a": criteria["R3_transfer_and_active_conformal"]["R3a_passive_34_zero_shot"]["verdict"],
        "R3b": criteria["R3_transfer_and_active_conformal"]["R3b_active_and_conformal"]["verdict"],
        "R4": criteria["R4_missing_sensor_resilience"]["verdict"],
    }

    p123_base = p123["ablations"]["60Hz_only"]
    p123_edge = p123["ablations"]["60Hz_plus_edge"]
    headline: dict[str, Any] = {
        "passive_123_events": p123["events"],
        "passive_123_arcing_events": p123["arcing_events"],
        "passive_123_intermittent_events": p123["intermittent_arc_events"],
        "passive_123_continuous_events": p123["continuous_arc_events"],
        "passive_34_events": p34["events"],
        "ml_full_60hz_overall": round(float(p123_base["ml_full"]["accuracy"]), 4),
        "ml_full_edge_overall": round(float(p123_edge["ml_full"]["accuracy"]), 4),
        "ml_full_60hz_slg400": p123_base["ml_full"]["slg_400_accuracy"],
        "ml_full_edge_slg400": p123_edge["ml_full"]["slg_400_accuracy"],
        "gbdt_60hz_overall": round(float(p123_base["per_node_gbdt"]["accuracy"]), 4),
        "gbdt_edge_overall": round(float(p123_edge["per_node_gbdt"]["accuracy"]), 4),
        "gbdt_60hz_slg400": p123_base["per_node_gbdt"]["slg_400_accuracy"],
        "gbdt_edge_slg400": p123_edge["per_node_gbdt"]["slg_400_accuracy"],
        "gnn_60hz_overall": round(float(p123_base["zone_tree_gnn"]["accuracy"]), 4),
        "gnn_edge_overall": round(float(p123_edge["zone_tree_gnn"]["accuracy"]), 4),
        "gnn_60hz_slg400": p123_base["zone_tree_gnn"]["slg_400_accuracy"],
        "gnn_edge_slg400": p123_edge["zone_tree_gnn"]["slg_400_accuracy"],
    }
    if active_ran:
        assert a123 is not None and a34 is not None
        headline.update({
            "active_123_events": a123["events"],
            "active_34_events": a34["events"],
            "active_123_gbdt_60hz_slg400": a123["ablations"]["60Hz_only"]["active_per_node_gbdt"]["slg_400_accuracy"],
            "active_123_gbdt_edge_slg400": a123["ablations"]["60Hz_plus_edge"]["active_per_node_gbdt"]["slg_400_accuracy"],
            "active_123_gat_60hz_slg400": a123["ablations"]["60Hz_only"]["active_grid_gatv2"]["slg_400_accuracy"],
            "active_123_gat_edge_slg400": a123["ablations"]["60Hz_plus_edge"]["active_grid_gatv2"]["slg_400_accuracy"],
            "active_123_gat_60hz_fpr": round(float(a123["ablations"]["60Hz_only"]["active_grid_gatv2"]["nofault_fpr"]), 4),
            "active_123_gat_edge_fpr": round(float(a123["ablations"]["60Hz_plus_edge"]["active_grid_gatv2"]["nofault_fpr"]), 4),
        })

    return {
        "phase": "hif_fusion_realistic_summary",
        "simulation_only": True,
        "realistic_mode": True,
        "quick_mode": bool(quick),
        "tier1_edge_model": ds_summary.get("tier1_edge_model"),
        "branch_status": {
            "passive_ieee123": p123.get("status", "COMPLETED"),
            "passive_ieee34": p34.get("status", "COMPLETED"),
            "active_ieee123": a123.get("status", "NOT_RUN_YET") if a123 else "NOT_RUN_YET",
            "active_ieee34": a34.get("status", "NOT_RUN_YET") if a34 else "NOT_RUN_YET",
            "conformal_hif": conf.get("status", "NOT_RUN_YET") if conf else "NOT_RUN_YET",
        },
        "verdicts": verdicts,
        "headline": headline,
        "criteria_details": criteria,
        "before_after_comparison": {
            "branch10_baseline_metrics_json": branch10_ref,
            "legacy_clean_hif_fusion": legacy_ref,
            "realistic_branch10_hif_fusion": realistic_cur,
        },
        **env_meta,
    }


def _rel_posix(path_str: str | None) -> str | None:
    if not path_str:
        return path_str
    p = Path(path_str)
    if not p.is_absolute():
        return p.as_posix()
    try:
        return p.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path_str).replace("\\", "/")


def _sanitize_sweep_paths(obj: dict[str, Any]) -> dict[str, Any]:
    out = dict(obj)
    for k in ("path", "model_source"):
        if k in out and isinstance(out[k], str):
            out[k] = _rel_posix(out[k])
    return out


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Two-tier Edge HIF-Sensor -> Graph FLISR on Branch-10 realistic faults")
    ap.add_argument("--model-npz", type=str, default="hif_sensor/results/model_int8.npz",
                    help="Path to frozen Tier-1 model_int8.npz (verified against locked SHA-256)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=0,
                    help="CPU workers for Tier-1 waveform synthesis (0 = auto min(8, cpu_count))")
    ap.add_argument("--skip-sweep", action="store_true",
                    help="Reuse existing data/generated/hif_fusion_realistic_*.npz")
    ap.add_argument("--skip-active", action="store_true",
                    help="Run Passive 123 & Passive 34 only; record Active & Conformal as NOT_RUN_YET")
    ap.add_argument("--quick", action="store_true",
                    help="Fast smoke test ONLY (never use for final results)")
    ap.add_argument("--out-dir", type=str, default=None,
                    help="Override output JSON directory (for isolated smoke tests; skips provenance if overridden)")
    args = ap.parse_args()

    t0 = time.time()
    out_dir = Path(args.out_dir) if args.out_dir else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    record_prov = (args.out_dir is None)

    n_workers = args.workers if args.workers > 0 else max(1, min(8, os.cpu_count() or 1))

    # Step 0: Load frozen Tier-1 Edge HIF-Sensor & strictly verify SHA-256
    print("=== Step 0: Load & verify frozen Tier-1 Edge HIF-Sensor (model_int8.npz) ===")
    model, model_info = he.load_or_train_model(
        args.model_npz,
        allow_retrain=False,
        verbose=True,
    )
    if model.sha256 != he.FROZEN_MODEL_SHA256:
        raise RuntimeError(
            f"Frozen Tier-1 model SHA-256 mismatch!\n"
            f"  Expected: {he.FROZEN_MODEL_SHA256}\n"
            f"  Actual:   {model.sha256}\n"
            f"  Path:     {model_info['path']}"
        )
    if model.n_params != he.EXPECTED_PARAMS or model.n_bytes != he.EXPECTED_BYTES:
        raise RuntimeError(
            f"Unexpected Tier-1 model size: {model.n_params} params / {model.n_bytes} bytes "
            f"(expected {he.EXPECTED_PARAMS} / {he.EXPECTED_BYTES})"
        )
    model_info["model_source"] = _rel_posix(model_info.get("model_source"))
    model_info["path"] = _rel_posix(model_info.get("path"))
    model.source = str(model_info["model_source"])
    print(f"  VERIFIED frozen Tier-1 model: params={model.n_params} | bytes={model.n_bytes} | "
          f"thr={model.threshold:.16f} | sha256={model.sha256}")

    # Step 1: Realistic OpenDSS + Tier-1 Edge sweeps (BEFORE PyTorch/CUDA init so multiprocessing is clean)
    p_ds = out_dir / "dataset_summary.json"
    if not args.skip_sweep:
        print(f"\n=== Step 1: Realistic Branch-10 OpenDSS + Tier-1 Edge sweeps "
              f"(workers={n_workers}, quick={args.quick}, skip_active={args.skip_active}) ===")
        p_kw = {"scenarios": 1, "max_cases": 80} if args.quick else {}
        a123_kw = (
            {"scenarios_per_topo": 1, "max_cases": 50, "max_nofault_per_topo": 21}
            if args.quick else {"scenarios_per_topo": 1}
        )
        a34_kw = (
            {"scenarios_per_topo": 1, "max_cases": 50, "max_nofault_per_topo": 21}
            if args.quick else {"scenarios_per_topo": 2}
        )

        sp123 = hf.sweep_passive_fusion(
            "ieee123", model, seed=args.seed, n_workers=n_workers, verbose=True, realistic=True, **p_kw
        )
        sp34 = hf.sweep_passive_fusion(
            "ieee34", model, seed=args.seed + 1, n_workers=n_workers, verbose=True, realistic=True, **p_kw
        )
        if not args.skip_active:
            sa123: dict[str, Any] = hf.sweep_active_fusion(
                "ieee123", model, seed=args.seed, n_workers=n_workers, verbose=True, realistic=True, **a123_kw
            )
            sa34: dict[str, Any] = hf.sweep_active_fusion(
                "ieee34", model, seed=args.seed + 1, n_workers=n_workers, verbose=True, realistic=True, **a34_kw
            )
        else:
            sa123 = {"branch": "active", "feeder": "ieee123", "status": "NOT_RUN_YET"}
            sa34 = {"branch": "active", "feeder": "ieee34", "status": "NOT_RUN_YET"}

        ds_summary = {
            "phase": "hif_fusion_realistic_dataset_summary",
            "status": "COMPLETED" if not args.skip_active else "PARTIAL_PASSIVE_ONLY",
            "simulation_only": True,
            "realistic_mode": True,
            "quick_mode": bool(args.quick),
            "seed": args.seed,
            "tier1_model_sha256": model.sha256,
            "tier1_edge_model": model_info,
            "butterworth_cutoff_hz_python": round(he.cutoff_hz(), 1),
            "butterworth_cutoff_hz_ltspice": he.LTSPICE_CUTOFF_HZ,
            "fs_adc_hz": he.FS_ADC,
            "persist_windows": he.PERSIST,
            "branch10_assumptions": {
                "hif_arc_min_r_ohm": config.HIF_ARC_MIN_R,
                "hif_intermittent_prob": config.HIF_INTERMITTENT_PROB,
                "hif_r_eff_max_4p16kv_ohm": config.HIF_R_EFF_MAX,
                "hif_r_eff_max_hv_ratio": 6.25,
                "load_drift_zone": config.LOAD_DRIFT_ZONE,
                "load_drift_spot": config.LOAD_DRIFT_SPOT,
                "ct_bias_mag": config.CT_BIAS_MAG,
                "ct_bias_ang_deg": config.CT_BIAS_ANG_DEG,
                "pt_bias_mag": config.PT_BIAS_MAG,
                "pt_bias_ang_deg": config.PT_BIAS_ANG_DEG,
                "noise_i_floor_a": config.NOISE_I_FLOOR_A,
                "noise_v_floor_pu": config.NOISE_V_FLOOR_PU,
            },
            "surfaces": list(hf.SURFACE_NAMES),
            "disturbances": list(he.DISTURBANCES),
            "passive_ieee123": _sanitize_sweep_paths(sp123),
            "passive_ieee34": _sanitize_sweep_paths(sp34),
            "active_ieee123": _sanitize_sweep_paths(sa123),
            "active_ieee34": _sanitize_sweep_paths(sa34),
        }
        p_ds.write_text(json.dumps(ds_summary, indent=2) + "\n", encoding="utf-8")
    else:
        ds_summary = _load_json_if_exists(p_ds) or {
            "phase": "hif_fusion_realistic_dataset_summary",
            "simulation_only": True,
            "realistic_mode": True,
            "quick_mode": bool(args.quick),
            "tier1_model_sha256": model.sha256,
            "tier1_edge_model": model_info,
        }
        # Normalize any relative model_source paths affected by OpenDSS cwd changes during prior sweep.
        for sub_k in ("passive_ieee123", "passive_ieee34", "active_ieee123", "active_ieee34"):
            sub = ds_summary.get(sub_k)
            if isinstance(sub, dict) and sub.get("model_sha256") == model.sha256:
                sub["model_source"] = model_info["model_source"]
        p_ds.write_text(json.dumps(ds_summary, indent=2) + "\n", encoding="utf-8")

    # Initialize PyTorch device AFTER multiprocessing sweeps finish
    dev = am.get_device(prefer_gpu=True)
    print(f"\n=== Tier-2 Graph FLISR training device: {dev} "
          f"(torch {torch.__version__}, cuda={torch.cuda.is_available()}, threads={torch.get_num_threads()}) ===")

    # Step 2: Passive Realistic Branch (IEEE 123-bus CV + IEEE 34-bus zero-shot / few-shot)
    print("\n=== Step 2: Passive Realistic Branch (FPI, ml_full, PerNodeGBDT, ZoneTreeGNN) ===")
    dsp123 = hf.load_passive_fusion_dataset("ieee123", realistic=True)
    dsp34 = hf.load_passive_fusion_dataset("ieee34", realistic=True)
    p123_obj, p_frozen = _run_passive_123_realistic(dsp123, seed=args.seed, quick=args.quick, device=dev)
    p34_obj = _run_passive_34_realistic(dsp34, p_frozen, seed=args.seed, quick=args.quick, device=dev)

    # Flush Passive JSONs early so progress is persisted even during long Active runs
    p_p123 = out_dir / "passive_ieee123.json"
    p_p34 = out_dir / "passive_ieee34.json"
    p_a123 = out_dir / "active_ieee123.json"
    p_a34 = out_dir / "active_ieee34.json"
    p_conf = out_dir / "conformal_hif.json"
    p_sum = out_dir / "summary.json"
    p_p123.write_text(json.dumps(p123_obj, indent=2) + "\n", encoding="utf-8")
    p_p34.write_text(json.dumps(p34_obj, indent=2) + "\n", encoding="utf-8")

    # Step 3 & 4: Active Realistic Branch + Split Conformal (`aps_rand` 90%/95% + `lac`)
    a123_obj: dict[str, Any]
    a34_obj: dict[str, Any]
    conf_obj: dict[str, Any]

    if not args.skip_active:
        print("\n=== Step 3: Active Realistic Branch (ActivePerNodeGBDT & ActiveGridGATv2) ===")
        dsa123 = hf.load_active_fusion_dataset("ieee123", realistic=True)
        dsa34 = hf.load_active_fusion_dataset("ieee34", realistic=True)
        a123_obj, a_frozen, oof123, fold_id123 = _run_active_123_realistic(
            dsa123, seed=args.seed, quick=args.quick, device=dev
        )
        a34_obj, zs34_probs = _run_active_34_realistic(
            dsa34, a_frozen, seed=args.seed, quick=args.quick, device=dev
        )

        # Save isolated conformal probabilities
        probs_path = hf.FUSED_OUT_DIR / "hif_fusion_realistic_probs.npz"
        probs_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            probs_path,
            y123=dsa123.y,
            fold_id123=fold_id123,
            nofault123=np.int64(dsa123.nofault_class),
            y34=dsa34.y,
            bus34=dsa34.bus.astype(str),
            nofault34=np.int64(dsa34.nofault_class),
            gbdt123_60hz=oof123["60Hz_only__gbdt"],
            gat123_60hz=oof123["60Hz_only__gatv2"],
            gbdt123_fused=oof123["60Hz_plus_edge__gbdt"],
            gat123_fused=oof123["60Hz_plus_edge__gatv2"],
            gbdt34_60hz=zs34_probs["60Hz_only__gbdt"],
            gat34_60hz=zs34_probs["60Hz_only__gatv2"],
            gbdt34_fused=zs34_probs["60Hz_plus_edge__gbdt"],
            gat34_fused=zs34_probs["60Hz_plus_edge__gatv2"],
        )
        print(f"  Saved realistic conformal probabilities to {probs_path}")

        print("\n=== Step 4: Split Conformal Prediction (aps_rand & lac at 90%/95%) ===")
        conf_obj = hfr._run_conformal(
            dsa123, dsa34, fold_id123, oof123, zs34_probs, quick=args.quick, seed=args.seed
        )
        conf_obj["phase"] = "hif_fusion_realistic_conformal"
        conf_obj["status"] = "COMPLETED"
        conf_obj["realistic_mode"] = True
        conf_obj["quick_mode"] = bool(args.quick)
    else:
        not_run_note = "Skipped via --skip-active; run without --skip-active or via notebooks/kaggle_hif_fusion_realistic.ipynb."
        a123_obj = {
            "phase": "hif_fusion_realistic_active_ieee123",
            "status": "NOT_RUN_YET",
            "simulation_only": True,
            "realistic_mode": True,
            "quick_mode": bool(args.quick),
            "note": not_run_note,
        }
        a34_obj = {
            "phase": "hif_fusion_realistic_active_ieee34",
            "status": "NOT_RUN_YET",
            "simulation_only": True,
            "realistic_mode": True,
            "quick_mode": bool(args.quick),
            "note": not_run_note,
        }
        conf_obj = {
            "phase": "hif_fusion_realistic_conformal",
            "status": "NOT_RUN_YET",
            "simulation_only": True,
            "realistic_mode": True,
            "quick_mode": bool(args.quick),
            "note": not_run_note,
        }

    # Step 5: Score pre-registered R1-R4 criteria & write summary.json
    criteria = _evaluate_r1_r4(p123_obj, p34_obj, a123_obj, a34_obj, conf_obj)
    total_rt = round(time.time() - t0, 1)
    env_meta = {
        "device": str(dev),
        "versions": {"torch": torch.__version__, "sklearn": sklearn.__version__, "numpy": np.__version__},
        "tier1_model_sha256": model.sha256,
        "tier1_model_source": model_info["model_source"],
        "runtime_s": total_rt,
    }
    p123_obj.update(env_meta)
    p34_obj.update(env_meta)
    a123_obj.update(env_meta)
    a34_obj["pre_registered_criteria"] = criteria
    a34_obj.update(env_meta)
    conf_obj["pre_registered_criteria_r3b_conformal"] = (
        criteria["R3_transfer_and_active_conformal"]["R3b_active_and_conformal"].get("conformal_aps_rand_95")
    )
    conf_obj.update(env_meta)

    summary_obj = _build_before_after_summary(
        ds_summary, p123_obj, p34_obj, a123_obj, a34_obj, conf_obj, criteria, env_meta, quick=args.quick
    )

    for path, obj in (
        (p_p123, p123_obj),
        (p_p34, p34_obj),
        (p_a123, a123_obj),
        (p_a34, a34_obj),
        (p_conf, conf_obj),
        (p_sum, summary_obj),
    ):
        path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")

    recorded = [p for p in (p_ds, p_p123, p_p34, p_a123, p_a34, p_conf, p_sum) if p.exists()]
    if record_prov:
        provenance.record(PRODUCER, recorded)

    print("\n=== Pre-registered R1-R4 Verdict Summary ===")
    print(json.dumps(summary_obj["verdicts"], indent=2))
    if record_prov:
        print(f"Done in {total_rt} s. Recorded provenance for {len(recorded)} files -> results/provenance/{PRODUCER}.json")
    else:
        print(f"Done in {total_rt} s. Wrote {len(recorded)} files to {out_dir} (provenance skipped due to --out-dir).")


if __name__ == "__main__":
    main()
