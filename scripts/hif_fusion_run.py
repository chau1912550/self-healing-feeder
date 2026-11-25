"""End-to-end Two-Tier Edge HIF-Sensor -> Graph FLISR experiment (research/hif-fusion/PLAN.md).

Paired ablation (`60Hz_only` vs `60Hz_plus_edge`) on identical OpenDSS events, folds, topologies,
and seeds, coupling the frozen Tier-1 Edge HIF-Sensor (417 params / 504 B int8 Tiny MLP from
Kaggle kernel `christoopherchau/ch-y-n`, or deterministic seed=42 fallback) into Tier-2 Graph FLISR:

  1. Passive branch (IEEE 123-bus 5-fold GroupKFold by bus -> unseen IEEE 34-bus zero-shot/few-shot):
     FPI floor, PerNodeGBDT (21 -> 23 features), ZoneTreeGNN (21 -> 23 features, 2L h64).
  2. Active branch (0-50% Model=7 DER, reconfigured/looped topologies, NO_FAULT across 7 disturbances):
     Active FPI floor, ActivePerNodeGBDT (26 -> 28 features + sum(hif_alarm)),
     ActiveGridGATv2 (26 -> 28 node features + 4 -> 5 edge features with diff_p_hif, 2L h64 4H).
  3. Split Conformal Prediction (`aps_rand` primary at 90%/95% with U_SEED=12345, plus `lac`):
     IEEE 123-bus bus-disjoint 5-fold cross-conformal; IEEE 34-bus frozen q_hat (no exchangeability
     guarantee) and bus-disjoint 5%/20% recalibration (10 draws, zero weight retraining).
  4. Pre-committed H1-H4 PASS / PARTIAL / FAIL evaluation.

Isolated outputs (never modifies existing `results/` or `data/generated/transfer_*.npz` / `active_*.npz`):
  data/generated/hif_fusion_{passive,active}_{ieee123,ieee34}.npz
  data/generated/hif_fusion_probs.npz
  results/hif_fusion/{dataset_summary,passive_ieee123,passive_ieee34,active_ieee123,active_ieee34,conformal_hif}.json
  results/provenance/hif_fusion.json

Usage:
  python -u scripts/hif_fusion_run.py --model-npz /kaggle/input/ch-y-n/results/model_int8.npz
  python -u scripts/hif_fusion_run.py --quick   # fast local CPU smoke test

Simulation only. Nothing here is field data.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import sklearn
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shf import (  # noqa: E402
    active_grid as ag,
    active_models as am,
    config,
    hif_edge as he,
    hif_fusion as hf,
    provenance,
    transfer_models as tm,
)

OUT_DIR = config.RESULTS / "hif_fusion"
PRODUCER = "hif_fusion"

# Frozen 123-bus hyperparameters from prior studies (PLAN.md §2.2 & §3.3; never tuned on 34-bus/fused).
FROZEN_PASSIVE_GBDT = {"max_iter": 300, "learning_rate": 0.10, "max_leaf_nodes": 31, "sensor_dropout": 0.15}
FROZEN_PASSIVE_GNN = {
    "n_layers": 2, "hidden": 64, "dropout": 0.1,
    "lr": 2e-3, "weight_decay": 1e-4, "epochs": 40, "batch_size": 256, "sensor_dropout": 0.15,
}
FROZEN_ACTIVE_GBDT = {"max_iter": 300, "learning_rate": 0.05, "max_leaf_nodes": 63, "sensor_dropout": 0.15}
FROZEN_ACTIVE_GAT = {
    "n_layers": 2, "hidden": 64, "n_heads": 4, "dropout": 0.1,
    "lr": 2e-3, "weight_decay": 1e-4, "epochs": 45, "batch_size": 256, "sensor_dropout": 0.15,
}

CONFORMAL_ALPHAS = (0.10, 0.05)
CONFORMAL_METHODS = ("aps_rand", "lac")
U_SEED = 12345

# Fixed indices for active 60-Hz / fused electrical channels (PLAN.md §2.2).
_A_IDX = {name: i for i, name in enumerate(hf.ACTIVE_FUSED_FEATURES)}
_A_DI_COLS = (_A_IDX["dIa"], _A_IDX["dIb"], _A_IDX["dIc"])
_A_V_COLS = (_A_IDX["Va"], _A_IDX["Vb"], _A_IDX["Vc"])
_A_HAS_COLS = (_A_IDX["has_a"], _A_IDX["has_b"], _A_IDX["has_c"])
_A_COS_PRE_COL = _A_IDX["cos_vi_pre"]
_A_PHIF_COL = _A_IDX["p_hif"]          # 21
_A_ALARM_COL = _A_IDX["hif_alarm"]     # 22

_P_IDX = {name: i for i, name in enumerate(hf.PASSIVE_FUSED_FEATURES)}
_P_PHIF_COL = _P_IDX["p_hif"]          # 17
_P_ALARM_COL = _P_IDX["hif_alarm"]     # 18


# ---------------------------------------------------------------------------
# Sensor blanking & dropout (simultaneous 60-Hz + Edge blanking when fused)
# ---------------------------------------------------------------------------
def _n_elec(branch: str, use_edge: bool) -> int:
    if branch == "passive":
        return hf.N_PASSIVE_FUSED_ELEC if use_edge else hf.N_PASSIVE_60HZ_ELEC
    if branch == "active":
        return hf.N_ACTIVE_FUSED_ELEC if use_edge else hf.N_ACTIVE_60HZ_ELEC
    raise ValueError(branch)


def _blank_sensor(X: np.ndarray, node: int, branch: str, use_edge: bool) -> np.ndarray:
    out = np.asarray(X, dtype=np.float32).copy()
    out[..., node, :_n_elec(branch, use_edge)] = np.nan
    return out


def _apply_dropout(X: np.ndarray, rng: np.random.Generator, branch: str, use_edge: bool, rate: float) -> np.ndarray:
    if rate <= 0.0:
        return X
    out = np.asarray(X, dtype=np.float32).copy()
    n_ev, n_nodes, _ = out.shape
    rows = np.flatnonzero(rng.random(n_ev) < rate)
    if len(rows):
        nodes = rng.integers(0, n_nodes, size=len(rows))
        out[rows, nodes, :_n_elec(branch, use_edge)] = np.nan
    return out


# ---------------------------------------------------------------------------
# Passive Tier-2 Models: FusedPerNodeGBDT & FusedZoneTreeGNN (GPU/CPU)
# ---------------------------------------------------------------------------
def _passive_neighborhood_features(X: np.ndarray, parent: np.ndarray, use_edge: bool) -> np.ndarray:
    e_count, n_nodes, n_feat = X.shape
    children = [np.flatnonzero(parent == i) for i in range(n_nodes)]

    x_par = np.full((e_count, n_nodes, n_feat), np.nan, dtype=np.float32)
    x_cmax = np.full((e_count, n_nodes, n_feat), np.nan, dtype=np.float32)
    x_cmean = np.full((e_count, n_nodes, n_feat), np.nan, dtype=np.float32)

    for i in range(n_nodes):
        p = int(parent[i])
        if p >= 0:
            x_par[:, i, :] = X[:, p, :]
        kids = children[i]
        if len(kids) == 1:
            x_cmax[:, i, :] = X[:, kids[0], :]
            x_cmean[:, i, :] = X[:, kids[0], :]
        elif len(kids) > 1:
            sub = X[:, kids, :]
            fin = np.isfinite(sub)
            any_f = fin.any(axis=1)
            safe_max = np.where(fin, sub, -np.inf).max(axis=1)
            x_cmax[:, i, :] = np.where(any_f, safe_max, np.nan)
            cnt = fin.sum(axis=1)
            safe_sum = np.where(fin, sub, 0.0).sum(axis=1)
            x_cmean[:, i, :] = np.where(cnt > 0, safe_sum / np.maximum(cnt, 1), np.nan)

    diff_cols = list(range(tm.N_CONT_ELEC)) + ([_P_PHIF_COL, _P_ALARM_COL] if use_edge else [])
    diff_par = X[:, :, diff_cols] - x_par[:, :, diff_cols]
    diff_cmax = X[:, :, diff_cols] - x_cmax[:, :, diff_cols]
    return np.concatenate([X, x_par, x_cmax, x_cmean, diff_par, diff_cmax], axis=-1)


class FusedPerNodeGBDT:
    def __init__(self, *, use_edge: bool, max_iter: int = 300, learning_rate: float = 0.1,
                 max_leaf_nodes: int = 31, sensor_dropout: float = 0.15, seed: int = 0):
        self.use_edge = bool(use_edge)
        self.params = dict(max_iter=max_iter, learning_rate=learning_rate, max_leaf_nodes=max_leaf_nodes,
                           sensor_dropout=sensor_dropout, seed=seed)
        self.clf = HistGradientBoostingClassifier(
            max_iter=max_iter, learning_rate=learning_rate,
            max_leaf_nodes=max_leaf_nodes, random_state=seed,
        )

    def fit(self, X: np.ndarray, y: np.ndarray, parent: np.ndarray) -> "FusedPerNodeGBDT":
        rng = np.random.default_rng(self.params["seed"])
        X_aug = _apply_dropout(X, rng, "passive", self.use_edge, self.params["sensor_dropout"])
        feat = _passive_neighborhood_features(X_aug, parent, self.use_edge)
        e_count, n_nodes, dim = feat.shape
        target = np.zeros((e_count, n_nodes), dtype=np.int64)
        target[np.arange(e_count), y] = 1
        self.clf.fit(feat.reshape(-1, dim), target.reshape(-1))
        return self

    def predict(self, X: np.ndarray, parent: np.ndarray) -> np.ndarray:
        feat = _passive_neighborhood_features(X, parent, self.use_edge)
        e_count, n_nodes, dim = feat.shape
        raw = self.clf.decision_function(feat.reshape(-1, dim)).reshape(e_count, n_nodes)
        return raw.argmax(axis=1).astype(np.int64)


def _finetune_passive_gbdt(base: FusedPerNodeGBDT, X_few: np.ndarray, y_few: np.ndarray, parent: np.ndarray, *,
                           extra_iter: int = 50, lr: float = 0.05, seed: int = 0) -> FusedPerNodeGBDT:
    clf = copy.deepcopy(base)
    rng = np.random.default_rng(seed)
    X_aug = _apply_dropout(X_few, rng, "passive", clf.use_edge, clf.params["sensor_dropout"])
    feat = _passive_neighborhood_features(X_aug, parent, clf.use_edge)
    e_count, n_nodes, dim = feat.shape
    target = np.zeros((e_count, n_nodes), dtype=np.int64)
    target[np.arange(e_count), y_few] = 1
    clf.clf.set_params(
        warm_start=True, early_stopping=False, learning_rate=lr,
        max_iter=int(clf.clf.n_iter_) + extra_iter, random_state=seed,
    )
    clf.clf.fit(feat.reshape(-1, dim), target.reshape(-1))
    return clf


class FusedZoneTreeGNN(nn.Module):
    """Exact ZoneTreeGNN architecture with configurable live-electrical channel count `n_elec` (17 or 19)."""

    def __init__(self, in_features: int, n_elec: int, hidden: int = 64, n_layers: int = 2, dropout: float = 0.1):
        super().__init__()
        self.in_features = in_features
        self.n_elec = n_elec
        self.hidden = hidden
        self.n_layers = n_layers
        self.dropout = dropout
        self.register_buffer("feat_mean", torch.zeros(in_features))
        self.register_buffer("feat_std", torch.ones(in_features))
        self.encoder = nn.Sequential(
            nn.Linear(in_features + 1, hidden),
            nn.LayerNorm(hidden),
            nn.GELU(),
            nn.Linear(hidden, hidden),
            nn.LayerNorm(hidden),
            nn.GELU(),
        )
        self.layers = nn.ModuleList([tm.TreeMPLayer(hidden, dropout=dropout) for _ in range(n_layers)])
        self.readout = nn.Sequential(
            nn.Linear(hidden, hidden // 2),
            nn.GELU(),
            nn.Linear(hidden // 2, 1),
        )

    def set_normalizer(self, X_train: np.ndarray) -> None:
        flat = X_train.reshape(-1, self.in_features)
        mean = np.nanmean(flat, axis=0)
        std = np.nanstd(flat, axis=0)
        std = np.where(std < 1e-6, 1.0, std)
        self.feat_mean.copy_(torch.from_numpy(mean.astype(np.float32)))
        self.feat_std.copy_(torch.from_numpy(std.astype(np.float32)))

    def forward(self, x: torch.Tensor, parent: torch.Tensor) -> torch.Tensor:
        observed = torch.isfinite(x[:, :, :self.n_elec]).all(dim=-1, keepdim=True)
        obs_f = observed.to(x.dtype)
        x_clean = torch.nan_to_num(x, nan=0.0)
        x_norm = (x_clean - self.feat_mean) / self.feat_std
        elec = x_norm[:, :, :self.n_elec] * obs_f
        struct = x_norm[:, :, self.n_elec:]
        h = self.encoder(torch.cat([elec, struct, obs_f], dim=-1))
        for layer in self.layers:
            h = layer(h, parent)
        return self.readout(h).squeeze(-1)


def _train_passive_gnn(X_train: np.ndarray, y_train: np.ndarray, parent: np.ndarray, *,
                       use_edge: bool, hidden: int = 64, n_layers: int = 2, dropout: float = 0.1,
                       lr: float = 2e-3, weight_decay: float = 1e-4, epochs: int = 40,
                       batch_size: int = 256, sensor_dropout: float = 0.15, seed: int = 0,
                       device: torch.device | None = None) -> FusedZoneTreeGNN:
    dev = device or am.get_device(prefer_gpu=True)
    torch.manual_seed(seed)
    if dev.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    rng = np.random.default_rng(seed)

    n_elec = _n_elec("passive", use_edge)
    net = FusedZoneTreeGNN(in_features=X_train.shape[-1], n_elec=n_elec,
                           hidden=hidden, n_layers=n_layers, dropout=dropout)
    net.set_normalizer(X_train)
    net.to(dev)

    x_all = torch.from_numpy(X_train.astype(np.float32)).to(dev)
    y_all = torch.from_numpy(y_train.astype(np.int64)).to(dev)
    par_t = torch.from_numpy(parent.astype(np.int64)).to(dev)

    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs, eta_min=lr * 0.01)

    n_ev, n_nodes = X_train.shape[0], X_train.shape[1]
    net.train()
    for _ in range(epochs):
        perm = torch.from_numpy(rng.permutation(n_ev)).to(dev)
        for start in range(0, n_ev, batch_size):
            idx = perm[start:start + batch_size]
            xb, yb = x_all[idx], y_all[idx]
            if sensor_dropout > 0.0:
                xb = xb.clone()
                mask = torch.from_numpy(rng.random(len(idx)) < sensor_dropout).to(dev)
                if mask.any():
                    d_rows = torch.nonzero(mask, as_tuple=False).squeeze(-1)
                    d_nodes = torch.from_numpy(rng.integers(0, n_nodes, size=len(d_rows))).to(dev)
                    xb[d_rows, d_nodes, :n_elec] = float("nan")
            opt.zero_grad(set_to_none=True)
            loss = F.cross_entropy(net(xb, par_t), yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 2.0)
            opt.step()
        sched.step()
    net.eval()
    return net


def _finetune_passive_gnn(base: FusedZoneTreeGNN, X_few: np.ndarray, y_few: np.ndarray, parent: np.ndarray, *,
                          epochs: int = 25, lr: float = 5e-4, weight_decay: float = 1e-4,
                          batch_size: int = 64, sensor_dropout: float = 0.15, seed: int = 0,
                          device: torch.device | None = None) -> FusedZoneTreeGNN:
    dev = device or am.get_device(prefer_gpu=True)
    torch.manual_seed(seed)
    if dev.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    rng = np.random.default_rng(seed)

    net = copy.deepcopy(base).to(dev)
    n_elec = net.n_elec
    x_all = torch.from_numpy(X_few.astype(np.float32)).to(dev)
    y_all = torch.from_numpy(y_few.astype(np.int64)).to(dev)
    par_t = torch.from_numpy(parent.astype(np.int64)).to(dev)

    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs, eta_min=lr * 0.05)

    n_ev, n_nodes = X_few.shape[0], X_few.shape[1]
    net.train()
    for _ in range(epochs):
        perm = torch.from_numpy(rng.permutation(n_ev)).to(dev)
        for start in range(0, n_ev, batch_size):
            idx = perm[start:start + batch_size]
            xb, yb = x_all[idx], y_all[idx]
            if sensor_dropout > 0.0:
                xb = xb.clone()
                mask = torch.from_numpy(rng.random(len(idx)) < sensor_dropout).to(dev)
                if mask.any():
                    d_rows = torch.nonzero(mask, as_tuple=False).squeeze(-1)
                    d_nodes = torch.from_numpy(rng.integers(0, n_nodes, size=len(d_rows))).to(dev)
                    xb[d_rows, d_nodes, :n_elec] = float("nan")
            opt.zero_grad(set_to_none=True)
            loss = F.cross_entropy(net(xb, par_t), yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 2.0)
            opt.step()
        sched.step()
    net.eval()
    return net


@torch.no_grad()
def _predict_passive_gnn(net: FusedZoneTreeGNN, X: np.ndarray, parent: np.ndarray,
                         batch_size: int = 1024, device: torch.device | None = None) -> np.ndarray:
    dev = device or next(net.parameters()).device
    net.eval()
    par_t = torch.from_numpy(parent.astype(np.int64)).to(dev)
    preds = []
    for start in range(0, len(X), batch_size):
        xb = torch.from_numpy(X[start:start + batch_size].astype(np.float32)).to(dev)
        preds.append(net(xb, par_t).argmax(dim=-1).cpu().numpy())
    return np.concatenate(preds).astype(np.int64)


# ---------------------------------------------------------------------------
# Active Tier-2 Models: FusedActivePerNodeGBDT & FusedActiveGridGATv2 (5 edge feat)
# ---------------------------------------------------------------------------
def _active_neighborhood_features(X: np.ndarray, adj: np.ndarray, topo_id: np.ndarray, use_edge: bool) -> np.ndarray:
    n_ev, n_nodes, n_feat = X.shape
    nbr_max = np.full((n_ev, n_nodes, n_feat), np.nan, dtype=np.float32)
    nbr_mean = np.full((n_ev, n_nodes, n_feat), np.nan, dtype=np.float32)
    nbr_min = np.full((n_ev, n_nodes, n_feat), np.nan, dtype=np.float32)

    for t in range(adj.shape[0]):
        rows = np.flatnonzero(topo_id == t)
        if not len(rows):
            continue
        Xt = X[rows]
        for i in range(n_nodes):
            nbrs = np.flatnonzero(adj[t, i] > 0.5)
            if len(nbrs) == 1:
                v = Xt[:, nbrs[0], :]
                nbr_max[rows, i, :] = v
                nbr_mean[rows, i, :] = v
                nbr_min[rows, i, :] = v
            elif len(nbrs) > 1:
                sub = Xt[:, nbrs, :]
                fin = np.isfinite(sub)
                any_f = fin.any(axis=1)
                smax = np.where(fin, sub, -np.inf).max(axis=1)
                smin = np.where(fin, sub, np.inf).min(axis=1)
                cnt = fin.sum(axis=1)
                ssum = np.where(fin, sub, 0.0).sum(axis=1)
                nbr_max[rows, i, :] = np.where(any_f, smax, np.nan)
                nbr_min[rows, i, :] = np.where(any_f, smin, np.nan)
                nbr_mean[rows, i, :] = np.where(cnt > 0, ssum / np.maximum(cnt, 1), np.nan)

    diff_cols = list(range(am.N_CONT_DIFF)) + ([_A_PHIF_COL, _A_ALARM_COL] if use_edge else [])
    d_max = X[:, :, diff_cols] - nbr_max[:, :, diff_cols]
    d_min = X[:, :, diff_cols] - nbr_min[:, :, diff_cols]
    return np.concatenate([X, nbr_max, nbr_mean, nbr_min, d_max, d_min], axis=-1)


def _active_graph_summary(X: np.ndarray, use_edge: bool) -> np.ndarray:
    base = am._graph_summary_features(X)
    if not use_edge:
        return base
    # PLAN.md §2.2: graph-level NO_FAULT GBDT extended with max(p_hif), mean(p_hif), sum(hif_alarm).
    # base already contains max/mean/min/std for every channel; append explicit sum(hif_alarm) over observed nodes.
    alarm = X[:, :, _A_ALARM_COL]
    fin = np.isfinite(alarm)
    alarm_sum = np.where(fin.any(axis=1), np.where(fin, alarm, 0.0).sum(axis=1), np.nan)[:, None].astype(np.float32)
    return np.concatenate([base, alarm_sum], axis=-1)


class FusedActivePerNodeGBDT:
    def __init__(self, *, use_edge: bool, max_iter: int = 300, learning_rate: float = 0.05,
                 max_leaf_nodes: int = 63, sensor_dropout: float = 0.15, seed: int = 0):
        self.use_edge = bool(use_edge)
        self.params = dict(max_iter=max_iter, learning_rate=learning_rate,
                           max_leaf_nodes=max_leaf_nodes, sensor_dropout=sensor_dropout, seed=seed)
        self.node_clf = HistGradientBoostingClassifier(
            max_iter=max_iter, learning_rate=learning_rate, max_leaf_nodes=max_leaf_nodes, random_state=seed,
        )
        self.nf_clf = HistGradientBoostingClassifier(
            max_iter=max_iter, learning_rate=learning_rate, max_leaf_nodes=max_leaf_nodes, random_state=seed + 1000,
        )

    def fit(self, X: np.ndarray, y: np.ndarray, adj: np.ndarray, topo_id: np.ndarray) -> "FusedActivePerNodeGBDT":
        rng = np.random.default_rng(self.params["seed"])
        X_aug = _apply_dropout(X, rng, "active", self.use_edge, self.params["sensor_dropout"])
        n_nodes = X.shape[1]

        is_nf = (y == n_nodes).astype(np.int64)
        self.nf_clf.fit(_active_graph_summary(X_aug, self.use_edge), is_nf)

        fmask = y < n_nodes
        feat = _active_neighborhood_features(X_aug[fmask], adj, topo_id[fmask], self.use_edge)
        ef, nf, dim = feat.shape
        target = np.zeros((ef, nf), dtype=np.int64)
        target[np.arange(ef), y[fmask]] = 1
        self.node_clf.fit(feat.reshape(-1, dim), target.reshape(-1))
        return self

    def predict_proba(self, X: np.ndarray, adj: np.ndarray, topo_id: np.ndarray) -> np.ndarray:
        p_nf = self.nf_clf.predict_proba(_active_graph_summary(X, self.use_edge))[:, 1:2]
        feat = _active_neighborhood_features(X, adj, topo_id, self.use_edge)
        n_ev, n_nodes, dim = feat.shape
        node_logits = self.node_clf.decision_function(feat.reshape(-1, dim)).reshape(n_ev, n_nodes)
        p_zones = am._softmax_np(node_logits) * (1.0 - p_nf)
        return np.concatenate([p_zones, p_nf], axis=1).astype(np.float64)

    def predict(self, X: np.ndarray, adj: np.ndarray, topo_id: np.ndarray) -> np.ndarray:
        return self.predict_proba(X, adj, topo_id).argmax(axis=1).astype(np.int64)


def _finetune_active_gbdt(base: FusedActivePerNodeGBDT, X_few: np.ndarray, y_few: np.ndarray,
                          adj: np.ndarray, topo_few: np.ndarray, *, extra_iter: int = 50,
                          lr: float = 0.05, seed: int = 0) -> FusedActivePerNodeGBDT:
    clf = copy.deepcopy(base)
    rng = np.random.default_rng(seed)
    X_aug = _apply_dropout(X_few, rng, "active", clf.use_edge, clf.params["sensor_dropout"])
    n_nodes = X_few.shape[1]

    is_nf = (y_few == n_nodes).astype(np.int64)
    if len(np.unique(is_nf)) == 2:
        clf.nf_clf.set_params(warm_start=True, early_stopping=False, learning_rate=lr,
                              max_iter=int(clf.nf_clf.n_iter_) + extra_iter, random_state=seed)
        clf.nf_clf.fit(_active_graph_summary(X_aug, clf.use_edge), is_nf)

    fmask = y_few < n_nodes
    if fmask.any():
        feat = _active_neighborhood_features(X_aug[fmask], adj, topo_few[fmask], clf.use_edge)
        ef, nf, dim = feat.shape
        target = np.zeros((ef, nf), dtype=np.int64)
        target[np.arange(ef), y_few[fmask]] = 1
        clf.node_clf.set_params(warm_start=True, early_stopping=False, learning_rate=lr,
                                max_iter=int(clf.node_clf.n_iter_) + extra_iter, random_state=seed)
        clf.node_clf.fit(feat.reshape(-1, dim), target.reshape(-1))
    return clf


class FusedActiveGridGATv2(nn.Module):
    """Bidirectional edge-aware GATv2 supporting 26-feat/4-edge (60Hz_only) and 28-feat/5-edge (+diff_p_hif)."""

    def __init__(self, in_features: int, use_edge: bool, hidden: int = 64,
                 n_layers: int = 2, n_heads: int = 4, dropout: float = 0.1):
        super().__init__()
        self.in_features = in_features
        self.use_edge = bool(use_edge)
        self.n_elec = _n_elec("active", self.use_edge)
        self.edge_dim = 5 if self.use_edge else 4
        self.hidden = hidden
        self.n_layers = n_layers
        self.n_heads = n_heads
        self.dropout = dropout

        self.register_buffer("feat_mean", torch.zeros(in_features))
        self.register_buffer("feat_std", torch.ones(in_features))

        self.encoder = nn.Sequential(
            nn.Linear(in_features + 1, hidden),
            nn.LayerNorm(hidden),
            nn.GELU(),
            nn.Linear(hidden, hidden),
            nn.LayerNorm(hidden),
            nn.GELU(),
        )
        self.layers = nn.ModuleList([
            am.EdgeGATv2Layer(hidden, edge_dim=self.edge_dim, n_heads=n_heads, dropout=dropout)
            for _ in range(n_layers)
        ])
        self.node_head = nn.Sequential(
            nn.Linear(hidden, hidden // 2),
            nn.GELU(),
            nn.Linear(hidden // 2, 1),
        )
        self.nofault_head = nn.Sequential(
            nn.Linear(2 * hidden, hidden // 2),
            nn.GELU(),
            nn.Linear(hidden // 2, 1),
        )

    def set_normalizer(self, X_train: np.ndarray) -> None:
        flat = X_train.reshape(-1, self.in_features)
        mean = np.nanmean(flat, axis=0)
        std = np.nanstd(flat, axis=0)
        std = np.where(std < 1e-6, 1.0, std)
        self.feat_mean.copy_(torch.from_numpy(mean.astype(np.float32)))
        self.feat_std.copy_(torch.from_numpy(std.astype(np.float32)))

    def _edge_features(self, x_clean: torch.Tensor, obs_f: torch.Tensor, is_tie: torch.Tensor) -> torch.Tensor:
        obs_1 = obs_f.squeeze(-1)
        di_max = x_clean[:, :, _A_DI_COLS].max(dim=-1).values * obs_1
        v_raw = x_clean[:, :, _A_V_COLS]
        has_ph = x_clean[:, :, _A_HAS_COLS] > 0.5
        v_min = torch.where(has_ph, v_raw, torch.full_like(v_raw, 2.0)).min(dim=-1).values
        v_min = torch.where((obs_1 > 0.5) & has_ph.any(dim=-1), v_min, torch.ones_like(v_min))
        cos_pre = x_clean[:, :, _A_COS_PRE_COL] * obs_1

        same_dir = cos_pre.unsqueeze(2) * cos_pre.unsqueeze(1)
        diff_di = di_max.unsqueeze(2) - di_max.unsqueeze(1)
        diff_v = v_min.unsqueeze(2) - v_min.unsqueeze(1)
        if not self.use_edge:
            return torch.stack([is_tie, same_dir, diff_di, diff_v], dim=-1)

        # PLAN.md §2.2: 5th directed edge feature diff_p_hif = p_hif(u) - p_hif(v), zeroed when either endpoint is offline.
        p_hif = x_clean[:, :, _A_PHIF_COL] * obs_1
        both_obs = obs_1.unsqueeze(2) * obs_1.unsqueeze(1)
        diff_phif = (p_hif.unsqueeze(2) - p_hif.unsqueeze(1)) * both_obs
        return torch.stack([is_tie, same_dir, diff_di, diff_v, diff_phif], dim=-1)

    def forward(self, x: torch.Tensor, adj: torch.Tensor, is_tie: torch.Tensor) -> torch.Tensor:
        observed = torch.isfinite(x[:, :, :self.n_elec]).all(dim=-1, keepdim=True)
        obs_f = observed.to(x.dtype)
        x_clean = torch.nan_to_num(x, nan=0.0)
        edge_attr = self._edge_features(x_clean, obs_f, is_tie)

        x_norm = (x_clean - self.feat_mean) / self.feat_std
        elec = x_norm[:, :, :self.n_elec] * obs_f
        struct = x_norm[:, :, self.n_elec:]
        h = self.encoder(torch.cat([elec, struct, obs_f], dim=-1))

        for layer in self.layers:
            h = layer(h, adj, edge_attr)

        zone_logits = self.node_head(h).squeeze(-1)
        g_pool = torch.cat([h.mean(dim=1), h.max(dim=1).values], dim=-1)
        nf_logit = self.nofault_head(g_pool)
        return torch.cat([zone_logits, nf_logit], dim=-1)


def _train_active_gat(X_train: np.ndarray, y_train: np.ndarray, adj: np.ndarray, is_tie: np.ndarray,
                      topo_train: np.ndarray, *, use_edge: bool, hidden: int = 64, n_layers: int = 2,
                      n_heads: int = 4, dropout: float = 0.1, lr: float = 2e-3, weight_decay: float = 1e-4,
                      epochs: int = 45, batch_size: int = 256, sensor_dropout: float = 0.15, seed: int = 0,
                      device: torch.device | None = None) -> FusedActiveGridGATv2:
    dev = device or am.get_device(prefer_gpu=True)
    torch.manual_seed(seed)
    if dev.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    rng = np.random.default_rng(seed)

    net = FusedActiveGridGATv2(in_features=X_train.shape[-1], use_edge=use_edge,
                               hidden=hidden, n_layers=n_layers, n_heads=n_heads, dropout=dropout)
    net.set_normalizer(X_train)
    net.to(dev)
    n_elec = net.n_elec

    x_all = torch.from_numpy(X_train.astype(np.float32)).to(dev)
    y_all = torch.from_numpy(y_train.astype(np.int64)).to(dev)
    t_all = torch.from_numpy(topo_train.astype(np.int64)).to(dev)
    adj_all = torch.from_numpy(adj.astype(np.float32)).to(dev)
    tie_all = torch.from_numpy(is_tie.astype(np.float32)).to(dev)

    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs, eta_min=lr * 0.01)

    n_ev, n_nodes = X_train.shape[0], X_train.shape[1]
    net.train()
    for _ in range(epochs):
        perm = torch.from_numpy(rng.permutation(n_ev)).to(dev)
        for start in range(0, n_ev, batch_size):
            idx = perm[start:start + batch_size]
            xb, yb, tb = x_all[idx], y_all[idx], t_all[idx]
            if sensor_dropout > 0.0:
                xb = xb.clone()
                mask = torch.from_numpy(rng.random(len(idx)) < sensor_dropout).to(dev)
                if mask.any():
                    d_rows = torch.nonzero(mask, as_tuple=False).squeeze(-1)
                    d_nodes = torch.from_numpy(rng.integers(0, n_nodes, size=len(d_rows))).to(dev)
                    xb[d_rows, d_nodes, :n_elec] = float("nan")
            opt.zero_grad(set_to_none=True)
            loss = F.cross_entropy(net(xb, adj_all[tb], tie_all[tb]), yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 2.0)
            opt.step()
        sched.step()
    net.eval()
    return net


def _finetune_active_gat(base: FusedActiveGridGATv2, X_few: np.ndarray, y_few: np.ndarray,
                         adj: np.ndarray, is_tie: np.ndarray, topo_few: np.ndarray, *,
                         epochs: int = 25, lr: float = 5e-4, weight_decay: float = 1e-4,
                         batch_size: int = 64, sensor_dropout: float = 0.15, seed: int = 0,
                         device: torch.device | None = None) -> FusedActiveGridGATv2:
    dev = device or am.get_device(prefer_gpu=True)
    torch.manual_seed(seed)
    if dev.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    rng = np.random.default_rng(seed)

    net = copy.deepcopy(base).to(dev)
    n_elec = net.n_elec
    x_all = torch.from_numpy(X_few.astype(np.float32)).to(dev)
    y_all = torch.from_numpy(y_few.astype(np.int64)).to(dev)
    t_all = torch.from_numpy(topo_few.astype(np.int64)).to(dev)
    adj_all = torch.from_numpy(adj.astype(np.float32)).to(dev)
    tie_all = torch.from_numpy(is_tie.astype(np.float32)).to(dev)

    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs, eta_min=lr * 0.05)

    n_ev, n_nodes = X_few.shape[0], X_few.shape[1]
    net.train()
    for _ in range(epochs):
        perm = torch.from_numpy(rng.permutation(n_ev)).to(dev)
        for start in range(0, n_ev, batch_size):
            idx = perm[start:start + batch_size]
            xb, yb, tb = x_all[idx], y_all[idx], t_all[idx]
            if sensor_dropout > 0.0:
                xb = xb.clone()
                mask = torch.from_numpy(rng.random(len(idx)) < sensor_dropout).to(dev)
                if mask.any():
                    d_rows = torch.nonzero(mask, as_tuple=False).squeeze(-1)
                    d_nodes = torch.from_numpy(rng.integers(0, n_nodes, size=len(d_rows))).to(dev)
                    xb[d_rows, d_nodes, :n_elec] = float("nan")
            opt.zero_grad(set_to_none=True)
            loss = F.cross_entropy(net(xb, adj_all[tb], tie_all[tb]), yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 2.0)
            opt.step()
        sched.step()
    net.eval()
    return net


@torch.no_grad()
def _predict_proba_gat(net: FusedActiveGridGATv2, X: np.ndarray, adj: np.ndarray, is_tie: np.ndarray,
                       topo_id: np.ndarray, batch_size: int = 1024,
                       device: torch.device | None = None) -> np.ndarray:
    dev = device or next(net.parameters()).device
    net.eval()
    adj_t = torch.from_numpy(adj.astype(np.float32)).to(dev)
    tie_t = torch.from_numpy(is_tie.astype(np.float32)).to(dev)
    out = []
    for start in range(0, len(X), batch_size):
        xb = torch.from_numpy(X[start:start + batch_size].astype(np.float32)).to(dev)
        tb = torch.from_numpy(topo_id[start:start + batch_size].astype(np.int64)).to(dev)
        out.append(F.softmax(net(xb, adj_t[tb], tie_t[tb]), dim=-1).cpu().numpy())
    return np.concatenate(out, axis=0).astype(np.float64)


# ---------------------------------------------------------------------------
# Metrics helpers (full range, 200-400 ohm, 1-10 kohm, 5 surfaces, 7 disturbances)
# ---------------------------------------------------------------------------
def _safe_mean(mask: np.ndarray, values: np.ndarray) -> float | None:
    return round(float(values[mask].mean()), 4) if np.any(mask) else None


def _eval_passive(
    ds: hf.PassiveFusionDataset,
    pred: np.ndarray,
    *,
    fold_indices: list[np.ndarray] | None = None,
    missing_preds: dict[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    corr = pred == ds.y
    slg = ds.ftype == "SLG"
    slg_200_400 = slg & np.isin(ds.r, [200.0, 400.0])
    slg_low_r = slg & (ds.r <= 100.0)
    phase_m = np.isin(ds.ftype, ["3PH", "LL", "LLG"])
    arc_m = ds.is_arcing

    by_ftype = {ft: _safe_mean(ds.ftype == ft, corr) for ft in sorted(np.unique(ds.ftype))}
    slg_by_r = {str(float(rv)): _safe_mean(slg & (ds.r == rv), corr) for rv in sorted(np.unique(ds.r[slg]))}
    by_zone = {d: _safe_mean(ds.y == i, corr) for i, d in enumerate(ds.devices)}
    by_surface = {s: _safe_mean(arc_m & (ds.arc_surface == s), corr) for s in hf.SURFACE_NAMES}

    out: dict[str, Any] = {
        "accuracy": float(corr.mean()),
        "slg_200_400_accuracy": _safe_mean(slg_200_400, corr),
        "slg_low_r_0_100_accuracy": _safe_mean(slg_low_r, corr),
        "phase_faults_accuracy": _safe_mean(phase_m, corr),
        "arcing_accuracy": _safe_mean(arc_m, corr),
        "by_fault_type": by_ftype,
        "slg_by_resistance": slg_by_r,
        "by_arc_surface": by_surface,
        "by_zone": by_zone,
    }
    if fold_indices is not None:
        faccs = [float(corr[idx].mean()) for idx in fold_indices]
        out["fold_accuracies"] = [round(a, 4) for a in faccs]
        out["fold_std"] = round(float(np.std(faccs)), 4)
    if missing_preds is not None:
        per_dev = {d: float((pm == ds.y).mean()) for d, pm in missing_preds.items()}
        out["missing_sensor_accuracy"] = per_dev
        out["missing_sensor_mean"] = float(np.mean(list(per_dev.values())))
        out["missing_sensor_min"] = float(np.min(list(per_dev.values())))
        if slg_200_400.any():
            out["missing_sensor_slg_200_400_mean"] = round(float(np.mean([
                float((pm[slg_200_400] == ds.y[slg_200_400]).mean()) for pm in missing_preds.values()
            ])), 4)
        else:
            out["missing_sensor_slg_200_400_mean"] = None
    return out


def _eval_active(
    ds: hf.ActiveFusionDataset,
    pred: np.ndarray,
    *,
    fold_indices: list[np.ndarray] | None = None,
    missing_preds: dict[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    nf = ds.nofault_class
    corr = pred == ds.y
    is_fault = ds.y < nf
    is_nf = ds.y == nf
    slg = ds.ftype == "SLG"
    slg_200_400 = slg & np.isin(ds.r, [200.0, 400.0])
    slg_1k_10k = slg & (ds.r >= 1000.0)
    slg_low_r = slg & (ds.r <= 100.0)
    phase_m = np.isin(ds.ftype, ["3PH", "LL", "LLG"])
    arc_m = ds.is_arcing

    fpr_nf = float((pred[is_nf] != nf).mean()) if is_nf.any() else 0.0
    det_recall = float((pred[is_fault] != nf).mean()) if is_fault.any() else 0.0
    fault_zone_acc = float(corr[is_fault].mean()) if is_fault.any() else 0.0

    by_topo = {tname: _safe_mean(ds.topo_id == ti, corr) for ti, tname in enumerate(ds.topo_names)}
    by_topo_fault = {tname: _safe_mean((ds.topo_id == ti) & is_fault, corr) for ti, tname in enumerate(ds.topo_names)}
    by_kind = {k: _safe_mean(ds.event_kind == k, corr) for k in sorted(np.unique(ds.event_kind))}
    by_ftype = {ft: _safe_mean(ds.ftype == ft, corr) for ft in sorted(np.unique(ds.ftype))}
    slg_by_r = {str(float(rv)): _safe_mean(slg & (ds.r == rv), corr) for rv in sorted(np.unique(ds.r[slg]))}
    by_surface = {s: _safe_mean(arc_m & (ds.arc_surface == s), corr) for s in hf.SURFACE_NAMES}
    nf_fpr_by_dist = {
        dist: _safe_mean(is_nf & (ds.edge_disturbance == dist), pred != nf)
        for dist in he.DISTURBANCES
    }
    der_bands = {
        "low_0_15pct": _safe_mean(is_fault & (ds.der_pct < 0.15), corr),
        "mid_15_30pct": _safe_mean(is_fault & (ds.der_pct >= 0.15) & (ds.der_pct < 0.30), corr),
        "high_30_50pct": _safe_mean(is_fault & (ds.der_pct >= 0.30), corr),
    }

    reconf_mask = ds.topo_id > 0
    loop_mask = ds.topo_is_looped[ds.topo_id]

    out: dict[str, Any] = {
        "overall_accuracy": float(corr.mean()),
        "fault_zone_accuracy": fault_zone_acc,
        "fault_detection_recall": det_recall,
        "nofault_fpr": fpr_nf,
        "reconfig_and_loop_accuracy": float(corr[reconf_mask].mean()) if reconf_mask.any() else None,
        "looped_accuracy": float(corr[loop_mask].mean()) if loop_mask.any() else None,
        "slg_200_400_accuracy": _safe_mean(slg_200_400, corr),
        "slg_hif_1k_10k_accuracy": _safe_mean(slg_1k_10k, corr),
        "slg_low_r_0_100_accuracy": _safe_mean(slg_low_r, corr),
        "phase_faults_accuracy": _safe_mean(phase_m, corr),
        "arcing_accuracy": _safe_mean(arc_m, corr),
        "by_topology": by_topo,
        "by_topology_fault_only": by_topo_fault,
        "by_event_kind": by_kind,
        "by_fault_type": by_ftype,
        "slg_by_resistance": slg_by_r,
        "by_arc_surface": by_surface,
        "nofault_fpr_by_disturbance": nf_fpr_by_dist,
        "fault_acc_by_der_band": der_bands,
    }
    if fold_indices is not None:
        faccs = [float(corr[idx].mean()) for idx in fold_indices]
        out["fold_accuracies"] = [round(a, 4) for a in faccs]
        out["fold_std"] = round(float(np.std(faccs)), 4)
    if missing_preds is not None:
        per_dev = {d: float((pm == ds.y).mean()) for d, pm in missing_preds.items()}
        out["missing_sensor_accuracy"] = per_dev
        out["missing_sensor_mean"] = float(np.mean(list(per_dev.values())))
        out["missing_sensor_min"] = float(np.min(list(per_dev.values())))
        if slg_200_400.any():
            out["missing_sensor_slg_200_400_mean"] = round(float(np.mean([
                float((pm[slg_200_400] == ds.y[slg_200_400]).mean()) for pm in missing_preds.values()
            ])), 4)
        else:
            out["missing_sensor_slg_200_400_mean"] = None
    return out


# ---------------------------------------------------------------------------
# Passive CV & 34-bus Transfer Runners
# ---------------------------------------------------------------------------
def _run_passive_123(ds123: hf.PassiveFusionDataset, *, seed: int, quick: bool,
                     device: torch.device) -> tuple[dict[str, Any], dict[str, Any]]:
    splits = list(GroupKFold(n_splits=tm.N_FOLDS).split(ds123.X, ds123.y, ds123.bus))
    folds = [te for _, te in splits]

    # 60 Hz FPI baseline
    X60 = ds123.X_60hz
    fpi_pred = tm.fpi_predict(X60, ds123.parent)
    fpi_miss = {d: tm.fpi_predict(tm.blank_sensor(X60, i), ds123.parent) for i, d in enumerate(ds123.devices)}
    fpi_res = _eval_passive(ds123, fpi_pred, fold_indices=folds, missing_preds=fpi_miss)
    fpi_res["no_device_flagged"] = float((fpi_pred < 0).mean())

    gbdt_kw = dict(FROZEN_PASSIVE_GBDT)
    gnn_kw = dict(FROZEN_PASSIVE_GNN)
    if quick:
        gbdt_kw["max_iter"] = 40
        gnn_kw["epochs"] = 6

    ablations: dict[str, Any] = {}
    frozen_models: dict[str, Any] = {}

    for abl_name, use_edge in (("60Hz_only", False), ("60Hz_plus_edge", True)):
        X_in = ds123.X if use_edge else X60
        print(f"  [passive 123] ablation={abl_name} (features={X_in.shape[-1]})")

        # PerNodeGBDT 5-fold CV
        t1 = time.time()
        oof_g = np.empty(len(ds123.y), dtype=np.int64)
        miss_g = {d: np.empty(len(ds123.y), dtype=np.int64) for d in ds123.devices}
        for fi, (tr, te) in enumerate(splits):
            clf = FusedPerNodeGBDT(use_edge=use_edge, seed=seed + fi, **gbdt_kw).fit(
                X_in[tr], ds123.y[tr], ds123.parent
            )
            oof_g[te] = clf.predict(X_in[te], ds123.parent)
            for i, d in enumerate(ds123.devices):
                miss_g[d][te] = clf.predict(_blank_sensor(X_in[te], i, "passive", use_edge), ds123.parent)
        res_g = _eval_passive(ds123, oof_g, fold_indices=folds, missing_preds=miss_g)
        res_g["params"] = gbdt_kw
        res_g["runtime_s"] = round(time.time() - t1, 1)
        print(f"    PerNodeGBDT ({abl_name}): acc={res_g['accuracy']:.4f}, SLG 200-400={res_g['slg_200_400_accuracy']}, "
              f"SLG 400={res_g['slg_by_resistance'].get('400.0')}, miss={res_g['missing_sensor_mean']:.4f} [{res_g['runtime_s']}s]")

        # ZoneTreeGNN 5-fold CV
        t2 = time.time()
        oof_n = np.empty(len(ds123.y), dtype=np.int64)
        miss_n = {d: np.empty(len(ds123.y), dtype=np.int64) for d in ds123.devices}
        for fi, (tr, te) in enumerate(splits):
            net = _train_passive_gnn(
                X_in[tr], ds123.y[tr], ds123.parent, use_edge=use_edge, seed=seed + fi, device=device, **gnn_kw
            )
            oof_n[te] = _predict_passive_gnn(net, X_in[te], ds123.parent, device=device)
            for i, d in enumerate(ds123.devices):
                miss_n[d][te] = _predict_passive_gnn(
                    net, _blank_sensor(X_in[te], i, "passive", use_edge), ds123.parent, device=device
                )
        res_n = _eval_passive(ds123, oof_n, fold_indices=folds, missing_preds=miss_n)
        res_n["params"] = gnn_kw
        res_n["runtime_s"] = round(time.time() - t2, 1)
        print(f"    ZoneTreeGNN ({abl_name}): acc={res_n['accuracy']:.4f}, SLG 200-400={res_n['slg_200_400_accuracy']}, "
              f"SLG 400={res_n['slg_by_resistance'].get('400.0')}, miss={res_n['missing_sensor_mean']:.4f} [{res_n['runtime_s']}s]")

        # Final frozen models trained on all 123-bus events for 34-bus transfer
        fin_g = FusedPerNodeGBDT(use_edge=use_edge, seed=seed, **gbdt_kw).fit(X_in, ds123.y, ds123.parent)
        fin_n = _train_passive_gnn(X_in, ds123.y, ds123.parent, use_edge=use_edge, seed=seed, device=device, **gnn_kw)
        res_n["parameter_count"] = int(sum(p.numel() for p in fin_n.parameters()))

        ablations[abl_name] = {"per_node_gbdt": res_g, "zone_tree_gnn": res_n}
        frozen_models[abl_name] = {"per_node_gbdt": fin_g, "zone_tree_gnn": fin_n}

    out = {
        "phase": "hif_fusion_passive_ieee123",
        "simulation_only": True,
        "feeder": "ieee123",
        "events": int(len(ds123.y)),
        "buses": int(len(np.unique(ds123.bus))),
        "arcing_events": int(ds123.is_arcing.sum()),
        "devices": ds123.devices,
        "features_60hz": list(hf.PASSIVE_FUSED_FEATURES[:17]) + list(hf.PASSIVE_FUSED_FEATURES[19:]),
        "features_fused": ds123.features,
        "validation": {"method": "GroupKFold", "group_by": "bus", "n_splits": tm.N_FOLDS},
        "fpi": fpi_res,
        "ablations": ablations,
    }
    return out, frozen_models


def _few_shot_passive(ds34: hf.PassiveFusionDataset, frac: float, *, frozen_models: dict[str, Any],
                      n_repeats: int, seed: int, quick: bool, device: torch.device) -> dict[str, Any]:
    buses = np.array(sorted(np.unique(ds34.bus)))
    n_tr_b = max(1, int(round(frac * len(buses))))
    ft_epochs = 5 if quick else 25
    ft_iter = 15 if quick else 50

    out_abl: dict[str, Any] = {}
    for abl_name, use_edge in (("60Hz_only", False), ("60Hz_plus_edge", True)):
        X_in = ds34.X if use_edge else ds34.X_60hz
        m_res: dict[str, Any] = {}
        for mname in ("per_node_gbdt", "zone_tree_gnn"):
            rng = np.random.default_rng(seed)
            split_accs, all_corr, all_ftype, all_r = [], [], [], []
            miss_hits = {d: 0 for d in ds34.devices}
            total_eval = 0
            for rep in range(n_repeats):
                chosen = set(rng.choice(buses, size=n_tr_b, replace=False).tolist())
                tr_m = np.array([b in chosen for b in ds34.bus])
                te_m = ~tr_m
                assert set(ds34.bus[tr_m]).isdisjoint(set(ds34.bus[te_m]))
                if mname == "per_node_gbdt":
                    m = _finetune_passive_gbdt(frozen_models[abl_name]["per_node_gbdt"],
                                               X_in[tr_m], ds34.y[tr_m], ds34.parent,
                                               extra_iter=ft_iter, seed=seed + rep)
                    pred = m.predict(X_in[te_m], ds34.parent)
                    for i, d in enumerate(ds34.devices):
                        pm = m.predict(_blank_sensor(X_in[te_m], i, "passive", use_edge), ds34.parent)
                        miss_hits[d] += int((pm == ds34.y[te_m]).sum())
                else:
                    m = _finetune_passive_gnn(frozen_models[abl_name]["zone_tree_gnn"],
                                              X_in[tr_m], ds34.y[tr_m], ds34.parent,
                                              epochs=ft_epochs, seed=seed + rep, device=device)
                    pred = _predict_passive_gnn(m, X_in[te_m], ds34.parent, device=device)
                    for i, d in enumerate(ds34.devices):
                        pm = _predict_passive_gnn(m, _blank_sensor(X_in[te_m], i, "passive", use_edge),
                                                  ds34.parent, device=device)
                        miss_hits[d] += int((pm == ds34.y[te_m]).sum())
                corr = pred == ds34.y[te_m]
                split_accs.append(float(corr.mean()))
                all_corr.append(corr)
                all_ftype.append(ds34.ftype[te_m])
                all_r.append(ds34.r[te_m])
                total_eval += int(te_m.sum())

            c_all = np.concatenate(all_corr)
            ft_all = np.concatenate(all_ftype)
            r_all = np.concatenate(all_r)
            slg = ft_all == "SLG"
            per_dev = {d: float(h / total_eval) for d, h in miss_hits.items()}
            m_res[mname] = {
                "accuracy_mean": round(float(np.mean(split_accs)), 4),
                "accuracy_std": round(float(np.std(split_accs)), 4),
                "slg_200_400_accuracy": _safe_mean(slg & np.isin(r_all, [200.0, 400.0]), c_all),
                "missing_sensor_mean": round(float(np.mean(list(per_dev.values()))), 4),
            }
        out_abl[abl_name] = m_res
    return {
        "fraction": frac,
        "train_buses": n_tr_b,
        "test_buses": int(len(buses) - n_tr_b),
        "n_repeats": n_repeats,
        "ablations": out_abl,
    }


def _run_passive_34(ds34: hf.PassiveFusionDataset, frozen_models: dict[str, Any], *,
                    seed: int, quick: bool, device: torch.device) -> dict[str, Any]:
    X60 = ds34.X_60hz
    fpi_pred = tm.fpi_predict(X60, ds34.parent)
    fpi_miss = {d: tm.fpi_predict(tm.blank_sensor(X60, i), ds34.parent) for i, d in enumerate(ds34.devices)}
    fpi_res = _eval_passive(ds34, fpi_pred, missing_preds=fpi_miss)
    fpi_res["no_device_flagged"] = float((fpi_pred < 0).mean())

    zs_abl: dict[str, Any] = {}
    for abl_name, use_edge in (("60Hz_only", False), ("60Hz_plus_edge", True)):
        X_in = ds34.X if use_edge else X60
        fg = frozen_models[abl_name]["per_node_gbdt"]
        fn = frozen_models[abl_name]["zone_tree_gnn"]

        pg = fg.predict(X_in, ds34.parent)
        mg = {d: fg.predict(_blank_sensor(X_in, i, "passive", use_edge), ds34.parent)
              for i, d in enumerate(ds34.devices)}
        rg = _eval_passive(ds34, pg, missing_preds=mg)

        pn = _predict_passive_gnn(fn, X_in, ds34.parent, device=device)
        mn = {d: _predict_passive_gnn(fn, _blank_sensor(X_in, i, "passive", use_edge), ds34.parent, device=device)
              for i, d in enumerate(ds34.devices)}
        rn = _eval_passive(ds34, pn, missing_preds=mn)

        print(f"  [passive 34 zero-shot {abl_name}] GBDT acc={rg['accuracy']:.4f} (miss={rg['missing_sensor_mean']:.4f}) | "
              f"GNN acc={rn['accuracy']:.4f} (miss={rn['missing_sensor_mean']:.4f})")
        zs_abl[abl_name] = {"per_node_gbdt": rg, "zone_tree_gnn": rn}

    n_rep = 2 if quick else 10
    fs5 = _few_shot_passive(ds34, 0.05, frozen_models=frozen_models, n_repeats=n_rep, seed=seed, quick=quick, device=device)
    fs20 = _few_shot_passive(ds34, 0.20, frozen_models=frozen_models, n_repeats=n_rep, seed=seed + 100, quick=quick, device=device)

    return {
        "phase": "hif_fusion_passive_ieee34",
        "simulation_only": True,
        "train_feeder": "ieee123",
        "test_feeder": "ieee34",
        "events": int(len(ds34.y)),
        "buses": int(len(np.unique(ds34.bus))),
        "arcing_events": int(ds34.is_arcing.sum()),
        "devices": ds34.devices,
        "fpi": fpi_res,
        "zero_shot": zs_abl,
        "few_shot": {"pct_5": fs5, "pct_20": fs20},
    }


# ---------------------------------------------------------------------------
# Active CV & 34-bus Transfer Runners
# ---------------------------------------------------------------------------
def _run_active_123(ds123: hf.ActiveFusionDataset, *, seed: int, quick: bool,
                    device: torch.device) -> tuple[dict[str, Any], dict[str, Any], dict[str, np.ndarray], np.ndarray]:
    splits = list(GroupKFold(n_splits=am.N_FOLDS).split(ds123.X, ds123.y, ds123.bus))
    folds = [te for _, te in splits]
    fold_id = np.full(len(ds123.y), -1, dtype=np.int64)
    for fi, (_, te) in enumerate(splits):
        fold_id[te] = fi

    X60 = ds123.X_60hz
    fpi_pred = am.active_fpi_predict(X60, ds123.adj, ds123.topo_id)
    fpi_miss = {d: am.active_fpi_predict(am.blank_active_sensor(X60, i), ds123.adj, ds123.topo_id)
                for i, d in enumerate(ds123.devices)}
    fpi_res = _eval_active(ds123, fpi_pred, fold_indices=folds, missing_preds=fpi_miss)

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
        print(f"  [active 123] ablation={abl_name} (node_feat={X_in.shape[-1]}, edge_feat={5 if use_edge else 4})")

        # ActivePerNodeGBDT 5-fold CV
        t1 = time.time()
        oof_g = np.zeros((len(ds123.y), ds123.n_nodes + 1), dtype=np.float64)
        miss_g = {d: np.empty(len(ds123.y), dtype=np.int64) for d in ds123.devices}
        for fi, (tr, te) in enumerate(splits):
            clf = FusedActivePerNodeGBDT(use_edge=use_edge, seed=seed + fi, **gbdt_kw).fit(
                X_in[tr], ds123.y[tr], ds123.adj, ds123.topo_id[tr]
            )
            oof_g[te] = clf.predict_proba(X_in[te], ds123.adj, ds123.topo_id[te])
            for i, d in enumerate(ds123.devices):
                miss_g[d][te] = clf.predict(_blank_sensor(X_in[te], i, "active", use_edge), ds123.adj, ds123.topo_id[te])
        res_g = _eval_active(ds123, oof_g.argmax(axis=1), fold_indices=folds, missing_preds=miss_g)
        res_g["params"] = gbdt_kw
        res_g["runtime_s"] = round(time.time() - t1, 1)
        print(f"    ActiveGBDT ({abl_name}): acc={res_g['overall_accuracy']:.4f}, SLG 200-400={res_g['slg_200_400_accuracy']}, "
              f"SLG 400={res_g['slg_by_resistance'].get('400.0')}, FPR={res_g['nofault_fpr']:.4f}, "
              f"miss={res_g['missing_sensor_mean']:.4f} [{res_g['runtime_s']}s]")

        # ActiveGridGATv2 5-fold CV
        t2 = time.time()
        oof_a = np.zeros((len(ds123.y), ds123.n_nodes + 1), dtype=np.float64)
        miss_a = {d: np.empty(len(ds123.y), dtype=np.int64) for d in ds123.devices}
        for fi, (tr, te) in enumerate(splits):
            net = _train_active_gat(
                X_in[tr], ds123.y[tr], ds123.adj, ds123.is_tie, ds123.topo_id[tr],
                use_edge=use_edge, seed=seed + fi, device=device, **gat_kw
            )
            oof_a[te] = _predict_proba_gat(net, X_in[te], ds123.adj, ds123.is_tie, ds123.topo_id[te], device=device)
            for i, d in enumerate(ds123.devices):
                miss_a[d][te] = _predict_proba_gat(
                    net, _blank_sensor(X_in[te], i, "active", use_edge),
                    ds123.adj, ds123.is_tie, ds123.topo_id[te], device=device
                ).argmax(axis=1)
        res_a = _eval_active(ds123, oof_a.argmax(axis=1), fold_indices=folds, missing_preds=miss_a)
        res_a["params"] = gat_kw
        res_a["edge_features"] = 5 if use_edge else 4
        res_a["runtime_s"] = round(time.time() - t2, 1)
        print(f"    ActiveGATv2({abl_name}): acc={res_a['overall_accuracy']:.4f}, SLG 200-400={res_a['slg_200_400_accuracy']}, "
              f"SLG 400={res_a['slg_by_resistance'].get('400.0')}, FPR={res_a['nofault_fpr']:.4f}, "
              f"miss={res_a['missing_sensor_mean']:.4f} [{res_a['runtime_s']}s]")

        # Final frozen models on all 123-bus active events
        fin_g = FusedActivePerNodeGBDT(use_edge=use_edge, seed=seed, **gbdt_kw).fit(
            X_in, ds123.y, ds123.adj, ds123.topo_id
        )
        fin_a = _train_active_gat(
            X_in, ds123.y, ds123.adj, ds123.is_tie, ds123.topo_id,
            use_edge=use_edge, seed=seed, device=device, **gat_kw
        )
        res_a["parameter_count"] = int(sum(p.numel() for p in fin_a.parameters()))

        ablations[abl_name] = {"active_per_node_gbdt": res_g, "active_grid_gatv2": res_a}
        frozen_models[abl_name] = {"active_per_node_gbdt": fin_g, "active_grid_gatv2": fin_a}
        oof_store[f"{abl_name}__gbdt"] = oof_g
        oof_store[f"{abl_name}__gatv2"] = oof_a

    out = {
        "phase": "hif_fusion_active_ieee123",
        "simulation_only": True,
        "feeder": "ieee123",
        "events": int(len(ds123.y)),
        "fault_events": int((ds123.y < ds123.nofault_class).sum()),
        "nofault_events": int((ds123.y == ds123.nofault_class).sum()),
        "arcing_events": int(ds123.is_arcing.sum()),
        "topologies": ds123.topo_names,
        "devices": ds123.devices,
        "features_60hz": list(ag.ACTIVE_FEATURES),
        "features_fused": ds123.features,
        "validation": {"method": "GroupKFold", "group_by": "bus", "n_splits": am.N_FOLDS},
        "fpi": fpi_res,
        "ablations": ablations,
    }
    return out, frozen_models, oof_store, fold_id


def _few_shot_active(ds34: hf.ActiveFusionDataset, frac: float, *, frozen_models: dict[str, Any],
                     n_repeats: int, seed: int, quick: bool, device: torch.device) -> dict[str, Any]:
    fault_buses = np.array(sorted(np.unique(ds34.bus[ds34.y < ds34.nofault_class])))
    nf_idx_all = np.flatnonzero(ds34.y == ds34.nofault_class)
    n_tr_b = max(1, int(round(frac * len(fault_buses))))
    n_tr_nf = max(10, int(round(frac * len(nf_idx_all))))
    ft_epochs = 5 if quick else 25
    ft_iter = 15 if quick else 50

    out_abl: dict[str, Any] = {}
    for abl_name, use_edge in (("60Hz_only", False), ("60Hz_plus_edge", True)):
        X_in = ds34.X if use_edge else ds34.X_60hz
        m_res: dict[str, Any] = {}
        for mname in ("active_per_node_gbdt", "active_grid_gatv2"):
            rng = np.random.default_rng(seed)
            split_accs, split_fprs, split_hifs, miss_means = [], [], [], []
            for rep in range(n_repeats):
                cb = set(rng.choice(fault_buses, size=n_tr_b, replace=False).tolist())
                cnf = set(rng.choice(nf_idx_all, size=n_tr_nf, replace=False).tolist())
                tr_m = np.array([(b in cb) or (i in cnf) for i, b in enumerate(ds34.bus)])
                te_m = ~tr_m
                assert set(ds34.bus[tr_m]).isdisjoint(set(ds34.bus[te_m]))

                if mname == "active_per_node_gbdt":
                    m = _finetune_active_gbdt(frozen_models[abl_name]["active_per_node_gbdt"],
                                              X_in[tr_m], ds34.y[tr_m], ds34.adj, ds34.topo_id[tr_m],
                                              extra_iter=ft_iter, seed=seed + rep)
                    pred = m.predict(X_in[te_m], ds34.adj, ds34.topo_id[te_m])
                    mh = [float((m.predict(_blank_sensor(X_in[te_m], i, "active", use_edge),
                                           ds34.adj, ds34.topo_id[te_m]) == ds34.y[te_m]).mean())
                          for i in range(ds34.n_nodes)]
                else:
                    m = _finetune_active_gat(frozen_models[abl_name]["active_grid_gatv2"],
                                             X_in[tr_m], ds34.y[tr_m], ds34.adj, ds34.is_tie, ds34.topo_id[tr_m],
                                             epochs=ft_epochs, seed=seed + rep, device=device)
                    pred = _predict_proba_gat(m, X_in[te_m], ds34.adj, ds34.is_tie,
                                              ds34.topo_id[te_m], device=device).argmax(axis=1)
                    mh = [float((_predict_proba_gat(m, _blank_sensor(X_in[te_m], i, "active", use_edge),
                                                    ds34.adj, ds34.is_tie, ds34.topo_id[te_m],
                                                    device=device).argmax(axis=1) == ds34.y[te_m]).mean())
                          for i in range(ds34.n_nodes)]
                y_te = ds34.y[te_m]
                split_accs.append(float((pred == y_te).mean()))
                is_nf_te = y_te == ds34.nofault_class
                split_fprs.append(float((pred[is_nf_te] != ds34.nofault_class).mean()) if is_nf_te.any() else 0.0)
                hif_te = (ds34.ftype[te_m] == "SLG") & (ds34.r[te_m] >= 1000.0)
                if hif_te.any():
                    split_hifs.append(float((pred[hif_te] == y_te[hif_te]).mean()))
                miss_means.append(float(np.mean(mh)))

            m_res[mname] = {
                "overall_accuracy_mean": round(float(np.mean(split_accs)), 4),
                "overall_accuracy_std": round(float(np.std(split_accs)), 4),
                "slg_hif_1k_10k_mean": round(float(np.mean(split_hifs)), 4) if split_hifs else None,
                "nofault_fpr_mean": round(float(np.mean(split_fprs)), 4),
                "missing_sensor_mean": round(float(np.mean(miss_means)), 4),
            }
        out_abl[abl_name] = m_res
    return {
        "fraction": frac,
        "train_fault_buses": n_tr_b,
        "test_fault_buses": int(len(fault_buses) - n_tr_b),
        "train_nofault_events": n_tr_nf,
        "n_repeats": n_repeats,
        "ablations": out_abl,
    }


def _run_active_34(ds34: hf.ActiveFusionDataset, frozen_models: dict[str, Any], *,
                   seed: int, quick: bool, device: torch.device) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    X60 = ds34.X_60hz
    fpi_pred = am.active_fpi_predict(X60, ds34.adj, ds34.topo_id)
    fpi_miss = {d: am.active_fpi_predict(am.blank_active_sensor(X60, i), ds34.adj, ds34.topo_id)
                for i, d in enumerate(ds34.devices)}
    fpi_res = _eval_active(ds34, fpi_pred, missing_preds=fpi_miss)

    zs_abl: dict[str, Any] = {}
    zs_probs: dict[str, np.ndarray] = {}

    for abl_name, use_edge in (("60Hz_only", False), ("60Hz_plus_edge", True)):
        X_in = ds34.X if use_edge else X60
        fg = frozen_models[abl_name]["active_per_node_gbdt"]
        fa = frozen_models[abl_name]["active_grid_gatv2"]

        pg = fg.predict_proba(X_in, ds34.adj, ds34.topo_id)
        mg = {d: fg.predict(_blank_sensor(X_in, i, "active", use_edge), ds34.adj, ds34.topo_id)
              for i, d in enumerate(ds34.devices)}
        rg = _eval_active(ds34, pg.argmax(axis=1), missing_preds=mg)

        pa = _predict_proba_gat(fa, X_in, ds34.adj, ds34.is_tie, ds34.topo_id, device=device)
        ma = {d: _predict_proba_gat(fa, _blank_sensor(X_in, i, "active", use_edge),
                                    ds34.adj, ds34.is_tie, ds34.topo_id, device=device).argmax(axis=1)
              for i, d in enumerate(ds34.devices)}
        ra = _eval_active(ds34, pa.argmax(axis=1), missing_preds=ma)

        print(f"  [active 34 zero-shot {abl_name}] GBDT acc={rg['overall_accuracy']:.4f} "
              f"(1-10k={rg['slg_hif_1k_10k_accuracy']}, FPR={rg['nofault_fpr']:.4f}, miss={rg['missing_sensor_mean']:.4f}) | "
              f"GATv2 acc={ra['overall_accuracy']:.4f} "
              f"(1-10k={ra['slg_hif_1k_10k_accuracy']}, FPR={ra['nofault_fpr']:.4f}, miss={ra['missing_sensor_mean']:.4f})")

        zs_abl[abl_name] = {"active_per_node_gbdt": rg, "active_grid_gatv2": ra}
        zs_probs[f"{abl_name}__gbdt"] = pg
        zs_probs[f"{abl_name}__gatv2"] = pa

    n_rep = 2 if quick else 5
    fs5 = _few_shot_active(ds34, 0.05, frozen_models=frozen_models, n_repeats=n_rep, seed=seed, quick=quick, device=device)
    fs20 = _few_shot_active(ds34, 0.20, frozen_models=frozen_models, n_repeats=n_rep, seed=seed + 100, quick=quick, device=device)

    out = {
        "phase": "hif_fusion_active_ieee34",
        "simulation_only": True,
        "train_feeder": "ieee123",
        "test_feeder": "ieee34",
        "events": int(len(ds34.y)),
        "fault_events": int((ds34.y < ds34.nofault_class).sum()),
        "nofault_events": int((ds34.y == ds34.nofault_class).sum()),
        "arcing_events": int(ds34.is_arcing.sum()),
        "topologies": ds34.topo_names,
        "devices": ds34.devices,
        "fpi": fpi_res,
        "zero_shot": zs_abl,
        "few_shot": {"pct_5": fs5, "pct_20": fs20},
    }
    return out, zs_probs


# ---------------------------------------------------------------------------
# Split Conformal Prediction (`aps_rand` primary + `lac`, PLAN.md §2.2 & H4)
# ---------------------------------------------------------------------------
def _u(n: int, salt: int) -> np.ndarray:
    return np.random.default_rng(U_SEED + salt).uniform(0.0, 1.0, size=n)


def _cross_conformal_123(probs: np.ndarray, y: np.ndarray, fold_id: np.ndarray, nf: int,
                         method: str, alpha: float) -> tuple[dict[str, Any], np.ndarray]:
    u = _u(len(y), 0)
    sets = np.zeros_like(probs, dtype=bool)
    q_hats = []
    for f in sorted(set(fold_id.tolist())):
        te = fold_id == f
        tr = ~te
        q = am.conformal_quantile(am.conformal_scores(probs[tr], y[tr], method, u[tr]), alpha)
        q_hats.append(q)
        sets[te] = am.conformal_sets(probs[te], q, method, u[te])
    rep = am.conformal_report(probs, y, sets, nf)
    rep["q_hat_mean"] = round(float(np.mean(q_hats)), 5)
    return rep, sets


def _zero_shot_conformal_34(probs123: np.ndarray, y123: np.ndarray, probs34: np.ndarray, y34: np.ndarray,
                            nf34: int, method: str, alpha: float) -> dict[str, Any]:
    q = am.conformal_quantile(am.conformal_scores(probs123, y123, method, _u(len(y123), 0)), alpha)
    sets = am.conformal_sets(probs34, q, method, _u(len(y34), 1))
    rep = am.conformal_report(probs34, y34, sets, nf34)
    rep["q_hat"] = round(float(q), 5)
    rep["exchangeability_note"] = "Frozen 123-bus q_hat applied cross-feeder to 34-bus; carries NO exchangeability guarantee."
    return rep


def _recal_conformal_34(probs34: np.ndarray, y34: np.ndarray, bus34: np.ndarray, nf34: int,
                        frac: float, method: str, alpha: float, *, n_repeats: int, seed: int) -> dict[str, Any]:
    fault_buses = np.array(sorted(np.unique(bus34[y34 < nf34])))
    nf_idx = np.flatnonzero(y34 == nf34)
    n_cal_b = max(1, int(round(frac * len(fault_buses))))
    n_cal_nf = max(10, int(round(frac * len(nf_idx))))
    u = _u(len(y34), 1)
    rng = np.random.default_rng(seed)
    reps = []
    for _ in range(n_repeats):
        cb = set(rng.choice(fault_buses, size=n_cal_b, replace=False).tolist())
        cnf = set(rng.choice(nf_idx, size=n_cal_nf, replace=False).tolist())
        cal = np.array([(b in cb) or (i in cnf) for i, b in enumerate(bus34)])
        te = ~cal
        q = am.conformal_quantile(am.conformal_scores(probs34[cal], y34[cal], method, u[cal]), alpha)
        r = am.conformal_report(probs34[te], y34[te], am.conformal_sets(probs34[te], q, method, u[te]), nf34)
        r["q_hat"] = q
        reps.append(r)

    def stats(k: str) -> dict[str, float | None]:
        vals = [r[k] for r in reps if r[k] is not None]
        if not vals:
            return {"mean": None, "std": None, "min": None, "max": None}
        return {
            "mean": round(float(np.mean(vals)), 4),
            "std": round(float(np.std(vals)), 4),
            "min": round(float(np.min(vals)), 4),
            "max": round(float(np.max(vals)), 4),
        }

    keys = ("coverage", "coverage_fault", "coverage_nofault", "avg_set_size", "empty_share",
            "singleton_share", "singleton_accuracy", "raw_argmax_accuracy",
            "nofault_autonomous_trip_share", "fault_autonomous_correct_share", "q_hat")
    return {
        "fraction": frac,
        "cal_fault_buses": n_cal_b,
        "cal_nofault_events": n_cal_nf,
        "n_repeats": n_repeats,
        **{k: stats(k) for k in keys},
    }


def _run_conformal(ds123: hf.ActiveFusionDataset, ds34: hf.ActiveFusionDataset, fold_id123: np.ndarray,
                   oof123: dict[str, np.ndarray], zs34: dict[str, np.ndarray], *,
                   quick: bool, seed: int) -> dict[str, Any]:
    n_rep = 3 if quick else 10
    results: dict[str, Any] = {}
    for abl_name in ("60Hz_only", "60Hz_plus_edge"):
        abl_res: dict[str, Any] = {}
        for m_key, m_tag in (("active_per_node_gbdt", "gbdt"), ("active_grid_gatv2", "gatv2")):
            p123 = oof123[f"{abl_name}__{m_tag}"]
            p34 = zs34[f"{abl_name}__{m_tag}"]
            m_res: dict[str, Any] = {}
            for method in CONFORMAL_METHODS:
                meth_res: dict[str, Any] = {}
                sets_123: dict[str, np.ndarray] = {}
                for alpha in CONFORMAL_ALPHAS:
                    tkey = f"target_{int(round(100 * (1 - alpha)))}"
                    r123, s123 = _cross_conformal_123(p123, ds123.y, fold_id123, ds123.nofault_class, method, alpha)
                    rzs = _zero_shot_conformal_34(p123, ds123.y, p34, ds34.y, ds34.nofault_class, method, alpha)
                    rc5 = _recal_conformal_34(p34, ds34.y, ds34.bus, ds34.nofault_class, 0.05, method, alpha,
                                              n_repeats=n_rep, seed=seed)
                    rc20 = _recal_conformal_34(p34, ds34.y, ds34.bus, ds34.nofault_class, 0.20, method, alpha,
                                               n_repeats=n_rep, seed=seed + 100)
                    sets_123[tkey] = s123
                    meth_res[tkey] = {
                        "ieee123_cross_conformal": r123,
                        "ieee34_zero_shot_q_from_123": rzs,
                        "ieee34_recal_5pct_buses": rc5,
                        "ieee34_recal_20pct_buses": rc20,
                    }
                differ = bool((sets_123["target_90"] != sets_123["target_95"]).any())
                cov95 = meth_res["target_95"]["ieee123_cross_conformal"]["coverage"]
                in_band = bool(0.92 <= cov95 <= 0.98)
                meth_res["reading_rule"] = {
                    "sets_90_and_95_differ": differ,
                    "ieee123_cov95_in_92_98": in_band,
                    "non_degenerate": bool(differ and in_band),
                }
                m_res[method] = meth_res
            abl_res[m_key] = m_res
        results[abl_name] = abl_res

    return {
        "phase": "hif_fusion_conformal",
        "simulation_only": True,
        "primary_method": "aps_rand",
        "primary_target": "target_95",
        "aps_rand_uniform_seed": U_SEED,
        "methods": {
            "aps_rand": "randomized APS, S = sum_{p_j > p_y} p_j + U*p_y, U ~ Uniform(0,1)",
            "lac": "least-ambiguous classifier, S = 1 - p_y",
        },
        "events": {"ieee123": int(len(ds123.y)), "ieee34": int(len(ds34.y))},
        "results": results,
    }


# ---------------------------------------------------------------------------
# Pre-committed H1-H4 Pass / Partial / Fail Evaluation (PLAN.md §4)
# ---------------------------------------------------------------------------
def _evaluate_precommitted_criteria(
    p123: dict[str, Any],
    p34: dict[str, Any],
    a123: dict[str, Any],
    a34: dict[str, Any],
    conf: dict[str, Any],
) -> dict[str, Any]:
    def _delta(fused_v: float | None, base_v: float | None) -> float | None:
        if fused_v is None or base_v is None:
            return None
        return round(float(fused_v - base_v), 4)

    # --- H1: IEEE 123-bus HIF Localization Gain (SLG 200-400 ohm) ---
    def _h1_branch(abl_dict: dict[str, Any], models: tuple[str, ...], acc_key: str) -> dict[str, Any]:
        per_model = {}
        any_pass, any_partial, any_regress = False, False, False
        for m in models:
            b = abl_dict["60Hz_only"][m]
            f = abl_dict["60Hz_plus_edge"][m]
            d400 = _delta(f["slg_by_resistance"].get("400.0"), b["slg_by_resistance"].get("400.0")) or 0.0
            d200_400 = _delta(f["slg_200_400_accuracy"], b["slg_200_400_accuracy"]) or 0.0
            d_low = _delta(f["slg_low_r_0_100_accuracy"], b["slg_low_r_0_100_accuracy"]) or 0.0
            d_ph = _delta(f["phase_faults_accuracy"], b["phase_faults_accuracy"]) or 0.0
            d_all = _delta(f[acc_key], b[acc_key]) or 0.0
            regress = (d_low < -0.005) or (d_ph < -0.005)
            if regress:
                any_regress = True
            if (d400 >= 0.10) and (d200_400 >= 0.05) and (not regress) and (d_all >= -1e-9 or acc_key == "accuracy"):
                any_pass = True
            elif (d400 >= 0.03) and (not regress):
                any_partial = True
            per_model[m] = {
                "base_slg400": b["slg_by_resistance"].get("400.0"),
                "fused_slg400": f["slg_by_resistance"].get("400.0"),
                "delta_slg400": d400,
                "base_slg_200_400": b["slg_200_400_accuracy"],
                "fused_slg_200_400": f["slg_200_400_accuracy"],
                "delta_slg_200_400": d200_400,
                "delta_slg_low_r": d_low,
                "delta_phase": d_ph,
                "delta_overall": d_all,
                "low_r_or_phase_regressed_gt_0p5pt": bool(regress),
            }
        verdict = "FAIL" if any_regress else ("PASS" if any_pass else ("PARTIAL" if any_partial else "FAIL"))
        return {"verdict": verdict, "models": per_model}

    h1_passive = _h1_branch(p123["ablations"], ("per_node_gbdt", "zone_tree_gnn"), "accuracy")
    h1_active = _h1_branch(a123["ablations"], ("active_per_node_gbdt", "active_grid_gatv2"), "overall_accuracy")
    if h1_passive["verdict"] == "PASS" and h1_active["verdict"] == "PASS":
        h1_overall = "PASS"
    elif "FAIL" not in (h1_passive["verdict"], h1_active["verdict"]):
        h1_overall = "PARTIAL"
    elif "PASS" in (h1_passive["verdict"], h1_active["verdict"]) or "PARTIAL" in (h1_passive["verdict"], h1_active["verdict"]):
        h1_overall = "PARTIAL"
    else:
        h1_overall = "FAIL"

    # --- H2: Zero-Shot Transfer to Unseen IEEE 34-bus (24.9 kV) ---
    h2_p_models = {}
    h2_p_ok = True
    for m in ("per_node_gbdt", "zone_tree_gnn"):
        b = p34["zero_shot"]["60Hz_only"][m]
        f = p34["zero_shot"]["60Hz_plus_edge"][m]
        d_all = _delta(f["accuracy"], b["accuracy"]) or 0.0
        d_200_400 = _delta(f["slg_200_400_accuracy"], b["slg_200_400_accuracy"]) or 0.0
        ok = (d_all >= -0.005) and (d_200_400 >= -0.005)
        h2_p_ok &= ok
        h2_p_models[m] = {"base_acc": round(b["accuracy"], 4), "fused_acc": round(f["accuracy"], 4),
                          "delta_acc": d_all, "delta_slg_200_400": d_200_400, "ok": bool(ok)}
    h2_passive = {"verdict": "PASS" if h2_p_ok else "FAIL", "models": h2_p_models}

    h2_a_models = {}
    h2_a_pass, h2_a_partial = False, False
    for m in ("active_per_node_gbdt", "active_grid_gatv2"):
        b = a34["zero_shot"]["60Hz_only"][m]
        f = a34["zero_shot"]["60Hz_plus_edge"][m]
        d_hif = _delta(f["slg_hif_1k_10k_accuracy"], b["slg_hif_1k_10k_accuracy"]) or 0.0
        d_all = _delta(f["overall_accuracy"], b["overall_accuracy"]) or 0.0
        d_low = _delta(f["slg_low_r_0_100_accuracy"], b["slg_low_r_0_100_accuracy"]) or 0.0
        d_ph = _delta(f["phase_faults_accuracy"], b["phase_faults_accuracy"]) or 0.0
        clean_ok = (d_low >= -0.005) and (d_ph >= -0.005)
        if d_hif >= 0.05 and d_all >= 0.02:
            h2_a_pass = True
        elif (d_hif >= 0.02 or d_all >= 0.005) and clean_ok:
            h2_a_partial = True
        h2_a_models[m] = {
            "base_overall": round(b["overall_accuracy"], 4), "fused_overall": round(f["overall_accuracy"], 4),
            "delta_overall": d_all,
            "base_hif_1k_10k": b["slg_hif_1k_10k_accuracy"], "fused_hif_1k_10k": f["slg_hif_1k_10k_accuracy"],
            "delta_hif_1k_10k": d_hif, "delta_low_r": d_low, "delta_phase": d_ph,
        }
    h2_active_v = "PASS" if h2_a_pass else ("PARTIAL" if h2_a_partial else "FAIL")
    h2_active = {"verdict": h2_active_v, "models": h2_a_models}
    h2_overall = "PASS" if (h2_passive["verdict"] == "PASS" and h2_active_v == "PASS") else (
        "PARTIAL" if ("PASS" in (h2_passive["verdict"], h2_active_v) or h2_active_v == "PARTIAL") else "FAIL"
    )

    # --- H3: NO_FAULT Nuisance-Trip Control across all 7 Background Disturbances ---
    h3_123_models = {}
    h3_123_pass, h3_123_partial = False, False
    for m in ("active_per_node_gbdt", "active_grid_gatv2"):
        b = a123["ablations"]["60Hz_only"][m]
        f = a123["ablations"]["60Hz_plus_edge"][m]
        fpr_b, fpr_f = b["nofault_fpr"], f["nofault_fpr"]
        dist_vals = [v for v in f["nofault_fpr_by_disturbance"].values() if v is not None]
        max_dist = max(dist_vals) if dist_vals else 0.0
        improved = fpr_f < fpr_b
        if improved and fpr_f <= 0.05 and max_dist <= 0.10:
            h3_123_pass = True
        elif improved:
            h3_123_partial = True
        h3_123_models[m] = {
            "base_fpr": round(fpr_b, 4), "fused_fpr": round(fpr_f, 4),
            "delta_fpr": round(fpr_f - fpr_b, 4), "max_disturbance_fpr": round(max_dist, 4),
            "by_disturbance": f["nofault_fpr_by_disturbance"],
        }
    h3_123_v = "PASS" if h3_123_pass else ("PARTIAL" if h3_123_partial else "FAIL")

    h3_34_models = {}
    h3_34_pass, h3_34_partial = False, False
    for m in ("active_per_node_gbdt", "active_grid_gatv2"):
        b = a34["zero_shot"]["60Hz_only"][m]
        f = a34["zero_shot"]["60Hz_plus_edge"][m]
        fpr_b, fpr_f = b["nofault_fpr"], f["nofault_fpr"]
        reduction = fpr_b - fpr_f
        if reduction >= 0.05:
            h3_34_pass = True
        elif reduction > 0.0:
            h3_34_partial = True
        h3_34_models[m] = {
            "base_fpr": round(fpr_b, 4), "fused_fpr": round(fpr_f, 4),
            "fpr_reduction": round(reduction, 4),
            "by_disturbance": f["nofault_fpr_by_disturbance"],
        }
    h3_34_v = "PASS" if h3_34_pass else ("PARTIAL" if h3_34_partial else "FAIL")
    h3_overall = "PASS" if (h3_123_v == "PASS" and h3_34_v == "PASS") else (
        "FAIL" if (h3_123_v == "FAIL" or h3_34_v == "FAIL") else "PARTIAL"
    )

    # --- H4: Missing-Sensor Resilience & Conformal Safety Gate (`aps_rand` 95%) ---
    miss_checks = {}
    miss_ok = True
    for label, b_obj, f_obj in (
        ("passive_123_gbdt", p123["ablations"]["60Hz_only"]["per_node_gbdt"], p123["ablations"]["60Hz_plus_edge"]["per_node_gbdt"]),
        ("passive_123_gnn", p123["ablations"]["60Hz_only"]["zone_tree_gnn"], p123["ablations"]["60Hz_plus_edge"]["zone_tree_gnn"]),
        ("passive_34_gbdt", p34["zero_shot"]["60Hz_only"]["per_node_gbdt"], p34["zero_shot"]["60Hz_plus_edge"]["per_node_gbdt"]),
        ("passive_34_gnn", p34["zero_shot"]["60Hz_only"]["zone_tree_gnn"], p34["zero_shot"]["60Hz_plus_edge"]["zone_tree_gnn"]),
        ("active_123_gbdt", a123["ablations"]["60Hz_only"]["active_per_node_gbdt"], a123["ablations"]["60Hz_plus_edge"]["active_per_node_gbdt"]),
        ("active_123_gatv2", a123["ablations"]["60Hz_only"]["active_grid_gatv2"], a123["ablations"]["60Hz_plus_edge"]["active_grid_gatv2"]),
        ("active_34_gbdt", a34["zero_shot"]["60Hz_only"]["active_per_node_gbdt"], a34["zero_shot"]["60Hz_plus_edge"]["active_per_node_gbdt"]),
        ("active_34_gatv2", a34["zero_shot"]["60Hz_only"]["active_grid_gatv2"], a34["zero_shot"]["60Hz_plus_edge"]["active_grid_gatv2"]),
    ):
        dm = round(float(f_obj["missing_sensor_mean"] - b_obj["missing_sensor_mean"]), 4)
        ok = dm >= -0.01
        miss_ok &= ok
        miss_checks[label] = {
            "base": round(b_obj["missing_sensor_mean"], 4),
            "fused": round(f_obj["missing_sensor_mean"], 4),
            "delta": dm,
            "ok_within_1pt": bool(ok),
        }

    conf_models = {}
    conf_any_pass = False
    for m in ("active_per_node_gbdt", "active_grid_gatv2"):
        cb = conf["results"]["60Hz_only"][m]["aps_rand"]
        cf = conf["results"]["60Hz_plus_edge"][m]["aps_rand"]
        non_deg = bool(cf["reading_rule"]["non_degenerate"])
        b123 = cb["target_95"]["ieee123_cross_conformal"]
        f123 = cf["target_95"]["ieee123_cross_conformal"]
        s_ok = (f123["singleton_share"] >= b123["singleton_share"] - 1e-4)
        acc_ok = (f123["singleton_accuracy"] is not None and f123["singleton_accuracy"] >= 0.985)
        trip_ok = (f123["nofault_autonomous_trip_share"] is not None and f123["nofault_autonomous_trip_share"] <= 0.015)
        m_pass = bool(non_deg and s_ok and acc_ok and trip_ok)
        conf_any_pass |= m_pass
        conf_models[m] = {
            "non_degenerate": non_deg,
            "ieee123_cov95": f123["coverage"],
            "base_singleton_share": b123["singleton_share"],
            "fused_singleton_share": f123["singleton_share"],
            "fused_singleton_accuracy": f123["singleton_accuracy"],
            "fused_nofault_auto_trip_share": f123["nofault_autonomous_trip_share"],
            "pass": m_pass,
        }
    h4_verdict = "PASS" if (miss_ok and conf_any_pass) else ("PARTIAL" if (miss_ok or conf_any_pass) else "FAIL")

    return {
        "H1_ieee123_hif_gain": {"verdict": h1_overall, "passive": h1_passive, "active": h1_active},
        "H2_ieee34_zero_shot": {"verdict": h2_overall, "passive": h2_passive, "active": h2_active},
        "H3_nofault_7_disturbances": {"verdict": h3_overall, "ieee123": {"verdict": h3_123_v, "models": h3_123_models},
                                      "ieee34": {"verdict": h3_34_v, "models": h3_34_models}},
        "H4_missing_sensor_and_conformal": {
            "verdict": h4_verdict,
            "missing_sensor_all_ok": bool(miss_ok),
            "missing_sensor": miss_checks,
            "conformal_aps_rand_95": conf_models,
        },
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Two-tier Edge HIF-Sensor -> Graph FLISR experiment")
    ap.add_argument("--model-npz", type=str, default=None,
                    help="Path to frozen model_int8.npz (e.g. from Kaggle christoopherchau/ch-y-n)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=0,
                    help="CPU workers for Tier-1 waveform synthesis (0 = auto min(4, cpu_count))")
    ap.add_argument("--skip-sweep", action="store_true", help="Reuse existing data/generated/hif_fusion_*.npz")
    ap.add_argument("--quick", action="store_true", help="Small smoke-test run on CPU")
    args = ap.parse_args()

    t0 = time.time()
    n_workers = args.workers if args.workers > 0 else min(4, os.cpu_count() or 1)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Step 0: Load frozen Tier-1 Edge HIF-Sensor model BEFORE touching CUDA (safe for multiprocessing).
    print("=== Step 0: Load frozen Tier-1 Edge HIF-Sensor (model_int8.npz) ===")
    model, model_info = he.load_or_train_model(
        args.model_npz,
        allow_retrain=True,
        n_events=400 if args.quick else he.N_EVENTS,
        verbose=True,
    )
    print(f"  Tier-1 Edge model: source={model_info['model_source']} | params={model.n_params} | "
          f"bytes={model.n_bytes} | thr={model.threshold:.6f} | sha256={model.sha256}")

    # Step 1: OpenDSS + Tier-1 Edge HIF-Sensor sweeps (BEFORE CUDA init so Linux fork workers never deadlock)
    p_ds = OUT_DIR / "dataset_summary.json"
    if not args.skip_sweep:
        print(f"\n=== Step 1: OpenDSS + Tier-1 Edge HIF-Sensor sweeps (workers={n_workers}, quick={args.quick}) ===")
        p_kw = {"scenarios": 1, "max_cases": 80} if args.quick else {}
        a123_kw = {"scenarios_per_topo": 1, "max_cases": 50, "max_nofault_per_topo": 21} if args.quick else {"scenarios_per_topo": 1}
        a34_kw = {"scenarios_per_topo": 1, "max_cases": 50, "max_nofault_per_topo": 21} if args.quick else {"scenarios_per_topo": 2}

        sp123 = hf.sweep_passive_fusion("ieee123", model, seed=args.seed, n_workers=n_workers, verbose=True, **p_kw)
        sp34 = hf.sweep_passive_fusion("ieee34", model, seed=args.seed + 1, n_workers=n_workers, verbose=True, **p_kw)
        sa123 = hf.sweep_active_fusion("ieee123", model, seed=args.seed, n_workers=n_workers, verbose=True, **a123_kw)
        sa34 = hf.sweep_active_fusion("ieee34", model, seed=args.seed + 1, n_workers=n_workers, verbose=True, **a34_kw)

        ds_summary = {
            "phase": "hif_fusion_dataset_summary",
            "simulation_only": True,
            "quick_mode": bool(args.quick),
            "seed": args.seed,
            "tier1_edge_model": model_info,
            "butterworth_cutoff_hz_python": round(he.cutoff_hz(), 1),
            "butterworth_cutoff_hz_ltspice": he.LTSPICE_CUTOFF_HZ,
            "fs_adc_hz": he.FS_ADC,
            "persist_windows": he.PERSIST,
            "surfaces": list(hf.SURFACE_NAMES),
            "disturbances": list(he.DISTURBANCES),
            "passive_ieee123": sp123,
            "passive_ieee34": sp34,
            "active_ieee123": sa123,
            "active_ieee34": sa34,
        }
        p_ds.write_text(json.dumps(ds_summary, indent=2) + "\n", encoding="utf-8")

    # Initialize PyTorch GPU/CPU device AFTER multiprocessing sweeps finish.
    dev = am.get_device(prefer_gpu=True)
    print(f"\n=== Tier-2 Graph FLISR training device: {dev} (torch {torch.__version__}, cuda={torch.cuda.is_available()}) ===")

    # Step 2: Passive branch (IEEE 123-bus CV + IEEE 34-bus zero-shot / few-shot)
    print("\n=== Step 2: Passive Branch (PerNodeGBDT & ZoneTreeGNN: 60Hz_only vs 60Hz_plus_edge) ===")
    dsp123 = hf.load_passive_fusion_dataset("ieee123")
    dsp34 = hf.load_passive_fusion_dataset("ieee34")
    p123_obj, p_frozen = _run_passive_123(dsp123, seed=args.seed, quick=args.quick, device=dev)
    p34_obj = _run_passive_34(dsp34, p_frozen, seed=args.seed, quick=args.quick, device=dev)

    # Step 3: Active branch (IEEE 123-bus CV + IEEE 34-bus zero-shot / few-shot)
    print("\n=== Step 3: Active Branch (ActivePerNodeGBDT & ActiveGridGATv2: 60Hz_only vs 60Hz_plus_edge) ===")
    dsa123 = hf.load_active_fusion_dataset("ieee123")
    dsa34 = hf.load_active_fusion_dataset("ieee34")
    a123_obj, a_frozen, oof123, fold_id123 = _run_active_123(dsa123, seed=args.seed, quick=args.quick, device=dev)
    a34_obj, zs34_probs = _run_active_34(dsa34, a_frozen, seed=args.seed, quick=args.quick, device=dev)

    # Save active conformal probabilities to isolated data/generated/hif_fusion_probs.npz
    probs_path = hf.FUSED_OUT_DIR / "hif_fusion_probs.npz"
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
    print(f"  Saved conformal input probabilities to {probs_path}")

    # Step 4: Split Conformal Prediction (`aps_rand` primary at 90%/95% + `lac`)
    print("\n=== Step 4: Split Conformal Prediction (aps_rand & lac at 90%/95%) ===")
    conf_obj = _run_conformal(dsa123, dsa34, fold_id123, oof123, zs34_probs, quick=args.quick, seed=args.seed)

    # Step 5: Pre-committed H1-H4 criteria evaluation
    criteria = _evaluate_precommitted_criteria(p123_obj, p34_obj, a123_obj, a34_obj, conf_obj)
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
    a34_obj["pre_committed_criteria"] = criteria
    a34_obj.update(env_meta)
    conf_obj["pre_committed_criteria_h4"] = criteria["H4_missing_sensor_and_conformal"]
    conf_obj.update(env_meta)

    p_p123 = OUT_DIR / "passive_ieee123.json"
    p_p34 = OUT_DIR / "passive_ieee34.json"
    p_a123 = OUT_DIR / "active_ieee123.json"
    p_a34 = OUT_DIR / "active_ieee34.json"
    p_conf = OUT_DIR / "conformal_hif.json"

    for path, obj in (
        (p_p123, p123_obj),
        (p_p34, p34_obj),
        (p_a123, a123_obj),
        (p_a34, a34_obj),
        (p_conf, conf_obj),
    ):
        path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")

    recorded = [p for p in (p_ds, p_p123, p_p34, p_a123, p_a34, p_conf) if p.exists()]
    provenance.record(PRODUCER, recorded)

    print("\n=== Pre-committed H1-H4 Verdict Summary ===")
    print(json.dumps({
        "H1": criteria["H1_ieee123_hif_gain"]["verdict"],
        "H2": criteria["H2_ieee34_zero_shot"]["verdict"],
        "H3": criteria["H3_nofault_7_disturbances"]["verdict"],
        "H4": criteria["H4_missing_sensor_and_conformal"]["verdict"],
    }, indent=2))
    print(f"Done in {total_rt} s. Recorded provenance for {len(recorded)} files -> results/provenance/{PRODUCER}.json")


if __name__ == "__main__":
    main()
