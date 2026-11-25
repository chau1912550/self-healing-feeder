"""Phase 1 of the HIF sensor: test the simulation-trained detector on REAL fault recordings.

Data set: VeHIF, 983 vegetation high-impedance fault tests and 53 background recordings made on a real
22 kV, 50 Hz feeder (funded by the Victorian Government, Australia). HDF5 format: D. Gomes and C. Ozansoy,
IEEE Trans. Power Delivery 37(6), 2022 (arXiv:2112.03651). Kaggle: dougpsg/highimpedance-vegetation-fault-data-set.

What is real and what is simulated here:
- REAL: the fault current waveform (LF channel) and the background recordings.
- SIMULATED: the sensor (front end + 12-bit ADC model) and the residual load current of the feeder, which is
  added on top of the real current. Each recording runs twice with the same load: without the recording
  (control) and with it. "Detected" = an alarm with the real fault and no alarm in the control.
- The detector is the Phase 0 model, trained on simulated arcs only. Nothing is re-trained here.
The 50 Hz recordings are resampled to 256 samples per cycle so harmonic orders match the 60 Hz design.
Vegetation faults are not downed conductors, so this measures how far the simulation-trained model transfers.
"""
import csv
import glob
import json
import os
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

from hif.features import FEATURES, K, window_features, window_labels
from hif.frontend import FS_SIM, N_CYCLE, OVERSAMPLE, codes_to_amps, sense
from hif.waveforms import SURFACES, WARMUP, _arc, _base, make_event
from train_kaggle import alarms, predict_q

H5_NAME = "hif_vegetation_dataset.h5"
N_TESTS = 250            # fault recordings to read; None = every valid one (slower)
MAX_SECONDS = 120        # only the last part of a long recording is analysed
MAX_MINUTES = 45         # stop reading new recordings after this long
GRID_HZ = 50.0
SEED = 7
SPC = N_CYCLE * OVERSAMPLE                                      # 2048 samples per cycle go into the sensor model
BINS = [(0, 1), (1, 2), (2, 5), (5, 10), (10, 1e9)]             # fault current, A rms (same bins as Phase 0)
RATIO_BINS = [(0, 0.05), (0.05, 0.2), (0.2, 0.5), (0.5, 1e9)]   # fault current / load current
J1, J3 = FEATURES.index("log_I1"), FEATURES.index("log_I3")
OUT = Path("results")
FIG = OUT / "figures"


# ---------------------------------------------------------------- reading the file
def find_h5():
    p = os.environ.get("VEHIF_PATH")
    if p and Path(p).exists():
        return p
    hits = glob.glob("/kaggle/input/**/" + H5_NAME, recursive=True)
    hits = hits or glob.glob("/kaggle/input/**/*.h5", recursive=True)
    return hits[0] if hits else None


def load_model(path=None):
    z = np.load(path or OUT / "model_int8.npz")
    layers, n = [], 0
    while f"W{n}" in z.files:
        layers.append({"Wq": z[f"W{n}"], "scale": float(z[f"s{n}"]), "b": z[f"b{n}"]})
        n += 1
    pick = {k[len("pickup_"):]: float(z[k]) for k in z.files if k.startswith("pickup_")}
    return layers, float(z["thr"]), pick


def _txt(v):
    if isinstance(v, np.ndarray):
        v = v.ravel()[0] if v.size else ""
    if isinstance(v, bytes):
        v = v.decode(errors="ignore")
    return str(v).strip().strip("\x00")


def attr(g, *names, num=False):
    for n in names:
        if n in g.attrs:
            v = g.attrs[n]
            if not num:
                return _txt(v)
            try:
                a = np.asarray(v, np.float64).ravel()
                return float(a[0]) if a.size and np.isfinite(a[0]) and a[0] > 0 else None
            except (TypeError, ValueError):
                return None
    return None


def _axis_slice(ds, lo, hi):
    ax = int(np.argmax(ds.shape))
    sl = [slice(None)] * len(ds.shape)
    sl[ax] = slice(lo, hi)
    return np.asarray(ds[tuple(sl)], np.float64).ravel()


def read_head(ds, n):
    return _axis_slice(ds, 0, min(n, max(ds.shape)))


def read_tail(ds, n):
    """Last n samples of a 1-D data set stored as (N,), (N, 1) or (1, N). Returns (samples, N)."""
    N = max(ds.shape)
    return _axis_slice(ds, max(0, N - n), N), N


# ---------------------------------------------------------------- signal helpers
def samples_per_cycle(v, guess=2000.0):
    """Length of one power cycle in samples, measured on the voltage (fallback: 100 kSa/s at 50 Hz)."""
    x = np.asarray(v, np.float64)
    if x.size < 20000 or not np.isfinite(x).all() or x.std() == 0:
        return guess
    X = np.abs(np.fft.rfft((x - x.mean()) * np.hanning(x.size)))
    lo, hi = int(x.size / (guess * 1.5)), int(x.size / (guess / 1.5))
    k = lo + int(np.argmax(X[lo:hi]))
    a, b, c = X[k - 1], X[k], X[k + 1]
    spc = x.size / (k + 0.5 * (a - c) / (a - 2 * b + c - 1e-30))
    return float(spc) if abs(spc / guess - 1) < 0.2 else guess


def to_sensor_rate(x, spc):
    """Resample so that one power cycle = 2048 samples (the rate the sensor model expects)."""
    fr = Fraction(SPC / spc).limit_denominator(1000)
    return signal.resample_poly(x, fr.numerator, fr.denominator)


def cycle_ms(x):
    return (x.reshape(-1, SPC) ** 2).mean(1)


def rolling_rms(ms, n):
    if len(ms) < n:
        return np.sqrt(ms.mean(keepdims=True))
    c = np.cumsum(np.insert(ms, 0, 0.0))
    return np.sqrt((c[n:] - c[:-n]) / n)


def through_sensor(x, rng):
    """Primary current at 2048 samples/cycle -> sensor model -> 16 features per window."""
    amps = codes_to_amps(sense(x, rng))[WARMUP * N_CYCLE:]
    X, _ = window_features(amps)
    return X, np.arange(K - 1, K - 1 + len(X)) + WARMUP     # last cycle of each window, counted in the recording


def first_alarm(score, thr):
    al = alarms(score, thr)
    return al[0] if al else None


# ---------------------------------------------------------------- one recording
def run_record(g, rng, layers, thr, base_thr):
    spc = samples_per_cycle(read_head(g["voltage_lf"], 1 << 18)) if "voltage_lf" in g else 2000.0
    raw, n_total = read_tail(g["current_lf"], int(MAX_SECONDS * GRID_HZ * spc))
    raw = np.nan_to_num(raw)
    x = to_sensor_rate(raw - raw.mean(), spc)
    n = len(x) // SPC * SPC
    if n < 40 * SPC:
        raise ValueError("recording shorter than 40 cycles")
    x = x[:n]
    load, a1, _ = _base(np.arange(n) / FS_SIM, rng)
    ms = cycle_ms(x)
    r8 = rolling_rms(ms, K)
    Xf, ends = through_sensor(load + x, rng)      # load + real recording
    Xc, _ = through_sensor(load, rng)             # control: the same load alone
    out = {"seconds": float(n_total / spc / GRID_HZ), "truncated": bool(len(raw) < n_total),
           "samples_per_cycle": float(spc), "raw_peak_A": float(np.abs(raw).max()),
           "rms_all": float(np.sqrt(ms.mean())), "peak_rms20": float(rolling_rms(ms, 20).max()),
           "load_rms": float(a1 / np.sqrt(2)), "rms_at_alarm": None}
    out["ratio"] = out["peak_rms20"] / out["load_rms"]
    for name, sf, sc, th in (("ml", predict_q(layers, Xf), predict_q(layers, Xc), thr),
                             ("51N", Xf[:, J1], Xc[:, J1], base_thr.get("residual_overcurrent_51N", 9e9)),
                             ("h3", Xf[:, J3], Xc[:, J3], base_thr.get("third_harmonic_level", 9e9))):
        kf, kc = first_alarm(sf, th), first_alarm(sc, th)
        out["alarm_" + name], out["control_" + name] = kf is not None, kc is not None
        out["det_" + name] = kf is not None and kc is None
        if name == "ml" and kf is not None:
            out["rms_at_alarm"] = float(r8[ends[kf] - (K - 1)])
    out["alarm"], out["control_alarm"], out["detected"] = out["alarm_ml"], out["control_ml"], out["det_ml"]
    strong = np.flatnonzero(r8[ends - (K - 1)] >= 1.0)          # windows with at least 1 A rms of real fault current
    out["_feat"] = Xf[strong[:: max(1, len(strong) // 150)][:150]]
    c0 = int(np.argmax(rolling_rms(ms, 3)))
    out["_snip"] = x[c0 * SPC:(c0 + 3) * SPC].astype(np.float32)
    return out


# ---------------------------------------------------------------- summaries
def sim_hif_windows(n_events):
    """Features of simulated arcing windows (same generator as Phase 0), to compare with the real ones."""
    rng = np.random.default_rng(SEED)
    rows = []
    for _ in range(n_events):
        amps, meta = make_event(rng, True)
        X, ends = window_features(amps)
        rows.append(X[window_labels(ends, meta) == 1])
    return np.concatenate(rows)


def feature_shift(real, sim):
    """How far the real arcing windows sit from the simulated ones, feature by feature."""
    out = []
    for j, name in enumerate(FEATURES):
        q25, q50, q75 = np.percentile(sim[:, j], [25, 50, 75])
        med = float(np.median(real[:, j]))
        out.append({"feature": name, "real_median": med, "sim_median": float(q50),
                    "shift_in_sim_iqr": float((med - q50) / (q75 - q25 + 1e-9))})
    return sorted(out, key=lambda d: -abs(d["shift_in_sim_iqr"]))


def by_bins(rows, key, bins, flag="detected"):
    out = {}
    for lo, hi in bins:
        sel = [r[flag] for r in rows if lo <= r[key] < hi]
        out[f"{lo:g}-{hi:g}" if hi < 1e8 else f">{lo:g}"] = {"n": len(sel),
                                                           "detected": float(np.mean(sel)) if sel else None}
    return out


def save(fig, name):
    fig.tight_layout()
    fig.savefig(FIG / name, dpi=120)
    if "ipykernel" in sys.modules:
        plt.show()
    plt.close(fig)


def figures(res, rows, snips, at):
    real = res["real_faults"]["by_peak_fault_current_A_rms"]
    sim = res.get("sim_reference_by_arc_current_A_rms") or {}
    names = list(real)
    fig, ax = plt.subplots(figsize=(7, 3.4))
    x, w = np.arange(len(names)), 0.4
    ax.bar(x - w / 2, [(sim.get(k) or {}).get("detected") or 0 for k in names], w,
           label="simulated arcs (Phase 0 test set)")
    ax.bar(x + w / 2, [real[k]["detected"] or 0 for k in names], w, label="real vegetation faults (VeHIF)")
    for k, name in enumerate(names):
        ax.text(k + w / 2, 0.02, f"n={real[name]['n']}", ha="center", fontsize=7)
    ax.set_xticks(x, names)
    ax.set_xlabel("fault current (A rms)")
    ax.set_ylabel("detected")
    ax.set_ylim(0, 1.05)
    ax.legend(fontsize=8)
    ax.set_title("Same detector: simulated arcs vs real recordings")
    save(fig, "real_detection_by_current.png")

    mid = sorted(rows, key=lambda r: r["peak_rms20"])[len(rows) // 2]["id"]
    arc = _arc(np.arange(40 * SPC) / FS_SIM, 0.0, np.random.default_rng(SEED), SURFACES["dry_grass"])[-3 * SPC:]
    fig, axs = plt.subplots(1, 2, figsize=(9, 3))
    axs[0].plot(np.arange(len(snips[mid])) / SPC, snips[mid])
    axs[0].set_title(f"Real vegetation fault (test {mid})")
    axs[1].plot(np.arange(len(arc)) / SPC, arc, color="tab:orange")
    axs[1].set_title("Simulated arc (Emanuel model, dry grass)")
    for a in axs:
        a.set_xlabel("cycles")
        a.set_ylabel("fault current (A)")
    save(fig, "real_vs_sim_waveform.png")

    if at:
        fig, ax = plt.subplots(figsize=(6, 3.2))
        ax.hist(at, bins=20)
        ax.set_xlabel("real fault current when the alarm was raised (A rms over 8 cycles)")
        ax.set_ylabel("recordings")
        ax.set_title("How much real fault current the detector needed")
        save(fig, "real_current_at_first_alarm.png")


# ---------------------------------------------------------------- main
def evaluate(f, layers, thr, pick, n_tests=N_TESTS, n_sim_events=300):
    t0 = time.time()
    FIG.mkdir(parents=True, exist_ok=True)
    base_thr = {k: float(np.log10(v)) for k, v in pick.items()}
    tg = f[next(k for k in f.keys() if k.lower().startswith("test"))]
    cg = f[next(k for k in f.keys() if k.lower().startswith("cal"))]
    ids = sorted(tg.keys())
    valid = [i for i in ids if (attr(tg[i], "report_validity") or "valid").lower() != "invalid"]
    order = np.random.default_rng(SEED).permutation(len(valid))
    chosen = sorted(valid[k] for k in (order[:n_tests] if n_tests else order))
    g0 = tg[chosen[0]]
    check = {"root_groups": sorted(f.keys()), "tests_in_file": len(ids), "tests_valid": len(valid),
             "background_in_file": len(cg.keys()), "first_test": chosen[0],
             "datasets": {k: [list(map(int, g0[k].shape)), str(getattr(g0[k], "dtype", "?"))] for k in g0.keys()},
             "attributes": {k: _txt(v)[:60] for k, v in dict(g0.attrs).items()}}
    print("FILE CHECK\n" + json.dumps(check, indent=1))

    rows, feats, snips, bg, errors = [], [], {}, [], []
    for n, i in enumerate(chosen):
        if (time.time() - t0) / 60 > MAX_MINUTES:
            print(f"time limit reached after {n} fault recordings")
            break
        try:
            g = tg[i]
            r = run_record(g, np.random.default_rng([SEED, n]), layers, thr, base_thr)
            feats.append(r.pop("_feat"))
            snips[i] = r.pop("_snip")
            r.update(id=i, fault_type=attr(g, "fault_type", "test_type", "cal_type") or "?",
                     max_current_attr=attr(g, "max_current", num=True))
            rows.append(r)
        except Exception as e:      # one unreadable recording must not stop the run
            errors.append(f"test {i}: {type(e).__name__}: {e}"[:160])
        if (n + 1) % 25 == 0:
            print(f"  {n + 1}/{len(chosen)} fault recordings ({time.time() - t0:.0f} s)")
    for n, i in enumerate(sorted(cg.keys())):
        try:
            r = run_record(cg[i], np.random.default_rng([SEED, 100000 + n]), layers, thr, base_thr)
            r.pop("_feat")
            r.pop("_snip")
            r["id"] = i
            bg.append(r)
        except Exception as e:
            errors.append(f"background {i}: {type(e).__name__}: {e}"[:160])
    if not rows:
        raise RuntimeError("no fault recording could be read: " + "; ".join(errors[:3]))

    at = [r["rms_at_alarm"] for r in rows if r["detected"] and not r["truncated"]]
    unit = [r["peak_rms20"] / r["max_current_attr"] for r in rows if r["max_current_attr"]]
    types = sorted({r["fault_type"] for r in rows})
    res = {
        "note": "REAL fault currents (VeHIF, 22 kV, 50 Hz vegetation faults) through a SIMULATED sensor with a "
                "SIMULATED load current added. Detector = Phase 0 model trained on simulated arcs only. "
                "Not a field test of hardware.",
        "data": "D. Gomes and C. Ozansoy, VeHIF, IEEE Trans. Power Delivery 37(6), 2022; "
                "kaggle.com/datasets/dougpsg/highimpedance-vegetation-fault-data-set (CC0)",
        "file_check": check,
        "setup": {"fault_recordings_requested": n_tests, "seconds_analysed_max": MAX_SECONDS, "seed": SEED,
                  "threshold": thr, "resampled_to_samples_per_cycle": N_CYCLE},
        "units_check_peak_rms_over_reported_max_current_median": float(np.median(unit)) if unit else None,
        "real_faults": {
            "recordings": len(rows),
            "detection_rate": float(np.mean([r["detected"] for r in rows])),
            "alarm_in_control_rate": float(np.mean([r["control_alarm"] for r in rows])),
            "peak_fault_current_A_rms_median": float(np.median([r["peak_rms20"] for r in rows])),
            "by_peak_fault_current_A_rms": by_bins(rows, "peak_rms20", BINS),
            "by_fault_to_load_ratio": by_bins(rows, "ratio", RATIO_BINS),
            "by_fault_type": {t: {"n": sum(r["fault_type"] == t for r in rows),
                                  "detected": float(np.mean([r["detected"] for r in rows if r["fault_type"] == t]))}
                              for t in types},
            "fault_A_rms_at_first_alarm": ({"n": len(at), "p25": float(np.percentile(at, 25)),
                                            "median": float(np.median(at)), "p75": float(np.percentile(at, 75))}
                                           if at else None),
            "baseline_detection_rate": {"residual_overcurrent_51N": float(np.mean([r["det_51N"] for r in rows])),
                                        "third_harmonic_level": float(np.mean([r["det_h3"] for r in rows]))},
        },
        "background_recordings": ({"recordings": len(bg),
                                   "alarm_rate": float(np.mean([r["alarm"] for r in bg])),
                                   "alarm_in_control_rate": float(np.mean([r["control_alarm"] for r in bg])),
                                   "noise_A_rms_median": float(np.median([r["rms_all"] for r in bg]))}
                                  if bg else None),
        "errors": errors[:20],
    }
    if (OUT / "metrics.json").exists():
        m = json.loads((OUT / "metrics.json").read_text())
        res["sim_reference_by_arc_current_A_rms"] = m.get("test_ml_int8", {}).get("by_arc_current_A_rms")
        res["sim_reference_detection_rate"] = m.get("test_ml_int8", {}).get("detection_rate")
    real = np.concatenate(feats) if feats else np.zeros((0, len(FEATURES)))
    res["real_windows_with_1A_or_more"] = int(len(real))
    if len(real) >= 50 and n_sim_events:
        res["feature_shift_real_vs_sim"] = feature_shift(real, sim_hif_windows(n_sim_events))
    res["runtime_s"] = round(time.time() - t0, 1)

    def conv(o):
        return o.item() if hasattr(o, "item") else str(o)

    (OUT / "real_vehif.json").write_text(json.dumps(res, indent=2, default=conv))
    cols = [k for k in rows[0] if not k.startswith("_")]
    with open(OUT / "real_vehif_tests.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    try:
        figures(res, rows, snips, at)
    except Exception as e:
        print("figures skipped:", type(e).__name__, e)

    def short(d):
        return {k: (v["n"], None if v["detected"] is None else round(v["detected"], 3)) for k, v in d.items()}

    rf = res["real_faults"]
    print("\n================ PHASE 1: REAL RECORDINGS (simulated sensor + load) ================")
    print(f"fault recordings read {rf['recordings']} | detected {rf['detection_rate']:.1%}"
          f" | alarm in control {rf['alarm_in_control_rate']:.1%}"
          f" | median peak fault current {rf['peak_fault_current_A_rms_median']:.2f} A rms")
    print("units check (measured peak / reported max current, median):",
          res["units_check_peak_rms_over_reported_max_current_median"])
    print("by peak fault current A rms (n, detected):", short(rf["by_peak_fault_current_A_rms"]))
    print("by fault/load ratio (n, detected):", short(rf["by_fault_to_load_ratio"]))
    print("by fault type (n, detected):", short(rf["by_fault_type"]))
    print("fault current at first alarm:", rf["fault_A_rms_at_first_alarm"])
    print("baselines:", rf["baseline_detection_rate"])
    print("background recordings:", res["background_recordings"])
    if "feature_shift_real_vs_sim" in res:
        print("largest real-vs-simulated feature shifts:",
              [(d["feature"], round(d["shift_in_sim_iqr"], 2)) for d in res["feature_shift_real_vs_sim"][:5]])
    if errors:
        print(f"{len(errors)} recordings skipped, first:", errors[0])
    print(f"runtime {res['runtime_s']} s -> results/real_vehif.json, results/real_vehif_tests.csv")
    return res


def main():
    if not (OUT / "model_int8.npz").exists():
        print("Phase 1 skipped: run Phase 0 first (results/model_int8.npz is missing).")
        return None
    path = find_h5()
    if path is None:
        print("Phase 1 skipped: the VeHIF data set is not attached. On Kaggle: Add Input -> search "
              "'High-impedance vegetation fault data set' (Douglas Gomes) -> +, then Run All again.")
        return None
    import h5py
    layers, thr, pick = load_model()
    print("reading", path)
    with h5py.File(path, "r") as f:
        return evaluate(f, layers, thr, pick)


if __name__ == "__main__":
    main()
