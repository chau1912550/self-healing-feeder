"""How many buses of a new feeder does conformal recalibration need?
(research/active-grid-gnn/PLAN.md Addendum B1 & research/ieee37-underground/PLAN.md Section 4.4)

Uses the probabilities saved by scripts/active_grid_run.py (frozen IEEE 123-bus models applied zero-shot to the
unseen active target feeder). Randomized APS at a 95% target, recalibrated on a growing share of target fault buses
(and the same share of its NO_FAULT events), 50 random draws per share, tested on everything else.

    .venv\\Scripts\\python scripts\\active_conformal_calsize.py                         # ieee34 -> results/active_grid/
    .venv\\Scripts\\python scripts\\active_conformal_calsize.py --test-feeder ieee37    # ieee37 -> results/active_grid_ieee37/

Writes conformal_calsize.json with a run record. Simulation only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shf import active_grid as ag, active_models as am, provenance  # noqa: E402

FRACTIONS = (0.05, 0.10, 0.20, 0.30, 0.40)
N_DRAWS = 50
ALPHA = 0.05
METHOD = "aps_rand"
U_SEED = 12345            # same uniform draws as scripts/active_conformal_posthoc.py (salt 1 = target feeder)
CRIT_MEAN, CRIT_P10 = 0.945, 0.920


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-feeder", choices=["ieee34", "ieee37"], default="ieee34")
    args = ap.parse_args()
    tf = args.test_feeder
    tag = "34" if tf == "ieee34" else "37"
    if tf == "ieee34":
        src = ag.transfer.OUT_DIR / "active_probs.npz"
        summary_dir = ag.ACTIVE_SUMMARY_DIR
        producer = "active_conformal_calsize"
        plan_ref = "research/active-grid-gnn/PLAN.md, Addendum B1 (written before this run)"
    else:
        src = ag.transfer.OUT_DIR / "active_grid_ieee37_probs.npz"
        summary_dir = ag.config.RESULTS / "active_grid_ieee37"
        producer = "active_conformal_calsize_ieee37"
        plan_ref = "research/ieee37-underground/PLAN.md, Section 4.4 (A3-Recal)"

    if not src.exists():
        raise SystemExit(f"{src} not found: it comes from scripts/active_grid_run.py (Kaggle output).")
    d = np.load(src, allow_pickle=False)
    y, bus, nf = d[f"y{tag}"], d[f"bus{tag}"], int(d[f"nofault{tag}"])
    u = np.random.default_rng(U_SEED + 1).uniform(0.0, 1.0, size=len(y))
    fault_buses = np.array(sorted(np.unique(bus[y < nf])))
    nf_idx = np.flatnonzero(y == nf)

    out = {"simulation_only": True, "test_feeder": tf, "plan": plan_ref,
           "score": METHOD, "target": 1 - ALPHA, "draws": N_DRAWS, f"fault_buses_{tag}": int(len(fault_buses)),
           f"nofault_events_{tag}": int(len(nf_idx)),
           "criterion": {"mean_coverage_at_least": CRIT_MEAN, "p10_coverage_at_least": CRIT_P10}, "models": {}}
    for mkey, pkey in (("active_gatv2", f"gat{tag}_zs"), ("per_node_gbdt", f"gbdt{tag}_zs")):
        probs = d[pkey]
        pred_raw = probs.argmax(axis=1)
        raw_acc_full = round(float((pred_raw == y).mean()), 4)
        is_nf_full = y == nf
        raw_fpr_full = round(float((pred_raw[is_nf_full] != nf).mean()), 4) if is_nf_full.any() else 0.0
        rows, first_ok, first_a3_full = [], None, None
        for frac in FRACTIONS:
            n_b = max(1, int(round(frac * len(fault_buses))))
            n_nf = max(10, int(round(frac * len(nf_idx))))
            rng = np.random.default_rng(0)
            reps = []
            for _ in range(N_DRAWS):
                cb = set(rng.choice(fault_buses, size=n_b, replace=False).tolist())
                cnf = set(rng.choice(nf_idx, size=n_nf, replace=False).tolist())
                cal = np.array([(b in cb) or (i in cnf) for i, b in enumerate(bus)])
                te = ~cal
                q = am.conformal_quantile(am.conformal_scores(probs[cal], y[cal], METHOD, u[cal]), ALPHA)
                reps.append(am.conformal_report(probs[te], y[te], am.conformal_sets(probs[te], q, METHOD, u[te]), nf))
            cov = np.array([r["coverage"] for r in reps])

            def mean(k: str) -> float | None:
                v = [r[k] for r in reps if r[k] is not None]
                return round(float(np.mean(v)), 4) if v else None
            row = {"fraction": frac, "cal_fault_buses": n_b, "cal_nofault_events": n_nf,
                   "coverage_mean": round(float(cov.mean()), 4),
                   "coverage_p10": round(float(np.percentile(cov, 10)), 4),
                   "coverage_min": round(float(cov.min()), 4),
                   "avg_set_size": mean("avg_set_size"), "singleton_share": mean("singleton_share"),
                   "singleton_accuracy": mean("singleton_accuracy"),
                   "raw_argmax_accuracy": mean("raw_argmax_accuracy"),
                   "nofault_autonomous_trip_share": mean("nofault_autonomous_trip_share")}
            cov_ok = bool(row["coverage_mean"] >= CRIT_MEAN and row["coverage_p10"] >= CRIT_P10)
            safer_ok = bool(
                row["singleton_accuracy"] is not None
                and row["raw_argmax_accuracy"] is not None
                and row["singleton_accuracy"] > row["raw_argmax_accuracy"]
                and row["nofault_autonomous_trip_share"] is not None
                and row["nofault_autonomous_trip_share"] < raw_fpr_full
            )
            row["meets_criterion"] = cov_ok
            row["meets_full_a3_recal"] = bool(cov_ok and safer_ok)
            if cov_ok and first_ok is None:
                first_ok = frac
            if row["meets_full_a3_recal"] and first_a3_full is None:
                first_a3_full = frac
            rows.append(row)
            print(f"{mkey:14s} {frac:.0%} ({n_b} buses): cov mean {row['coverage_mean']:.4f} p10 {row['coverage_p10']:.4f} "
                  f"min {row['coverage_min']:.4f} size {row['avg_set_size']} single {row['singleton_share']} "
                  f"acc {row['singleton_accuracy']} trip {row['nofault_autonomous_trip_share']} ok={row['meets_criterion']}")
        out["models"][mkey] = {
            "raw_argmax_accuracy_full": raw_acc_full,
            "raw_nofault_fpr_full": raw_fpr_full,
            "by_fraction": rows,
            "smallest_fraction_meeting_criterion": first_ok,
            "smallest_fraction_meeting_full_a3_recal": first_a3_full,
        }

    summary_dir.mkdir(parents=True, exist_ok=True)
    path = summary_dir / "conformal_calsize.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    provenance.record(producer, [path])


if __name__ == "__main__":
    main()
