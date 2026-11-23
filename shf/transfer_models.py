"""Feeder-independent fault-zone models for the transfer study (research/gnn-transfer/PLAN.md, phase 2).

Every model here takes the same graph input from data/generated/transfer_<feeder>.npz:
  X      : (events, nodes, 21) relative node features (shf.transfer.FEATURES)
  parent : (nodes,) upstream device index in the zone tree, -1 for the head recloser

None of the models depend on device names, feeder voltage level, or a fixed node count, so a model
trained on IEEE 123-bus can be run unchanged on an unseen feeder in phase 3.

Models compared:
  1. FPI rule (graph_fpi_predict): relative pickup rule using shf.config.FPI_PHASE_FACTOR (2.0x)
     and FPI_GROUND_FACTOR (0.5x on incremental residual 3*dI0), picking the deepest flagged node.
  2. Per-node gradient boosting (PerNodeGBDT): HistGradientBoostingClassifier on each node's own
     features plus parent/child aggregates and self-vs-neighbor differences; predicts argmax node.
  3. Zone-tree GNN (ZoneTreeGNN): 2 or 3 directional message-passing layers over the zone tree
     (parent -> child and child -> parent with max + mean child pooling), then a per-node logit
     trained with cross-entropy (softmax over nodes) in plain PyTorch on CPU.

Simulation only. Nothing here is field data.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import copy
from dataclasses import dataclass
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold

from . import config, transfer

N_FOLDS = 5
DROPOUT_RATE = 0.15                        # matches shf.model.DROPOUT_RATE
N_ELEC = 17                                # features 0..16 are measurements; 17..20 are tree structure
N_CONT_ELEC = 14                           # continuous measurements dIa..dVc (0..13)

_IDX = {name: i for i, name in enumerate(transfer.FEATURES)}
_PHASE_COLS = (_IDX["Ia"], _IDX["Ib"], _IDX["Ic"])
_DI0_COL = _IDX["dI0"]


@dataclass
class GraphDataset:
    feeder: str
    X: np.ndarray                          # (E, N, F) float32
    y: np.ndarray                          # (E,) int64
    parent: np.ndarray                     # (N,) int64 (-1 for root)
    features: list[str]
    devices: list[str]
    bus: np.ndarray                        # (E,) str
    ftype: np.ndarray                      # (E,) str
    phases: np.ndarray                     # (E,) str
    r: np.ndarray                          # (E,) float64
    scenario: np.ndarray                   # (E,) int64
    load_mult: np.ndarray                  # (E,) float64


def load_dataset(feeder: str, path: Path | None = None) -> GraphDataset:
    """Load converged graph events from data/generated/transfer_<feeder>.npz."""
    p = path or (transfer.OUT_DIR / f"transfer_{feeder}.npz")
    d = np.load(p, allow_pickle=False)
    ok = d["converged"].astype(bool)
    return GraphDataset(
        feeder=feeder,
        X=d["X"][ok].astype(np.float32),
        y=d["y"][ok].astype(np.int64),
        parent=d["parent"].astype(np.int64),
        features=[str(s) for s in d["features"]],
        devices=[str(s) for s in d["devices"]],
        bus=d["bus"][ok].astype(str),
        ftype=d["ftype"][ok].astype(str),
        phases=d["phases"][ok].astype(str),
        r=d["r"][ok].astype(float),
        scenario=d["scenario"][ok].astype(int),
        load_mult=d["load_mult"][ok].astype(float),
    )


def tree_depths(parent: np.ndarray) -> np.ndarray:
    """Depth of each node in the zone tree (0 for root)."""
    n = len(parent)
    depths = np.zeros(n, dtype=np.int64)
    for i in range(n):
        d, cur = 0, int(parent[i])
        while cur >= 0:
            d += 1
            cur = int(parent[cur])
        depths[i] = d
    return depths


def blank_sensor(X: np.ndarray, node: int) -> np.ndarray:
    """Copy X with one sensor's measurements blanked to NaN (structure features stay intact)."""
    out = X.copy()
    out[:, node, :N_ELEC] = np.nan
    return out


def apply_sensor_dropout(X: np.ndarray, rng: np.random.Generator, rate: float = DROPOUT_RATE) -> np.ndarray:
    """Blank one random device's measurements on a share of training events."""
    if rate <= 0.0:
        return X
    out = X.copy()
    n_events, n_nodes, _ = out.shape
    rows = np.flatnonzero(rng.random(n_events) < rate)
    if len(rows):
        nodes = rng.integers(0, n_nodes, size=len(rows))
        out[rows, nodes, :N_ELEC] = np.nan
    return out


# ---------------------------------------------------------------------------
# 1. FPI rule (graph-level, relative pickups from shf.config)
# ---------------------------------------------------------------------------

def fpi_predict(X: np.ndarray, parent: np.ndarray) -> np.ndarray:
    """Relative-pickup FPI rule on feeder-independent graph features.

    A device flags when its post-fault phase current ratio exceeds FPI_PHASE_FACTOR (2.0x pre-fault
    base) OR its incremental residual current ratio 3*|dI0|/base exceeds FPI_GROUND_FACTOR (0.5x).
    Returns the deepest flagged node index, breaking same-depth ties by largest normalized ratio
    (permutation-invariant), or -1 when no device flags.
    """
    phase_ratio = np.expm1(X[:, :, _PHASE_COLS]).max(axis=-1)
    ground_ratio = 3.0 * np.expm1(X[:, :, _DI0_COL])
    # NaNs from a missing sensor evaluate False in comparisons, so an offline sensor never flags.
    phase_norm = np.where(np.isfinite(phase_ratio), phase_ratio / config.FPI_PHASE_FACTOR, -1.0)
    ground_norm = np.where(np.isfinite(ground_ratio), ground_ratio / config.FPI_GROUND_FACTOR, -1.0)
    flagged = (phase_norm > 1.0) | (ground_norm > 1.0)
    signal = np.maximum(phase_norm, ground_norm)

    depths = tree_depths(parent)
    # Lexicographic score: depth dominates; normalized ratio breaks ties at the same depth.
    score = np.where(flagged, depths[None, :] * 1e6 + np.clip(signal, 0.0, 1e5), -1.0)
    best = score.argmax(axis=1)
    none_flagged = ~flagged.any(axis=1)
    return np.where(none_flagged, -1, best).astype(np.int64)


# ---------------------------------------------------------------------------
# 2. Per-node Gradient Boosting (own features + parent/child aggregates)
# ---------------------------------------------------------------------------

def node_neighborhood_features(X: np.ndarray, parent: np.ndarray) -> np.ndarray:
    """Build per-node feature tensor (E, N, 4*F + 2*N_CONT_ELEC) from (X, parent).

    For each node i:
      [x_i, x_parent, max_{c in C(i)} x_c, mean_{c in C(i)} x_c,
       x_i[:14] - x_parent[:14], x_i[:14] - child_max[:14]]
    Missing neighbors (root's parent, leaf's children) and offline sensors stay NaN so
    HistGradientBoostingClassifier handles them natively without inventing values.
    """
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
            sub = X[:, kids, :]                             # (E, K, F)
            finite = np.isfinite(sub)
            any_fin = finite.any(axis=1)
            safe_max = np.where(finite, sub, -np.inf).max(axis=1)
            x_cmax[:, i, :] = np.where(any_fin, safe_max, np.nan)
            count = finite.sum(axis=1)
            safe_sum = np.where(finite, sub, 0.0).sum(axis=1)
            x_cmean[:, i, :] = np.where(count > 0, safe_sum / np.maximum(count, 1), np.nan)

    diff_par = X[:, :, :N_CONT_ELEC] - x_par[:, :, :N_CONT_ELEC]
    diff_cmax = X[:, :, :N_CONT_ELEC] - x_cmax[:, :, :N_CONT_ELEC]
    return np.concatenate([X, x_par, x_cmax, x_cmean, diff_par, diff_cmax], axis=-1)


class PerNodeGBDT:
    """Feeder-independent per-node gradient boosting classifier."""

    def __init__(self, max_iter: int = 300, learning_rate: float = 0.1, max_leaf_nodes: int = 31,
                 min_samples_leaf: int = 20, l2_regularization: float = 0.0,
                 sensor_dropout: float = DROPOUT_RATE, seed: int = 0):
        self.params = dict(max_iter=max_iter, learning_rate=learning_rate, max_leaf_nodes=max_leaf_nodes,
                           min_samples_leaf=min_samples_leaf, l2_regularization=l2_regularization,
                           sensor_dropout=sensor_dropout, seed=seed)
        self.clf = HistGradientBoostingClassifier(
            max_iter=max_iter, learning_rate=learning_rate, max_leaf_nodes=max_leaf_nodes,
            min_samples_leaf=min_samples_leaf, l2_regularization=l2_regularization, random_state=seed,
        )

    def fit(self, X: np.ndarray, y: np.ndarray, parent: np.ndarray) -> "PerNodeGBDT":
        rng = np.random.default_rng(self.params["seed"])
        X_aug = apply_sensor_dropout(X, rng, self.params["sensor_dropout"])
        feat = node_neighborhood_features(X_aug, parent)    # (E, N, D)
        e_count, n_nodes, dim = feat.shape
        target = np.zeros((e_count, n_nodes), dtype=np.int64)
        target[np.arange(e_count), y] = 1
        self.clf.fit(feat.reshape(-1, dim), target.reshape(-1))
        return self

    def scores(self, X: np.ndarray, parent: np.ndarray) -> np.ndarray:
        """Per-node log-odds of shape (E, N)."""
        feat = node_neighborhood_features(X, parent)
        e_count, n_nodes, dim = feat.shape
        raw = self.clf.decision_function(feat.reshape(-1, dim))
        return raw.reshape(e_count, n_nodes)

    def predict(self, X: np.ndarray, parent: np.ndarray) -> np.ndarray:
        return self.scores(X, parent).argmax(axis=1).astype(np.int64)


# ---------------------------------------------------------------------------
# 3. Zone-tree GNN (plain PyTorch, CPU)
# ---------------------------------------------------------------------------

class TreeMPLayer(nn.Module):
    """One directional message-passing layer over a rooted zone tree.

    Each node combines its own state, its parent's state (0 for root), and max + mean pooled
    states from its children (0 for leaves), followed by a residual MLP and LayerNorm.
    """

    def __init__(self, hidden: int, dropout: float = 0.1):
        super().__init__()
        self.msg = nn.Sequential(
            nn.Linear(4 * hidden, hidden),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, hidden),
            nn.Dropout(dropout),
        )
        self.norm = nn.LayerNorm(hidden)

    def forward(self, h: torch.Tensor, parent: torch.Tensor) -> torch.Tensor:
        # h: (B, N, H), parent: (N,) long with -1 at root
        bsz, n_nodes, hid = h.shape
        has_par = parent >= 0
        par_safe = parent.clamp(min=0)
        h_par = h[:, par_safe, :] * has_par.view(1, n_nodes, 1).to(h.dtype)

        child_idx = torch.nonzero(has_par, as_tuple=False).squeeze(-1)
        if child_idx.numel() > 0:
            par_of_child = parent[child_idx]
            src = h[:, child_idx, :]                                    # (B, E_edges, H)
            idx = par_of_child.view(1, -1, 1).expand(bsz, -1, hid)

            deg = torch.zeros(n_nodes, device=h.device, dtype=h.dtype)
            deg.scatter_add_(0, par_of_child, torch.ones_like(par_of_child, dtype=h.dtype))
            has_child = deg > 0

            csum = torch.zeros_like(h).scatter_add(1, idx, src)
            cmean = csum / deg.clamp(min=1.0).view(1, n_nodes, 1)

            cmax_raw = torch.full_like(h, -1e9).scatter_reduce(1, idx, src, reduce="amax", include_self=False)
            cmax = torch.where(has_child.view(1, n_nodes, 1), cmax_raw, torch.zeros_like(h))
        else:
            cmean = torch.zeros_like(h)
            cmax = torch.zeros_like(h)

        cat = torch.cat([h, h_par, cmax, cmean], dim=-1)
        return self.norm(h + self.msg(cat))


class ZoneTreeGNN(nn.Module):
    """2- or 3-layer tree GNN with per-node readout (softmax over nodes in cross-entropy)."""

    def __init__(self, in_features: int = len(transfer.FEATURES), hidden: int = 64,
                 n_layers: int = 3, dropout: float = 0.1):
        super().__init__()
        self.in_features = in_features
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
        self.layers = nn.ModuleList([TreeMPLayer(hidden, dropout=dropout) for _ in range(n_layers)])
        self.readout = nn.Sequential(
            nn.Linear(hidden, hidden // 2),
            nn.GELU(),
            nn.Linear(hidden // 2, 1),
        )

    def set_normalizer(self, X_train: np.ndarray) -> None:
        """Fit per-feature mean/std strictly on training data (ignoring NaNs)."""
        flat = X_train.reshape(-1, self.in_features)
        mean = np.nanmean(flat, axis=0)
        std = np.nanstd(flat, axis=0)
        std = np.where(std < 1e-6, 1.0, std)
        self.feat_mean.copy_(torch.from_numpy(mean.astype(np.float32)))
        self.feat_std.copy_(torch.from_numpy(std.astype(np.float32)))

    def forward(self, x: torch.Tensor, parent: torch.Tensor) -> torch.Tensor:
        """Return per-node logits of shape (B, N). Offline sensors have NaN measurements."""
        # A node is observed iff its measurement channels are finite.
        observed = torch.isfinite(x[:, :, :N_ELEC]).all(dim=-1, keepdim=True)     # (B, N, 1)
        x_clean = torch.nan_to_num(x, nan=0.0)
        x_norm = (x_clean - self.feat_mean) / self.feat_std
        # Zero out normalized measurements for offline sensors while keeping structural features.
        obs_f = observed.to(x.dtype)
        elec = x_norm[:, :, :N_ELEC] * obs_f
        struct = x_norm[:, :, N_ELEC:]
        inp = torch.cat([elec, struct, obs_f], dim=-1)

        h = self.encoder(inp)
        for layer in self.layers:
            h = layer(h, parent)
        return self.readout(h).squeeze(-1)


def train_gnn(X_train: np.ndarray, y_train: np.ndarray, parent: np.ndarray, *,
              hidden: int = 64, n_layers: int = 3, dropout: float = 0.1,
              lr: float = 2e-3, weight_decay: float = 1e-4, epochs: int = 40,
              batch_size: int = 256, sensor_dropout: float = DROPOUT_RATE,
              seed: int = 0) -> ZoneTreeGNN:
    """Train ZoneTreeGNN on CPU with a fixed cosine schedule (no validation leakage)."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)

    model = ZoneTreeGNN(in_features=X_train.shape[-1], hidden=hidden, n_layers=n_layers, dropout=dropout)
    model.set_normalizer(X_train)

    x_all = torch.from_numpy(X_train.astype(np.float32))
    y_all = torch.from_numpy(y_train.astype(np.int64))
    par_t = torch.from_numpy(parent.astype(np.int64))

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs, eta_min=lr * 0.01)

    n_events, n_nodes = X_train.shape[0], X_train.shape[1]
    model.train()
    for _ in range(epochs):
        perm = torch.from_numpy(rng.permutation(n_events))
        for start in range(0, n_events, batch_size):
            idx = perm[start:start + batch_size]
            xb = x_all[idx]
            yb = y_all[idx]
            if sensor_dropout > 0.0:
                xb = xb.clone()
                mask = torch.from_numpy(rng.random(len(idx)) < sensor_dropout)
                if mask.any():
                    drop_rows = torch.nonzero(mask, as_tuple=False).squeeze(-1)
                    drop_nodes = torch.from_numpy(rng.integers(0, n_nodes, size=len(drop_rows)))
                    xb[drop_rows, drop_nodes, :N_ELEC] = float("nan")
            opt.zero_grad(set_to_none=True)
            loss = F.cross_entropy(model(xb, par_t), yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
            opt.step()
        sched.step()
    model.eval()
    return model


@torch.no_grad()
def predict_gnn(model: ZoneTreeGNN, X: np.ndarray, parent: np.ndarray, batch_size: int = 1024) -> np.ndarray:
    """Predicted zone indices of shape (E,)."""
    model.eval()
    par_t = torch.from_numpy(parent.astype(np.int64))
    preds = []
    for start in range(0, len(X), batch_size):
        xb = torch.from_numpy(X[start:start + batch_size].astype(np.float32))
        preds.append(model(xb, par_t).argmax(dim=-1).numpy())
    return np.concatenate(preds).astype(np.int64)


# ---------------------------------------------------------------------------
# GroupKFold cross-validation and metrics (strictly by fault bus)
# ---------------------------------------------------------------------------

def evaluate_predictions(ds: GraphDataset, pred: np.ndarray,
                         fold_indices: list[np.ndarray] | None = None,
                         missing_hits: dict[str, int] | None = None) -> dict[str, Any]:
    """Compute overall, per-fold, per-fault-type, SLG-by-resistance, per-zone, and missing-sensor metrics."""
    correct = pred == ds.y
    by_ftype = {ft: round(float(correct[ds.ftype == ft].mean()), 4) for ft in sorted(np.unique(ds.ftype))}
    slg = ds.ftype == "SLG"
    slg_by_r = {str(float(rv)): round(float(correct[slg & (ds.r == rv)].mean()), 4)
                for rv in sorted(np.unique(ds.r[slg]))}
    by_zone = {d: round(float(correct[ds.y == i].mean()), 4) for i, d in enumerate(ds.devices)}
    out: dict[str, Any] = {
        "accuracy": float(correct.mean()),
        "by_fault_type": by_ftype,
        "slg_by_resistance": slg_by_r,
        "by_zone": by_zone,
    }
    if fold_indices is not None:
        fold_accs = [float(correct[idx].mean()) for idx in fold_indices]
        out["fold_accuracies"] = [round(a, 4) for a in fold_accs]
        out["fold_std"] = round(float(np.std(fold_accs)), 4)
    if missing_hits is not None:
        per_dev = {d: float(h / len(ds.y)) for d, h in missing_hits.items()}
        out["missing_sensor_accuracy"] = per_dev
        out["missing_sensor_mean"] = float(np.mean(list(per_dev.values())))
        out["missing_sensor_min"] = float(np.min(list(per_dev.values())))
    return out


def cv_fpi(ds: GraphDataset, n_splits: int = N_FOLDS) -> dict[str, Any]:
    """Evaluate the graph FPI rule with the same GroupKFold fold breakdown + missing-sensor test."""
    folds = [test for _, test in GroupKFold(n_splits=n_splits).split(ds.X, ds.y, ds.bus)]
    pred = fpi_predict(ds.X, ds.parent)
    missing_hits = {}
    for i, d in enumerate(ds.devices):
        pm = fpi_predict(blank_sensor(ds.X, i), ds.parent)
        missing_hits[d] = int((pm == ds.y).sum())
    res = evaluate_predictions(ds, pred, folds, missing_hits)
    res["no_device_flagged"] = float((pred < 0).mean())
    res["pred"] = pred
    return res


def cv_gbdt(ds: GraphDataset, *, n_splits: int = N_FOLDS, eval_missing: bool = True,
            **kwargs: Any) -> dict[str, Any]:
    """GroupKFold cross-validation by fault bus for PerNodeGBDT."""
    oof = np.empty(len(ds.y), dtype=np.int64)
    folds: list[np.ndarray] = []
    missing_hits = {d: 0 for d in ds.devices} if eval_missing else None
    base_seed = int(kwargs.get("seed", 0))
    for fold_i, (train, test) in enumerate(GroupKFold(n_splits=n_splits).split(ds.X, ds.y, ds.bus)):
        folds.append(test)
        fold_kw = dict(kwargs)
        fold_kw["seed"] = base_seed + fold_i
        clf = PerNodeGBDT(**fold_kw).fit(ds.X[train], ds.y[train], ds.parent)
        oof[test] = clf.predict(ds.X[test], ds.parent)
        if eval_missing and missing_hits is not None:
            for i, d in enumerate(ds.devices):
                pm = clf.predict(blank_sensor(ds.X[test], i), ds.parent)
                missing_hits[d] += int((pm == ds.y[test]).sum())
    res = evaluate_predictions(ds, oof, folds, missing_hits)
    res["pred"] = oof
    return res


def _gnn_fold_worker(args: tuple) -> tuple[np.ndarray, np.ndarray, dict[str, int] | None]:
    X_tr, y_tr, X_te, y_te, parent, devices, eval_missing, fold_kw, threads = args
    torch.set_num_threads(threads)
    net = train_gnn(X_tr, y_tr, parent, **fold_kw)
    pred = predict_gnn(net, X_te, parent)
    miss = None
    if eval_missing:
        miss = {d: int((predict_gnn(net, blank_sensor(X_te, i), parent) == y_te).sum())
                for i, d in enumerate(devices)}
    return pred, y_te, miss


def cv_gnn(ds: GraphDataset, *, n_splits: int = N_FOLDS, eval_missing: bool = True,
           n_jobs: int = 1, threads_per_worker: int = 2, **kwargs: Any) -> dict[str, Any]:
    """GroupKFold cross-validation by fault bus for ZoneTreeGNN."""
    oof = np.empty(len(ds.y), dtype=np.int64)
    folds: list[np.ndarray] = []
    missing_hits = {d: 0 for d in ds.devices} if eval_missing else None
    base_seed = int(kwargs.get("seed", 0))
    splits = list(GroupKFold(n_splits=n_splits).split(ds.X, ds.y, ds.bus))
    jobs = []
    for fold_i, (train, test) in enumerate(splits):
        folds.append(test)
        fold_kw = dict(kwargs)
        fold_kw["seed"] = base_seed + fold_i
        jobs.append((ds.X[train], ds.y[train], ds.X[test], ds.y[test],
                     ds.parent, ds.devices, eval_missing, fold_kw, threads_per_worker))

    if n_jobs > 1:
        with ProcessPoolExecutor(max_workers=min(n_jobs, len(jobs))) as pool:
            outputs = list(pool.map(_gnn_fold_worker, jobs))
    else:
        outputs = [_gnn_fold_worker(j) for j in jobs]

    for (_, test), (pred, _, miss) in zip(splits, outputs):
        oof[test] = pred
        if eval_missing and missing_hits is not None and miss is not None:
            for d, h in miss.items():
                missing_hits[d] += h
    res = evaluate_predictions(ds, oof, folds, missing_hits)
    res["pred"] = oof
    return res


# ---------------------------------------------------------------------------
# Phase 3 helpers: frozen-model loading, zero-shot evaluation, few-shot fine-tuning
# ---------------------------------------------------------------------------

def load_frozen_models(model_dir: Path | None = None) -> tuple[PerNodeGBDT, ZoneTreeGNN, dict[str, Any]]:
    """Load the frozen IEEE 123-bus models written by scripts/transfer_train.py."""
    mdir = model_dir or (config.MODELS / "transfer")
    with open(mdir / "per_node_gbdt_ieee123.pkl", "rb") as f:
        gbdt_pkg = pickle.load(f)
    gnn_pkg = torch.load(mdir / "gnn_ieee123.pt", map_location="cpu", weights_only=False)
    net = ZoneTreeGNN(**gnn_pkg["arch"])
    net.load_state_dict(gnn_pkg["state_dict"])
    net.eval()
    meta = {
        "gbdt_params": gbdt_pkg["params"],
        "gnn_params": gnn_pkg["params"],
        "gnn_arch": gnn_pkg["arch"],
        "sensor_dropout": gnn_pkg.get("sensor_dropout", DROPOUT_RATE),
    }
    return gbdt_pkg["model"], net, meta


def eval_zero_shot_gbdt(clf: PerNodeGBDT, ds: GraphDataset, eval_missing: bool = True) -> dict[str, Any]:
    """Evaluate a pre-trained PerNodeGBDT unchanged on another feeder."""
    pred = clf.predict(ds.X, ds.parent)
    missing_hits = None
    if eval_missing:
        missing_hits = {d: int((clf.predict(blank_sensor(ds.X, i), ds.parent) == ds.y).sum())
                        for i, d in enumerate(ds.devices)}
    res = evaluate_predictions(ds, pred, None, missing_hits)
    res["pred"] = pred
    return res


def eval_zero_shot_gnn(net: ZoneTreeGNN, ds: GraphDataset, eval_missing: bool = True) -> dict[str, Any]:
    """Evaluate a pre-trained ZoneTreeGNN unchanged on another feeder."""
    pred = predict_gnn(net, ds.X, ds.parent)
    missing_hits = None
    if eval_missing:
        missing_hits = {d: int((predict_gnn(net, blank_sensor(ds.X, i), ds.parent) == ds.y).sum())
                        for i, d in enumerate(ds.devices)}
    res = evaluate_predictions(ds, pred, None, missing_hits)
    res["pred"] = pred
    return res


def finetune_gbdt(base_clf: PerNodeGBDT, X_few: np.ndarray, y_few: np.ndarray, parent: np.ndarray, *,
                  extra_iter: int = 50, lr: float = 0.05, sensor_dropout: float = DROPOUT_RATE,
                  seed: int = 0) -> PerNodeGBDT:
    """Warm-start fine-tune a frozen PerNodeGBDT on a small sample of target-feeder events."""
    clf = copy.deepcopy(base_clf)
    rng = np.random.default_rng(seed)
    X_aug = apply_sensor_dropout(X_few, rng, sensor_dropout)
    feat = node_neighborhood_features(X_aug, parent)
    e_count, n_nodes, dim = feat.shape
    target = np.zeros((e_count, n_nodes), dtype=np.int64)
    target[np.arange(e_count), y_few] = 1
    clf.clf.set_params(
        warm_start=True,
        early_stopping=False,
        learning_rate=lr,
        max_iter=int(clf.clf.n_iter_) + extra_iter,
        random_state=seed,
    )
    clf.clf.fit(feat.reshape(-1, dim), target.reshape(-1))
    return clf


def finetune_gnn(base_net: ZoneTreeGNN, X_few: np.ndarray, y_few: np.ndarray, parent: np.ndarray, *,
                 epochs: int = 25, lr: float = 5e-4, weight_decay: float = 1e-4,
                 batch_size: int = 64, sensor_dropout: float = DROPOUT_RATE,
                 seed: int = 0) -> ZoneTreeGNN:
    """Fine-tune a frozen ZoneTreeGNN on a small sample of target-feeder events (keeping its normalizer)."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    net = copy.deepcopy(base_net)
    x_all = torch.from_numpy(X_few.astype(np.float32))
    y_all = torch.from_numpy(y_few.astype(np.int64))
    par_t = torch.from_numpy(parent.astype(np.int64))

    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs, eta_min=lr * 0.05)

    n_events, n_nodes = X_few.shape[0], X_few.shape[1]
    net.train()
    for _ in range(epochs):
        perm = torch.from_numpy(rng.permutation(n_events))
        for start in range(0, n_events, batch_size):
            idx = perm[start:start + batch_size]
            xb, yb = x_all[idx], y_all[idx]
            if sensor_dropout > 0.0:
                xb = xb.clone()
                mask = torch.from_numpy(rng.random(len(idx)) < sensor_dropout)
                if mask.any():
                    drop_rows = torch.nonzero(mask, as_tuple=False).squeeze(-1)
                    drop_nodes = torch.from_numpy(rng.integers(0, n_nodes, size=len(drop_rows)))
                    xb[drop_rows, drop_nodes, :N_ELEC] = float("nan")
            opt.zero_grad(set_to_none=True)
            loss = F.cross_entropy(net(xb, par_t), yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 2.0)
            opt.step()
        sched.step()
    net.eval()
    return net


def few_shot_eval(ds: GraphDataset, frac: float, *, base_gbdt: PerNodeGBDT, base_gnn: ZoneTreeGNN,
                  n_repeats: int = 10, seed: int = 0, sensor_dropout: float = DROPOUT_RATE) -> dict[str, Any]:
    """Few-shot fine-tuning on `frac` of unique buses, tested strictly on the remaining buses."""
    buses = np.array(sorted(np.unique(ds.bus)))
    n_train_buses = max(1, int(round(frac * len(buses))))
    rng = np.random.default_rng(seed)

    results = {}
    for model_name in ("per_node_gbdt", "gnn"):
        split_accs = []
        all_correct, all_ftype, all_r = [], [], []
        miss_hits = {d: 0 for d in ds.devices}
        total_eval = 0

        for rep in range(n_repeats):
            chosen = set(rng.choice(buses, size=n_train_buses, replace=False).tolist())
            tr_mask = np.array([b in chosen for b in ds.bus])
            te_mask = ~tr_mask
            assert set(ds.bus[tr_mask]).isdisjoint(set(ds.bus[te_mask]))

            if model_name == "per_node_gbdt":
                m = finetune_gbdt(base_gbdt, ds.X[tr_mask], ds.y[tr_mask], ds.parent,
                                  sensor_dropout=sensor_dropout, seed=seed + rep)
                pred = m.predict(ds.X[te_mask], ds.parent)
                for i, d in enumerate(ds.devices):
                    pm = m.predict(blank_sensor(ds.X[te_mask], i), ds.parent)
                    miss_hits[d] += int((pm == ds.y[te_mask]).sum())
            else:
                m = finetune_gnn(base_gnn, ds.X[tr_mask], ds.y[tr_mask], ds.parent,
                                 sensor_dropout=sensor_dropout, seed=seed + rep)
                pred = predict_gnn(m, ds.X[te_mask], ds.parent)
                for i, d in enumerate(ds.devices):
                    pm = predict_gnn(m, blank_sensor(ds.X[te_mask], i), ds.parent)
                    miss_hits[d] += int((pm == ds.y[te_mask]).sum())

            corr = pred == ds.y[te_mask]
            split_accs.append(float(corr.mean()))
            all_correct.append(corr)
            all_ftype.append(ds.ftype[te_mask])
            all_r.append(ds.r[te_mask])
            total_eval += int(te_mask.sum())

        # Reset RNG before the second model so both models see the EXACT same 10 bus splits!
        rng = np.random.default_rng(seed)

        c_all = np.concatenate(all_correct)
        ft_all = np.concatenate(all_ftype)
        r_all = np.concatenate(all_r)
        slg = ft_all == "SLG"
        per_dev = {d: float(h / total_eval) for d, h in miss_hits.items()}
        results[model_name] = {
            "accuracy_mean": float(np.mean(split_accs)),
            "accuracy_std": float(np.std(split_accs)),
            "split_accuracies": [round(a, 4) for a in split_accs],
            "by_fault_type": {ft: round(float(c_all[ft_all == ft].mean()), 4) for ft in sorted(np.unique(ft_all))},
            "slg_by_resistance": {str(float(rv)): round(float(c_all[slg & (r_all == rv)].mean()), 4)
                                  for rv in sorted(np.unique(r_all[slg]))},
            "missing_sensor_accuracy": per_dev,
            "missing_sensor_mean": float(np.mean(list(per_dev.values()))),
            "missing_sensor_min": float(np.min(list(per_dev.values()))),
        }

    return {
        "fraction": frac,
        "train_buses": n_train_buses,
        "test_buses": int(len(buses) - n_train_buses),
        "n_repeats": n_repeats,
        "models": results,
    }
