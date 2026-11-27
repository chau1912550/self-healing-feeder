"""Coupling OpenDSS feeder currents with Tier-1 Edge HIF-Sensors (research/hif-fusion/PLAN.md).

For every converged OpenDSS event on a passive radial feeder (`shf/transfer.py`) or an active,
reconfigurable/looped feeder with DERs (`shf/active_grid.py`), this module extracts each switch's
pre-fault residual current `I_res_pre(d)`, incremental residual current `dI_res(d)`, and the
fault-point current `I_fault`, synthesizes a 1-second 122.88 kHz residual current waveform per
monitored switch through the frozen Tier-1 Edge HIF-Sensor (`shf/hif_edge.py`), and appends the
two feeder-independent edge outputs `(p_hif, hif_alarm)` to each node's live-sensor feature block:

  - Passive fused node features (23): 17 60-Hz live electrical + (p_hif, hif_alarm) + 4 tree structure.
  - Active  fused node features (28): 21 60-Hz live electrical + (p_hif, hif_alarm) + 5 grid state.

Fused datasets are written exclusively to isolated files `data/generated/hif_fusion_*.npz` and
never modify existing `data/generated/transfer_*.npz`, `active_*.npz`, or `results/`.

Simulation only. Quasi-steady harmonic superposition is a modeling assumption, not an EMTP
transient simulation and not field data.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import time
from pathlib import Path
from typing import Any

import numpy as np
import opendssdirect as dss

from . import active_grid as ag, config, faults, feeder, hif_edge as he, transfer

# ---------------------------------------------------------------------------
# Locked coupling assumptions (research/hif-fusion/PLAN.md §3.1 - §3.2)
# ---------------------------------------------------------------------------
# ASSUMPTION: a fault is modeled as an Emanuel arcing earth fault iff it is SLG,
# R >= 100 ohm, and fault-point current <= 45 A RMS (covers 100% of 100-400 ohm SLG
# on 4.16 kV IEEE 123-bus and 100% of 400-10,000 ohm SLG on 24.9 kV IEEE 34-bus).
ARC_MIN_R_OHM = 100.0
ARC_MAX_FAULT_CURRENT_A = 45.0
# ASSUMPTION: switches with incremental residual current below 0.05 A carry negligible
# fault return and receive zero arc/step injection.
ARC_MIN_DEVICE_DI_RES_A = 0.05
# ASSUMPTION: local pre-fault residual unbalance fed to the SCT-013-000 + 33 ohm burden
# front end is clipped to [1.0, 20.0] A RMS (the calibration range of hif-sensor).
BASE_RESIDUAL_CLIP_A = (1.0, 20.0)
# ASSUMPTION: on fault events, each closed switch independently experiences a concurrent
# background disturbance (uniform across the 6 non-"none" classes) with probability 0.25,
# matching hif-sensor/hif/waveforms.py:make_event().
FAULT_DISTURBANCE_PROB = 0.25

NON_NONE_DISTURBANCES: tuple[str, ...] = tuple(d for d in he.DISTURBANCES if d != "none")
SURFACE_NAMES: tuple[str, ...] = tuple(he.SURFACES.keys())

# ASSUMPTION: balanced mapping of OpenDSS active-grid NO_FAULT kinds to all 7 time-domain
# disturbance classes so every class (including hard negatives arc_welder, inrush,
# motor_start, nonlinear_fluct) is explicitly evaluated.
NOFAULT_LOAD_STEP_CYCLE: tuple[str, ...] = (
    "load_step", "inrush", "motor_start", "arc_welder", "nonlinear_fluct",
)
NOFAULT_CAP_SWITCH_CYCLE: tuple[str, ...] = ("cap_switch", "cap_switch", "none")
NOFAULT_PV_CLOUD_CYCLE: tuple[str, ...] = ("none", "nonlinear_fluct")

# ---------------------------------------------------------------------------
# Fused node feature schemas (research/hif-fusion/PLAN.md §2.2)
# ---------------------------------------------------------------------------
EDGE_NODE_FEATURES: list[str] = ["p_hif", "hif_alarm"]

N_PASSIVE_60HZ_ELEC = 17
PASSIVE_FUSED_FEATURES: list[str] = (
    list(transfer.FEATURES[:N_PASSIVE_60HZ_ELEC])
    + EDGE_NODE_FEATURES
    + list(transfer.FEATURES[N_PASSIVE_60HZ_ELEC:])
)
N_PASSIVE_FUSED_ELEC = N_PASSIVE_60HZ_ELEC + len(EDGE_NODE_FEATURES)  # 19 (0..18 live; 19..22 tree structure)

N_ACTIVE_60HZ_ELEC = ag.N_ACTIVE_ELEC                                  # 21
ACTIVE_FUSED_FEATURES: list[str] = (
    list(ag.ACTIVE_FEATURES[:N_ACTIVE_60HZ_ELEC])
    + EDGE_NODE_FEATURES
    + list(ag.ACTIVE_FEATURES[N_ACTIVE_60HZ_ELEC:])
)
N_ACTIVE_FUSED_ELEC = N_ACTIVE_60HZ_ELEC + len(EDGE_NODE_FEATURES)    # 23 (0..22 live; 23..27 grid state)

FUSED_OUT_DIR = config.GENERATED

# Exact per-device column order matching `shf/model.py:feature_columns(..., kind="full")`
# (15 features/device x 10 devices = 150 features on IEEE 123-bus).
ML_FULL_DEVICE_KEYS: tuple[str, ...] = (
    "Ia", "Ib", "Ic", "dIa", "dIb", "dIc", "I0", "dI0", "dI2",
    "Va", "Vb", "Vc", "dVa", "dVb", "dVc",
)


def _sample_realistic_arc(r_nom: float, ftype: str, rng: np.random.Generator) -> dict[str, Any]:
    """Sample Branch-10 intermittent arcing equivalent 60 Hz resistance.

    Uses `faults.sample_arc_resistance()` directly. For HV feeders where nominal
    `r_nom > 400` ohm (Active IEEE 34-bus at 24.9 kV with 1,000-10,000 ohm SLG),
    extends the upper cap proportionally to `max(HIF_R_EFF_MAX, 6.25 * r_nom)`
    (ASSUMPTION, research/hif-fusion-realistic/PLAN.md §3.1: keeps the 2500/400 = 6.25x
    ratio of 4.16 kV so 5-10 kohm faults are never artificially clipped down to 2.5 kohm).
    """
    arc = faults.sample_arc_resistance(r_nom, ftype, rng)
    r_nom_f = float(r_nom)
    r_eff_max = max(float(config.HIF_R_EFF_MAX), 6.25 * r_nom_f)
    if arc["is_arcing"] and r_eff_max > float(config.HIF_R_EFF_MAX):
        raw = (r_nom_f * float(arc["r_jitter"])) / (float(arc["arc_kappa"]) * float(arc["arc_duty"]))
        arc["r_eff"] = float(np.clip(raw, 0.5 * r_nom_f, r_eff_max))
    return arc


def _load_zone_indices(grid: transfer.Grid, base: list[tuple[str, float, float]]) -> np.ndarray:
    """Map each spot load in `base` to its switching-zone index in `grid.devices` (or -1)."""
    zone_idx = {d: i for i, d in enumerate(grid.devices)}
    bus_zone_lower = {b.lower(): z for b, z in grid.bus_zone.items()}
    return np.array(
        [zone_idx.get(bus_zone_lower.get(b, ""), -1) for b in feeder.load_buses(base)],
        dtype=int,
    )


def _ml_full_feature_names(devices: list[str] | tuple[str, ...]) -> list[str]:
    return [f"{d}_{k}" for d in devices for k in ML_FULL_DEVICE_KEYS]


def _ml_full_row(
    post: dict[str, dict[str, Any]],
    pre: dict[str, dict[str, Any]],
    devices: list[str] | tuple[str, ...],
) -> np.ndarray:
    """Extract 15 features/device in exact `shf.model.feature_columns(..., kind='full')` order."""
    feat_dict = faults.features(post, pre)
    return np.array(
        [feat_dict[f"{d}_{k}"] for d in devices for k in ML_FULL_DEVICE_KEYS],
        dtype=np.float32,
    )


# ---------------------------------------------------------------------------
# Feature manipulation & offline-sensor blanking helpers
# ---------------------------------------------------------------------------
def _live_elec_count(branch: str) -> tuple[int, int]:
    """Return (n_60hz_elec, n_fused_elec) for branch in {'passive', 'active'}."""
    if branch == "passive":
        return N_PASSIVE_60HZ_ELEC, N_PASSIVE_FUSED_ELEC
    if branch == "active":
        return N_ACTIVE_60HZ_ELEC, N_ACTIVE_FUSED_ELEC
    raise ValueError(f"unsupported branch: {branch!r} (expected 'passive' or 'active')")


def insert_edge_features(X_60hz: np.ndarray, edge_feats: np.ndarray, branch: str) -> np.ndarray:
    """Insert `(..., N, 2)` `(p_hif, hif_alarm)` right after the 60-Hz live electrical block."""
    n_elec, _ = _live_elec_count(branch)
    x = np.asarray(X_60hz, dtype=np.float32)
    e = np.asarray(edge_feats, dtype=np.float32)
    return np.concatenate([x[..., :n_elec], e, x[..., n_elec:]], axis=-1).astype(np.float32)


def strip_edge_features(X_fused: np.ndarray, branch: str) -> np.ndarray:
    """Remove `(p_hif, hif_alarm)` to recover the paired 60Hz-only tensor (21 or 26 features)."""
    n_60, n_fused = _live_elec_count(branch)
    x = np.asarray(X_fused, dtype=np.float32)
    return np.concatenate([x[..., :n_60], x[..., n_fused:]], axis=-1).astype(np.float32)


def blank_fused_sensor(X_fused: np.ndarray, node: int, branch: str) -> np.ndarray:
    """Blank switch `node` offline: sets BOTH 60-Hz electrical channels AND `(p_hif, hif_alarm)` to NaN.

    Structural / grid-state channels remain finite and untouched (PLAN.md §2.2 item 3).
    """
    _, n_fused = _live_elec_count(branch)
    out = np.asarray(X_fused, dtype=np.float32).copy()
    out[..., node, :n_fused] = np.nan
    return out


def apply_fused_sensor_dropout(
    X_fused: np.ndarray,
    rng: np.random.Generator,
    branch: str,
    rate: float = 0.15,
) -> np.ndarray:
    """Blank one random switch's live channels (60 Hz + edge) on a share of training events."""
    if rate <= 0.0:
        return X_fused
    _, n_fused = _live_elec_count(branch)
    out = np.asarray(X_fused, dtype=np.float32).copy()
    n_ev, n_nodes, _ = out.shape
    rows = np.flatnonzero(rng.random(n_ev) < rate)
    if len(rows):
        nodes = rng.integers(0, n_nodes, size=len(rows))
        out[rows, nodes, :n_fused] = np.nan
    return out


# ---------------------------------------------------------------------------
# OpenDSS residual current & fault current extraction
# ---------------------------------------------------------------------------
def fault_current_rms(fault_name: str = "Fault.F") -> float:
    """Read primary fault-point current magnitude (A RMS) from the active OpenDSS fault element."""
    dss.Circuit.SetActiveElement(fault_name)
    nph = max(1, int(dss.CktElement.NumPhases()))
    cur = dss.CktElement.Currents()
    if not cur or len(cur) < 2:
        return 0.0
    mags = [abs(complex(cur[2 * k], cur[2 * k + 1])) for k in range(min(nph, len(cur) // 2))]
    return float(max(mags)) if mags else 0.0


def extract_device_residuals(
    grid: transfer.Grid,
    pre: dict[str, dict[str, Any]],
    post: dict[str, dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray]:
    """Extract `(I_res_pre, dI_res)` in primary A RMS for every device in `grid.devices`.

    `I_res_pre(d) = |Ia_pre + Ib_pre + Ic_pre|`
    `dI_res(d)    = |(Ia + Ib + Ic)_post - (Ia + Ib + Ic)_pre|`
    """
    n = len(grid.devices)
    i_res_pre = np.zeros(n, dtype=np.float64)
    di_res = np.zeros(n, dtype=np.float64)
    for k, d in enumerate(grid.devices):
        i_pre_sum = complex(np.sum(pre[d]["i"]))
        i_post_sum = complex(np.sum(post[d]["i"]))
        i_res_pre[k] = abs(i_pre_sum)
        di_res[k] = abs(i_post_sum - i_pre_sum)
    return i_res_pre, di_res


def is_arcing_hif(ftype: str, r_ohm: float, i_fault_a: float) -> bool:
    """Locked arcing condition (PLAN.md §3.1): SLG with R >= 100 ohm and I_fault <= 45 A RMS."""
    return (
        str(ftype).upper() == "SLG"
        and float(r_ohm) >= ARC_MIN_R_OHM
        and 0.0 < float(i_fault_a) <= ARC_MAX_FAULT_CURRENT_A
    )


def choose_nofault_disturbance(event_kind: str, kind_counter: int) -> str:
    """Deterministic balanced mapping from OpenDSS NO_FAULT transient kind to all 7 disturbances."""
    if event_kind == "cap_switch":
        return NOFAULT_CAP_SWITCH_CYCLE[kind_counter % len(NOFAULT_CAP_SWITCH_CYCLE)]
    if event_kind == "pv_cloud":
        return NOFAULT_PV_CLOUD_CYCLE[kind_counter % len(NOFAULT_PV_CLOUD_CYCLE)]
    if event_kind == "load_step":
        return NOFAULT_LOAD_STEP_CYCLE[kind_counter % len(NOFAULT_LOAD_STEP_CYCLE)]
    return "none"


def passive_arc_path_mask(parent: np.ndarray, fault_zone: int) -> np.ndarray:
    """Boolean mask `(N,)` of switches on the radial substation-to-fault path.

    Kirchhoff harmonic current-division physics: on a passive radial tree with a single
    substation source at the root, nonlinear arcing harmonic current generated at `fault_zone`
    returns to the substation strictly along `ancestors(fault_zone)`. Healthy sibling or
    downstream branches outside this path experience only linear 60 Hz voltage-sag load/capacitor
    response, never a nonlinear Emanuel arc waveform.
    """
    n = len(parent)
    mask = np.zeros(n, dtype=bool)
    cur = int(fault_zone)
    seen = 0
    while 0 <= cur < n and not mask[cur] and seen < n:
        mask[cur] = True
        cur = int(parent[cur])
        seen += 1
    return mask


def active_arc_path_mask(
    adj_t: np.ndarray,
    is_closed: np.ndarray,
    fault_zone: int,
    source_node: int = 0,
) -> np.ndarray:
    """Boolean mask `(N,)` of closed switches on any simple path from `source_node` to `fault_zone`.

    Exact for both radial/reconfigured trees (unique upstream path) and closed-loop topologies
    (every energized branch of a loop between substation and fault, excluding open switches and
    healthy radial stubs behind or beside the fault).
    """
    n = len(is_closed)
    closed = np.asarray(is_closed, dtype=bool)
    mask = np.zeros(n, dtype=bool)
    if not (0 <= fault_zone < n) or not (0 <= source_node < n):
        return mask
    if not (closed[source_node] and closed[fault_zone]):
        return mask
    if source_node == fault_zone:
        mask[source_node] = True
        return mask

    adj_list: list[list[int]] = [[] for _ in range(n)]
    for u in range(n):
        if not closed[u]:
            continue
        for v in range(n):
            if u != v and closed[v] and adj_t[u, v] > 0.5:
                adj_list[u].append(v)

    visited = [False] * n
    path: list[int] = []

    def _dfs(u: int) -> None:
        visited[u] = True
        path.append(u)
        if u == fault_zone:
            for node in path:
                mask[node] = True
        else:
            for v in adj_list[u]:
                if not visited[v]:
                    _dfs(v)
        path.pop()
        visited[u] = False

    _dfs(source_node)
    return mask


# ---------------------------------------------------------------------------
# Event-level Tier-1 Edge HIF-Sensor synthesis (per switch)
# ---------------------------------------------------------------------------
def synthesize_event_edge(
    i_res_pre: np.ndarray,
    di_res: np.ndarray,
    is_closed: np.ndarray,
    model: he.EdgeModel,
    rng: np.random.Generator,
    *,
    is_arcing: bool,
    is_nofault: bool = False,
    surface: str | None = None,
    nofault_disturbance: str | None = None,
    nofault_kind: str | None = None,
    arc_duty: float | None = None,
    di_res_drift: np.ndarray | None = None,
    arc_path_mask: np.ndarray | None = None,
    interlock_open_switches: bool = True,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Synthesize 1-second 122.88 kHz waveforms for all `N` switches of one event and score via frozen int8 MLP.

    When `arc_duty` / `di_res_drift` are provided (`realistic=True`, research/hif-fusion-realistic/PLAN.md §3.2):
      - `di_res` carries the fault-only incremental residual current attenuated by `r_eff`
        (`|I_res(post) - I_res(post_drift)|`), scaled onto an Emanuel arc whose cycle restrike
        dropout matches `arc_duty` (`p_off = clip(1 - arc_duty, 0, 0.65)`).
      - `di_res_drift` carries the linear 60 Hz pre-to-post load-drift residual current
        (`|I_res(post_drift) - I_res(pre)|`) and is injected strictly as a linear 60 Hz step
        (never modulated by the Emanuel arc).

    Returns:
      - `edge_feats`: `(N, 2)` float32 array `[p_hif, hif_alarm]`, finite with `p_hif in [0, 1]`.
      - `info`: metadata dict (`surface`, `edge_disturbance`, `device_disturbances`, `start_cycle`, `is_arcing`).
    """
    t = he.standard_time_grid()
    n_dev = len(i_res_pre)
    start_cycle = int(rng.integers(12, 41))
    t0 = (he.WARMUP + start_cycle) / he.F_LINE

    i_arc_unit: np.ndarray | None = None
    chosen_surface = "none"
    if is_arcing and not is_nofault:
        chosen_surface = surface or str(SURFACE_NAMES[int(rng.integers(0, len(SURFACE_NAMES)))])
        arc_raw = he._arc(t, t0, rng, he.SURFACES[chosen_surface], arc_duty=arc_duty)
        tail = arc_raw[-20 * he.N_CYCLE * he.OVERSAMPLE:]
        rms_tail = float(np.sqrt(np.mean(tail ** 2)))
        if rms_tail > 1e-9:
            i_arc_unit = arc_raw / rms_tail
        elif arc_duty is not None:
            # ASSUMPTION (research/hif-fusion-realistic/PLAN.md §3.2): if high restrike dropout
            # extinguishes all last 20 cycles by chance, normalize by full post-event RMS.
            post_mask = t >= t0
            rms_post = float(np.sqrt(np.mean(arc_raw[post_mask] ** 2))) if np.any(post_mask) else 0.0
            i_arc_unit = (arc_raw / rms_post) if rms_post > 1e-9 else np.zeros_like(arc_raw)
        else:
            i_arc_unit = np.zeros_like(arc_raw)

    # Pre-allocate primary current waveforms (N, N_SIM_SAMPLES) for batched Butterworth filtering.
    prim = np.zeros((n_dev, he.N_SIM_SAMPLES), dtype=np.float64)
    dev_disturbances: list[str] = []
    event_disturbance = "none"
    if is_nofault:
        event_disturbance = nofault_disturbance or "none"

    on_t0 = (t >= t0).astype(np.float64)
    for k in range(n_dev):
        if not bool(is_closed[k]):
            # ASSUMPTION: an open switch carries 0 A primary current; ADC sees mid-rail bias + 1.5 LSB noise only.
            dev_disturbances.append("open")
            continue

        base_rms = float(np.clip(i_res_pre[k], BASE_RESIDUAL_CLIP_A[0], BASE_RESIDUAL_CLIP_A[1]))
        force_inv = bool(is_nofault and nofault_kind == "pv_cloud" and event_disturbance == "none")
        sig, a1, ph = he.make_base_residual(t, rng, base_rms, force_inverter_noise=force_inv)

        di_k = float(di_res[k])
        on_arc_path = True if arc_path_mask is None else bool(arc_path_mask[k])
        if is_arcing and not is_nofault and i_arc_unit is not None and on_arc_path:
            # ASSUMPTION (PLAN.md §3.1): quasi-steady current-division scaling of the event arc waveform
            # strictly along energized source-to-fault return paths (Kirchhoff harmonic current division).
            if di_k >= ARC_MIN_DEVICE_DI_RES_A:
                sig = sig + di_k * i_arc_unit
            if di_res_drift is not None:
                di_drift_k = float(di_res_drift[k])
                if di_drift_k >= ARC_MIN_DEVICE_DI_RES_A:
                    # ASSUMPTION (research/hif-fusion-realistic/PLAN.md §3.2): pre->post load drift
                    # is injected strictly as a linear 60 Hz step, never as an Emanuel arc.
                    ph_drift = float(rng.uniform(0.0, he.TWO_PI))
                    sig = sig + on_t0 * (di_drift_k * np.sqrt(2.0)) * he._sin_harmonic(1, ph_drift, t)
        else:
            # Non-arcing faults (3PH, LL, LLG, low-R SLG), NO_FAULT transients, and healthy switches
            # outside the source-to-fault arc return path carry strictly linear 60 Hz residual current
            # shifts (voltage-sag ZIP/capacitor response + load drift), never a nonlinear Emanuel arc.
            di_linear = di_k
            if di_res_drift is not None and is_arcing and not is_nofault:
                di_linear = di_k + float(di_res_drift[k])
            if di_linear >= ARC_MIN_DEVICE_DI_RES_A:
                ph_step = float(rng.uniform(0.0, he.TWO_PI))
                sig = sig + on_t0 * (di_linear * np.sqrt(2.0)) * he._sin_harmonic(1, ph_step, t)

        if is_nofault:
            dist_k = event_disturbance
            t1 = t0
        else:
            if rng.random() < FAULT_DISTURBANCE_PROB:
                dist_k = str(NON_NONE_DISTURBANCES[int(rng.integers(0, len(NON_NONE_DISTURBANCES)))])
            else:
                dist_k = "none"
            t1 = (he.WARMUP + int(rng.integers(0, he.N_CYCLES))) / he.F_LINE

        dev_disturbances.append(dist_k)
        if dist_k != "none":
            sig = sig + he._disturb(t, t1, rng, dist_k, a1, ph)
        prim[k] = sig

    # Batched 4th-order Butterworth anti-alias filter + 12-bit ADC quantization across all N switches.
    codes = he.sense(prim, rng)
    amps_all = he.codes_to_amps(codes)[:, he.WARMUP * he.N_CYCLE:]

    edge_feats = np.zeros((n_dev, 2), dtype=np.float32)
    for k in range(n_dev):
        if interlock_open_switches and not bool(is_closed[k]):
            # IEEE C37.2 52a open-switch interlock: a de-energized open switch (0 A primary +
            # 1.5 LSB ADC quantization floor) must not be scored by an energized-current (1-20 A)
            # arcing MLP, which otherwise triggers 100% spurious HIF alarms on pure white noise.
            edge_feats[k, 0] = np.float32(0.0)
            edge_feats[k, 1] = np.float32(0.0)
            continue
        p_hif, hif_alarm = he.score_waveform(amps_all[k], model, start_cycle=start_cycle)
        edge_feats[k, 0] = np.float32(p_hif)
        edge_feats[k, 1] = np.float32(hif_alarm)

    if not is_nofault:
        # Record the disturbance on the highest-residual closed switch (or 'none') for event metadata.
        closed_idx = np.flatnonzero(is_closed)
        if len(closed_idx):
            top = int(closed_idx[int(np.argmax(di_res[closed_idx]))])
            event_disturbance = dev_disturbances[top]

    info = {
        "surface": chosen_surface,
        "edge_disturbance": event_disturbance,
        "device_disturbances": dev_disturbances,
        "start_cycle": start_cycle,
        "is_arcing": bool(is_arcing and not is_nofault),
    }
    return edge_feats, info


def fuse_passive_event(
    grid: transfer.Grid,
    pre_meas: dict[str, dict[str, Any]],
    post_meas: dict[str, dict[str, Any]],
    struct: np.ndarray,
    model: he.EdgeModel,
    rng: np.random.Generator,
    *,
    ftype: str,
    r_ohm: float,
    i_fault_a: float,
    pre_clean: dict[str, dict[str, Any]] | None = None,
    post_clean: dict[str, dict[str, Any]] | None = None,
    surface: str | None = None,
    arc_duty: float | None = None,
    di_res_drift: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Fuse one passive OpenDSS event into `(N, 23)` node features."""
    x_60 = transfer.node_features(grid, pre_meas, post_meas, struct)
    i_res_pre, di_res = extract_device_residuals(grid, pre_clean or pre_meas, post_clean or post_meas)
    is_closed = np.ones(len(grid.devices), dtype=bool)
    arcing = is_arcing_hif(ftype, r_ohm, i_fault_a)
    edge_feats, info = synthesize_event_edge(
        i_res_pre, di_res, is_closed, model, rng,
        is_arcing=arcing, is_nofault=False, surface=surface,
        arc_duty=arc_duty, di_res_drift=di_res_drift,
    )
    info["i_res_pre"] = i_res_pre
    info["di_res"] = di_res
    return insert_edge_features(x_60, edge_feats, "passive"), info


def fuse_active_event(
    grid: transfer.Grid,
    topo: ag.TopoSpec,
    adj_t: np.ndarray,
    pre_meas: dict[str, dict[str, Any]],
    post_meas: dict[str, dict[str, Any]],
    der_kw_by_zone: dict[str, float],
    model: he.EdgeModel,
    rng: np.random.Generator,
    *,
    ftype: str,
    r_ohm: float,
    i_fault_a: float,
    event_kind: str = "fault",
    nofault_counter: int = 0,
    pre_clean: dict[str, dict[str, Any]] | None = None,
    post_clean: dict[str, dict[str, Any]] | None = None,
    surface: str | None = None,
    nofault_disturbance: str | None = None,
    arc_duty: float | None = None,
    di_res_drift: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Fuse one active-grid OpenDSS event (fault or NO_FAULT) into `(N, 28)` node features."""
    x_60 = ag.active_node_features(grid, topo, adj_t, pre_meas, post_meas, der_kw_by_zone)
    i_res_pre, di_res = extract_device_residuals(grid, pre_clean or pre_meas, post_clean or post_meas)
    is_closed = np.array([d not in topo.open_devices for d in grid.devices], dtype=bool)
    is_nf = (event_kind != "fault") or (str(ftype).upper() == "NO_FAULT")
    arcing = (not is_nf) and is_arcing_hif(ftype, r_ohm, i_fault_a)
    nf_dist = (nofault_disturbance or choose_nofault_disturbance(event_kind, nofault_counter)) if is_nf else None
    edge_feats, info = synthesize_event_edge(
        i_res_pre, di_res, is_closed, model, rng,
        is_arcing=arcing,
        is_nofault=is_nf,
        surface=surface,
        nofault_disturbance=nf_dist,
        nofault_kind=event_kind if is_nf else None,
        arc_duty=arc_duty,
        di_res_drift=di_res_drift,
    )
    info["i_res_pre"] = i_res_pre
    info["di_res"] = di_res
    return insert_edge_features(x_60, edge_feats, "active"), info


# ---------------------------------------------------------------------------
# Parallel/batch Tier-1 synthesis worker (deterministic per-event SeedSequence)
# ---------------------------------------------------------------------------
def _synthesize_chunk(args: tuple[Any, ...]) -> tuple[np.ndarray, list[str], list[str]]:
    (
        i_res_pre_chunk,
        di_res_chunk,
        is_closed_chunk,
        is_arcing_chunk,
        is_nofault_chunk,
        nf_dist_chunk,
        nf_kind_chunk,
        seeds_chunk,
        layers,
        threshold,
        arc_duty_chunk,
        di_res_drift_chunk,
        arc_path_chunk,
    ) = args
    model = he.EdgeModel(layers=layers, threshold=threshold, source="worker")
    n_ev, n_dev = i_res_pre_chunk.shape
    out = np.zeros((n_ev, n_dev, 2), dtype=np.float32)
    surfaces: list[str] = []
    dists: list[str] = []
    for idx in range(n_ev):
        rng = np.random.default_rng(seeds_chunk[idx])
        duty_i = None if arc_duty_chunk is None else float(arc_duty_chunk[idx])
        drift_i = None if di_res_drift_chunk is None else di_res_drift_chunk[idx]
        path_i = None if arc_path_chunk is None else arc_path_chunk[idx]
        ef, info = synthesize_event_edge(
            i_res_pre_chunk[idx],
            di_res_chunk[idx],
            is_closed_chunk[idx],
            model,
            rng,
            is_arcing=bool(is_arcing_chunk[idx]),
            is_nofault=bool(is_nofault_chunk[idx]),
            nofault_disturbance=nf_dist_chunk[idx],
            nofault_kind=nf_kind_chunk[idx],
            arc_duty=duty_i,
            di_res_drift=drift_i,
            arc_path_mask=path_i,
        )
        out[idx] = ef
        surfaces.append(str(info["surface"]))
        dists.append(str(info["edge_disturbance"]))
    return out, surfaces, dists


def _run_edge_synthesis_batch(
    i_res_pre: np.ndarray,
    di_res: np.ndarray,
    is_closed: np.ndarray,
    is_arcing: np.ndarray,
    is_nofault: np.ndarray,
    nf_dist: list[str | None],
    nf_kind: list[str | None],
    model: he.EdgeModel,
    seed: int,
    n_workers: int = 1,
    verbose: bool = True,
    label: str = "edge",
    *,
    arc_duty: np.ndarray | None = None,
    di_res_drift: np.ndarray | None = None,
    arc_path_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Deterministically synthesize Tier-1 `(p_hif, hif_alarm)` for all events (optional multi-process)."""
    t0 = time.time()
    n_ev = len(i_res_pre)
    child_seeds = np.random.SeedSequence(seed + 7919).spawn(n_ev)

    workers = max(1, int(n_workers))
    if workers == 1 or n_ev < 32:
        edge_out, surfaces, dists = _synthesize_chunk((
            i_res_pre, di_res, is_closed, is_arcing, is_nofault,
            nf_dist, nf_kind, child_seeds, model.layers, model.threshold,
            arc_duty, di_res_drift, arc_path_mask,
        ))
    else:
        n_chunks = min(workers * 4, n_ev)
        splits = np.array_split(np.arange(n_ev), n_chunks)
        tasks = [
            (
                i_res_pre[sl],
                di_res[sl],
                is_closed[sl],
                is_arcing[sl],
                is_nofault[sl],
                [nf_dist[i] for i in sl],
                [nf_kind[i] for i in sl],
                [child_seeds[i] for i in sl],
                model.layers,
                model.threshold,
                None if arc_duty is None else arc_duty[sl],
                None if di_res_drift is None else di_res_drift[sl],
                None if arc_path_mask is None else arc_path_mask[sl],
            )
            for sl in splits if len(sl) > 0
        ]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            parts = list(pool.map(_synthesize_chunk, tasks))
        edge_out = np.concatenate([p[0] for p in parts], axis=0)
        surfaces = [s for p in parts for s in p[1]]
        dists = [d for p in parts for d in p[2]]

    if verbose:
        print(f"  [{label}] synthesized {n_ev} events x {i_res_pre.shape[1]} switches "
              f"({int(is_arcing.sum())} arcing) in {time.time() - t0:.1f} s")
    return edge_out, np.array(surfaces, dtype=str), np.array(dists, dtype=str)


# ---------------------------------------------------------------------------
# Full fused dataset sweeps (isolated outputs in data/generated/hif_fusion_*.npz)
# ---------------------------------------------------------------------------
def sweep_passive_fusion(
    name: str,
    model: he.EdgeModel,
    *,
    seed: int = 0,
    scenarios: int | None = None,
    max_cases: int | None = None,
    out_path: Path | str | None = None,
    n_workers: int = 1,
    verbose: bool = True,
    realistic: bool = False,
) -> dict[str, Any]:
    """Run passive OpenDSS fault sweep + Tier-1 Edge HIF-Sensor fusion.

    When `realistic=False` (default), preserves the legacy clean 60-Hz sweep and writes
    `data/generated/hif_fusion_passive_<name>.npz`.
    When `realistic=True` (Branch 10, `research/hif-fusion-realistic/PLAN.md`), applies
    hierarchical zone loading + pre/post drift, intermittent arcing `r_eff` for SLG >= 100 ohm,
    systematic CT/PT bias + additive noise floors, physically separates fault-only residual
    current `dI_res` from linear load-drift current `dI_res_drift`, synchronizes `arc_duty`
    into Tier-1 `_arc()`, and writes isolated `data/generated/hif_fusion_realistic_passive_<name>.npz`
    (plus 150-dim `X_ml_full` for `ieee123`).

    Never touches existing `data/generated/transfer_<name>.npz`, `data/generated/hif_fusion_*.npz`
    (when `realistic=True`), or `results/`.
    """
    t0 = time.time()
    transfer.load_feeder(name)
    grid = transfer.study_grid() if name == "ieee123" else transfer.placement_rule(name)
    if name == "ieee123":
        feeder.set_normal_configuration()

    scenarios = scenarios or config.SCENARIOS_PER_CASE
    rng = np.random.default_rng(seed)
    cases = transfer.fault_cases(grid)
    if max_cases is not None and max_cases < len(cases):
        idx = np.linspace(0, len(cases) - 1, int(max_cases), dtype=int)
        cases = [cases[i] for i in idx]
    base = feeder.base_loads()
    struct = transfer.structure(grid)
    first = grid.members[grid.devices[0]][0]
    p0 = feeder.bus_phases(first)[0]
    feeder.cmd(f"New Fault.F phases=1 bus1={first}.{p0} bus2={first}.0 r=1 enabled=no")

    load_zone_idx = _load_zone_indices(grid, base) if realistic else None
    n_zones = len(grid.devices)
    if realistic:
        feeder.scale_loads(base, np.ones(len(base)))
        feeder.set_load_level(1.0)
        feeder.reset_regulators()
        feeder.solve(controls=True)

    index = {d: i for i, d in enumerate(grid.devices)}
    bus_zone = grid.bus_zone
    collect_ml_full = bool(realistic and name == "ieee123")

    X60_list, y_list, meta = [], [], []
    ires_pre_list, dires_list, dires_drift_list, ifault_list, arcing_list = [], [], [], [], []
    r_eff_list, arc_kappa_list, arc_duty_list = [], [], []
    X_ml_full_list: list[np.ndarray] = []

    for s in range(scenarios):
        for c in cases:
            mult = float(rng.uniform(*config.LOAD_MULT_RANGE))
            if realistic:
                assert load_zone_idx is not None
                f_pre, f_post = faults.sample_load_factors(load_zone_idx, n_zones, rng, realistic=True)
                feeder.scale_loads(base, f_pre)
                feeder.set_load_level(mult)
                feeder.cmd("Edit Fault.F enabled=no")
                ok_pre = feeder.solve(controls=True)
                pre_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
                bias = faults.sample_ct_pt_bias(grid.devices, rng)
                pre = faults._perturb(
                    pre_clean, rng, bias=bias,
                    floor_i=config.NOISE_I_FLOOR_A, floor_v=config.NOISE_V_FLOOR_PU,
                )

                feeder.scale_loads(base, f_post)
                arc = _sample_realistic_arc(c["r"], c["ftype"], rng)
                if arc["is_arcing"]:
                    feeder.cmd("Edit Fault.F enabled=no")
                    ok_drift = feeder.solve(controls=False)
                    post_drift_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
                    spec = f"{c['spec'].rsplit(' r=', 1)[0]} r={arc['r_eff']:.6f}"
                    feeder.cmd(f"Edit Fault.F {spec} enabled=yes")
                    ok_post = feeder.solve(controls=False)
                    post_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
                    i_flt = fault_current_rms("Fault.F") if ok_post else 0.0
                    arcing_now = is_arcing_hif(c["ftype"], float(c["r"]), i_flt)
                    if arcing_now:
                        ir_pre, di_drift = extract_device_residuals(grid, pre_clean, post_drift_clean)
                        _, dir_post = extract_device_residuals(grid, post_drift_clean, post_clean)
                    else:
                        ir_pre, dir_post = extract_device_residuals(grid, pre_clean, post_clean)
                        di_drift = np.zeros_like(dir_post)
                    ok_all = bool(ok_pre and ok_drift and ok_post)
                else:
                    feeder.cmd(f"Edit Fault.F {c['spec']} enabled=yes")
                    ok_post = feeder.solve(controls=False)
                    post_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
                    i_flt = fault_current_rms("Fault.F") if ok_post else 0.0
                    arcing_now = False
                    ir_pre, dir_post = extract_device_residuals(grid, pre_clean, post_clean)
                    di_drift = np.zeros_like(dir_post)
                    ok_all = bool(ok_pre and ok_post)

                post = faults._perturb(
                    post_clean, rng, bias=bias,
                    floor_i=config.NOISE_I_FLOOR_A, floor_v=config.NOISE_V_FLOOR_PU,
                )
                r_eff_list.append(float(arc["r_eff"]))
                arc_kappa_list.append(float(arc["arc_kappa"]))
                arc_duty_list.append(float(arc["arc_duty"]))
                dires_drift_list.append(di_drift)
                if collect_ml_full:
                    X_ml_full_list.append(_ml_full_row(post, pre, grid.devices))
            else:
                spread = np.clip(rng.normal(1.0, config.LOAD_SPREAD, len(base)), 0.3, 1.7)
                feeder.scale_loads(base, spread)
                feeder.set_load_level(mult)
                feeder.cmd("Edit Fault.F enabled=no")
                ok_pre = feeder.solve(controls=True)
                pre_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
                pre = faults._perturb(pre_clean, rng)

                feeder.cmd(f"Edit Fault.F {c['spec']} enabled=yes")
                ok_post = feeder.solve(controls=False)
                post_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
                post = faults._perturb(post_clean, rng)
                i_flt = fault_current_rms("Fault.F") if ok_post else 0.0
                ir_pre, dir_post = extract_device_residuals(grid, pre_clean, post_clean)
                arcing_now = is_arcing_hif(c["ftype"], float(c["r"]), i_flt)
                ok_all = bool(ok_pre and ok_post)

            X60_list.append(transfer.node_features(grid, pre, post, struct))
            y_list.append(index[bus_zone[c["bus"]]])
            ires_pre_list.append(ir_pre)
            dires_list.append(dir_post)
            ifault_list.append(i_flt)
            arcing_list.append(arcing_now)
            meta.append((c["bus"], c["ftype"], c["phases"], float(c["r"]), s, mult, ok_all))
        if verbose:
            tag = "realistic " if realistic else ""
            print(f"  [passive {tag}{name}] OpenDSS scenario {s + 1}/{scenarios}: {len(cases)} faults ({time.time() - t0:.1f} s)")

    # Restore clean circuit state.
    feeder.cmd("Edit Fault.F enabled=no")
    feeder.scale_loads(base, np.ones(len(base)))
    feeder.set_load_level(1.0)
    if realistic:
        feeder.reset_regulators()
        feeder.solve(controls=True)

    X60 = np.stack(X60_list).astype(np.float32)
    i_res_pre_arr = np.stack(ires_pre_list).astype(np.float32)
    di_res_arr = np.stack(dires_list).astype(np.float32)
    is_closed_arr = np.ones((len(y_list), len(grid.devices)), dtype=bool)
    is_arcing_arr = np.array(arcing_list, dtype=bool)
    is_nofault_arr = np.zeros(len(y_list), dtype=bool)
    arc_duty_arr = np.array(arc_duty_list, dtype=np.float64) if realistic else None
    di_res_drift_arr = np.stack(dires_drift_list).astype(np.float32) if realistic else None

    parent_idx = np.array([index[grid.parent[d]] if grid.parent[d] else -1 for d in grid.devices], dtype=np.int64)
    arc_path_arr = (
        np.stack([passive_arc_path_mask(parent_idx, yi) for yi in y_list]).astype(bool)
        if realistic else None
    )

    edge_feats, surfaces, dists = _run_edge_synthesis_batch(
        i_res_pre_arr, di_res_arr, is_closed_arr, is_arcing_arr, is_nofault_arr,
        [None] * len(y_list), [None] * len(y_list),
        model=model, seed=seed, n_workers=n_workers, verbose=verbose,
        label=f"passive {'realistic ' if realistic else ''}{name}",
        arc_duty=arc_duty_arr,
        di_res_drift=di_res_drift_arr,
        arc_path_mask=arc_path_arr,
    )
    X_fused = insert_edge_features(X60, edge_feats, "passive")

    FUSED_OUT_DIR.mkdir(parents=True, exist_ok=True)
    m = np.array(meta, dtype=object)
    default_name = f"hif_fusion_realistic_passive_{name}.npz" if realistic else f"hif_fusion_passive_{name}.npz"
    npz_path = Path(out_path) if out_path is not None else (FUSED_OUT_DIR / default_name)
    npz_path.parent.mkdir(parents=True, exist_ok=True)
    conv = m[:, 6].astype(bool)

    payload: dict[str, Any] = dict(
        X=X_fused,
        y=np.array(y_list, dtype=np.int64),
        parent=parent_idx,
        features=np.array(PASSIVE_FUSED_FEATURES, dtype=str),
        devices=np.array(grid.devices, dtype=str),
        bus=m[:, 0].astype(str),
        ftype=m[:, 1].astype(str),
        phases=m[:, 2].astype(str),
        r=m[:, 3].astype(float),
        scenario=m[:, 4].astype(int),
        load_mult=m[:, 5].astype(float),
        converged=conv,
        i_fault=np.array(ifault_list, dtype=np.float32),
        is_arcing=is_arcing_arr,
        arc_surface=surfaces,
        edge_disturbance=dists,
        i_res_pre=i_res_pre_arr,
        di_res=di_res_arr,
        model_source=np.array(model.source),
        model_sha256=np.array(model.sha256 or ""),
        model_threshold=np.float64(model.threshold),
    )
    if realistic:
        payload["r_eff"] = np.array(r_eff_list, dtype=float)
        payload["arc_kappa"] = np.array(arc_kappa_list, dtype=float)
        payload["arc_duty"] = np.array(arc_duty_list, dtype=float)
        payload["realistic_mode"] = np.bool_(True)
        payload["di_res_drift"] = di_res_drift_arr
        if collect_ml_full:
            payload["X_ml_full"] = np.stack(X_ml_full_list).astype(np.float32)
            payload["ml_full_features"] = np.array(_ml_full_feature_names(grid.devices), dtype=str)

    np.savez_compressed(npz_path, **payload)

    summary: dict[str, Any] = {
        "branch": "passive",
        "feeder": name,
        "realistic_mode": bool(realistic),
        "path": str(npz_path),
        "events_total": int(len(y_list)),
        "converged": int(conv.sum()),
        "arcing_events": int(is_arcing_arr[conv].sum()),
        "surface_counts": {s: int((surfaces[conv] == s).sum()) for s in SURFACE_NAMES},
        "features": PASSIVE_FUSED_FEATURES,
        "devices": list(grid.devices),
        "model_source": model.source,
        "model_sha256": model.sha256,
        "model_params": model.n_params,
        "model_bytes": model.n_bytes,
        "model_threshold": model.threshold,
        "runtime_s": round(time.time() - t0, 1),
    }
    if realistic and arc_duty_arr is not None:
        summary["intermittent_arc_events"] = int((is_arcing_arr[conv] & (arc_duty_arr[conv] < 1.0)).sum())
        summary["continuous_arc_events"] = int((is_arcing_arr[conv] & (arc_duty_arr[conv] >= 1.0)).sum())
    return summary


def sweep_active_fusion(
    name: str,
    model: he.EdgeModel,
    *,
    seed: int = 0,
    scenarios_per_topo: int = 1,
    nofault_share: float = 0.15,
    max_cases: int | None = None,
    max_nofault_per_topo: int | None = None,
    out_path: Path | str | None = None,
    n_workers: int = 1,
    verbose: bool = True,
    realistic: bool = False,
) -> dict[str, Any]:
    """Run active-grid OpenDSS sweep + Tier-1 Edge HIF-Sensor fusion.

    Includes all topologies (radial, reconfigured, closed-loop), 0-50% Model=7 DERs, voltage-scaled
    HIFs, 5 Emanuel surfaces, and NO_FAULT operational transients spanning all 7 disturbances.
    When `realistic=False` (default), preserves the legacy sweep and writes
    `data/generated/hif_fusion_active_<name>.npz`.
    When `realistic=True` (Branch 10, `research/hif-fusion-realistic/PLAN.md`), applies zone loading
    + pre/post drift (including on NO_FAULT events), intermittent arcing `r_eff` (with voltage-scaled
    upper clip `max(HIF_R_EFF_MAX, 6.25 * r_nom)` for 24.9 kV HIFs), CT/PT systematic bias + additive
    noise floors, physical `post_drift_clean` separation for arcing events, and synchronized `arc_duty`
    in Tier-1 `_arc()`, writing isolated `data/generated/hif_fusion_realistic_active_<name>.npz`.
    Never touches existing `data/generated/active_<name>.npz`, `data/generated/hif_fusion_*.npz`
    (when `realistic=True`), or `results/`.
    """
    t0 = time.time()
    grid, der_names, caps = ag.load_active_feeder(name)
    topos = ag.TOPOLOGIES[name]
    adj, is_tie = ag.build_topology_matrices(grid, topos)
    cases = ag.active_fault_cases(name, grid)
    if max_cases is not None and max_cases < len(cases):
        idx = np.linspace(0, len(cases) - 1, int(max_cases), dtype=int)
        cases = [cases[i] for i in idx]
    base = feeder.base_loads()
    spec = ag.DER_SPECS[name]
    bus_zone = grid.bus_zone
    dev_index = {d: i for i, d in enumerate(grid.devices)}
    der_zones = [bus_zone[b] for b in spec["buses"]]
    n_dev = len(grid.devices)
    nofault_label = n_dev

    first = grid.members[grid.devices[0]][0]
    p0 = feeder.bus_phases(first)[0]
    feeder.cmd(f"New Fault.F phases=1 bus1={first}.{p0} bus2={first}.0 r=1 enabled=no")

    load_zone_idx = _load_zone_indices(grid, base) if realistic else None
    if realistic:
        feeder.scale_loads(base, np.ones(len(base)))
        feeder.set_load_level(1.0)
        feeder.reset_regulators()
        feeder.solve(controls=True)

    rng = np.random.default_rng(seed)

    def random_operating_point() -> tuple[float, np.ndarray, np.ndarray, float, np.ndarray, dict[str, float]]:
        mult = float(rng.uniform(*config.LOAD_MULT_RANGE))
        if realistic:
            assert load_zone_idx is not None
            f_pre, f_post = faults.sample_load_factors(load_zone_idx, n_dev, rng, realistic=True)
        else:
            f_pre = np.clip(rng.normal(1.0, config.LOAD_SPREAD, len(base)), 0.3, 1.7)
            f_post = f_pre
        feeder.scale_loads(base, f_pre)
        feeder.set_load_level(mult)
        pen = float(rng.uniform(*ag.DER_PEN_RANGE))
        w = np.clip(rng.normal(1.0, 0.25, len(der_names)), 0.1, 1.5)
        w = w / w.sum()
        der_kws = pen * spec["nominal_kw"] * w
        ag.set_der_kw(der_names, der_kws)
        for cname in caps:
            feeder.cmd(f"Edit Capacitor.{cname} enabled=yes")
        dz: dict[str, float] = {}
        for z, kw in zip(der_zones, der_kws):
            dz[z] = dz.get(z, 0.0) + float(kw)
        return mult, f_pre, f_post, pen, der_kws, dz

    X60_list, y_list, topo_list = [], [], []
    bus_list, ftype_list, r_list, der_list, kind_list, conv_list = [], [], [], [], [], []
    ires_pre_list, dires_list, dires_drift_list, closed_list, ifault_list, arcing_list = [], [], [], [], [], []
    r_eff_list, arc_kappa_list, arc_duty_list = [], [], []
    is_nf_list: list[bool] = []
    nf_dist_req: list[str | None] = []
    nf_kind_req: list[str | None] = []

    n_fault_per_topo = scenarios_per_topo * len(cases)
    n_nf_per_topo = max(30, int(round(n_fault_per_topo * nofault_share / (1.0 - nofault_share))))
    if max_nofault_per_topo is not None:
        n_nf_per_topo = max_nofault_per_topo

    kind_counters: dict[str, int] = {"cap_switch": 0, "pv_cloud": 0, "load_step": 0}

    for ti, topo in enumerate(topos):
        ag.set_topology(name, grid, topo)
        closed_mask = np.array([d not in topo.open_devices for d in grid.devices], dtype=bool)

        # --- Fault events ---
        for _ in range(scenarios_per_topo):
            for c in cases:
                _, _, f_post, pen, _, dz = random_operating_point()
                feeder.cmd("Edit Fault.F enabled=no")
                ok_pre = feeder.solve(controls=True)
                pre_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}

                if realistic:
                    bias = faults.sample_ct_pt_bias(grid.devices, rng)
                    pre = faults._perturb(
                        pre_clean, rng, bias=bias,
                        floor_i=config.NOISE_I_FLOOR_A, floor_v=config.NOISE_V_FLOOR_PU,
                    )
                    feeder.scale_loads(base, f_post)
                    arc = _sample_realistic_arc(c["r"], c["ftype"], rng)
                    if arc["is_arcing"]:
                        feeder.cmd("Edit Fault.F enabled=no")
                        ok_drift = feeder.solve(controls=False)
                        post_drift_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
                        spec_str = f"{c['spec'].rsplit(' r=', 1)[0]} r={arc['r_eff']:.6f}"
                        feeder.cmd(f"Edit Fault.F {spec_str} enabled=yes")
                        ok_post = feeder.solve(controls=False)
                        post_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
                        i_flt = fault_current_rms("Fault.F") if ok_post else 0.0
                        arcing_now = is_arcing_hif(c["ftype"], float(c["r"]), i_flt)
                        if arcing_now:
                            ir_pre, di_drift = extract_device_residuals(grid, pre_clean, post_drift_clean)
                            _, dir_post = extract_device_residuals(grid, post_drift_clean, post_clean)
                        else:
                            ir_pre, dir_post = extract_device_residuals(grid, pre_clean, post_clean)
                            di_drift = np.zeros_like(dir_post)
                        ok_all = bool(ok_pre and ok_drift and ok_post)
                    else:
                        feeder.cmd(f"Edit Fault.F {c['spec']} enabled=yes")
                        ok_post = feeder.solve(controls=False)
                        post_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
                        i_flt = fault_current_rms("Fault.F") if ok_post else 0.0
                        arcing_now = False
                        ir_pre, dir_post = extract_device_residuals(grid, pre_clean, post_clean)
                        di_drift = np.zeros_like(dir_post)
                        ok_all = bool(ok_pre and ok_post)

                    post = faults._perturb(
                        post_clean, rng, bias=bias,
                        floor_i=config.NOISE_I_FLOOR_A, floor_v=config.NOISE_V_FLOOR_PU,
                    )
                    r_eff_list.append(float(arc["r_eff"]))
                    arc_kappa_list.append(float(arc["arc_kappa"]))
                    arc_duty_list.append(float(arc["arc_duty"]))
                    dires_drift_list.append(di_drift)
                else:
                    pre = faults._perturb(pre_clean, rng)
                    feeder.cmd(f"Edit Fault.F {c['spec']} enabled=yes")
                    ok_post = feeder.solve(controls=False)
                    post_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
                    post = faults._perturb(post_clean, rng)
                    i_flt = fault_current_rms("Fault.F") if ok_post else 0.0
                    ir_pre, dir_post = extract_device_residuals(grid, pre_clean, post_clean)
                    arcing_now = is_arcing_hif(c["ftype"], float(c["r"]), i_flt)
                    ok_all = bool(ok_pre and ok_post)

                X60_list.append(ag.active_node_features(grid, topo, adj[ti], pre, post, dz))
                y_list.append(dev_index[bus_zone[c["bus"]]])
                topo_list.append(ti)
                bus_list.append(c["bus"].lower())
                ftype_list.append(c["ftype"])
                r_list.append(float(c["r"]))
                der_list.append(pen)
                kind_list.append("fault")
                conv_list.append(ok_all)
                ires_pre_list.append(ir_pre)
                dires_list.append(dir_post)
                closed_list.append(closed_mask)
                ifault_list.append(i_flt)
                arcing_list.append(arcing_now)
                is_nf_list.append(False)
                nf_dist_req.append(None)
                nf_kind_req.append(None)

        # --- Non-fault operational transients across all 7 disturbances ---
        feeder.cmd("Edit Fault.F enabled=no")
        nf_kinds = ("cap_switch", "pv_cloud", "load_step") if caps else ("pv_cloud", "load_step")
        for nfi in range(n_nf_per_topo):
            kind = nf_kinds[nfi % len(nf_kinds)]
            mult, f_pre, f_post, pen, der_kws, dz = random_operating_point()
            bias = faults.sample_ct_pt_bias(grid.devices, rng) if realistic else None
            floor_i = config.NOISE_I_FLOOR_A if realistic else 0.0
            floor_v = config.NOISE_V_FLOOR_PU if realistic else 0.0

            if kind == "cap_switch" and caps:
                cname = caps[int(rng.integers(0, len(caps)))]
                start_on = bool(rng.random() < 0.5)
                feeder.cmd(f"Edit Capacitor.{cname} enabled={'yes' if start_on else 'no'}")
                ok_pre = feeder.solve(controls=True)
                pre_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
                pre = faults._perturb(pre_clean, rng, bias=bias, floor_i=floor_i, floor_v=floor_v)
                if realistic:
                    feeder.scale_loads(base, f_post)
                feeder.cmd(f"Edit Capacitor.{cname} enabled={'no' if start_on else 'yes'}")
                ok_post = feeder.solve(controls=False)
                post_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
                post = faults._perturb(post_clean, rng, bias=bias, floor_i=floor_i, floor_v=floor_v)
                feeder.cmd(f"Edit Capacitor.{cname} enabled=yes")
            elif kind == "pv_cloud":
                if pen < 0.10:
                    pen = float(rng.uniform(0.15, ag.DER_PEN_RANGE[1]))
                    w = np.clip(rng.normal(1.0, 0.25, len(der_names)), 0.1, 1.5)
                    der_kws = pen * spec["nominal_kw"] * (w / w.sum())
                    ag.set_der_kw(der_names, der_kws)
                    dz = {}
                    for z, kw in zip(der_zones, der_kws):
                        dz[z] = dz.get(z, 0.0) + float(kw)
                ok_pre = feeder.solve(controls=True)
                pre_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
                pre = faults._perturb(pre_clean, rng, bias=bias, floor_i=floor_i, floor_v=floor_v)
                if realistic:
                    feeder.scale_loads(base, f_post)
                drop = rng.uniform(0.15, 0.50, size=len(der_names))
                ag.set_der_kw(der_names, der_kws * drop)
                ok_post = feeder.solve(controls=False)
                post_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
                post = faults._perturb(post_clean, rng, bias=bias, floor_i=floor_i, floor_v=floor_v)
            else:
                ok_pre = feeder.solve(controls=True)
                pre_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
                pre = faults._perturb(pre_clean, rng, bias=bias, floor_i=floor_i, floor_v=floor_v)
                spread2 = f_post.copy() if realistic else f_pre.copy()
                pick = rng.choice(len(base), size=min(len(base), int(rng.integers(1, 5))), replace=False)
                spread2[pick] *= rng.uniform(1.30, 1.80, size=len(pick))
                feeder.scale_loads(base, spread2)
                ok_post = feeder.solve(controls=False)
                post_clean = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
                post = faults._perturb(post_clean, rng, bias=bias, floor_i=floor_i, floor_v=floor_v)

            ir_pre, dir_post = extract_device_residuals(grid, pre_clean, post_clean)
            dist_choice = choose_nofault_disturbance(kind, kind_counters[kind])
            kind_counters[kind] += 1

            X60_list.append(ag.active_node_features(grid, topo, adj[ti], pre, post, dz))
            y_list.append(nofault_label)
            topo_list.append(ti)
            bus_list.append(f"nf_{ti}_{nfi}")
            ftype_list.append("NO_FAULT")
            r_list.append(-1.0)
            der_list.append(pen)
            kind_list.append(kind)
            conv_list.append(bool(ok_pre and ok_post))
            ires_pre_list.append(ir_pre)
            dires_list.append(dir_post)
            if realistic:
                r_eff_list.append(-1.0)
                arc_kappa_list.append(1.0)
                arc_duty_list.append(1.0)
                dires_drift_list.append(np.zeros_like(dir_post))
            closed_list.append(closed_mask)
            ifault_list.append(0.0)
            arcing_list.append(False)
            is_nf_list.append(True)
            nf_dist_req.append(dist_choice)
            nf_kind_req.append(kind)

        if verbose:
            tag = "realistic " if realistic else ""
            print(f"  [active {tag}{name}] OpenDSS topo '{topo.name}' ({ti + 1}/{len(topos)}): "
                  f"{n_fault_per_topo} faults + {n_nf_per_topo} non-faults ({time.time() - t0:.1f} s)")

    # Restore clean circuit state.
    feeder.cmd("Edit Fault.F enabled=no")
    ag.set_der_kw(der_names, np.zeros(len(der_names)))
    ag.set_topology(name, grid, topos[0])
    feeder.scale_loads(base, np.ones(len(base)))
    feeder.set_load_level(1.0)
    if realistic:
        feeder.reset_regulators()
        feeder.solve(controls=True)

    X60 = np.stack(X60_list).astype(np.float32)
    i_res_pre_arr = np.stack(ires_pre_list).astype(np.float32)
    di_res_arr = np.stack(dires_list).astype(np.float32)
    is_closed_arr = np.stack(closed_list).astype(bool)
    is_arcing_arr = np.array(arcing_list, dtype=bool)
    is_nofault_arr = np.array(is_nf_list, dtype=bool)
    arc_duty_arr = np.array(arc_duty_list, dtype=np.float64) if realistic else None
    di_res_drift_arr = np.stack(dires_drift_list).astype(np.float32) if realistic else None

    arc_path_arr: np.ndarray | None = None
    if realistic:
        arc_path_arr = np.zeros((len(y_list), n_dev), dtype=bool)
        for ev_i, (yi, ti_i, is_nf_i) in enumerate(zip(y_list, topo_list, is_nf_list)):
            if not is_nf_i:
                arc_path_arr[ev_i] = active_arc_path_mask(adj[ti_i], is_closed_arr[ev_i], yi)

    edge_feats, surfaces, dists = _run_edge_synthesis_batch(
        i_res_pre_arr, di_res_arr, is_closed_arr, is_arcing_arr, is_nofault_arr,
        nf_dist_req, nf_kind_req,
        model=model, seed=seed, n_workers=n_workers, verbose=verbose,
        label=f"active {'realistic ' if realistic else ''}{name}",
        arc_duty=arc_duty_arr,
        di_res_drift=di_res_drift_arr,
        arc_path_mask=arc_path_arr,
    )
    X_fused = insert_edge_features(X60, edge_feats, "active")

    FUSED_OUT_DIR.mkdir(parents=True, exist_ok=True)
    default_name = f"hif_fusion_realistic_active_{name}.npz" if realistic else f"hif_fusion_active_{name}.npz"
    npz_path = Path(out_path) if out_path is not None else (FUSED_OUT_DIR / default_name)
    npz_path.parent.mkdir(parents=True, exist_ok=True)
    conv = np.array(conv_list, dtype=bool)

    payload: dict[str, Any] = dict(
        X=X_fused,
        y=np.array(y_list, dtype=np.int64),
        topo_id=np.array(topo_list, dtype=np.int64),
        adj=adj,
        is_tie=is_tie,
        topo_names=np.array([t.name for t in topos], dtype=str),
        topo_is_looped=np.array([t.is_looped for t in topos], dtype=bool),
        features=np.array(ACTIVE_FUSED_FEATURES, dtype=str),
        devices=np.array(grid.devices, dtype=str),
        bus=np.array(bus_list, dtype=str),
        ftype=np.array(ftype_list, dtype=str),
        r=np.array(r_list, dtype=float),
        der_pct=np.array(der_list, dtype=float),
        event_kind=np.array(kind_list, dtype=str),
        converged=conv,
        i_fault=np.array(ifault_list, dtype=np.float32),
        is_arcing=is_arcing_arr,
        arc_surface=surfaces,
        edge_disturbance=dists,
        i_res_pre=i_res_pre_arr,
        di_res=di_res_arr,
        model_source=np.array(model.source),
        model_sha256=np.array(model.sha256 or ""),
        model_threshold=np.float64(model.threshold),
    )
    if realistic:
        payload["r_eff"] = np.array(r_eff_list, dtype=float)
        payload["arc_kappa"] = np.array(arc_kappa_list, dtype=float)
        payload["arc_duty"] = np.array(arc_duty_list, dtype=float)
        payload["realistic_mode"] = np.bool_(True)
        payload["di_res_drift"] = di_res_drift_arr

    np.savez_compressed(npz_path, **payload)

    nf_conv = conv & is_nofault_arr
    summary: dict[str, Any] = {
        "branch": "active",
        "feeder": name,
        "realistic_mode": bool(realistic),
        "path": str(npz_path),
        "events_total": int(len(y_list)),
        "converged": int(conv.sum()),
        "fault_events": int((conv & ~is_nofault_arr).sum()),
        "nofault_events": int(nf_conv.sum()),
        "arcing_events": int(is_arcing_arr[conv].sum()),
        "surface_counts": {s: int((surfaces[conv] == s).sum()) for s in SURFACE_NAMES},
        "nofault_disturbance_counts": {d: int((dists[nf_conv] == d).sum()) for d in he.DISTURBANCES},
        "features": ACTIVE_FUSED_FEATURES,
        "devices": list(grid.devices),
        "topologies": [t.name for t in topos],
        "model_source": model.source,
        "model_sha256": model.sha256,
        "model_params": model.n_params,
        "model_bytes": model.n_bytes,
        "model_threshold": model.threshold,
        "runtime_s": round(time.time() - t0, 1),
    }
    if realistic and arc_duty_arr is not None:
        summary["intermittent_arc_events"] = int((is_arcing_arr[conv] & (arc_duty_arr[conv] < 1.0)).sum())
        summary["continuous_arc_events"] = int((is_arcing_arr[conv] & (arc_duty_arr[conv] >= 1.0)).sum())
    return summary


# ---------------------------------------------------------------------------
# Fused dataset containers & loaders (for T-31 pipeline)
# ---------------------------------------------------------------------------
@dataclass
class PassiveFusionDataset:
    feeder: str
    X: np.ndarray                          # (E, N, 23) float32
    y: np.ndarray                          # (E,) int64
    parent: np.ndarray                     # (N,) int64
    features: list[str]
    devices: list[str]
    bus: np.ndarray
    ftype: np.ndarray
    phases: np.ndarray
    r: np.ndarray
    scenario: np.ndarray
    load_mult: np.ndarray
    i_fault: np.ndarray
    is_arcing: np.ndarray
    arc_surface: np.ndarray
    edge_disturbance: np.ndarray
    model_source: str
    model_sha256: str
    model_threshold: float
    r_eff: np.ndarray | None = None
    arc_kappa: np.ndarray | None = None
    arc_duty: np.ndarray | None = None
    realistic_mode: bool = False
    X_ml_full: np.ndarray | None = None
    ml_full_features: list[str] | None = None

    @property
    def X_60hz(self) -> np.ndarray:
        return strip_edge_features(self.X, "passive")


@dataclass
class ActiveFusionDataset:
    feeder: str
    X: np.ndarray                          # (E, N, 28) float32
    y: np.ndarray                          # (E,) int64 in 0..N (N = NO_FAULT)
    topo_id: np.ndarray
    adj: np.ndarray
    is_tie: np.ndarray
    topo_names: list[str]
    topo_is_looped: np.ndarray
    features: list[str]
    devices: list[str]
    bus: np.ndarray
    ftype: np.ndarray
    r: np.ndarray
    der_pct: np.ndarray
    event_kind: np.ndarray
    i_fault: np.ndarray
    is_arcing: np.ndarray
    arc_surface: np.ndarray
    edge_disturbance: np.ndarray
    model_source: str
    model_sha256: str
    model_threshold: float
    r_eff: np.ndarray | None = None
    arc_kappa: np.ndarray | None = None
    arc_duty: np.ndarray | None = None
    realistic_mode: bool = False

    @property
    def n_nodes(self) -> int:
        return self.X.shape[1]

    @property
    def nofault_class(self) -> int:
        return self.X.shape[1]

    @property
    def X_60hz(self) -> np.ndarray:
        return strip_edge_features(self.X, "active")


def load_passive_fusion_dataset(
    feeder_name: str,
    path: Path | str | None = None,
    *,
    realistic: bool = False,
) -> PassiveFusionDataset:
    default_name = (
        f"hif_fusion_realistic_passive_{feeder_name}.npz"
        if realistic
        else f"hif_fusion_passive_{feeder_name}.npz"
    )
    p = Path(path) if path is not None else (FUSED_OUT_DIR / default_name)
    with np.load(p, allow_pickle=False) as d:
        ok = d["converged"].astype(bool)
        r_arr = d["r"][ok].astype(float)
        r_eff = d["r_eff"][ok].astype(float) if "r_eff" in d.files else r_arr.copy()
        arc_kappa = d["arc_kappa"][ok].astype(float) if "arc_kappa" in d.files else np.ones(len(r_arr), dtype=float)
        arc_duty = d["arc_duty"][ok].astype(float) if "arc_duty" in d.files else np.ones(len(r_arr), dtype=float)
        realistic_mode = bool(d["realistic_mode"]) if "realistic_mode" in d.files else False
        x_ml_full = d["X_ml_full"][ok].astype(np.float32) if "X_ml_full" in d.files else None
        ml_full_feats = [str(s) for s in d["ml_full_features"]] if "ml_full_features" in d.files else None
        return PassiveFusionDataset(
            feeder=feeder_name,
            X=d["X"][ok].astype(np.float32),
            y=d["y"][ok].astype(np.int64),
            parent=d["parent"].astype(np.int64),
            features=[str(s) for s in d["features"]],
            devices=[str(s) for s in d["devices"]],
            bus=d["bus"][ok].astype(str),
            ftype=d["ftype"][ok].astype(str),
            phases=d["phases"][ok].astype(str),
            r=r_arr,
            scenario=d["scenario"][ok].astype(int),
            load_mult=d["load_mult"][ok].astype(float),
            i_fault=d["i_fault"][ok].astype(np.float32),
            is_arcing=d["is_arcing"][ok].astype(bool),
            arc_surface=d["arc_surface"][ok].astype(str),
            edge_disturbance=d["edge_disturbance"][ok].astype(str),
            model_source=str(d["model_source"]),
            model_sha256=str(d["model_sha256"]),
            model_threshold=float(d["model_threshold"]),
            r_eff=r_eff,
            arc_kappa=arc_kappa,
            arc_duty=arc_duty,
            realistic_mode=realistic_mode,
            X_ml_full=x_ml_full,
            ml_full_features=ml_full_feats,
        )


def load_active_fusion_dataset(
    feeder_name: str,
    path: Path | str | None = None,
    *,
    realistic: bool = False,
) -> ActiveFusionDataset:
    default_name = (
        f"hif_fusion_realistic_active_{feeder_name}.npz"
        if realistic
        else f"hif_fusion_active_{feeder_name}.npz"
    )
    p = Path(path) if path is not None else (FUSED_OUT_DIR / default_name)
    with np.load(p, allow_pickle=False) as d:
        ok = d["converged"].astype(bool)
        r_arr = d["r"][ok].astype(float)
        r_eff = d["r_eff"][ok].astype(float) if "r_eff" in d.files else r_arr.copy()
        arc_kappa = d["arc_kappa"][ok].astype(float) if "arc_kappa" in d.files else np.ones(len(r_arr), dtype=float)
        arc_duty = d["arc_duty"][ok].astype(float) if "arc_duty" in d.files else np.ones(len(r_arr), dtype=float)
        realistic_mode = bool(d["realistic_mode"]) if "realistic_mode" in d.files else False
        return ActiveFusionDataset(
            feeder=feeder_name,
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
            r=r_arr,
            der_pct=d["der_pct"][ok].astype(float),
            event_kind=d["event_kind"][ok].astype(str),
            i_fault=d["i_fault"][ok].astype(np.float32),
            is_arcing=d["is_arcing"][ok].astype(bool),
            arc_surface=d["arc_surface"][ok].astype(str),
            edge_disturbance=d["edge_disturbance"][ok].astype(str),
            model_source=str(d["model_source"]),
            model_sha256=str(d["model_sha256"]),
            model_threshold=float(d["model_threshold"]),
            r_eff=r_eff,
            arc_kappa=arc_kappa,
            arc_duty=arc_duty,
            realistic_mode=realistic_mode,
        )
