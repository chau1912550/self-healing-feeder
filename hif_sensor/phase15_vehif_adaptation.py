"""Phase 1.5 of the HIF sensor:
1. Real GCC C firmware bit-parity & latency verification (Phase 0 & Phase 1.5 headers).
2. Explicit 50 Hz (Vietnam / Australia 22 kV) vs 60 Hz (US 12.47 kV) front-end & native-rate study.
3. Zero-shot feature-group ablation (Sim -> Real VeHIF) to diagnose the asymmetry domain gap.
4. Leak-free few-shot real-VeHIF adaptation (5% / 10% / 20%, 5 recording-disjoint seeds, strict FA guard).

What is real vs simulated:
- REAL: VeHIF 22 kV, 50 Hz vegetation fault currents and 53 background recordings (Gomes & Ozansoy 2022).
- SIMULATED: SCT-013 + Sallen-Key + 12-bit ADC sensor front end, feeder residual load, Emanuel arcs,
  and 7 normal grid disturbances. Not a field test of physical hardware.
"""
import json
import os
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

import matplotlib
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import signal
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

from hif.features import FEATURES, K, window_features, window_labels
from hif.frontend import (
    F_LINE, F_LINE_VN, FS_SIM, N_CYCLE, OVERSAMPLE, STAGES, STAGES_50HZ_RETUNED,
    codes_to_amps, frequency_response_summary, sense, sim_rate_hz,
)
from hif.waveforms import DISTURBANCES, SURFACES, WARMUP, _base, make_event
from real_data_test import (
    BINS, GRID_HZ, attr, by_bins, cycle_ms, find_h5, load_model,
    read_head, read_tail, rolling_rms, samples_per_cycle,
)
from train_kaggle import (
    HIDDEN, MAX_FALSE_ALARM, N_EVENTS, PERSIST, SEED,
    alarms, event_result, fold_and_quantize, pick_threshold, predict_q, split, stack, summarize,
)

OUT = Path("results")
FIG = OUT / "figures"
FW = Path("firmware")
BUILD = Path("build")
for d in (OUT, FIG, FW, BUILD):
    d.mkdir(parents=True, exist_ok=True)

N_VEHIF_POOL = 300         # 250 Phase-1 recordings + 50 additional valid recordings
N_PHASE1_COMPARE = 250     # exact Phase-1 seed=7 subset for 50 Hz vs 60 Hz & ablation
MAX_SECONDS = 90           # last 90 s of each recording (keeps runtime ~12-18 min on Kaggle CPU)
MAX_MINUTES = 45
VEHIF_SEED = 7
ADAPT_SEEDS = [0, 1, 2, 3, 4]
ADAPT_FRACS = [0.05, 0.10, 0.20]
SPC = N_CYCLE * OVERSAMPLE  # 2048 samples/cycle

ABLATION_SETS = {
    "all_16": list(FEATURES),
    "no_asymmetry_12": [f for f in FEATURES if f not in ("dc_ratio", "h2_ratio", "even_ratio", "even_std")],
    "no_top_shift_9": [f for f in FEATURES if f not in (
        "dc_ratio", "h2_ratio", "even_ratio", "even_std", "I3_cv", "ph3_jitter", "I1_cv")],
    "harmonics_only_7": ["log_I1", "log_I3", "h2_ratio", "h3_ratio", "h5_ratio", "even_ratio", "dc_ratio"],
    "temporal_only_8": ["I3_cv", "I1_cv", "ph3_jitter", "cycle_diff", "even_std", "h3_trend", "I1_trend", "interharm"],
}


def save_fig(fig, name):
    fig.tight_layout()
    fig.savefig(FIG / name, dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------- 1. C firmware GCC check
def verify_c_firmware(header_name, vectors_path, tag):
    """Compile firmware/hif_infer.c + test_infer.c with gcc -O2 -Wall -Wextra -Werror and run."""
    bin_path = BUILD / f"test_infer_{tag}"
    cmd = [
        "gcc", "-O2", "-Wall", "-Wextra", "-Werror",
        "-I", str(FW),
        f'-DHIF_MODEL_HEADER="{header_name}"',
        str(FW / "hif_infer.c"), str(FW / "test_infer.c"),
        "-lm", "-o", str(bin_path),
    ]
    comp = subprocess.run(cmd, capture_output=True, text=True)
    if comp.returncode != 0:
        return {"compiled": False, "returncode": comp.returncode,
                "stderr": comp.stderr[-1000:], "header": header_name}
    ver = subprocess.run(["gcc", "--version"], capture_output=True, text=True)
    gcc_line = ver.stdout.splitlines()[0].strip() if ver.stdout else "gcc"
    run = subprocess.run([str(bin_path), str(vectors_path)], capture_output=True, text=True)
    res = json.loads(run.stdout) if run.stdout.strip().startswith("{") else {"raw_stdout": run.stdout}
    res.update({
        "compiled": True,
        "compiler": gcc_line,
        "compile_flags": "-O2 -Wall -Wextra -Werror",
        "header": header_name,
        "binary_bytes": bin_path.stat().st_size,
        "exit_code": run.returncode,
    })
    return res


def write_extended_vectors(layers, X_pool, y_pool, out_path, n_vecs=100, seed=42):
    rng = np.random.default_rng(seed)
    p = predict_q(layers, X_pool)
    # Stratified sample across low, mid (near decision boundary), and high probability
    low = np.flatnonzero(p < 0.05)
    mid = np.flatnonzero((p >= 0.05) & (p <= 0.995))
    hi = np.flatnonzero(p > 0.995)
    picks = []
    for arr, k in ((low, n_vecs // 3), (mid, n_vecs // 3), (hi, n_vecs - 2 * (n_vecs // 3))):
        if len(arr):
            picks.append(rng.choice(arr, size=min(k, len(arr)), replace=False))
    idx = np.concatenate(picks) if picks else np.arange(min(n_vecs, len(X_pool)))
    vecs = [{"features": [float(v) for v in X_pool[i]], "prob": float(p[i]), "is_hif": bool(y_pool[i] == 1)}
            for i in idx]
    out_path.write_text(json.dumps(vecs, indent=2), encoding="utf-8")
    return out_path


def export_c_header(layers, thr, header_path, comment):
    def carr(a, fmt):
        return "{" + ", ".join(fmt(v) for v in np.ravel(a)) + "}"
    def carr2d(a2d, fmt):
        return "{" + ", ".join("{" + ", ".join(fmt(v) for v in row) + "}" for row in a2d) + "}"
    lines = [
        f"// {comment}",
        "#pragma once",
        "#include <stdint.h>",
        f"#define HIF_N_IN {layers[0]['Wq'].shape[0]}",
        f"#define HIF_PERSIST {PERSIST}",
        f"static const float HIF_THRESHOLD = {thr:.6f}f;",
    ]
    for n, L in enumerate(layers, 1):
        Wt = L["Wq"].T
        lines += [
            f"#define HIF_L{n}_OUT {Wt.shape[0]}",
            f"#define HIF_L{n}_IN {Wt.shape[1]}",
            f"static const int8_t HIF_W{n}[{Wt.shape[0]}][{Wt.shape[1]}] = " + carr2d(Wt, lambda v: str(int(v))) + ";",
            f"static const float HIF_S{n} = {L['scale']:.8e}f;",
            f"static const float HIF_B{n}[{Wt.shape[0]}] = " + carr(L["b"], lambda v: f"{v:.8e}f") + ";",
        ]
    header_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 2. Fast VeHIF extraction
def to_sensor_rate_fast(x, spc):
    """Resample so 1 power cycle = 2048 samples with bounded polyphase denominator (pitch error < 0.005%)."""
    fr = Fraction(SPC / spc).limit_denominator(256)
    return signal.resample_poly(x, fr.numerator, fr.denominator)


def through_sensor_freq(x, rng, f_line):
    amps = codes_to_amps(sense(x, rng, f_line=f_line))[WARMUP * N_CYCLE:]
    X, _ = window_features(amps)
    ends = np.arange(K - 1, K - 1 + len(X)) + WARMUP
    return X, ends


def extract_vehif_record(g, rec_id, seed_pair, also_60hz=False):
    spc = samples_per_cycle(read_head(g["voltage_lf"], 1 << 18)) if "voltage_lf" in g else 2000.0
    raw, n_total = read_tail(g["current_lf"], int(MAX_SECONDS * GRID_HZ * spc))
    raw = np.nan_to_num(raw)
    x = to_sensor_rate_fast(raw - raw.mean(), spc)
    n = len(x) // SPC * SPC
    if n < 40 * SPC:
        raise ValueError("recording shorter than 40 cycles")
    x = x[:n]
    ms = cycle_ms(x)
    r8 = rolling_rms(ms, K)
    peak_rms20 = float(rolling_rms(ms, 20).max())

    # Native 50 Hz (Vietnam / Australia VeHIF physical rate: FS_ADC = 12,800 Hz)
    rng50 = np.random.default_rng(seed_pair)
    t50 = np.arange(n) / sim_rate_hz(F_LINE_VN)
    load50, a1_50, _ = _base(t50, rng50, w=2 * np.pi * F_LINE_VN)
    Xf50, ends = through_sensor_freq(load50 + x, rng50, f_line=F_LINE_VN)
    Xc50, _ = through_sensor_freq(load50, rng50, f_line=F_LINE_VN)
    win_r8 = r8[ends - (K - 1)].astype(np.float32)

    rec = {
        "id": rec_id,
        "fault_type": attr(g, "fault_type", "test_type", "cal_type") or "?",
        "seconds": float(n_total / spc / GRID_HZ),
        "peak_rms20": peak_rms20,
        "rms_all": float(np.sqrt(ms.mean())),
        "load_rms": float(a1_50 / np.sqrt(2)),
        "ratio": float(peak_rms20 / (a1_50 / np.sqrt(2))),
        "Xf50": Xf50,
        "Xc50": Xc50,
        "r8": win_r8,
    }
    if also_60hz:
        # Paired 60 Hz resampled mode (matches Phase 1 real_data_test.py rate: FS_ADC = 15,360 Hz)
        rng60 = np.random.default_rng(seed_pair)
        t60 = np.arange(n) / FS_SIM
        load60, _, _ = _base(t60, rng60, w=2 * np.pi * F_LINE)
        Xf60, _ = through_sensor_freq(load60 + x, rng60, f_line=F_LINE)
        Xc60, _ = through_sensor_freq(load60, rng60, f_line=F_LINE)
        rec["Xf60"] = Xf60
        rec["Xc60"] = Xc60
    return rec


def eval_vehif_records(records, layers, thr, feat_idx=None, mode="50hz"):
    xf_key = "Xf50" if mode == "50hz" else "Xf60"
    xc_key = "Xc50" if mode == "50hz" else "Xc60"
    rows = []
    for r in records:
        Xf = r[xf_key] if feat_idx is None else r[xf_key][:, feat_idx]
        Xc = r[xc_key] if feat_idx is None else r[xc_key][:, feat_idx]
        sf = predict_q(layers, Xf)
        sc = predict_q(layers, Xc)
        af = alarms(sf, thr)
        ac = alarms(sc, thr)
        alarm_f, alarm_c = bool(af), bool(ac)
        rows.append({
            "id": r["id"],
            "peak_rms20": r["peak_rms20"],
            "ratio": r["ratio"],
            "fault_type": r["fault_type"],
            "alarm": alarm_f,
            "control_alarm": alarm_c,
            "detected": alarm_f and not alarm_c,
        })
    low02 = [row["detected"] for row in rows if row["peak_rms20"] < 2.0]
    return {
        "recordings": len(rows),
        "detection_rate": float(np.mean([row["detected"] for row in rows])),
        "detection_rate_0_to_2A": float(np.mean(low02)) if low02 else None,
        "n_0_to_2A": len(low02),
        "alarm_in_control_rate": float(np.mean([row["control_alarm"] for row in rows])),
        "by_peak_fault_current_A_rms": by_bins(rows, "peak_rms20", BINS),
    }


def eval_bg_records(bg_records, layers, thr, feat_idx=None, mode="50hz"):
    xf_key = "Xf50" if mode == "50hz" else "Xf60"
    xc_key = "Xc50" if mode == "50hz" else "Xc60"
    al_f, al_c = [], []
    for r in bg_records:
        Xf = r[xf_key] if feat_idx is None else r[xf_key][:, feat_idx]
        Xc = r[xc_key] if feat_idx is None else r[xc_key][:, feat_idx]
        al_f.append(bool(alarms(predict_q(layers, Xf), thr)))
        al_c.append(bool(alarms(predict_q(layers, Xc), thr)))
    return {
        "recordings": len(bg_records),
        "alarm_rate": float(np.mean(al_f)) if al_f else 0.0,
        "alarm_in_control_rate": float(np.mean(al_c)) if al_c else 0.0,
    }


# ---------------------------------------------------------------- 3. Training & adaptation helpers
def simulate_phase0_events(f_line=F_LINE, n_events=N_EVENTS, seed=SEED):
    rng = np.random.default_rng(seed)
    events = []
    for k in range(n_events):
        amps, meta = make_event(rng, is_hif=(k % 2 == 0), f_line=f_line)
        X, ends = window_features(amps)
        events.append({"X": X, "ends": ends, "y": window_labels(ends, meta), **meta})
    return events


def fit_subset_int8(tr, va, feat_idx, seed=SEED):
    X_tr, y_tr = stack(tr)
    X_tr = X_tr[:, feat_idx]
    sc = StandardScaler().fit(X_tr)
    clf = MLPClassifier(hidden_layer_sizes=HIDDEN, alpha=1e-3, max_iter=400,
                        early_stopping=True, n_iter_no_change=15, random_state=seed)
    clf.fit(sc.transform(X_tr), y_tr)
    layers = fold_and_quantize(sc, clf)
    grid = np.linspace(0.30, 0.999, 300)
    va_scores = [predict_q(layers, e["X"][:, feat_idx]) for e in va]
    thr = pick_threshold(va, va_scores, grid)
    return layers, thr


def pick_joint_threshold(sim_va, sim_va_scores, real_ctrl_scores, max_sim_fa=MAX_FALSE_ALARM, max_real_fa=0.02):
    """Pick lowest threshold satisfying BOTH simulated val FA <= max_sim_fa AND real control FA <= max_real_fa."""
    grid = np.linspace(0.30, 0.999, 350)
    def ok(thr):
        s_fa = float(np.mean([event_result(e, s, thr)["false_alarm"] for e, s in zip(sim_va, sim_va_scores)]))
        if s_fa > max_sim_fa:
            return False
        if real_ctrl_scores:
            r_fa = float(np.mean([bool(alarms(s, thr)) for s in real_ctrl_scores]))
            if r_fa > max_real_fa:
                return False
        return True

    lo, hi = 0, len(grid) - 1
    if not ok(grid[hi]):
        return float(grid[hi])
    while lo < hi:
        mid = (lo + hi) // 2
        if ok(grid[mid]):
            hi = mid
        else:
            lo = mid + 1
    return float(grid[lo])


def sample_real_adapt_windows(adapt_recs, bg_adapt_recs, rng, max_per_rec=220):
    """Extract active fault windows (y=1) and paired control/background windows (y=0) from adaptation pool."""
    Xs, ys = [], []
    for r in adapt_recs:
        r8 = r["r8"]
        thresh_i = min(0.20, max(0.08, 0.45 * r["peak_rms20"]))
        pos_idx = np.flatnonzero(r8 >= thresh_i)
        if len(pos_idx) == 0:
            pos_idx = np.array([int(np.argmax(r8))])
        if len(pos_idx) > max_per_rec:
            pos_idx = np.sort(rng.choice(pos_idx, size=max_per_rec, replace=False))
        Xf_pos = r["Xf50"][pos_idx]

        n_ctrl = min(len(r["Xc50"]), max_per_rec)
        ctrl_idx = np.sort(rng.choice(len(r["Xc50"]), size=n_ctrl, replace=False))
        Xc_neg = r["Xc50"][ctrl_idx]

        Xs.append(Xf_pos)
        ys.append(np.ones(len(Xf_pos), dtype=np.int8))
        Xs.append(Xc_neg)
        ys.append(np.zeros(len(Xc_neg), dtype=np.int8))

    for br in bg_adapt_recs:
        n_bg = min(len(br["Xf50"]), 100)
        idx = np.sort(rng.choice(len(br["Xf50"]), size=n_bg, replace=False))
        Xs.append(br["Xf50"][idx])
        ys.append(np.zeros(n_bg, dtype=np.int8))
    return np.concatenate(Xs, axis=0), np.concatenate(ys, axis=0)


def hidden_repr(layers, X):
    """Run frozen Layer 1 & Layer 2 (ReLU) to extract 8-dim penultimate representation."""
    h = X.astype(np.float32)
    for L in layers[:2]:
        h = np.maximum(h @ (L["Wq"].astype(np.float32) * L["scale"]) + L["b"], 0.0)
    return h


def fit_head_recal_int8(phase0_layers, X_sim, y_sim, X_real, y_real, seed):
    """Freeze Layer 1-2 of Phase 0 int8 MLP; recalibrate Layer 3 (9 params) on Sim + Real; keep 504 B int8."""
    rng = np.random.default_rng(seed)
    n_sim_sub = min(len(X_sim), max(12000, len(X_real) * 3))
    sub = rng.choice(len(X_sim), size=n_sim_sub, replace=False)
    H_sim = hidden_repr(phase0_layers, X_sim[sub])
    H_real = hidden_repr(phase0_layers, X_real)
    H = np.concatenate([H_sim, H_real], axis=0)
    y = np.concatenate([y_sim[sub], y_real], axis=0)
    # Weight real adaptation windows to carry ~30% total weight
    w_real = (0.30 / 0.70) * (len(H_sim) / max(1, len(H_real)))
    sw = np.concatenate([np.ones(len(H_sim)), np.full(len(H_real), w_real)])
    lr = LogisticRegression(C=1.0, max_iter=500, random_state=seed)
    lr.fit(H, y, sample_weight=sw)
    W3 = lr.coef_.T.astype(np.float32)      # (8, 1)
    b3 = lr.intercept_.astype(np.float32)   # (1,)
    s3 = float(np.abs(W3).max() / 127.0) or 1e-6
    new_layers = [
        {"Wq": phase0_layers[0]["Wq"].copy(), "scale": phase0_layers[0]["scale"], "b": phase0_layers[0]["b"].copy()},
        {"Wq": phase0_layers[1]["Wq"].copy(), "scale": phase0_layers[1]["scale"], "b": phase0_layers[1]["b"].copy()},
        {"Wq": np.round(W3 / s3).astype(np.int8), "scale": s3, "b": b3},
    ]
    return new_layers


def fit_joint_mlp_int8(X_sim, y_sim, X_real, y_real, seed):
    """Jointly train a 504 B int8 (16, 8) Tiny MLP on Sim + few-shot Real VeHIF (oversampled ~25% mix)."""
    rng = np.random.default_rng(seed)
    # Repeat real windows so real takes ~25% of training samples (MLPClassifier has no sample_weight in all sklearn versions)
    target_real = int(0.33 * len(X_sim))
    reps = max(1, int(np.ceil(target_real / max(1, len(X_real)))))
    idx_real = np.tile(np.arange(len(X_real)), reps)[:target_real]
    rng.shuffle(idx_real)
    X_all = np.concatenate([X_sim, X_real[idx_real]], axis=0)
    y_all = np.concatenate([y_sim, y_real[idx_real]], axis=0)
    perm = rng.permutation(len(X_all))
    X_all, y_all = X_all[perm], y_all[perm]

    sc = StandardScaler().fit(X_all)
    clf = MLPClassifier(hidden_layer_sizes=HIDDEN, alpha=1e-3, max_iter=350,
                        early_stopping=True, n_iter_no_change=12, random_state=seed)
    clf.fit(sc.transform(X_all), y_all)
    return fold_and_quantize(sc, clf)


def stratified_split_indices(records, test_frac, seed):
    """Recording-disjoint stratified split by peak fault current bin."""
    rng = np.random.default_rng(seed)
    bins = {}
    for idx, r in enumerate(records):
        v = r["peak_rms20"]
        b = 0 if v < 1.0 else (1 if v < 2.0 else (2 if v < 5.0 else 3))
        bins.setdefault(b, []).append(idx)
    test_idx, pool_idx = [], []
    for b in sorted(bins):
        arr = np.array(bins[b], dtype=int)
        rng.shuffle(arr)
        n_te = int(round(len(arr) * test_frac))
        test_idx.extend(arr[:n_te].tolist())
        pool_idx.extend(arr[n_te:].tolist())
    rng.shuffle(pool_idx)
    return test_idx, pool_idx


def stratified_prefix(records, pool_idx, n_take, seed):
    """Take n_take recordings from pool_idx stratified by peak fault current bin."""
    rng = np.random.default_rng(seed)
    bins = {}
    for idx in pool_idx:
        v = records[idx]["peak_rms20"]
        b = 0 if v < 1.0 else (1 if v < 2.0 else (2 if v < 5.0 else 3))
        bins.setdefault(b, []).append(idx)
    chosen = []
    total = len(pool_idx)
    for b in sorted(bins):
        arr = np.array(bins[b], dtype=int)
        rng.shuffle(arr)
        k = max(1, int(round(n_take * len(arr) / total))) if len(arr) else 0
        chosen.extend(arr[:k].tolist())
    # Adjust exact count
    rem = [i for i in pool_idx if i not in set(chosen)]
    rng.shuffle(rem)
    while len(chosen) < n_take and rem:
        chosen.append(rem.pop())
    return chosen[:n_take]


# ---------------------------------------------------------------- 4. Figures
def make_figures(res):
    # Figure 1: Few-shot adaptation curve (overall + 0-2 A + sim retention + FA)
    adapt = res["few_shot_adaptation"]
    fracs_pct = [0, 5, 10, 20]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 4.0))

    z0 = adapt["zero_shot_phase0"]
    for method, label, color, marker in (
        ("head_recal_int8", "Head recalibration (frozen trunk, 504 B)", "#0284c7", "s"),
        ("joint_mlp_int8", "Joint fine-tuned Tiny MLP (504 B int8)", "#16a34a", "o"),
    ):
        ys_all = [z0["real_detection_mean"]] + [adapt["by_fraction"][str(f)][method]["real_detection_mean"] for f in ADAPT_FRACS]
        es_all = [z0["real_detection_std"]] + [adapt["by_fraction"][str(f)][method]["real_detection_std"] for f in ADAPT_FRACS]
        ys_low = [z0["real_0_to_2A_mean"]] + [adapt["by_fraction"][str(f)][method]["real_0_to_2A_mean"] for f in ADAPT_FRACS]
        es_low = [z0["real_0_to_2A_std"]] + [adapt["by_fraction"][str(f)][method]["real_0_to_2A_std"] for f in ADAPT_FRACS]
        ax1.errorbar(fracs_pct, [v * 100 for v in ys_all], yerr=[v * 100 for v in es_all],
                     marker=marker, lw=2, capsize=4, color=color, label=label + " — All")
        ax1.errorbar(fracs_pct, [v * 100 for v in ys_low], yerr=[v * 100 for v in es_low],
                     marker=marker, lw=1.6, ls="--", capsize=3, color=color, alpha=0.8, label=label + " — 0–2 A")
    ax1.set_xlabel("Real VeHIF recordings used for adaptation (% of 300 pool)")
    ax1.set_ylabel("Held-out real VeHIF detection (%)")
    ax1.set_ylim(0, 105)
    ax1.set_xticks(fracs_pct)
    ax1.grid(alpha=0.25)
    ax1.legend(fontsize=7.5, loc="lower right")
    ax1.set_title("Few-shot adaptation on unseen real VeHIF 22 kV (5 seeds)")

    # Right panel: Band-by-band comparison (Zero-shot vs 20% Joint MLP int8)
    bands = ["0-1", "1-2", "2-5", "5-10"]
    x = np.arange(len(bands))
    w = 0.36
    z_bands = [(z0["by_current_band_mean"].get(b) or 0.0) * 100 for b in bands]
    j20 = adapt["by_fraction"]["0.2"]["joint_mlp_int8"]
    j_bands = [(j20["by_current_band_mean"].get(b) or 0.0) * 100 for b in bands]
    ax2.bar(x - w / 2, z_bands, w, color="#94a3b8", label="Phase 0 Zero-shot (504 B)")
    ax2.bar(x + w / 2, j_bands, w, color="#16a34a", label="Phase 1.5 Joint 20% (504 B)")
    for i, (zv, jv) in enumerate(zip(z_bands, j_bands)):
        ax2.text(i - w / 2, zv + 1.8, f"{zv:.0f}%", ha="center", fontsize=8)
        ax2.text(i + w / 2, jv + 1.8, f"{jv:.0f}%", ha="center", fontsize=8, fontweight="bold")
    ax2.set_xticks(x, [f"{b} A" for b in bands])
    ax2.set_ylabel("Held-out detection (%)")
    ax2.set_ylim(0, 110)
    ax2.grid(axis="y", alpha=0.25)
    ax2.legend(fontsize=8)
    ax2.set_title("Detection by real fault current band (50 Hz native)")
    save_fig(fig, "phase15_adaptation.png")

    # Figure 2: Feature-group ablation (Sim vs Zero-shot Real VeHIF)
    abl = res["feature_ablation"]
    names = list(ABLATION_SETS.keys())
    labels = ["All 16\n(Phase 0)", "No Asym\n(12)", "No Top-7\nShift (9)", "Harmonics\nOnly (7)", "Temporal\nOnly (8)"]
    sim_det = [abl[n]["sim_test"]["detection_rate"] * 100 for n in names]
    real_det = [abl[n]["real_vehif_50hz"]["detection_rate"] * 100 for n in names]
    sim_fa = [abl[n]["sim_test"]["false_alarm_rate_normal"] * 100 for n in names]
    fig, ax = plt.subplots(figsize=(8.6, 3.8))
    x = np.arange(len(names))
    w = 0.28
    ax.bar(x - w, sim_det, w, color="#2563eb", label="Simulated Emanuel test detection (%)")
    ax.bar(x, real_det, w, color="#ea580c", label="Real VeHIF 22 kV zero-shot detection (%)")
    ax.bar(x + w, sim_fa, w, color="#dc2626", label="Simulated normal false alarms (%)")
    for i in range(len(names)):
        ax.text(i - w, sim_det[i] + 1.5, f"{sim_det[i]:.1f}", ha="center", fontsize=7.5)
        ax.text(i, real_det[i] + 1.5, f"{real_det[i]:.1f}", ha="center", fontsize=7.5)
        ax.text(i + w, sim_fa[i] + 1.5, f"{sim_fa[i]:.1f}", ha="center", fontsize=7.5)
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 112)
    ax.set_ylabel("Rate (%)")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(fontsize=8)
    ax.set_title("Feature-group ablation: simulated accuracy vs zero-shot real VeHIF transfer")
    save_fig(fig, "phase15_ablation.png")

    # Figure 3: 50 Hz Vietnam vs 60 Hz US front-end Bode & VeHIF evaluation
    f50 = res["freq_50hz_vs_60hz"]
    freqs = np.logspace(1.4, 4.3, 1200)
    _, h_std = signal.freqs([1.0], np.polymul(
        [STAGES[0][0] ** 2 * STAGES[0][1] * STAGES[0][2], 2 * STAGES[0][0] * STAGES[0][2], 1.0],
        [STAGES[1][0] ** 2 * STAGES[1][1] * STAGES[1][2], 2 * STAGES[1][0] * STAGES[1][2], 1.0],
    ), worN=2 * np.pi * freqs)
    _, h_50r = signal.freqs([1.0], np.polymul(
        [STAGES_50HZ_RETUNED[0][0] ** 2 * STAGES_50HZ_RETUNED[0][1] * STAGES_50HZ_RETUNED[0][2],
         2 * STAGES_50HZ_RETUNED[0][0] * STAGES_50HZ_RETUNED[0][2], 1.0],
        [STAGES_50HZ_RETUNED[1][0] ** 2 * STAGES_50HZ_RETUNED[1][1] * STAGES_50HZ_RETUNED[1][2],
         2 * STAGES_50HZ_RETUNED[1][0] * STAGES_50HZ_RETUNED[1][2], 1.0],
    ), worN=2 * np.pi * freqs)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.4, 3.8))
    a1.semilogx(freqs, 20 * np.log10(np.abs(h_std)), lw=2, color="#2563eb", label="Current PCB (fc = 2,048 Hz)")
    a1.semilogx(freqs, 20 * np.log10(np.abs(h_50r)), lw=1.8, ls="--", color="#16a34a", label="50 Hz Retuned R×1.2 (fc ≈ 1,688 Hz)")
    a1.axvline(6400, color="#ea580c", ls=":", lw=1.3, label="50 Hz Nyquist (6.40 kHz)")
    a1.axvline(7680, color="#64748b", ls=":", lw=1.3, label="60 Hz Nyquist (7.68 kHz)")
    a1.set_ylim(-85, 5)
    a1.set_xlabel("Frequency (Hz)")
    a1.set_ylabel("Filter gain (dB)")
    a1.grid(alpha=0.25)
    a1.legend(fontsize=7.5)
    a1.set_title("Same PCB anti-aliasing margin: 50 Hz (VN) vs 60 Hz (US)")

    bands = ["0-1", "1-2", "2-5", "5-10"]
    x = np.arange(len(bands))
    w = 0.36
    b60 = [((f50["vehif_250_resampled_60hz"]["by_peak_fault_current_A_rms"].get(b) or {}).get("detected") or 0.0) * 100 for b in bands]
    b50 = [((f50["vehif_250_native_50hz"]["by_peak_fault_current_A_rms"].get(b) or {}).get("detected") or 0.0) * 100 for b in bands]
    a2.bar(x - w / 2, b60, w, color="#2563eb", label=f"60 Hz resampled ({f50['vehif_250_resampled_60hz']['detection_rate']*100:.1f}%)")
    a2.bar(x + w / 2, b50, w, color="#ea580c", label=f"50 Hz native VN/AU ({f50['vehif_250_native_50hz']['detection_rate']*100:.1f}%)")
    a2.set_xticks(x, [f"{b} A" for b in bands])
    a2.set_ylabel("VeHIF zero-shot detection (%)")
    a2.set_ylim(0, 108)
    a2.grid(axis="y", alpha=0.25)
    a2.legend(fontsize=8)
    a2.set_title("Phase 0 frozen model on 250 VeHIF: 50 Hz vs 60 Hz")
    save_fig(fig, "phase15_50hz_vs_60hz.png")


# ---------------------------------------------------------------- 5. Main runner
def main():
    t_start = time.time()
    print("=== PHASE 1.5: C Firmware Check + 50/60 Hz + Feature Ablation + VeHIF Few-Shot Adaptation ===")

    if not (OUT / "model_int8.npz").exists():
        raise FileNotFoundError("results/model_int8.npz missing (attach Phase 0 model first)")
    phase0_layers, phase0_thr, _ = load_model(OUT / "model_int8.npz")

    # 1. Verify Phase 0 C firmware on official test_vectors.json right away
    print("\n[1/5] Compiling & verifying Phase 0 C firmware (firmware/hif_infer.c + firmware/hif_model.h)...")
    c_phase0_official = verify_c_firmware("hif_model.h", OUT / "test_vectors.json", "phase0_official")
    print("  Phase 0 official 6 vectors:", json.dumps(c_phase0_official))

    # 2. Simulate Phase 0 events (exact same seed=42 & 60/20/20 split as train_kaggle.py)
    print("\n[2/5] Simulating Phase 0 60 Hz reference events (N=4000, seed=42)...")
    t_sim = time.time()
    sim_events = simulate_phase0_events(f_line=F_LINE, n_events=N_EVENTS, seed=SEED)
    sim_tr, sim_va, sim_te = split(sim_events, np.random.default_rng(SEED))
    X_sim_tr, y_sim_tr = stack(sim_tr)
    X_sim_te, y_sim_te = stack(sim_te)
    print(f"  Simulated {len(sim_events)} events in {time.time() - t_sim:.1f} s (tr/va/te = {len(sim_tr)}/{len(sim_va)}/{len(sim_te)})")

    # Extended 100-vector C firmware verification for Phase 0
    ext_vec_p0 = write_extended_vectors(phase0_layers, X_sim_te, y_sim_te, BUILD / "test_vectors_phase0_100.json", n_vecs=100, seed=42)
    c_phase0_ext = verify_c_firmware("hif_model.h", ext_vec_p0, "phase0_ext100")
    print(f"  Phase 0 extended 100 vectors: max_err={c_phase0_ext.get('max_abs_prob_error')}, "
          f"agree={c_phase0_ext.get('decision_agreement')}, lat={c_phase0_ext.get('host_latency_us_per_inference')} us")

    # Also test simulated 50 Hz (Vietnam) grid events (N=600) with Phase 0 model
    print("  Simulating 600 native 50 Hz (Vietnam) events to test 50 Hz simulated transfer...")
    sim50_events = simulate_phase0_events(f_line=F_LINE_VN, n_events=600, seed=SEED + 50)
    sim50_summary = summarize(sim50_events, [predict_q(phase0_layers, e["X"]) for e in sim50_events], phase0_thr)
    sim60_summary = summarize(sim_te, [predict_q(phase0_layers, e["X"]) for e in sim_te], phase0_thr)

    # 3. Read real VeHIF 22 kV recordings (250 exact Phase-1 subset + 50 extra = 300, plus 53 background)
    h5_path = find_h5()
    if not h5_path:
        raise FileNotFoundError("VeHIF HDF5 dataset not found under /kaggle/input/ or VEHIF_PATH")
    import h5py
    print(f"\n[3/5] Extracting {N_VEHIF_POOL} real VeHIF fault recordings + 53 background from {h5_path}...")
    t_ve = time.time()
    fault_recs, bg_recs, errors = [], [], []
    with h5py.File(h5_path, "r") as f:
        tg = f[next(k for k in f.keys() if k.lower().startswith("test"))]
        cg = f[next(k for k in f.keys() if k.lower().startswith("cal"))]
        ids = sorted(tg.keys())
        valid = [i for i in ids if (attr(tg[i], "report_validity") or "valid").lower() != "invalid"]
        order = np.random.default_rng(VEHIF_SEED).permutation(len(valid))
        p1_ids = sorted(valid[k] for k in order[:N_PHASE1_COMPARE])
        p1_set = set(p1_ids)
        extra_ids = [valid[k] for k in order[N_PHASE1_COMPARE:N_VEHIF_POOL]]
        chosen = p1_ids + extra_ids

        for idx, rec_id in enumerate(chosen):
            if (time.time() - t_ve) / 60.0 > MAX_MINUTES:
                print(f"  time budget reached at {idx}/{len(chosen)} recordings")
                break
            try:
                r = extract_vehif_record(tg[rec_id], rec_id, [VEHIF_SEED, idx], also_60hz=(rec_id in p1_set))
                r["in_phase1_250"] = rec_id in p1_set
                fault_recs.append(r)
            except Exception as e:
                errors.append(f"test {rec_id}: {type(e).__name__}: {e}"[:140])
            if (idx + 1) % 50 == 0:
                print(f"  extracted {idx + 1}/{len(chosen)} fault recordings ({time.time() - t_ve:.0f} s)")

        for idx, rec_id in enumerate(sorted(cg.keys())):
            try:
                bg_recs.append(extract_vehif_record(cg[rec_id], rec_id, [VEHIF_SEED, 100000 + idx], also_60hz=True))
            except Exception as e:
                errors.append(f"bg {rec_id}: {type(e).__name__}: {e}"[:140])
    print(f"  Extracted {len(fault_recs)} fault + {len(bg_recs)} background recordings in {time.time() - t_ve:.1f} s")

    p1_recs = [r for r in fault_recs if r["in_phase1_250"]]

    # 4. 50 Hz (Vietnam) vs 60 Hz (US) evaluation
    print("\n[4/5] Running 50 Hz vs 60 Hz comparison & Feature-Group Ablation...")
    freq_comp = {
        "hardware_60hz_us": frequency_response_summary(F_LINE, STAGES),
        "hardware_50hz_vn_same_pcb": frequency_response_summary(F_LINE_VN, STAGES),
        "hardware_50hz_vn_retuned_R1p2": frequency_response_summary(F_LINE_VN, STAGES_50HZ_RETUNED),
        "sim_60hz_test_800": {
            "detection_rate": sim60_summary["detection_rate"],
            "false_alarm_rate_normal": sim60_summary["false_alarm_rate_normal"],
        },
        "sim_50hz_test_600": {
            "detection_rate": sim50_summary["detection_rate"],
            "false_alarm_rate_normal": sim50_summary["false_alarm_rate_normal"],
        },
        "vehif_250_resampled_60hz": eval_vehif_records(p1_recs, phase0_layers, phase0_thr, mode="60hz"),
        "vehif_250_native_50hz": eval_vehif_records(p1_recs, phase0_layers, phase0_thr, mode="50hz"),
        "bg_53_resampled_60hz": eval_bg_records(bg_recs, phase0_layers, phase0_thr, mode="60hz"),
        "bg_53_native_50hz": eval_bg_records(bg_recs, phase0_layers, phase0_thr, mode="50hz"),
    }
    print(f"  250 VeHIF zero-shot: 60Hz={freq_comp['vehif_250_resampled_60hz']['detection_rate']:.1%} "
          f"vs 50Hz={freq_comp['vehif_250_native_50hz']['detection_rate']:.1%}")

    # Feature-group ablation (trained ONLY on Phase 0 simulated data, zero-shot to VeHIF 50 Hz)
    ablation_res = {}
    for name, cols in ABLATION_SETS.items():
        fidx = [FEATURES.index(c) for c in cols]
        L_ab, thr_ab = fit_subset_int8(sim_tr, sim_va, fidx, seed=SEED)
        sim_r = summarize(sim_te, [predict_q(L_ab, e["X"][:, fidx]) for e in sim_te], thr_ab)
        ve_r = eval_vehif_records(p1_recs, L_ab, thr_ab, feat_idx=fidx, mode="50hz")
        bg_r = eval_bg_records(bg_recs, L_ab, thr_ab, feat_idx=fidx, mode="50hz")
        ablation_res[name] = {
            "n_features": len(cols),
            "features": cols,
            "threshold": thr_ab,
            "sim_test": {
                "detection_rate": sim_r["detection_rate"],
                "false_alarm_rate_normal": sim_r["false_alarm_rate_normal"],
                "fa_inrush": sim_r["false_alarm_by_disturbance"]["inrush"],
                "fa_motor_start": sim_r["false_alarm_by_disturbance"]["motor_start"],
                "fa_arc_welder": sim_r["false_alarm_by_disturbance"]["arc_welder"],
            },
            "real_vehif_50hz": ve_r,
            "real_bg_50hz": bg_r,
        }
        print(f"  Ablation {name:16s}: sim_det={sim_r['detection_rate']:.1%}, sim_fa={sim_r['false_alarm_rate_normal']:.1%}, "
              f"real_vehif={ve_r['detection_rate']:.1%} (0-2A={ve_r['detection_rate_0_to_2A']:.1%}), bg_fa={bg_r['alarm_rate']:.1%}")

    # 5. Few-shot real-VeHIF adaptation (strict recording-level disjoint splits, 5 seeds)
    print("\n[5/5] Running leak-free Few-Shot Real-VeHIF Adaptation (5%, 10%, 20% x 5 seeds)...")
    z0_runs = []
    by_frac = {str(fr): {"head_recal_int8": [], "joint_mlp_int8": []} for fr in ADAPT_FRACS}
    best_model_export = None

    for s in ADAPT_SEEDS:
        te_idx, pool_idx = stratified_split_indices(fault_recs, test_frac=0.60, seed=100 + s)
        real_te = [fault_recs[i] for i in te_idx]
        rng_bg = np.random.default_rng(200 + s)
        bg_perm = rng_bg.permutation(len(bg_recs))
        bg_adapt = [bg_recs[i] for i in bg_perm[:20]]
        bg_te = [bg_recs[i] for i in bg_perm[20:]]

        # Zero-shot Phase 0 on this exact seed's held-out test split
        z_ve = eval_vehif_records(real_te, phase0_layers, phase0_thr, mode="50hz")
        z_bg = eval_bg_records(bg_te, phase0_layers, phase0_thr, mode="50hz")
        z0_runs.append({
            "seed": s, "real_ve": z_ve, "real_bg": z_bg,
            "sim_det": sim60_summary["detection_rate"],
            "sim_fa": sim60_summary["false_alarm_rate_normal"],
        })

        for fr in ADAPT_FRACS:
            n_take = max(1, int(round(fr * len(fault_recs))))
            sel_idx = stratified_prefix(fault_recs, pool_idx, n_take, seed=300 + s * 10 + n_take)
            adapt_recs = [fault_recs[i] for i in sel_idx]
            X_real, y_real = sample_real_adapt_windows(adapt_recs, bg_adapt, np.random.default_rng(400 + s * 10 + n_take))

            for method in ("head_recal_int8", "joint_mlp_int8"):
                if method == "head_recal_int8":
                    layers_m = fit_head_recal_int8(phase0_layers, X_sim_tr, y_sim_tr, X_real, y_real, seed=500 + s)
                else:
                    layers_m = fit_joint_mlp_int8(X_sim_tr, y_sim_tr, X_real, y_real, seed=600 + s)

                sim_va_scores = [predict_q(layers_m, e["X"]) for e in sim_va]
                real_ctrl_scores = [predict_q(layers_m, r["Xc50"]) for r in adapt_recs] + [
                    predict_q(layers_m, b["Xf50"]) for b in bg_adapt]
                thr_m = pick_joint_threshold(sim_va, sim_va_scores, real_ctrl_scores,
                                             max_sim_fa=MAX_FALSE_ALARM, max_real_fa=0.02)
                ve_m = eval_vehif_records(real_te, layers_m, thr_m, mode="50hz")
                bg_m = eval_bg_records(bg_te, layers_m, thr_m, mode="50hz")
                sim_m = summarize(sim_te, [predict_q(layers_m, e["X"]) for e in sim_te], thr_m)
                by_frac[str(fr)][method].append({
                    "seed": s,
                    "n_adapt_recordings": len(adapt_recs),
                    "threshold": thr_m,
                    "real_ve": ve_m,
                    "real_bg": bg_m,
                    "sim_det": sim_m["detection_rate"],
                    "sim_fa": sim_m["false_alarm_rate_normal"],
                    "sim_fa_by_dist": sim_m["false_alarm_by_disturbance"],
                })
                if s == 0 and fr == 0.20 and method == "joint_mlp_int8":
                    best_model_export = (layers_m, thr_m, ve_m, bg_m, sim_m)

        print(f"  seed {s} done | 0%: {z_ve['detection_rate']:.1%} | "
              f"20% head: {by_frac['0.2']['head_recal_int8'][-1]['real_ve']['detection_rate']:.1%} | "
              f"20% joint: {by_frac['0.2']['joint_mlp_int8'][-1]['real_ve']['detection_rate']:.1%} "
              f"(0-2A={by_frac['0.2']['joint_mlp_int8'][-1]['real_ve']['detection_rate_0_to_2A']:.1%}, "
              f"sim_fa={by_frac['0.2']['joint_mlp_int8'][-1]['sim_fa']:.1%}, "
              f"bg_fa={by_frac['0.2']['joint_mlp_int8'][-1]['real_bg']['alarm_rate']:.1%})")

    def agg(runs):
        bands = ["0-1", "1-2", "2-5", "5-10"]
        band_mean = {}
        band_std = {}
        for b in bands:
            vals = [r["real_ve"]["by_peak_fault_current_A_rms"][b]["detected"]
                    for r in runs if r["real_ve"]["by_peak_fault_current_A_rms"][b]["detected"] is not None]
            band_mean[b] = float(np.mean(vals)) if vals else None
            band_std[b] = float(np.std(vals)) if vals else None
        return {
            "n_seeds": len(runs),
            "n_adapt_recordings": runs[0].get("n_adapt_recordings", 0),
            "n_heldout_fault": runs[0]["real_ve"]["recordings"],
            "n_heldout_bg": runs[0]["real_bg"]["recordings"],
            "real_detection_mean": float(np.mean([r["real_ve"]["detection_rate"] for r in runs])),
            "real_detection_std": float(np.std([r["real_ve"]["detection_rate"] for r in runs])),
            "real_0_to_2A_mean": float(np.mean([r["real_ve"]["detection_rate_0_to_2A"] for r in runs])),
            "real_0_to_2A_std": float(np.std([r["real_ve"]["detection_rate_0_to_2A"] for r in runs])),
            "real_control_fa_mean": float(np.mean([r["real_ve"]["alarm_in_control_rate"] for r in runs])),
            "real_bg_fa_mean": float(np.mean([r["real_bg"]["alarm_rate"] for r in runs])),
            "sim_detection_mean": float(np.mean([r["sim_det"] for r in runs])),
            "sim_fa_mean": float(np.mean([r["sim_fa"] for r in runs])),
            "by_current_band_mean": band_mean,
            "by_current_band_std": band_std,
            "threshold_mean": float(np.mean([r.get("threshold", phase0_thr) for r in runs])),
        }

    adapt_summary = {
        "pool_fault_recordings": len(fault_recs),
        "pool_background_recordings": len(bg_recs),
        "split_protocol": "60% held-out real test / 40% adaptation pool, recording-ID disjoint, stratified by peak current, 5 seeds",
        "fa_guard": {"sim_val_max": MAX_FALSE_ALARM, "real_adapt_control_max": 0.02},
        "zero_shot_phase0": agg(z0_runs),
        "by_fraction": {
            str(fr): {m: agg(by_frac[str(fr)][m]) for m in ("head_recal_int8", "joint_mlp_int8")}
            for fr in ADAPT_FRACS
        },
    }

    # Export Phase 1.5 adapted 504 B int8 model + C header + run GCC verification on it!
    c_phase15 = None
    if best_model_export is not None:
        L15, thr15, _, _, _ = best_model_export
        d15 = {"thr": thr15}
        for n, L in enumerate(L15):
            d15[f"W{n}"], d15[f"s{n}"], d15[f"b{n}"] = L["Wq"], L["scale"], L["b"]
        np.savez(OUT / "model_phase15_int8.npz", **d15)
        export_c_header(L15, thr15, FW / "hif_model_phase15.h",
                        "Auto-generated by phase15_vehif_adaptation.py (20% VeHIF joint fine-tuned 504 B int8 MLP).")
        vec15_path = write_extended_vectors(L15, X_sim_te, y_sim_te, OUT / "test_vectors_phase15.json", n_vecs=100, seed=15)
        c_phase15 = verify_c_firmware("hif_model_phase15.h", vec15_path, "phase15")
        print(f"\n  Phase 1.5 C firmware check: max_err={c_phase15.get('max_abs_prob_error')}, "
              f"agree={c_phase15.get('decision_agreement')}, pass={c_phase15.get('parity_pass')}")

    # Pre-registered acceptance criteria P1.5-A..D
    z0_agg = adapt_summary["zero_shot_phase0"]
    j20_agg = adapt_summary["by_fraction"]["0.2"]["joint_mlp_int8"]
    gain_02 = j20_agg["real_0_to_2A_mean"] - z0_agg["real_0_to_2A_mean"]
    criteria = {
        "P1_5_A_low_current_gain_ge_15pp": {
            "pass": bool(gain_02 >= 0.15),
            "measured_delta_0_to_2A": round(gain_02, 4),
            "zero_shot_0_to_2A": round(z0_agg["real_0_to_2A_mean"], 4),
            "adapted_20pct_0_to_2A": round(j20_agg["real_0_to_2A_mean"], 4),
        },
        "P1_5_B_real_bg_and_control_fa_le_3pct": {
            "pass": bool(j20_agg["real_bg_fa_mean"] <= 0.03 and j20_agg["real_control_fa_mean"] <= 0.03),
            "real_bg_fa_mean": round(j20_agg["real_bg_fa_mean"], 4),
            "real_control_fa_mean": round(j20_agg["real_control_fa_mean"], 4),
        },
        "P1_5_C_no_catastrophic_forgetting_sim": {
            "pass": bool(j20_agg["sim_detection_mean"] >= 0.88 and j20_agg["sim_fa_mean"] <= 0.03),
            "sim_detection_mean": round(j20_agg["sim_detection_mean"], 4),
            "sim_fa_mean": round(j20_agg["sim_fa_mean"], 4),
        },
        "P1_5_D_c_firmware_bit_parity": {
            "pass": bool(c_phase0_official.get("parity_pass") and c_phase0_ext.get("parity_pass")
                         and (c_phase15 or {}).get("parity_pass")),
            "phase0_official_max_err": c_phase0_official.get("max_abs_prob_error"),
            "phase0_ext100_max_err": c_phase0_ext.get("max_abs_prob_error"),
            "phase15_ext100_max_err": (c_phase15 or {}).get("max_abs_prob_error"),
        },
    }

    c_verify_out = {
        "note": "Compiled and executed natively on Linux GCC with -O2 -Wall -Wextra -Werror.",
        "phase0_official_6_vectors": c_phase0_official,
        "phase0_extended_100_vectors": c_phase0_ext,
        "phase15_adapted_100_vectors": c_phase15,
    }
    (OUT / "c_firmware_verify.json").write_text(json.dumps(c_verify_out, indent=2) + "\n", encoding="utf-8")

    res = {
        "note": "REAL VeHIF 22 kV 50 Hz vegetation fault currents & 53 background recordings through SIMULATED "
                "sensor + SIMULATED feeder load, combined with SIMULATED Emanuel arcs & 7 disturbances. "
                "Not a field test of physical hardware.",
        "data": "D. Gomes and C. Ozansoy, VeHIF, IEEE Trans. Power Delivery 37(6), 2022; "
                "kaggle.com/datasets/dougpsg/highimpedance-vegetation-fault-data-set (CC0)",
        "freq_50hz_vs_60hz": freq_comp,
        "feature_ablation": ablation_res,
        "few_shot_adaptation": adapt_summary,
        "c_firmware_verify": c_verify_out,
        "criteria": criteria,
        "errors": errors[:20],
        "runtime_s": round(time.time() - t_start, 1),
    }
    (OUT / "phase15_vehif.json").write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    make_figures(res)

    print("\n================ PHASE 1.5 SUMMARY ================")
    print("Criteria:", json.dumps(criteria, indent=2))
    print(f"Total runtime: {res['runtime_s']} s -> results/phase15_vehif.json, results/c_firmware_verify.json")
    return res


if __name__ == "__main__":
    main()
