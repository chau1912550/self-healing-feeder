"""Phase 0 of the HIF sensor: simulate events, train a tiny MLP, quantize to int8, evaluate, export.

Run on Kaggle (CPU is enough). Writes results/metrics.json, results/figures/*.png,
firmware/hif_model.h and results/test_vectors.json.
"""
import json
import sys
import time
from pathlib import Path

import matplotlib
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import roc_auc_score
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

from hif.features import FEATURES, K, window_features, window_labels
from hif.frontend import cutoff_hz
from hif.waveforms import DISTURBANCES, SURFACES, make_event

SEED = 42
N_EVENTS = 4000            # half HIF, half normal
MAX_FALSE_ALARM = 0.01     # share of normal records allowed to alarm (picked on validation)
PERSIST = 3                # consecutive windows above threshold before an alarm (like a relay timer)
HIDDEN = (16, 8)
OUT = Path("results")
FIG = OUT / "figures"
FW = Path("firmware")
for d in (OUT, FIG, FW):
    d.mkdir(parents=True, exist_ok=True)


def show(fig, name):
    fig.tight_layout()
    fig.savefig(FIG / name, dpi=120)
    if "ipykernel" in sys.modules:
        plt.show()
    plt.close(fig)


# ---------------------------------------------------------------- 1. simulate
def simulate():
    rng = np.random.default_rng(SEED)
    events = []
    t0 = time.time()
    for k in range(N_EVENTS):
        amps, meta = make_event(rng, is_hif=(k % 2 == 0))
        X, ends = window_features(amps)
        events.append({"X": X, "ends": ends, "y": window_labels(ends, meta), **meta})
        if (k + 1) % 500 == 0:
            print(f"  simulated {k + 1}/{N_EVENTS} events ({time.time() - t0:.0f} s)")
    return events


# ---------------------------------------------------------------- 2. model helpers
def stack(evs):
    X = np.concatenate([e["X"] for e in evs])
    y = np.concatenate([e["y"] for e in evs])
    keep = y >= 0
    return X[keep], y[keep]


def fit(evs):
    X, y = stack(evs)
    sc = StandardScaler().fit(X)
    clf = MLPClassifier(hidden_layer_sizes=HIDDEN, alpha=1e-3, max_iter=400, early_stopping=True,
                        n_iter_no_change=15, random_state=SEED).fit(sc.transform(X), y)
    return sc, clf


def fold_and_quantize(sc, clf):
    """Fold the scaler into layer 1, then int8 weights (per-layer scale) + float32 biases."""
    Ws = [w.copy() for w in clf.coefs_]
    bs = [b.copy() for b in clf.intercepts_]
    bs[0] = bs[0] - (sc.mean_ / sc.scale_) @ Ws[0]
    Ws[0] = Ws[0] / sc.scale_[:, None]
    layers = []
    for W, b in zip(Ws, bs):
        s = float(np.abs(W).max() / 127.0)
        layers.append({"Wq": np.round(W / s).astype(np.int8), "scale": s, "b": b.astype(np.float32)})
    return layers


def predict_q(layers, X):
    h = X.astype(np.float32)
    for n, L in enumerate(layers):
        h = h @ (L["Wq"].astype(np.float32) * L["scale"]) + L["b"]
        h = np.maximum(h, 0) if n < len(layers) - 1 else 1 / (1 + np.exp(-h))
    return h.ravel()


def alarms(p, thr):
    run, out = 0, []
    for k, a in enumerate(p > thr):
        run = run + 1 if a else 0
        if run == PERSIST:
            out.append(k)
    return out


def event_result(e, score, thr):
    al = [int(e["ends"][k]) for k in alarms(score, thr)]
    s = e["start_cycle"]
    if e["is_hif"]:
        pre = any(a < s for a in al)
        post = [a for a in al if a >= s]
        return {"false_alarm": pre, "detected": bool(post), "delay": (post[0] - s) if post else None}
    return {"false_alarm": bool(al), "detected": False, "delay": None}


def pick_threshold(evs, scores, grid):
    """Lowest threshold whose false-alarm rate is within budget (FA falls as thr rises: bisection)."""
    def fa(thr):
        return np.mean([event_result(e, s, thr)["false_alarm"] for e, s in zip(evs, scores)])
    lo, hi = 0, len(grid) - 1
    if fa(grid[hi]) > MAX_FALSE_ALARM:
        return float(grid[hi])
    while lo < hi:
        mid = (lo + hi) // 2
        if fa(grid[mid]) <= MAX_FALSE_ALARM:
            hi = mid
        else:
            lo = mid + 1
    return float(grid[lo])


def summarize(evs, scores, thr):
    res = [event_result(e, s, thr) for e, s in zip(evs, scores)]
    hif = [(e, r) for e, r in zip(evs, res) if e["is_hif"]]
    nor = [(e, r) for e, r in zip(evs, res) if not e["is_hif"]]
    delays = [r["delay"] for _, r in hif if r["delay"] is not None]
    out = {
        "hif_records": len(hif), "normal_records": len(nor),
        "detection_rate": float(np.mean([r["detected"] for _, r in hif])),
        "false_alarm_rate_normal": float(np.mean([r["false_alarm"] for _, r in nor])),
        "pre_fault_false_alarm_rate_hif": float(np.mean([r["false_alarm"] for _, r in hif])),
        "delay_cycles_median": float(np.median(delays)) if delays else None,
        "delay_cycles_p90": float(np.percentile(delays, 90)) if delays else None,
        "by_surface": {s: float(np.mean([r["detected"] for e, r in hif if e["surface"] == s]))
                       for s in SURFACES},
        "false_alarm_by_disturbance": {d: float(np.mean([r["false_alarm"] for e, r in nor
                                                        if e["disturbance"] == d]))
                                       for d in DISTURBANCES},
    }
    bins = [(0, 1), (1, 2), (2, 5), (5, 10), (10, 1e9)]
    out["by_arc_current_A_rms"] = {}
    for lo, hi in bins:
        sel = [r["detected"] for e, r in hif if lo <= e["arc_rms"] < hi]
        key = f"{lo}-{hi}" if hi < 1e9 else f">{lo}"
        out["by_arc_current_A_rms"][key] = {"n": len(sel), "detected": float(np.mean(sel)) if sel else None}
    return out


def split(evs, rng):
    idx = rng.permutation(len(evs))
    n1, n2 = int(0.6 * len(evs)), int(0.8 * len(evs))
    return [evs[i] for i in idx[:n1]], [evs[i] for i in idx[n1:n2]], [evs[i] for i in idx[n2:]]


def train_eval(tr, va, te):
    sc, clf = fit(tr)
    layers = fold_and_quantize(sc, clf)
    grid = np.linspace(0.30, 0.999, 300)
    thr = pick_threshold(va, [predict_q(layers, e["X"]) for e in va], grid)
    return layers, thr, summarize(te, [predict_q(layers, e["X"]) for e in te], thr)


# ---------------------------------------------------------------- 3. main
def main():
    t_start = time.time()
    print(f"front-end model -3 dB = {cutoff_hz():.1f} Hz (LTspice: 2045.1 Hz)")
    events = simulate()
    rng = np.random.default_rng(SEED)
    tr, va, te = split(events, rng)
    print(f"events train/val/test = {len(tr)}/{len(va)}/{len(te)}")

    # main model
    sc, clf = fit(tr)
    layers = fold_and_quantize(sc, clf)
    grid = np.linspace(0.30, 0.999, 300)
    thr = pick_threshold(va, [predict_q(layers, e["X"]) for e in va], grid)
    te_q = [predict_q(layers, e["X"]) for e in te]
    te_f = [clf.predict_proba(sc.transform(e["X"]))[:, 1] for e in te]
    ml = summarize(te, te_q, thr)
    Xt, yt = stack(te)
    pq = predict_q(layers, Xt)
    pf = clf.predict_proba(sc.transform(Xt))[:, 1]
    n_params = sum(L["Wq"].size + L["b"].size for L in layers)
    model_bytes = sum(L["Wq"].size + 4 * L["b"].size + 4 for L in layers)

    # classical baselines, same persistence logic and same false-alarm budget
    base = {}
    for name, col in (("residual_overcurrent_51N", "log_I1"), ("third_harmonic_level", "log_I3")):
        j = FEATURES.index(col)
        g = np.linspace(-1.0, 2.5, 400)
        bthr = pick_threshold(va, [e["X"][:, j] for e in va], g)
        base[name] = summarize(te, [e["X"][:, j] for e in te], bthr)
        base[name]["pickup_A_peak"] = float(10 ** bthr)

    # generalization: leave one surface out, and an unseen hard-negative load
    loso = {}
    for s in SURFACES:
        keep = lambda e: not (e["is_hif"] and e["surface"] == s)  # noqa: E731
        _, _, r = train_eval([e for e in tr if keep(e)], [e for e in va if keep(e)], te)
        loso[s] = {"detection_unseen_surface": r["by_surface"][s],
                   "false_alarm_rate_normal": r["false_alarm_rate_normal"]}
        print(f"  leave-out {s}: detection {r['by_surface'][s]:.3f}")
    keep = lambda e: e["disturbance"] != "arc_welder" or e["is_hif"]  # noqa: E731
    _, _, r = train_eval([e for e in tr if keep(e)], [e for e in va if keep(e)], te)
    unseen_welder = {"false_alarm_arc_welder_unseen": r["false_alarm_by_disturbance"]["arc_welder"],
                     "false_alarm_arc_welder_seen": ml["false_alarm_by_disturbance"]["arc_welder"]}

    metrics = {
        "note": "All waveforms are simulated (Emanuel arc model + assumed load/disturbance ranges). "
                "Not field data.",
        "setup": {"events": N_EVENTS, "cycles_per_event": 60, "window_cycles": K,
                  "features": FEATURES, "hidden": list(HIDDEN), "persist_windows": PERSIST,
                  "false_alarm_budget_val": MAX_FALSE_ALARM, "seed": SEED,
                  "windows_total": int(sum(len(e["y"]) for e in events))},
        "frontend_cutoff_hz_python": cutoff_hz(),
        "model": {"params": int(n_params), "bytes_int8_weights_float_bias": int(model_bytes),
                  "threshold": thr, "window_auc_int8": float(roc_auc_score(yt, pq)),
                  "window_auc_float": float(roc_auc_score(yt, pf)),
                  "window_decision_agreement_int8_vs_float": float(np.mean((pq > thr) == (pf > thr))),
                  "event_detection_float": summarize(te, te_f, thr)["detection_rate"]},
        "test_ml_int8": ml,
        "test_baselines": base,
        "leave_one_surface_out": loso,
        "unseen_arc_welder": unseen_welder,
        "runtime_s": round(time.time() - t_start, 1),
    }
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2))
    export_firmware(layers, thr, te, te_q)
    save_model(layers, thr, base)
    figures(ml, base, loso, te)
    print_summary(metrics)


def save_model(layers, thr, base):
    """Python-loadable copy of the int8 model and the baseline pickups (read by real_data_test.py)."""
    d = {"thr": thr}
    for n, L in enumerate(layers):
        d[f"W{n}"], d[f"s{n}"], d[f"b{n}"] = L["Wq"], L["scale"], L["b"]
    for name, br in base.items():
        d["pickup_" + name] = br["pickup_A_peak"]
    np.savez(OUT / "model_int8.npz", **d)


def export_firmware(layers, thr, te, te_q):
    def carr(a, fmt):
        return "{" + ", ".join(fmt(v) for v in np.ravel(a)) + "}"
    def carr2d(a2d, fmt):
        return "{" + ", ".join("{" + ", ".join(fmt(v) for v in row) + "}" for row in a2d) + "}"
    lines = ["// Auto-generated by train_kaggle.py. Tiny MLP for HIF detection (int8 weights).",
             "#pragma once", "#include <stdint.h>",
             f"#define HIF_N_IN {layers[0]['Wq'].shape[0]}", f"#define HIF_PERSIST {PERSIST}",
             f"static const float HIF_THRESHOLD = {thr:.6f}f;"]
    dims = []
    for n, L in enumerate(layers, 1):
        Wt = L["Wq"].T                                    # [out][in]
        dims.append(Wt.shape)
        lines += [f"#define HIF_L{n}_OUT {Wt.shape[0]}", f"#define HIF_L{n}_IN {Wt.shape[1]}",
                  f"static const int8_t HIF_W{n}[{Wt.shape[0]}][{Wt.shape[1]}] = "
                  + carr2d(Wt, lambda v: str(int(v))) + ";",
                  f"static const float HIF_S{n} = {L['scale']:.8e}f;",
                  f"static const float HIF_B{n}[{Wt.shape[0]}] = " + carr(L["b"], lambda v: f"{v:.8e}f") + ";"]
    (FW / "hif_model.h").write_text("\n".join(lines) + "\n")
    vec = []
    for e, p in zip(te[:6], te_q[:6]):
        k = len(p) - 1
        vec.append({"features": e["X"][k].tolist(), "prob": float(p[k]), "is_hif": e["is_hif"]})
    (OUT / "test_vectors.json").write_text(json.dumps(vec, indent=2))


def figures(ml, base, loso, te):
    names = list(SURFACES)
    fig, ax = plt.subplots(figsize=(8, 3.5))
    w = 0.27
    x = np.arange(len(names))
    ax.bar(x - w, [ml["by_surface"][s] for s in names], w, label="tiny MLP (int8)")
    for k, (bn, br) in enumerate(base.items()):
        ax.bar(x + k * w, [br["by_surface"][s] for s in names], w, label=bn)
    ax.set_xticks(x, names)
    ax.set_ylabel("HIF records detected")
    ax.set_ylim(0, 1.05)
    ax.legend(fontsize=8)
    ax.set_title(f"Detection by surface at <= {MAX_FALSE_ALARM:.0%} false alarms (simulated)")
    show(fig, "detection_by_surface.png")

    fig, ax = plt.subplots(figsize=(8, 3.2))
    d = list(DISTURBANCES)
    ax.bar(d, [ml["false_alarm_by_disturbance"][k] for k in d])
    ax.set_ylabel("normal records with an alarm")
    ax.set_title("False alarms by normal event type (test set)")
    plt.setp(ax.get_xticklabels(), rotation=20)
    show(fig, "false_alarm_by_disturbance.png")

    fig, ax = plt.subplots(figsize=(6, 3.2))
    b = ml["by_arc_current_A_rms"]
    ax.bar(list(b), [v["detected"] or 0 for v in b.values()])
    for i, v in enumerate(b.values()):
        ax.text(i, 0.02, f"n={v['n']}", ha="center", fontsize=8, color="white")
    ax.set_xlabel("HIF arc current (A rms)")
    ax.set_ylabel("detected")
    ax.set_title("Detection vs fault current size")
    show(fig, "detection_vs_current.png")

    fig, ax = plt.subplots(figsize=(6, 3.2))
    ax.bar(names, [loso[s]["detection_unseen_surface"] for s in names], color="tab:orange")
    ax.set_ylim(0, 1.05)
    ax.set_title("Detection when the surface was never seen in training")
    plt.setp(ax.get_xticklabels(), rotation=15)
    show(fig, "leave_one_surface_out.png")


def print_summary(m):
    ml = m["test_ml_int8"]
    print("\n================ RESULTS (simulated test set) ================")
    print(f"tiny MLP int8: {m['model']['params']} params, {m['model']['bytes_int8_weights_float_bias']} bytes")
    print(f"HIF detected {ml['detection_rate']:.1%} | normal false alarms {ml['false_alarm_rate_normal']:.1%}"
          f" | median delay {ml['delay_cycles_median']} cycles (p90 {ml['delay_cycles_p90']})")
    for bn, br in m["test_baselines"].items():
        print(f"{bn}: detected {br['detection_rate']:.1%} | false alarms {br['false_alarm_rate_normal']:.1%}"
              f" | pickup {br['pickup_A_peak']:.1f} A peak")
    print("by surface:", {k: round(v, 3) for k, v in ml["by_surface"].items()})
    print("false alarm by load:", {k: round(v, 3) for k, v in ml["false_alarm_by_disturbance"].items()})
    print("leave-one-surface-out:", {k: round(v["detection_unseen_surface"], 3)
                                     for k, v in m["leave_one_surface_out"].items()})
    print("unseen arc welder:", m["unseen_arc_welder"])
    print(f"runtime {m['runtime_s']} s -> results/metrics.json, firmware/hif_model.h")


if __name__ == "__main__":
    main()
