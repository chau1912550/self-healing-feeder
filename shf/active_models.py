"""Active-grid fault location models and Split Conformal Prediction (research/active-grid-gnn/PLAN.md).

All models operate on general dynamic graphs (radial, back-fed reconfigured, or closed-loop cycles)
with N zone nodes plus a joint NO_FAULT class (index N), and never depend on device names, absolute
amperes, voltage bases, or a fixed node count:
  1. active_fpi_predict  : conventional pickup rule generalized via active-graph distance from sources.
  2. ActivePerNodeGBDT   : per-node GBDT on active 1-hop neighbor aggregates + graph-level NO_FAULT GBDT.
  3. ActiveGridGATv2     : 3-layer bidirectional edge-aware GATv2 in plain PyTorch (GPU on Kaggle / CPU
                           locally), with joint (N + 1)-way readout (N zones + global-pooled NO_FAULT).
  4. Split Conformal APS : finite-sample Adaptive Prediction Sets (Romano et al., 2020) separating safe
                           autonomous single-zone switching (|C|=1) from operator deferral (|C|>=2).

Simulation only. Nothing here is field data.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold

from . import active_grid as ag, config, transfer

N_FOLDS = 5
DROPOUT_RATE = 0.15

_IDX = {name: i for i, name in enumerate(ag.ACTIVE_FEATURES)}
_DI_COLS = (_IDX["dIa"], _IDX["dIb"], _IDX["dIc"])
_I_COLS = (_IDX["Ia"], _IDX["Ib"], _IDX["Ic"])
_V_COLS = (_IDX["Va"], _IDX["Vb"], _IDX["Vc"])
_HAS_COLS = (_IDX["has_a"], _IDX["has_b"], _IDX["has_c"])
_DI0_COL = _IDX["dI0"]
_COS_PRE_COL = _IDX["cos_vi_pre"]
_CLOSED_COL = _IDX["is_closed"]
_SRC_COL = _IDX["is_source_adj"]
N_CONT_DIFF = 14                           # dIa..dVc continuous electrical channels for neighbor contrast


@dataclass
class ActiveGraphDataset:
    feeder: str
    X: np.ndarray                          # (E, N, 26) float32
    y: np.ndarray                          # (E,) int64 in 0..N (N = NO_FAULT)
    topo_id: np.ndarray                    # (E,) int64
    adj: np.ndarray                        # (T, N, N) float32
    is_tie: np.ndarray                     # (T, N, N) float32
    topo_names: list[str]
    topo_is_looped: np.ndarray             # (T,) bool
    features: list[str]
    devices: list[str]
    bus: np.ndarray                        # (E,) str
    ftype: np.ndarray                      # (E,) str
    r: np.ndarray                          # (E,) float64
    der_pct: np.ndarray                    # (E,) float64
    event_kind: np.ndarray                 # (E,) str ('fault', 'cap_switch', 'pv_cloud', 'load_step')

    @property
    def n_nodes(self) -> int:
        return self.X.shape[1]

    @property
    def nofault_class(self) -> int:
        return self.X.shape[1]


def load_active_dataset(feeder: str, path: Path | None = None) -> ActiveGraphDataset:
    p = path or (transfer.OUT_DIR / f"active_{feeder}.npz")
    d = np.load(p, allow_pickle=False)
    ok = d["converged"].astype(bool)
    return ActiveGraphDataset(
        feeder=feeder,
        X=d["X"][ok].astype(np.float32),
        y=d["y"][ok].astype(np.int64),
        topo_id=d["topo_id"][ok].astype(np.int64),
        adj=d["adj"].astype(np.float32),
        is_tie=d["is_tie"].astype(np.float32),
        topo_names=[str(s) for s in d["topo_names"]],
        topo_is_looped=d["topo_is_looped"].astype(bool),
        features=[str(s) for s in d["features"]],
        devices=[str(s) for s in d["devices"]],
        bus=d["bus"][ok].astype(str),
        ftype=d["ftype"][ok].astype(str),
        r=d["r"][ok].astype(float),
        der_pct=d["der_pct"][ok].astype(float),
        event_kind=d["event_kind"][ok].astype(str),
    )


def blank_active_sensor(X: np.ndarray, node: int) -> np.ndarray:
    """Copy X with one sensor's live electrical measurements blanked to NaN."""
    out = X.copy()
    out[:, node, :ag.N_ACTIVE_ELEC] = np.nan
    return out


def apply_active_sensor_dropout(X: np.ndarray, rng: np.random.Generator,
                                rate: float = DROPOUT_RATE) -> np.ndarray:
    if rate <= 0.0:
        return X
    out = X.copy()
    n_ev, n_nodes, _ = out.shape
    rows = np.flatnonzero(rng.random(n_ev) < rate)
    if len(rows):
        nodes = rng.integers(0, n_nodes, size=len(rows))
        out[rows, nodes, :ag.N_ACTIVE_ELEC] = np.nan
    return out


def make_bus_group_folds(ds: ActiveGraphDataset, n_splits: int = N_FOLDS) -> list[tuple[np.ndarray, np.ndarray]]:
    """5-fold GroupKFold by bus: fault buses never overlap between train and test; NO_FAULT events split evenly."""
    # Fault events group by physical bus; NO_FAULT events each have a unique id `nf_t_i` so GroupKFold spreads them.
    return list(GroupKFold(n_splits=n_splits).split(ds.X, ds.y, ds.bus))


def _softmax_np(logits: np.ndarray) -> np.ndarray:
    z = logits - logits.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / np.maximum(e.sum(axis=-1, keepdims=True), 1e-12)


# ---------------------------------------------------------------------------
# 1. Conventional FPI generalized to dynamic active/looped graphs
# ---------------------------------------------------------------------------

def _source_bfs_depths(adj_t: np.ndarray, src_mask: np.ndarray) -> np.ndarray:
    """Shortest-path hop distance from any active source-adjacent node in adj_t."""
    n = adj_t.shape[0]
    dist = np.full(n, n, dtype=np.int64)
    queue = list(np.flatnonzero(src_mask))
    for q in queue:
        dist[q] = 0
    head = 0
    while head < len(queue):
        u = queue[head]
        head += 1
        for v in np.flatnonzero(adj_t[u] > 0.5):
            if dist[v] > dist[u] + 1:
                dist[v] = dist[u] + 1
                queue.append(int(v))
    return dist


def active_fpi_predict(X: np.ndarray, adj: np.ndarray, topo_id: np.ndarray) -> np.ndarray:
    """Relative-pickup FPI on active graphs; predicts N (NO_FAULT) when no closed device flags."""
    n_ev, n_nodes, _ = X.shape
    phase_ratio = np.expm1(X[:, :, _I_COLS]).max(axis=-1)
    ground_ratio = 3.0 * np.expm1(X[:, :, _DI0_COL])
    is_closed = X[:, :, _CLOSED_COL] > 0.5

    phase_norm = np.where(np.isfinite(phase_ratio) & is_closed, phase_ratio / config.FPI_PHASE_FACTOR, -1.0)
    ground_norm = np.where(np.isfinite(ground_ratio) & is_closed, ground_ratio / config.FPI_GROUND_FACTOR, -1.0)
    flagged = (phase_norm > 1.0) | (ground_norm > 1.0)
    signal = np.maximum(phase_norm, ground_norm)

    # Compute hop distance from active source nodes for each topology.
    n_topos = adj.shape[0]
    depths = np.zeros((n_topos, n_nodes), dtype=np.int64)
    for t in range(n_topos):
        rows_t = np.flatnonzero(topo_id == t)
        if len(rows_t):
            src_mask = X[rows_t[0], :, _SRC_COL] > 0.5
        else:
            src_mask = np.zeros(n_nodes, dtype=bool)
            src_mask[0] = True
        depths[t] = _source_bfs_depths(adj[t], src_mask)

    ev_depths = depths[topo_id]                                    # (E, N)
    score = np.where(flagged, ev_depths * 1e6 + np.clip(signal, 0.0, 1e5), -1.0)
    best = score.argmax(axis=1)
    none_flagged = ~flagged.any(axis=1)
    return np.where(none_flagged, n_nodes, best).astype(np.int64)


# ---------------------------------------------------------------------------
# 2. Active Per-node GBDT + Graph-level NO_FAULT GBDT (strong non-GNN baseline)
# ---------------------------------------------------------------------------

def active_node_neighborhood_features(X: np.ndarray, adj: np.ndarray, topo_id: np.ndarray) -> np.ndarray:
    """Build (E, N, 4*F + 2*N_CONT_DIFF) per-node features using live active-graph 1-hop neighbors."""
    n_ev, n_nodes, n_feat = X.shape
    nbr_max = np.full((n_ev, n_nodes, n_feat), np.nan, dtype=np.float32)
    nbr_mean = np.full((n_ev, n_nodes, n_feat), np.nan, dtype=np.float32)
    nbr_min = np.full((n_ev, n_nodes, n_feat), np.nan, dtype=np.float32)

    for t in range(adj.shape[0]):
        rows = np.flatnonzero(topo_id == t)
        if not len(rows):
            continue
        Xt = X[rows]                                               # (Et, N, F)
        for i in range(n_nodes):
            nbrs = np.flatnonzero(adj[t, i] > 0.5)
            if len(nbrs) == 1:
                v = Xt[:, nbrs[0], :]
                nbr_max[rows, i, :] = v
                nbr_mean[rows, i, :] = v
                nbr_min[rows, i, :] = v
            elif len(nbrs) > 1:
                sub = Xt[:, nbrs, :]                               # (Et, K, F)
                fin = np.isfinite(sub)
                any_f = fin.any(axis=1)
                smax = np.where(fin, sub, -np.inf).max(axis=1)
                smin = np.where(fin, sub, np.inf).min(axis=1)
                cnt = fin.sum(axis=1)
                ssum = np.where(fin, sub, 0.0).sum(axis=1)
                nbr_max[rows, i, :] = np.where(any_f, smax, np.nan)
                nbr_min[rows, i, :] = np.where(any_f, smin, np.nan)
                nbr_mean[rows, i, :] = np.where(cnt > 0, ssum / np.maximum(cnt, 1), np.nan)

    d_max = X[:, :, :N_CONT_DIFF] - nbr_max[:, :, :N_CONT_DIFF]
    d_min = X[:, :, :N_CONT_DIFF] - nbr_min[:, :, :N_CONT_DIFF]
    return np.concatenate([X, nbr_max, nbr_mean, nbr_min, d_max, d_min], axis=-1)


def _graph_summary_features(X: np.ndarray) -> np.ndarray:
    """Graph-level permutation-invariant stats (E, 4*F) for NO_FAULT detection."""
    fin = np.isfinite(X)
    any_f = fin.any(axis=1)
    cnt = np.maximum(fin.sum(axis=1), 1)
    gmax = np.where(any_f, np.where(fin, X, -np.inf).max(axis=1), np.nan)
    gmin = np.where(any_f, np.where(fin, X, np.inf).min(axis=1), np.nan)
    gmean = np.where(any_f, np.where(fin, X, 0.0).sum(axis=1) / cnt, np.nan)
    diff = np.where(fin, X - gmean[:, None, :], 0.0)
    gstd = np.where(any_f, np.sqrt((diff * diff).sum(axis=1) / cnt), np.nan)
    return np.concatenate([gmax, gmean, gmin, gstd], axis=-1).astype(np.float32)


class ActivePerNodeGBDT:
    """Feeder-independent per-node GBDT (zone scoring) + graph-level GBDT (NO_FAULT probability)."""

    def __init__(self, max_iter: int = 300, learning_rate: float = 0.1, max_leaf_nodes: int = 31,
                 sensor_dropout: float = DROPOUT_RATE, seed: int = 0):
        self.params = dict(max_iter=max_iter, learning_rate=learning_rate,
                           max_leaf_nodes=max_leaf_nodes, sensor_dropout=sensor_dropout, seed=seed)
        self.node_clf = HistGradientBoostingClassifier(
            max_iter=max_iter, learning_rate=learning_rate,
            max_leaf_nodes=max_leaf_nodes, random_state=seed,
        )
        self.nf_clf = HistGradientBoostingClassifier(
            max_iter=max_iter, learning_rate=learning_rate,
            max_leaf_nodes=max_leaf_nodes, random_state=seed + 1000,
        )

    def fit(self, X: np.ndarray, y: np.ndarray, adj: np.ndarray, topo_id: np.ndarray) -> "ActivePerNodeGBDT":
        rng = np.random.default_rng(self.params["seed"])
        X_aug = apply_active_sensor_dropout(X, rng, self.params["sensor_dropout"])
        n_nodes = X.shape[1]

        # 1) Graph-level NO_FAULT vs FAULT classifier on all events.
        is_nf = (y == n_nodes).astype(np.int64)
        self.nf_clf.fit(_graph_summary_features(X_aug), is_nf)

        # 2) Per-node binary classifier on fault events only.
        fault_mask = y < n_nodes
        feat = active_node_neighborhood_features(X_aug[fault_mask], adj, topo_id[fault_mask])
        ef, nf, dim = feat.shape
        target = np.zeros((ef, nf), dtype=np.int64)
        target[np.arange(ef), y[fault_mask]] = 1
        self.node_clf.fit(feat.reshape(-1, dim), target.reshape(-1))
        return self

    def predict_proba(self, X: np.ndarray, adj: np.ndarray, topo_id: np.ndarray) -> np.ndarray:
        """Calibrated (E, N + 1) probabilities over N zones + NO_FAULT."""
        p_nf = self.nf_clf.predict_proba(_graph_summary_features(X))[:, 1:2]      # (E, 1)
        feat = active_node_neighborhood_features(X, adj, topo_id)
        n_ev, n_nodes, dim = feat.shape
        node_logits = self.node_clf.decision_function(feat.reshape(-1, dim)).reshape(n_ev, n_nodes)
        p_zones = _softmax_np(node_logits) * (1.0 - p_nf)
        return np.concatenate([p_zones, p_nf], axis=1).astype(np.float64)

    def predict(self, X: np.ndarray, adj: np.ndarray, topo_id: np.ndarray) -> np.ndarray:
        return self.predict_proba(X, adj, topo_id).argmax(axis=1).astype(np.int64)


def finetune_active_gbdt(base: ActivePerNodeGBDT, X_few: np.ndarray, y_few: np.ndarray,
                         adj: np.ndarray, topo_few: np.ndarray, *, extra_iter: int = 50,
                         lr: float = 0.05, sensor_dropout: float = DROPOUT_RATE,
                         seed: int = 0) -> ActivePerNodeGBDT:
    clf = copy.deepcopy(base)
    rng = np.random.default_rng(seed)
    X_aug = apply_active_sensor_dropout(X_few, rng, sensor_dropout)
    n_nodes = X_few.shape[1]

    is_nf = (y_few == n_nodes).astype(np.int64)
    if len(np.unique(is_nf)) == 2:
        clf.nf_clf.set_params(warm_start=True, early_stopping=False, learning_rate=lr,
                              max_iter=int(clf.nf_clf.n_iter_) + extra_iter, random_state=seed)
        clf.nf_clf.fit(_graph_summary_features(X_aug), is_nf)

    fmask = y_few < n_nodes
    if fmask.any():
        feat = active_node_neighborhood_features(X_aug[fmask], adj, topo_few[fmask])
        ef, nf, dim = feat.shape
        target = np.zeros((ef, nf), dtype=np.int64)
        target[np.arange(ef), y_few[fmask]] = 1
        clf.node_clf.set_params(warm_start=True, early_stopping=False, learning_rate=lr,
                                max_iter=int(clf.node_clf.n_iter_) + extra_iter, random_state=seed)
        clf.node_clf.fit(feat.reshape(-1, dim), target.reshape(-1))
    return clf


# ---------------------------------------------------------------------------
# 3. Bidirectional Edge-Aware GATv2 (plain PyTorch, GPU/CPU)
# ---------------------------------------------------------------------------

class EdgeGATv2Layer(nn.Module):
    """Multi-head Edge-Aware GATv2 layer with dual attention + max neighbor aggregation.

    Works on arbitrary general graphs (radial, reconfigured, or closed loops) of any size N.
    """

    def __init__(self, hidden: int, edge_dim: int = 4, n_heads: int = 4, dropout: float = 0.1):
        super().__init__()
        assert hidden % n_heads == 0
        self.hidden = hidden
        self.n_heads = n_heads
        self.d_head = hidden // n_heads

        self.w_l = nn.Linear(hidden, hidden, bias=False)
        self.w_r = nn.Linear(hidden, hidden, bias=False)
        self.w_e = nn.Linear(edge_dim, hidden, bias=False)
        self.attn = nn.Parameter(torch.empty(n_heads, self.d_head))
        nn.init.xavier_uniform_(self.attn)
        self.attn_drop = nn.Dropout(dropout)

        self.update = nn.Sequential(
            nn.Linear(3 * hidden, hidden),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, hidden),
            nn.Dropout(dropout),
        )
        self.norm = nn.LayerNorm(hidden)

    def forward(self, h: torch.Tensor, adj: torch.Tensor, edge_attr: torch.Tensor) -> torch.Tensor:
        # h: (B, N, H), adj: (B, N, N) in {0,1}, edge_attr: (B, N, N, E_dim)
        bsz, n_nodes, hid = h.shape
        nh, dh = self.n_heads, self.d_head

        hl = self.w_l(h).view(bsz, n_nodes, nh, dh)
        hr = self.w_r(h).view(bsz, n_nodes, nh, dh)
        he = self.w_e(edge_attr).view(bsz, n_nodes, n_nodes, nh, dh)

        # GATv2 dynamic attention: a^T LeakyReLU(W_l h_u + W_r h_v + W_e e_uv)
        pair = hl.unsqueeze(2) + hr.unsqueeze(1) + he              # (B, N, N, nh, dh)
        e_logits = (F.leaky_relu(pair, 0.2) * self.attn.view(1, 1, 1, nh, dh)).sum(dim=-1)  # (B, N, N, nh)

        mask = adj > 0.5                                           # (B, N, N)
        has_nbr = mask.any(dim=-1, keepdim=True)                   # (B, N, 1)
        e_masked = e_logits.masked_fill(~mask.unsqueeze(-1), -1e9)
        alpha = self.attn_drop(F.softmax(e_masked, dim=2))
        alpha = alpha * has_nbr.unsqueeze(-1).to(h.dtype)

        val = (hr.unsqueeze(1) + he).reshape(bsz, n_nodes, n_nodes, hid)
        # Attention-weighted neighbor summary: (B, N, nh, dh) -> (B, N, H)
        val_h = val.view(bsz, n_nodes, n_nodes, nh, dh)
        h_attn = (alpha.unsqueeze(-1) * val_h).sum(dim=2).reshape(bsz, n_nodes, hid)

        # Elementwise max over active neighbors (key inductive bias for catching faulted branches).
        val_masked = val.masked_fill(~mask.unsqueeze(-1), -1e9)
        h_max = torch.where(has_nbr, val_masked.max(dim=2).values, torch.zeros_like(h))

        return self.norm(h + self.update(torch.cat([h, h_attn, h_max], dim=-1)))


class ActiveGridGATv2(nn.Module):
    """Bidirectional edge-aware GATv2 with joint (N + 1)-way readout (N zones + NO_FAULT)."""

    def __init__(self, in_features: int = len(ag.ACTIVE_FEATURES), hidden: int = 64,
                 n_layers: int = 3, n_heads: int = 4, dropout: float = 0.1):
        super().__init__()
        self.in_features = in_features
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
            EdgeGATv2Layer(hidden, edge_dim=4, n_heads=n_heads, dropout=dropout)
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

    @staticmethod
    def _edge_features(x_clean: torch.Tensor, obs_f: torch.Tensor, is_tie: torch.Tensor) -> torch.Tensor:
        """Compute (B, N, N, 4) directional physical edge features from raw sensor readings."""
        # Zero out offline sensor contributions cleanly.
        obs_1 = obs_f.squeeze(-1)                                  # (B, N)
        di_max = x_clean[:, :, _DI_COLS].max(dim=-1).values * obs_1
        # Minimum voltage among present phases (fallback to 1.0 if offline).
        v_raw = x_clean[:, :, _V_COLS]
        has_ph = x_clean[:, :, _HAS_COLS] > 0.5
        v_min = torch.where(has_ph, v_raw, torch.full_like(v_raw, 2.0)).min(dim=-1).values
        v_min = torch.where((obs_1 > 0.5) & has_ph.any(dim=-1), v_min, torch.ones_like(v_min))
        cos_pre = x_clean[:, :, _COS_PRE_COL] * obs_1

        same_dir = cos_pre.unsqueeze(2) * cos_pre.unsqueeze(1)
        diff_di = di_max.unsqueeze(2) - di_max.unsqueeze(1)
        diff_v = v_min.unsqueeze(2) - v_min.unsqueeze(1)
        return torch.stack([is_tie, same_dir, diff_di, diff_v], dim=-1)

    def forward(self, x: torch.Tensor, adj: torch.Tensor, is_tie: torch.Tensor) -> torch.Tensor:
        """Return (B, N + 1) logits: columns 0..N-1 are zones, column N is NO_FAULT."""
        observed = torch.isfinite(x[:, :, :ag.N_ACTIVE_ELEC]).all(dim=-1, keepdim=True)
        obs_f = observed.to(x.dtype)
        x_clean = torch.nan_to_num(x, nan=0.0)
        edge_attr = self._edge_features(x_clean, obs_f, is_tie)

        x_norm = (x_clean - self.feat_mean) / self.feat_std
        elec = x_norm[:, :, :ag.N_ACTIVE_ELEC] * obs_f
        struct = x_norm[:, :, ag.N_ACTIVE_ELEC:]
        h = self.encoder(torch.cat([elec, struct, obs_f], dim=-1))

        for layer in self.layers:
            h = layer(h, adj, edge_attr)

        zone_logits = self.node_head(h).squeeze(-1)                # (B, N)
        g_pool = torch.cat([h.mean(dim=1), h.max(dim=1).values], dim=-1)  # (B, 2*H)
        nf_logit = self.nofault_head(g_pool)                       # (B, 1)
        return torch.cat([zone_logits, nf_logit], dim=-1)


def get_device(prefer_gpu: bool = True) -> torch.device:
    if prefer_gpu and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def train_active_gat(X_train: np.ndarray, y_train: np.ndarray, adj: np.ndarray, is_tie: np.ndarray,
                     topo_train: np.ndarray, *, hidden: int = 64, n_layers: int = 3,
                     n_heads: int = 4, dropout: float = 0.1, lr: float = 2e-3,
                     weight_decay: float = 1e-4, epochs: int = 45, batch_size: int = 256,
                     sensor_dropout: float = DROPOUT_RATE, seed: int = 0,
                     device: torch.device | None = None) -> ActiveGridGATv2:
    """Train ActiveGridGATv2 on GPU (Kaggle) or CPU with a fixed cosine schedule."""
    dev = device or get_device()
    torch.manual_seed(seed)
    if dev.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    rng = np.random.default_rng(seed)

    net = ActiveGridGATv2(in_features=X_train.shape[-1], hidden=hidden, n_layers=n_layers,
                          n_heads=n_heads, dropout=dropout)
    net.set_normalizer(X_train)
    net.to(dev)

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
            xb = x_all[idx]
            yb = y_all[idx]
            tb = t_all[idx]
            if sensor_dropout > 0.0:
                xb = xb.clone()
                mask = torch.from_numpy(rng.random(len(idx)) < sensor_dropout).to(dev)
                if mask.any():
                    d_rows = torch.nonzero(mask, as_tuple=False).squeeze(-1)
                    d_nodes = torch.from_numpy(rng.integers(0, n_nodes, size=len(d_rows))).to(dev)
                    xb[d_rows, d_nodes, :ag.N_ACTIVE_ELEC] = float("nan")
            opt.zero_grad(set_to_none=True)
            logits = net(xb, adj_all[tb], tie_all[tb])
            loss = F.cross_entropy(logits, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 2.0)
            opt.step()
        sched.step()
    net.eval()
    return net


def finetune_active_gat(base: ActiveGridGATv2, X_few: np.ndarray, y_few: np.ndarray,
                        adj: np.ndarray, is_tie: np.ndarray, topo_few: np.ndarray, *,
                        epochs: int = 25, lr: float = 5e-4, weight_decay: float = 1e-4,
                        batch_size: int = 64, sensor_dropout: float = DROPOUT_RATE,
                        seed: int = 0, device: torch.device | None = None) -> ActiveGridGATv2:
    dev = device or get_device()
    torch.manual_seed(seed)
    if dev.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    rng = np.random.default_rng(seed)

    net = copy.deepcopy(base).to(dev)
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
                    xb[d_rows, d_nodes, :ag.N_ACTIVE_ELEC] = float("nan")
            opt.zero_grad(set_to_none=True)
            loss = F.cross_entropy(net(xb, adj_all[tb], tie_all[tb]), yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 2.0)
            opt.step()
        sched.step()
    net.eval()
    return net


@torch.no_grad()
def predict_proba_gat(net: ActiveGridGATv2, X: np.ndarray, adj: np.ndarray, is_tie: np.ndarray,
                      topo_id: np.ndarray, batch_size: int = 1024,
                      device: torch.device | None = None) -> np.ndarray:
    """Return (E, N + 1) softmax probabilities."""
    dev = device or next(net.parameters()).device
    net.eval()
    adj_t = torch.from_numpy(adj.astype(np.float32)).to(dev)
    tie_t = torch.from_numpy(is_tie.astype(np.float32)).to(dev)
    out = []
    for start in range(0, len(X), batch_size):
        xb = torch.from_numpy(X[start:start + batch_size].astype(np.float32)).to(dev)
        tb = torch.from_numpy(topo_id[start:start + batch_size].astype(np.int64)).to(dev)
        probs = F.softmax(net(xb, adj_t[tb], tie_t[tb]), dim=-1).cpu().numpy()
        out.append(probs)
    return np.concatenate(out, axis=0).astype(np.float64)


# ---------------------------------------------------------------------------
# 4. Split Conformal Prediction — Adaptive Prediction Sets (Romano et al. 2020)
# ---------------------------------------------------------------------------

def aps_scores(probs: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Deterministic conservative APS nonconformity score S(x, y) = sum_{j: p_j >= p_y} p_j."""
    p_true = probs[np.arange(len(y)), y][:, None]
    return np.where(probs >= p_true - 1e-12, probs, 0.0).sum(axis=1)


def conformal_calibrate(probs_cal: np.ndarray, y_cal: np.ndarray, alpha: float = 0.05) -> float:
    """Finite-sample conformal quantile q_hat guaranteeing P(y in C(x)) >= 1 - alpha."""
    scores = aps_scores(probs_cal, y_cal)
    n = len(scores)
    q_level = min(1.0, np.ceil((n + 1) * (1.0 - alpha)) / n)
    return float(np.quantile(scores, q_level, method="higher"))


def conformal_predict_sets(probs: np.ndarray, q_hat: float) -> np.ndarray:
    """Return boolean membership matrix C of shape (E, C_classes) for threshold q_hat."""
    n_ev, n_cls = probs.shape
    order = np.argsort(-probs, axis=1)
    sorted_p = np.take_along_axis(probs, order, axis=1)
    csum = np.cumsum(sorted_p, axis=1)
    # Include every class up to and including the first index where cumulative prob >= q_hat.
    prev_csum = csum - sorted_p
    keep_sorted = prev_csum < q_hat
    keep_sorted[:, 0] = True                                       # never emit an empty set
    sets = np.zeros((n_ev, n_cls), dtype=bool)
    np.put_along_axis(sets, order, keep_sorted, axis=1)
    return sets


def evaluate_conformal(probs: np.ndarray, y: np.ndarray, q_hat: float,
                       nofault_class: int) -> dict[str, Any]:
    """Evaluate empirical coverage, set size, autonomous share/accuracy, and autonomous FPR."""
    sets = conformal_predict_sets(probs, q_hat)
    sizes = sets.sum(axis=1)
    covered = sets[np.arange(len(y)), y]

    auto = sizes == 1
    defer = sizes >= 2
    auto_pred = probs.argmax(axis=1)

    is_nf = y == nofault_class
    auto_nf_fpr = float((auto_pred[auto & is_nf] != nofault_class).mean()) if (auto & is_nf).any() else 0.0
    raw_nf_fpr = float((auto_pred[is_nf] != nofault_class).mean()) if is_nf.any() else 0.0

    return {
        "q_hat": round(float(q_hat), 5),
        "empirical_coverage": round(float(covered.mean()), 4),
        "avg_set_size": round(float(sizes.mean()), 3),
        "autonomous_share": round(float(auto.mean()), 4),
        "autonomous_accuracy": round(float((auto_pred[auto] == y[auto]).mean()), 4) if auto.any() else None,
        "raw_argmax_accuracy": round(float((auto_pred == y).mean()), 4),
        "defer_share": round(float(defer.mean()), 4),
        "defer_coverage": round(float(covered[defer].mean()), 4) if defer.any() else None,
        "autonomous_nofault_fpr": round(auto_nf_fpr, 4),
        "raw_nofault_fpr": round(raw_nf_fpr, 4),
    }


# ---------------------------------------------------------------------------
# 4b. Post-hoc conformal scores (research/active-grid-gnn/PLAN.md, Addendum A)
#     aps_det  : pre-registered deterministic APS (same as aps_scores above)
#     lac      : least-ambiguous classifier, S = 1 - p_y (Sadinle, Lei & Wasserman 2019)
#     aps_rand : randomized APS, S = sum_{p_j > p_y} p_j + U * p_y (Romano, Sesia & Candes 2020)
# ---------------------------------------------------------------------------

CONFORMAL_METHODS = ("aps_det", "lac", "aps_rand")


def conformal_scores(probs: np.ndarray, y: np.ndarray, method: str,
                     u: np.ndarray | None = None) -> np.ndarray:
    """Nonconformity score of the true label for each row (higher = less conforming)."""
    p_true = probs[np.arange(len(y)), y]
    if method == "aps_det":
        return aps_scores(probs, y)
    if method == "lac":
        return 1.0 - p_true
    if method == "aps_rand":
        if u is None:
            raise ValueError("aps_rand needs one uniform draw per row")
        above = np.where(probs > p_true[:, None], probs, 0.0).sum(axis=1)
        return above + u * p_true
    raise ValueError(f"unknown conformal method: {method}")


def conformal_quantile(scores: np.ndarray, alpha: float) -> float:
    """Finite-sample split-conformal quantile: the ceil((n+1)(1-alpha))-th smallest score."""
    n = len(scores)
    q_level = min(1.0, np.ceil((n + 1) * (1.0 - alpha)) / n)
    return float(np.quantile(scores, q_level, method="higher"))


def conformal_sets(probs: np.ndarray, q_hat: float, method: str,
                   u: np.ndarray | None = None) -> np.ndarray:
    """Boolean membership (E, C). `aps_det` never returns an empty set; `lac` and `aps_rand` may."""
    if method == "aps_det":
        return conformal_predict_sets(probs, q_hat)
    if method == "lac":
        return probs >= 1.0 - q_hat
    if method == "aps_rand":
        if u is None:
            raise ValueError("aps_rand needs one uniform draw per row")
        order = np.argsort(-probs, axis=1, kind="stable")
        sorted_p = np.take_along_axis(probs, order, axis=1)
        before = np.cumsum(sorted_p, axis=1) - sorted_p      # mass of strictly larger labels (ties: stable order)
        keep_sorted = before + u[:, None] * sorted_p <= q_hat
        sets = np.zeros_like(probs, dtype=bool)
        np.put_along_axis(sets, order, keep_sorted, axis=1)
        return sets
    raise ValueError(f"unknown conformal method: {method}")


def conformal_report(probs: np.ndarray, y: np.ndarray, sets: np.ndarray, nofault_class: int) -> dict[str, Any]:
    """Coverage (overall / fault / NO_FAULT), set sizes, and what an 'act only on a singleton' rule would do."""
    sizes = sets.sum(axis=1)
    covered = sets[np.arange(len(y)), y]
    single = sizes == 1
    pred = probs.argmax(axis=1)
    single_label = np.where(single, sets.argmax(axis=1), -1)
    is_nf = y == nofault_class
    is_f = ~is_nf

    def share(mask: np.ndarray, of: np.ndarray) -> float | None:
        return round(float(mask[of].mean()), 4) if of.any() else None

    auto_trip_on_nf = single & is_nf & (single_label != nofault_class)
    auto_right_fault = single & is_f & (single_label == y)
    return {
        "coverage": round(float(covered.mean()), 4),
        "coverage_fault": share(covered, is_f),
        "coverage_nofault": share(covered, is_nf),
        "avg_set_size": round(float(sizes.mean()), 3),
        "empty_share": round(float((sizes == 0).mean()), 4),
        "singleton_share": round(float(single.mean()), 4),
        "singleton_accuracy": round(float((single_label[single] == y[single]).mean()), 4) if single.any() else None,
        "raw_argmax_accuracy": round(float((pred == y).mean()), 4),
        "nofault_autonomous_trip_share": share(auto_trip_on_nf, is_nf),
        "fault_autonomous_correct_share": share(auto_right_fault, is_f),
    }


# ---------------------------------------------------------------------------
# Comprehensive active-grid metrics (overall, by topology, DER, R, NO_FAULT, missing sensor)
# ---------------------------------------------------------------------------

def evaluate_active(ds: ActiveGraphDataset, pred: np.ndarray,
                    fold_indices: list[np.ndarray] | None = None,
                    missing_hits: dict[str, int] | None = None) -> dict[str, Any]:
    nf = ds.nofault_class
    corr = pred == ds.y
    is_fault = ds.y < nf
    is_nf = ds.y == nf

    # Overall, fault-only zone accuracy, fault detection recall, and NO_FAULT false-positive rate.
    fpr_nf = float((pred[is_nf] != nf).mean()) if is_nf.any() else 0.0
    det_recall = float((pred[is_fault] != nf).mean()) if is_fault.any() else 0.0
    fault_zone_acc = float(corr[is_fault].mean()) if is_fault.any() else 0.0

    by_topo = {tname: round(float(corr[ds.topo_id == ti].mean()), 4)
               for ti, tname in enumerate(ds.topo_names)}
    by_topo_fault = {tname: round(float(corr[(ds.topo_id == ti) & is_fault].mean()), 4)
                     for ti, tname in enumerate(ds.topo_names)}
    by_kind = {k: round(float(corr[ds.event_kind == k].mean()), 4)
               for k in sorted(np.unique(ds.event_kind))}
    by_ftype = {ft: round(float(corr[ds.ftype == ft].mean()), 4)
                for ft in sorted(np.unique(ds.ftype))}

    slg = ds.ftype == "SLG"
    slg_by_r = {str(float(rv)): round(float(corr[slg & (ds.r == rv)].mean()), 4)
                for rv in sorted(np.unique(ds.r[slg]))}

    # Breakdown by DER penetration band: low (<15%), mid (15-30%), high (>=30%).
    der_bands = {
        "low_0_15pct":  round(float(corr[is_fault & (ds.der_pct < 0.15)].mean()), 4),
        "mid_15_30pct": round(float(corr[is_fault & (ds.der_pct >= 0.15) & (ds.der_pct < 0.30)].mean()), 4),
        "high_30_50pct": round(float(corr[is_fault & (ds.der_pct >= 0.30)].mean()), 4),
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
        "by_topology": by_topo,
        "by_topology_fault_only": by_topo_fault,
        "by_event_kind": by_kind,
        "by_fault_type": by_ftype,
        "slg_by_resistance": slg_by_r,
        "fault_acc_by_der_band": der_bands,
    }
    if fold_indices is not None:
        faccs = [float(corr[idx].mean()) for idx in fold_indices]
        out["fold_accuracies"] = [round(a, 4) for a in faccs]
        out["fold_std"] = round(float(np.std(faccs)), 4)
    if missing_hits is not None:
        per_dev = {d: float(h / len(ds.y)) for d, h in missing_hits.items()}
        out["missing_sensor_accuracy"] = per_dev
        out["missing_sensor_mean"] = float(np.mean(list(per_dev.values())))
        out["missing_sensor_min"] = float(np.min(list(per_dev.values())))
    return out
